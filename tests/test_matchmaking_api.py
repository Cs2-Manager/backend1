"""Pruebas de la API de la sección CS2 MATCHMAKING."""

import io
import os
from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models.matchmaking import (
    MatchmakingAuthorization,
    MatchmakingMatch,
    MatchmakingSyncRun,
)
from app.models.steam import SteamAccount
from app.models.user import User
from app.security import generate_token
from app.services.matchmaking.sharecode import encode_share_code

STEAM_ID = "76561198000000001"
AUTH_CODE = "ABCD-12345-EFGH"
MATCH_ID = (1_700_000_000 << 32) | 0x01020304
SHARE_CODE = encode_share_code(MATCH_ID, 424242, 37020)
MESSAGE = (
    "Este jugador todavía no habilitó la sincronización de sus partidas de "
    "matchmaking oficial."
)


def _register(client, username="matcher", visibility=None):
    response = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "secret123",
        },
    )
    assert response.status_code == 201
    user_id = response.get_json()["user"]["id"]
    user = db.session.get(User, user_id)
    if visibility:
        user.profile.visibility = visibility
        db.session.commit()
    return user


def _link(user, steam_id=STEAM_ID):
    account = SteamAccount(user_id=user.id, steam_id=steam_id)
    db.session.add(account)
    db.session.commit()
    return account


def _headers(user):
    return {"Authorization": f"Bearer {generate_token(user)}"}


def _authorize(client, user):
    return client.post(
        "/api/matchmaking/authorization",
        json={"auth_code": AUTH_CODE, "share_code": SHARE_CODE},
        headers=_headers(user),
    )


def _add_processed_match(user, **overrides):
    payload = {
        "user_id": user.id,
        "share_code": encode_share_code((1_700_000_000 << 32) + 9, 1, 1),
        "match_id": (1_700_000_000 << 32) + 9,
        "map_name": "de_mirage",
        "played_at": datetime.now(timezone.utc) - timedelta(days=1),
        "result": "WIN",
        "team_score": 13,
        "opponent_score": 7,
        "rounds_played": 20,
        "rounds_won": 13,
        "rounds_lost": 7,
        "kills": 20,
        "deaths": 10,
        "assists": 5,
        "damage": 1600,
        "headshot_kills": 8,
        "kast_rounds": 14,
        "mvps": 4,
        "clutches": 1,
        "opening_kills": 3,
        "opening_deaths": 2,
        "adr": 80.0,
        "hs_percentage": 40.0,
        "kd": 2.0,
        "kast_percentage": 70.0,
        "demo_status": "OK",
        "processed_at": datetime.now(timezone.utc),
    }
    payload.update(overrides)
    match = MatchmakingMatch(**payload)
    db.session.add(match)
    db.session.commit()
    return match


def test_status_without_authorization_shows_exact_message(client):
    user = _register(client)

    response = client.get("/api/matchmaking/status", headers=_headers(user))

    assert response.status_code == 200
    section = response.get_json()["matchmaking"]
    assert section["available"] is False
    assert section["authorized"] is False
    assert section["status"] == "UNAVAILABLE"
    assert section["message"] == MESSAGE
    assert section["has_data"] is False
    assert section["summary"]["has_data"] is False
    assert section["recent_matches"] == []
    assert section["authorization"] is None


def test_authorization_requires_linked_steam_account(client):
    user = _register(client)

    response = _authorize(client, user)

    assert response.status_code == 400
    assert "Steam" in response.get_json()["error"]


def test_authorization_rejects_malformed_codes(client):
    user = _register(client)
    _link(user)

    response = client.post(
        "/api/matchmaking/authorization",
        json={"auth_code": "bad", "share_code": SHARE_CODE},
        headers=_headers(user),
    )

    assert response.status_code == 400
    assert "auth_code" in response.get_json()["fields"]


def test_authorization_persists_only_encrypted_code(client):
    user = _register(client)
    _link(user)

    response = _authorize(client, user)

    assert response.status_code == 200
    section = response.get_json()["matchmaking"]
    assert section["available"] is True
    assert section["authorized"] is True
    assert section["status"] == "PROCESSING"
    assert section["authorization"]["status"] == "ACTIVE"
    assert "auth_code" not in response.get_data(as_text=True)
    assert AUTH_CODE not in response.get_data(as_text=True)
    assert "encrypted" not in response.get_data(as_text=True)

    authorization = (
        db.session.query(MatchmakingAuthorization)
        .filter_by(user_id=user.id)
        .one()
    )
    assert authorization.auth_code_encrypted
    assert authorization.auth_code_encrypted != AUTH_CODE
    assert authorization.cursor_share_code == SHARE_CODE

    matches = db.session.query(MatchmakingMatch).filter_by(user_id=user.id).all()
    assert len(matches) == 1
    assert matches[0].demo_status == "AWAITING_DEMO"
    assert matches[0].match_id == MATCH_ID


