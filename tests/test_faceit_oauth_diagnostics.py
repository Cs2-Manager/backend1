"""Regresiones del callback, transacciones y diagnóstico sin secretos."""

import base64
import hashlib
import io
import json
import logging
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.models.faceit import FaceitAccount, FaceitOAuthRequest, FaceitSyncState
from app.models.user import User
from app.security import generate_token, hash_password
from app.services import faceit_api, faceit_service


class _Response(io.BytesIO):
    status = 200


def _start(client, username="oauth-owner"):
    user = User(
        username=username, email=f"{username}@example.com",
        password_hash=hash_password("secret123"),
    )
    db.session.add(user)
    db.session.commit()
    response = client.post(
        "/api/faceit/oauth/start",
        headers={"Authorization": f"Bearer {generate_token(user)}"},
    )
    params = parse_qs(urlparse(response.get_json()["authorization_url"]).query)
    return user.id, params


def _callback(client, params, **kwargs):
    return client.get(
        "/api/faceit/oauth/callback",
        query_string={"state": params["state"][0], "code": "private-code"},
        **kwargs,
    )


def _identity(monkeypatch):
    monkeypatch.setattr(
        faceit_api, "exchange_oauth_code", lambda *_: {"access_token": "private-token"}
    )
    monkeypatch.setattr(
        faceit_api, "fetch_oauth_userinfo", lambda _: {"guid": "verified-player"}
    )
    monkeypatch.setattr(
        faceit_api, "fetch_player", lambda _: {"player_id": "verified-player"}
    )


def test_token_request_matches_official_contract_and_pkce(app, monkeypatch, caplog):
    verifier, challenge = faceit_api.build_pkce_pair()
    assert 43 <= len(verifier) <= 128
    assert challenge == base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).decode("ascii").rstrip("=")
    calls = []

    def open_request(request, **kwargs):
        calls.append(request)
        assert request.full_url == app.config["FACEIT_OAUTH_TOKEN_URL"]
        assert request.method == "POST"
        assert request.get_header("Content-type") == "application/x-www-form-urlencoded"
        credentials = base64.b64decode(
            request.get_header("Authorization").split(" ", 1)[1]
        ).decode()
        assert credentials == (
            app.config["FACEIT_OAUTH_CLIENT_ID"] + ":"
            + app.config["FACEIT_OAUTH_CLIENT_SECRET"]
        )
        assert parse_qs(request.data.decode()) == {
            "grant_type": ["authorization_code"], "code": ["private-code"],
            "redirect_uri": [app.config["FACEIT_OAUTH_REDIRECT_URI"]],
            "code_verifier": [verifier],
        }
        return _Response(b'{"access_token":"private-token"}')

    monkeypatch.setattr(faceit_api, "urlopen", open_request)
    assert faceit_api.exchange_oauth_code("private-code", verifier)["access_token"]
    assert len(calls) == 1
    assert "faceit_oauth_token http=200 category=ok" in caplog.text
    for secret in ("private-code", "private-token", verifier,
                   app.config["FACEIT_OAUTH_CLIENT_SECRET"]):
        assert secret not in caplog.text


@pytest.mark.parametrize("category,status", [
    ("invalid_grant", 400), ("invalid_client", 401),
    ("invalid_redirect_uri", 400), ("invalid_pkce", 400),
    ("pkce_verification_failed", 400),
    ("arbitrary-private-value", 400), ({"private": "value"}, 400),
])
def test_token_error_is_classified_without_logging_body(
    app, monkeypatch, caplog, category, status
):
    calls = []

    def fail(request, **kwargs):
        calls.append(request)
        raise HTTPError(
            request.full_url, status, "private-code", {},
            io.BytesIO(json.dumps({
                "error": category,
                "error_description": "private-code private-secret private-token",
            }).encode()),
        )

    monkeypatch.setattr(faceit_api, "urlopen", fail)
    expected = category if isinstance(category, str) and category in (
        faceit_api.OAUTH_ERROR_CATEGORIES
    ) else "http_error"
    with pytest.raises(faceit_api.FaceitApiError) as caught:
        faceit_api.exchange_oauth_code("private-code", "private-verifier")
    assert caught.value.code == expected
    assert caught.value.status == status
    assert len(calls) == 1  # Authorization codes are never retried.
    assert f"faceit_oauth_token http={status} category={expected}" in caplog.text
    for secret in ("private-code", "private-secret", "private-token",
                   "private-verifier", "arbitrary-private-value"):
        assert secret not in caplog.text
        assert secret not in str(caught.value)


