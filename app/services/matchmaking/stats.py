"""Cálculo de estadísticas individuales a partir de eventos de una demo.

Este módulo es puro (no importa Flask ni el parser) para poder probarlo con
fixtures. El parser normaliza la demo a la estructura que consumen estas
funciones:

```python
{
    "map_name": "de_dust2",
    "played_at": datetime | None,
    "rounds": [
        {"number": 0, "winner": "CT", "player_team": "CT"},
        ...
    ],
    "deaths": [
        {
            "round": 0,
            "tick": 1234,
            "victim": "765...",
            "attacker": "765...",
            "assister": "765...",
            "headshot": True,
            "victim_team": "CT",
            "attacker_team": "T",
        },
        ...
    ],
    "hurts": [
        {"round": 0, "tick": 1235, "attacker": "765...",
         "victim": "765...", "damage": 27},
        ...
    ],
    "mvps": [{"round": 0, "steam_id": "765..."}, ...],
}
```

Los acumulados se calculan sumando numeradores y denominadores; nunca se
promedian porcentajes ni ADR de partidas distintas.
"""

TRADE_WINDOW_TICKS = 320
DEFAULT_TEAM_SIZE = 5

SIDES = ("CT", "T")
SIDE_ALIASES = {
    "CT": "CT",
    "COUNTER-TERRORIST": "CT",
    "COUNTERTERRORIST": "CT",
    "T": "T",
    "TERRORIST": "T",
    "TERRORISTS": "T",
}


def normalize_side(value):
    """Normaliza los nombres de bando que usan demoparser2/CS2."""
    if value is None:
        return None
    return SIDE_ALIASES.get(str(value).strip().upper())


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value, digits):
    if value is None:
        return None
    return round(float(value), digits)


def _sid(value):
    if value is None or value == "":
        return None
    return str(value)


def _ratio(numerator, denominator, digits):
    if not denominator:
        return None
    return round(numerator / denominator, digits)


def _event_round(event, fallback=0):
    for key in ("round", "number", "total_rounds_played"):
        value = event.get(key)
        if value is not None:
            return _int(value, fallback)
    return fallback


def _group_by_round(events):
    grouped = {}
    for event in events or []:
        grouped.setdefault(_event_round(event), []).append(event)
    return grouped


def _team_sizes(summary):
    sizes = summary.get("team_sizes") or {}
    return {
        "CT": max(1, _int(sizes.get("CT"), DEFAULT_TEAM_SIZE)),
        "T": max(1, _int(sizes.get("T"), DEFAULT_TEAM_SIZE)),
    }


def _event_ids(event):
    victim = _sid(event.get("victim", event.get("user_steamid")))
    attacker = _sid(event.get("attacker", event.get("attacker_steamid")))
    assister = _sid(event.get("assister", event.get("assister_steamid")))
    return victim, attacker, assister


def _event_attacker(event):
    return _sid(event.get("attacker", event.get("attacker_steamid")))


def _is_kill(event, steam_id):
    victim, attacker, _ = _event_ids(event)
    return attacker == steam_id and victim != steam_id


def _is_assist(event, steam_id):
    victim, attacker, assister = _event_ids(event)
    return (
        assister == steam_id
        and attacker != steam_id
        and victim != steam_id
    )


def _is_death(event, steam_id):
    victim, _, _ = _event_ids(event)
    return victim == steam_id


def _round_headshots(round_deaths, steam_id):
    return sum(
        1
        for event in round_deaths
        if event.get("headshot") and _is_kill(event, steam_id)
    )


def _round_kill_counts(round_deaths, steam_id):
    kills = sum(1 for event in round_deaths if _is_kill(event, steam_id))
    assists = sum(1 for event in round_deaths if _is_assist(event, steam_id))
    deaths = sum(1 for event in round_deaths if _is_death(event, steam_id))
    return kills, assists, _round_headshots(round_deaths, steam_id), deaths


