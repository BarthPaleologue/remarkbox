"""add is_superuser column to user

Revision ID: 03061161fc3d
Revises: b7f3a2d1e8c9
Create Date: 2026-02-02 08:01:12.446084

"""

# revision identifiers, used by Alembic.
revision = '03061161fc3d'
down_revision = 'b7f3a2d1e8c9'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('rb_user', sa.Column('is_superuser', sa.Boolean(), nullable=True))


def downgrade():
    op.drop_column('rb_user', 'is_superuser')
