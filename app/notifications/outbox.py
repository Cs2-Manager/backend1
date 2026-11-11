"""Outbox transaccional y entrega al menos una vez.

La fila de outbox se agrega a la sesión ANTES del commit de la operación de
negocio. Tras el commit se intenta una entrega inmediata; si falla, un hilo de
relay reintenta con backoff exponencial hasta un límite. La idempotencia final
la aporta NestJS por `event_id`.
"""

import logging
import threading
from datetime import datetime, timedelta, timezone

from flask import current_app

from app.extensions import db
from app.models.realtime import (
    Notification,
    NotificationRecipient,
    RealtimeOutbox,
)

from .catalog import render_notification

logger = logging.getLogger(__name__)

_relay_lock = threading.Lock()
_relay_started = False


def _now():
    return datetime.now(timezone.utc)


def _as_aware(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _config_int(name, default):
    try:
        return int(current_app.config.get(name, default))
    except (TypeError, ValueError):
        return default


def _config_float(name, default):
    try:
        return float(current_app.config.get(name, default))
    except (TypeError, ValueError):
        return default


def realtime_enabled():
    from app.realtime.client import is_enabled

    return is_enabled()


def persist_notification(event):
    """Crea la notificación y sus destinatarios en la sesión actual."""
    rendered = render_notification(event)
    if rendered is None:
        return None

    existing = (
        db.session.query(Notification)
        .filter(Notification.event_id == event["event_id"])
        .first()
    )
    if existing is not None:
        event["notification_id"] = existing.id
        return existing

    created_at = _now()
    occurred = event.get("occurred_at")
    if isinstance(occurred, str):
        try:
            created_at = datetime.fromisoformat(occurred.replace("Z", "+00:00"))
        except ValueError:
            pass

    notification = Notification(
        event_id=event["event_id"],
        event_type=event["event_type"],
        team_id=event.get("team_id"),
        resource_type=rendered["resource_type"],
        resource_id=rendered["resource_id"],
        path=rendered["path"],
        title=rendered["title"],
        message=rendered["message"],
        notification_metadata=rendered.get("metadata"),
        created_at=created_at,
    )
    db.session.add(notification)

    seen = set()
    for user_id in event.get("recipients") or []:
        if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id < 1:
            continue
        if user_id in seen:
            continue
        seen.add(user_id)
        db.session.add(
            NotificationRecipient(
                notification=notification,
                user_id=user_id,
                created_at=created_at,
            )
        )
    # El id de la notificación persistida viaja en el evento para que el
    # frontend pueda marcarla como leída sin una recarga adicional.
    db.session.flush()
    event["notification_id"] = notification.id
    return notification


def queue_event(event):
    """Persiste notificación (si aplica) y outbox en la transacción actual.

    Si el servicio realtime está deshabilitado, la notificación se guarda igual
    para que el historial siga disponible; no se crea una outbox que nunca
    podría entregarse.
    """
    if not isinstance(event, dict) or not event.get("event_id"):
        return None

    persist_notification(event)

    if not realtime_enabled():
        return None

    existing = (
        db.session.query(RealtimeOutbox)
        .filter(RealtimeOutbox.event_id == event["event_id"])
        .first()
    )
    if existing is not None:
        return existing

    row = RealtimeOutbox(
        event_id=event["event_id"],
        event_type=event["event_type"],
        payload=event,
        status="PENDING",
        attempts=0,
        next_attempt_at=_now(),
        created_at=_now(),
    )
    db.session.add(row)
    return row


def _backoff_seconds(attempts):
    base = _config_float("REALTIME_OUTBOX_BACKOFF_BASE_SECONDS", 2.0)
    maximum = _config_float("REALTIME_OUTBOX_BACKOFF_MAX_SECONDS", 300.0)
    delay = base * (2 ** max(attempts - 1, 0))
    return min(delay, maximum)


def dispatch_event(event_id):
    """Intenta entregar una fila concreta. Devuelve True si fue aceptada."""
    if not realtime_enabled():
        return False

    row = (
        db.session.query(RealtimeOutbox)
        .filter(RealtimeOutbox.event_id == event_id)
        .first()
    )
    if row is None:
        return False
    if row.status == "DELIVERED":
        return True

    from app.realtime.client import publish_event

    delivered = bool(publish_event(row.payload))
    row.attempts = (row.attempts or 0) + 1
    now = _now()

    if delivered:
        row.status = "DELIVERED"
        row.delivered_at = now
        row.last_error = None
        db.session.query(NotificationRecipient).filter(
            NotificationRecipient.notification_id
            == db.session.query(Notification.id)
            .filter(Notification.event_id == event_id)
            .scalar_subquery()
        ).filter(NotificationRecipient.delivered_at.is_(None)).update(
            {NotificationRecipient.delivered_at: now},
            synchronize_session=False,
        )
    else:
        max_attempts = max(_config_int("REALTIME_OUTBOX_MAX_ATTEMPTS", 8), 1)
        row.last_error = "Realtime delivery failed"
        if row.attempts >= max_attempts:
            row.status = "FAILED"
        else:
            row.status = "PENDING"
            row.next_attempt_at = now + timedelta(
                seconds=_backoff_seconds(row.attempts)
            )

    try:
        db.session.commit()
    except Exception:  # noqa: BLE001 - nunca romper la operación que ya commiteó
        db.session.rollback()
        logger.warning("Realtime outbox state could not be persisted")
        return delivered
    return delivered


def dispatch_many(event_ids):
    delivered = 0
    for event_id in event_ids:
        if event_id and dispatch_event(event_id):
            delivered += 1
    return delivered


def run_once(limit=None):
    """Reintenta las filas pendientes vencidas. Devuelve cuántas se intentaron."""
    if not realtime_enabled():
        return 0

    limit = limit or _config_int("REALTIME_OUTBOX_BATCH_SIZE", 20)
    now = _now()
    rows = (
        db.session.query(RealtimeOutbox.event_id)
        .filter(
            RealtimeOutbox.status == "PENDING",
            RealtimeOutbox.next_attempt_at <= now,
        )
        .order_by(RealtimeOutbox.id)
        .limit(limit)
        .all()
    )
    attempted = 0
    for (event_id,) in rows:
        dispatch_event(event_id)
        attempted += 1
    return attempted


def relay_loop(app):
    interval = max(
        int(app.config.get("REALTIME_OUTBOX_RELAY_INTERVAL_SECONDS", 5) or 5),
        1,
    )
    while True:
        try:
            with app.app_context():
                try:
                    run_once()
                finally:
                    db.session.remove()
        except Exception:  # noqa: BLE001 - el relay no debe morir por un fallo
            logger.exception("Realtime outbox relay iteration failed")
        threading.Event().wait(interval)


def start_relay(app):
    """Arranca el relay una sola vez por proceso si está habilitado."""
    global _relay_started
    if not app.config.get("REALTIME_OUTBOX_RELAY_ENABLED", False):
        return False
    if not app.config.get("REALTIME_ENABLED", False):
        return False

    with _relay_lock:
        if _relay_started:
            return False
        _relay_started = True

    thread = threading.Thread(
        target=relay_loop,
        args=(app,),
        name="realtime-outbox-relay",
        daemon=True,
    )
    thread.start()
    app.logger.info("Realtime outbox relay started")
    return True
