"""Worker independiente de matchmaking de CS2.

Se ejecuta en un contenedor aparte del backend (`Dockerfile.worker`) porque
`demoparser2` necesita wheels nativas y el parseo de una demo consume CPU y
memoria durante varios segundos. El ciclo HTTP nunca parsea demos.

Responsabilidades:

1. Ejecutar las sincronizaciones manuales encoladas por la API (tabla
   `matchmaking_sync_runs`, `kind=MANUAL`).
2. Descubrir share codes nuevos de forma periódica para las autorizaciones
   activas, avanzando el cursor y sin volver a pedir códigos ya vistos.
3. Escanear la carpeta de ingesta (`inbox/<user_id>/`), archivar por SHA-256 y
   crear trabajos deduplicados.
4. Procesar los trabajos pendientes con reintentos y backoff exponencial.
5. Marcar como `UNAVAILABLE` las partidas cuya demo ya no puede conseguirse
   (Valve conserva las demos ~30 días).
6. Recalcular los agregados por mapa después de cada demo procesada.

No descarga demos desde Valve: eso exigiría una sesión del Game Coordinator
con credenciales del jugador, algo que el proyecto no hace. Las demos llegan
por subida HTTP o por la carpeta de ingesta.
"""

import time
from datetime import datetime, timedelta, timezone

from flask import current_app

from app.extensions import db
from app.models.matchmaking import (
    MatchmakingAuthorization,
    MatchmakingDemoJob,
    MatchmakingMatch,
    MatchmakingSyncRun,
)
from app.models.user import User
from app.services import matchmaking_service
from app.services.matchmaking import (
    crypto,
    demo_parser,
    discovery,
    storage,
    stats,
)
from app.utils.time_utils import as_utc, utcnow

JOB_BATCH_SIZE = 5
BACKOFF_BASE_SECONDS = 30
BACKOFF_MAX_SECONDS = 900


def _config(name, default=None):
    return current_app.config.get(name, default)


def _int_config(name, default):
    try:
        return int(_config(name, default))
    except (TypeError, ValueError):
        return default


def _truncate(value, limit=300):
    return (str(value) if value is not None else "")[:limit] or None


class DiscoveryOutcome:
    """Resultado de un descubrimiento para una autorización."""

    def __init__(self, found=0, status="OK", error=None):
        self.found = found
        self.status = status
        self.error = error

    def as_dict(self):
        return {
            "found": self.found,
            "status": self.status,
            "error": self.error,
        }


def _invalidate_auth_code(authorization, now):
    message = "No se pudo descifrar el código de autenticación"
    authorization.status = "INVALID"
    authorization.last_discovery_at = now
    authorization.last_discovery_status = "ERROR"
    authorization.last_discovery_error = _truncate(message)
    db.session.commit()
    return DiscoveryOutcome(status="ERROR", error=message)


def _register_next_code(authorization, auth_code, current):
    next_code = discovery.get_next_share_code(
        authorization.steam_id, auth_code, current
    )
    if not next_code:
        return None, False
    _match, created = matchmaking_service._register_share_code(
        authorization.user,
        next_code,
        authorization=authorization,
        commit=False,
    )
    return next_code, created


def _advance_cursor(authorization, auth_code, limit):
    found = 0
    current = authorization.cursor_share_code or authorization.first_share_code
    for _ in range(limit):
        next_code, created = _register_next_code(
            authorization, auth_code, current
        )
        if not next_code:
            break
        current = next_code
        if created:
            found += 1
    return found, current


def _record_discovery_error(authorization, error):
    authorization.last_discovery_at = utcnow()
    authorization.last_discovery_status = "ERROR"
    authorization.last_discovery_error = _truncate(error.message)
    if error.code == "invalid_auth_code":
        authorization.status = "INVALID"
        authorization.auth_code_encrypted = None
    db.session.commit()
    return DiscoveryOutcome(status="ERROR", error=error.message)


def _record_unexpected_error(authorization, error):
    db.session.rollback()
    authorization.last_discovery_at = utcnow()
    authorization.last_discovery_status = "ERROR"
    authorization.last_discovery_error = _truncate(error)
    db.session.commit()
    return DiscoveryOutcome(status="ERROR", error=str(error))


def _initial_cursor(authorization):
    return authorization.cursor_share_code or authorization.first_share_code


def _discovery_limit(max_codes):
    configured = _int_config("MATCHMAKING_DISCOVERY_MAX_CODES", 50)
    return max(1, max_codes or configured)


def _discovery_auth_code(authorization, now):
    if authorization is None:
        return None, DiscoveryOutcome(
            status="SKIPPED", error="Sin autorización"
        )
    if authorization.status != "ACTIVE":
        return None, DiscoveryOutcome(
            status="SKIPPED", error="La autorización no está activa"
        )
    auth_code = crypto.decrypt_secret(authorization.auth_code_encrypted)
    if not auth_code:
        return None, _invalidate_auth_code(authorization, now)
    if not _initial_cursor(authorization):
        return None, DiscoveryOutcome(
            status="SKIPPED", error="No hay un share code de partida"
        )
    return auth_code, None


