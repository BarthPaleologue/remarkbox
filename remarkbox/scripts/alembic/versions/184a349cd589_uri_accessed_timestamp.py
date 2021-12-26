"""uri-accessed-timestamp

Revision ID: 184a349cd589
Revises: a38c12eeff2d
Create Date: 2020-04-20 22:13:20.339912

"""

# revision identifiers, used by Alembic.
revision = '184a349cd589'
down_revision = 'a38c12eeff2d'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column('rb_uri', sa.Column('accessed_timestamp', sa.BigInteger(), nullable=False, server_default="0"))
    op.create_index(op.f('ix_rb_uri_accessed_timestamp'), 'rb_uri', ['accessed_timestamp'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_rb_uri_accessed_timestamp'), table_name='rb_uri')
    op.drop_column('rb_uri', 'accessed_timestamp')
