"""create graph_depth column on node model.

Revision ID: 76deff88cfd6
Revises: d1a0ab4f617f
Create Date: 2020-02-23 20:51:49.889183

"""

# revision identifiers, used by Alembic.
revision = '76deff88cfd6'
down_revision = 'd1a0ab4f617f'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.add_column(
        'rb_node',
        sa.Column(
            'graph_depth',
            sa.Integer(),
            nullable=False,
            server_default="-1",
        )
    )

def downgrade():
    op.drop_column('rb_node', 'graph_depth')
