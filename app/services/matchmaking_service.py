"""Lógica de autorización, sincronización y consulta de matchmaking de CS2.

Separación de responsabilidades:

- Este servicio valida la autorización, registra share codes, consulta el
  estado y prepara la ingesta de demos.
- El worker (`app/worker/matchmaking.py`) hace el descubrimiento periódico y
  procesa las demos fuera del ciclo HTTP.
- Las demos nunca se descargan automáticamente desde Valve: requieren una
  sesión del Game Coordinator, que este proyecto no utiliza.
"""

from datetime import datetime, timedelta, timezone

from flask import current_app
from sqlalchemy import nullslast

from app.errors import ApiError
from app.extensions import db
from app.models.matchmaking import (
    MatchmakingAuthorization,
    MatchmakingDemoJob,
    MatchmakingMapStats,
    MatchmakingMatch,
    MatchmakingSyncRun,
)
from app.serializers.matchmaking import (
    serialize_matchmaking_match,
    serialize_matchmaking_section,
)
from app.services.matchmaking import crypto, discovery, storage
from app.services.matchmaking.demo_parser import played_at_from_match_id
from app.services.matchmaking.sharecode import (
    ShareCodeError,
    canonical_share_code,
    decode_share_code,
    match_id_from_filename,
    validate_auth_code,
)
from app.services.matchmaking.stats import build_map_aggregates
from app.utils.time_utils import as_utc, utcnow

RECENT_MATCH_LIMIT = 10
HISTORY_MATCH_LIMIT = 100


def _config(name, default=None):
    return current_app.config.get(name, default)


def is_enabled():
    return bool(_config("MATCHMAKING_ENABLED", True))


def is_configured():
    return bool(str(_config("STEAM_API_KEY", "")).strip())


def _interval():
    try:
        return max(0, int(_config("MATCHMAKING_SYNC_MIN_INTERVAL_SECONDS", 300)))
    except (TypeError, ValueError):
        return 300


def get_authorization(user):
    return user.matchmaking_authorization


def _require_steam(user, claimed_steam_id=None):
    account = user.steam_account
    if account is None:
        raise ApiError(
            "Vinculá tu cuenta de Steam antes de habilitar la sincronización "
            "de matchmaking.",
            status_code=400,
        )
    if claimed_steam_id and str(claimed_steam_id) != str(account.steam_id):
        raise ApiError(
            "El SteamID indicado no coincide con la cuenta vinculada.",
            status_code=400,
        )
    return account


def _coerce_share_code(value):
    try:
        code = canonical_share_code(value)
        decoded = decode_share_code(code)
    except ShareCodeError as error:
        raise ApiError(
            "El share code no es válido.",
            status_code=400,
            fields={"share_code": "invalid share code"},
        ) from error
    return code, decoded


def authorize(user, data):
    """Habilita (o renueva) la autorización con un código de Steam."""
    if not is_enabled():
        raise ApiError(
            "La sincronización de matchmaking no está habilitada.",
            status_code=503,
        )
    account = _require_steam(user, (data or {}).get("steam_id"))
    try:
        auth_code = validate_auth_code((data or {}).get("auth_code"))
    except ShareCodeError as error:
        raise ApiError(
            "El código de autenticación de Steam no tiene el formato "
            "esperado (XXXX-XXXXX-XXXX).",
            status_code=400,
            fields={"auth_code": "invalid authentication code"},
        ) from error
    share_code, decoded = _coerce_share_code((data or {}).get("share_code"))

    authorization = user.matchmaking_authorization
    if authorization is None:
        authorization = MatchmakingAuthorization(
            user_id=user.id,
            steam_id=str(account.steam_id),
            first_share_code=share_code,
        )
        db.session.add(authorization)
        db.session.flush()
    elif authorization.status == "INVALID":
        authorization.authorized_at = utcnow()
    authorization.steam_id = str(account.steam_id)
    authorization.auth_code_encrypted = crypto.encrypt_secret(auth_code)
    authorization.status = "ACTIVE"
    authorization.revoked_at = None
    authorization.last_discovery_error = None
    authorization.cursor_share_code = share_code
    if not authorization.first_share_code:
        authorization.first_share_code = share_code

    _register_share_code(
        user,
        share_code,
        authorization=authorization,
        decoded=decoded,
        commit=False,
    )
    db.session.commit()
    return build_section(user, owner=True)


