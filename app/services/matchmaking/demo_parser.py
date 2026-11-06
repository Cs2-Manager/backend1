"""Adaptador entre `demoparser2` y las estadísticas normalizadas.

`demoparser2` se instala solo en la imagen del worker (Rust + wheels
manylinux). El backend no lo importa: así la API sigue siendo liviana y puede
funcionar sin la dependencia nativa.

La demo se convierte a la estructura que consume `stats.py`. Las columnas que
agrega `demoparser2` se detectan de forma tolerante porque cambian entre
versiones (por ejemplo `user_team_name` frente a `user_team`).
"""

import math
from datetime import datetime, timezone

from app.services.matchmaking.stats import normalize_side


class DemoParseError(Exception):
    """La demo está corrupta, incompleta o no se pudo interpretar."""


def played_at_from_match_id(match_id):
    """Aproxima la fecha de la partida desde el match id (segundos en 32 bits).

    El match id de CS2 codifica el Unix time en sus 32 bits altos. Se usa solo
    como referencia; si el valor no es plausible se deja `None`.
    """
    try:
        number = int(match_id)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    seconds = number >> 32
    if seconds < 1_300_000_000 or seconds > 4_100_000_000:
        return None
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def _clean(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return value


def _sid(value):
    value = _clean(value)
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not value.is_integer():
            return None
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text or None


def _int(value, default=None):
    value = _clean(value)
    if value is None:
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _bool(value):
    value = _clean(value)
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in ("1", "true", "yes")


def _records(frame):
    if frame is None:
        return []
    if hasattr(frame, "to_dict"):
        try:
            return frame.to_dict("records")
        except TypeError:
            pass
    return list(frame)


def _pick(row, *names):
    for name in names:
        if name in row:
            value = _clean(row[name])
            if value is not None:
                return value
    return None


def _parse_event(parser, name, *, player=None, other=None):
    kwargs = {}
    if player:
        kwargs["player"] = player
    if other:
        kwargs["other"] = other
    try:
        return _records(parser.parse_event(name, **kwargs))
    except Exception:  # noqa: BLE001 - compatibilidad entre versiones
        if kwargs:
            try:
                return _records(parser.parse_event(name))
            except Exception as error:  # noqa: BLE001
                raise DemoParseError(
                    f"No se pudo leer el evento {name}"
                ) from error
        raise


def _round_teams(parser, steam_id, round_end_ticks):
    """Bando del jugador al final de cada ronda (los equipos cambian)."""
    if not round_end_ticks:
        return {}
    try:
        frame = parser.parse_ticks(
            ["team_name"], player=[int(steam_id)], ticks=round_end_ticks
        )
    except Exception:  # noqa: BLE001
        return {}
    teams = {}
    for row in _records(frame):
        tick = _int(row.get("tick"))
        team = normalize_side(_pick(row, "team_name", "user_team_name"))
        if tick is not None and team is not None:
            teams[tick] = team
    return teams


def _fallback_mvps(parser, steam_id, tick):
    try:
        frame = parser.parse_ticks(
            ["mvps"], player=[int(steam_id)], ticks=[tick]
        )
    except Exception:  # noqa: BLE001
        return 0
    for row in _records(frame):
        return max(0, _int(_pick(row, "mvps"), 0) or 0)
    return 0


def parse_demo(path, steam_id, *, match_id=None):
    """Parsea una demo local y devuelve el resumen normalizado."""
    steam_id = _sid(steam_id)
    if not steam_id:
        raise DemoParseError("La partida no tiene un SteamID asociado")

    try:
        from demoparser2 import DemoParser
    except ImportError as error:  # pragma: no cover - solo en el worker
        raise DemoParseError(
            "demoparser2 no está instalado; ejecutá el worker de matchmaking"
        ) from error

    try:
        parser = DemoParser(str(path))
        header = parser.parse_header() or {}
    except Exception as error:  # noqa: BLE001
        raise DemoParseError("Demo corrupta o ilegible") from error

    map_name = _clean(
        header.get("map_name") if isinstance(header, dict) else None
    )

    round_events = _parse_event(
        parser, "round_end", other=["total_rounds_played"]
    )
    if not round_events:
        raise DemoParseError("La demo no contiene rondas jugadas")

    round_ticks = []
    for row in round_events:
        tick = _int(row.get("tick"))
        if tick is not None:
            round_ticks.append(tick)
    team_by_tick = _round_teams(parser, steam_id, sorted(set(round_ticks)))

    rounds = []
    for index, row in enumerate(round_events):
        number = _int(
            _pick(row, "total_rounds_played", "round"), default=index
        )
        tick = _int(row.get("tick"))
        rounds.append(
            {
                "number": number,
                "winner": _clean(_pick(row, "winner", "team")),
                "player_team": team_by_tick.get(tick),
            }
        )

    round_team_by_number = {
        round_data["number"]: round_data["player_team"]
        for round_data in rounds
        if round_data["player_team"]
    }

    deaths = []
    for row in _parse_event(
        parser,
        "player_death",
        player=["team_name"],
        other=["total_rounds_played"],
    ):
        number = _int(_pick(row, "total_rounds_played", "round"), 0)
        victim_team = normalize_side(
            _pick(row, "user_team_name", "user_team")
        )
        attacker_team = normalize_side(
            _pick(row, "attacker_team_name", "attacker_team")
        )
        victim = _sid(_pick(row, "user_steamid", "victim_steamid", "victim"))
        if victim_team is None and victim == steam_id:
            victim_team = round_team_by_number.get(number)
        deaths.append(
            {
                "round": number,
                "tick": _int(row.get("tick"), 0),
                "victim": victim,
                "attacker": _sid(
                    _pick(row, "attacker_steamid", "attacker")
                ),
                "assister": _sid(
                    _pick(row, "assister_steamid", "assister")
                ),
                "headshot": _bool(_pick(row, "headshot")),
                "victim_team": victim_team,
                "attacker_team": attacker_team,
            }
        )

    hurts = []
    for row in _parse_event(
        parser, "player_hurt", other=["total_rounds_played"]
    ):
        hurts.append(
            {
                "round": _int(_pick(row, "total_rounds_played", "round"), 0),
                "tick": _int(row.get("tick"), 0),
                "attacker": _sid(
                    _pick(row, "attacker_steamid", "attacker")
                ),
                "victim": _sid(_pick(row, "user_steamid", "victim_steamid")),
                "damage": _int(_pick(row, "dmg_health", "damage"), 0) or 0,
            }
        )

    mvps = []
    for row in _parse_event(
        parser, "round_mvp", other=["total_rounds_played"]
    ):
        mvps.append(
            {
                "round": _int(_pick(row, "total_rounds_played", "round"), 0),
                "steam_id": _sid(
                    _pick(row, "user_steamid", "steamid", "player_steamid")
                ),
            }
        )

    max_tick = max(round_ticks) if round_ticks else 0
    fallback_mvps = (
        _fallback_mvps(parser, steam_id, max_tick) if max_tick else 0
    )

    return {
        "map_name": map_name,
        "played_at": played_at_from_match_id(match_id),
        "rounds": rounds,
        "deaths": deaths,
        "hurts": hurts,
        "mvps": mvps,
        "fallback_mvps": fallback_mvps,
        "team_sizes": {"CT": 5, "T": 5},
    }
