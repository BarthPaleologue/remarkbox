"""add subscription_type to Namespace

Revision ID: 3ee195d142fb
Revises: 771ef7c868de
Create Date: 2019-02-16 14:23:03.175524

"""

# revision identifiers, used by Alembic.
revision = '3ee195d142fb'
down_revision = '771ef7c868de'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column(
        'rb_namespace',
        sa.Column(
            'subscription_type',
            sa.Enum('development', 'trial', 'production', name='subscription_type'),
            nullable=False,
            server_default='development'
        )
    )


def downgrade():
    pass
