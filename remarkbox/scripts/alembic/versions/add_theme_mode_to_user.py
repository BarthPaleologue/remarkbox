"""add theme_mode column to rb_user

Revision ID: b8f3c9d4e5a1
Revises: 14a6a35940c7
Create Date: 2025-10-11 00:00:00.000000

"""

# revision identifiers, used by Alembic.
revision = 'b8f3c9d4e5a1'
down_revision = '14a6a35940c7'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column(
        'rb_user',
        sa.Column(
            'theme_mode',
            sa.Enum('auto', 'light', 'dark', name='theme_mode_enum'),
            nullable=False,
            server_default='auto',
        ),
    )


def downgrade():
    op.drop_column('rb_user', 'theme_mode')
    # Also drop the enum type
    op.execute('DROP TYPE theme_mode_enum')
