"""Rutas del historial persistente de notificaciones.

- `GET  /api/notifications`                historial paginado
- `GET  /api/notifications/unread-count`   contador persistente
- `POST /api/notifications/<id>/read`      marcar una como leída
- `POST /api/notifications/read-all`       marcar todas como leídas
"""

from flask import Blueprint, jsonify, request

from app.errors import ApiError
from app.notifications import (
    list_for_user,
    mark_all_read,
    mark_read,
    serialize_notification,
    unread_count,
)
from app.pagination import paginate
from app.security import jwt_required

notifications_bp = Blueprint(
    "notifications", __name__, url_prefix="/api/notifications"
)


@notifications_bp.get("")
@jwt_required()
def history(user):
    query = list_for_user(user)
    items, meta = paginate(query, default_per_page=20)
    return (
        jsonify(
            {
                "notifications": [
                    serialize_notification(recipient, notification)
                    for recipient, notification in items
                ],
                "meta": meta,
                "unread_count": unread_count(user),
            }
        ),
        200,
    )


@notifications_bp.get("/unread-count")
@jwt_required()
def count(user):
    return jsonify({"unread_count": unread_count(user)}), 200


@notifications_bp.post("/<int:notification_id>/read")
@jwt_required()
def read_one(user, notification_id):
    notification = mark_read(user, notification_id)
    if notification is None:
        raise ApiError("Notification not found", status_code=404)
    return (
        jsonify(
            {
                "notification": notification,
                "unread_count": unread_count(user),
            }
        ),
        200,
    )


@notifications_bp.post("/read-all")
@jwt_required()
def read_all(user):
    updated = mark_all_read(user)
    return (
        jsonify({"updated": updated, "unread_count": unread_count(user)}),
        200,
    )