def test_owner_sees_masked_authorization_code_and_full_match_code(client):
    user = _register(client)
    _link(user)
    _authorize(client, user)

    section = client.get(
        "/api/matchmaking/status", headers=_headers(user)
    ).get_json()["matchmaking"]

    assert section["authorization"]["share_code"].endswith("*****")
    assert section["recent_matches"][0]["share_code"] == SHARE_CODE
    assert section["recent_matches"][0]["status"] == "AWAITING_DEMO"
    assert section["recent_matches"][0]["has_stats"] is False
    assert section["recent_matches"][0]["source"] == "PENDING"


def test_manual_sync_is_queued_once(client):
    user = _register(client)
    _link(user)
    _authorize(client, user)

    first = client.post("/api/matchmaking/sync", headers=_headers(user))
    second = client.post("/api/matchmaking/sync", headers=_headers(user))

    assert first.status_code == 202
    assert first.get_json()["status"] == "QUEUED"
    assert first.get_json()["sync"]["status"] == "RUNNING"
    assert second.status_code == 202
    runs = (
        db.session.query(MatchmakingSyncRun)
        .filter_by(user_id=user.id, kind="MANUAL")
        .all()
    )
    assert len(runs) == 1
    assert runs[0].status == "RUNNING"


def test_sync_requires_authorization(client):
    user = _register(client)

    response = client.post("/api/matchmaking/sync", headers=_headers(user))

    assert response.status_code == 400


def test_sync_requires_configured_steam_api(client, app):
    user = _register(client)
    _link(user)
    _authorize(client, user)
    app.config["STEAM_API_KEY"] = ""

    response = client.post("/api/matchmaking/sync", headers=_headers(user))

    assert response.status_code == 503


def test_revocation_removes_secret_and_keeps_matches(client):
    user = _register(client)
    _link(user)
    _authorize(client, user)
    _add_processed_match(user)

    response = client.delete(
        "/api/matchmaking/authorization", headers=_headers(user)
    )

    assert response.status_code == 200
    section = response.get_json()["matchmaking"]
    assert section["status"] == "REVOKED"
    assert section["authorized"] is False
    assert section["source"] == "VERIFIED_DEMO"
    assert section["summary"]["has_data"] is True

    authorization = (
        db.session.query(MatchmakingAuthorization)
        .filter_by(user_id=user.id)
        .one()
    )
    assert authorization.status == "REVOKED"
    assert authorization.auth_code_encrypted is None
    assert authorization.cursor_share_code is None
    assert authorization.first_share_code is None


def test_history_lists_processed_matches_with_aggregates(client):
    user = _register(client)
    _link(user)
    _authorize(client, user)
    _add_processed_match(user)

    status = client.get(
        "/api/matchmaking/status", headers=_headers(user)
    ).get_json()["matchmaking"]
    listing = client.get(
        "/api/matchmaking/matches", headers=_headers(user)
    ).get_json()

    assert status["has_data"] is True
    assert status["status"] == "PARTIAL"  # queda 1 partida sin demo
    assert status["summary"]["matches_played"] == 1
    assert status["summary"]["kd"] == 2.0
    assert status["summary"]["adr"] == 80.0
    assert status["map_performance"][0]["map"] == "de_mirage"

    assert listing["count"] >= 1
    processed = [m for m in listing["matches"] if m["status"] == "OK"]
    assert processed[0]["has_stats"] is True
    assert processed[0]["source"] == "VERIFIED_DEMO"
    assert processed[0]["kills"] == 20


def test_match_detail_is_scoped_to_owner(client):
    owner = _register(client, "owner")
    other = _register(client, "other")
    _link(owner)
    _authorize(client, owner)
    match = _add_processed_match(owner)

    own = client.get(
        f"/api/matchmaking/matches/{match.id}", headers=_headers(owner)
    )
    foreign = client.get(
        f"/api/matchmaking/matches/{match.id}", headers=_headers(other)
    )

    assert own.status_code == 200
    assert own.get_json()["match"]["map"] == "de_mirage"
    assert foreign.status_code == 404


