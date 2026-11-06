"""Persist curated strategy recommendations per lineup."""
from alembic import op
import sqlalchemy as sa
revision = 'f8d400000004'
down_revision = 'f8c300000003'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('lineup_recommendations',
        sa.Column('lineup_id', sa.Integer(), sa.ForeignKey('team_lineups.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('strategy_id', sa.Integer(), sa.ForeignKey('team_strategies.id', ondelete='CASCADE'), primary_key=True))


def downgrade():
    op.drop_table('lineup_recommendations')
