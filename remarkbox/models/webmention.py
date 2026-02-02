from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Unicode,
    UnicodeText,
)

from sqlalchemy.orm import relationship

import uuid

from .meta import Base, RBase, UUIDType, foreign_key, now_timestamp, get_object_by_id

import logging

log = logging.getLogger(__name__)


class Webmention(RBase, Base):
    """
    Represents a received webmention -- a notification from an external
    site that it has linked to a page with a Remarkbox thread.

    Reference: https://www.w3.org/TR/webmention/
    """

    id = Column(UUIDType, primary_key=True, index=True)
    source = Column(Unicode(2048), nullable=False)
    target = Column(Unicode(2048), nullable=False)
    node_id = Column(UUIDType, foreign_key("Node", "id"), index=True, nullable=True)
    verified = Column(Boolean, default=False, nullable=False)
    author_name = Column(Unicode(256), nullable=True)
    author_url = Column(Unicode(2048), nullable=True)
    content = Column(UnicodeText, nullable=True)
    created_timestamp = Column(BigInteger, nullable=False)
    updated_timestamp = Column(BigInteger, nullable=False)

    node = relationship(argument="Node", uselist=False, lazy="joined")

    def __init__(self, source, target):
        self.id = uuid.uuid1()
        self.source = source
        self.target = target
        self.created_timestamp = now_timestamp()
        self.updated_timestamp = now_timestamp()

    def mark_verified(self, author_name=None, author_url=None, content=None):
        self.verified = True
        self.updated_timestamp = now_timestamp()
        if author_name:
            self.author_name = author_name
        if author_url:
            self.author_url = author_url
        if content:
            self.content = content[:500]


def get_webmention_by_id(dbsession, webmention_id):
    return get_object_by_id(dbsession, webmention_id, Webmention)


def get_webmention_by_source_and_target(dbsession, source, target):
    return (
        dbsession.query(Webmention)
        .filter(Webmention.source == source, Webmention.target == target)
        .one_or_none()
    )


def get_verified_webmentions_for_node(dbsession, node_id):
    return (
        dbsession.query(Webmention)
        .filter(Webmention.node_id == node_id, Webmention.verified == True)
        .order_by(Webmention.created_timestamp.desc())
        .all()
    )