def _round_damage(hurts, steam_id):
    total = 0
    for event in hurts:
        victim, attacker, _ = _event_ids(event)
        if attacker == steam_id and victim != steam_id:
            damage = event.get("damage", event.get("dmg_health"))
            total += max(0, _int(damage))
    return total


def _opening_counts(round_deaths, steam_id):
    if not round_deaths:
        return 0, 0
    victim, attacker, _ = _event_ids(round_deaths[0])
    return (
        1 if attacker == steam_id else 0,
        1 if victim == steam_id else 0,
    )


def _player_death(round_deaths, steam_id):
    for event in round_deaths:
        if _is_death(event, steam_id):
            return event
    return None


def _same_team(event, player_team):
    attacker_team = normalize_side(event.get("attacker_team"))
    victim_team = normalize_side(event.get("victim_team"))
    if attacker_team is not None and player_team is not None:
        return attacker_team == player_team
    return victim_team is not None and victim_team != player_team


def _trade_candidate(event, player_death, killer, steam_id):
    if event is player_death:
        return False
    victim, attacker, _ = _event_ids(event)
    return victim == killer and attacker != steam_id


def _is_trade(event, player_death, killer, player_team, steam_id, death_tick):
    if not _trade_candidate(event, player_death, killer, steam_id):
        return False
    if not _same_team(event, player_team):
        return False
    tick = _int(event.get("tick"))
    return 0 <= tick - death_tick <= TRADE_WINDOW_TICKS


def _trade_killer(player_death, steam_id):
    if player_death is None:
        return None
    killer = _event_attacker(player_death)
    if not killer or killer == steam_id:
        return None
    return killer


def _was_traded(round_deaths, player_death, player_team, steam_id):
    killer = _trade_killer(player_death, steam_id)
    if killer is None:
        return False
    death_tick = _int(player_death.get("tick"))
    return any(
        _is_trade(
            event, player_death, killer, player_team, steam_id, death_tick
        )
        for event in round_deaths
    )


def _round_outcome(winner, player_team):
    if winner is None or player_team is None:
        return 0, 0
    if winner == player_team:
        return 1, 0
    return 0, 1


def _kast_round(kills, assists, survived, traded):
    if kills or assists or survived or traded:
        return 1
    return 0


def _round_metrics(round_deaths, hurts, round_data, summary, steam_id):
    player_team = normalize_side((round_data or {}).get("player_team"))
    kills, assists, headshots, deaths = _round_kill_counts(
        round_deaths, steam_id
    )
    player_death = _player_death(round_deaths, steam_id)
    traded = _was_traded(round_deaths, player_death, player_team, steam_id)
    survived = player_death is None
    winner = normalize_side((round_data or {}).get("winner"))
    won, lost = _round_outcome(winner, player_team)
    opening_kills, opening_deaths = _opening_counts(round_deaths, steam_id)
    return {
        "kills": kills,
        "deaths": deaths,
        "assists": assists,
        "headshot_kills": headshots,
        "damage": _round_damage(hurts, steam_id),
        "clutches": _round_clutch(
            round_deaths,
            player_team,
            steam_id,
            _team_sizes(summary),
            (round_data or {}).get("winner"),
        ),
        "opening_kills": opening_kills,
        "opening_deaths": opening_deaths,
        "kast_rounds": _kast_round(kills, assists, survived, traded),
        "rounds_won": won,
        "rounds_lost": lost,
    }


def _new_totals():
    return {
        "kills": 0,
        "deaths": 0,
        "assists": 0,
        "headshot_kills": 0,
        "damage": 0,
        "clutches": 0,
        "opening_kills": 0,
        "opening_deaths": 0,
        "kast_rounds": 0,
        "rounds_won": 0,
        "rounds_lost": 0,
    }


def _add_round(totals, metrics):
    for key, value in metrics.items():
        totals[key] += value