def revoke(user):
    """Revoca la autorización y elimina el código cifrado.

    Las partidas ya procesadas se conservan (fueron autorizadas), pero dejan de
    actualizarse y la sección indica el estado `REVOKED`.
    """
    authorization = user.matchmaking_authorization
    if authorization is None:
        raise ApiError("No hay una autorización de matchmaking", status_code=404)
    authorization.status = "REVOKED"
    authorization.revoked_at = utcnow()
    authorization.auth_code_encrypted = None
    authorization.cursor_share_code = None
    authorization.first_share_code = None
    db.session.commit()
    return build_section(user, owner=True)


def _find_match(user_id, *, share_code=None, match_id=None):
    query = db.session.query(MatchmakingMatch).filter(
        MatchmakingMatch.user_id == user_id
    )
    if match_id is not None:
        found = query.filter(MatchmakingMatch.match_id == match_id).first()
        if found is not None:
            return found
    if share_code is not None:
        return query.filter(MatchmakingMatch.share_code == share_code).first()
    return None


def _register_share_code(
    user, share_code, *, authorization=None, decoded=None, commit=True
):
    """Registra un share code una sola vez. Devuelve (partida, creada)."""
    code = canonical_share_code(share_code)
    decoded = decoded or decode_share_code(code)
    match = _find_match(
        user.id, share_code=code, match_id=decoded.match_id
    )
    if match is not None:
        if not match.share_code:
            match.share_code = code
        if match.authorization_id is None and authorization is not None:
            match.authorization_id = authorization.id
        if commit:
            db.session.commit()
        return match, False

    match = MatchmakingMatch(
        user_id=user.id,
        authorization_id=authorization.id if authorization is not None else None,
        share_code=code,
        match_id=decoded.match_id,
        played_at=played_at_from_match_id(decoded.match_id),
        demo_status="AWAITING_DEMO",
    )
    db.session.add(match)
    if commit:
        db.session.commit()
    else:
        db.session.flush()
    return match, True


def register_manual_share_code(user, value):
    """Permite sumar un share code sin esperar al descubrimiento."""
    authorization = user.matchmaking_authorization
    if authorization is None or authorization.status != "ACTIVE":
        raise ApiError(
            "Primero habilitá la sincronización de matchmaking.",
            status_code=400,
        )
    code, decoded = _coerce_share_code(value)
    match, created = _register_share_code(
        user, code, authorization=authorization, decoded=decoded
    )
    db.session.commit()
    return match, created


def _ordered_matches(user, *, limit=None):
    query = (
        db.session.query(MatchmakingMatch)
        .filter(MatchmakingMatch.user_id == user.id)
        .order_by(
            nullslast(MatchmakingMatch.played_at.desc()),
            MatchmakingMatch.id.desc(),
        )
    )
    if limit is not None:
        query = query.limit(limit)
    return query.all()


def build_section(user, *, owner=False):
    """Construye la sección independiente CS2 MATCHMAKING."""
    authorization = user.matchmaking_authorization
    matches = _ordered_matches(user)
    configured = is_configured()
    interval = _interval()
    can_sync = False
    if owner and authorization is not None and authorization.status == "ACTIVE":
        last = as_utc(authorization.last_discovery_at)
        can_sync = configured and (
            last is None or ( utcnow() - last).total_seconds() >= interval
        )
    return serialize_matchmaking_section(
        authorization,
        matches,
        owner=owner,
        configured=configured,
        interval=interval,
        can_sync=can_sync,
        recent_limit=RECENT_MATCH_LIMIT,
        enabled=is_enabled(),
    )


