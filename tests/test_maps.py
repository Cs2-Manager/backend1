def _create_map(client, auth_headers, name="Mirage"):
    response = client.post(
        "/api/maps",
        json={"name": name, "image_url": "https://example.com/map.jpg"},
        headers=auth_headers,
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


def test_create_and_get_map(client, auth_headers):
    map_id = _create_map(client, auth_headers)
    response = client.get(f"/api/maps/{map_id}")
    assert response.status_code == 200
    assert response.get_json()["map"]["name"] == "Mirage"


def test_create_map_duplicate_name(client, auth_headers):
    _create_map(client, auth_headers, name="Inferno")
    response = client.post(
        "/api/maps",
        json={"name": "Inferno", "image_url": "https://x/i.jpg"},
        headers=auth_headers,
    )
    assert response.status_code == 409


def test_create_map_validation_error(client, auth_headers):
    response = client.post(
        "/api/maps", json={"name": ""}, headers=auth_headers
    )
    assert response.status_code == 400
    assert "name" in response.get_json()["fields"]


def test_update_and_delete_map(client, auth_headers):
    map_id = _create_map(client, auth_headers, name="Dust2")

    updated = client.put(
        f"/api/maps/{map_id}",
        json={"active_pool": True},
        headers=auth_headers,
    )
    assert updated.status_code == 200
    assert updated.get_json()["map"]["active_pool"] is True

    assert client.delete(f"/api/maps/{map_id}", headers=auth_headers).status_code == 200
    assert client.get(f"/api/maps/{map_id}").status_code == 404


def test_callout_crud(client, auth_headers):
    map_id = _create_map(client, auth_headers, name="Nuke")

    no_auth = client.post(
        f"/api/maps/{map_id}/callouts",
        json={"zone_name": "A", "x_ratio": 0.2, "y_ratio": 0.3},
    )
    assert no_auth.status_code == 401

    created = client.post(
        f"/api/maps/{map_id}/callouts",
        json={"zone_name": "A", "x_ratio": 0.2, "y_ratio": 0.3},
        headers=auth_headers,
    )
    assert created.status_code == 201
    callout_id = created.get_json()["callout"]["id"]

    assert client.get(f"/api/maps/{map_id}/callouts/{callout_id}").status_code == 200
    listed = client.get(f"/api/maps/{map_id}/callouts").get_json()
    assert len(listed["callouts"]) == 1

    updated = client.put(
        f"/api/maps/{map_id}/callouts/{callout_id}",
        json={"zone_name": "B"},
        headers=auth_headers,
    )
    assert updated.get_json()["callout"]["zone_name"] == "B"

    assert (
        client.delete(
            f"/api/maps/{map_id}/callouts/{callout_id}", headers=auth_headers
        ).status_code
        == 200
    )


def test_callout_ratio_validation(client, auth_headers):
    map_id = _create_map(client, auth_headers, name="Vertigo")
    response = client.post(
        f"/api/maps/{map_id}/callouts",
        json={"zone_name": "A", "x_ratio": 5, "y_ratio": 0.3},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "x_ratio" in response.get_json()["fields"]