def _rounds_by_number(summary):
    rounds = list(summary.get("rounds") or [])
    return {
        _event_round(round_data): round_data for round_data in rounds
    }


def _round_numbers(summary, rounds_by_number):
    numbers = sorted(rounds_by_number)
    if numbers:
        return numbers
    grouped = (
        _group_by_round(summary.get("deaths")).keys()
        | _group_by_round(summary.get("hurts")).keys()
        | _group_by_round(summary.get("mvps")).keys()
    )
    return sorted(grouped)


def _match_result(rounds_won, rounds_lost, rounds_played):
    known_rounds = rounds_won + rounds_lost
    if not known_rounds or known_rounds != rounds_played:
        return "UNKNOWN", known_rounds
    if rounds_won > rounds_lost:
        return "WIN", known_rounds
    if rounds_lost > rounds_won:
        return "LOSS", known_rounds
    return "DRAW", known_rounds


def _mvp_events(summary):
    return summary.get("mvps") or []


def _player_mvps(summary, steam_id, fallback_mvps):
    events = _mvp_events(summary)
    player_mvps = sum(
        1
        for event in events
        if _sid(event.get("steam_id", event.get("user_steamid"))) == steam_id
    )
    if not events and fallback_mvps:
        return max(0, _int(fallback_mvps))
    return player_mvps


def _optional_score(value, known_rounds):
    if known_rounds:
        return value
    return None


def _percentage(numerator, denominator, digits):
    if not denominator:
        return None
    return _float(numerator * 100 / denominator, digits)


def _stats_payload(summary, totals, rounds_played, known_rounds, result, mvps):
    kills = totals["kills"]
    deaths = totals["deaths"]
    return {
        "map_name": summary.get("map_name"),
        "played_at": summary.get("played_at"),
        "result": result,
        "team_score": _optional_score(totals["rounds_won"], known_rounds),
        "opponent_score": _optional_score(
            totals["rounds_lost"], known_rounds
        ),
        "rounds_played": rounds_played,
        "rounds_won": totals["rounds_won"],
        "rounds_lost": totals["rounds_lost"],
        "kills": kills,
        "deaths": deaths,
        "assists": totals["assists"],
        "damage": totals["damage"],
        "headshot_kills": totals["headshot_kills"],
        "mvps": mvps,
        "clutches": totals["clutches"],
        "opening_kills": totals["opening_kills"],
        "opening_deaths": totals["opening_deaths"],
        "kast_rounds": totals["kast_rounds"],
        "adr": _float(_ratio(totals["damage"], rounds_played, 1), 1),
        "hs_percentage": _percentage(totals["headshot_kills"], kills, 1),
        "kd": _ratio(kills, deaths, 2),
        "kast_percentage": _percentage(
            totals["kast_rounds"], rounds_played, 1
        ),
    }


def compute_match_stats(summary, steam_id, *, fallback_mvps=0):
    """Calcula las estadísticas de un jugador para una demo normalizada."""
    steam_id = _sid(steam_id)
    if not steam_id:
        raise ValueError("steam_id is required")

    rounds_by_number = _rounds_by_number(summary)
    round_numbers = _round_numbers(summary, rounds_by_number)
    deaths_by_round = _group_by_round(summary.get("deaths"))
    hurts_by_round = _group_by_round(summary.get("hurts"))

    totals = _new_totals()
    for number in round_numbers:
        round_deaths = sorted(
            deaths_by_round.get(number, []),
            key=lambda event: _int(event.get("tick")),
        )
        _add_round(
            totals,
            _round_metrics(
                round_deaths,
                hurts_by_round.get(number, []),
                rounds_by_number.get(number) or {},
                summary,
                steam_id,
            ),
        )

    rounds_played = len(round_numbers)
    result, known_rounds = _match_result(
        totals["rounds_won"], totals["rounds_lost"], rounds_played
    )
    mvps = _player_mvps(summary, steam_id, fallback_mvps)
    return _stats_payload(
        summary, totals, rounds_played, known_rounds, result, mvps
    )


