"""node data html column

Revision ID: 591800942adf
Revises: c97ddfcbc406
Create Date: 2017-09-01 21:42:39.429275

"""

# revision identifiers, used by Alembic.
revision = "591800942adf"
down_revision = "c97ddfcbc406"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa

from remarkbox.models import Node

from remarkbox.lib.render import markdown_to_html


def upgrade():

    bind = op.get_bind()
    DBSession = sa.orm.Session(bind=bind)

    op.add_column("Node", sa.Column("data_html", sa.UnicodeText(), nullable=True))

    nodes = DBSession.query(Node).all()

    for node in nodes:
        if node.data:
            node.data_html = markdown_to_html(node.data, node.root.namespace)
            DBSession.add(node)

    DBSession.flush()
    DBSession.commit()


def downgrade():
    op.drop_column("Node", "data_html")
