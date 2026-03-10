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

from sqlalchemy_utils import UUIDType as TempUUIDType
UUIDType = TempUUIDType(binary=False)


def upgrade():
    op.create_table('rb_revision',
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
    op.create_index(op.f('ix_rb_revision_id'), 'rb_revision', ['id'], unique=False)
    op.create_index(op.f('ix_rb_revision_node_id'), 'rb_revision', ['node_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_rb_revision_node_id'), table_name='rb_revision')
    op.drop_index(op.f('ix_rb_revision_id'), table_name='rb_revision')
    op.drop_table('rb_revision')
