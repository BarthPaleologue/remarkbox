"""pay what you can table

Revision ID: b132ec968f0c
Revises: 184a349cd589
Create Date: 2021-01-31 09:47:47.220938

"""

# revision identifiers, used by Alembic.
revision = 'b132ec968f0c'
down_revision = '184a349cd589'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa

from sqlalchemy_utils import UUIDType as TempUUIDType
UUIDType = TempUUIDType(binary=False)


def upgrade():
    op.create_table('rb_pay_what_you_can',
        sa.Column('user_id', UUIDType, nullable=False),
        sa.Column('frequency', sa.Enum('once', 'yearly', name='frequency'), nullable=False),
        sa.Column('amount', sa.BigInteger(), nullable=False),
        sa.Column('contributions', sa.BigInteger(), nullable=False),
        sa.Column('created_timestamp', sa.BigInteger(), nullable=False),
        sa.Column('updated_timestamp', sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['rb_user.id'], ),
        sa.PrimaryKeyConstraint('user_id')
    )
    op.create_index(op.f('ix_rb_pay_what_you_can_user_id'), 'rb_pay_what_you_can', ['user_id'], unique=False)
