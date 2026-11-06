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


def serialize_faceit_stats(stats):
    if stats is None:
        return _empty_stats()
    payload = {field: getattr(stats, field, None) for field in STAT_FIELDS}
    available = any(value is not None for value in payload.values())
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


def serialize_faceit_match(match, *, owner=False):
    stats = match.player_stats
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
        "has_stats": bool(stats is not None),
        "source": "VERIFIED_FACEIT",
        "fetched_at": _iso(match.fetched_at),
        "stats": {
            "kills": stats.kills if stats else None,
            "deaths": stats.deaths if stats else None,
            "assists": stats.assists if stats else None,
            "kd": _float(stats.kd) if stats else None,
            "kr": _float(stats.kr) if stats else None,
            "adr": _float(stats.adr) if stats else None,
            "headshot_percentage": _float(stats.headshot_percentage)
            if stats
            else None,
            "mvps": stats.mvps if stats else None,
            "rounds_played": stats.rounds_played if stats else None,
            "source": "VERIFIED_FACEIT" if stats else "UNAVAILABLE",
        },
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
    status = "NEVER"
    if sync_state is not None:
        status = sync_state.status or "NEVER"
    if not configured or not enabled:
        status = "NOT_CONFIGURED"
    if status not in SYNC_STATUS_LABELS:
        status = "ERROR"

    payload = {
        "status": status,
        "status_label": SYNC_STATUS_LABELS.get(status, status),
        "last_sync_at": _iso(
            sync_state.last_success_at if sync_state else None
        ),
        "last_attempt_at": _iso(
            sync_state.last_attempt_at if sync_state else None
        ),
        "next_sync_at": _iso(sync_state.next_sync_at if sync_state else None),
        "can_sync": bool(owner and can_sync and configured and enabled),
        "enabled": bool(enabled),
        "api_configured": configured if owner else None,
        "oauth_configured": oauth_configured if owner else None,
        "min_interval_seconds": min_interval if owner else None,
    }
    if owner:
        payload["last_error"] = (
            sync_state.last_error if sync_state else None
        )
        payload["consecutive_failures"] = (
            sync_state.consecutive_failures if sync_state else 0
        )
    return payload


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
    matches = list(matches or [])
    map_stats = list(map_stats or [])
    elo_history = list(elo_history or [])
    stats = serialize_faceit_stats(account.stats if account else None)
    sync_state = account.sync_state if account else None
    sync = serialize_faceit_sync(
        sync_state,
        owner=owner,
        configured=configured,
        enabled=enabled,
        oauth_configured=oauth_configured,
        min_interval=min_interval,
        can_sync=can_sync,
    )

    message = None
    if not configured:
        message = NOT_CONFIGURED_MESSAGE
    elif not enabled:
        message = "La integración con FACEIT está deshabilitada en este servidor."
    elif account is None:
        message = NO_ACCOUNT_MESSAGE

    return {
        "linked": account is not None,
        "configured": configured if owner else None,
        "oauth_configured": oauth_configured if owner else None,
        "enabled": bool(enabled),
        "status": sync["status"],
        "status_label": sync["status_label"],
        "message": message,
        "unavailable_reason": message if account is None else None,
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
        "availability": {
            "stats": bool(stats["available"]),
            "matches": history_total
            if history_total is not None
            else len(matches),
            "maps": len(map_stats),
            "elo_snapshots": len(elo_history),
        },
    }