def test_userinfo_diagnostic_is_distinct_from_token(app, monkeypatch, caplog):
    def fail(request, **kwargs):
        assert request.method == "GET"
        assert request.full_url == app.config["FACEIT_OAUTH_USERINFO_URL"]
        assert request.get_header("Authorization") == "Bearer private-token"
        raise HTTPError(request.full_url, 401, "private-token", {}, io.BytesIO(b'{}'))

    monkeypatch.setattr(faceit_api, "urlopen", fail)
    with pytest.raises(faceit_api.FaceitApiError):
        faceit_api.fetch_oauth_userinfo("private-token")
    assert "faceit_oauth_userinfo http=401 category=http_error" in caplog.text
    assert "private-token" not in caplog.text


def test_token_html_basic_challenge_is_client_authentication_failure(
    app, monkeypatch, caplog
):
    def fail(request, **kwargs):
        raise HTTPError(
            request.full_url, 401, "Unauthorized",
            {"WWW-Authenticate": 'Basic realm="OAuth"'},
            io.BytesIO(b"<html>private-code private-secret</html>"),
        )

    monkeypatch.setattr(faceit_api, "urlopen", fail)
    with pytest.raises(faceit_api.FaceitApiError) as caught:
        faceit_api.exchange_oauth_code("private-code", "private-verifier")
    assert caught.value.status == 401
    assert caught.value.code == "client_authentication_failed"
    assert "http=401 category=client_authentication_failed" in caplog.text
    assert "private-code" not in caplog.text
    assert "private-secret" not in caplog.text


def test_bad_verifier_does_not_consume_state_or_exchange(client, monkeypatch):
    _, params = _start(client)
    oauth = db.session.query(FaceitOAuthRequest).one()
    oauth.code_verifier_encrypted = "not-decryptable"
    db.session.commit()
    monkeypatch.setattr(
        faceit_api, "exchange_oauth_code",
        lambda *_: pytest.fail("Must validate the verifier before exchange"),
    )
    response = _callback(client, params)
    assert "reason=invalid_state" in response.location
    db.session.expire_all()
    assert db.session.query(FaceitOAuthRequest).one().consumed_at is None


def test_callback_uses_state_owner_not_callback_jwt_or_origin(
    client, app, monkeypatch
):
    app.config["FACEIT_PUBLIC_BASE_URL"] = "https://public.example"
    app.config["FACEIT_OAUTH_REDIRECT_URI"] = (
        "https://public.example/api/faceit/oauth/callback"
    )
    owner_id, params = _start(client)
    other_id, _ = _start(client, "different-user")
    other = db.session.get(User, other_id)
    _identity(monkeypatch)

    def exchange(code, verifier):
        request = db.session.query(FaceitOAuthRequest).filter_by(user_id=owner_id).one()
        assert request.consumed_at is None  # Not committed ahead of verification.
        assert verifier == faceit_service._decrypt(request.code_verifier_encrypted)
        return {"access_token": "private-token"}

    monkeypatch.setattr(faceit_api, "exchange_oauth_code", exchange)
    response = _callback(
        client, params,
        headers={"Authorization": f"Bearer {generate_token(other)}"},
    )
    assert response.status_code == 302
    assert response.location == "https://public.example/profile?faceit=linked"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert db.session.query(FaceitAccount).one().user_id == owner_id
    assert db.session.query(FaceitSyncState).count() == 1
    assert db.session.query(FaceitOAuthRequest).filter_by(user_id=owner_id).one().consumed_at


