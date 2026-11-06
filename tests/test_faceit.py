"""Pruebas de la integración verificada con FACEIT.

Cubren descubrimiento por SteamID, vinculación OAuth2 con PKCE, sincronización
idempotente, procedencia explícita, privacidad entre usuarios y ausencia de
secretos en las respuestas.
"""

from urllib.parse import parse_qs, urlparse

from app.extensions import db
from app.models.faceit import (
    FaceitAccount,
    FaceitEloSnapshot,
    FaceitMapStats,
    FaceitMatch,
    FaceitOAuthRequest,
    FaceitPlayerStats,
    FaceitSyncState,
)
from app.models.steam import SteamAccount
from app.models.user import User
from app.security import generate_token, hash_password
from app.services import faceit_api, faceit_service

STEAM_ID = "76561198000000001"
PLAYER_ID = "faceit-player-1"


def _create_user(username="faceit-user"):
    user = User(
        username=username,
        email=f"{username}@example.com",
        password_hash=hash_password("secret123"),
    )
    db.session.add(user)
    db.session.commit()
    return user


def _link_steam(user, steam_id=STEAM_ID):
    account = SteamAccount(user_id=user.id, steam_id=steam_id)
    db.session.add(account)
    db.session.commit()
    return account


def _link_faceit(user, *, player_id=PLAYER_ID, verified=False):
    account = FaceitAccount(
        user_id=user.id,
        faceit_player_id=player_id,
        nickname="FaceitUser",
        link_status="VERIFIED" if verified else "DISCOVERED",
        verification_source="OAUTH2" if verified else "STEAM_DISCOVERY",
        steam_id=STEAM_ID,
        elo=2100,
        skill_level=9,
    )
    db.session.add(account)
    db.session.flush()
    db.session.add(FaceitSyncState(account_id=account.id, status="NEVER"))
    db.session.commit()
    return account


def _headers(user):
    return {"Authorization": f"Bearer {generate_token(user)}"}


def _player(**overrides):
    payload = {
        "player_id": PLAYER_ID,
        "nickname": "FaceitUser",
        "avatar_url": "https://cdn.example/avatar.jpg",
        "cover_image_url": "https://cdn.example/cover.jpg",
        "country": "ar",
        "region": "SA",
        "steam_id": STEAM_ID,
        "steam_nickname": "SteamUser",
        "faceit_url": f"https://www.faceit.com/en/players/{PLAYER_ID}",
        "elo": 2100,
        "skill_level": 9,
    }
    payload.update(overrides)
    return payload


def _stats_payload():
    return {
        "player_id": PLAYER_ID,
        "game_id": "cs2",
        "lifetime": {
            "Total Matches": "120",
            "Total Wins": "70",
            "Total Losses": "50",
            "Win Rate %": "58",
            "Total Kills": "2400",
            "Total Deaths": "1800",
            "Total Assists": "500",
            "K/D Ratio": "1.33",
            "K/R Ratio": "0.79",
            "Total Headshots": "1100",
            "Headshots %": "46",
            "ADR": "82.4",
            "MVPs": "220",
            "Triple Kills": "30",
            "Quadro Kills": "4",
            "Penta Kills": "1",
            "Total Rounds": "2700",
            "Total Damage": "220000",
        },
        "segments": [
            {
                "type": "Map",
                "label": "de_mirage",
                "stats": {
                    "Matches": "40",
                    "Wins": "25",
                    "Losses": "15",
                    "Win Rate %": "62.5",
                    "Kills": "820",
                    "Deaths": "600",
                    "Assists": "170",
                    "K/D Ratio": "1.37",
                    "ADR": "85.1",
                    "Headshots %": "48",
                },
            }
        ],
    }


def _game_stats_payload():
    return {
        "items": [
            {
                "faceit_url": f"https://www.faceit.com/en/cs2/room/1-abc",
                "stats": {
                    "Match Id": "1-abc",
                    "Map": "de_mirage",
                    "Game Mode": "5v5",
                    "Region": "SA",
                    "Result": "1",
                    "Score": "13 / 7",
                    "Kills": "22",
                    "Deaths": "14",
                    "Assists": "4",
                    "K/D Ratio": "1.57",
                    "K/R Ratio": "0.88",
                    "ADR": "91.2",
                    "Headshots %": "52",
                    "MVPs": "4",
                    "Rounds": "20",
                    "Match Finished At": "1730000000000",
                },
            }
        ]
    }


