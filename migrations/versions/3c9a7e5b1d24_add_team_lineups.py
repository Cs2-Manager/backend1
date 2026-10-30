"""add team lineups

Revision ID: 3c9a7e5b1d24
Revises: 2d236ff229a2
Create Date: 2026-10-29 23:05:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "3c9a7e5b1d24"
down_revision: Union[str, None] = "2d236ff229a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "team_lineups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=10),
            server_default="DRAFT",
            nullable=False,
        ),
        sa.Column(
            "is_primary",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE')",
            name="ck_team_lineups_status",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_team_lineups_status"),
        "team_lineups",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_team_lineups_team_id"),
        "team_lineups",
        ["team_id"],
        unique=False,
    )
    op.create_index(
        "uq_team_lineups_one_primary",
        "team_lineups",
        ["team_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
        sqlite_where=sa.text("is_primary"),
    )

    op.create_table(
        "team_lineup_players",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lineup_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=True),
        sa.Column(
            "is_starter",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "role IS NULL OR role IN "
            "('IGL', 'AWPER', 'ENTRY', 'SUPPORT', 'LURKER', 'ANCHOR', "
            "'RIFLER', 'FLEX')",
            name="ck_team_lineup_players_role",
        ),
        sa.ForeignKeyConstraint(
            ["lineup_id"], ["team_lineups.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "lineup_id",
            "user_id",
            name="uq_team_lineup_players_lineup_user",
        ),
    )
    op.create_index(
        op.f("ix_team_lineup_players_lineup_id"),
        "team_lineup_players",
        ["lineup_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_team_lineup_players_user_id"),
        "team_lineup_players",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_team_lineup_players_user_id"),
        table_name="team_lineup_players",
    )
    op.drop_index(
        op.f("ix_team_lineup_players_lineup_id"),
        table_name="team_lineup_players",
    )
    op.drop_table("team_lineup_players")
    op.drop_index(
        "uq_team_lineups_one_primary",
        table_name="team_lineups",
        postgresql_where=sa.text("is_primary"),
        sqlite_where=sa.text("is_primary"),
    )
    op.drop_index(
        op.f("ix_team_lineups_team_id"), table_name="team_lineups"
    )
    op.drop_index(
        op.f("ix_team_lineups_status"), table_name="team_lineups"
    )
    op.drop_table("team_lineups")