def test_persistence_failure_rolls_back_link_and_state(client, monkeypatch, caplog):
    _, params = _start(client)
    _identity(monkeypatch)

    def fail(*_):
        raise SQLAlchemyError("private-code private-token SQL parameters")

    monkeypatch.setattr(faceit_service, "_ensure_sync_state", fail)
    response = _callback(client, params)
    assert response.status_code == 302
    assert "reason=database_error" in response.location
    assert db.session.query(FaceitAccount).count() == 0
    assert db.session.query(FaceitSyncState).count() == 0
    assert db.session.query(FaceitOAuthRequest).one().consumed_at is None
    assert "category=database_error" in caplog.text
    assert "SQL parameters" not in caplog.text
    assert "private-token" not in caplog.text


@pytest.mark.parametrize("stage,reason", [
    ("exchange_oauth_code", "exchange_failed"),
    ("fetch_oauth_userinfo", "userinfo_failed"),
])
def test_terminal_upstream_error_consumes_once(client, monkeypatch, stage, reason):
    _, params = _start(client)
    _identity(monkeypatch)
    calls = []

    def fail(*_):
        calls.append(True)
        raise faceit_api.FaceitApiError("private-token", code="invalid_grant", status=400)

    monkeypatch.setattr(faceit_api, stage, fail)
    response = _callback(client, params)
    assert f"reason={reason}" in response.location
    assert db.session.query(FaceitOAuthRequest).one().consumed_at is not None
    assert db.session.query(FaceitAccount).count() == 0
    assert "reason=invalid_state" in _callback(client, params).location
    assert len(calls) == 1


def test_denied_callback_validates_state_first(client):
    _, params = _start(client)
    response = client.get("/api/faceit/oauth/callback", query_string={
        "error": "access_denied", "state": "unknown-state",
    })
    assert "reason=invalid_state" in response.location
    assert db.session.query(FaceitOAuthRequest).one().consumed_at is None
    response = client.get("/api/faceit/oauth/callback", query_string={
        "error": "access_denied", "state": params["state"][0],
    })
    assert "reason=access_denied" in response.location
    assert db.session.query(FaceitOAuthRequest).one().consumed_at is not None


@pytest.mark.parametrize("existing_owner,reason", [
    ("other", "account_conflict"), ("self", "already_linked"),
])
def test_callback_preserves_existing_links(client, monkeypatch, existing_owner, reason):
    owner_id, params = _start(client)
    other_id, _ = _start(client, "existing-owner")
    account = FaceitAccount(
        user_id=other_id if existing_owner == "other" else owner_id,
        faceit_player_id="verified-player" if existing_owner == "other" else "other-player",
        link_status="DISCOVERED", verification_source="STEAM_DISCOVERY",
    )
    db.session.add(account)
    db.session.commit()
    _identity(monkeypatch)
    response = _callback(client, params)
    assert f"reason={reason}" in response.location
    assert db.session.query(FaceitAccount).one().verification_source == "STEAM_DISCOVERY"
    assert db.session.query(FaceitOAuthRequest).filter_by(user_id=owner_id).one().consumed_at


def test_callback_internal_error_is_sanitized(client, monkeypatch, caplog):
    _, params = _start(client)

    def fail(*_):
        raise RuntimeError("private-code private-token")

    monkeypatch.setattr(faceit_api, "exchange_oauth_code", fail)
    response = _callback(client, params)
    assert "reason=internal_error" in response.location
    assert "category=internal_error" in caplog.text
    assert "private-code" not in caplog.text
    assert "private-token" not in caplog.text


def test_werkzeug_callback_access_log_drops_query(caplog):
    with caplog.at_level(logging.INFO, logger="werkzeug"):
        logging.getLogger("werkzeug").info(
            '"%s" %s',
            "GET /api/faceit/oauth/callback?code=private-code&state=private-state HTTP/1.1",
            302,
        )
    assert "/api/faceit/oauth/callback HTTP/1.1" in caplog.text
    assert "private-code" not in caplog.text
    assert "private-state" not in caplog.text
