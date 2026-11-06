"""Pruebas del cliente OpenID de Steam (sin llamadas reales a Steam)."""

from urllib.error import URLError
from urllib.parse import parse_qs, urlparse

import pytest

from app.services import steam_openid

STEAM_ID = "76561198000000001"
RETURN_TO = (
    "http://localhost/api/auth/steam/callback?state=test-state"
)


def _valid_values():
    claimed = f"https://steamcommunity.com/openid/id/{STEAM_ID}"
    return {
        "openid.mode": "id_res",
        "openid.op_endpoint": "https://steamcommunity.com/openid/login",
        "openid.claimed_id": claimed,
        "openid.identity": claimed,
        "openid.return_to": RETURN_TO,
        "openid.response_nonce": "2026-10-30T00:00:00Znonce",
        "openid.signed": "signed,op_endpoint,claimed_id,identity,return_to",
        "openid.sig": "signature",
    }


def test_build_login_url_uses_official_endpoint():
    url = steam_openid.build_login_url(RETURN_TO, "http://localhost")
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "steamcommunity.com"
    assert parsed.path == "/openid/login"
    assert query["openid.mode"] == ["checkid_setup"]
    assert query["openid.return_to"] == [RETURN_TO]
    assert query["openid.realm"] == ["http://localhost"]


def test_valid_steam_id_format_and_range():
    assert steam_openid.is_valid_steam_id(STEAM_ID)
    assert steam_openid.is_valid_steam_id("76561197960265728")
    assert not steam_openid.is_valid_steam_id("")
    assert not steam_openid.is_valid_steam_id("123")
    assert not steam_openid.is_valid_steam_id("76560000000000000")
    assert not steam_openid.is_valid_steam_id("7656119796026572")


def test_verify_response_accepts_valid_steam_signature(monkeypatch):
    sent = {}

    def fake_post(url, data):
        sent["url"] = url
        sent["data"] = data
        return "ns:http://specs.openid.net/auth/2.0\nis_valid:true\n"

    monkeypatch.setattr(steam_openid, "_post_form", fake_post)

    assert (
        steam_openid.verify_response(_valid_values(), RETURN_TO) == STEAM_ID
    )
    assert sent["url"] == steam_openid.STEAM_OPENID_ENDPOINT
    assert sent["data"]["openid.mode"] == "check_authentication"
    assert sent["data"]["openid.claimed_id"].endswith(STEAM_ID)


def test_verify_response_rejects_mismatched_return_to(monkeypatch):
    monkeypatch.setattr(
        steam_openid,
        "_post_form",
        lambda _url, _data: "is_valid:true\n",
    )
    with pytest.raises(steam_openid.SteamOpenIDError):
        steam_openid.verify_response(
            _valid_values(), "http://localhost/other-callback"
        )


def test_verify_response_rejects_wrong_endpoint(monkeypatch):
    monkeypatch.setattr(
        steam_openid,
        "_post_form",
        lambda _url, _data: "is_valid:true\n",
    )
    values = _valid_values()
    values["openid.op_endpoint"] = "https://evil.example/openid"
    with pytest.raises(steam_openid.SteamOpenIDError):
        steam_openid.verify_response(values, RETURN_TO)


def test_verify_response_rejects_forged_claimed_id(monkeypatch):
    monkeypatch.setattr(
        steam_openid,
        "_post_form",
        lambda _url, _data: "is_valid:true\n",
    )
    values = _valid_values()
    forged = "https://steamcommunity.com/openid/id/not-a-steam-id"
    values["openid.claimed_id"] = forged
    values["openid.identity"] = forged
    with pytest.raises(steam_openid.SteamOpenIDError):
        steam_openid.verify_response(values, RETURN_TO)


def test_verify_response_rejects_identity_mismatch(monkeypatch):
    monkeypatch.setattr(
        steam_openid,
        "_post_form",
        lambda _url, _data: "is_valid:true\n",
    )
    values = _valid_values()
    values["openid.identity"] = (
        "https://steamcommunity.com/openid/id/76561198000000002"
    )
    with pytest.raises(steam_openid.SteamOpenIDError):
        steam_openid.verify_response(values, RETURN_TO)


def test_verify_response_requires_steam_confirmation(monkeypatch):
    monkeypatch.setattr(
        steam_openid,
        "_post_form",
        lambda _url, _data: "is_valid:false\n",
    )
    with pytest.raises(steam_openid.SteamOpenIDError):
        steam_openid.verify_response(_valid_values(), RETURN_TO)


def test_verify_response_handles_unavailable_steam(monkeypatch):
    def fake_post(_url, _data):
        raise URLError("offline")

    monkeypatch.setattr(steam_openid, "_post_form", fake_post)
    with pytest.raises(steam_openid.SteamOpenIDError) as error:
        steam_openid.verify_response(_valid_values(), RETURN_TO)

    assert error.value.code == "unavailable"
