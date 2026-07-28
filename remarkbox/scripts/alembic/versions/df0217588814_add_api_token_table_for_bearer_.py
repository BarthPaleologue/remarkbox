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

from remarkbox.lib.migration_helpers import (
    create_index_if_missing,
    create_table_if_missing,
    drop_index_if_present,
    drop_table_if_present,
)


def upgrade():
    # Guarded: our deploy runs create_all() first, which builds this table
    # from our models before alembic gets here. See T22.
    create_table_if_missing(
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
    create_index_if_missing(op.f('ix_rb_api_token_id'), 'rb_api_token', ['id'], unique=False)
    create_index_if_missing('ix_rb_api_token_lookup', 'rb_api_token', ['token_hash', 'revoked'], unique=False)
    create_index_if_missing(op.f('ix_rb_api_token_token_hash'), 'rb_api_token', ['token_hash'], unique=True)
    create_index_if_missing(op.f('ix_rb_api_token_user_id'), 'rb_api_token', ['user_id'], unique=False)


def downgrade():
    drop_index_if_present(op.f('ix_rb_api_token_user_id'), 'rb_api_token')
    drop_index_if_present(op.f('ix_rb_api_token_token_hash'), 'rb_api_token')
    drop_index_if_present('ix_rb_api_token_lookup', 'rb_api_token')
    drop_index_if_present(op.f('ix_rb_api_token_id'), 'rb_api_token')
    drop_table_if_present('rb_api_token')