def _history_payload():
    return {
        "items": [
            {
                "match_id": "1-abc",
                "game_mode": "5v5",
                "region": "SA",
                "competition_name": "Ranked",
                "finished_at": 1730000000,
                "teams": {
                    "faction1": {
                        "nickname": "Our Team",
                        "players": [{"player_id": PLAYER_ID}],
                    },
                    "faction2": {
                        "nickname": "Enemy Team",
                        "players": [{"player_id": "other"}],
                    },
                },
                "results": {
                    "winner": "faction1",
                    "score": {"faction1": 13, "faction2": 7},
                },
                "faceit_url": "https://www.faceit.com/en/cs2/room/1-abc",
            },
            {
                "match_id": "1-def",
                "game_mode": "5v5",
                "region": "SA",
                "finished_at": 1729000000,
                "teams": {
                    "faction1": {
                        "nickname": "Our Team",
                        "players": [{"player_id": PLAYER_ID}],
                    },
                    "faction2": {
                        "nickname": "Enemy Team",
                        "players": [{"player_id": "other"}],
                    },
                },
                "results": {
                    "winner": "faction2",
                    "score": {"faction1": 9, "faction2": 13},
                },
            },
        ]
    }


def _patch_sync(monkeypatch):
    monkeypatch.setattr(
        faceit_api, "fetch_player", lambda _pid: _player()
    )
    monkeypatch.setattr(
        faceit_api, "fetch_player_stats", lambda _pid: _stats_payload()
    )
    monkeypatch.setattr(
        faceit_api,
        "fetch_player_game_stats",
        lambda _pid, **_kwargs: _game_stats_payload(),
    )
    monkeypatch.setattr(
        faceit_api,
        "fetch_player_history",
        lambda _pid, **_kwargs: _history_payload(),
    )


def test_status_requires_authentication(client):
    assert client.get("/api/faceit/status").status_code == 401


def test_status_without_account_is_explicit_and_configured(client):
    user = _create_user()
    response = client.get("/api/faceit/status", headers=_headers(user))
    body = response.get_json()["faceit"]

    assert response.status_code == 200
    assert body["linked"] is False
    assert body["configured"] is True
    assert body["oauth_configured"] is True
    assert body["account"] is None
    assert body["stats"]["available"] is False
    assert body["stats"]["source"] == "UNAVAILABLE"
    assert body["message"]


def test_status_does_not_leak_secrets(client, app):
    app.config["FACEIT_API_KEY"] = "super-secret-api-key"
    app.config["FACEIT_OAUTH_CLIENT_SECRET"] = "super-secret-client"
    user = _create_user()
    _link_faceit(user)

    raw = client.get("/api/faceit/status", headers=_headers(user)).get_data(
        as_text=True
    )
    assert "super-secret-api-key" not in raw
    assert "super-secret-client" not in raw


def test_discover_requires_verified_steam(client):
    user = _create_user()
    response = client.post("/api/faceit/discover", headers=_headers(user))

    assert response.status_code == 409
    assert "Steam" in response.get_json()["error"]


def test_discover_reports_not_found_without_claiming(client, monkeypatch):
    user = _create_user()
    _link_steam(user)

    def missing(_steam_id):
        raise faceit_api.FaceitApiError("missing", code="not_found")

    monkeypatch.setattr(faceit_api, "fetch_player_by_steam_id", missing)
    response = client.post("/api/faceit/discover", headers=_headers(user))
    body = response.get_json()["discovery"]

    assert response.status_code == 200
    assert body["found"] is False
    assert body["linked"] is False
    assert db.session.query(FaceitAccount).count() == 0


