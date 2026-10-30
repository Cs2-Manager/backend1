"""Serializadores del perfil competitivo.

La separación público/privado es explícita: el serializador público nunca
incluye email, hash de contraseña ni privilegios administrativos.
"""


def _iso(value):
    return value.isoformat() if value is not None else None


def _ratio(numerator, denominator, digits=2):
    if not denominator:
        return None
    return round(numerator / denominator, digits)


def serialize_competitive(competitive):
    """Datos competitivos verificados. Los campos sin fuente quedan en null."""
    level = getattr(competitive, "level", None)
    elo = getattr(competitive, "elo", None)
    xp = getattr(competitive, "xp", None)
    status = getattr(competitive, "status", None) or "UNRANKED"

    return {
        "status": status,
        "ranked": elo is not None,
        "level": level,
        "elo": elo,
        "xp": xp,
        "xp_to_next_level": None,
        "ranking_position": None,
    }


def serialize_stats(stats):
    """Agregados reales. `has_data` evita mostrar ceros como si fueran datos."""
    matches_played = getattr(stats, "matches_played", 0) or 0
    wins = getattr(stats, "wins", 0) or 0
    losses = getattr(stats, "losses", 0) or 0
    draws = getattr(stats, "draws", 0) or 0
    kills = getattr(stats, "kills", 0) or 0
    deaths = getattr(stats, "deaths", 0) or 0
    assists = getattr(stats, "assists", 0) or 0
    headshots = getattr(stats, "headshots", 0) or 0
    rounds_played = getattr(stats, "rounds_played", 0) or 0
    total_damage = getattr(stats, "total_damage", 0) or 0

    return {
        "has_data": matches_played > 0,
        "matches_played": matches_played,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "kills": kills,
        "deaths": deaths,
        "assists": assists,
        "headshots": headshots,
        "rounds_played": rounds_played,
        "total_damage": total_damage,
        "kd": _ratio(kills, deaths),
        "kr": _ratio(kills, rounds_played),
        "adr": _ratio(total_damage, rounds_played, 1),
        "headshot_percentage": _ratio(headshots * 100, kills, 1),
        "win_rate": _ratio(wins * 100, matches_played, 1),
    }


def serialize_match(match):
    map_obj = match.map
    return {
        "id": match.id,
        "played_at": _iso(match.played_at),
        "match_type": match.match_type,
        "result": match.result,
        "map": (
            {"id": map_obj.id, "name": map_obj.name} if map_obj is not None else None
        ),
        "kills": match.kills,
        "deaths": match.deaths,
        "assists": match.assists,
        "headshots": match.headshots,
        "rounds_played": match.rounds_played,
        "damage": match.damage,
        "kd": _ratio(match.kills, match.deaths),
        "adr": _ratio(match.damage, match.rounds_played, 1),
        "headshot_percentage": _ratio(match.headshots * 100, match.kills, 1),
        "elo_before": match.elo_before,
        "elo_after": match.elo_after,
    }


def serialize_map_performance(row):
    map_obj = row.map
    return {
        "map": {"id": map_obj.id, "name": map_obj.name},
        **serialize_stats(row),
    }


def serialize_social_links(profile):
    return {link.platform: link.url for link in profile.social_links}


def _profile_base(profile):
    user = profile.user
    return {
        "id": user.id,
        "username": user.username,
        "nickname": profile.nickname,
        "display_name": profile.display_name,
        "avatar_url": profile.avatar_url,
        "country": profile.country,
        "bio": profile.bio,
        "steam_url": profile.steam_url,
        "social_links": serialize_social_links(profile),
        "member_since": _iso(user.created_at),
        "last_active_at": _iso(profile.last_active_at),
    }


def _profile_sections(profile, stats, map_performance, recent_matches):
    return {
        "competitive": serialize_competitive(profile.competitive),
        "stats": serialize_stats(stats),
        "map_performance": [
            serialize_map_performance(row) for row in map_performance
        ],
        "recent_matches": [serialize_match(match) for match in recent_matches],
        "matches_total": getattr(stats, "matches_played", 0) or 0,
    }


def serialize_profile_public(
    profile, *, stats, map_performance, recent_matches
):
    """Perfil visible por terceros: sin email, hash ni privilegios."""
    return {
        **_profile_base(profile),
        "is_owner": False,
        **_profile_sections(profile, stats, map_performance, recent_matches),
    }


def serialize_profile_owner(profile, *, stats, map_performance, recent_matches):
    """Perfil propio: agrega email y configuración de privacidad."""
    return {
        **_profile_base(profile),
        "email": profile.user.email,
        "visibility": profile.visibility,
        "is_owner": True,
        **_profile_sections(profile, stats, map_performance, recent_matches),
    }


def serialize_profile_summary(profile, stats):
    """Resumen para listados públicos de jugadores."""
    return {
        "id": profile.user_id,
        "username": profile.user.username,
        "nickname": profile.nickname,
        "display_name": profile.display_name,
        "avatar_url": profile.avatar_url,
        "country": profile.country,
        "competitive": serialize_competitive(profile.competitive),
        "stats": serialize_stats(stats),
    }
