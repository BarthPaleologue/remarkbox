"""create rb_sudo_otp table

Revision ID: 7c624a8fae9e
Revises: e99b1524710c
Create Date: 2026-02-05 16:06:35.820072

"""

# revision identifiers, used by Alembic.
revision = '7c624a8fae9e'
down_revision = 'e99b1524710c'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table('rb_sudo_otp',
        sa.Column('action_key', sa.Unicode(length=256), nullable=False),
        sa.Column('code', sa.Unicode(length=8), nullable=False),
        sa.Column('action', sa.Unicode(length=512), nullable=False),
        sa.Column('client_ip', sa.Unicode(length=45), nullable=True),
        sa.Column('created_at', sa.BigInteger(), nullable=False),
        sa.Column('expires_at', sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint('action_key'),
    )


def downgrade():
    op.drop_table('rb_sudo_otp')