def _finish_discovery(authorization, found, current):
    authorization.cursor_share_code = current
    authorization.last_discovery_at = utcnow()
    authorization.last_discovery_status = "OK"
    authorization.last_discovery_error = None
    db.session.commit()
    return DiscoveryOutcome(found=found, status="OK")


def discover_authorization(authorization, *, max_codes=None):
    """Avanza el cursor de share codes de una autorización activa.

    Nunca lanza por errores de red: los registra en la autorización y devuelve
    el resultado para que el llamador cierre la corrida de sincronización.
    """
    auth_code, skipped = _discovery_auth_code(authorization, utcnow())
    if skipped is not None:
        return skipped

    limit = _discovery_limit(max_codes)
    try:
        found, current = _advance_cursor(authorization, auth_code, limit)
    except discovery.DiscoveryError as error:
        return _record_discovery_error(authorization, error)
    except Exception as error:  # noqa: BLE001 - el worker no debe caerse
        return _record_unexpected_error(authorization, error)

    return _finish_discovery(authorization, found, current)


def _finish_run(run, outcome):
    status = "OK" if outcome.status == "OK" else "ERROR"
    matchmaking_service.mark_sync_run(
        run,
        status=status,
        found=outcome.found,
        processed=0,
        failed=0 if outcome.status == "OK" else 1,
        message=outcome.error,
    )
    db.session.commit()


def process_manual_sync_runs():
    """Ejecuta las corridas manuales que la API dejó en `RUNNING`."""
    runs = (
        db.session.query(MatchmakingSyncRun)
        .filter(
            MatchmakingSyncRun.kind == "MANUAL",
            MatchmakingSyncRun.status == "RUNNING",
        )
        .order_by(MatchmakingSyncRun.id)
        .all()
    )
    for run in runs:
        user = db.session.get(User, run.user_id)
        if user is None:
            matchmaking_service.mark_sync_run(
                run, status="ERROR", failed=1, message="Usuario inexistente"
            )
            db.session.commit()
            continue
        outcome = discover_authorization(user.matchmaking_authorization)
        _finish_run(run, outcome)
        matchmaking_service.purge_old_sync_runs(user.id)
        db.session.commit()
    return len(runs)


def _periodic_due(authorization, now, interval):
    last = as_utc(authorization.last_discovery_at)
    return last is None or (now - last).total_seconds() >= interval


def process_due_authorizations():
    """Descubre códigos nuevos para autorizaciones activas vencidas."""
    interval = max(0, _int_config("MATCHMAKING_DISCOVERY_INTERVAL_SECONDS", 3600))
    now = utcnow()
    authorizations = (
        db.session.query(MatchmakingAuthorization)
        .filter(MatchmakingAuthorization.status == "ACTIVE")
        .order_by(MatchmakingAuthorization.id)
        .all()
    )
    processed = 0
    for authorization in authorizations:
        if not _periodic_due(authorization, now, interval):
            continue
        run = MatchmakingSyncRun(
            user_id=authorization.user_id,
            kind="DISCOVERY",
            status="RUNNING",
            started_at=now,
        )
        db.session.add(run)
        db.session.commit()
        outcome = discover_authorization(authorization)
        _finish_run(run, outcome)
        processed += 1
    return processed


def scan_inbox():
    """Archiva demos nuevas y crea trabajos deduplicados."""
    results = storage.scan_inbox()
    created = 0
    for info in results:
        if info.get("duplicate"):
            continue
        _job, was_created = matchmaking_service.enqueue_ingested_demo(info)
        if was_created:
            created += 1
    return created


def _steam_id_for(match):
    user = db.session.get(User, match.user_id)
    account = getattr(user, "steam_account", None) if user else None
    return str(account.steam_id) if account is not None else None


def _apply_stats(match, result):
    for field in (
        "map_name",
        "played_at",
        "result",
        "team_score",
        "opponent_score",
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
        "kast_rounds",
        "adr",
        "hs_percentage",
        "kd",
        "kast_percentage",
    ):
        value = result.get(field)
        if value is not None:
            setattr(match, field, value)


def _process_job(job):
    match = db.session.get(MatchmakingMatch, job.match_id) if job.match_id else None
    steam_id = _steam_id_for(match) if match is not None else None
    if match is None:
        raise RuntimeError("El trabajo no tiene una partida asociada")
    if not steam_id:
        raise RuntimeError("La cuenta de Steam no está vinculada")

    with storage.prepared_demo(job.file_path) as path:
        summary = demo_parser.parse_demo(
            path, steam_id, match_id=match.match_id
        )
    computed = stats.compute_match_stats(
        summary, steam_id, fallback_mvps=summary.get("fallback_mvps", 0)
    )
    _apply_stats(match, computed)
    return match


def _job_match(job):
    if job is None or not job.match_id:
        return None
    return db.session.get(MatchmakingMatch, job.match_id)


def _job_ready(job, now):
    next_attempt = as_utc(job.next_attempt_at)
    return next_attempt is None or next_attempt <= now


