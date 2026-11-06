"""Map rosters, audit history, strategies and preparation."""
from alembic import op
import sqlalchemy as sa

revision = 'f8b200000002'
down_revision = 'f8a100000001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('team_lineups', sa.Column('map_id', sa.Integer(), sa.ForeignKey('maps.id', ondelete='SET NULL'), nullable=True))
    op.add_column('team_lineups', sa.Column('notes', sa.Text(), nullable=False, server_default=''))
    op.create_index('ix_team_lineups_map_id', 'team_lineups', ['map_id'])
    op.create_table('team_lineup_history',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('team_id', sa.Integer(), sa.ForeignKey('teams.id', ondelete='SET NULL')),
        sa.Column('lineup_id', sa.Integer(), nullable=False),
        sa.Column('actor_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('action', sa.String(40), nullable=False),
        sa.Column('before', sa.JSON()), sa.Column('after', sa.JSON()),
        sa.Column('created_at', sa.DateTime(), nullable=False))
    for field in ('team_id', 'lineup_id'):
        op.create_index('ix_team_lineup_history_' + field, 'team_lineup_history', [field])
    op.create_table('team_strategies',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('team_id', sa.Integer(), sa.ForeignKey('teams.id', ondelete='CASCADE'), nullable=False),
        sa.Column('map_id', sa.Integer(), sa.ForeignKey('maps.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('lineup_id', sa.Integer(), sa.ForeignKey('team_lineups.id', ondelete='SET NULL')),
        sa.Column('author_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('name', sa.String(160), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('side', sa.String(2), nullable=False),
        sa.Column('category', sa.String(30), nullable=False),
        sa.Column('status', sa.String(12), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('document', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("status IN ('DRAFT','PUBLISHED','ARCHIVED')", name='ck_strategy_status'))
    for field in ('team_id', 'map_id'):
        op.create_index('ix_team_strategies_' + field, 'team_strategies', [field])
    op.create_table('strategy_revisions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('strategy_id', sa.Integer(), sa.ForeignKey('team_strategies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('author_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('snapshot', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('strategy_id', 'version', name='uq_strategy_revision'))
    op.create_index('ix_strategy_revisions_strategy_id', 'strategy_revisions', ['strategy_id'])
    op.create_table('team_map_setups',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('team_id', sa.Integer(), sa.ForeignKey('teams.id', ondelete='CASCADE'), nullable=False),
        sa.Column('map_id', sa.Integer(), sa.ForeignKey('maps.id', ondelete='CASCADE'), nullable=False),
        sa.Column('lineup_id', sa.Integer(), sa.ForeignKey('team_lineups.id', ondelete='SET NULL')),
        sa.Column('notes', sa.Text(), nullable=False),
        sa.Column('readiness', sa.String(20), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.UniqueConstraint('team_id', 'map_id', name='uq_team_map_setup'))
    op.create_index('ix_team_map_setups_team_id', 'team_map_setups', ['team_id'])


def downgrade():
    for table in ('team_map_setups', 'strategy_revisions', 'team_strategies', 'team_lineup_history'):
        op.drop_table(table)
    op.drop_index('ix_team_lineups_map_id', table_name='team_lineups')
    op.drop_column('team_lineups', 'notes')
    op.drop_column('team_lineups', 'map_id')
