"""Persistencia y agregación de partidas reales.

En esta fase no existe matchmaking ni una fuente externa de estadísticas. Este
servicio deja preparada la escritura transaccional del historial y mantiene los
agregados globales y por mapa sin generar valores ficticios.
"""

from datetime import datetime, timezone

from sqlalchemy import func

from app.errors import ApiError
from app.extensions import db
from app.models.map import Map
from app.models.player_profile import (
    MATCH_RESULTS,
    MATCH_TYPES,
    PlayerMapStats,
    PlayerMatch,
    PlayerStats,
)
from app.validators import clean_str, parse_non_negative_int


def _utcnow():
    return datetime.now(timezone.utc)


def _parse_optional_int(value, field, errors):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        errors[field] = f"{field} must be an integer"
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        errors[field] = f"{field} must be an integer"
        return None


def _parse_played_at(value, errors):
    if value is None or value == "":
        return _utcnow()
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        errors["played_at"] = "played_at must be an ISO 8601 datetime"
        return None


def ensure_stats(profile):
    """Devuelve el agregado global, creándolo para perfiles antiguos."""
    if profile.stats is not None:
        return profile.stats

    stats = PlayerStats(profile=profile)
    db.session.add(stats)
    db.session.commit()
    return stats


def matches_query(profile):
    """Consulta base del historial, ordenada de más reciente a más antigua."""
    return (
        db.session.query(PlayerMatch)
        .filter(PlayerMatch.profile_id == profile.id)
        .order_by(PlayerMatch.played_at.desc(), PlayerMatch.id.desc())
    )


def list_matches(profile, limit=None):
    query = matches_query(profile)
    if limit is not None:
        query = query.limit(limit)
    return query.all()


def map_performance(profile):
    """Rendimiento por mapa derivado de partidas reales registradas."""
    return (
        db.session.query(PlayerMapStats)
        .join(Map, PlayerMapStats.map_id == Map.id)
        .filter(
            PlayerMapStats.profile_id == profile.id,
            PlayerMapStats.matches_played > 0,
        )
        .order_by(PlayerMapStats.matches_played.desc(), Map.name)
        .all()
    )


def _apply_result(aggregate, result):
    aggregate.matches_played = (aggregate.matches_played or 0) + 1
    if result == "WIN":
        aggregate.wins = (aggregate.wins or 0) + 1
    elif result == "LOSS":
        aggregate.losses = (aggregate.losses or 0) + 1
    else:
        aggregate.draws = (aggregate.draws or 0) + 1


def _apply_counters(aggregate, match):
    aggregate.kills = (aggregate.kills or 0) + match.kills
    aggregate.deaths = (aggregate.deaths or 0) + match.deaths
    aggregate.assists = (aggregate.assists or 0) + match.assists
    aggregate.headshots = (aggregate.headshots or 0) + match.headshots
    aggregate.rounds_played = (aggregate.rounds_played or 0) + match.rounds_played
    aggregate.total_damage = (aggregate.total_damage or 0) + match.damage
    aggregate.updated_at = _utcnow()


def _update_aggregates(profile, match):
    stats = ensure_stats(profile)
    _apply_result(stats, match.result)
    _apply_counters(stats, match)

    if match.map_id is None:
        return

    map_stats = (
        db.session.query(PlayerMapStats)
        .filter_by(profile_id=profile.id, map_id=match.map_id)
        .first()
    )
    if map_stats is None:
        map_stats = PlayerMapStats(profile_id=profile.id, map_id=match.map_id)
        db.session.add(map_stats)
    _apply_result(map_stats, match.result)
    _apply_counters(map_stats, match)


def record_match(profile, data):
    """Registra una partida real y actualiza los agregados en la misma transacción."""
    errors = {}
    map_id = None
    raw_map_id = data.get("map_id")
    if raw_map_id not in (None, ""):
        try:
            map_id = int(raw_map_id)
        except (TypeError, ValueError):
            errors["map_id"] = "map_id must be an integer"
        else:
            if db.session.get(Map, map_id) is None:
                errors["map_id"] = "map not found"

    played_at = _parse_played_at(data.get("played_at"), errors)

    result = clean_str(data.get("result")).upper()
    if not result:
        errors["result"] = "result is required"
    elif result not in MATCH_RESULTS:
        errors["result"] = f"result must be one of {', '.join(MATCH_RESULTS)}"

    match_type = clean_str(data.get("match_type")).upper() or "COMPETITIVE"
    if match_type not in MATCH_TYPES:
        errors["match_type"] = (
            f"match_type must be one of {', '.join(MATCH_TYPES)}"
        )

    kills = parse_non_negative_int(data.get("kills"), "kills", errors)
    deaths = parse_non_negative_int(data.get("deaths"), "deaths", errors)
    assists = parse_non_negative_int(data.get("assists"), "assists", errors)
    headshots = parse_non_negative_int(
        data.get("headshots"), "headshots", errors
    )
    rounds_played = parse_non_negative_int(
        data.get("rounds_played"), "rounds_played", errors
    )
    damage = parse_non_negative_int(data.get("damage"), "damage", errors)
    elo_before = _parse_optional_int(data.get("elo_before"), "elo_before", errors)
    elo_after = _parse_optional_int(data.get("elo_after"), "elo_after", errors)

    if headshots > kills:
        errors["headshots"] = "headshots cannot exceed kills"

    if errors:
        raise ApiError("Invalid match", status_code=400, fields=errors)

    match = PlayerMatch(
        profile_id=profile.id,
        map_id=map_id,
        played_at=played_at,
        match_type=match_type,
        result=result,
        kills=kills,
        deaths=deaths,
        assists=assists,
        headshots=headshots,
        rounds_played=rounds_played,
        damage=damage,
        elo_before=elo_before,
        elo_after=elo_after,
    )
    db.session.add(match)
    _update_aggregates(profile, match)
    db.session.commit()
    return match


def total_matches(profile):
    return (
        db.session.query(func.count(PlayerMatch.id))
        .filter(PlayerMatch.profile_id == profile.id)
        .scalar()
        or 0
    )
