from .meta import NODE_EVENT_ACTIONS
from .meta import Base, RBase, UUIDType, foreign_key, get_object_by_id, now_timestamp

from sqlalchemy import Column, BigInteger, Unicode, UnicodeText, Enum

from sqlalchemy.orm import relationship, backref

import uuid


class NodeEvent(RBase, Base):
    id = Column(UUIDType, primary_key=True, index=True)
    # the Node this event is for.
    node_id = Column(UUIDType, foreign_key("Node", "id"), index=True)
    # the User who performed the event action on the Node.
    user_id = Column(UUIDType, foreign_key("User", "id"), index=True)
    # the type of action that was performed on Node.
    action = Column(Enum(*NODE_EVENT_ACTIONS, name="action"), nullable=False)
    # the timestamp when the event was created.
    created_timestamp = Column(BigInteger, nullable=False)

    def __init__(self, user, node, action):
        self.id = uuid.uuid1()
        self.user = user
        self.node = node
        self.action = action
        self.created_timestamp = now_timestamp()

    # 1-to-1 relationships.
    node = relationship(argument="Node", uselist=False, lazy="joined")
    user = relationship(
        argument="User",
        uselist=False,
        lazy="joined",
        backref=backref("events", cascade="save-update, merge, delete"),
    )


def get_node_event_by_id(dbsession, node_event_id):
    """Try to get NodeEvent object by id or return None."""
    return get_object_by_id(dbsession, node_event_id, NodeEvent)
