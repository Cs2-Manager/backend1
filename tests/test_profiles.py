"""Pruebas del perfil competitivo, privacidad e historial de partidas."""

from app.extensions import db
from app.models.map import Map
from app.models.player_profile import (
    PlayerCompetitiveProfile,
    PlayerProfile,
    PlayerStats,
)
from app.models.user import User
from app.security import generate_token, hash_password


def _create_user(username, *, is_admin=False):
    user = User(
        username=username,
        email=f"{username}@example.com",
        password_hash=hash_password("secret123"),
        is_admin=is_admin,
    )
    db.session.add(user)
    db.session.commit()
    return user


def _headers_for(user):
    return {"Authorization": f"Bearer {generate_token(user)}"}


def _create_map(name="Mirage"):
    map_obj = Map(
        name=name,
        image_url="https://example.com/map.jpg",
        active_pool=True,
    )
    db.session.add(map_obj)
    db.session.commit()
    return map_obj


def _register(client, username="newbie"):
    response = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "secret123",
        },
    )
    assert response.status_code == 201
    return response.get_json()["user"]


def _match_payload(**overrides):
    payload = {
        "result": "WIN",
        "match_type": "COMPETITIVE",
        "kills": 20,
        "deaths": 10,
        "assists": 5,
        "headshots": 8,
        "rounds_played": 20,
        "damage": 1800,
    }
    payload.update(overrides)
    return payload


def test_register_creates_private_empty_profile(client):
    user = _register(client)

    profile = db.session.query(PlayerProfile).filter_by(user_id=user["id"]).one()
    assert profile.nickname == "newbie"
    assert profile.display_name == "newbie"
    assert profile.visibility == "PRIVATE"
    assert profile.last_active_at is not None
    assert profile.competitive.status == "UNRANKED"
    assert profile.competitive.elo is None
    assert profile.stats.matches_played == 0


def test_login_updates_last_active(client):
    user = _register(client)
    profile = db.session.query(PlayerProfile).filter_by(user_id=user["id"]).one()
    profile.last_active_at = None
    db.session.commit()

    response = client.post(
        "/api/auth/login",
        json={"username": "newbie", "password": "secret123"},
    )

    assert response.status_code == 200
    db.session.refresh(profile)
    assert profile.last_active_at is not None


def test_own_profile_requires_authentication(client):
    assert client.get("/api/profile").status_code == 401


def test_own_profile_has_empty_sections_without_invented_data(client, auth_headers):
    response = client.get("/api/profile", headers=auth_headers)

    assert response.status_code == 200
    profile = response.get_json()["profile"]
    assert profile["nickname"] == "tester"
    assert profile["is_owner"] is True
    assert profile["visibility"] == "PRIVATE"
    assert profile["email"] == "tester@example.com"

    assert profile["competitive"]["status"] == "UNRANKED"
    assert profile["competitive"]["elo"] is None
    assert profile["competitive"]["level"] is None
    assert profile["competitive"]["ranked"] is False

    assert profile["stats"]["has_data"] is False
    assert profile["stats"]["matches_played"] == 0
    assert profile["stats"]["kd"] is None
    assert profile["stats"]["adr"] is None
    assert profile["stats"]["win_rate"] is None
    assert profile["recent_matches"] == []
    assert profile["map_performance"] == []
    assert profile["matches_total"] == 0


