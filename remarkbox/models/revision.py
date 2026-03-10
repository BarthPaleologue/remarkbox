"""Revision model — tracks edit history for wiki mode."""

from sqlalchemy import BigInteger, Column, Integer, Unicode, UnicodeText
from sqlalchemy.orm import relationship

import uuid

from .meta import Base, RBase, UUIDType, now_timestamp, foreign_key


class Revision(RBase, Base):
    """Stores a snapshot of node content before each edit.

    When wiki mode is enabled on a namespace, every edit to a root node
    creates a revision record preserving the previous state.
    """
    id = Column(UUIDType, primary_key=True, index=True)
    node_id = Column(UUIDType, foreign_key("Node", "id"), nullable=False, index=True)
    user_id = Column(UUIDType, foreign_key("User", "id"), nullable=True)
    data = Column(UnicodeText, nullable=False)
    source_format = Column(Unicode(16), default="markdown", nullable=False)
    revision_number = Column(Integer, nullable=False)
    created = Column(BigInteger, nullable=False)

    node = relationship("Node", backref="revisions")
    user = relationship("User")

    def __init__(self, node=None, user=None, data="", source_format="markdown", revision_number=1):
        self.id = uuid.uuid1()
        self.created = now_timestamp()
        if node:
            self.node_id = node.id
            self.node = node
        if user:
            self.user_id = user.id
            self.user = user
        self.data = data
        self.source_format = source_format
        self.revision_number = revision_number
