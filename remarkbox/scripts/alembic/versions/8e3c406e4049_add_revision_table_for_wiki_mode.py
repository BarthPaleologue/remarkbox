"""add revision table for wiki mode

Revision ID: 8e3c406e4049
Revises: 7c624a8fae9e
Create Date: 2026-03-09 23:09:54.651756

"""

# revision identifiers, used by Alembic.
revision = '8e3c406e4049'
down_revision = 'd47dc908d2ea'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa

from remarkbox.lib.migration_helpers import (
    create_index_if_missing,
    create_table_if_missing,
    drop_index_if_present,
    drop_table_if_present,
)

from sqlalchemy_utils import UUIDType as TempUUIDType
UUIDType = TempUUIDType(binary=False)


def upgrade():
    # Guarded: our deploy runs create_all() first, which builds this table
    # from our models before alembic gets here. Creating it unguarded aborted
    # the whole upgrade and stranded every later revision. See T22.
    create_table_if_missing('rb_revision',
        sa.Column('id', UUIDType, nullable=False),
        sa.Column('node_id', UUIDType, nullable=False),
        sa.Column('user_id', UUIDType, nullable=True),
        sa.Column('data', sa.UnicodeText(), nullable=False),
        sa.Column('source_format', sa.Unicode(length=16), nullable=False),
        sa.Column('revision_number', sa.Integer(), nullable=False),
        sa.Column('created', sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(['node_id'], ['rb_node.id']),
        sa.ForeignKeyConstraint(['user_id'], ['rb_user.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    create_index_if_missing(op.f('ix_rb_revision_id'), 'rb_revision', ['id'], unique=False)
    create_index_if_missing(op.f('ix_rb_revision_node_id'), 'rb_revision', ['node_id'], unique=False)


def downgrade():
    drop_index_if_present(op.f('ix_rb_revision_node_id'), 'rb_revision')
    drop_index_if_present(op.f('ix_rb_revision_id'), 'rb_revision')
    drop_table_if_present('rb_revision')
