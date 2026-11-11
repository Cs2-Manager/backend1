"""Notificaciones persistentes, outbox transaccional y relay de entrega."""

from .outbox import (
    dispatch_event,
    dispatch_many,
    persist_notification,
    queue_event,
    run_once,
    start_relay,
)
from .service import (
    list_for_user,
    mark_all_read,
    mark_read,
    serialize_notification,
    unread_count,
)

__all__ = [
    "dispatch_event",
    "dispatch_many",
    "list_for_user",
    "mark_all_read",
    "mark_read",
    "persist_notification",
    "queue_event",
    "run_once",
    "serialize_notification",
    "start_relay",
    "unread_count",
]
