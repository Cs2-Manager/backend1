"""Serializadores de la integración con FACEIT.

La procedencia es explícita (`VERIFIED_FACEIT`) y nunca se mezcla con Steam,
matchmaking por demos o datos manuales. Cada métrica ausente se serializa como
`null`; la UI la muestra como "No disponible" y jamás como cero.

Los secretos (API key, client secret, tokens OAuth y code_verifier) no forman
parte de ninguno de estos serializadores.
"""

from app.models.faceit import FACEIT_GAME_ID

SYNC_STATUS_LABELS = {
    "NEVER": "Sin sincronizar",
    "OK": "Sincronización correcta",
    "PARTIAL": "Sincronización parcial",
    "ERROR": "Error de sincronización",
    "SKIPPED": "Esperando intervalo",
    "NOT_CONFIGURED": "FACEIT no configurado",
}

LINK_STATUS_LABELS = {
    "DISCOVERED": "Descubierta por Steam",
    "VERIFIED": "Verificada con FACEIT Connect",
}

VERIFICATION_SOURCE_LABELS = {
    "STEAM_DISCOVERY": "SteamID verificado",
    "OAUTH2": "FACEIT Connect (OAuth2)",
}

NO_ACCOUNT_MESSAGE = (
    "Todavía no vinculaste una cuenta de FACEIT. Podés descubrirla desde tu "
    "SteamID verificado o verificarla con FACEIT Connect."
)

NOT_CONFIGURED_MESSAGE = (
    "FACEIT no está configurado en este servidor. Un administrador debe "
    "definir FACEIT_API_KEY en el backend."
)

OAUTH_NOT_CONFIGURED_MESSAGE = (
    "FACEIT Connect no está configurado. La consulta de datos públicos sigue "
    "disponible, pero la vinculación verificada por OAuth2 está pendiente de "
    "credenciales oficiales."
)

STAT_FIELDS = (
    "matches_played",
    "wins",
    "losses",
    "win_rate",
    "kills",
    "deaths",
    "assists",
    "kd",
    "kr",
    "headshots",
    "headshot_percentage",
    "adr",
    "mvps",
    "triple_kills",
    "quadruple_kills",
    "penta_kills",
    "rounds_played",
    "total_damage",
)


def _iso(value):
    return value.isoformat() if value is not None else None


def _float(value):
    return float(value) if value is not None else None


def _empty_stats():
    payload = {field: None for field in STAT_FIELDS}
    payload.update(
        {
            "available": False,
            "source": "UNAVAILABLE",
            "game_id": FACEIT_GAME_ID,
            "fetched_at": None,
        }
    )
    return payload


def _stats_available(payload):
    return any(value is not None for value in payload.values())


def serialize_faceit_stats(stats):
    if stats is None:
        return _empty_stats()
    payload = {field: getattr(stats, field, None) for field in STAT_FIELDS}
    available = _stats_available(payload)
    payload.update(
        {
            "available": available,
            "source": "VERIFIED_FACEIT" if available else "UNAVAILABLE",
            "game_id": stats.game_id or FACEIT_GAME_ID,
            "fetched_at": _iso(stats.fetched_at),
        }
    )
    return payload


def serialize_faceit_account(account, *, owner=False):
    if account is None:
        return None
    payload = {
        "player_id": account.faceit_player_id,
        "nickname": account.nickname,
        "avatar_url": account.avatar_url,
        "cover_image_url": account.cover_image_url,
        "country": account.country,
        "region": account.region,
        "steam_id": account.steam_id,
        "steam_nickname": account.steam_nickname,
        "faceit_url": account.faceit_url,
        "skill_level": account.skill_level,
        "elo": account.elo,
        "link_status": account.link_status,
        "link_status_label": LINK_STATUS_LABELS.get(
            account.link_status, account.link_status
        ),
        "verified": account.verified,
        "verification_source": account.verification_source,
        "verification_source_label": VERIFICATION_SOURCE_LABELS.get(
            account.verification_source, account.verification_source
        ),
        "verified_at": _iso(account.verified_at),
        "linked_at": _iso(account.created_at),
        "updated_at": _iso(account.updated_at),
    }
    if owner:
        payload["sync_enabled"] = bool(account.sync_enabled)
    return payload


_MATCH_STAT_FIELDS = (
    "kills",
    "deaths",
    "assists",
    "kd",
    "kr",
    "adr",
    "headshot_percentage",
    "mvps",
    "rounds_played",
)
_MATCH_STAT_FLOATS = ("kd", "kr", "adr", "headshot_percentage")


def _stat_value(stats, field):
    value = getattr(stats, field)
    if field in _MATCH_STAT_FLOATS:
        return _float(value)
    return value


def _match_stats_payload(stats):
    if stats is None:
        payload = {field: None for field in _MATCH_STAT_FIELDS}
        payload["source"] = "UNAVAILABLE"
        return payload
    payload = {
        field: _stat_value(stats, field) for field in _MATCH_STAT_FIELDS
    }
    payload["source"] = "VERIFIED_FACEIT"
    return payload


def serialize_faceit_match(match, *, owner=False):
    payload = {
        "id": match.id,
        "match_id": match.faceit_match_id,
        "played_at": _iso(match.played_at),
        "map": match.map_name,
        "game_mode": match.game_mode,
        "region": match.region,
        "competition_name": match.competition_name,
        "result": match.result or "UNKNOWN",
        "team_score": match.team_score,
        "opponent_score": match.opponent_score,
        "score": match.score,
        "player_team_name": match.player_team_name,
        "opponent_team_name": match.opponent_team_name,
        "faceit_url": match.faceit_url,
        "status": match.status or "PARTIAL",
        "has_stats": bool(match.player_stats is not None),
        "source": "VERIFIED_FACEIT",
        "fetched_at": _iso(match.fetched_at),
        "stats": _match_stats_payload(match.player_stats),
    }
    if owner:
        payload["account_id"] = match.account_id
    return payload


