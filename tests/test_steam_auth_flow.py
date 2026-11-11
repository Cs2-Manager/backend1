"""Pruebas del flujo OpenID, registro, vinculación y canje de handoff."""

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from app.extensions import db
from app.models.player_profile import PlayerProfile
from app.models.steam import SteamAccount, SteamAuthRequest
from app.models.user import User
from app.security import generate_token, hash_password
from app.services import steam_api, steam_openid

STEAM_ID = "76561198000000001"
STEAM_ID_2 = "76561198000000002"


def _summary(steam_id=STEAM_ID, name="FragMaster"):
    return {
        "steam_id": steam_id,
        "persona_name": name,
        "profile_url": f"https://steamcommunity.com/profiles/{steam_id}",
        "avatar_url": "https://cdn.example/avatar.jpg",
        "avatar_medium_url": "https://cdn.example/avatar_medium.jpg",
        "avatar_full_url": "https://cdn.example/avatar_full.jpg",
        "persona_state": 1,
        "community_visibility_state": 3,
        "profile_created_at": 1600000000,
        "last_logoff_at": 1700000000,
    }


def _mock_steam_api(monkeypatch):
    monkeypatch.setattr(
        steam_api,
        "fetch_player_summaries",
        lambda _steam_id: _summary(),
    )


def _create_user(username, email=None):
    user = User(
        username=username,
        email=email or f"{username}@example.com",
        password_hash=hash_password("secret123"),
    )
    db.session.add(user)
    db.session.commit()
    return user


def _headers_for(user):
    return {"Authorization": f"Bearer {generate_token(user)}"}


def _start(client, path="/api/auth/steam/start", headers=None):
    response = client.get(path, headers=headers or {})
    assert response.status_code == 302
    location = response.headers["Location"]
    query = parse_qs(urlparse(location).query)
    return_to = query["openid.return_to"][0]
    state = parse_qs(urlparse(return_to).query)["state"][0]
    return location, state


def _callback(client, state, monkeypatch, steam_id=STEAM_ID):
    monkeypatch.setattr(
        steam_openid,
        "verify_response",
        lambda _values, _return_to: steam_id,
    )
    response = client.get(
        f"/api/auth/steam/callback?state={state}"
    )
    assert response.status_code == 302
    location = response.headers["Location"]
    query = parse_qs(urlparse(location).query)
    return location, query


def _exchange(client, handoff):
    return client.post(
        "/api/auth/steam/exchange", json={"handoff": handoff}
    )


def test_steam_login_creates_local_account_and_profile(client, monkeypatch):
    _mock_steam_api(monkeypatch)

    location, state = _start(client)
    assert location.startswith("https://steamcommunity.com/openid/login?")
    assert state

    callback_url, query = _callback(client, state, monkeypatch)
    assert callback_url.startswith("http://localhost/steam/callback?")
    handoff = query["handoff"][0]

    response = _exchange(client, handoff)
    assert response.status_code == 200
    body = response.get_json()

    user = db.session.query(User).filter_by(
        email=f"steam_{STEAM_ID}@steam.invalid"
    ).one()
    account = db.session.query(SteamAccount).filter_by(
        steam_id=STEAM_ID
    ).one()
    profile = db.session.query(PlayerProfile).filter_by(
        user_id=user.id
    ).one()

    assert body["created"] is True
    assert body["intent"] == "LOGIN"
    assert body["user"]["id"] == user.id
    assert body["token"]
    assert account.user_id == user.id
    assert account.persona_name == "FragMaster"
    assert profile.user_id == user.id
    assert profile.display_name == "FragMaster"

    me = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {body['token']}"},
    )
    assert me.status_code == 200
    assert me.get_json()["user"]["id"] == user.id

    # La contraseña local es aleatoria e inutilizable: solo se entra por Steam.
    login = client.post(
        "/api/auth/login",
        json={
            "email": f"steam_{STEAM_ID}@steam.invalid",
            "password": "anything",
        },
    )
    assert login.status_code == 401


def test_steam_login_reuses_existing_linked_account(client, monkeypatch):
    _mock_steam_api(monkeypatch)

    _, state = _start(client)
    _, query = _callback(client, state, monkeypatch)
    first = _exchange(client, query["handoff"][0])
    first_user_id = first.get_json()["user"]["id"]

    _, state = _start(client)
    _, query = _callback(client, state, monkeypatch)
    second = _exchange(client, query["handoff"][0])

    assert second.status_code == 200
    assert second.get_json()["created"] is False
    assert second.get_json()["user"]["id"] == first_user_id
    assert db.session.query(SteamAccount).count() == 1


def test_handoff_is_single_use(client, monkeypatch):
    _mock_steam_api(monkeypatch)
    _, state = _start(client)
    _, query = _callback(client, state, monkeypatch)
    handoff = query["handoff"][0]

    assert _exchange(client, handoff).status_code == 200
    assert _exchange(client, handoff).status_code == 400


def test_expired_or_unknown_state_is_rejected(client):
    response = client.get("/api/auth/steam/callback?state=unknown")
    assert response.status_code == 302
    assert "error=invalid_state" in response.headers["Location"]

    _, state = _start(client)
    request = db.session.query(SteamAuthRequest).one()
    request.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.session.commit()

    response = client.get(f"/api/auth/steam/callback?state={state}")
    assert "error=invalid_state" in response.headers["Location"]