def list_matches(user, *, limit=RECENT_MATCH_LIMIT, offset=0, owner=True):
    query = (
        db.session.query(MatchmakingMatch)
        .filter(MatchmakingMatch.user_id == user.id)
        .order_by(
            nullslast(MatchmakingMatch.played_at.desc()),
            MatchmakingMatch.id.desc(),
        )
        .offset(max(0, int(offset)))
        .limit(max(1, min(int(limit), HISTORY_MATCH_LIMIT)))
    )
    return [
        serialize_matchmaking_match(match, owner=owner)
        for match in query.all()
    ]


def get_match(user, match_id, *, owner=True):
    match = (
        db.session.query(MatchmakingMatch)
        .filter(
            MatchmakingMatch.user_id == user.id,
            MatchmakingMatch.id == int(match_id),
        )
        .first()
    )
    if match is None:
        raise ApiError("Partida no encontrada", status_code=404)
    return serialize_matchmaking_match(match, owner=owner)


def request_sync(user):
    """Encola un descubrimiento manual para que lo ejecute el worker."""
    if not is_enabled():
        raise ApiError(
            "La sincronización de matchmaking no está habilitada.",
            status_code=503,
        )
    authorization = user.matchmaking_authorization
    if authorization is None:
        raise ApiError(
            "Primero habilitá la sincronización de matchmaking.",
            status_code=400,
        )
    if authorization.status != "ACTIVE":
        raise ApiError(
            "La autorización no está activa. Volvé a generarla para "
            "sincronizar.",
            status_code=409,
        )
    if not is_configured():
        raise ApiError(
            "La integración con Steam no está configurada en el servidor.",
            status_code=503,
        )

    now = utcnow()
    last = as_utc(authorization.last_discovery_at)
    interval = _interval()
    if last is not None:
        elapsed = (now - last).total_seconds()
        if elapsed < interval:
            section = build_section(user, owner=True)
            sync = dict(section["sync"])
            sync.update(
                {
                    "status": "SKIPPED",
                    "status_label": "Esperando intervalo",
                    "message": "La sincronización se hizo recientemente.",
                    "retry_after_seconds": max(1, int(interval - elapsed)),
                }
            )
            return {"status": "SKIPPED", "sync": sync, "matchmaking": section}

    # Evita encolar dos corridas manuales simultáneas.
    running = (
        db.session.query(MatchmakingSyncRun)
        .filter(
            MatchmakingSyncRun.user_id == user.id,
            MatchmakingSyncRun.kind == "MANUAL",
            MatchmakingSyncRun.status == "RUNNING",
        )
        .first()
    )
    if running is None:
        db.session.add(
            MatchmakingSyncRun(
                user_id=user.id,
                kind="MANUAL",
                status="RUNNING",
                started_at=now,
            )
        )
        db.session.commit()

    section = build_section(user, owner=True)
    sync = dict(section["sync"])
    sync.update(
        {
            "status": "RUNNING",
            "status_label": "Sincronizando",
            "message": "La sincronización quedó en cola; el worker la "
            "procesará en segundo plano.",
        }
    )
    return {"status": "QUEUED", "sync": sync, "matchmaking": section}


def upload_demo(user, file_storage):
    """Guarda una demo autorizada. El worker la procesa en segundo plano."""
    if not is_enabled():
        raise ApiError(
            "La sincronización de matchmaking no está habilitada.",
            status_code=503,
        )
    authorization = user.matchmaking_authorization
    if authorization is None or authorization.status != "ACTIVE":
        raise ApiError(
            "Necesitás una autorización activa para subir demos.",
            status_code=400,
        )
    try:
        path = storage.save_upload(user.id, file_storage)
    except storage.StorageError as error:
        raise ApiError(str(error), status_code=400) from error
    return {
        "status": "QUEUED",
        "message": "La demo se guardó. El worker la procesará en segundo "
        "plano.",
        "file": storage.safe_name(file_storage.filename),
        "size_bytes": _safe_size(path),
    }


def _safe_size(path):
    try:
        import os

        return os.path.getsize(path)
    except OSError:
        return None


