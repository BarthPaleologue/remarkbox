"""add api token table for bearer authentication

Revision ID: df0217588814
Revises: 554e2329ebf0
Create Date: 2026-07-27 20:08:52.532345

Bearer tokens give our API an authentication path that is not ambient, so an
API write cannot be forged by a page our user happens to be visiting.

Only the SHA-256 of a token is stored: a token carries 256 bits of entropy,
so there is nothing to brute force, and a database read recovers no working
credential.
"""

# revision identifiers, used by Alembic.
revision = 'df0217588814'
down_revision = '554e2329ebf0'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
import sqlalchemy_utils


def upgrade():
    op.create_table(
        'rb_api_token',
        sa.Column('id', sqlalchemy_utils.types.uuid.UUIDType(binary=False), nullable=False),
        sa.Column('user_id', sqlalchemy_utils.types.uuid.UUIDType(binary=False), nullable=False),
        sa.Column('name', sa.Unicode(length=64), nullable=True),
        sa.Column('token_hash', sa.Unicode(length=64), nullable=False),
        sa.Column('created_timestamp', sa.BigInteger(), nullable=False),
        sa.Column('last_used_timestamp', sa.BigInteger(), nullable=True),
        sa.Column('revoked', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['rb_user.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_rb_api_token_id'), 'rb_api_token', ['id'], unique=False)
    op.create_index('ix_rb_api_token_lookup', 'rb_api_token', ['token_hash', 'revoked'], unique=False)
    op.create_index(op.f('ix_rb_api_token_token_hash'), 'rb_api_token', ['token_hash'], unique=True)
    op.create_index(op.f('ix_rb_api_token_user_id'), 'rb_api_token', ['user_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_rb_api_token_user_id'), table_name='rb_api_token')
    op.drop_index(op.f('ix_rb_api_token_token_hash'), table_name='rb_api_token')
    op.drop_index('ix_rb_api_token_lookup', table_name='rb_api_token')
    op.drop_index(op.f('ix_rb_api_token_id'), table_name='rb_api_token')
    op.drop_table('rb_api_token')