def _start_job(job):
    job.status = "PROCESSING"
    job.attempts = (job.attempts or 0) + 1
    match = _job_match(job)
    if match is not None:
        match.demo_status = "PROCESSING"
    db.session.commit()


def _retry_delay(attempts):
    return min(
        BACKOFF_MAX_SECONDS,
        BACKOFF_BASE_SECONDS * (2 ** (attempts - 1)),
    )


def _mark_job_error(job, match):
    job.status = "ERROR"
    job.next_attempt_at = None
    if match is not None:
        match.demo_status = "ERROR"


def _mark_job_retry(job, match):
    job.status = "QUEUED"
    job.next_attempt_at = utcnow() + timedelta(
        seconds=_retry_delay(job.attempts)
    )
    if match is not None:
        match.demo_status = "QUEUED"


def _process_failure(job_id, error, max_attempts):
    db.session.rollback()
    job = db.session.get(MatchmakingDemoJob, job_id)
    match = _job_match(job)
    if job is None:
        return
    message = _truncate(error)
    job.last_error = message
    if match is not None:
        match.processing_error = message
        match.attempts = job.attempts
    if job.attempts >= max_attempts:
        _mark_job_error(job, match)
    else:
        _mark_job_retry(job, match)
    db.session.commit()


def _process_success(job_id, match):
    job = db.session.get(MatchmakingDemoJob, job_id)
    job.status = "OK"
    job.last_error = None
    job.next_attempt_at = None
    match.demo_status = "OK"
    match.processed_at = utcnow()
    match.processing_error = None
    match.attempts = job.attempts
    db.session.commit()
    matchmaking_service.refresh_map_stats(match.user_id)
    db.session.commit()


def process_pending_jobs(limit=JOB_BATCH_SIZE):
    """Procesa trabajos en cola aplicando reintentos con backoff."""
    now = utcnow()
    max_attempts = max(1, _int_config("MATCHMAKING_MAX_ATTEMPTS", 3))
    jobs = (
        db.session.query(MatchmakingDemoJob)
        .filter(MatchmakingDemoJob.status == "QUEUED")
        .order_by(MatchmakingDemoJob.id)
        .all()
    )
    processed = 0
    for job in jobs:
        if processed >= limit:
            break
        if not _job_ready(job, now):
            continue

        _start_job(job)
        try:
            match = _process_job(job)
        except Exception as error:  # noqa: BLE001 - se registra y se reintenta
            _process_failure(job.id, error, max_attempts)
            continue

        _process_success(job.id, match)
        processed += 1
    return processed


def mark_expired_demos():
    """Marca las partidas sin demo que ya no pueden recuperarse.

    Valve elimina las demos de matchmaking alrededor de los 30 días. Pasado el
    plazo, la partida queda como `UNAVAILABLE` y el historial se informa como
    incompleto en vez de quedar esperando para siempre.
    """
    days = max(1, _int_config("MATCHMAKING_DEMO_EXPIRY_DAYS", 31))
    cutoff = utcnow() - timedelta(days=days)
    matches = (
        db.session.query(MatchmakingMatch)
        .filter(
            MatchmakingMatch.demo_status == "AWAITING_DEMO",
            MatchmakingMatch.played_at.isnot(None),
            MatchmakingMatch.played_at < cutoff,
        )
        .all()
    )
    for match in matches:
        match.demo_status = "UNAVAILABLE"
        match.processing_error = _truncate(
            "La demo de Valve ya no está disponible (expira ~30 días)."
        )
    if matches:
        db.session.commit()
    return len(matches)


def run_once():
    """Una pasada completa del worker. Requiere un contexto de aplicación."""
    from app.services import faceit_service

    storage.ensure_dirs()
    manual = process_manual_sync_runs()
    discovered = process_due_authorizations()
    ingested = scan_inbox()
    jobs = process_pending_jobs()
    expired = mark_expired_demos()
    # FACEIT se sincroniza con su propio lease y backoff; un fallo del
    # proveedor nunca interrumpe el procesamiento de demos.
    try:
        faceit = faceit_service.sync_due_accounts()
    except Exception:  # noqa: BLE001 - el worker debe seguir vivo
        db.session.rollback()
        current_app.logger.exception("FACEIT automatic sync failed")
        faceit = {"status": "ERROR", "synced": 0, "skipped": 0, "errors": 1}
    return {
        "manual_runs": manual,
        "discoveries": discovered,
        "ingested": ingested,
        "jobs": jobs,
        "expired": expired,
        "faceit": faceit,
    }


def _wait_next_poll(stop_event, poll):
    if stop_event is None:
        time.sleep(poll)
        return False
    return stop_event.wait(poll)


def run_forever(stop_event=None):
    """Bucle principal con espera configurable entre pasadas."""
    poll = max(1, _int_config("MATCHMAKING_WORKER_POLL_SECONDS", 15))
    while stop_event is None or not stop_event.is_set():
        try:
            run_once()
        except Exception:  # noqa: BLE001 - el worker debe seguir vivo
            current_app.logger.exception("Error en la pasada del worker")
            db.session.rollback()
        if _wait_next_poll(stop_event, poll):
            break