def test_discover_and_link_persist_verified_identity(client, monkeypatch):
    user = _create_user()
    _link_steam(user)
    monkeypatch.setattr(
        faceit_api,
        "fetch_player_by_steam_id",
        lambda _steam_id: _player(),
    )

    discovered = client.post(
        "/api/faceit/discover", headers=_headers(user)
    ).get_json()["discovery"]
    assert discovered["found"] is True
    assert discovered["linked"] is False
    assert discovered["claimed"] is False

    response = client.post("/api/faceit/link", headers=_headers(user))
    body = response.get_json()["faceit"]

    assert response.status_code == 200
    assert body["linked"] is True
    assert body["account"]["player_id"] == PLAYER_ID
    assert body["account"]["verified"] is False
    assert body["account"]["verification_source"] == "STEAM_DISCOVERY"

    db.session.expire_all()
    account = db.session.query(FaceitAccount).one()
    assert account.user_id == user.id
    assert account.steam_id == STEAM_ID
    assert account.elo == 2100
    assert db.session.query(FaceitSyncState).one().status == "NEVER"


def test_discover_never_exposes_account_owned_by_another_user(
    client, monkeypatch
):
    owner = _create_user("owner")
    intruder = _create_user("intruder")
    _link_steam(owner)
    _link_steam(intruder, steam_id="76561198000000002")
    _link_faceit(owner)
    monkeypatch.setattr(
        faceit_api,
        "fetch_player_by_steam_id",
        lambda _steam_id: _player(),
    )

    body = client.post(
        "/api/faceit/discover", headers=_headers(intruder)
    ).get_json()["discovery"]

    assert body["found"] is True
    assert body["claimed"] is True
    assert body["linked"] is False
    assert body["player"] is not None
    assert "otro usuario" in body["message"]

    link = client.post("/api/faceit/link", headers=_headers(intruder))
    assert link.status_code == 409


def test_link_rejects_player_id_mismatch(client, monkeypatch):
    user = _create_user()
    _link_steam(user)
    monkeypatch.setattr(
        faceit_api,
        "fetch_player_by_steam_id",
        lambda _steam_id: _player(),
    )

    response = client.post(
        "/api/faceit/link",
        json={"player_id": "another-player"},
        headers=_headers(user),
    )
    assert response.status_code == 400


def test_sync_persists_stats_matches_maps_and_elo(
    client, app, monkeypatch
):
    app.config["FACEIT_SYNC_MIN_INTERVAL_SECONDS"] = 0
    user = _create_user()
    _link_faceit(user)
    _patch_sync(monkeypatch)

    response = client.post("/api/faceit/sync", headers=_headers(user))
    body = response.get_json()

    assert response.status_code == 200
    assert body["status"] in ("OK", "PARTIAL")
    assert body["faceit"]["stats"]["available"] is True
    assert body["faceit"]["stats"]["matches_played"] == 120
    assert body["faceit"]["stats"]["kd"] == 1.33
    assert body["faceit"]["stats"]["source"] == "VERIFIED_FACEIT"

    db.session.expire_all()
    stats = db.session.query(FaceitPlayerStats).one()
    assert stats.matches_played == 120
    assert stats.headshot_percentage == 46.0
    assert db.session.query(FaceitMatch).count() == 2
    match = (
        db.session.query(FaceitMatch)
        .filter_by(faceit_match_id="1-abc")
        .one()
    )
    assert match.map_name == "de_mirage"
    assert match.result == "WIN"
    assert match.team_score == 13
    assert match.player_stats.kills == 22
    map_stats = (
        db.session.query(FaceitMapStats).filter_by(map_name="de_mirage").one()
    )
    assert map_stats.matches_played == 40
    assert map_stats.calculated_from == "FACEIT_SEGMENT"
    assert db.session.query(FaceitEloSnapshot).count() == 1
    assert (
        db.session.query(FaceitSyncState).one().status == body["status"]
    )


def test_sync_is_idempotent_and_updates_in_place(client, app, monkeypatch):
    app.config["FACEIT_SYNC_MIN_INTERVAL_SECONDS"] = 0
    user = _create_user()
    _link_faceit(user)
    _patch_sync(monkeypatch)

    assert (
        client.post("/api/faceit/sync", headers=_headers(user)).status_code
        == 200
    )
    assert (
        client.post("/api/faceit/sync", headers=_headers(user)).status_code
        == 200
    )

    db.session.expire_all()
    assert db.session.query(FaceitMatch).count() == 2
    assert db.session.query(FaceitPlayerStats).count() == 1
    assert db.session.query(FaceitMapStats).count() == 1
    # El ELO no cambió: no se duplican snapshots.
    assert db.session.query(FaceitEloSnapshot).count() == 1


