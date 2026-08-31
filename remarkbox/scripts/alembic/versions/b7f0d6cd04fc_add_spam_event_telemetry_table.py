"""add spam_event telemetry table

Revision ID: b7f0d6cd04fc
Revises: 8aa65ccc4241
Create Date: 2026-08-31 11:55:35.478808

Autogenerate also emitted unrelated drift against a stale development
database -- dropping rb_root_cache, dropping rb_user.admin, rb_user.stripe_id
and rb_namespace.email_notify, creating rb_payment, and reindexing most of the
schema. All of that was stripped: applying it to production would be
destructive and has nothing to do with this change.

Schema is created through migration_helpers because salt runs
Base.metadata.create_all() immediately before `alembic upgrade head` on every
release. create_all knows nothing about alembic, so a bare CREATE TABLE here
would hit a table that already exists, raise, and abort the whole upgrade --
leaving every later revision silently unapplied.
"""

# revision identifiers, used by Alembic.
revision = 'b7f0d6cd04fc'
down_revision = '8aa65ccc4241'
branch_labels = None
depends_on = None

import sqlalchemy as sa
import sqlalchemy_utils

from remarkbox.lib.migration_helpers import (
    create_table_if_missing,
    create_index_if_missing,
    drop_table_if_present,
    drop_index_if_present,
)


def upgrade():
    create_table_if_missing(
        'rb_spam_event',
        sa.Column('id', sqlalchemy_utils.types.uuid.UUIDType(binary=False),
                  nullable=False),
        sa.Column('created_timestamp', sa.BigInteger(), nullable=False),
        sa.Column('namespace_id',
                  sqlalchemy_utils.types.uuid.UUIDType(binary=False),
                  nullable=True),
        sa.Column('user_id',
                  sqlalchemy_utils.types.uuid.UUIDType(binary=False),
                  nullable=True),
        sa.Column('action', sa.Unicode(length=16), nullable=False),
        sa.Column('source', sa.Unicode(length=16), nullable=False),
        sa.Column('spam_score', sa.Float(), nullable=True),
        sa.Column('signals', sa.Unicode(length=512), nullable=True),
        sa.Column('llm_ran', sa.Boolean(), nullable=False),
        sa.Column('llm_verdict', sa.Boolean(), nullable=True),
        sa.Column('llm_model', sa.Unicode(length=128), nullable=True),
        sa.ForeignKeyConstraint(['namespace_id'], ['rb_namespace.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['rb_user.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    create_index_if_missing(
        'ix_rb_spam_event_id', 'rb_spam_event', ['id'], unique=False)
    create_index_if_missing(
        'ix_rb_spam_event_action', 'rb_spam_event', ['action'], unique=False)
    create_index_if_missing(
        'ix_rb_spam_event_created_timestamp', 'rb_spam_event',
        ['created_timestamp'], unique=False)
    create_index_if_missing(
        'ix_rb_spam_event_namespace_id', 'rb_spam_event',
        ['namespace_id'], unique=False)
    create_index_if_missing(
        'ix_rb_spam_event_user_id', 'rb_spam_event', ['user_id'], unique=False)
    create_index_if_missing(
        'ix_rb_spam_event_namespace_created', 'rb_spam_event',
        ['namespace_id', 'created_timestamp'], unique=False)


def downgrade():
    for index_name in (
        'ix_rb_spam_event_namespace_created',
        'ix_rb_spam_event_user_id',
        'ix_rb_spam_event_namespace_id',
        'ix_rb_spam_event_created_timestamp',
        'ix_rb_spam_event_action',
        'ix_rb_spam_event_id',
    ):
        drop_index_if_present(index_name, 'rb_spam_event')
    drop_table_if_present('rb_spam_event')
