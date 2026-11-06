"""Pruebas del worker de matchmaking (sin demos reales)."""

import os
from datetime import datetime, timedelta, timezone

import pytest

from app.extensions import db
from app.models.matchmaking import (
    MatchmakingAuthorization,
    MatchmakingDemoJob,
    MatchmakingMapStats,
    MatchmakingMatch,
    MatchmakingSyncRun,
)
from app.models.steam import SteamAccount
from app.models.user import User
from app.security import hash_password
from app.services.matchmaking import crypto
from app.services.matchmaking.demo_parser import DemoParseError
from app.services.matchmaking.sharecode import encode_share_code
from app.services.matchmaking_service import enqueue_ingested_demo
from app.worker import matchmaking as worker

STEAM_ID = "76561198000000001"
MATCH_ID = (1_700_000_000 << 32) | 0x00AABBCC
KNOWN = encode_share_code(MATCH_ID, 10, 1)
NEXT = encode_share_code((1_700_000_000 << 32) + 5, 20, 1)


@pytest.fixture()
def storage_dirs(app, tmp_path):
    root = tmp_path / "matchmaking"
    app.config["MATCHMAKING_STORAGE_DIR"] = str(root)
    app.config["MATCHMAKING_INBOX_DIR"] = str(root / "inbox")
    (root / "demos").mkdir(parents=True)
    (root / "inbox").mkdir(parents=True)
    return root


def _user(username="worker"):
    user = User(
        username=username,
        email=f"{username}@example.com",
        password_hash=hash_password("secret123"),
    )
    db.session.add(user)
    db.session.commit()
    db.session.add(SteamAccount(user_id=user.id, steam_id=STEAM_ID))
    db.session.commit()
    return user


def _authorization(user):
    authorization = MatchmakingAuthorization(
        user_id=user.id,
        steam_id=STEAM_ID,
        auth_code_encrypted=crypto.encrypt_secret("ABCD-12345-EFGH"),
        first_share_code=KNOWN,
        cursor_share_code=KNOWN,
        status="ACTIVE",
    )
    db.session.add(authorization)
    db.session.commit()
    return authorization


def _match(user, *, status="QUEUED", **overrides):
    payload = {
        "user_id": user.id,
        "share_code": KNOWN,
        "match_id": MATCH_ID,
        "played_at": datetime.now(timezone.utc) - timedelta(days=2),
        "demo_status": status,
    }
    payload.update(overrides)
    match = MatchmakingMatch(**payload)
    db.session.add(match)
    db.session.commit()
    return match


def _job(match, path, sha="a" * 64, name="match730_1_1.dem"):
    job = MatchmakingDemoJob(
        user_id=match.user_id,
        match_id=match.id,
        file_path=str(path),
        original_name=name,
        sha256=sha,
        size_bytes=10,
        status="QUEUED",
        attempts=0,
    )
    db.session.add(job)
    db.session.commit()
    return job


def _summary():
    return {
        "map_name": "de_mirage",
        "played_at": None,
        "team_sizes": {"CT": 5, "T": 5},
        "rounds": [
            {"number": 0, "winner": "CT", "player_team": "CT"},
            {"number": 1, "winner": "CT", "player_team": "CT"},
        ],
        "deaths": [
            {
                "round": 0,
                "tick": 100,
                "victim": "76561198000000099",
                "attacker": STEAM_ID,
                "assister": None,
                "headshot": True,
                "victim_team": "T",
                "attacker_team": "CT",
            }
        ],
        "hurts": [
            {
                "round": 0,
                "tick": 90,
                "attacker": STEAM_ID,
                "victim": "76561198000000099",
                "damage": 100,
            }
        ],
        "mvps": [{"round": 0, "steam_id": STEAM_ID}],
        "fallback_mvps": 0,
    }


def test_process_pending_job_persists_stats(app, storage_dirs, monkeypatch):
    user = _user()
    match = _match(user)
    demo = storage_dirs / "demos" / "demo.dem"
    demo.write_bytes(b"fake demo")
    job = _job(match, demo)
    monkeypatch.setattr(
        worker.demo_parser, "parse_demo", lambda *a, **k: _summary()
    )

    processed = worker.process_pending_jobs()

    assert processed == 1
    db.session.refresh(job)
    db.session.refresh(match)
    assert job.status == "OK"
    assert match.demo_status == "OK"
    assert match.map_name == "de_mirage"
    assert match.kills == 1
    assert match.deaths == 0
    assert match.rounds_played == 2
    assert match.result == "WIN"
    assert match.adr == 50.0
    assert match.hs_percentage == 100.0
    assert match.processed_at is not None

    map_stats = (
        db.session.query(MatchmakingMapStats)
        .filter_by(user_id=user.id, map_name="de_mirage")
        .one()
    )
    assert map_stats.matches == 1
    assert map_stats.kills == 1


