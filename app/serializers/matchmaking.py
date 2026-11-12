"""Serializadores de la sección CS2 MATCHMAKING.

La sección es independiente de FACEIT y de Steam. Solo presenta datos de
demos procesadas (`VERIFIED_DEMO`) y distingue explícitamente lo pendiente, lo
no disponible y lo incompleto.

Reglas de privacidad:

- El share code completo, el SHA-256 y los errores de procesamiento solo se
  muestran al dueño.
- El *game authentication code* nunca se serializa.
- Los perfiles privados no llegan a construir esta sección.
"""

from app.services.matchmaking.sharecode import mask_share_code
from app.services.matchmaking.stats import (
    aggregate_matches,
    build_map_aggregates,
)

NO_AUTHORIZATION_MESSAGE = (
    "Este jugador todavía no habilitó la sincronización de sus partidas de "
    "matchmaking oficial."
)

SECTION_LABELS = {
    "UNAVAILABLE": "Sin autorizar",
    "AUTHORIZED": "Autorizado, esperando demos",
    "PROCESSING": "Procesando demos",
    "READY": "Historial completo",
    "PARTIAL": "Historial incompleto",
    "REVOKED": "Autorización revocada",
}

DEMO_STATUS_LABELS = {
    "AWAITING_DEMO": "Falta la demo",
    "QUEUED": "En cola",
    "PROCESSING": "Procesando",
    "OK": "Procesada",
    "ERROR": "Error de procesamiento",
    "UNAVAILABLE": "Demo no disponible",
    "DUPLICATE": "Duplicada",
}

SYNC_STATUS_LABELS = {
    "NEVER": "Sin sincronizar",
    "RUNNING": "Sincronizando",
    "OK": "Sincronización correcta",
    "PARTIAL": "Sincronización parcial",
    "ERROR": "Error de sincronización",
    "SKIPPED": "Esperando intervalo",
}

PROCESSED_STATUSES = ("OK",)
PENDING_STATUSES = ("AWAITING_DEMO", "QUEUED", "PROCESSING", "DUPLICATE")
FAILED_STATUSES = ("ERROR",)
UNAVAILABLE_STATUSES = ("UNAVAILABLE",)


def _iso(value):
    return value.isoformat() if value is not None else None


def _float(value):
    return float(value) if value is not None else None


def _match_source(demo_status):
    if demo_status in PROCESSED_STATUSES:
        return "VERIFIED_DEMO"
    if demo_status in PENDING_STATUSES:
        return "PENDING"
    if demo_status in UNAVAILABLE_STATUSES:
        return "UNAVAILABLE"
    return "INCOMPLETE"


_MATCH_COUNTED_FIELDS = (
    "rounds_played",
    "rounds_won",
    "rounds_lost",
    "kills",
    "deaths",
    "assists",
    "damage",
    "headshot_kills",
    "mvps",
    "clutches",
    "opening_kills",
    "opening_deaths",
)
_MATCH_RATE_FIELDS = ("kd", "adr", "hs_percentage", "kast_percentage")


def _match_payload(match, demo_status):
    payload = {
        "id": match.id,
        "played_at": _iso(match.played_at),
        "map": match.map_name,
        "result": match.result or "UNKNOWN",
        "team_score": match.team_score,
        "opponent_score": match.opponent_score,
        "status": demo_status,
        "status_label": DEMO_STATUS_LABELS.get(demo_status, demo_status),
        "has_stats": demo_status in PROCESSED_STATUSES,
        "processed": demo_status in PROCESSED_STATUSES,
        "source": _match_source(demo_status),
    }
    for field in _MATCH_COUNTED_FIELDS:
        payload[field] = getattr(match, field) or 0
    for field in _MATCH_RATE_FIELDS:
        payload[field] = _float(getattr(match, field))
    return payload


def _match_owner_fields(match):
    fields = {
        "attempts": match.attempts or 0,
        "processed_at": _iso(match.processed_at),
    }
    if match.processing_error:
        fields["processing_error"] = match.processing_error
    if match.demo_sha256:
        fields["demo_sha256"] = match.demo_sha256
    return fields


def serialize_matchmaking_match(match, *, owner=False, include_share_code=None):
    demo_status = match.demo_status or "AWAITING_DEMO"
    payload = _match_payload(match, demo_status)
    if owner:
        payload.update(_match_owner_fields(match))
    show_code = owner if include_share_code is None else include_share_code
    payload["share_code"] = (
        match.share_code if show_code else mask_share_code(match.share_code)
    )
    return payload


def _processed_status(pending, failed, unavailable):
    if pending or failed or unavailable:
        return "PARTIAL"
    return "READY"


def _empty_section_status(pending, failed, unavailable):
    if pending:
        return "PROCESSING"
    if failed or unavailable:
        return "PARTIAL"
    return "AUTHORIZED"


def _section_status(authorization, processed, pending, failed, unavailable):
    if authorization is None:
        return "UNAVAILABLE"
    if authorization.status == "REVOKED":
        return "REVOKED"
    if authorization.status == "INVALID":
        return "PARTIAL"
    if processed:
        return _processed_status(pending, failed, unavailable)
    return _empty_section_status(pending, failed, unavailable)


def _unavailable_reason(authorization):
    if authorization is None:
        return NO_AUTHORIZATION_MESSAGE
    if authorization.status == "REVOKED":
        return (
            "La autorización fue revocada. Las partidas procesadas siguen "
            "visibles, pero no se sincronizarán nuevas partidas."
        )
    if authorization.status == "INVALID":
        return (
            "Steam rechazó el código de autenticación. Generá uno nuevo para "
            "volver a sincronizar."
        )
    return None


