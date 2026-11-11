"""Realtime notifications, transactional outbox and team activity.

Migración aditiva y reversible. No modifica tablas existentes ni migraciones
históricas. La cabeza previa es `f9b700000007`.
"""
from alembic import op
import sqlalchemy as sa

revision = "fa7c00000008"
down_revision = "f9b700000007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column(
            "team_id",
            sa.Integer(),
            sa.ForeignKey("teams.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("resource_type", sa.String(40), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("path", sa.String(300), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("notification_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_notifications_event_id", "notifications", ["event_id"], unique=True)
    op.create_index("ix_notifications_event_type", "notifications", ["event_type"])
    op.create_index("ix_notifications_team_id", "notifications", ["team_id"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])

    op.create_table(
        "notification_recipients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "notification_id",
            sa.Integer(),
            sa.ForeignKey("notifications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "notification_id",
            "user_id",
            name="uq_notification_recipient",
        ),
    )
    op.create_index(
        "ix_notification_recipients_notification_id",
        "notification_recipients",
        ["notification_id"],
    )
    op.create_index(
        "ix_notification_recipients_user_id",
        "notification_recipients",
        ["user_id"],
    )
    op.create_index(
        "ix_notification_recipients_user_read",
        "notification_recipients",
        ["user_id", "read_at"],
    )
    op.create_index(
        "ix_notification_recipients_user_created",
        "notification_recipients",
        ["user_id", "created_at"],
    )

    op.create_table(
        "realtime_outbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("last_error", sa.String(300), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('PENDING','DELIVERED','FAILED')",
            name="ck_realtime_outbox_status",
        ),
    )
    op.create_index(
        "ix_realtime_outbox_event_id",
        "realtime_outbox",
        ["event_id"],
        unique=True,
    )
    op.create_index("ix_realtime_outbox_event_type", "realtime_outbox", ["event_type"])
    op.create_index("ix_realtime_outbox_status", "realtime_outbox", ["status"])
    op.create_index(
        "ix_realtime_outbox_next_attempt_at",
        "realtime_outbox",
        ["next_attempt_at"],
    )
    op.create_index(
        "ix_realtime_outbox_status_next",
        "realtime_outbox",
        ["status", "next_attempt_at"],
    )

    op.create_table(
        "team_activity",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "event_id",
            sa.String(36),
            nullable=False,
        ),
        sa.Column(
            "team_id",
            sa.Integer(),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("activity_type", sa.String(60), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column(
            "actor_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_username", sa.String(80), nullable=False, server_default=""),
        sa.Column("resource_type", sa.String(40), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("path", sa.String(300), nullable=False),
        sa.Column("activity_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_team_activity_event_id", "team_activity", ["event_id"], unique=True)
    op.create_index("ix_team_activity_team_id", "team_activity", ["team_id"])
    op.create_index("ix_team_activity_activity_type", "team_activity", ["activity_type"])
    op.create_index("ix_team_activity_created_at", "team_activity", ["created_at"])
    op.create_index(
        "ix_team_activity_team_created",
        "team_activity",
        ["team_id", "created_at"],
    )


def downgrade():
    op.drop_index("ix_team_activity_team_created", table_name="team_activity")
    op.drop_index("ix_team_activity_created_at", table_name="team_activity")
    op.drop_index("ix_team_activity_activity_type", table_name="team_activity")
    op.drop_index("ix_team_activity_team_id", table_name="team_activity")
    op.drop_index("ix_team_activity_event_id", table_name="team_activity")
    op.drop_table("team_activity")

    op.drop_index("ix_realtime_outbox_status_next", table_name="realtime_outbox")
    op.drop_index("ix_realtime_outbox_next_attempt_at", table_name="realtime_outbox")
    op.drop_index("ix_realtime_outbox_status", table_name="realtime_outbox")
    op.drop_index("ix_realtime_outbox_event_type", table_name="realtime_outbox")
    op.drop_index("ix_realtime_outbox_event_id", table_name="realtime_outbox")
    op.drop_table("realtime_outbox")

    op.drop_index(
        "ix_notification_recipients_user_created",
        table_name="notification_recipients",
    )
    op.drop_index(
        "ix_notification_recipients_user_read",
        table_name="notification_recipients",
    )
    op.drop_index(
        "ix_notification_recipients_user_id",
        table_name="notification_recipients",
    )
    op.drop_index(
        "ix_notification_recipients_notification_id",
        table_name="notification_recipients",
    )
    op.drop_table("notification_recipients")

    op.drop_index("ix_notifications_created_at", table_name="notifications")
    op.drop_index("ix_notifications_team_id", table_name="notifications")
    op.drop_index("ix_notifications_event_type", table_name="notifications")
    op.drop_index("ix_notifications_event_id", table_name="notifications")
    op.drop_table("notifications")