def test_failed_demo_is_retried_then_marked_error(app, storage_dirs, monkeypatch):
    app.config["MATCHMAKING_MAX_ATTEMPTS"] = 2
    user = _user("retry")
    match = _match(user)
    demo = storage_dirs / "demos" / "broken.dem"
    demo.write_bytes(b"broken")
    job = _job(match, demo, sha="b" * 64)

    def fail(*_args, **_kwargs):
        raise DemoParseError("Demo corrupta o ilegible")

    monkeypatch.setattr(worker.demo_parser, "parse_demo", fail)

    assert worker.process_pending_jobs() == 0
    db.session.refresh(job)
    db.session.refresh(match)
    assert job.status == "QUEUED"
    assert job.attempts == 1
    assert job.next_attempt_at is not None
    assert match.demo_status == "QUEUED"
    assert "corrupta" in match.processing_error

    # Fuerza el vencimiento del backoff y ejecuta la segunda pasada.
    job.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.session.commit()

    assert worker.process_pending_jobs() == 0
    db.session.refresh(job)
    db.session.refresh(match)
    assert job.status == "ERROR"
    assert job.attempts == 2
    assert match.demo_status == "ERROR"
    assert "corrupta" in match.processing_error


def test_same_demo_hash_is_not_processed_twice(app, storage_dirs):
    user = _user("dedupe")
    _authorization(user)
    inbox = storage_dirs / "inbox" / str(user.id)
    inbox.mkdir(parents=True)
    content = b"identical demo"
    (inbox / "a.dem").write_bytes(content)

    assert worker.scan_inbox() == 1
    assert db.session.query(MatchmakingDemoJob).count() == 1
    jobs = db.session.query(MatchmakingDemoJob).all()
    first_path = jobs[0].file_path
    assert os.path.isfile(first_path)

    # El mismo contenido subido otra vez se detecta por SHA-256.
    (inbox / "b.dem").write_bytes(content)
    assert worker.scan_inbox() == 0
    assert db.session.query(MatchmakingDemoJob).count() == 1
    assert not os.path.exists(str(inbox / "b.dem"))


def test_second_demo_for_processed_match_is_duplicate(app, storage_dirs):
    user = _user("duplicate")
    match = _match(user, status="OK", demo_sha256="c" * 64)
    info = {
        "user_id": user.id,
        "path": str(storage_dirs / "demos" / "other.dem"),
        "original_name": f"match730_{MATCH_ID}_1700000000.dem",
        "sha256": "d" * 64,
        "size_bytes": 10,
        "duplicate": False,
    }

    job, created = enqueue_ingested_demo(info)

    assert created is False
    assert job.status == "DUPLICATE"
    db.session.refresh(match)
    assert match.demo_status == "OK"


def test_manual_run_discovers_and_registers_codes(app, monkeypatch):
    user = _user("manual")
    authorization = _authorization(user)
    run = MatchmakingSyncRun(
        user_id=user.id,
        kind="MANUAL",
        status="RUNNING",
        started_at=datetime.now(timezone.utc),
    )
    db.session.add(run)
    db.session.commit()
    monkeypatch.setattr(
        worker.discovery, "get_next_share_code", lambda *a: NEXT
    )

    assert worker.process_manual_sync_runs() == 1

    db.session.refresh(run)
    db.session.refresh(authorization)
    assert run.status == "OK"
    assert run.found == 1
    assert authorization.cursor_share_code == NEXT
    assert authorization.last_discovery_status == "OK"
    discovered = (
        db.session.query(MatchmakingMatch)
        .filter_by(user_id=user.id, share_code=NEXT)
        .one()
    )
    assert discovered.demo_status == "AWAITING_DEMO"


def test_manual_run_marks_error_when_discovery_fails(app, monkeypatch):
    user = _user("manual-fail")
    authorization = _authorization(user)
    run = MatchmakingSyncRun(
        user_id=user.id,
        kind="MANUAL",
        status="RUNNING",
        started_at=datetime.now(timezone.utc),
    )
    db.session.add(run)
    db.session.commit()

    def fail(*_args):
        from app.services.matchmaking.discovery import DiscoveryError

        raise DiscoveryError("Steam respondió HTTP 500", code="http_error")

    monkeypatch.setattr(worker.discovery, "get_next_share_code", fail)

    assert worker.process_manual_sync_runs() == 1

    db.session.refresh(run)
    db.session.refresh(authorization)
    assert run.status == "ERROR"
    assert run.failed == 1
    assert authorization.last_discovery_status == "ERROR"
    assert authorization.status == "ACTIVE"


def test_invalid_auth_code_invalidates_authorization(app, monkeypatch):
    user = _user("invalid")
    authorization = _authorization(user)

    def fail(*_args):
        from app.services.matchmaking.discovery import DiscoveryError

        raise DiscoveryError("rechazado", code="invalid_auth_code")

    monkeypatch.setattr(worker.discovery, "get_next_share_code", fail)

    outcome = worker.discover_authorization(authorization)

    db.session.refresh(authorization)
    assert outcome.status == "ERROR"
    assert authorization.status == "INVALID"
    assert authorization.auth_code_encrypted is None


def test_expired_demo_is_marked_unavailable(app, storage_dirs):
    user = _user("expired")
    match = _match(
        user,
        status="AWAITING_DEMO",
        played_at=datetime.now(timezone.utc) - timedelta(days=45),
    )

    assert worker.mark_expired_demos() == 1

    db.session.refresh(match)
    assert match.demo_status == "UNAVAILABLE"
    assert "no está disponible" in match.processing_error


def test_run_once_is_safe_without_pending_work(app, storage_dirs):
    result = worker.run_once()

    assert result == {
        "manual_runs": 0,
        "discoveries": 0,
        "ingested": 0,
        "jobs": 0,
        "expired": 0,
        # FACEIT se integra en el mismo worker; sin cuentas vencidas no
        # realiza ninguna llamada externa.
        "faceit": {"synced": 0, "skipped": 0, "errors": 0, "status": "OK"},
    }
