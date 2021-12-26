from sqlalchemy import Integer, BigInteger, Column

import uuid

from remarkbox.lib import timestamp_to_ago_string, timestamp_to_date_string

from .meta import Base, RBase
from .meta import now_timestamp, foreign_key
from .meta import UUIDType


class Vote(RBase, Base):
    id = Column(UUIDType, primary_key=True, index=True)
    user_id = Column(UUIDType, foreign_key("User", "id"))
    node_id = Column(UUIDType, foreign_key("Node", "id"))
    created = Column(BigInteger, nullable=False)
    value = Column(Integer, nullable=False)

    def __init__(self):
        self.id = uuid.uuid1()
        self.created = now_timestamp()

    @property
    def human_timestamp(self):
        return timestamp_to_ago_string(self.created)

    # TODO: take into account user's timezone?
    @property
    def created_date(self):
        return timestamp_to_date_string(self.created)
