"""namespace model

Revision ID: 98a90d2add21
Revises: 04e52337756e
Create Date: 2017-07-03 16:13:09.160494

"""

# revision identifiers, used by Alembic.
revision = "98a90d2add21"
down_revision = "04e52337756e"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa

from remarkbox.models import UUIDType


def upgrade():
    # we don't need to create the table.
    # it will be created automatically during release.
    # We do need to create the namespace_id column on the node table.
    op.add_column(u"Node", sa.Column("namespace_id", UUIDType, nullable=True))

    # this fails so I had to comment it out.
    # op.create_foreign_key(None, 'Node', 'Namespace', ['namespace_id'], ['id'])


def downgrade():
    op.drop_constraint(None, "Node", type_="foreignkey")
    op.drop_column(u"Node", "namespace_id")
    op.drop_index(op.f("ix_Namespace_name"), table_name="Namespace")
    op.drop_index(op.f("ix_Namespace_id"), table_name="Namespace")
    op.drop_table("Namespace")
