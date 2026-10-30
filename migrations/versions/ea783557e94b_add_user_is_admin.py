"""add user is_admin

Revision ID: ea783557e94b
Revises: 1d65f5c82647
Create Date: 2026-10-29 20:11:31.712145

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ea783557e94b'
down_revision: Union[str, None] = '1d65f5c82647'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default permite aplicar la migración sobre filas existentes.
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("users", "is_admin")