def _clutch_teams(player_team, winner):
    if player_team not in SIDES:
        return None
    if normalize_side(winner) != player_team:
        return None
    return "T" if player_team == "CT" else "CT"


def _clutch_alive(alive, victim_team):
    alive[victim_team] = max(0, alive[victim_team] - 1)


def _clutch_possible(player_alive, alive, player_team, enemy_side):
    if not player_alive:
        return False
    return alive[player_team] == 1 and alive[enemy_side] >= 1


def _clutch_step(event, state):
    victim, _, _ = _event_ids(event)
    victim_team = normalize_side(event.get("victim_team"))
    if victim_team not in state["alive"]:
        return False
    _clutch_alive(state["alive"], victim_team)
    if victim == state["steam_id"]:
        state["player_alive"] = False
    return True


def _clutch_survives(deaths, state):
    possible = False
    for event in deaths:
        if not _clutch_step(event, state):
            return False
        possible = possible or _clutch_possible(
            state["player_alive"],
            state["alive"],
            state["player_team"],
            state["enemy_side"],
        )
    return state["player_alive"] and possible


def _round_clutch(deaths, player_team, steam_id, team_sizes, winner):
    enemy_side = _clutch_teams(player_team, winner)
    if enemy_side is None:
        return 0
    state = {
        "alive": dict(team_sizes),
        "player_alive": True,
        "player_team": player_team,
        "enemy_side": enemy_side,
        "steam_id": steam_id,
    }
    if _clutch_survives(deaths, state):
        return 1
    return 0


def _total(rows, field):
    return sum(max(0, _int(getattr(row, field, 0))) for row in rows)


def aggregate_matches(matches):
    """Agrega partidas procesadas con denominadores ponderados."""
    rows = list(matches or [])
    rounds = _total(rows, "rounds_played")
    kills = _total(rows, "kills")
    deaths = _total(rows, "deaths")
    assists = _total(rows, "assists")
    damage = _total(rows, "damage")
    headshots = _total(rows, "headshot_kills")
    kast = _total(rows, "kast_rounds")
    wins = sum(1 for row in rows if getattr(row, "result", None) == "WIN")
    losses = sum(1 for row in rows if getattr(row, "result", None) == "LOSS")
    draws = sum(1 for row in rows if getattr(row, "result", None) == "DRAW")
    played = len(rows)

    return {
        "has_data": played > 0,
        "matches_played": played,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "rounds_played": rounds,
        "rounds_won": _total(rows, "rounds_won"),
        "rounds_lost": _total(rows, "rounds_lost"),
        "kills": kills,
        "deaths": deaths,
        "assists": assists,
        "damage": damage,
        "headshot_kills": headshots,
        "mvps": _total(rows, "mvps"),
        "clutches": _total(rows, "clutches"),
        "opening_kills": _total(rows, "opening_kills"),
        "opening_deaths": _total(rows, "opening_deaths"),
        "kast_rounds": kast,
        "kd": _ratio(kills, deaths, 2),
        "adr": _ratio(damage, rounds, 1),
        "hs_percentage": _ratio(headshots * 100, kills, 1),
        "kast_percentage": _ratio(kast * 100, rounds, 1),
        "win_rate": _ratio(wins * 100, played, 1),
    }


def build_map_aggregates(matches):
    """Agrupa por mapa y agrega cada grupo de forma ponderada."""
    groups = {}
    for match in matches or []:
        map_name = getattr(match, "map_name", None)
        if not map_name:
            continue
        groups.setdefault(map_name, []).append(match)

    rows = []
    for map_name, group in groups.items():
        aggregate = aggregate_matches(group)
        rows.append({"map_name": map_name, **aggregate})
    return sorted(
        rows, key=lambda row: (-row["matches_played"], row["map_name"])
    )
