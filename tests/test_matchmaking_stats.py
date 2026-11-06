"""Pruebas de las fórmulas de estadísticas por partida y agregados."""

from types import SimpleNamespace

from app.services.matchmaking.stats import (
    aggregate_matches,
    build_map_aggregates,
    compute_match_stats,
)

PLAYER = "76561198000000001"
MATE = "76561198000000002"
ENEMY = "76561198000000003"
ENEMY2 = "76561198000000004"
ENEMY3 = "76561198000000005"


def _death(round_number, tick, victim, attacker, *, headshot=False,
           victim_team=None, attacker_team=None, assister=None):
    return {
        "round": round_number,
        "tick": tick,
        "victim": victim,
        "attacker": attacker,
        "assister": assister,
        "headshot": headshot,
        "victim_team": victim_team,
        "attacker_team": attacker_team,
    }


def _summary():
    return {
        "map_name": "de_mirage",
        "played_at": None,
        "team_sizes": {"CT": 5, "T": 5},
        "rounds": [
            {"number": 0, "winner": "CT", "player_team": "CT"},
            {"number": 1, "winner": "CT", "player_team": "T"},
            {"number": 2, "winner": "T", "player_team": "T"},
        ],
        "deaths": [
            # Ronda 0: opening kill del jugador y muerte con trade.
            _death(0, 100, ENEMY, PLAYER, headshot=True,
                   victim_team="T", attacker_team="CT"),
            _death(0, 200, PLAYER, ENEMY2,
                   victim_team="CT", attacker_team="T"),
            _death(0, 250, ENEMY2, MATE,
                   victim_team="T", attacker_team="CT"),
            # Ronda 1: el jugador sobrevive y su equipo pierde.
            _death(1, 100, MATE, ENEMY,
                   victim_team="T", attacker_team="CT"),
            # Ronda 2: 1v5 ganado (clutch).
            _death(2, 100, MATE, ENEMY,
                   victim_team="T", attacker_team="CT"),
            _death(2, 104, "76561198000000010", ENEMY,
                   victim_team="T", attacker_team="CT"),
            _death(2, 106, "76561198000000011", ENEMY2,
                   victim_team="T", attacker_team="CT"),
            _death(2, 108, "76561198000000012", ENEMY3,
                   victim_team="T", attacker_team="CT"),
            _death(2, 110, ENEMY, PLAYER,
                   victim_team="CT", attacker_team="T"),
            _death(2, 120, ENEMY2, PLAYER,
                   victim_team="CT", attacker_team="T"),
            _death(2, 130, ENEMY3, PLAYER,
                   victim_team="CT", attacker_team="T"),
            _death(2, 140, "76561198000000013", PLAYER,
                   victim_team="CT", attacker_team="T"),
            _death(2, 150, "76561198000000014", PLAYER,
                   victim_team="CT", attacker_team="T"),
        ],
        "hurts": [
            {"round": 0, "tick": 90, "attacker": PLAYER,
             "victim": ENEMY, "damage": 80},
            {"round": 0, "tick": 190, "attacker": ENEMY2,
             "victim": PLAYER, "damage": 100},
        ],
        "mvps": [{"round": 0, "steam_id": PLAYER}],
    }


def test_compute_match_stats_counts_events_once():
    result = compute_match_stats(_summary(), PLAYER)

    assert result["map_name"] == "de_mirage"
    assert result["rounds_played"] == 3
    assert result["rounds_won"] == 2
    assert result["rounds_lost"] == 1
    assert result["result"] == "WIN"
    assert result["team_score"] == 2
    assert result["opponent_score"] == 1
    assert result["kills"] == 6
    assert result["deaths"] == 1
    assert result["assists"] == 0
    assert result["headshot_kills"] == 1
    assert result["damage"] == 80
    assert result["mvps"] == 1
    assert result["opening_kills"] == 1
    assert result["opening_deaths"] == 0
    assert result["clutches"] == 1
    assert result["kast_rounds"] == 3
    assert result["kast_percentage"] == 100.0
    assert result["kd"] == 6.0
    assert result["adr"] == 26.7
    assert result["hs_percentage"] == 16.7


