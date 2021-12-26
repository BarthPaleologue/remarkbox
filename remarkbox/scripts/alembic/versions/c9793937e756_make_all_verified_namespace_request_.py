"""add root_id field

Revision ID: c9793937e756
Revises: 051f8b810f26
Create Date: 2017-01-14 20:59:39.701946

"""

# revision identifiers, used by Alembic.
revision = "c9793937e756"
down_revision = "051f8b810f26"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa

from remarkbox.models import NamespaceRequest


def upgrade():

    bind = op.get_bind()
    DBSession = sa.orm.Session(bind=bind)
    namespace_requests = DBSession.query(NamespaceRequest).all()

    for namespace_request in namespace_requests:
        if namespace_request.verified:
            namespace = namespace_request.namespace
            namespace.set_role_for_user(namespace_request.user, "owner")
            DBSession.add(namespace)

    DBSession.flush()
    DBSession.commit()


def downgrade():
    pass
