"""add player profiles and match history

Revision ID: d3900c44a271
Revises: ea783557e94b
Create Date: 2026-10-29 20:57:45.101981

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd3900c44a271'
down_revision: Union[str, None] = 'ea783557e94b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "player_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("nickname", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=True),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("avatar_url", sa.String(length=500), nullable=True),
        sa.Column("steam_url", sa.String(length=500), nullable=True),
        sa.Column(
            "visibility",
            sa.String(length=10),
            server_default="PRIVATE",
            nullable=False,
        ),
        sa.Column("last_active_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_player_profiles_user_id"),
        "player_profiles",
        ["user_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_player_profiles_nickname"),
        "player_profiles",
        ["nickname"],
        unique=True,
    )

    op.create_table(
        "player_competitive_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=True),
        sa.Column("elo", sa.Integer(), nullable=True),
        sa.Column("xp", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="UNRANKED",
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["player_profiles.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_player_competitive_profiles_profile_id"),
        "player_competitive_profiles",
        ["profile_id"],
        unique=True,
    )

    op.create_table(
        "player_stats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column(
            "matches_played",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("wins", sa.Integer(), server_default="0", nullable=False),
        sa.Column("losses", sa.Integer(), server_default="0", nullable=False),
        sa.Column("draws", sa.Integer(), server_default="0", nullable=False),
        sa.Column("kills", sa.Integer(), server_default="0", nullable=False),
        sa.Column("deaths", sa.Integer(), server_default="0", nullable=False),
        sa.Column("assists", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "headshots", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "rounds_played",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "total_damage",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["player_profiles.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_player_stats_profile_id"),
        "player_stats",
        ["profile_id"],
        unique=True,
    )

    op.create_table(
        "player_social_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["player_profiles.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "profile_id",
            "platform",
            name="uq_player_social_links_profile_platform",
        ),
    )

    op.create_table(
        "player_matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("map_id", sa.Integer(), nullable=True),
        sa.Column("played_at", sa.DateTime(), nullable=False),
        sa.Column(
            "match_type",
            sa.String(length=20),
            server_default="COMPETITIVE",
            nullable=False,
        ),
        sa.Column("result", sa.String(length=10), nullable=False),
        sa.Column("kills", sa.Integer(), server_default="0", nullable=False),
        sa.Column("deaths", sa.Integer(), server_default="0", nullable=False),
        sa.Column("assists", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "headshots", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "rounds_played",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("damage", sa.Integer(), server_default="0", nullable=False),
        sa.Column("elo_before", sa.Integer(), nullable=True),
        sa.Column("elo_after", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["player_profiles.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["map_id"], ["maps.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_player_matches_map_id"),
        "player_matches",
        ["map_id"],
        unique=False,
    )
    op.create_index(
        "ix_player_matches_profile_played",
        "player_matches",
        ["profile_id", "played_at"],
        unique=False,
    )

    op.create_table(
        "player_map_stats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("map_id", sa.Integer(), nullable=False),
        sa.Column(
            "matches_played",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("wins", sa.Integer(), server_default="0", nullable=False),
        sa.Column("losses", sa.Integer(), server_default="0", nullable=False),
        sa.Column("draws", sa.Integer(), server_default="0", nullable=False),
        sa.Column("kills", sa.Integer(), server_default="0", nullable=False),
        sa.Column("deaths", sa.Integer(), server_default="0", nullable=False),
        sa.Column("assists", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "headshots", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "rounds_played",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "total_damage",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["player_profiles.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["map_id"], ["maps.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "profile_id", "map_id", name="uq_player_map_stats_profile_map"
        ),
    )
    op.create_index(
        op.f("ix_player_map_stats_map_id"),
        "player_map_stats",
        ["map_id"],
        unique=False,
    )

    # Perfiles para usuarios existentes. No se inventa actividad: la fecha de
    # última actividad queda en NULL hasta el próximo login o edición.
    op.execute(
        """
        INSERT INTO player_profiles
            (user_id, nickname, display_name, visibility, created_at, updated_at)
        SELECT id, username, username, 'PRIVATE', created_at, created_at
        FROM users
        """
    )
    op.execute(
        """
        INSERT INTO player_competitive_profiles (profile_id, status, updated_at)
        SELECT id, 'UNRANKED', updated_at
        FROM player_profiles
        """
    )
    op.execute(
        """
        INSERT INTO player_stats (profile_id, updated_at)
        SELECT id, updated_at
        FROM player_profiles
        """
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_player_map_stats_map_id"), table_name="player_map_stats"
    )
    op.drop_table("player_map_stats")

    op.drop_index(
        "ix_player_matches_profile_played", table_name="player_matches"
    )
    op.drop_index(op.f("ix_player_matches_map_id"), table_name="player_matches")
    op.drop_table("player_matches")

    op.drop_table("player_social_links")

    op.drop_index(op.f("ix_player_stats_profile_id"), table_name="player_stats")
    op.drop_table("player_stats")

    op.drop_index(
        op.f("ix_player_competitive_profiles_profile_id"),
        table_name="player_competitive_profiles",
    )
    op.drop_table("player_competitive_profiles")

    op.drop_index(
        op.f("ix_player_profiles_nickname"), table_name="player_profiles"
    )
    op.drop_index(
        op.f("ix_player_profiles_user_id"), table_name="player_profiles"
    )
    op.drop_table("player_profiles")
