"""Steam API transport and defensive payload normalization, no external requests."""
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.error import HTTPError, URLError

import pytest

from app.services import steam_api

STEAM_ID = "76561198000000001"


@pytest.mark.parametrize("payload,code", [
    ([], "not_found"), ({"response": []}, "not_found"),
    ({"response": {"players": []}}, "not_found"),
    ({"response": {"players": [None]}}, "invalid_response"),
    ({"response": {"players": [{"steamid": "other"}]}}, "invalid_response"),
])
def test_summary_rejects_malformed_or_mismatched_identity(app, monkeypatch, payload, code):
    monkeypatch.setattr(steam_api, "_get_json", lambda *a: payload)
    with pytest.raises(steam_api.SteamApiError) as error:
        steam_api.fetch_player_summaries(STEAM_ID)
    assert error.value.code == code


def test_summary_normalizes_verified_identity(app, monkeypatch):
    player = {"steamid": STEAM_ID, "personaname": " Tester ", "personastate": "1",
              "communityvisibilitystate": 3, "timecreated": "42", "lastlogoff": -1}
    monkeypatch.setattr(steam_api, "_get_json", lambda *a: {"response": {"players": [player]}})
    assert steam_api.fetch_player_summaries(STEAM_ID) == {
        "steam_id": STEAM_ID, "persona_name": "Tester", "profile_url": None,
        "avatar_url": None, "avatar_medium_url": None, "avatar_full_url": None,
        "persona_state": None, "community_visibility_state": 3,
        "profile_created_at": 42, "last_logoff_at": None,
    }


@pytest.mark.parametrize("payload,expected", [
    ({"response": {}}, None),
    ({"response": {"games": [], "game_count": 0}}, {"games": [], "game_count": 0}),
])
def test_private_library_is_not_an_empty_owned_library(app, monkeypatch, payload, expected):
    monkeypatch.setattr(steam_api, "_get_json", lambda *a: payload)
    assert steam_api.fetch_owned_games(STEAM_ID) == expected


@pytest.mark.parametrize("payload", [[], {}, {"response": []}, {"response": {"games": None}}])
def test_invalid_library_shape_is_rejected(app, monkeypatch, payload):
    monkeypatch.setattr(steam_api, "_get_json", lambda *a: payload)
    with pytest.raises(steam_api.SteamApiError) as error:
        steam_api.fetch_owned_games(STEAM_ID)
    assert error.value.code == "invalid_response"


def test_library_filters_wrong_app_and_invalid_records(app, monkeypatch):
    games = [None, {"appid": "bad"}, {"appid": 1},
             {"appid": "730", "name": " CS2 ", "playtime_forever": "120", "playtime_2weeks": -1}]
    monkeypatch.setattr(steam_api, "_get_json", lambda *a: {"response": {"games": games, "game_count": 1}})
    assert steam_api.fetch_owned_games(STEAM_ID) == {
        "game_count": 1, "games": [{"app_id": 730, "name": "CS2", "playtime_forever_minutes": 120,
                                  "playtime_two_weeks_minutes": None, "last_played": None, "img_icon_url": None}],
    }


@pytest.mark.parametrize("status,code", [(403, "forbidden"), (429, "rate_limited"), (500, "http_error")])
def test_transport_http_error_taxonomy(app, monkeypatch, status, code):
    def unavailable(*args, **kwargs):
        raise HTTPError("https://steam.test", status, "upstream", None, None)
    monkeypatch.setattr(steam_api, "urlopen", unavailable)
    with pytest.raises(steam_api.SteamApiError) as error:
        steam_api._get_json("https://steam.test", {})
    assert error.value.code == code


def test_transport_invalid_json(app, monkeypatch):
    response = MagicMock()
    response.__enter__.return_value = SimpleNamespace(read=lambda: b'not-json')
    monkeypatch.setattr(steam_api, "urlopen", lambda *a, **kw: response)
    with pytest.raises(steam_api.SteamApiError) as error:
        steam_api._get_json("https://steam.test", {})
    assert error.value.code == "invalid_response"


def test_transport_network_error(app, monkeypatch):
    def unavailable(*args, **kwargs):
        raise URLError("offline")
    monkeypatch.setattr(steam_api, "urlopen", unavailable)
    with pytest.raises(steam_api.SteamApiError) as error:
        steam_api._get_json("https://steam.test", {})
    assert error.value.code == "unavailable"
