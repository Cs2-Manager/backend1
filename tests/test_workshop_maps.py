def _payload(**overrides):
    data = {
        "title": "Aim Botz",
        "category": "Aim",
        "image_url": "https://example.com/aim.jpg",
        "workshop_url": "https://steamcommunity.com/sharedfiles/1",
    }
    data.update(overrides)
    return data


def test_create_workshop_map_requires_auth(client):
    response = client.post("/api/workshop-maps", json=_payload())
    assert response.status_code == 401


def test_create_and_filter_by_category(client, admin_headers):
    created = client.post(
        "/api/workshop-maps", json=_payload(), headers=admin_headers
    )
    assert created.status_code == 201
    workshop_id = created.get_json()["workshop_map"]["id"]

    listed = client.get(
        "/api/workshop-maps", query_string={"category": "Aim"}
    ).get_json()
    assert listed["workshop_maps"][0]["id"] == workshop_id

    bad = client.get("/api/workshop-maps", query_string={"category": "Nope"})
    assert bad.status_code == 400


def test_create_workshop_map_validation(client, admin_headers):
    response = client.post(
        "/api/workshop-maps", json=_payload(category="Bad"), headers=admin_headers
    )
    assert response.status_code == 400
    assert "category" in response.get_json()["fields"]


def test_update_and_delete_workshop_map(client, admin_headers):
    workshop_id = client.post(
        "/api/workshop-maps", json=_payload(), headers=admin_headers
    ).get_json()["workshop_map"]["id"]

    updated = client.put(
        f"/api/workshop-maps/{workshop_id}",
        json={"title": "Aim Botz 2"},
        headers=admin_headers,
    )
    assert updated.get_json()["workshop_map"]["title"] == "Aim Botz 2"

    assert (
        client.delete(
            f"/api/workshop-maps/{workshop_id}", headers=admin_headers
        ).status_code
        == 200
    )
    assert client.get(f"/api/workshop-maps/{workshop_id}").status_code == 404
