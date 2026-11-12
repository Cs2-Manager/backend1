"""Serializadores de la integración con Steam.

La separación es explícita para no presentar datos manuales como verificados:

- `VERIFIED_STEAM`: obtenido de una API oficial de Valve/Steam.
- `MANUAL`: cargado por el usuario o un administrador en la plataforma.
- `UNAVAILABLE`: no existe una fuente oficial que lo proporcione.
"""

CS2_UNAVAILABLE_REASON = (
    "Steam no expone estadísticas por jugador ni historial de partidas de "
    "Counter-Strike 2 mediante su Web API oficial."
)

COMMUNITY_VISIBILITY_LABELS = {
    1: "PUBLIC",
    2: "FRIENDS_ONLY",
    3: "PRIVATE",
}


def _iso(value):
    return value.isoformat() if value is not None else None


def _unavailable_cs2():
    return {
        "app_id": 730,
        "available": False,
        "ownership": "UNKNOWN",
        "playtime_available": False,
        "playtime_forever_minutes": None,
        "playtime_two_weeks_minutes": None,
        "last_played_at": None,
        "source": "UNAVAILABLE",
        "fetched_at": None,
        "stats_available": False,
        "matches_available": False,
        "stats": {
            "kills": None,
            "deaths": None,
            "assists": None,
            "kd": None,
            "kr": None,
            "adr": None,
            "headshot_percentage": None,
            "matches_played": None,
            "wins": None,
            "losses": None,
            "win_rate": None,
            "source": "UNAVAILABLE",
        },
        "matches": [],
        "unavailable_reason": CS2_UNAVAILABLE_REASON,
    }


def serialize_steam_account(account, *, owner=False):
    if account is None:
        return None
    payload = {
        "steam_id": account.steam_id,
        "persona_name": account.persona_name,
        "profile_url": account.profile_url,
        "avatar_url": account.avatar_full_url
        or account.avatar_medium_url
        or account.avatar_url,
        "avatar_medium_url": account.avatar_medium_url,
        "avatar_full_url": account.avatar_full_url,
        "community_visibility": COMMUNITY_VISIBILITY_LABELS.get(
            account.community_visibility_state, "UNKNOWN"
        ),
        "profile_created_at": _iso(account.profile_created_at),
        "linked_at": _iso(account.created_at),
        "last_sync_at": _iso(account.last_sync_at),
        "last_sync_status": account.last_sync_status or "NEVER",
        "playtime_source": "VERIFIED_STEAM",
    }
    if owner:
        payload["last_sync_error"] = account.last_sync_error
    return payload


def serialize_steam_cs2(account):
    payload = _unavailable_cs2()
    if account is None:
        return payload

    stat = account.cs2_stats()
    if stat is None:
        if account.community_visibility_state == 3:
            payload["ownership"] = "PRIVATE"
            payload["unavailable_reason"] = (
                "El perfil de Steam es privado; el tiempo de juego de CS2 no "
                "es visible. " + CS2_UNAVAILABLE_REASON
            )
        else:
            payload["ownership"] = "NOT_AVAILABLE"
            payload["unavailable_reason"] = (
                "Steam no devolvió datos de CS2 para esta cuenta. La "
                "biblioteca puede ser privada o el juego no estar presente. "
                + CS2_UNAVAILABLE_REASON
            )
        return payload

    payload.update(
        {
            "available": True,
            "ownership": "OWNED",
            "playtime_available": True,
            "playtime_forever_minutes": stat.playtime_forever_minutes,
            "playtime_two_weeks_minutes": stat.playtime_two_weeks_minutes,
            "last_played_at": _iso(stat.last_played_at),
            "source": "VERIFIED_STEAM",
            "fetched_at": _iso(stat.fetched_at),
        }
    )
    return payload


def serialize_steam_sync(account, *, owner=False, configured=True):
    if account is None:
        return {
            "status": "NEVER",
            "last_sync_at": None,
            "last_sync_error": None,
            "can_sync": False,
            "next_sync_at": None,
            "min_interval_seconds": None,
            "api_configured": configured if owner else None,
        }

    payload = {
        "status": account.last_sync_status or "NEVER",
        "last_sync_at": _iso(account.last_sync_at),
        "can_sync": False,
        "next_sync_at": None,
    }
    if owner:
        payload["last_sync_error"] = account.last_sync_error
        payload["min_interval_seconds"] = None
        payload["api_configured"] = configured
    return payload


def serialize_steam_section(
    account, *, owner=False, configured=True
):
    if account is None:
        return {
            "linked": False,
            "configured": configured if owner else None,
            "account": None,
            "cs2": _unavailable_cs2(),
            "sync": serialize_steam_sync(
                None, owner=owner, configured=configured
            ),
        }

    return {
        "linked": True,
        "configured": configured if owner else None,
        "account": serialize_steam_account(account, owner=owner),
        "cs2": serialize_steam_cs2(account),
        "sync": serialize_steam_sync(
            account, owner=owner, configured=configured
        ),
    }


def build_provenance(
    *,
    stats,
    map_performance,
    recent_matches,
    steam,
    matchmaking=None,
    faceit=None,
):
    stats_available = bool(getattr(stats, "has_data", False))
    steam_linked = bool(steam.get("linked"))
    playtime_available = bool(
        steam.get("cs2", {}).get("playtime_available")
    )
    matchmaking = matchmaking or {}
    faceit = faceit or {}
    # Las estadísticas y el historial de matchmaking salen solo de demos
    # procesadas; si todavía no hay ninguna, la fuente sigue siendo UNAVAILABLE.
    demo_stats = bool(matchmaking.get("has_data"))
    demo_history = bool(matchmaking.get("availability", {}).get("processed"))
    # One provenance rule, with explicit source/availability per public field.
    sources = {
        "steam_identity": ("VERIFIED_STEAM", steam_linked),
        "steam_playtime": ("VERIFIED_STEAM", playtime_available),
        "manual_stats": ("MANUAL", stats_available),
        "manual_map_performance": ("MANUAL", map_performance),
        "manual_match_history": ("MANUAL", recent_matches),
        "cs2_player_stats": ("VERIFIED_DEMO", demo_stats),
        "cs2_match_history": ("VERIFIED_DEMO", demo_history),
        "faceit_stats": ("VERIFIED_FACEIT", faceit.get("stats", {}).get("available")),
        "faceit_match_history": ("VERIFIED_FACEIT", faceit.get("availability", {}).get("matches")),
    }
    return {field: source if available else "UNAVAILABLE" for field, (source, available) in sources.items()}
