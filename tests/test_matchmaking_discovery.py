"""Pruebas del cliente de descubrimiento de share codes (sin red real)."""

from urllib.error import HTTPError, URLError

import pytest

from app.services.matchmaking import discovery
from app.services.matchmaking.sharecode import encode_share_code

STEAM_ID = "76561198000000001"
AUTH_CODE = "ABCD-12345-EFGH"
KNOWN = encode_share_code((1_700_000_000 << 32) + 1, 100, 1)
NEXT = encode_share_code((1_700_000_000 << 32) + 2, 200, 1)


def test_returns_next_canonical_code(app, monkeypatch):
    calls = []

    def fake_request(steam_id, auth_code, known_code):
        calls.append((steam_id, auth_code, known_code))
        return NEXT.replace("-", "")

    monkeypatch.setattr(discovery, "_request", fake_request)

    assert discovery.get_next_share_code(STEAM_ID, AUTH_CODE, KNOWN) == NEXT
    assert calls == [(STEAM_ID, AUTH_CODE, KNOWN)]


def test_no_more_codes_returns_none(app, monkeypatch):
    for value in (None, "", "N/A", "n/a"):
        monkeypatch.setattr(discovery, "_request", lambda *a, v=value: v)
        assert discovery.get_next_share_code(STEAM_ID, AUTH_CODE, KNOWN) is None


def test_invalid_response_code_is_rejected(app, monkeypatch):
    monkeypatch.setattr(discovery, "_request", lambda *a: "CSGO-INVALID")

    with pytest.raises(discovery.DiscoveryError) as error:
        discovery.get_next_share_code(STEAM_ID, AUTH_CODE, KNOWN)
    assert error.value.code == "invalid_response"


def test_missing_authorization_is_rejected_without_network(app):
    with pytest.raises(discovery.DiscoveryError) as error:
        discovery.get_next_share_code(STEAM_ID, "", KNOWN)
    assert error.value.code == "invalid_authorization"
    assert error.value.retryable is False


def test_invalid_known_share_code_is_rejected(app):
    with pytest.raises(discovery.DiscoveryError) as error:
        discovery.get_next_share_code(STEAM_ID, AUTH_CODE, "CSGO-12345")
    assert error.value.code == "invalid_share_code"


@pytest.mark.parametrize(
    "status, expected_code, retryable",
    [
        (403, "invalid_auth_code", False),
        (400, "invalid_share_code", False),
        (429, "rate_limited", True),
        (500, "http_error", True),
    ],
)
def test_http_errors_are_classified(app, monkeypatch, status, expected_code,
                                    retryable):
    def fake_urlopen(*_args, **_kwargs):
        raise HTTPError("https://steam", status, "error", None, None)

    monkeypatch.setattr(discovery, "urlopen", fake_urlopen)

    with pytest.raises(discovery.DiscoveryError) as error:
        discovery._request(STEAM_ID, AUTH_CODE, KNOWN)
    assert error.value.code == expected_code
    assert error.value.retryable is retryable


def test_http_202_means_no_more_codes(app, monkeypatch):
    def fake_urlopen(*_args, **_kwargs):
        raise HTTPError("https://steam", 202, "accepted", None, None)

    monkeypatch.setattr(discovery, "urlopen", fake_urlopen)
    assert discovery._request(STEAM_ID, AUTH_CODE, KNOWN) is None


def test_network_error_is_retryable(app, monkeypatch):
    def fake_urlopen(*_args, **_kwargs):
        raise URLError("offline")

    monkeypatch.setattr(discovery, "urlopen", fake_urlopen)

    with pytest.raises(discovery.DiscoveryError) as error:
        discovery._request(STEAM_ID, AUTH_CODE, KNOWN)
    assert error.value.code == "unavailable"
    assert error.value.retryable is True


def test_not_configured_without_api_key(app, monkeypatch):
    app.config["STEAM_API_KEY"] = ""
    with pytest.raises(discovery.DiscoveryError) as error:
        discovery._request(STEAM_ID, AUTH_CODE, KNOWN)
    assert error.value.code == "not_configured"
    assert error.value.retryable is False
