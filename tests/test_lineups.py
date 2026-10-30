VALID_VIDEO = "https://youtu.be/dQw4w9WgXcQ"


def _create_map(client, admin_headers, name="Mirage"):
    response = client.post(
        "/api/maps",
        json={"name": name, "image_url": "https://example.com/map.jpg"},
        headers=admin_headers,
    )
    return response.get_json()["map"]["id"]


def _payload(map_id, **overrides):
    data = {
        "map_id": map_id,
        "type": "Smoke",
        "side": "CT",
        "title": "Smoke A",
        "video_url": VALID_VIDEO,
    }
    data.update(overrides)
    return data


def test_create_lineup_requires_auth(client, admin_headers):
    map_id = _create_map(client, admin_headers)
    response = client.post("/api/lineups", json=_payload(map_id))
    assert response.status_code == 401


def test_lineup_crud_and_filters(client, admin_headers):
    map_id = _create_map(client, admin_headers)

    created = client.post("/api/lineups", json=_payload(map_id), headers=admin_headers)
    assert created.status_code == 201
    lineup_id = created.get_json()["lineup"]["id"]

    assert client.get(f"/api/lineups/{lineup_id}").status_code == 200

    listed = client.get(
        "/api/lineups", query_string={"type": "Smoke", "side": "CT"}
    ).get_json()
    assert len(listed["lineups"]) == 1

    updated = client.put(
        f"/api/lineups/{lineup_id}",
        json={"title": "Smoke A v2"},
        headers=admin_headers,
    )
    assert updated.get_json()["lineup"]["title"] == "Smoke A v2"

    assert (
        client.delete(f"/api/lineups/{lineup_id}", headers=admin_headers).status_code
        == 200
    )


def test_lineup_validation_errors(client, admin_headers):
    map_id = _create_map(client, admin_headers)
    response = client.post(
        "/api/lineups",
        json=_payload(
            map_id, type="Bad", side="XX", title="", video_url="not-a-url"
        ),
        headers=admin_headers,
    )
    assert response.status_code == 400
    fields = response.get_json()["fields"]
    assert {"type", "side", "title", "video_url"} <= set(fields)


def test_lineup_invalid_map(client, admin_headers):
    response = client.post(
        "/api/lineups", json=_payload(9999), headers=admin_headers
    )
    assert response.status_code == 400
    assert response.get_json()["fields"]["map_id"] == "Map not found"
