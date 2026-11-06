"""Add map library metadata without changing existing tactical images."""

from alembic import op
import sqlalchemy as sa

revision = "f8a100000001"
down_revision = "c4f2a8d6e1b9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("maps", sa.Column("cover_url", sa.String(500), nullable=True))
    op.add_column("maps", sa.Column("description", sa.Text(), nullable=False, server_default=""))


def downgrade():
    op.drop_column("maps", "description")
    op.drop_column("maps", "cover_url")
