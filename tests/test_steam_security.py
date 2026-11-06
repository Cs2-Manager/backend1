"""Pruebas de privacidad y aislamiento de la integración con Steam."""

from app.extensions import db
from app.models.steam import SteamAccount
from app.models.user import User
from app.security import generate_token, hash_password
from app.services import profile_service, steam_api

STEAM_ID_A = "76561198000000001"
STEAM_ID_B = "76561198000000002"


def _create_user(username):
    user = User(
        username=username,
        email=f"{username}@example.com",
        password_hash=hash_password("secret123"),
    )
    db.session.add(user)
    db.session.commit()
    profile_service.ensure_profile(user)
    return user


def _link(user, steam_id):
    account = SteamAccount(
        user_id=user.id,
        steam_id=steam_id,
        persona_name=f"Persona {steam_id[-1]}",
        profile_url=f"https://steamcommunity.com/profiles/{steam_id}",
        avatar_full_url="https://cdn.example/avatar.jpg",
        community_visibility_state=3,
    )
    db.session.add(account)
    db.session.commit()
    return account


def _headers(user):
    return {"Authorization": f"Bearer {generate_token(user)}"}


def _summary(steam_id, name):
    return {
        "steam_id": steam_id,
        "persona_name": name,
        "profile_url": f"https://steamcommunity.com/profiles/{steam_id}",
        "avatar_url": None,
        "avatar_medium_url": None,
        "avatar_full_url": None,
        "persona_state": 1,
        "community_visibility_state": 3,
        "profile_created_at": None,
        "last_logoff_at": None,
    }


def test_public_profile_exposes_only_public_steam_data(client, app):
    app.config["STEAM_API_KEY"] = "super-secret-api-key"
    user = _create_user("publicplayer")
    _link(user, STEAM_ID_A)
    profile = user.profile
    profile.visibility = "PUBLIC"
    db.session.commit()

    response = client.get(f"/api/players/{user.id}")
    assert response.status_code == 200
    body = response.get_json()["profile"]

    assert body["steam"]["linked"] is True
    assert body["steam"]["account"]["steam_id"] == STEAM_ID_A
    assert body["steam"]["cs2"]["stats_available"] is False
    assert body["provenance"]["cs2_player_stats"] == "UNAVAILABLE"
    assert "super-secret-api-key" not in response.get_data(as_text=True)


def test_private_profile_does_not_expose_steam_data(client):
    user = _create_user("privateplayer")
    _link(user, STEAM_ID_A)
    user.profile.visibility = "PRIVATE"
    db.session.commit()

    response = client.get(f"/api/players/{user.id}")
    assert response.status_code == 403
    assert STEAM_ID_A not in response.get_data(as_text=True)


def test_owner_metadata_is_not_exposed_publicly(client):
    user = _create_user("owner")
    account = _link(user, STEAM_ID_A)
    account.last_sync_status = "ERROR"
    account.last_sync_error = "internal upstream detail"
    user.profile.visibility = "PUBLIC"
    db.session.commit()

    public = client.get(f"/api/players/{user.id}").get_json()["profile"]
    owner = client.get("/api/profile", headers=_headers(user)).get_json()[
        "profile"
    ]

    assert "last_sync_error" not in public["steam"]["account"]
    assert "last_sync_error" not in public["steam"]["sync"]
    assert "api_configured" not in public["steam"]
    assert owner["steam"]["account"]["last_sync_error"] == (
        "internal upstream detail"
    )
    assert owner["steam"]["sync"]["api_configured"] is True


def test_profile_update_cannot_change_verified_steam_data(client):
    user = _create_user("editor")
    account = _link(user, STEAM_ID_A)
    original_persona = account.persona_name

    response = client.put(
        "/api/profile",
        headers=_headers(user),
        json={
            "nickname": "edited",
            "steam_id": STEAM_ID_B,
            "steam": {"linked": True, "account": {"steam_id": STEAM_ID_B}},
            "stats": {"kills": 99999, "source": "VERIFIED_STEAM"},
            "competitive": {"elo": 5000, "status": "RANKED"},
        },
    )
    assert response.status_code == 200

    db.session.expire_all()
    account = db.session.query(SteamAccount).one()
    assert account.steam_id == STEAM_ID_A
    assert account.persona_name == original_persona

    body = response.get_json()["profile"]
    assert body["stats"]["source"] != "VERIFIED_STEAM"
    assert body["competitive"]["elo"] is None
    assert body["steam"]["account"]["steam_id"] == STEAM_ID_A


def test_sync_only_updates_authenticated_user(client, app, monkeypatch):
    app.config["STEAM_SYNC_MIN_INTERVAL_SECONDS"] = 0
    user_a = _create_user("alpha")
    user_b = _create_user("bravo")
    _link(user_a, STEAM_ID_A)
    _link(user_b, STEAM_ID_B)

    def summary(steam_id):
        return _summary(steam_id, "Updated A" if steam_id == STEAM_ID_A else "Updated B")

    monkeypatch.setattr(steam_api, "fetch_player_summaries", summary)
    monkeypatch.setattr(
        steam_api,
        "fetch_owned_games",
        lambda _steam_id, app_id=730: None,
    )

    response = client.post("/api/steam/sync", headers=_headers(user_a))
    assert response.status_code == 200

    db.session.expire_all()
    account_a = db.session.query(SteamAccount).filter_by(
        steam_id=STEAM_ID_A
    ).one()
    account_b = db.session.query(SteamAccount).filter_by(
        steam_id=STEAM_ID_B
    ).one()
    assert account_a.persona_name == "Updated A"
    assert account_b.persona_name == "Persona 2"
    assert account_b.last_sync_at is None


def test_unlink_does_not_delete_local_account_or_other_data(client):
    user = _create_user("survivor")
    _link(user, STEAM_ID_A)
    user_id = user.id

    response = client.delete("/api/steam/account", headers=_headers(user))
    assert response.status_code == 200

    db.session.expire_all()
    assert db.session.get(User, user_id) is not None
    assert db.session.query(SteamAccount).count() == 0
    assert client.get(
        "/api/auth/me", headers=_headers(user)
    ).status_code == 200


def test_steam_account_is_unique_across_users(app):
    user_a = _create_user("unique_a")
    user_b = _create_user("unique_b")
    _link(user_a, STEAM_ID_A)

    db.session.add(SteamAccount(user_id=user_b.id, steam_id=STEAM_ID_A))
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
    else:  # pragma: no cover - la restricción debe impedirlo
        raise AssertionError("Se permitió duplicar un SteamID64")

    assert db.session.query(SteamAccount).count() == 1
