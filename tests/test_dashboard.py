VALID_VIDEO = "https://youtu.be/dQw4w9WgXcQ"


def _create_map(client, admin_headers, name="Mirage", active_pool=False):
    response = client.post(
        "/api/maps",
        json={
            "name": name,
            "image_url": "https://example.com/map.jpg",
            "active_pool": active_pool,
        },
        headers=admin_headers,
    )
    return response.get_json()["map"]["id"]


def _create_callout(client, admin_headers, map_id, zone_name="A"):
    response = client.post(
        f"/api/maps/{map_id}/callouts",
        json={"zone_name": zone_name, "x_ratio": 0.25, "y_ratio": 0.75},
        headers=admin_headers,
    )
    return response.get_json()["callout"]["id"]


def _create_lineup(client, admin_headers, map_id, title, lineup_type="Smoke"):
    response = client.post(
        "/api/lineups",
        json={
            "map_id": map_id,
            "type": lineup_type,
            "side": "CT",
            "title": title,
            "video_url": VALID_VIDEO,
        },
        headers=admin_headers,
    )
    return response.get_json()["lineup"]["id"]


def test_dashboard_requires_auth(client):
    response = client.get("/api/dashboard")
    assert response.status_code == 401


def test_dashboard_empty_summary(client, auth_headers):
    response = client.get("/api/dashboard", headers=auth_headers)
    assert response.status_code == 200

    dashboard = response.get_json()["dashboard"]
    assert dashboard["summary"]["maps"] == {
        "total": 0,
        "active_pool": 0,
        "callouts": 0,
    }
    assert dashboard["summary"]["lineups"]["total"] == 0
    assert [item["count"] for item in dashboard["summary"]["lineups"]["by_type"]] == [
        0,
        0,
        0,
        0,
        0,
    ]
    assert dashboard["summary"]["workshop_maps"] == {"total": 0, "categories": 0}
    assert dashboard["active_maps"] == []
    assert dashboard["recent_lineups"] == []


def test_dashboard_populated_summary(client, admin_headers, auth_headers):
    active_map_id = _create_map(client, admin_headers, name="Mirage", active_pool=True)
    _create_map(client, admin_headers, name="Inferno")
    _create_callout(client, admin_headers, active_map_id)
    _create_callout(client, admin_headers, active_map_id, zone_name="B")
    _create_lineup(client, admin_headers, active_map_id, title="Smoke CT")
    _create_lineup(
        client, admin_headers, active_map_id, title="Flash CT", lineup_type="Flash"
    )
    client.post(
        "/api/workshop-maps",
        json={
            "title": "Aim Botz",
            "category": "Aim",
            "image_url": "https://example.com/aim.jpg",
            "workshop_url": "https://steamcommunity.com/sharedfiles/1",
        },
        headers=admin_headers,
    )

    dashboard = client.get("/api/dashboard", headers=auth_headers).get_json()[
        "dashboard"
    ]

    assert dashboard["summary"]["maps"] == {
        "total": 2,
        "active_pool": 1,
        "callouts": 2,
    }
    assert dashboard["summary"]["lineups"]["total"] == 2
    by_type = {
        item["type"]: item["count"]
        for item in dashboard["summary"]["lineups"]["by_type"]
    }
    assert by_type == {
        "Smoke": 1,
        "Molotov": 0,
        "Flash": 1,
        "HE": 0,
        "Decoy": 0,
    }
    assert dashboard["summary"]["workshop_maps"] == {"total": 1, "categories": 1}
    assert dashboard["active_maps"] == [
        {
            "id": active_map_id,
            "name": "Mirage",
            "image_url": "https://example.com/map.jpg",
            "callouts_count": 2,
        }
    ]
    assert [lineup["title"] for lineup in dashboard["recent_lineups"]] == [
        "Flash CT",
        "Smoke CT",
    ]
    assert dashboard["recent_lineups"][0]["map_name"] == "Mirage"
