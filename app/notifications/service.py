"""Consultas y lectura de notificaciones persistentes."""

from datetime import datetime, timezone

from sqlalchemy import func, or_

from app.extensions import db
from app.models.realtime import Notification, NotificationRecipient
from app.models.team import TeamMember


def _utcnow():
    return datetime.now(timezone.utc)


def _iso(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _visible_filter(user):
    """Un usuario solo ve notificaciones de equipos a los que pertenece hoy.

    Las invitaciones recibidas son personales y siguen visibles aunque el
    usuario no pertenezca al equipo. Así, cambiar de equipo no filtra el
    historial privado de otro equipo ni expone notificaciones ajenas.
    """
    member_teams = db.session.query(TeamMember.team_id).filter(
        TeamMember.user_id == user.id
    )
    return or_(
        Notification.team_id.is_(None),
        Notification.event_type == "team.invitation.created",
        Notification.team_id.in_(member_teams),
    )


def _base_query(user):
    return (
        db.session.query(NotificationRecipient, Notification)
        .join(Notification, Notification.id == NotificationRecipient.notification_id)
        .filter(
            NotificationRecipient.user_id == user.id,
            _visible_filter(user),
        )
    )


def serialize_notification(recipient, notification):
    return {
        "id": notification.event_id,
        "notification_id": notification.id,
        "event_id": notification.event_id,
        "event_type": notification.event_type,
        "created_at": _iso(notification.created_at),
        "title": notification.title,
        "message": notification.message,
        "resource": {
            "type": notification.resource_type,
            "id": notification.resource_id,
            "team_id": notification.team_id,
            "path": notification.path,
        },
        "metadata": notification.notification_metadata or {},
        "read": recipient.read_at is not None,
        "read_at": _iso(recipient.read_at),
        "delivered_at": _iso(recipient.delivered_at),
    }


def list_for_user(user):
    return _base_query(user).order_by(
        Notification.created_at.desc(), Notification.id.desc()
    )


def unread_count(user):
    return (
        _base_query(user)
        .filter(NotificationRecipient.read_at.is_(None))
        .with_entities(func.count(NotificationRecipient.id))
        .scalar()
        or 0
    )


def mark_read(user, notification_id):
    row = (
        _base_query(user)
        .filter(Notification.id == notification_id)
        .first()
    )
    if row is None:
        return None
    recipient, notification = row
    if recipient.read_at is None:
        recipient.read_at = _utcnow()
        db.session.commit()
    return serialize_notification(recipient, notification)


def mark_all_read(user):
    rows = (
        _base_query(user)
        .filter(NotificationRecipient.read_at.is_(None))
        .all()
    )
    now = _utcnow()
    for recipient, _notification in rows:
        recipient.read_at = now
    if rows:
        db.session.commit()
    return len(rows)
