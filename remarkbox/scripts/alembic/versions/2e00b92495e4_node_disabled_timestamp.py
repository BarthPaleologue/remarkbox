"""Node disabled_timestamp

Revision ID: 2e00b92495e4
Revises: 7a3a4755b4a8
Create Date: 2017-08-13 15:58:33.169624

"""

# revision identifiers, used by Alembic.
revision = "2e00b92495e4"
down_revision = "7a3a4755b4a8"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa

from remarkbox.models import Node, now_timestamp


def upgrade():
    # add the new column.
    op.add_column(
        "Node", sa.Column("disabled_timestamp", sa.BigInteger(), nullable=True)
    )

    bind = op.get_bind()
    DBSession = sa.orm.Session(bind=bind)

    # get all disabled nodes.
    nodes = DBSession.query(Node).filter(Node.disabled == True)

    for node in nodes:
        node.disabled_timestamp = now_timestamp()
        DBSession.add(node)

    DBSession.flush()
    DBSession.commit()


def downgrade():
    op.drop_column("Node", "disabled_timestamp")