def serialize_faceit_map(row):
    return {
        "map": row.map_name,
        "matches_played": row.matches_played,
        "wins": row.wins,
        "losses": row.losses,
        "win_rate": _float(row.win_rate),
        "kills": row.kills,
        "deaths": row.deaths,
        "assists": row.assists,
        "kd": _float(row.kd),
        "adr": _float(row.adr),
        "headshot_percentage": _float(row.headshot_percentage),
        "source": "VERIFIED_FACEIT",
        "calculated_from": row.calculated_from,
        "updated_at": _iso(row.updated_at),
    }


def serialize_elo_snapshot(snapshot):
    return {
        "elo": snapshot.elo,
        "skill_level": snapshot.skill_level,
        "captured_at": _iso(snapshot.captured_at),
        "source": snapshot.source,
    }


def _state_status(sync_state):
    if sync_state is None:
        return "NEVER"
    return sync_state.status or "NEVER"


def _sync_status(sync_state, configured, enabled):
    if not configured or not enabled:
        return "NOT_CONFIGURED"
    status = _state_status(sync_state)
    if status not in SYNC_STATUS_LABELS:
        return "ERROR"
    return status


def _sync_field(sync_state, name, default=None):
    if sync_state is None:
        return default
    return getattr(sync_state, name)


def _sync_timestamps(sync_state):
    return {
        "last_sync_at": _iso(_sync_field(sync_state, "last_success_at")),
        "last_attempt_at": _iso(_sync_field(sync_state, "last_attempt_at")),
        "next_sync_at": _iso(_sync_field(sync_state, "next_sync_at")),
    }


def _owner_only(value, owner):
    return value if owner else None


def _owner_sync_fields(sync_state):
    return {
        "last_error": _sync_field(sync_state, "last_error"),
        "consecutive_failures": _sync_field(
            sync_state, "consecutive_failures", 0
        ),
    }


def serialize_faceit_sync(
    sync_state,
    *,
    owner,
    configured,
    enabled,
    oauth_configured,
    min_interval,
    can_sync,
):
    status = _sync_status(sync_state, configured, enabled)
    payload = {
        "status": status,
        "status_label": SYNC_STATUS_LABELS.get(status, status),
        **_sync_timestamps(sync_state),
        "can_sync": bool(owner and can_sync and configured and enabled),
        "enabled": bool(enabled),
        "api_configured": _owner_only(configured, owner),
        "oauth_configured": _owner_only(oauth_configured, owner),
        "min_interval_seconds": _owner_only(min_interval, owner),
    }
    if owner:
        payload.update(_owner_sync_fields(sync_state))
    return payload


def _section_message(account, configured, enabled):
    if not configured:
        return NOT_CONFIGURED_MESSAGE
    if not enabled:
        return "La integración con FACEIT está deshabilitada en este servidor."
    if account is None:
        return NO_ACCOUNT_MESSAGE
    return None


def _section_availability(
    stats, matches, map_stats, elo_history, history_total
):
    if history_total is not None:
        total = history_total
    else:
        total = len(matches)
    return {
        "stats": bool(stats["available"]),
        "matches": total,
        "maps": len(map_stats),
        "elo_snapshots": len(elo_history),
    }


def _as_list(value):
    return list(value or [])


def _account_stats(account):
    if account is None:
        return None
    return account.stats


def _account_sync_state(account):
    if account is None:
        return None
    return account.sync_state


def _unavailable_reason(message, account):
    if account is None:
        return message
    return None


def serialize_faceit_section(
    account,
    *,
    owner=False,
    configured=True,
    enabled=True,
    oauth_configured=False,
    min_interval=300,
    can_sync=False,
    matches=None,
    map_stats=None,
    elo_history=None,
    recent_limit=10,
    history_total=None,
):
    matches = _as_list(matches)
    map_stats = _as_list(map_stats)
    elo_history = _as_list(elo_history)
    stats = serialize_faceit_stats(_account_stats(account))
    sync_state = _account_sync_state(account)
    sync = serialize_faceit_sync(
        sync_state,
        owner=owner,
        configured=configured,
        enabled=enabled,
        oauth_configured=oauth_configured,
        min_interval=min_interval,
        can_sync=can_sync,
    )
    message = _section_message(account, configured, enabled)

    return {
        "linked": account is not None,
        "configured": _owner_only(configured, owner),
        "oauth_configured": _owner_only(oauth_configured, owner),
        "enabled": bool(enabled),
        "status": sync["status"],
        "status_label": sync["status_label"],
        "message": message,
        "unavailable_reason": _unavailable_reason(message, account),
        "account": serialize_faceit_account(account, owner=owner),
        "stats": stats,
        "recent_matches": [
            serialize_faceit_match(match, owner=owner)
            for match in matches[:recent_limit]
        ],
        "map_stats": [
            serialize_faceit_map(row) for row in map_stats
        ],
        "elo_history": [
            serialize_elo_snapshot(snapshot) for snapshot in elo_history
        ],
        "sync": sync,
        "availability": _section_availability(
            stats, matches, map_stats, elo_history, history_total
        ),
    }
