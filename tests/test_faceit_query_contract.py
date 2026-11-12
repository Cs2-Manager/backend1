"""History query coercion keeps its defaults and does not bypass JWT."""
import pytest

from app.services import faceit_service


@pytest.mark.parametrize("query,expected", [
    ("", {"limit": 25, "offset": 0, "map_name": None, "result": None}),
    ("?limit=bad&offset=bad&map=%20%20&result=", {"limit": 25, "offset": 0, "map_name": None, "result": None}),
    ("?limit=-1&offset=3&map=%20de_mirage%20&result=%20WIN%20", {"limit": -1, "offset": 3, "map_name": "de_mirage", "result": "WIN"}),
])
def test_history_query_contract(client, auth_headers, monkeypatch, query, expected):
    calls = []
    def list_matches(user, **options):
        calls.append(options)
        return {"matches": []}
    monkeypatch.setattr(faceit_service, "list_matches", list_matches)
    response = client.get("/api/faceit/matches" + query, headers=auth_headers)
    assert (response.status_code, response.get_json()) == (200, {"matches": []})
    assert calls == [expected]


def test_history_requires_jwt(client, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Unauthenticated history must not call the service")
    monkeypatch.setattr(faceit_service, "list_matches", forbidden)
    assert client.get("/api/faceit/matches").status_code == 401