def test_sync_partial_when_some_endpoints_fail(client, app, monkeypatch):
    app.config["FACEIT_SYNC_MIN_INTERVAL_SECONDS"] = 0
    user = _create_user()
    _link_faceit(user)
    monkeypatch.setattr(
        faceit_api, "fetch_player", lambda _pid: _player()
    )

    def failing(_pid):
        raise faceit_api.FaceitApiError("down", code="unavailable")

    monkeypatch.setattr(faceit_api, "fetch_player_stats", failing)
    monkeypatch.setattr(
        faceit_api,
        "fetch_player_game_stats",
        lambda _pid, **_kwargs: _game_stats_payload(),
    )
    monkeypatch.setattr(
        faceit_api,
        "fetch_player_history",
        lambda _pid, **_kwargs: _history_payload(),
    )

    response = client.post("/api/faceit/sync", headers=_headers(user))
    body = response.get_json()

    assert response.status_code == 200
    assert body["status"] == "PARTIAL"
    assert "estadísticas generales" in body["partial_reasons"]
    assert body["faceit"]["stats"]["available"] is False

    db.session.expire_all()
    state = db.session.query(FaceitSyncState).one()
    assert state.status == "PARTIAL"
    assert "parcial" in state.last_error.lower()


def test_sync_error_applies_backoff(client, app, monkeypatch):
    app.config["FACEIT_SYNC_MIN_INTERVAL_SECONDS"] = 0
    user = _create_user()
    _link_faceit(user)

    def failing(_pid):
        raise faceit_api.FaceitApiError("down", code="unavailable")

    monkeypatch.setattr(faceit_api, "fetch_player", failing)
    response = client.post("/api/faceit/sync", headers=_headers(user))
    body = response.get_json()

    assert response.status_code == 200
    assert body["status"] == "ERROR"
    assert body["sync"]["can_sync"] is False

    db.session.expire_all()
    state = db.session.query(FaceitSyncState).one()
    assert state.status == "ERROR"
    assert state.consecutive_failures == 1
    assert state.next_sync_at is not None


def test_sync_requires_configuration(client, app):
    user = _create_user()
    _link_faceit(user)
    app.config["FACEIT_API_KEY"] = ""

    response = client.post("/api/faceit/sync", headers=_headers(user))
    assert response.status_code == 503
    assert "FACEIT_API_KEY" in response.get_json()["error"]


def test_sync_respects_minimum_interval(client, app, monkeypatch):
    app.config["FACEIT_SYNC_MIN_INTERVAL_SECONDS"] = 300
    user = _create_user()
    _link_faceit(user)
    _patch_sync(monkeypatch)

    assert (
        client.post("/api/faceit/sync", headers=_headers(user)).status_code
        == 200
    )
    second = client.post("/api/faceit/sync", headers=_headers(user))
    body = second.get_json()

    assert second.status_code == 200
    assert body["status"] == "SKIPPED"
    assert body["message"]


def test_history_and_maps_are_private_per_user(client, app, monkeypatch):
    app.config["FACEIT_SYNC_MIN_INTERVAL_SECONDS"] = 0
    owner = _create_user("owner")
    other = _create_user("other")
    _link_faceit(owner)
    _patch_sync(monkeypatch)
    client.post("/api/faceit/sync", headers=_headers(owner))

    assert (
        client.get("/api/faceit/matches", headers=_headers(owner)).status_code
        == 200
    )
    assert (
        client.get("/api/faceit/maps", headers=_headers(owner)).status_code
        == 200
    )
    assert (
        client.get("/api/faceit/elo", headers=_headers(owner)).status_code
        == 200
    )
    assert (
        client.get("/api/faceit/matches", headers=_headers(other)).status_code
        == 404
    )
    assert (
        client.get("/api/faceit/maps", headers=_headers(other)).status_code
        == 404
    )


