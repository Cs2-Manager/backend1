"""add steam integration

Revision ID: 9b8f1c2d4e6a
Revises: 3c9a7e5b1d24
Create Date: 2026-10-30 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9b8f1c2d4e6a"
down_revision: Union[str, None] = "3c9a7e5b1d24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "steam_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("steam_id", sa.String(length=20), nullable=False),
        sa.Column("persona_name", sa.String(length=100), nullable=True),
        sa.Column("profile_url", sa.String(length=500), nullable=True),
        sa.Column("avatar_url", sa.String(length=500), nullable=True),
        sa.Column("avatar_medium_url", sa.String(length=500), nullable=True),
        sa.Column("avatar_full_url", sa.String(length=500), nullable=True),
        sa.Column("persona_state", sa.Integer(), nullable=True),
        sa.Column("community_visibility_state", sa.Integer(), nullable=True),
        sa.Column("profile_created_at", sa.DateTime(), nullable=True),
        sa.Column("last_logoff_at", sa.DateTime(), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(), nullable=True),
        sa.Column(
            "last_sync_status",
            sa.String(length=20),
            server_default="NEVER",
            nullable=False,
        ),
        sa.Column("last_sync_error", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_steam_accounts_steam_id"),
        "steam_accounts",
        ["steam_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_steam_accounts_user_id"),
        "steam_accounts",
        ["user_id"],
        unique=True,
    )

    op.create_table(
        "steam_game_stats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("steam_account_id", sa.Integer(), nullable=False),
        sa.Column(
            "app_id",
            sa.Integer(),
            server_default="730",
            nullable=False,
        ),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("playtime_forever_minutes", sa.Integer(), nullable=True),
        sa.Column("playtime_two_weeks_minutes", sa.Integer(), nullable=True),
        sa.Column("last_played_at", sa.DateTime(), nullable=True),
        sa.Column("icon_url", sa.String(length=500), nullable=True),
        sa.Column(
            "source",
            sa.String(length=20),
            server_default="VERIFIED_STEAM",
            nullable=False,
        ),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["steam_account_id"],
            ["steam_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "steam_account_id",
            "app_id",
            name="uq_steam_game_stats_account_app",
        ),
    )
    op.create_index(
        op.f("ix_steam_game_stats_steam_account_id"),
        "steam_game_stats",
        ["steam_account_id"],
        unique=False,
    )

    op.create_table(
        "steam_auth_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("handoff_hash", sa.String(length=64), nullable=True),
        sa.Column("intent", sa.String(length=10), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("return_to", sa.String(length=500), nullable=False),
        sa.Column("steam_id", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("handoff_expires_at", sa.DateTime(), nullable=True),
        sa.Column("handoff_used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_steam_auth_requests_handoff_hash"),
        "steam_auth_requests",
        ["handoff_hash"],
        unique=True,
    )
    op.create_index(
        op.f("ix_steam_auth_requests_state_hash"),
        "steam_auth_requests",
        ["state_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_steam_auth_requests_state_hash"),
        table_name="steam_auth_requests",
    )
    op.drop_index(
        op.f("ix_steam_auth_requests_handoff_hash"),
        table_name="steam_auth_requests",
    )
    op.drop_table("steam_auth_requests")

    op.drop_index(
        op.f("ix_steam_game_stats_steam_account_id"),
        table_name="steam_game_stats",
    )
    op.drop_table("steam_game_stats")

    op.drop_index(
        op.f("ix_steam_accounts_user_id"), table_name="steam_accounts"
    )
    op.drop_index(
        op.f("ix_steam_accounts_steam_id"), table_name="steam_accounts"
    )
    op.drop_table("steam_accounts")
