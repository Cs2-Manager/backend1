import re

from flask import jsonify

from app.extensions import db
from app.models.user import User
from app.security import jwt_optional

VALID_VIDEO = "https://youtu.be/dQw4w9WgXcQ"
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
PUBLIC_WRITE_ENDPOINTS = {"auth.register", "auth.login"}
# Escrituras de propiedad: requieren JWT, pero no privilegios administrativos.
OWNER_WRITE_ENDPOINTS = {"profiles.update_profile"}
# Escrituras de equipo: se autorizan por rol (capitán/entrenador) y tienen
# pruebas específicas en test_teams.py.
TEAM_WRITE_ENDPOINTS = {
    "teams.create_team",
    "teams.update_team",
    "teams.invite_member",
    "teams.cancel_invitation",
    "teams.accept_invitation",
    "teams.reject_invitation",
    "teams.remove_member",
    "teams.update_member_role",
    "teams.leave_team",
    "teams.transfer_captain",
    # Alineaciones: se autorizan por rol y tienen pruebas en
    # test_team_lineups.py.
    "team_lineups.create_lineup",
    "team_lineups.update_lineup",
    "team_lineups.delete_lineup",
    "team_lineups.replace_lineup_players",
    "team_lineups.activate_lineup",
    "team_lineups.deactivate_lineup",
    "team_lineups.set_primary_lineup",
}


def _write_requests(app):
    requests = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint in (
            PUBLIC_WRITE_ENDPOINTS | OWNER_WRITE_ENDPOINTS | TEAM_WRITE_ENDPOINTS
        ):
            continue
        methods = sorted((rule.methods or set()) & WRITE_METHODS)
        if not methods:
            continue
        path = re.sub(r"<[^>]+>", "1", rule.rule)
        requests.extend((method, path) for method in methods)
    return requests


def _create_map(client, headers):
    return client.post(
        "/api/maps",
        json={"name": "Mirage", "image_url": "https://example.com/map.jpg"},
        headers=headers,
    ).get_json()["map"]["id"]


def _create_callout(client, headers, map_id):
    return client.post(
        f"/api/maps/{map_id}/callouts",
        json={"zone_name": "A", "x_ratio": 0.2, "y_ratio": 0.3},
        headers=headers,
    ).get_json()["callout"]["id"]


def _create_lineup(client, headers, map_id):
    return client.post(
        "/api/lineups",
        json={
            "map_id": map_id,
            "type": "Smoke",
            "side": "CT",
            "title": "Smoke A",
            "video_url": VALID_VIDEO,
        },
        headers=headers,
    ).get_json()["lineup"]["id"]


def _create_workshop(client, headers):
    return client.post(
        "/api/workshop-maps",
        json={
            "title": "Aim Botz",
            "category": "Aim",
            "image_url": "https://example.com/aim.jpg",
            "workshop_url": "https://steamcommunity.com/sharedfiles/1",
        },
        headers=headers,
    ).get_json()["workshop_map"]["id"]


def test_non_admin_cannot_write_catalog(client, auth_headers, admin_headers):
    map_id = _create_map(client, admin_headers)
    callout_id = _create_callout(client, admin_headers, map_id)
    lineup_id = _create_lineup(client, admin_headers, map_id)
    workshop_id = _create_workshop(client, admin_headers)

    calls = [
        client.post("/api/maps", json={"name": "X", "image_url": "https://x/y.jpg"}, headers=auth_headers),
        client.put(f"/api/maps/{map_id}", json={"active_pool": True}, headers=auth_headers),
        client.delete(f"/api/maps/{map_id}", headers=auth_headers),
        client.post(f"/api/maps/{map_id}/callouts", json={"zone_name": "B", "x_ratio": 0.1, "y_ratio": 0.1}, headers=auth_headers),
        client.put(f"/api/maps/{map_id}/callouts/{callout_id}", json={"zone_name": "B"}, headers=auth_headers),
        client.delete(f"/api/maps/{map_id}/callouts/{callout_id}", headers=auth_headers),
        client.post("/api/lineups", json={"map_id": map_id, "type": "Smoke", "side": "CT", "title": "X", "video_url": VALID_VIDEO}, headers=auth_headers),
        client.put(f"/api/lineups/{lineup_id}", json={"title": "X"}, headers=auth_headers),
        client.delete(f"/api/lineups/{lineup_id}", headers=auth_headers),
        client.post("/api/workshop-maps", json={"title": "X", "category": "Aim", "image_url": "https://x/y.jpg", "workshop_url": "https://x"}, headers=auth_headers),
        client.put(f"/api/workshop-maps/{workshop_id}", json={"title": "X"}, headers=auth_headers),
        client.delete(f"/api/workshop-maps/{workshop_id}", headers=auth_headers),
    ]

    assert all(response.status_code == 403 for response in calls)


