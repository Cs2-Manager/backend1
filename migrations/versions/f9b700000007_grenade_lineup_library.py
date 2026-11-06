"""Biblioteca avanzada de mapas y lineups de granadas.

Migración aditiva y reversible. No elimina ni renombra datos existentes:
- Amplía `maps` con metadatos de catálogo.
- Amplía `lineups` con scope, posiciones normalizadas, instrucciones y
  versionado.
- Crea medios, revisiones y propuestas de equipo.
- Hace opcional `lineups.video_url` (el editor visual no exige video).

La columna `visibility` se conserva y se sincroniza con `scope` para no romper
el código y los datos anteriores.
"""

import re

import sqlalchemy as sa
from alembic import op

revision = "f9b700000007"
down_revision = "f9a600000006"
branch_labels = None
depends_on = None

NOW = sa.text("CURRENT_TIMESTAMP")


def _slugify(value):
    normalized = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower())
    return normalized.strip("-") or "map"


def _backfill_slugs():
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, name FROM maps ORDER BY id")).fetchall()
    seen = set()
    for map_id, name in rows:
        base = _slugify(name)
        slug = base
        if slug in seen:
            slug = f"{base}-{map_id}"
        seen.add(slug)
        connection.execute(
            sa.text("UPDATE maps SET slug = :slug WHERE id = :id"),
            {"slug": slug, "id": map_id},
        )


