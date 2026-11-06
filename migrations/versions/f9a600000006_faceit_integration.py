"""add FACEIT integration

Revision ID: f9a600000006
Revises: f8e500000005
Create Date: 2026-11-02 12:00:00.000000

Migración aditiva y reversible: crea las tablas de FACEIT sin tocar Steam,
matchmaking, perfiles, equipos ni el catálogo táctico.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f9a600000006"
down_revision: Union[str, None] = "f8e500000005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "faceit_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("faceit_player_id", sa.String(length=64), nullable=False),
        sa.Column("nickname", sa.String(length=100), nullable=True),
        sa.Column("avatar_url", sa.String(length=500), nullable=True),
        sa.Column("cover_image_url", sa.String(length=500), nullable=True),
        sa.Column("country", sa.String(length=8), nullable=True),
        sa.Column("region", sa.String(length=20), nullable=True),
        sa.Column("steam_id", sa.String(length=20), nullable=True),
        sa.Column("steam_nickname", sa.String(length=100), nullable=True),
        sa.Column("faceit_url", sa.String(length=500), nullable=True),
        sa.Column("skill_level", sa.Integer(), nullable=True),
        sa.Column("elo", sa.Integer(), nullable=True),
        sa.Column(
            "link_status",
            sa.String(length=20),
            server_default="DISCOVERED",
            nullable=False,
        ),
        sa.Column(
            "verification_source",
            sa.String(length=20),
            server_default="STEAM_DISCOVERY",
            nullable=False,
        ),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column(
            "sync_enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_faceit_accounts_user_id"),
        "faceit_accounts",
        ["user_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_faceit_accounts_faceit_player_id"),
        "faceit_accounts",
        ["faceit_player_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_faceit_accounts_steam_id"),
        "faceit_accounts",
        ["steam_id"],
        unique=False,
    )

    op.create_table(
        "faceit_player_stats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column(
            "game_id",
            sa.String(length=20),
            server_default="cs2",
            nullable=False,
        ),
        sa.Column("matches_played", sa.Integer(), nullable=True),
        sa.Column("wins", sa.Integer(), nullable=True),
        sa.Column("losses", sa.Integer(), nullable=True),
        sa.Column("win_rate", sa.Float(), nullable=True),
        sa.Column("kills", sa.Integer(), nullable=True),
        sa.Column("deaths", sa.Integer(), nullable=True),
        sa.Column("assists", sa.Integer(), nullable=True),
        sa.Column("kd", sa.Float(), nullable=True),
        sa.Column("kr", sa.Float(), nullable=True),
        sa.Column("headshots", sa.Integer(), nullable=True),
        sa.Column("headshot_percentage", sa.Float(), nullable=True),
        sa.Column("adr", sa.Float(), nullable=True),
        sa.Column("mvps", sa.Integer(), nullable=True),
        sa.Column("triple_kills", sa.Integer(), nullable=True),
        sa.Column("quadruple_kills", sa.Integer(), nullable=True),
        sa.Column("penta_kills", sa.Integer(), nullable=True),
        sa.Column("rounds_played", sa.Integer(), nullable=True),
        sa.Column("total_damage", sa.Integer(), nullable=True),
        sa.Column(
            "source",
            sa.String(length=20),
            server_default="VERIFIED_FACEIT",
            nullable=False,
        ),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"], ["faceit_accounts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id", name="uq_faceit_player_stats_account"
        ),
    )
    op.create_index(
        op.f("ix_faceit_player_stats_account_id"),
        "faceit_player_stats",
        ["account_id"],
        unique=False,
    )

    op.create_table(
        "faceit_matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("faceit_match_id", sa.String(length=64), nullable=False),
        sa.Column("played_at", sa.DateTime(), nullable=True),
        sa.Column("game_mode", sa.String(length=60), nullable=True),
        sa.Column("map_name", sa.String(length=80), nullable=True),
        sa.Column("region", sa.String(length=20), nullable=True),
        sa.Column("competition_name", sa.String(length=160), nullable=True),
        sa.Column("result", sa.String(length=10), nullable=True),
        sa.Column("team_score", sa.Integer(), nullable=True),
        sa.Column("opponent_score", sa.Integer(), nullable=True),
        sa.Column("score", sa.String(length=40), nullable=True),
        sa.Column("player_team_name", sa.String(length=120), nullable=True),
        sa.Column("opponent_team_name", sa.String(length=120), nullable=True),
        sa.Column("faceit_url", sa.String(length=500), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="PARTIAL",
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.String(length=20),
            server_default="VERIFIED_FACEIT",
            nullable=False,
        ),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"], ["faceit_accounts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id",
            "faceit_match_id",
            name="uq_faceit_matches_account_match",
        ),
    )
    op.create_index(
        op.f("ix_faceit_matches_account_id"),
        "faceit_matches",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_faceit_matches_faceit_match_id"),
        "faceit_matches",
        ["faceit_match_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_faceit_matches_played_at"),
        "faceit_matches",
        ["played_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_faceit_matches_map_name"),
        "faceit_matches",
        ["map_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_faceit_matches_result"),
        "faceit_matches",
        ["result"],
        unique=False,
    )

    op.create_table(
        "faceit_match_player_stats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("kills", sa.Integer(), nullable=True),
        sa.Column("deaths", sa.Integer(), nullable=True),
        sa.Column("assists", sa.Integer(), nullable=True),
        sa.Column("kd", sa.Float(), nullable=True),
        sa.Column("kr", sa.Float(), nullable=True),
        sa.Column("adr", sa.Float(), nullable=True),
        sa.Column("headshot_percentage", sa.Float(), nullable=True),
        sa.Column("mvps", sa.Integer(), nullable=True),
        sa.Column("rounds_played", sa.Integer(), nullable=True),
        sa.Column(
            "source",
            sa.String(length=20),
            server_default="VERIFIED_FACEIT",
            nullable=False,
        ),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["match_id"], ["faceit_matches.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "match_id", name="uq_faceit_match_player_stats_match"
        ),
    )
    op.create_index(
        op.f("ix_faceit_match_player_stats_match_id"),
        "faceit_match_player_stats",
        ["match_id"],
        unique=False,
    )

    op.create_table(
        "faceit_map_stats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("map_name", sa.String(length=80), nullable=False),
        sa.Column("matches_played", sa.Integer(), nullable=True),
        sa.Column("wins", sa.Integer(), nullable=True),
        sa.Column("losses", sa.Integer(), nullable=True),
        sa.Column("win_rate", sa.Float(), nullable=True),
        sa.Column("kills", sa.Integer(), nullable=True),
        sa.Column("deaths", sa.Integer(), nullable=True),
        sa.Column("assists", sa.Integer(), nullable=True),
        sa.Column("kd", sa.Float(), nullable=True),
        sa.Column("adr", sa.Float(), nullable=True),
        sa.Column("headshot_percentage", sa.Float(), nullable=True),
        sa.Column(
            "source",
            sa.String(length=20),
            server_default="VERIFIED_FACEIT",
            nullable=False,
        ),
        sa.Column(
            "calculated_from",
            sa.String(length=20),
            server_default="FACEIT_SEGMENT",
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"], ["faceit_accounts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id",
            "map_name",
            name="uq_faceit_map_stats_account_map",
        ),
    )
    op.create_index(
        op.f("ix_faceit_map_stats_account_id"),
        "faceit_map_stats",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_faceit_map_stats_map_name"),
        "faceit_map_stats",
        ["map_name"],
        unique=False,
    )

    op.create_table(
        "faceit_elo_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("elo", sa.Integer(), nullable=False),
        sa.Column("skill_level", sa.Integer(), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column(
            "source",
            sa.String(length=30),
            server_default="VERIFIED_FACEIT",
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["faceit_accounts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id",
            "captured_at",
            name="uq_faceit_elo_snapshots_account_time",
        ),
    )
    op.create_index(
        op.f("ix_faceit_elo_snapshots_account_id"),
        "faceit_elo_snapshots",
        ["account_id"],
        unique=False,
    )

    op.create_table(
        "faceit_sync_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="NEVER",
            nullable=False,
        ),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("next_sync_at", sa.DateTime(), nullable=True),
        sa.Column(
            "consecutive_failures",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("last_error", sa.String(length=300), nullable=True),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"], ["faceit_accounts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id", name="uq_faceit_sync_states_account"
        ),
    )
    op.create_index(
        op.f("ix_faceit_sync_states_account_id"),
        "faceit_sync_states",
        ["account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_faceit_sync_states_next_sync_at"),
        "faceit_sync_states",
        ["next_sync_at"],
        unique=False,
    )

    op.create_table(
        "faceit_oauth_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("code_verifier_encrypted", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("return_to", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_faceit_oauth_requests_state_hash"),
        "faceit_oauth_requests",
        ["state_hash"],
        unique=True,
    )
    op.create_index(
        op.f("ix_faceit_oauth_requests_user_id"),
        "faceit_oauth_requests",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_faceit_oauth_requests_user_id"),
        table_name="faceit_oauth_requests",
    )
    op.drop_index(
        op.f("ix_faceit_oauth_requests_state_hash"),
        table_name="faceit_oauth_requests",
    )
    op.drop_table("faceit_oauth_requests")

    op.drop_index(
        op.f("ix_faceit_sync_states_next_sync_at"),
        table_name="faceit_sync_states",
    )
    op.drop_index(
        op.f("ix_faceit_sync_states_account_id"),
        table_name="faceit_sync_states",
    )
    op.drop_table("faceit_sync_states")

    op.drop_index(
        op.f("ix_faceit_elo_snapshots_account_id"),
        table_name="faceit_elo_snapshots",
    )
    op.drop_table("faceit_elo_snapshots")

    op.drop_index(
        op.f("ix_faceit_map_stats_map_name"), table_name="faceit_map_stats"
    )
    op.drop_index(
        op.f("ix_faceit_map_stats_account_id"), table_name="faceit_map_stats"
    )
    op.drop_table("faceit_map_stats")

    op.drop_index(
        op.f("ix_faceit_match_player_stats_match_id"),
        table_name="faceit_match_player_stats",
    )
    op.drop_table("faceit_match_player_stats")

    op.drop_index(
        op.f("ix_faceit_matches_result"), table_name="faceit_matches"
    )
    op.drop_index(
        op.f("ix_faceit_matches_map_name"), table_name="faceit_matches"
    )
    op.drop_index(
        op.f("ix_faceit_matches_played_at"), table_name="faceit_matches"
    )
    op.drop_index(
        op.f("ix_faceit_matches_faceit_match_id"),
        table_name="faceit_matches",
    )
    op.drop_index(
        op.f("ix_faceit_matches_account_id"), table_name="faceit_matches"
    )
    op.drop_table("faceit_matches")

    op.drop_index(
        op.f("ix_faceit_player_stats_account_id"),
        table_name="faceit_player_stats",
    )
    op.drop_table("faceit_player_stats")

    op.drop_index(
        op.f("ix_faceit_accounts_steam_id"),
        table_name="faceit_accounts",
    )
    op.drop_index(
        op.f("ix_faceit_accounts_faceit_player_id"),
        table_name="faceit_accounts",
    )
    op.drop_index(
        op.f("ix_faceit_accounts_user_id"), table_name="faceit_accounts"
    )
    op.drop_table("faceit_accounts")
