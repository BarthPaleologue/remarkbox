"""loop over root nodes and create namespace

Revision ID: 256468780798
Revises: 98a90d2add21
Create Date: 2017-07-03 16:37:07.937232

"""

# revision identifiers, used by Alembic.
revision = "256468780798"
down_revision = "98a90d2add21"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa

from sqlalchemy.orm.exc import NoResultFound

from remarkbox.models import Node, Namespace


def upgrade():

    bind = op.get_bind()
    DBSession = sa.orm.Session(bind=bind)

    def get_or_create_namespace(name):
        try:
            return DBSession.query(Namespace).filter(Namespace.name == name).one()
        except NoResultFound:
            namespace = Namespace(name)
            DBSession.add(namespace)
            DBSession.flush()
            DBSession.commit()
            return namespace

    root_nodes = DBSession.query(Node).filter(Node.parent_id == None)

    for root_node in root_nodes:

        if root_node.uri:
            namespace = get_or_create_namespace(root_node.uri.parsed.hostname)
        else:
            namespace = get_or_create_namespace("temp.namespace.com")

        root_node.namespace_id = namespace.id

        DBSession.add(root_node)
        DBSession.flush()
        DBSession.commit()


def downgrade():
    pass
