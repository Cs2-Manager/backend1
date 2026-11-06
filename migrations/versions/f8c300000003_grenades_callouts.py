"""Extend existing grenade and callout catalogs."""
from alembic import op
import sqlalchemy as sa
revision = 'f8c300000003'
down_revision = 'f8b200000002'
branch_labels = None
depends_on = None


def upgrade():
    for name, target, deletion in [('team_id', 'teams.id', 'CASCADE'), ('author_id', 'users.id', 'SET NULL'), ('responsible_id', 'users.id', 'SET NULL')]:
        op.add_column('lineups', sa.Column(name, sa.Integer(), sa.ForeignKey(target, ondelete=deletion)))
    op.create_index('ix_lineups_team_id', 'lineups', ['team_id'])
    for name, size, default in [('visibility', 10, 'PUBLIC'), ('difficulty', 10, 'MEDIUM'), ('status', 12, 'PUBLISHED'), ('launch_zone', 120, ''), ('impact_zone', 120, '')]:
        op.add_column('lineups', sa.Column(name, sa.String(size), nullable=False, server_default=default))
    op.add_column('lineups', sa.Column('image_url', sa.String(500)))
    op.add_column('lineups', sa.Column('position', sa.JSON()))
    op.create_table('grenade_favorites',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('lineup_id', sa.Integer(), sa.ForeignKey('lineups.id', ondelete='CASCADE'), primary_key=True))
    op.add_column('callouts', sa.Column('zone', sa.String(120), nullable=False, server_default=''))
    op.add_column('callouts', sa.Column('description', sa.Text(), nullable=False, server_default=''))
    op.add_column('callouts', sa.Column('image_url', sa.String(500)))
    op.add_column('callouts', sa.Column('status', sa.String(12), nullable=False, server_default='PUBLISHED'))
    op.add_column('callouts', sa.Column('author_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')))


def downgrade():
    for name in ('author_id', 'status', 'image_url', 'description', 'zone'):
        op.drop_column('callouts', name)
    op.drop_table('grenade_favorites')
    op.drop_index('ix_lineups_team_id', table_name='lineups')
    for name in ('position', 'image_url', 'impact_zone', 'launch_zone', 'status', 'difficulty', 'visibility', 'responsible_id', 'author_id', 'team_id'):
        op.drop_column('lineups', name)
