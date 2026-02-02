"""add push notification columns to user and webmention table

Revision ID: b7f3a2d1e8c9
Revises: 896568b0752e
Create Date: 2026-02-01 21:00:00.000000

"""

# revision identifiers, used by Alembic.
revision = 'b7f3a2d1e8c9'
down_revision = '896568b0752e'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa

from remarkbox.models.meta import UUIDType


def upgrade():
    # T10: push notification preferences on user
    op.add_column('rb_user', sa.Column('notification_preference', sa.Unicode(length=5), server_default='email', nullable=False))
    op.add_column('rb_user', sa.Column('push_subscriptions', sa.UnicodeText(), nullable=True))

    # T7: webmention table
    op.create_table(
        'rb_webmention',
        sa.Column('id', UUIDType, primary_key=True, index=True),
        sa.Column('source', sa.Unicode(2048), nullable=False),
        sa.Column('target', sa.Unicode(2048), nullable=False),
        sa.Column('node_id', UUIDType, sa.ForeignKey('rb_node.id'), index=True, nullable=True),
        sa.Column('verified', sa.Boolean(), default=False, nullable=False),
        sa.Column('author_name', sa.Unicode(256), nullable=True),
        sa.Column('author_url', sa.Unicode(2048), nullable=True),
        sa.Column('content', sa.UnicodeText(), nullable=True),
        sa.Column('created_timestamp', sa.BigInteger(), nullable=False),
        sa.Column('updated_timestamp', sa.BigInteger(), nullable=False),
    )


def downgrade():
    op.drop_table('rb_webmention')
    op.drop_column('rb_user', 'push_subscriptions')
    op.drop_column('rb_user', 'notification_preference')
