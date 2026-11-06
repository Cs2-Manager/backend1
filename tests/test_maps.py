from app.extensions import db
from app.models import Lineup, Map, TeamStrategy


def _create_map(client, admin_headers, name="Mirage"):
    response = client.post(
        "/api/maps",
        json={"name": name, "image_url": "https://example.com/map.jpg"},
        headers=admin_headers,
    )
    return response.get_json()["map"]["id"]


def test_list_maps_empty(client):
    response = client.get("/api/maps")
    assert response.status_code == 200
    assert response.get_json()["maps"] == []


def test_create_map_requires_auth(client):
    response = client.post(
        "/api/maps", json={"name": "Mirage", "image_url": "https://x/y.jpg"}
    )
    assert response.status_code == 401


def test_create_and_get_map(client, admin_headers):
    map_id = _create_map(client, admin_headers)
    response = client.get(f"/api/maps/{map_id}")
    assert response.status_code == 200
    assert response.get_json()["map"]["name"] == "Mirage"


def test_create_map_duplicate_name(client, admin_headers):
    _create_map(client, admin_headers, name="Inferno")
    response = client.post(
        "/api/maps",
        json={"name": "Inferno", "image_url": "https://x/i.jpg"},
        headers=admin_headers,
    )
    assert response.status_code == 409


def test_create_map_validation_error(client, admin_headers):
    response = client.post(
        "/api/maps", json={"name": ""}, headers=admin_headers
    )
    assert response.status_code == 400
    assert "name" in response.get_json()["fields"]


def test_update_and_delete_map(client, admin_headers):
    map_id = _create_map(client, admin_headers, name="Dust2")

    updated = client.put(
        f"/api/maps/{map_id}",
        json={"active_pool": True},
        headers=admin_headers,
    )
    assert updated.status_code == 200
    assert updated.get_json()["map"]["active_pool"] is True

    deleted = client.delete(f"/api/maps/{map_id}", headers=admin_headers)
    assert deleted.status_code == 200
    assert deleted.get_json()["archived"] is False
    assert client.get(f"/api/maps/{map_id}").status_code == 404


def test_delete_map_without_references_removes_it(client, app, admin_headers):
    map_id = _create_map(client, admin_headers, name="Anubis")

    response = client.delete(f"/api/maps/{map_id}", headers=admin_headers)

    assert response.status_code == 200
    assert response.get_json()["archived"] is False
    assert db.session.get(Map, map_id) is None


def test_delete_map_with_lineups_archives_it(client, app, admin_headers):
    map_id = _create_map(client, admin_headers, name="Train")
    db.session.add(
        Lineup(map_id=map_id, type="Smoke", side="T", title="Smoke ivy")
    )
    db.session.commit()

    response = client.delete(f"/api/maps/{map_id}", headers=admin_headers)

    assert response.status_code == 200
    assert response.get_json()["archived"] is True
    archived = db.session.get(Map, map_id)
    assert archived is not None
    assert archived.status == "ARCHIVED"
    assert archived.active_pool is False
    # El contenido asociado sigue disponible.
    assert client.get(f"/api/maps/{map_id}").status_code == 200


def test_delete_map_with_strategies_archives_it(client, app, admin_headers):
    map_id = _create_map(client, admin_headers, name="Overpass")
    db.session.add(
        TeamStrategy(
            map_id=map_id,
            name="A execute",
            side="T",
            category="EXECUTE",
            document={"steps": []},
        )
    )
    db.session.commit()

    response = client.delete(f"/api/maps/{map_id}", headers=admin_headers)

    assert response.status_code == 200
    assert response.get_json()["archived"] is True
    assert db.session.get(Map, map_id).status == "ARCHIVED"


def test_delete_missing_map_returns_clear_404(client, admin_headers):
    response = client.delete("/api/maps/999999", headers=admin_headers)

    assert response.status_code == 404
    assert response.get_json()["error"] == "Map not found"


def test_delete_map_requires_admin(client, auth_headers):
    # El usuario sin privilegios no puede crear ni borrar mapas del catálogo.
    created = client.post(
        "/api/maps",
        json={"name": "Cache", "image_url": "https://example.com/cache.jpg"},
        headers=auth_headers,
    )
    assert created.status_code == 403
    response = client.delete("/api/maps/1", headers=auth_headers)
    assert response.status_code == 403
    assert response.get_json()["error"] == "Administrator access required"


def test_archived_map_can_be_restored(client, app, admin_headers):
    map_id = _create_map(client, admin_headers, name="Ancient")

    archived = client.post(f"/api/maps/{map_id}/archive", headers=admin_headers)
    assert archived.status_code == 200
    assert archived.get_json()["map"]["status"] == "ARCHIVED"
    assert db.session.get(Map, map_id).status == "ARCHIVED"

    restored = client.post(f"/api/maps/{map_id}/unarchive", headers=admin_headers)
    assert restored.status_code == 200
    assert restored.get_json()["map"]["status"] == "ACTIVE"
    assert db.session.get(Map, map_id).status == "ACTIVE"

    listed = client.get("/api/maps?status=ACTIVE").get_json()["maps"]
    assert any(item["id"] == map_id for item in listed)


def test_unarchive_requires_admin(client, admin_headers):
    map_id = _create_map(client, admin_headers, name="Nuke")
    client.post(f"/api/maps/{map_id}/archive", headers=admin_headers)

    response = client.post(f"/api/maps/{map_id}/unarchive")

    assert response.status_code == 401
    assert db.session.get(Map, map_id).status == "ARCHIVED"


def test_callout_crud(client, admin_headers):
    map_id = _create_map(client, admin_headers, name="Nuke")

    no_auth = client.post(
        f"/api/maps/{map_id}/callouts",
        json={"zone_name": "A", "x_ratio": 0.2, "y_ratio": 0.3},
    )
    assert no_auth.status_code == 401

    created = client.post(
        f"/api/maps/{map_id}/callouts",
        json={"zone_name": "A", "x_ratio": 0.2, "y_ratio": 0.3},
        headers=admin_headers,
    )
    assert created.status_code == 201
    callout_id = created.get_json()["callout"]["id"]

    assert client.get(f"/api/maps/{map_id}/callouts/{callout_id}").status_code == 200
    listed = client.get(f"/api/maps/{map_id}/callouts").get_json()
    assert len(listed["callouts"]) == 1

    updated = client.put(
        f"/api/maps/{map_id}/callouts/{callout_id}",
        json={"zone_name": "B"},
        headers=admin_headers,
    )
    assert updated.get_json()["callout"]["zone_name"] == "B"

    assert (
        client.delete(
            f"/api/maps/{map_id}/callouts/{callout_id}", headers=admin_headers
        ).status_code
        == 200
    )


def test_callout_ratio_validation(client, admin_headers):
    map_id = _create_map(client, admin_headers, name="Vertigo")
    response = client.post(
        f"/api/maps/{map_id}/callouts",
        json={"zone_name": "A", "x_ratio": 5, "y_ratio": 0.3},
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert "x_ratio" in response.get_json()["fields"]
