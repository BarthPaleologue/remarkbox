"""Added email_id column to User table.

Revision ID: 6a440d3921d2
Revises: 5a5d0b68db78
Create Date: 2017-05-16 16:22:51.161059

"""

# revision identifiers, used by Alembic.
revision = "6a440d3921d2"
down_revision = "5a5d0b68db78"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa

from remarkbox.models import User
from remarkbox.models import now_timestamp


def upgrade():

    bind = op.get_bind()
    DBSession = sa.orm.Session(bind=bind)

    op.add_column("User", sa.Column("email_id", sa.Unicode))
    op.add_column(
        "User",
        sa.Column(
            "password_timestamp", sa.BigInteger, server_default=str(now_timestamp())
        ),
    )

    users = DBSession.query(User).all()

    for user in users:
        user.email_id = user._generate_raw_password(8)
        DBSession.add(user)

    DBSession.flush()
    DBSession.commit()


def downgrade():
    # this will fail for sqlite3 databases...
    op.drop_column("User", "email_id")
    op.drop_column("User", "password_timestamp")