def test_upload_requires_active_authorization(client, app, tmp_path):
    app.config["MATCHMAKING_STORAGE_DIR"] = str(tmp_path / "mm")
    app.config["MATCHMAKING_INBOX_DIR"] = str(tmp_path / "mm" / "inbox")
    user = _register(client)

    response = client.post(
        "/api/matchmaking/demos",
        data={"demo": (io.BytesIO(b"demo"), "match730_1_1.dem")},
        content_type="multipart/form-data",
        headers=_headers(user),
    )

    assert response.status_code == 400


def test_upload_rejects_invalid_extension(client, app, tmp_path):
    app.config["MATCHMAKING_STORAGE_DIR"] = str(tmp_path / "mm")
    app.config["MATCHMAKING_INBOX_DIR"] = str(tmp_path / "mm" / "inbox")
    user = _register(client)
    _link(user)
    _authorize(client, user)

    response = client.post(
        "/api/matchmaking/demos",
        data={"demo": (io.BytesIO(b"not a demo"), "notes.txt")},
        content_type="multipart/form-data",
        headers=_headers(user),
    )

    assert response.status_code == 400


def test_upload_stores_demo_in_user_inbox(client, app, tmp_path):
    app.config["MATCHMAKING_STORAGE_DIR"] = str(tmp_path / "mm")
    app.config["MATCHMAKING_INBOX_DIR"] = str(tmp_path / "mm" / "inbox")
    user = _register(client)
    _link(user)
    _authorize(client, user)

    response = client.post(
        "/api/matchmaking/demos",
        data={"demo": (io.BytesIO(b"fake demo bytes"), "match730_1_2.dem")},
        content_type="multipart/form-data",
        headers=_headers(user),
    )

    assert response.status_code == 202
    body = response.get_json()
    assert body["status"] == "QUEUED"
    inbox = os.path.join(str(tmp_path / "mm" / "inbox"), str(user.id))
    assert len(os.listdir(inbox)) == 1


def test_revoked_authorization_cannot_upload(client, app, tmp_path):
    app.config["MATCHMAKING_STORAGE_DIR"] = str(tmp_path / "mm")
    app.config["MATCHMAKING_INBOX_DIR"] = str(tmp_path / "mm" / "inbox")
    user = _register(client)
    _link(user)
    _authorize(client, user)
    client.delete("/api/matchmaking/authorization", headers=_headers(user))

    response = client.post(
        "/api/matchmaking/demos",
        data={"demo": (io.BytesIO(b"demo"), "match123.dem")},
        content_type="multipart/form-data",
        headers=_headers(user),
    )

    assert response.status_code == 400


def test_public_profile_never_exposes_codes_or_errors(client):
    user = _register(client, "public", visibility="PUBLIC")
    _link(user)
    _authorize(client, user)
    _add_processed_match(user)

    response = client.get(f"/api/players/{user.id}")

    assert response.status_code == 200
    section = response.get_json()["profile"]["matchmaking"]
    assert section["available"] is True
    assert section["summary"]["has_data"] is True
    assert section["recent_matches"][0]["share_code"].endswith("*****")
    body = response.get_data(as_text=True)
    assert SHARE_CODE not in body
    assert AUTH_CODE not in body
    assert "demo_sha256" not in body
    assert "processing_error" not in body
    assert "last_sync_error" not in body


def test_public_profile_shows_message_without_authorization(client):
    user = _register(client, "public2", visibility="PUBLIC")

    response = client.get(f"/api/players/{user.id}")

    section = response.get_json()["profile"]["matchmaking"]
    assert section["status"] == "UNAVAILABLE"
    assert section["message"] == MESSAGE


def test_section_reports_server_switch(client, app):
    user = _register(client, "disabled")
    app.config["MATCHMAKING_ENABLED"] = False

    response = client.get("/api/matchmaking/status", headers=_headers(user))

    assert response.status_code == 200
    assert response.get_json()["matchmaking"]["enabled"] is False


def test_profile_provenance_marks_demo_source(client):
    user = _register(client, "provenance", visibility="PUBLIC")
    _link(user)
    _authorize(client, user)
    _add_processed_match(user)

    response = client.get(f"/api/players/{user.id}")

    provenance = response.get_json()["profile"]["provenance"]
    assert provenance["cs2_player_stats"] == "VERIFIED_DEMO"
    assert provenance["cs2_match_history"] == "VERIFIED_DEMO"
    assert provenance["manual_stats"] == "UNAVAILABLE"
