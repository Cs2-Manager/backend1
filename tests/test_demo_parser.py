"""Contracts of the demo adapter without the optional native parser or network."""
import sys
from types import SimpleNamespace

import pytest

from app.services.matchmaking import demo_parser as adapter

STEAM_ID = "76561198000000001"


@pytest.fixture
def parser(monkeypatch):
    events = {
        "round_end": [{"tick": 100, "winner": "CT", "total_rounds_played": 1}],
        "player_death": [{"tick": 80, "victim": STEAM_ID, "attacker": 2.0,
                          "headshot": "true", "total_rounds_played": 1}],
        "player_hurt": [{"tick": 60, "victim_steamid": STEAM_ID,
                         "attacker": 2, "dmg_health": "35", "round": 1}],
        "round_mvp": [{"steamid": STEAM_ID, "round": 1}],
    }
    instance = SimpleNamespace(
        parse_header=lambda: {"map_name": " de_mirage "},
        parse_event=lambda name, **kwargs: events[name],
        parse_ticks=lambda fields, **kwargs: [{"tick": 100, "team_name": "CT", "mvps": 2}],
    )
    monkeypatch.setitem(sys.modules, "demoparser2", SimpleNamespace(DemoParser=lambda path: instance))
    return instance, events


def test_parse_demo_normalizes_all_event_types(parser):
    assert adapter.parse_demo("fixture.dem", STEAM_ID) == {
        "map_name": "de_mirage", "played_at": None,
        "rounds": [{"number": 1, "winner": "CT", "player_team": "CT"}],
        "deaths": [{"round": 1, "tick": 80, "victim": STEAM_ID, "attacker": "2",
                    "assister": None, "headshot": True, "victim_team": "CT", "attacker_team": None}],
        "hurts": [{"round": 1, "tick": 60, "attacker": "2", "victim": STEAM_ID, "damage": 35}],
        "mvps": [{"round": 1, "steam_id": STEAM_ID}],
        "fallback_mvps": 2, "team_sizes": {"CT": 5, "T": 5},
    }


@pytest.mark.parametrize("value,expected", [(None, None), (True, None), (123.5, None),
                                             (123.0, "123"), (123, "123"), ("123.0", "123"),
                                             (" abc ", "abc"), ("", None), (float("nan"), None)])
def test_steam_identity_normalization(value, expected):
    assert adapter._sid(value) == expected


def test_demo_requires_rounds(parser):
    parser[1]["round_end"] = []
    with pytest.raises(adapter.DemoParseError, match="no contiene rondas"):
        adapter.parse_demo("fixture.dem", STEAM_ID)


def test_demo_requires_identity_before_loading_native_module():
    with pytest.raises(adapter.DemoParseError, match="SteamID asociado"):
        adapter.parse_demo("fixture.dem", None)


def test_optional_team_lookup_failure_is_tolerated(parser):
    def unavailable(*args, **kwargs):
        raise RuntimeError("unsupported property")
    parser[0].parse_ticks = unavailable
    result = adapter.parse_demo("fixture.dem", STEAM_ID)
    assert result["rounds"][0]["player_team"] is None
    assert result["fallback_mvps"] == 0


def test_event_falls_back_to_unfiltered_call():
    def parse_event(name, **kwargs):
        if kwargs:
            raise TypeError("unsupported arguments")
        return [{"tick": 1}]
    assert adapter._parse_event(SimpleNamespace(parse_event=parse_event), "round_end", other=["round"]) == [{"tick": 1}]


def test_unreadable_fallback_event_is_a_controlled_error():
    def parse_event(*args, **kwargs):
        raise ValueError("corrupt event")
    with pytest.raises(adapter.DemoParseError, match="evento round_end"):
        adapter._parse_event(SimpleNamespace(parse_event=parse_event), "round_end", other=["round"])
