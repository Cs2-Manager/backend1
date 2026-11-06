"""add cs2 matchmaking stats

Revision ID: c4f2a8d6e1b9
Revises: 9b8f1c2d4e6a
Create Date: 2026-10-31 02:30:00.000000

Migración aditiva: crea las cinco tablas de estadísticas de matchmaking de
CS2. No modifica tablas existentes y el downgrade elimina solo estas tablas.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c4f2a8d6e1b9"
down_revision: Union[str, None] = "9b8f1c2d4e6a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "matchmaking_authorizations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("steam_id", sa.String(length=20), nullable=False),
        sa.Column("auth_code_encrypted", sa.Text(), nullable=True),
        sa.Column("first_share_code", sa.String(length=80), nullable=True),
        sa.Column("cursor_share_code", sa.String(length=80), nullable=True),
        sa.Column(
            "status",
            sa.String(length=10),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column("authorized_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("last_discovery_at", sa.DateTime(), nullable=True),
        sa.Column("last_discovery_status", sa.String(length=20), nullable=True),
        sa.Column(
            "last_discovery_error", sa.String(length=300), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_matchmaking_authorizations_user_id"),
        "matchmaking_authorizations",
        ["user_id"],
        unique=True,
    )

    op.create_table(
        "matchmaking_matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("authorization_id", sa.Integer(), nullable=True),
        sa.Column("share_code", sa.String(length=80), nullable=True),
        sa.Column("match_id", sa.BigInteger(), nullable=True),
        sa.Column("map_name", sa.String(length=80), nullable=True),
        sa.Column("played_at", sa.DateTime(), nullable=True),
        sa.Column(
            "result",
            sa.String(length=10),
            server_default="UNKNOWN",
            nullable=False,
        ),
        sa.Column("team_score", sa.Integer(), nullable=True),
        sa.Column("opponent_score", sa.Integer(), nullable=True),
        sa.Column("rounds_played", sa.Integer(), nullable=False),
        sa.Column("rounds_won", sa.Integer(), nullable=False),
        sa.Column("rounds_lost", sa.Integer(), nullable=False),
        sa.Column("kills", sa.Integer(), nullable=False),
        sa.Column("deaths", sa.Integer(), nullable=False),
        sa.Column("assists", sa.Integer(), nullable=False),
        sa.Column("damage", sa.Integer(), nullable=False),
        sa.Column("headshot_kills", sa.Integer(), nullable=False),
        sa.Column("mvps", sa.Integer(), nullable=False),
        sa.Column("clutches", sa.Integer(), nullable=False),
        sa.Column("opening_kills", sa.Integer(), nullable=False),
        sa.Column("opening_deaths", sa.Integer(), nullable=False),
        sa.Column("kast_rounds", sa.Integer(), nullable=False),
        sa.Column("adr", sa.Numeric(precision=6, scale=1), nullable=True),
        sa.Column(
            "hs_percentage", sa.Numeric(precision=5, scale=1), nullable=True
        ),
        sa.Column("kd", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column(
            "kast_percentage", sa.Numeric(precision=5, scale=1), nullable=True
        ),
        sa.Column(
            "demo_status",
            sa.String(length=20),
            server_default="AWAITING_DEMO",
            nullable=False,
        ),
        sa.Column("demo_sha256", sa.String(length=64), nullable=True),
        sa.Column("demo_path", sa.String(length=500), nullable=True),
        sa.Column("processing_error", sa.String(length=300), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["authorization_id"],
            ["matchmaking_authorizations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "demo_sha256",
            name="uq_matchmaking_matches_user_demo_sha",
        ),
        sa.UniqueConstraint(
            "user_id",
            "match_id",
            name="uq_matchmaking_matches_user_match_id",
        ),
        sa.UniqueConstraint(
            "user_id",
            "share_code",
            name="uq_matchmaking_matches_user_share_code",
        ),
    )
    op.create_index(
        op.f("ix_matchmaking_matches_demo_status"),
        "matchmaking_matches",
        ["demo_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_matchmaking_matches_user_id"),
        "matchmaking_matches",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "matchmaking_map_stats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("map_name", sa.String(length=80), nullable=False),
        sa.Column("matches", sa.Integer(), nullable=False),
        sa.Column("wins", sa.Integer(), nullable=False),
        sa.Column("losses", sa.Integer(), nullable=False),
        sa.Column("draws", sa.Integer(), nullable=False),
        sa.Column("rounds_played", sa.Integer(), nullable=False),
        sa.Column("kills", sa.Integer(), nullable=False),
        sa.Column("deaths", sa.Integer(), nullable=False),
        sa.Column("assists", sa.Integer(), nullable=False),
        sa.Column("damage", sa.Integer(), nullable=False),
        sa.Column("headshot_kills", sa.Integer(), nullable=False),
        sa.Column("kast_rounds", sa.Integer(), nullable=False),
        sa.Column("mvps", sa.Integer(), nullable=False),
        sa.Column("clutches", sa.Integer(), nullable=False),
        sa.Column("opening_kills", sa.Integer(), nullable=False),
        sa.Column("opening_deaths", sa.Integer(), nullable=False),
        sa.Column("adr", sa.Numeric(precision=6, scale=1), nullable=True),
        sa.Column(
            "hs_percentage", sa.Numeric(precision=5, scale=1), nullable=True
        ),
        sa.Column("kd", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column(
            "kast_percentage", sa.Numeric(precision=5, scale=1), nullable=True
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "map_name", name="uq_matchmaking_map_stats_user_map"
        ),
    )
    op.create_index(
        op.f("ix_matchmaking_map_stats_user_id"),
        "matchmaking_map_stats",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "matchmaking_demo_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("match_id", sa.Integer(), nullable=True),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="QUEUED",
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["match_id"],
            ["matchmaking_matches.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_matchmaking_demo_jobs_match_id"),
        "matchmaking_demo_jobs",
        ["match_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_matchmaking_demo_jobs_sha256"),
        "matchmaking_demo_jobs",
        ["sha256"],
        unique=True,
    )
    op.create_index(
        op.f("ix_matchmaking_demo_jobs_status"),
        "matchmaking_demo_jobs",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_matchmaking_demo_jobs_user_id"),
        "matchmaking_demo_jobs",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "matchmaking_sync_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="RUNNING",
            nullable=False,
        ),
        sa.Column("found", sa.Integer(), nullable=False),
        sa.Column("processed", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("message", sa.String(length=300), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_matchmaking_sync_runs_user_id"),
        "matchmaking_sync_runs",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_matchmaking_sync_runs_user_id"),
        table_name="matchmaking_sync_runs",
    )
    op.drop_table("matchmaking_sync_runs")

    op.drop_index(
        op.f("ix_matchmaking_demo_jobs_user_id"),
        table_name="matchmaking_demo_jobs",
    )
    op.drop_index(
        op.f("ix_matchmaking_demo_jobs_status"),
        table_name="matchmaking_demo_jobs",
    )
    op.drop_index(
        op.f("ix_matchmaking_demo_jobs_sha256"),
        table_name="matchmaking_demo_jobs",
    )
    op.drop_index(
        op.f("ix_matchmaking_demo_jobs_match_id"),
        table_name="matchmaking_demo_jobs",
    )
    op.drop_table("matchmaking_demo_jobs")

    op.drop_index(
        op.f("ix_matchmaking_map_stats_user_id"),
        table_name="matchmaking_map_stats",
    )
    op.drop_table("matchmaking_map_stats")

    op.drop_index(
        op.f("ix_matchmaking_matches_user_id"),
        table_name="matchmaking_matches",
    )
    op.drop_index(
        op.f("ix_matchmaking_matches_demo_status"),
        table_name="matchmaking_matches",
    )
    op.drop_table("matchmaking_matches")

    op.drop_index(
        op.f("ix_matchmaking_authorizations_user_id"),
        table_name="matchmaking_authorizations",
    )
    op.drop_table("matchmaking_authorizations")