def upgrade():
    # --- Catálogo de mapas -------------------------------------------------
    with op.batch_alter_table("maps") as batch:
        batch.add_column(sa.Column("slug", sa.String(length=80), nullable=True))
        batch.add_column(
            sa.Column(
                "category",
                sa.String(length=20),
                nullable=False,
                server_default="COMPETITIVE",
            )
        )
        batch.add_column(
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default="ACTIVE",
            )
        )
        batch.add_column(sa.Column("image_source", sa.String(length=300), nullable=True))
        batch.add_column(
            sa.Column("top_down_source", sa.String(length=300), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "visual_version", sa.Integer(), nullable=False, server_default="1"
            )
        )
        batch.add_column(
            sa.Column(
                "display_order", sa.Integer(), nullable=False, server_default="0"
            )
        )
        batch.add_column(sa.Column("release_date", sa.Date(), nullable=True))
        batch.add_column(
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW)
        )
        batch.add_column(
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=NOW)
        )

    _backfill_slugs()
    op.create_index("ix_maps_slug", "maps", ["slug"], unique=True)
    op.create_index("ix_maps_category", "maps", ["category"])
    op.create_index("ix_maps_status", "maps", ["status"])

    # --- Lineups -----------------------------------------------------------
    with op.batch_alter_table("lineups") as batch:
        batch.alter_column("video_url", existing_type=sa.String(length=500), nullable=True)
        batch.add_column(
            sa.Column(
                "scope",
                sa.String(length=12),
                nullable=False,
                server_default="PERSONAL",
            )
        )
        batch.add_column(sa.Column("launch_position", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("impact_position", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("launch_callout_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("impact_callout_id", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column(
                "throw_type", sa.String(length=30), nullable=False, server_default=""
            )
        )
        batch.add_column(
            sa.Column("instructions", sa.Text(), nullable=False, server_default="")
        )
        batch.add_column(
            sa.Column("notes", sa.Text(), nullable=False, server_default="")
        )
        batch.add_column(sa.Column("tags", sa.JSON(), nullable=True))
        batch.add_column(
            sa.Column(
                "game_version", sa.String(length=40), nullable=False, server_default=""
            )
        )
        batch.add_column(
            sa.Column("version", sa.Integer(), nullable=False, server_default="1")
        )
        batch.add_column(sa.Column("source_lineup_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("source_proposal_id", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW)
        )
        batch.add_column(
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=NOW)
        )
        batch.create_foreign_key(
            "fk_lineups_launch_callout",
            "callouts",
            ["launch_callout_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_lineups_impact_callout",
            "callouts",
            ["impact_callout_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # Backfill de scope a partir de los datos históricos.
    connection = op.get_bind()
    connection.execute(
        sa.text("UPDATE lineups SET scope = 'TEAM' WHERE team_id IS NOT NULL")
    )
    connection.execute(
        sa.text(
            "UPDATE lineups SET scope = 'OFFICIAL' "
            "WHERE team_id IS NULL AND visibility = 'PUBLIC'"
        )
    )

    op.create_index("ix_lineups_scope", "lineups", ["scope"])
    op.create_index("ix_lineups_source_lineup_id", "lineups", ["source_lineup_id"])
    op.create_index("ix_lineups_source_proposal_id", "lineups", ["source_proposal_id"])

    # --- Medios ------------------------------------------------------------
    op.create_table(
        "grenade_lineup_media",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "lineup_id",
            sa.Integer(),
            sa.ForeignKey("lineups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "kind", sa.String(length=10), nullable=False, server_default="IMAGE"
        ),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("thumbnail_url", sa.String(length=500), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW),
    )
    op.create_index(
        "ix_grenade_lineup_media_lineup_id", "grenade_lineup_media", ["lineup_id"]
    )

    # --- Revisiones --------------------------------------------------------
    op.create_table(
        "grenade_lineup_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "lineup_id",
            sa.Integer(),
            sa.ForeignKey("lineups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "actor_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "action", sa.String(length=30), nullable=False, server_default="UPDATE"
        ),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW),
        sa.UniqueConstraint(
            "lineup_id", "version", name="uq_grenade_lineup_revision"
        ),
    )
    op.create_index(
        "ix_grenade_lineup_revisions_lineup_id",
        "grenade_lineup_revisions",
        ["lineup_id"],
    )

    # --- Propuestas --------------------------------------------------------
    op.create_table(
        "team_grenade_lineup_proposals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "team_id",
            sa.Integer(),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "map_id",
            sa.Integer(),
            sa.ForeignKey("maps.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "source_lineup_id",
            sa.Integer(),
            sa.ForeignKey("lineups.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "author_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "decided_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "approved_lineup_id",
            sa.Integer(),
            sa.ForeignKey("lineups.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "status", sa.String(length=12), nullable=False, server_default="PENDING"
        ),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("rejection_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=NOW),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('PENDING','APPROVED','REJECTED','CANCELLED')",
            name="ck_team_grenade_proposal_status",
        ),
    )
    op.create_index(
        "ix_team_grenade_lineup_proposals_team_id",
        "team_grenade_lineup_proposals",
        ["team_id"],
    )
    op.create_index(
        "ix_team_grenade_lineup_proposals_map_id",
        "team_grenade_lineup_proposals",
        ["map_id"],
    )
    op.create_index(
        "ix_team_grenade_lineup_proposals_source_lineup_id",
        "team_grenade_lineup_proposals",
        ["source_lineup_id"],
    )
    op.create_index(
        "ix_team_grenade_lineup_proposals_approved_lineup_id",
        "team_grenade_lineup_proposals",
        ["approved_lineup_id"],
    )
    op.create_index(
        "ix_team_grenade_lineup_proposals_status",
        "team_grenade_lineup_proposals",
        ["status"],
    )


def downgrade():
    op.drop_index(
        "ix_team_grenade_lineup_proposals_status",
        table_name="team_grenade_lineup_proposals",
    )
    op.drop_index(
        "ix_team_grenade_lineup_proposals_approved_lineup_id",
        table_name="team_grenade_lineup_proposals",
    )
    op.drop_index(
        "ix_team_grenade_lineup_proposals_source_lineup_id",
        table_name="team_grenade_lineup_proposals",
    )
    op.drop_index(
        "ix_team_grenade_lineup_proposals_map_id",
        table_name="team_grenade_lineup_proposals",
    )
    op.drop_index(
        "ix_team_grenade_lineup_proposals_team_id",
        table_name="team_grenade_lineup_proposals",
    )
    op.drop_table("team_grenade_lineup_proposals")

    op.drop_index(
        "ix_grenade_lineup_revisions_lineup_id",
        table_name="grenade_lineup_revisions",
    )
    op.drop_table("grenade_lineup_revisions")

    op.drop_index(
        "ix_grenade_lineup_media_lineup_id", table_name="grenade_lineup_media"
    )
    op.drop_table("grenade_lineup_media")

    op.drop_index("ix_lineups_source_proposal_id", table_name="lineups")
    op.drop_index("ix_lineups_source_lineup_id", table_name="lineups")
    op.drop_index("ix_lineups_scope", table_name="lineups")

    # La versión histórica exigía video_url; se normaliza antes de restaurar
    # la restricción para que el downgrade sea posible con datos nuevos.
    op.get_bind().execute(
        sa.text("UPDATE lineups SET video_url = '' WHERE video_url IS NULL")
    )
    with op.batch_alter_table("lineups") as batch:
        batch.drop_constraint("fk_lineups_launch_callout", type_="foreignkey")
        batch.drop_constraint("fk_lineups_impact_callout", type_="foreignkey")
        for column in (
            "updated_at",
            "created_at",
            "source_proposal_id",
            "source_lineup_id",
            "version",
            "game_version",
            "tags",
            "notes",
            "instructions",
            "throw_type",
            "impact_callout_id",
            "launch_callout_id",
            "impact_position",
            "launch_position",
            "scope",
        ):
            batch.drop_column(column)
        batch.alter_column(
            "video_url", existing_type=sa.String(length=500), nullable=False
        )

    op.drop_index("ix_maps_status", table_name="maps")
    op.drop_index("ix_maps_category", table_name="maps")
    op.drop_index("ix_maps_slug", table_name="maps")
    with op.batch_alter_table("maps") as batch:
        for column in (
            "updated_at",
            "created_at",
            "release_date",
            "display_order",
            "visual_version",
            "top_down_source",
            "image_source",
            "status",
            "category",
            "slug",
        ):
            batch.drop_column(column)
