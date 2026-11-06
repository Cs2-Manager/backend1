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


def compute_match_stats(summary, steam_id, *, fallback_mvps=0):
    """Calcula las estadísticas de un jugador para una demo normalizada."""
    steam_id = _sid(steam_id)
    if not steam_id:
        raise ValueError("steam_id is required")

    rounds = list(summary.get("rounds") or [])
    rounds_by_number = {
        _event_round(round_data): round_data for round_data in rounds
    }
    round_numbers = sorted(rounds_by_number)
    if not round_numbers:
        round_numbers = sorted(
            _group_by_round(summary.get("deaths")).keys()
            | _group_by_round(summary.get("hurts")).keys()
            | _group_by_round(summary.get("mvps")).keys()
        )

    deaths_by_round = _group_by_round(summary.get("deaths"))
    hurts_by_round = _group_by_round(summary.get("hurts"))
    mvps_by_round = _group_by_round(summary.get("mvps"))

    kills = deaths = assists = headshot_kills = 0
    damage = 0
    clutches = opening_kills = opening_deaths = kast_rounds = 0
    rounds_won = rounds_lost = 0

    for number in round_numbers:
        round_deaths = sorted(
            deaths_by_round.get(number, []),
            key=lambda event: _int(event.get("tick")),
        )
        player_team = normalize_side(
            (rounds_by_number.get(number) or {}).get("player_team")
        )

        round_kills = 0
        round_assists = 0
        for event in round_deaths:
            victim = _sid(event.get("victim", event.get("user_steamid")))
            attacker = _sid(
                event.get("attacker", event.get("attacker_steamid"))
            )
            assister = _sid(
                event.get("assister", event.get("assister_steamid"))
            )

            if attacker == steam_id and victim != steam_id:
                round_kills += 1
                if event.get("headshot"):
                    headshot_kills += 1
            if (
                assister == steam_id
                and attacker != steam_id
                and victim != steam_id
            ):
                round_assists += 1
            if victim == steam_id:
                deaths += 1

        kills += round_kills
        assists += round_assists

        for event in hurts_by_round.get(number, []):
            attacker = _sid(
                event.get("attacker", event.get("attacker_steamid"))
            )
            victim = _sid(event.get("victim", event.get("user_steamid")))
            if attacker == steam_id and victim != steam_id:
                damage += max(0, _int(event.get("damage", event.get("dmg_health"))))

        # Opening kill/death: primera muerte de la ronda.
        if round_deaths:
            first = round_deaths[0]
            if _sid(first.get("attacker", first.get("attacker_steamid"))) == steam_id:
                opening_kills += 1
            if _sid(first.get("victim", first.get("user_steamid"))) == steam_id:
                opening_deaths += 1

        # KAST: kill, asistencia, supervivencia o trade.
        player_death = next(
            (
                event
                for event in round_deaths
                if _sid(event.get("victim", event.get("user_steamid")))
                == steam_id
            ),
            None,
        )
        traded = False
        if player_death is not None:
            killer = _sid(
                player_death.get(
                    "attacker", player_death.get("attacker_steamid")
                )
            )
            death_tick = _int(player_death.get("tick"))
            if killer and killer != steam_id:
                for event in round_deaths:
                    if event is player_death:
                        continue
                    attacker = _sid(
                        event.get("attacker", event.get("attacker_steamid"))
                    )
                    victim = _sid(
                        event.get("victim", event.get("user_steamid"))
                    )
                    if victim != killer or attacker == steam_id:
                        continue
                    attacker_team = normalize_side(
                        event.get("attacker_team")
                    )
                    victim_team = normalize_side(event.get("victim_team"))
                    if attacker_team is not None and player_team is not None:
                        same_team = attacker_team == player_team
                    else:
                        same_team = (
                            victim_team is not None
                            and victim_team != player_team
                        )
                    tick = _int(event.get("tick"))
                    if (
                        same_team
                        and 0 <= tick - death_tick <= TRADE_WINDOW_TICKS
                    ):
                        traded = True
                        break

        survived = player_death is None
        if round_kills or round_assists or survived or traded:
            kast_rounds += 1

        # Clutch 1vX: el jugador queda solo, hay enemigos vivos y gana la ronda.
        clutches += _round_clutch(
            round_deaths,
            player_team,
            steam_id,
            _team_sizes(summary),
            (rounds_by_number.get(number) or {}).get("winner"),
        )

        winner = normalize_side(
            (rounds_by_number.get(number) or {}).get("winner")
        )
        if winner is not None and player_team is not None:
            if winner == player_team:
                rounds_won += 1
            else:
                rounds_lost += 1

    player_mvps = sum(
        1
        for event in summary.get("mvps") or []
        if _sid(event.get("steam_id", event.get("user_steamid"))) == steam_id
    )
    if not summary.get("mvps") and fallback_mvps:
        player_mvps = max(0, _int(fallback_mvps))

    rounds_played = len(round_numbers)
    known_rounds = rounds_won + rounds_lost
    if known_rounds and known_rounds == rounds_played:
        if rounds_won > rounds_lost:
            result = "WIN"
        elif rounds_lost > rounds_won:
            result = "LOSS"
        else:
            result = "DRAW"
    else:
        result = "UNKNOWN"

    return {
        "map_name": summary.get("map_name"),
        "played_at": summary.get("played_at"),
        "result": result,
        "team_score": rounds_won if known_rounds else None,
        "opponent_score": rounds_lost if known_rounds else None,
        "rounds_played": rounds_played,
        "rounds_won": rounds_won,
        "rounds_lost": rounds_lost,
        "kills": kills,
        "deaths": deaths,
        "assists": assists,
        "damage": damage,
        "headshot_kills": headshot_kills,
        "mvps": player_mvps,
        "clutches": clutches,
        "opening_kills": opening_kills,
        "opening_deaths": opening_deaths,
        "kast_rounds": kast_rounds,
        "adr": _float(_ratio(damage, rounds_played, 1), 1),
        "hs_percentage": _float(
            None if not kills else headshot_kills * 100 / kills, 1
        ),
        "kd": _float(None if not deaths else kills / deaths, 2),
        "kast_percentage": _float(
            None if not rounds_played else kast_rounds * 100 / rounds_played, 1
        ),
    }


def _round_clutch(deaths, player_team, steam_id, team_sizes, winner):
    if player_team not in SIDES:
        return 0
    winner = normalize_side(winner)
    if winner != player_team:
        return 0

    alive = dict(team_sizes)
    enemy_side = "T" if player_team == "CT" else "CT"
    player_alive = True
    clutch_possible = False

    for event in deaths:
        victim = _sid(event.get("victim", event.get("user_steamid")))
        victim_team = normalize_side(event.get("victim_team"))
        if victim_team not in alive:
            # Sin bando no se puede mantener el conteo: se descarta el clutch.
            return 0
        alive[victim_team] = max(0, alive[victim_team] - 1)
        if victim == steam_id:
            player_alive = False
        if player_alive and alive[player_team] == 1 and alive[enemy_side] >= 1:
            clutch_possible = True

    if player_alive and clutch_possible:
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
