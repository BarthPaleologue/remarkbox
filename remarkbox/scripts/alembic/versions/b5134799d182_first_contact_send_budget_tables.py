"""first-contact send budget tables

Revision ID: b5134799d182
Revises: b7f0d6cd04fc
Create Date: 2026-09-24 16:51:55.254034

rb_send_ledger counts first-contact sends & first verifications;
rb_send_queue holds first-contact emails waiting for budget
(lib/send_budget.py). Autogenerate drift against the development database
was stripped. Tables go through migration_helpers because salt runs
Base.metadata.create_all() before `alembic upgrade head` on every release.
"""

# revision identifiers, used by Alembic.
revision = 'b5134799d182'
down_revision = 'b7f0d6cd04fc'
branch_labels = None
depends_on = None

import sqlalchemy as sa
import sqlalchemy_utils

from remarkbox.lib.migration_helpers import (
    create_table_if_missing,
    create_index_if_missing,
    drop_table_if_present,
)

UUID = sqlalchemy_utils.types.uuid.UUIDType(binary=False)


def upgrade():
    create_table_if_missing(
        'rb_send_ledger',
        sa.Column('id', UUID, nullable=False),
        sa.Column('created_timestamp', sa.BigInteger(), nullable=False),
        sa.Column('kind', sa.Unicode(length=16), nullable=False),
        sa.Column('purpose', sa.Unicode(length=32), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    create_index_if_missing('ix_rb_send_ledger_created_timestamp', 'rb_send_ledger', ['created_timestamp'])
    create_index_if_missing('ix_rb_send_ledger_id', 'rb_send_ledger', ['id'])
    create_index_if_missing('ix_rb_send_ledger_kind', 'rb_send_ledger', ['kind'])
    create_table_if_missing(
        'rb_send_queue',
        sa.Column('id', UUID, nullable=False),
        sa.Column('created_timestamp', sa.BigInteger(), nullable=False),
        sa.Column('expires_timestamp', sa.BigInteger(), nullable=False),
        sa.Column('email', sa.Unicode(length=256), nullable=False),
        sa.Column('purpose', sa.Unicode(length=32), nullable=False),
        sa.Column('priority', sa.SmallInteger(), nullable=False, server_default='0'),
        sa.Column('domain', sa.Unicode(length=256), nullable=False),
        sa.Column('from_name', sa.Unicode(length=256), nullable=False, server_default=''),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email', 'purpose'),
    )
    create_index_if_missing('ix_rb_send_queue_created_timestamp', 'rb_send_queue', ['created_timestamp'])
    create_index_if_missing('ix_rb_send_queue_expires_timestamp', 'rb_send_queue', ['expires_timestamp'])
    create_index_if_missing('ix_rb_send_queue_id', 'rb_send_queue', ['id'])


def downgrade():
    drop_table_if_present('rb_send_queue')
    drop_table_if_present('rb_send_ledger')
