def _register(client, username="alice", email="alice@example.com", password="secret123"):
    return client.post(
        "/api/auth/register",
        json={"username": username, "email": email, "password": password},
    )


def test_register_success(client):
    response = _register(client)
    assert response.status_code == 201
    body = response.get_json()
    assert body["user"]["username"] == "alice"
    assert body["user"]["email"] == "alice@example.com"
    assert "password_hash" not in body["user"]


def test_register_missing_fields(client):
    response = client.post("/api/auth/register", json={"username": "bob"})
    assert response.status_code == 400
    fields = response.get_json()["fields"]
    assert "email" in fields and "password" in fields


def test_register_duplicate_username(client):
    _register(client)
    response = _register(client, email="other@example.com")
    assert response.status_code == 409


def test_register_duplicate_email(client):
    _register(client)
    response = _register(client, username="other")
    assert response.status_code == 409


def test_login_success_returns_token(client, auth_headers):
    response = client.post(
        "/api/auth/login",
        json={"email": "tester@example.com", "password": "secret123"},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["token"]
    assert body["user"]["username"] == "tester"


def test_login_invalid_credentials(client, auth_headers):
    response = client.post(
        "/api/auth/login",
        json={"email": "tester@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 401


def test_me_requires_token(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_with_token(client, auth_headers):
    response = client.get("/api/auth/me", headers=auth_headers)
    assert response.status_code == 200
    assert response.get_json()["user"]["username"] == "tester"
