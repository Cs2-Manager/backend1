"""Pruebas de sincronización de datos verificados de Steam."""

from app.extensions import db
from app.models.steam import SteamAccount, SteamGameStats
from app.models.user import User
from app.security import generate_token, hash_password
from app.services import steam_api

STEAM_ID = "76561198000000001"


def _create_user(username="syncer"):
    user = User(
        username=username,
        email=f"{username}@example.com",
        password_hash=hash_password("secret123"),
    )
    db.session.add(user)
    db.session.commit()
    return user


def _link(user):
    account = SteamAccount(user_id=user.id, steam_id=STEAM_ID)
    db.session.add(account)
    db.session.commit()
    return account


def _headers(user):
    return {"Authorization": f"Bearer {generate_token(user)}"}


def _summary(**overrides):
    payload = {
        "steam_id": STEAM_ID,
        "persona_name": "Syncer",
        "profile_url": f"https://steamcommunity.com/profiles/{STEAM_ID}",
        "avatar_url": "https://cdn.example/avatar.jpg",
        "avatar_medium_url": "https://cdn.example/avatar_medium.jpg",
        "avatar_full_url": "https://cdn.example/avatar_full.jpg",
        "persona_state": 1,
        "community_visibility_state": 3,
        "profile_created_at": 1600000000,
        "last_logoff_at": 1700000000,
    }
    payload.update(overrides)
    return payload


def _owned(minutes=4200, two_weeks=120):
    return {
        "game_count": 1,
        "games": [
            {
                "app_id": 730,
                "name": "Counter-Strike 2",
                "playtime_forever_minutes": minutes,
                "playtime_two_weeks_minutes": two_weeks,
                "last_played": 1700000000,
                "img_icon_url": "abc123",
            }
        ],
    }


def test_sync_requires_linked_account(client):
    user = _create_user()
    response = client.post("/api/steam/sync", headers=_headers(user))
    assert response.status_code == 404


def test_sync_requires_configuration(client, app, monkeypatch):
    user = _create_user()
    _link(user)
    app.config["STEAM_API_KEY"] = ""

    response = client.post("/api/steam/sync", headers=_headers(user))
    assert response.status_code == 503


def test_sync_persists_only_verified_steam_data(client, app, monkeypatch):
    app.config["STEAM_SYNC_MIN_INTERVAL_SECONDS"] = 0
    user = _create_user()
    account = _link(user)

    monkeypatch.setattr(
        steam_api, "fetch_player_summaries", lambda _steam_id: _summary()
    )
    monkeypatch.setattr(
        steam_api,
        "fetch_owned_games",
        lambda _steam_id, app_id=730: _owned(minutes=5000),
    )

    response = client.post("/api/steam/sync", headers=_headers(user))
    assert response.status_code == 200
    body = response.get_json()

    db.session.expire_all()
    account = db.session.query(SteamAccount).one()
    stat = db.session.query(SteamGameStats).one()

    assert body["sync"]["status"] == "OK"
    assert body["steam"]["linked"] is True
    assert body["steam"]["cs2"]["source"] == "VERIFIED_STEAM"
    assert body["steam"]["cs2"]["playtime_forever_minutes"] == 5000
    assert body["steam"]["cs2"]["stats_available"] is False
    assert body["steam"]["cs2"]["matches_available"] is False
    assert account.last_sync_at is not None
    assert account.last_sync_status == "OK"
    assert stat.app_id == 730
    assert stat.playtime_forever_minutes == 5000
    assert stat.source == "VERIFIED_STEAM"


def test_sync_updates_without_duplicating_stats(client, app, monkeypatch):
    app.config["STEAM_SYNC_MIN_INTERVAL_SECONDS"] = 0
    user = _create_user()
    _link(user)

    monkeypatch.setattr(
        steam_api, "fetch_player_summaries", lambda _steam_id: _summary()
    )
    monkeypatch.setattr(
        steam_api,
        "fetch_owned_games",
        lambda _steam_id, app_id=730: _owned(minutes=1),
    )

    assert client.post("/api/steam/sync", headers=_headers(user)).status_code == 200
    monkeypatch.setattr(
        steam_api,
        "fetch_owned_games",
        lambda _steam_id, app_id=730: _owned(minutes=99),
    )
    assert client.post("/api/steam/sync", headers=_headers(user)).status_code == 200

    db.session.expire_all()
    assert db.session.query(SteamGameStats).count() == 1
    assert db.session.query(SteamGameStats).one().playtime_forever_minutes == 99


