"""add root_id field

Revision ID: 5a5d0b68db78
Revises: 6bbc92ccc112
Create Date: 2017-01-14 20:59:39.701946

"""

# revision identifiers, used by Alembic.
revision = "5a5d0b68db78"
down_revision = "6bbc92ccc112"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa

from remarkbox.models import Node


def upgrade():

    bind = op.get_bind()
    DBSession = sa.orm.Session(bind=bind)

    op.add_column("Node", sa.Column("root_id", sa.Integer, default=None))

    nodes = DBSession.query(Node).all()

    for node in nodes:
        node.root_id = node.root.id
        DBSession.add(node)

    DBSession.flush()
    DBSession.commit()


def downgrade():
    # this will fail for sqlite3 databases...
    op.drop_column("Node", "root_id")
