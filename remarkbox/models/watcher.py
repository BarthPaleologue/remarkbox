from .meta import WATCHER_TYPES, NOTIFICATION_FREQUENCIES, NOTIFICATION_METHODS
from .meta import Base, RBase, UUIDType, foreign_key, get_object_by_id, now_timestamp

from sqlalchemy import Column, BigInteger, Unicode, UnicodeText, Enum

from sqlalchemy.orm import relationship

import uuid

from .notification import NodeEventNotification


class Watcher(RBase, Base):
    id = Column(UUIDType, primary_key=True, index=True)
    # the User watching the Node.
    user_id = Column(UUIDType, foreign_key("User", "id"), index=True)
    # the Node under watch.
    node_id = Column(UUIDType, foreign_key("Node", "id"), index=True, nullable=True)
    # the Namespace under watch.
    namespace_id = Column(
        UUIDType, foreign_key("Namespace", "id"), index=True, nullable=True
    )
    # the type of watcher object.
    type = Column(Enum(*WATCHER_TYPES, name="type"))
    # how will this watcher object notify?
    notification_method = Column(
        Enum(*NOTIFICATION_METHODS, name="notification_method"), default="email"
    )
    # how frequently should we notify of changes?
    notification_frequency = Column(
        Enum(*NOTIFICATION_FREQUENCIES, name="frequency"), default="daily"
    )
    # the point in time when the User started authorized consent to watch.
    created_timestamp = Column(BigInteger, nullable=False)
    # the last time this record was modified.
    updated_timestamp = Column(BigInteger, nullable=False)

    def __init__(
        self,
        user,
        type,
        notification_method="email",
        notification_frequency="daily",
        node=None,
        namespace=None,
    ):
        self.id = uuid.uuid1()
        self.user = user
        self.type = type
        self.notification_method = notification_method
        self.notification_frequency = notification_frequency
        self.created_timestamp = now_timestamp()
        self.updated_timestamp = now_timestamp()

        self.node = node
        self.namespace = namespace

    # 1-to-1 relationships.
    node = relationship(argument="Node", uselist=False, lazy="joined")
    namespace = relationship(argument="Namespace", uselist=False, lazy="joined")
    user = relationship(argument="User", uselist=False, lazy="joined")
    notifications = relationship(
        argument="NodeEventNotification",
        lazy="dynamic",
        cascade="save-update, merge, delete",
        back_populates="watcher"
    )

    def unsent_notifications(self):
        self.notifications.filter(NodeEventNotification.sent == False)

    def new_notification(self, node_event):
        notification = NodeEventNotification(watcher=self, node_event=node_event)
        self.notifications.append(notification)
        return notification


def get_watcher_by_id(dbsession, watcher_id):
    """Try to get Watcher object by id or return None."""
    return get_object_by_id(dbsession, watcher_id, Watcher)