def _serialize_authorization(authorization, *, owner):
    if authorization is None:
        return None
    payload = {
        "status": authorization.status,
        "authorized_at": _iso(authorization.authorized_at),
        "revoked_at": _iso(authorization.revoked_at),
    }
    if owner:
        payload.update(
            {
                "steam_id": authorization.steam_id,
                "share_code": mask_share_code(
                    authorization.cursor_share_code
                ),
                "last_discovery_at": _iso(authorization.last_discovery_at),
                "last_discovery_status": authorization.last_discovery_status,
                "last_discovery_error": authorization.last_discovery_error,
            }
        )
    return payload


def _never_sync(configured, owner):
    return {
        "status": "NEVER",
        "status_label": SYNC_STATUS_LABELS["NEVER"],
        "last_sync_at": None,
        "can_sync": False,
        "next_sync_at": None,
        "api_configured": configured if owner else None,
    }


def _sync_status(authorization):
    status = authorization.last_discovery_status or "NEVER"
    if status not in SYNC_STATUS_LABELS:
        return "ERROR"
    return status


def _next_sync_at(authorization, interval):
    if authorization.last_discovery_at is None or not interval:
        return None
    from datetime import timedelta

    next_at = authorization.last_discovery_at + timedelta(seconds=interval)
    return _iso(next_at)


def _owner_sync_fields(authorization, configured, interval):
    return {
        "min_interval_seconds": interval,
        "api_configured": configured,
        "last_sync_error": authorization.last_discovery_error,
        "next_sync_at": _next_sync_at(authorization, interval),
    }


def _serialize_sync(authorization, *, owner, configured, interval, can_sync):
    if authorization is None:
        return _never_sync(configured, owner)

    status = _sync_status(authorization)
    payload = {
        "status": status,
        "status_label": SYNC_STATUS_LABELS.get(status, status),
        "last_sync_at": _iso(authorization.last_discovery_at),
        "can_sync": bool(owner and can_sync),
        "next_sync_at": None,
    }
    if owner:
        payload.update(_owner_sync_fields(authorization, configured, interval))
    return payload


def _status_groups(matches):
    statuses = {
        "processed": PROCESSED_STATUSES,
        "pending": PENDING_STATUSES,
        "failed": FAILED_STATUSES,
        "unavailable": UNAVAILABLE_STATUSES,
    }
    return {
        name: [m for m in matches if (m.demo_status or "") in allowed]
        for name, allowed in statuses.items()
    }


def _authorized(authorization):
    return authorization is not None and authorization.status == "ACTIVE"


def _incomplete(groups):
    return bool(groups["pending"] or groups["failed"] or groups["unavailable"])


def _source(processed):
    return "VERIFIED_DEMO" if processed else "UNAVAILABLE"


def _map_rows(maps):
    return [
        {
            "map": row["map_name"],
            **{key: value for key, value in row.items() if key != "map_name"},
            "source": "VERIFIED_DEMO",
        }
        for row in maps
    ]


def _availability(groups, total):
    return {
        "processed": len(groups["processed"]),
        "pending": len(groups["pending"]),
        "errors": len(groups["failed"]),
        "unavailable": len(groups["unavailable"]),
        "total": total,
    }


def serialize_matchmaking_section(
    authorization,
    matches,
    *,
    owner=False,
    configured=True,
    interval=300,
    can_sync=False,
    recent_limit=10,
    enabled=True,
):
    """Construye la sección completa a partir de las partidas persistidas."""
    matches = list(matches or [])
    groups = _status_groups(matches)
    processed = groups["processed"]
    status = _section_status(
        authorization,
        processed,
        groups["pending"],
        groups["failed"],
        groups["unavailable"],
    )
    summary = aggregate_matches(processed)
    source = _source(processed)

    return {
        "available": authorization is not None,
        "authorized": _authorized(authorization),
        "status": status,
        "status_label": SECTION_LABELS.get(status, status),
        "message": NO_AUTHORIZATION_MESSAGE
        if authorization is None
        else None,
        "unavailable_reason": _unavailable_reason(authorization),
        "source": source,
        "has_data": summary["has_data"],
        "incomplete": _incomplete(groups),
        "incomplete_reason": _incomplete_reason(
            groups["pending"], groups["failed"], groups["unavailable"]
        ),
        "summary": {**summary, "source": source},
        "map_performance": _map_rows(build_map_aggregates(processed)),
        "recent_matches": [
            serialize_matchmaking_match(match, owner=owner)
            for match in matches[:recent_limit]
        ],
        "availability": _availability(groups, len(matches)),
        "authorization": _serialize_authorization(
            authorization, owner=owner
        ),
        "sync": _serialize_sync(
            authorization,
            owner=owner,
            configured=configured,
            interval=interval,
            can_sync=can_sync,
        ),
        "enabled": bool(enabled),
    }


def _incomplete_reason(pending, failed, unavailable):
    parts = []
    if pending:
        parts.append(
            f"{len(pending)} partida(s) todavía no tienen una demo procesada"
        )
    if failed:
        parts.append(f"{len(failed)} partida(s) fallaron al procesarse")
    if unavailable:
        parts.append(
            f"{len(unavailable)} partida(s) no tienen demo disponible"
        )
    if not parts:
        return None
    return ". ".join(parts) + "."
