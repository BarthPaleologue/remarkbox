from sqlalchemy import Integer, BigInteger, Boolean, Column, Unicode, UnicodeText, or_

from sqlalchemy.orm import relationship, backref

from sqlalchemy.ext.associationproxy import association_proxy

import uuid

from collections import defaultdict

from .meta import Base, RBase
from .meta import now_timestamp, foreign_key
from .meta import UUIDType


class NamespaceUser(RBase, Base):
    user_id = Column(UUIDType, foreign_key("User", "id"), primary_key=True, index=True)
    namespace_id = Column(
        UUIDType, foreign_key("Namespace", "id"), primary_key=True, index=True
    )
    role = Column(Unicode(64), default=None)
    # TODO: someday this should be renamed to created_timestamp
    created = Column(BigInteger, nullable=False)
    # TODO: someday this should be renamed to changed_timestamp
    changed = Column(BigInteger, nullable=False)
    disabled = Column(Boolean, default=False)
    verified = Column(Boolean, default=False)

    user = relationship(
        argument="User",
        backref=backref("user_namespaces", cascade="all, delete-orphan"),
    )

    namespace = relationship(
        argument="Namespace",
        backref=backref("namespace_users", cascade="all, delete-orphan"),
    )

    def __init__(self, role=None, namespace=None, user=None):
        self.created = now_timestamp()
        self.changed = now_timestamp()
        self.role = role
        self.namespace = namespace
        self.user = user