def test_trade_grants_kast_without_kill_or_assist():
    summary = {
        "map_name": "de_dust2",
        "rounds": [
            {"number": 0, "winner": "CT", "player_team": "CT"},
            {"number": 1, "winner": "CT", "player_team": "CT"},
        ],
        "deaths": [
            # Ronda 0: muere y un compañero mata al asesino dentro de la ventana.
            _death(0, 500, PLAYER, ENEMY, victim_team="CT", attacker_team="T"),
            _death(0, 600, ENEMY, MATE, victim_team="T", attacker_team="CT"),
            # Ronda 1: muere sin trade.
            _death(1, 500, PLAYER, ENEMY, victim_team="CT", attacker_team="T"),
        ],
        "hurts": [],
        "mvps": [],
    }

    result = compute_match_stats(summary, PLAYER)

    assert result["deaths"] == 2
    assert result["kast_rounds"] == 1
    assert result["kast_percentage"] == 50.0


def test_trade_outside_window_does_not_count():
    summary = {
        "map_name": "de_dust2",
        "rounds": [{"number": 0, "winner": "CT", "player_team": "CT"}],
        "deaths": [
            _death(0, 100, PLAYER, ENEMY, victim_team="CT", attacker_team="T"),
            _death(0, 500, ENEMY, MATE, victim_team="T", attacker_team="CT"),
        ],
        "hurts": [],
        "mvps": [],
    }

    assert compute_match_stats(summary, PLAYER)["kast_rounds"] == 0


def test_draw_and_unknown_result():
    draw = {
        "map_name": "de_nuke",
        "rounds": [
            {"number": 0, "winner": "CT", "player_team": "CT"},
            {"number": 1, "winner": "T", "player_team": "CT"},
        ],
        "deaths": [],
        "hurts": [],
        "mvps": [],
    }
    assert compute_match_stats(draw, PLAYER)["result"] == "DRAW"

    unknown = {
        "map_name": "de_nuke",
        "rounds": [{"number": 0, "winner": None, "player_team": "CT"}],
        "deaths": [],
        "hurts": [],
        "mvps": [],
    }
    assert compute_match_stats(unknown, PLAYER)["result"] == "UNKNOWN"


def test_no_rounds_or_events_returns_zeroes():
    result = compute_match_stats(
        {"map_name": None, "rounds": [], "deaths": [], "hurts": [], "mvps": []},
        PLAYER,
    )

    assert result["rounds_played"] == 0
    assert result["kills"] == 0
    assert result["adr"] is None
    assert result["hs_percentage"] is None
    assert result["kd"] is None
    assert result["kast_percentage"] is None


def _row(**overrides):
    payload = {
        "map_name": "de_mirage",
        "result": "WIN",
        "rounds_played": 20,
        "rounds_won": 13,
        "rounds_lost": 7,
        "kills": 20,
        "deaths": 10,
        "assists": 5,
        "damage": 1600,
        "headshot_kills": 8,
        "mvps": 4,
        "clutches": 1,
        "opening_kills": 3,
        "opening_deaths": 2,
        "kast_rounds": 14,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_aggregate_uses_weighted_denominators():
    first = _row()
    second = _row(
        map_name="de_dust2",
        result="LOSS",
        rounds_played=30,
        rounds_won=10,
        rounds_lost=20,
        kills=30,
        deaths=20,
        assists=10,
        damage=2400,
        headshot_kills=12,
        kast_rounds=24,
    )

    aggregate = aggregate_matches([first, second])

    assert aggregate["matches_played"] == 2
    assert aggregate["wins"] == 1
    assert aggregate["losses"] == 1
    assert aggregate["rounds_played"] == 50
    assert aggregate["kills"] == 50
    assert aggregate["deaths"] == 30
    # Promediar porcentajes daría (70 + 80) / 2 = 75; ponderado es 76.
    assert aggregate["kast_percentage"] == 76.0
    # Promediar ADR daría (80 + 80) / 2 = 80; acá coincide, pero se calcula
    # sobre 4000 de daño y 50 rondas.
    assert aggregate["adr"] == 80.0
    assert aggregate["kd"] == 1.67
    assert aggregate["hs_percentage"] == 40.0
    assert aggregate["win_rate"] == 50.0
    assert aggregate["has_data"] is True


def test_aggregate_without_matches_has_no_data():
    aggregate = aggregate_matches([])

    assert aggregate["has_data"] is False
    assert aggregate["matches_played"] == 0
    assert aggregate["kd"] is None
    assert aggregate["adr"] is None


def test_build_map_aggregates_groups_and_sorts():
    rows = [
        _row(map_name="de_mirage"),
        _row(map_name="de_mirage", result="LOSS", rounds_played=30),
        _row(map_name="de_dust2"),
        _row(map_name=None),
    ]

    grouped = build_map_aggregates(rows)

    assert [row["map_name"] for row in grouped] == ["de_mirage", "de_dust2"]
    assert grouped[0]["matches_played"] == 2
    assert grouped[0]["rounds_played"] == 50
    assert grouped[1]["matches_played"] == 1
