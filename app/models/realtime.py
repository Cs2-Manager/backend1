"""Persistencia de notificaciones, outbox y actividad de equipos.

Estas tablas son propiedad de Flask. NestJS no replica usuarios, equipos ni
permisos: solo recibe eventos firmados y los entrega por Socket.IO. La outbox se
escribe en la MISMA transacción que la operación de negocio, de modo que un
evento no puede perderse si el proceso cae entre el commit y el envío HTTP.

Entrega: al menos una vez. La idempotencia real la garantiza NestJS por
`event_id`; la outbox solo reintenta hasta un límite y conserva el fallo.
"""

from datetime import datetime, timezone

from app.extensions import db

NOTIFICATION_STATUSES = ("PENDING", "DELIVERED", "FAILED")


def _utcnow():
    return datetime.now(timezone.utc)


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.String(36), nullable=False, unique=True, index=True)
    event_type = db.Column(db.String(60), nullable=False, index=True)
    team_id = db.Column(
        db.Integer,
        db.ForeignKey("teams.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    resource_type = db.Column(db.String(40), nullable=False)
    resource_id = db.Column(db.Integer, nullable=False)
    path = db.Column(db.String(300), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    notification_metadata = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow, index=True)

    recipients = db.relationship(
        "NotificationRecipient",
        back_populates="notification",
        cascade="all, delete-orphan",
    )


class NotificationRecipient(db.Model):
    __tablename__ = "notification_recipients"
    __table_args__ = (
        db.UniqueConstraint(
            "notification_id",
            "user_id",
            name="uq_notification_recipient",
        ),
        db.Index(
            "ix_notification_recipients_user_read",
            "user_id",
            "read_at",
        ),
        db.Index(
            "ix_notification_recipients_user_created",
            "user_id",
            "created_at",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    notification_id = db.Column(
        db.Integer,
        db.ForeignKey("notifications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    read_at = db.Column(db.DateTime, nullable=True)
    delivered_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    notification = db.relationship("Notification", back_populates="recipients")
    user = db.relationship("User")


class RealtimeOutbox(db.Model):
    __tablename__ = "realtime_outbox"
    __table_args__ = (
        db.CheckConstraint(
            "status IN ('PENDING','DELIVERED','FAILED')",
            name="ck_realtime_outbox_status",
        ),
        db.Index(
            "ix_realtime_outbox_status_next",
            "status",
            "next_attempt_at",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.String(36), nullable=False, unique=True, index=True)
    event_type = db.Column(db.String(60), nullable=False, index=True)
    payload = db.Column(db.JSON, nullable=False)
    status = db.Column(
        db.String(12),
        nullable=False,
        default="PENDING",
        server_default="PENDING",
        index=True,
    )
    attempts = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    next_attempt_at = db.Column(
        db.DateTime, nullable=False, default=_utcnow, index=True
    )
    last_error = db.Column(db.String(300), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    delivered_at = db.Column(db.DateTime, nullable=True)


class TeamActivity(db.Model):
    __tablename__ = "team_activity"
    __table_args__ = (
        db.Index(
            "ix_team_activity_team_created",
            "team_id",
            "created_at",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.String(36), nullable=False, unique=True, index=True)
    team_id = db.Column(
        db.Integer,
        db.ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    activity_type = db.Column(db.String(60), nullable=False, index=True)
    description = db.Column(db.String(500), nullable=False)
    actor_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_username = db.Column(db.String(80), nullable=False, default="")
    resource_type = db.Column(db.String(40), nullable=False)
    resource_id = db.Column(db.Integer, nullable=False)
    path = db.Column(db.String(300), nullable=False)
    activity_metadata = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow, index=True)