def test_update_own_profile_normalizes_and_persists(client, auth_headers):
    response = client.put(
        "/api/profile",
        json={
            "nickname": "FragMachine",
            "display_name": "  Frag Machine  ",
            "country": "es",
            "bio": "  Jugador competitivo  ",
            "avatar_url": "https://cdn.example.com/avatar.png",
            "steam_url": "https://steamcommunity.com/id/fragmachine",
            "social_links": {
                "twitch": "https://twitch.tv/fragmachine",
                "x": "https://x.com/fragmachine",
            },
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    profile = response.get_json()["profile"]
    assert profile["nickname"] == "FragMachine"
    assert profile["display_name"] == "Frag Machine"
    assert profile["country"] == "ES"
    assert profile["bio"] == "Jugador competitivo"
    assert profile["avatar_url"] == "https://cdn.example.com/avatar.png"
    assert profile["steam_url"] == "https://steamcommunity.com/id/fragmachine"
    assert profile["social_links"] == {
        "twitch": "https://twitch.tv/fragmachine",
        "x": "https://x.com/fragmachine",
    }
    assert profile["last_active_at"] is not None


def test_update_profile_can_remove_optional_values_and_social_links(
    client, auth_headers
):
    client.put(
        "/api/profile",
        json={
            "bio": "Texto",
            "avatar_url": "https://cdn.example.com/avatar.png",
            "social_links": {"twitch": "https://twitch.tv/tester"},
        },
        headers=auth_headers,
    )

    response = client.put(
        "/api/profile",
        json={
            "bio": "",
            "avatar_url": "",
            "social_links": {"twitch": ""},
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    profile = response.get_json()["profile"]
    assert profile["bio"] is None
    assert profile["avatar_url"] is None
    assert profile["social_links"] == {}


def test_update_profile_rejects_invalid_values(client, auth_headers):
    response = client.put(
        "/api/profile",
        json={
            "nickname": "",
            "country": "ESP",
            "bio": "x" * 501,
            "display_name": "x" * 81,
            "avatar_url": "javascript:alert(1)",
            "steam_url": "https://example.com/steam",
            "social_links": {"x": "javascript:alert(1)"},
        },
        headers=auth_headers,
    )

    assert response.status_code == 400
    fields = response.get_json()["fields"]
    for field in (
        "nickname",
        "country",
        "bio",
        "display_name",
        "avatar_url",
        "steam_url",
        "x",
    ):
        assert field in fields


def test_update_profile_rejects_unknown_social_platform(client, auth_headers):
    response = client.put(
        "/api/profile",
        json={"social_links": {"myspace": "https://myspace.com/tester"}},
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "social_links" in response.get_json()["fields"]


def test_update_profile_rejects_non_object_social_links(client, auth_headers):
    response = client.put(
        "/api/profile",
        json={"social_links": ["https://twitch.tv/tester"]},
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "social_links" in response.get_json()["fields"]


def test_nickname_must_be_unique(client, auth_headers):
    assert client.get("/api/profile", headers=auth_headers).status_code == 200
    other = _create_user("other")
    assert client.get("/api/profile", headers=_headers_for(other)).status_code == 200

    response = client.put(
        "/api/profile",
        json={"nickname": "tester"},
        headers=_headers_for(other),
    )

    assert response.status_code == 400
    assert "nickname" in response.get_json()["fields"]


def test_visibility_only_accepts_public_or_private(client, auth_headers):
    team = client.put(
        "/api/profile", json={"visibility": "TEAM"}, headers=auth_headers
    )
    assert team.status_code == 400
    assert "visibility" in team.get_json()["fields"]

    unknown = client.put(
        "/api/profile", json={"visibility": "FRIENDS"}, headers=auth_headers
    )
    assert unknown.status_code == 400
    assert "visibility" in unknown.get_json()["fields"]


def test_private_profile_is_hidden_from_other_users_and_anonymous(
    client, auth_headers
):
    tester = db.session.query(User).filter_by(username="tester").one()
    other = _create_user("other")

    assert client.get(f"/api/players/{tester.id}").status_code == 403
    assert (
        client.get(f"/api/players/{tester.id}", headers=_headers_for(other)).status_code
        == 403
    )

    owner = client.get(f"/api/players/{tester.id}", headers=auth_headers)
    assert owner.status_code == 200
    assert owner.get_json()["profile"]["is_owner"] is True
    assert owner.get_json()["profile"]["email"] == "tester@example.com"


def test_public_profile_never_exposes_sensitive_fields(client, auth_headers):
    tester = db.session.query(User).filter_by(username="tester").one()
    client.put(
        "/api/profile",
        json={
            "visibility": "PUBLIC",
            "nickname": "PublicTester",
            "country": "AR",
        },
        headers=auth_headers,
    )

    response = client.get(f"/api/players/{tester.id}")

    assert response.status_code == 200
    profile = response.get_json()["profile"]
    assert profile["nickname"] == "PublicTester"
    assert profile["country"] == "AR"
    assert profile["is_owner"] is False
    for forbidden in ("email", "password_hash", "is_admin"):
        assert forbidden not in profile


def test_admin_can_view_private_profile_without_private_fields(
    client, auth_headers, admin_headers
):
    tester = db.session.query(User).filter_by(username="tester").one()
    client.get("/api/profile", headers=auth_headers)

    response = client.get(f"/api/players/{tester.id}", headers=admin_headers)

    assert response.status_code == 200
    profile = response.get_json()["profile"]
    assert profile["is_owner"] is False
    assert "email" not in profile
    assert "password_hash" not in profile
    assert "is_admin" not in profile


def test_missing_player_returns_404(client):
    assert client.get("/api/players/9999").status_code == 404


def test_players_directory_only_lists_public_profiles(client, auth_headers):
    tester = db.session.query(User).filter_by(username="tester").one()
    beta = _create_user("beta")
    hidden = _create_user("hidden")

    client.put(
        "/api/profile",
        json={"visibility": "PUBLIC", "nickname": "Alpha"},
        headers=auth_headers,
    )
    client.put(
        "/api/profile",
        json={"visibility": "PUBLIC", "nickname": "Beta"},
        headers=_headers_for(beta),
    )
    client.get("/api/profile", headers=_headers_for(hidden))

    response = client.get("/api/players")

    assert response.status_code == 200
    body = response.get_json()
    assert [player["nickname"] for player in body["players"]] == ["Alpha", "Beta"]
    assert body["meta"]["total"] == 2
    for player in body["players"]:
        assert "email" not in player
        assert player["id"] in (tester.id, beta.id)

    filtered = client.get("/api/players?search=alp").get_json()
    assert [player["nickname"] for player in filtered["players"]] == ["Alpha"]


def test_profile_update_ignores_account_privileges_and_competitive_fields(
    client, auth_headers
):
    other = _create_user("other")
    client.get("/api/profile", headers=_headers_for(other))

    response = client.put(
        "/api/profile",
        json={
            "nickname": "Legit",
            "user_id": other.id,
            "username": "evil",
            "email": "evil@example.com",
            "is_admin": True,
            "elo": 9999,
            "level": 10,
            "xp": 123456,
            "competitive": {"elo": 9999},
            "stats": {"matches_played": 999, "wins": 999},
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    tester = db.session.query(User).filter_by(username="tester").one()
    other_user = db.session.query(User).filter_by(username="other").one()
    assert tester.username == "tester"
    assert tester.email == "tester@example.com"
    assert tester.is_admin is False
    assert other_user.username == "other"

    tester_profile = (
        db.session.query(PlayerProfile).filter_by(user_id=tester.id).one()
    )
    other_profile = (
        db.session.query(PlayerProfile).filter_by(user_id=other_user.id).one()
    )
    assert tester_profile.nickname == "Legit"
    assert other_profile.nickname == "other"
    assert tester_profile.competitive.elo is None
    assert tester_profile.competitive.level is None
    assert tester_profile.competitive.xp is None
    assert tester_profile.stats.matches_played == 0
    assert tester_profile.stats.wins == 0


def test_record_match_requires_admin(client, auth_headers):
    tester = db.session.query(User).filter_by(username="tester").one()
    payload = _match_payload()

    anonymous = client.post(f"/api/players/{tester.id}/matches", json=payload)
    assert anonymous.status_code == 401

    non_admin = client.post(
        f"/api/players/{tester.id}/matches",
        json=payload,
        headers=auth_headers,
    )
    assert non_admin.status_code == 403


def test_match_history_and_aggregates_come_from_recorded_matches(
    client, auth_headers, admin_headers
):
    tester = db.session.query(User).filter_by(username="tester").one()
    map_obj = _create_map()

    first = client.post(
        f"/api/players/{tester.id}/matches",
        json=_match_payload(map_id=map_obj.id),
        headers=admin_headers,
    )
    assert first.status_code == 201
    match = first.get_json()["match"]
    assert match["result"] == "WIN"
    assert match["map"] == {"id": map_obj.id, "name": "Mirage"}
    assert match["kd"] == 2.0
    assert match["adr"] == 90.0
    assert match["headshot_percentage"] == 40.0

    second = client.post(
        f"/api/players/{tester.id}/matches",
        json=_match_payload(
            result="LOSS",
            map_id=map_obj.id,
            kills=10,
            deaths=20,
            assists=2,
            headshots=4,
            damage=1200,
        ),
        headers=admin_headers,
    )
    assert second.status_code == 201

    response = client.get("/api/profile", headers=auth_headers)
    profile = response.get_json()["profile"]
    stats = profile["stats"]
    assert stats["has_data"] is True
    assert stats["matches_played"] == 2
    assert stats["wins"] == 1
    assert stats["losses"] == 1
    assert stats["kills"] == 30
    assert stats["deaths"] == 30
    assert stats["assists"] == 7
    assert stats["headshots"] == 12
    assert stats["rounds_played"] == 40
    assert stats["total_damage"] == 3000
    assert stats["kd"] == 1.0
    assert stats["adr"] == 75.0
    assert stats["headshot_percentage"] == 40.0
    assert stats["win_rate"] == 50.0
    assert profile["matches_total"] == 2
    assert len(profile["recent_matches"]) == 2

    map_row = profile["map_performance"][0]
    assert map_row["map"] == {"id": map_obj.id, "name": "Mirage"}
    assert map_row["matches_played"] == 2
    assert map_row["wins"] == 1
    assert map_row["losses"] == 1
    assert map_row["win_rate"] == 50.0


def test_matches_endpoint_respects_profile_visibility(
    client, auth_headers, admin_headers
):
    tester = db.session.query(User).filter_by(username="tester").one()
    other = _create_user("other")
    client.post(
        f"/api/players/{tester.id}/matches",
        json=_match_payload(),
        headers=admin_headers,
    )

    assert client.get(f"/api/players/{tester.id}/matches").status_code == 403
    assert (
        client.get(
            f"/api/players/{tester.id}/matches", headers=_headers_for(other)
        ).status_code
        == 403
    )

    client.put(
        "/api/profile", json={"visibility": "PUBLIC"}, headers=auth_headers
    )
    response = client.get(f"/api/players/{tester.id}/matches")
    assert response.status_code == 200
    assert len(response.get_json()["matches"]) == 1


def test_matches_endpoint_paginates(client, auth_headers, admin_headers):
    tester = db.session.query(User).filter_by(username="tester").one()
    for _ in range(3):
        client.post(
            f"/api/players/{tester.id}/matches",
            json=_match_payload(),
            headers=admin_headers,
        )

    response = client.get(
        f"/api/players/{tester.id}/matches?page=1&per_page=2",
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.get_json()
    assert len(body["matches"]) == 2
    assert body["meta"] == {"total": 3, "page": 1, "per_page": 2}


def test_match_validation_rejects_invalid_payloads(
    client, auth_headers, admin_headers
):
    tester = db.session.query(User).filter_by(username="tester").one()
    client.get("/api/profile", headers=auth_headers)
    url = f"/api/players/{tester.id}/matches"

    missing_result = client.post(url, json={"kills": 1}, headers=admin_headers)
    assert missing_result.status_code == 400
    assert "result" in missing_result.get_json()["fields"]

    invalid_result = client.post(
        url, json=_match_payload(result="TIE"), headers=admin_headers
    )
    assert "result" in invalid_result.get_json()["fields"]

    invalid_type = client.post(
        url, json=_match_payload(match_type="RANKED"), headers=admin_headers
    )
    assert "match_type" in invalid_type.get_json()["fields"]

    negative = client.post(
        url, json=_match_payload(kills=-1), headers=admin_headers
    )
    assert "kills" in negative.get_json()["fields"]

    too_many_headshots = client.post(
        url, json=_match_payload(kills=1, headshots=2), headers=admin_headers
    )
    assert "headshots" in too_many_headshots.get_json()["fields"]

    unknown_map = client.post(
        url, json=_match_payload(map_id=9999), headers=admin_headers
    )
    assert "map_id" in unknown_map.get_json()["fields"]

    invalid_date = client.post(
        url, json=_match_payload(played_at="not-a-date"), headers=admin_headers
    )
    assert "played_at" in invalid_date.get_json()["fields"]


def test_match_without_map_does_not_create_map_performance(
    client, auth_headers, admin_headers
):
    tester = db.session.query(User).filter_by(username="tester").one()

    response = client.post(
        f"/api/players/{tester.id}/matches",
        json=_match_payload(),
        headers=admin_headers,
    )
    assert response.status_code == 201
    assert response.get_json()["match"]["map"] is None

    profile = client.get("/api/profile", headers=auth_headers).get_json()["profile"]
    assert profile["stats"]["matches_played"] == 1
    assert profile["map_performance"] == []


def test_stats_serializer_derives_ratios_only_with_real_data():
    from app.serializers import serialize_stats

    empty = serialize_stats(PlayerStats())
    assert empty["has_data"] is False
    assert empty["kd"] is None
    assert empty["kr"] is None
    assert empty["adr"] is None
    assert empty["headshot_percentage"] is None
    assert empty["win_rate"] is None

    stats = PlayerStats(
        matches_played=4,
        wins=3,
        losses=1,
        kills=80,
        deaths=40,
        assists=10,
        headshots=40,
        rounds_played=100,
        total_damage=8500,
    )
    data = serialize_stats(stats)
    assert data["has_data"] is True
    assert data["kd"] == 2.0
    assert data["kr"] == 0.8
    assert data["adr"] == 85.0
    assert data["headshot_percentage"] == 50.0
    assert data["win_rate"] == 75.0


def test_competitive_serializer_never_invents_values():
    from app.serializers import serialize_competitive

    data = serialize_competitive(PlayerCompetitiveProfile(status="UNRANKED"))

    assert data == {
        "status": "UNRANKED",
        "ranked": False,
        "level": None,
        "elo": None,
        "xp": None,
        "xp_to_next_level": None,
        "ranking_position": None,
    }