def enqueue_ingested_demo(info):
    """Crea el trabajo de procesamiento a partir de un archivo de la bandeja."""
    existing = (
        db.session.query(MatchmakingDemoJob)
        .filter(MatchmakingDemoJob.sha256 == info["sha256"])
        .first()
    )
    if existing is not None:
        return existing, False

    user_id = int(info["user_id"])
    match_id = match_id_from_filename(info.get("original_name"))
    match = _find_match(user_id, match_id=match_id) if match_id else None
    if match is None:
        match = MatchmakingMatch(
            user_id=user_id,
            match_id=match_id,
            played_at=played_at_from_match_id(match_id) if match_id else None,
            demo_status="QUEUED",
        )
        db.session.add(match)
        db.session.flush()

    # La partida ya tiene una demo procesada: este archivo es un duplicado y no
    # debe volver a poner la partida en cola ni sobrescribir sus estadísticas.
    if match.demo_status == "OK":
        job = MatchmakingDemoJob(
            user_id=user_id,
            match_id=match.id,
            file_path=info["path"],
            original_name=info.get("original_name"),
            sha256=info["sha256"],
            size_bytes=info.get("size_bytes"),
            status="DUPLICATE",
            attempts=0,
        )
        db.session.add(job)
        db.session.commit()
        return job, False

    job = MatchmakingDemoJob(
        user_id=user_id,
        match_id=match.id,
        file_path=info["path"],
        original_name=info.get("original_name"),
        sha256=info["sha256"],
        size_bytes=info.get("size_bytes"),
        status="QUEUED",
        attempts=0,
        next_attempt_at=None,
    )
    db.session.add(job)
    match.demo_status = "QUEUED"
    match.demo_path = info["path"]
    match.demo_sha256 = info["sha256"]
    match.processing_error = None
    db.session.commit()
    return job, True


def refresh_map_stats(user_id):
    """Recalcula los agregados por mapa desde las partidas procesadas."""
    matches = (
        db.session.query(MatchmakingMatch)
        .filter(
            MatchmakingMatch.user_id == user_id,
            MatchmakingMatch.demo_status == "OK",
        )
        .all()
    )
    rows = build_map_aggregates(matches)
    (
        db.session.query(MatchmakingMapStats)
        .filter(MatchmakingMapStats.user_id == user_id)
        .delete(synchronize_session=False)
    )
    for row in rows:
        db.session.add(
            MatchmakingMapStats(
                user_id=user_id,
                map_name=row["map_name"],
                matches=row["matches_played"],
                wins=row["wins"],
                losses=row["losses"],
                draws=row["draws"],
                rounds_played=row["rounds_played"],
                kills=row["kills"],
                deaths=row["deaths"],
                assists=row["assists"],
                damage=row["damage"],
                headshot_kills=row["headshot_kills"],
                kast_rounds=row["kast_rounds"],
                mvps=row["mvps"],
                clutches=row["clutches"],
                opening_kills=row["opening_kills"],
                opening_deaths=row["opening_deaths"],
                adr=row["adr"],
                hs_percentage=row["hs_percentage"],
                kd=row["kd"],
                kast_percentage=row["kast_percentage"],
            )
        )
    return rows


def latest_sync_run(user):
    return (
        db.session.query(MatchmakingSyncRun)
        .filter(MatchmakingSyncRun.user_id == user.id)
        .order_by(MatchmakingSyncRun.id.desc())
        .first()
    )


def mark_sync_run(run, *, status, found=0, processed=0, failed=0, message=None):
    run.status = status
    run.found = max(0, int(found))
    run.processed = max(0, int(processed))
    run.failed = max(0, int(failed))
    run.message = (message or "")[:300] or None
    run.finished_at = utcnow()
    return run


def purge_old_sync_runs(user_id, keep=50):
    ids = [
        row[0]
        for row in (
            db.session.query(MatchmakingSyncRun.id)
            .filter(MatchmakingSyncRun.user_id == user_id)
            .order_by(MatchmakingSyncRun.id.desc())
            .offset(keep)
            .all()
        )
    ]
    if ids:
        (
            db.session.query(MatchmakingSyncRun)
            .filter(MatchmakingSyncRun.id.in_(ids))
            .delete(synchronize_session=False)
        )


def next_sync_at(authorization):
    last = as_utc(authorization.last_discovery_at) if authorization else None
    if last is None:
        return None
    return last + timedelta(seconds=_interval())