def test_private_library_removes_cached_playtime(client, app, monkeypatch):
    app.config["STEAM_SYNC_MIN_INTERVAL_SECONDS"] = 0
    user = _create_user()
    _link(user)

    monkeypatch.setattr(
        steam_api, "fetch_player_summaries", lambda _steam_id: _summary()
    )
    monkeypatch.setattr(
        steam_api,
        "fetch_owned_games",
        lambda _steam_id, app_id=730: _owned(),
    )
    client.post("/api/steam/sync", headers=_headers(user))
    assert db.session.query(SteamGameStats).count() == 1

    monkeypatch.setattr(
        steam_api,
        "fetch_owned_games",
        lambda _steam_id, app_id=730: None,
    )
    response = client.post("/api/steam/sync", headers=_headers(user))
    body = response.get_json()

    db.session.expire_all()
    assert db.session.query(SteamGameStats).count() == 0
    assert body["sync"]["status"] == "PARTIAL"
    assert body["steam"]["cs2"]["playtime_available"] is False
    assert "no es pública" in body["sync"]["message"]


def test_partial_sync_when_owned_games_fails(client, app, monkeypatch):
    app.config["STEAM_SYNC_MIN_INTERVAL_SECONDS"] = 0
    user = _create_user()
    _link(user)

    monkeypatch.setattr(
        steam_api, "fetch_player_summaries", lambda _steam_id: _summary()
    )

    def fake_owned(_steam_id, app_id=730):
        raise steam_api.SteamApiError("timeout", code="unavailable")

    monkeypatch.setattr(steam_api, "fetch_owned_games", fake_owned)

    response = client.post("/api/steam/sync", headers=_headers(user))
    body = response.get_json()
    assert body["sync"]["status"] == "PARTIAL"
    assert body["sync"]["error_code"] == "unavailable"

    db.session.expire_all()
    account = db.session.query(SteamAccount).one()
    assert account.last_sync_status == "PARTIAL"
    assert "timeout" in account.last_sync_error


def test_failed_sync_can_be_retried(client, app, monkeypatch):
    app.config["STEAM_SYNC_MIN_INTERVAL_SECONDS"] = 0
    user = _create_user()
    _link(user)

    def failing_summary(_steam_id):
        raise steam_api.SteamApiError("offline", code="unavailable")

    monkeypatch.setattr(
        steam_api, "fetch_player_summaries", failing_summary
    )
    failed = client.post("/api/steam/sync", headers=_headers(user))
    assert failed.status_code == 200
    assert failed.get_json()["sync"]["status"] == "ERROR"

    db.session.expire_all()
    account = db.session.query(SteamAccount).one()
    assert account.last_sync_status == "ERROR"
    assert account.last_sync_at is not None

    monkeypatch.setattr(
        steam_api, "fetch_player_summaries", lambda _steam_id: _summary()
    )
    monkeypatch.setattr(
        steam_api,
        "fetch_owned_games",
        lambda _steam_id, app_id=730: _owned(),
    )
    retried = client.post("/api/steam/sync", headers=_headers(user))
    assert retried.get_json()["sync"]["status"] == "OK"

    db.session.expire_all()
    assert db.session.query(SteamAccount).one().last_sync_status == "OK"


def test_sync_respects_minimum_interval(client, app, monkeypatch):
    app.config["STEAM_SYNC_MIN_INTERVAL_SECONDS"] = 300
    user = _create_user()
    _link(user)
    calls = {"summaries": 0}

    def summary(_steam_id):
        calls["summaries"] += 1
        return _summary()

    monkeypatch.setattr(
        steam_api, "fetch_player_summaries", summary
    )
    monkeypatch.setattr(
        steam_api,
        "fetch_owned_games",
        lambda _steam_id, app_id=730: _owned(),
    )

    assert client.post("/api/steam/sync", headers=_headers(user)).status_code == 200
    second = client.post("/api/steam/sync", headers=_headers(user))
    body = second.get_json()

    assert body["sync"]["status"] == "SKIPPED"
    assert body["sync"]["retry_after_seconds"] >= 1
    assert calls["summaries"] == 1


def test_status_exposes_last_sync_timestamp(client, app, monkeypatch):
    app.config["STEAM_SYNC_MIN_INTERVAL_SECONDS"] = 0
    user = _create_user()
    _link(user)
    monkeypatch.setattr(
        steam_api, "fetch_player_summaries", lambda _steam_id: _summary()
    )
    monkeypatch.setattr(
        steam_api,
        "fetch_owned_games",
        lambda _steam_id, app_id=730: _owned(),
    )
    client.post("/api/steam/sync", headers=_headers(user))

    response = client.get("/api/steam/status", headers=_headers(user))
    body = response.get_json()["steam"]
    assert response.status_code == 200
    assert body["sync"]["status"] == "OK"
    assert body["sync"]["last_sync_at"]
    assert body["account"]["last_sync_at"]
