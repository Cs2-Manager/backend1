"""Preserve archived playbooks after the last member leaves a team."""
from alembic import op
import sqlalchemy as sa
revision = 'f8e500000005'
down_revision = 'f8d400000004'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint('team_strategies_team_id_fkey', 'team_strategies', type_='foreignkey')
    op.alter_column('team_strategies', 'team_id', existing_type=sa.Integer(), nullable=True)
    op.create_foreign_key('team_strategies_team_id_fkey', 'team_strategies', 'teams', ['team_id'], ['id'], ondelete='SET NULL')


def downgrade():
    # Refuse incompatible downgrades instead of deleting historical documents.
    if op.get_bind().execute(sa.text('SELECT count(*) FROM team_strategies WHERE team_id IS NULL')).scalar():
        raise RuntimeError('Archived playbooks without a team must be reassigned before downgrade')
    op.drop_constraint('team_strategies_team_id_fkey', 'team_strategies', type_='foreignkey')
    op.alter_column('team_strategies', 'team_id', existing_type=sa.Integer(), nullable=False)
    op.create_foreign_key('team_strategies_team_id_fkey', 'team_strategies', 'teams', ['team_id'], ['id'], ondelete='CASCADE')