def test_anonymous_cannot_write_catalog(client):
    response = client.post(
        "/api/maps", json={"name": "X", "image_url": "https://x/y.jpg"}
    )
    assert response.status_code == 401


def test_every_write_endpoint_requires_admin(app, client, auth_headers):
    requests = _write_requests(app)
    assert requests

    for method, path in requests:
        anonymous = client.open(path, method=method)
        assert anonymous.status_code == 401, (method, path, anonymous.status_code)

        non_admin = client.open(path, method=method, headers=auth_headers)
        assert non_admin.status_code == 403, (method, path, non_admin.status_code)


def test_owner_profile_update_requires_auth_but_not_admin(client, auth_headers):
    anonymous = client.put("/api/profile", json={"display_name": "Anon"})
    assert anonymous.status_code == 401

    non_admin = client.put(
        "/api/profile",
        json={"display_name": "Tester"},
        headers=auth_headers,
    )
    assert non_admin.status_code == 200
    assert non_admin.get_json()["profile"]["display_name"] == "Tester"


def test_register_cannot_self_assign_admin(client):
    response = client.post(
        "/api/auth/register",
        json={
            "username": "mallory",
            "email": "mallory@example.com",
            "password": "secret123",
            "is_admin": True,
        },
    )

    assert response.status_code == 201
    assert response.get_json()["user"]["is_admin"] is False
    assert db.session.query(User).filter_by(username="mallory").one().is_admin is False


def test_jwt_optional_allows_anonymous_and_authenticated(app, client, auth_headers):
    @app.route("/api/test/optional")
    @jwt_optional()
    def optional_route(user):
        return jsonify({"authenticated": user is not None})

    assert client.get("/api/test/optional").get_json()["authenticated"] is False
    assert (
        client.get("/api/test/optional", headers=auth_headers).get_json()[
            "authenticated"
        ]
        is True
    )


def test_set_admin_cli(app, auth_headers):
    runner = app.test_cli_runner()

    result = runner.invoke(args=["set-admin", "tester"])
    assert result.exit_code == 0
    assert db.session.query(User).filter_by(username="tester").one().is_admin is True

    result = runner.invoke(args=["set-admin", "tester", "--revoke"])
    assert result.exit_code == 0
    assert db.session.query(User).filter_by(username="tester").one().is_admin is False


def test_set_admin_cli_accepts_email_case_insensitively(app, auth_headers):
    result = app.test_cli_runner().invoke(args=["set-admin", "TESTER@EXAMPLE.COM"])
    assert result.exit_code == 0
    assert db.session.query(User).filter_by(username="tester").one().is_admin is True


def test_revoked_admin_loses_access_immediately(client, admin_headers):
    admin = db.session.query(User).filter_by(username="admin").one()
    admin.is_admin = False
    db.session.commit()

    response = client.post(
        "/api/maps",
        json={"name": "X", "image_url": "https://x/y.jpg"},
        headers=admin_headers,
    )
    assert response.status_code == 403


def test_set_admin_cli_unknown_user(app):
    result = app.test_cli_runner().invoke(args=["set-admin", "missing"])
    assert result.exit_code != 0