def test_match_detail_cannot_be_read_by_another_user(
    client, app, monkeypatch
):
    app.config["FACEIT_SYNC_MIN_INTERVAL_SECONDS"] = 0
    owner = _create_user("owner")
    other = _create_user("other")
    _link_faceit(owner)
    _patch_sync(monkeypatch)
    client.post("/api/faceit/sync", headers=_headers(owner))

    db.session.expire_all()
    match = db.session.query(FaceitMatch).first()
    response = client.get(
        f"/api/faceit/matches/{match.id}", headers=_headers(other)
    )
    assert response.status_code == 404


def test_matches_filter_and_pagination(client, app, monkeypatch):
    app.config["FACEIT_SYNC_MIN_INTERVAL_SECONDS"] = 0
    user = _create_user()
    _link_faceit(user)
    _patch_sync(monkeypatch)
    client.post("/api/faceit/sync", headers=_headers(user))

    response = client.get(
        "/api/faceit/matches?map=de_mirage&result=WIN&limit=1",
        headers=_headers(user),
    )
    body = response.get_json()
    assert response.status_code == 200
    assert body["total"] >= 1
    assert all(row["map"] == "de_mirage" for row in body["matches"])
    assert all(row["result"] == "WIN" for row in body["matches"])


def test_unlink_removes_faceit_data_but_not_local_account(client):
    user = _create_user()
    _link_faceit(user)

    response = client.delete(
        "/api/faceit/account", headers=_headers(user)
    )
    assert response.status_code == 200
    assert response.get_json()["faceit"]["linked"] is False

    db.session.expire_all()
    assert db.session.query(FaceitAccount).count() == 0
    assert db.session.query(User).filter_by(id=user.id).count() == 1


def test_oauth_start_requires_configuration(client, app):
    user = _create_user()
    app.config["FACEIT_OAUTH_CLIENT_ID"] = ""

    response = client.post(
        "/api/faceit/oauth/start", headers=_headers(user)
    )
    assert response.status_code == 503
    assert "FACEIT Connect" in response.get_json()["error"]