def test_expired_handoff_is_rejected(client, monkeypatch):
    _mock_steam_api(monkeypatch)
    _, state = _start(client)
    _, query = _callback(client, state, monkeypatch)
    request = db.session.query(SteamAuthRequest).one()
    request.handoff_expires_at = datetime.now(timezone.utc) - timedelta(
        seconds=1
    )
    db.session.commit()

    assert _exchange(client, query["handoff"][0]).status_code == 400


def test_existing_user_can_link_and_unlink_steam(client, monkeypatch):
    _mock_steam_api(monkeypatch)
    user = _create_user("localhero")
    headers = _headers_for(user)
    profile = PlayerProfile(
        user_id=user.id,
        nickname="localhero",
        steam_url="https://steamcommunity.com/id/manual",
        visibility="PUBLIC",
    )
    db.session.add(profile)
    db.session.commit()

    response = client.post("/api/steam/link", headers=headers)
    assert response.status_code == 200
    auth_url = response.get_json()["authorization_url"]
    state = parse_qs(
        urlparse(parse_qs(urlparse(auth_url).query)["openid.return_to"][0]).query
    )["state"][0]

    _, query = _callback(client, state, monkeypatch)
    exchange = _exchange(client, query["handoff"][0])
    assert exchange.status_code == 200
    body = exchange.get_json()
    assert body["intent"] == "LINK"
    assert body["user"]["id"] == user.id
    assert body["steam"]["linked"] is True

    account = db.session.query(SteamAccount).one()
    assert account.user_id == user.id
    assert account.steam_id == STEAM_ID

    db.session.refresh(profile)
    assert profile.steam_url == "https://steamcommunity.com/id/manual"

    status = client.get("/api/steam/status", headers=headers)
    assert status.status_code == 200
    assert status.get_json()["steam"]["account"]["steam_id"] == STEAM_ID

    removed = client.delete("/api/steam/account", headers=headers)
    assert removed.status_code == 200
    assert removed.get_json()["steam"]["linked"] is False
    assert db.session.query(SteamAccount).count() == 0
    assert db.session.get(User, user.id) is not None


def test_linking_steam_already_owned_by_another_user_is_rejected(
    client, monkeypatch
):
    owner = _create_user("owner")
    other = _create_user("other")
    db.session.add(SteamAccount(user_id=owner.id, steam_id=STEAM_ID))
    db.session.commit()

    headers = _headers_for(other)
    response = client.post("/api/steam/link", headers=headers)
    auth_url = response.get_json()["authorization_url"]
    state = parse_qs(
        urlparse(parse_qs(urlparse(auth_url).query)["openid.return_to"][0]).query
    )["state"][0]

    location, query = _callback(client, state, monkeypatch)
    assert location.endswith("error=account_conflict")
    assert "handoff" not in query

    db.session.expire_all()
    assert db.session.get(User, other.id).steam_account is None
    assert db.session.query(SteamAccount).count() == 1


def test_link_conflict_detected_again_at_exchange(client, monkeypatch):
    other = _create_user("other")
    headers = _headers_for(other)
    response = client.post("/api/steam/link", headers=headers)
    auth_url = response.get_json()["authorization_url"]
    state = parse_qs(
        urlparse(parse_qs(urlparse(auth_url).query)["openid.return_to"][0]).query
    )["state"][0]
    _, query = _callback(client, state, monkeypatch)

    winner = _create_user("winner")
    db.session.add(SteamAccount(user_id=winner.id, steam_id=STEAM_ID))
    db.session.commit()

    exchange = _exchange(client, query["handoff"][0])
    assert exchange.status_code == 409
    db.session.expire_all()
    assert db.session.get(User, other.id).steam_account is None


def test_link_requires_authentication(client):
    assert client.post("/api/steam/link").status_code == 401
    assert client.get("/api/steam/status").status_code == 401
    assert client.post("/api/steam/sync").status_code == 401
    assert client.delete("/api/steam/account").status_code == 401


def test_exchange_ignores_frontend_supplied_steam_identity(
    client, monkeypatch
):
    _mock_steam_api(monkeypatch)
    _, state = _start(client)
    _, query = _callback(client, state, monkeypatch)

    response = client.post(
        "/api/auth/steam/exchange",
        json={
            "handoff": query["handoff"][0],
            "steam_id": STEAM_ID_2,
            "user_id": 999,
        },
    )
    assert response.status_code == 200
    account = db.session.query(SteamAccount).one()
    assert account.steam_id == STEAM_ID


def test_link_cannot_be_started_twice(client, monkeypatch):
    user = _create_user("linked")
    db.session.add(SteamAccount(user_id=user.id, steam_id=STEAM_ID))
    db.session.commit()

    response = client.post("/api/steam/link", headers=_headers_for(user))
    assert response.status_code == 409


def test_steam_start_without_api_key_redirects_with_error(client, app):
    app.config["STEAM_API_KEY"] = ""
    response = client.get("/api/auth/steam/start")
    assert response.status_code == 302
    assert "error=not_configured" in response.headers["Location"]