def test_oauth_start_builds_pkce_authorization_url(client):
    user = _create_user()
    response = client.post(
        "/api/faceit/oauth/start", headers=_headers(user)
    )
    body = response.get_json()

    assert response.status_code == 200
    parsed = urlparse(body["authorization_url"])
    params = parse_qs(parsed.query)
    assert parsed.netloc == "accounts.faceit.test"
    assert params["response_type"] == ["code"]
    assert params["redirect_popup"] == ["true"]
    assert params["scope"] == ["openid profile membership"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["code_challenge"][0]
    assert params["state"][0]
    assert body["expires_in_seconds"] == 600

    db.session.expire_all()
    request = db.session.query(FaceitOAuthRequest).one()
    assert request.consumed_at is None
    assert request.code_verifier_encrypted
    # El verifier nunca se guarda en claro.
    assert params["code_challenge"][0] not in request.code_verifier_encrypted


def test_oauth_callback_verifies_and_is_single_use(client, monkeypatch):
    user = _create_user()
    start = client.post(
        "/api/faceit/oauth/start", headers=_headers(user)
    ).get_json()
    state = parse_qs(urlparse(start["authorization_url"]).query)["state"][0]

    monkeypatch.setattr(
        faceit_api,
        "exchange_oauth_code",
        lambda code, verifier: {"access_token": "token"},
    )
    monkeypatch.setattr(
        faceit_api,
        "fetch_oauth_userinfo",
        lambda token: {
            "guid": PLAYER_ID,
            "name": "FaceitUser",
            "picture": "https://cdn.example/avatar.jpg",
        },
    )
    monkeypatch.setattr(
        faceit_api, "fetch_player", lambda _pid: _player()
    )

    response = client.get(
        f"/api/faceit/oauth/callback?state={state}&code=abc",
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "faceit=linked" in response.headers["Location"]

    db.session.expire_all()
    account = db.session.query(FaceitAccount).one()
    assert account.faceit_player_id == PLAYER_ID
    assert account.link_status == "VERIFIED"
    assert account.verification_source == "OAUTH2"
    assert account.verified_at is not None
    assert db.session.query(FaceitOAuthRequest).one().consumed_at is not None

    replay = client.get(
        f"/api/faceit/oauth/callback?state={state}&code=abc",
        follow_redirects=False,
    )
    assert replay.status_code == 302
    assert "reason=invalid_state" in replay.headers["Location"]


def test_oauth_callback_links_guid_when_data_api_fails(client, monkeypatch):
    user = _create_user()
    start = client.post(
        "/api/faceit/oauth/start", headers=_headers(user)
    ).get_json()
    state = parse_qs(urlparse(start["authorization_url"]).query)["state"][0]

    monkeypatch.setattr(
        faceit_api,
        "exchange_oauth_code",
        lambda code, verifier: {"access_token": "token"},
    )
    monkeypatch.setattr(
        faceit_api,
        "fetch_oauth_userinfo",
        lambda token: {
            "guid": PLAYER_ID,
            "name": "FaceitUser",
            "picture": "https://cdn.example/avatar.jpg",
        },
    )

    def failing(_player_id):
        raise faceit_api.FaceitApiError("down", code="unavailable")

    monkeypatch.setattr(faceit_api, "fetch_player", failing)

    response = client.get(
        f"/api/faceit/oauth/callback?state={state}&code=abc",
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "faceit=linked" in response.headers["Location"]

    db.session.expire_all()
    account = db.session.query(FaceitAccount).one()
    assert account.faceit_player_id == PLAYER_ID
    assert account.nickname == "FaceitUser"
    assert account.link_status == "VERIFIED"


def test_oauth_callback_rejects_expired_request(client):
    user = _create_user()
    start = client.post(
        "/api/faceit/oauth/start", headers=_headers(user)
    ).get_json()
    state = parse_qs(urlparse(start["authorization_url"]).query)["state"][0]

    db.session.expire_all()
    request = db.session.query(FaceitOAuthRequest).one()
    request.expires_at = request.created_at.replace(year=2000)
    db.session.commit()

    response = client.get(
        f"/api/faceit/oauth/callback?state={state}&code=abc",
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "reason=invalid_state" in response.headers["Location"]


def test_oauth_callback_does_not_leak_exchange_errors(client, monkeypatch):
    user = _create_user()
    start = client.post(
        "/api/faceit/oauth/start", headers=_headers(user)
    ).get_json()
    state = parse_qs(urlparse(start["authorization_url"]).query)["state"][0]

    def failing(_code, _verifier):
        raise faceit_api.FaceitApiError(
            "invalid_client super-secret", code="unauthorized"
        )

    monkeypatch.setattr(faceit_api, "exchange_oauth_code", failing)
    response = client.get(
        f"/api/faceit/oauth/callback?state={state}&code=abc",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "reason=exchange_failed" in response.headers["Location"]
    assert "super-secret" not in response.headers["Location"]


def test_profile_includes_faceit_section_without_owner_secrets(client):
    user = _create_user()
    _link_faceit(user, verified=True)

    response = client.get("/api/profile", headers=_headers(user))
    body = response.get_json()["profile"]

    assert response.status_code == 200
    assert body["faceit"]["linked"] is True
    assert body["faceit"]["account"]["player_id"] == PLAYER_ID
    assert body["faceit"]["account"]["verified"] is True
    assert body["provenance"]["faceit_stats"] == "UNAVAILABLE"
    assert body["faceit"]["sync"]["api_configured"] is True


def test_worker_syncs_due_accounts(client, app, monkeypatch):
    app.config["FACEIT_SYNC_MIN_INTERVAL_SECONDS"] = 0
    user = _create_user()
    account = _link_faceit(user)
    account.sync_state.next_sync_at = None
    account.sync_state.last_attempt_at = None
    db.session.commit()
    _patch_sync(monkeypatch)

    result = faceit_service.sync_due_accounts(limit=5)

    assert result["synced"] == 1
    assert result["errors"] == 0
    db.session.expire_all()
    assert db.session.query(FaceitPlayerStats).count() == 1
