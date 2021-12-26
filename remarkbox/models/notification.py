from .meta import Base, RBase, UUIDType, foreign_key, get_object_by_id, now_timestamp

from sqlalchemy import Column, BigInteger, Boolean, Unicode, UnicodeText, Enum

from sqlalchemy.orm import relationship

import uuid

from remarkbox.lib import (
    timestamp_to_datetime,
    timestamp_to_ago_string,
    timestamp_to_date_string,
)


class NodeEventNotification(RBase, Base):
    id = Column(UUIDType, primary_key=True, index=True)
    # the Node this event is for.
    node_event_id = Column(UUIDType, foreign_key("NodeEvent", "id"), index=True)
    # the watcher which caused this notification to exist.
    watcher_id = Column(UUIDType, foreign_key("Watcher", "id"), index=True)
    # the user to notify.
    user_id = Column(UUIDType, foreign_key("User", "id"), index=True)
    # the type of action that was performed on Node.
    created_timestamp = Column(BigInteger, nullable=False)
    # the timestamp when the notification was last updated.
    updated_timestamp = Column(BigInteger, nullable=False)
    # was the notification sent yet?
    sent = Column(Boolean, default=False)
    # was the notification read yet?
    # not really used for email, but could be useful for
    # push notifications, web notifications, or browser notifications
    read = Column(Boolean, default=False)

    def __init__(self, node_event, watcher):
        self.id = uuid.uuid1()
        self.node_event = node_event
        self.watcher = watcher
        self.user = watcher.user
        self.created_timestamp = now_timestamp()
        self.updated_timestamp = now_timestamp()

    # 1-to-1 relationships.
    node_event = relationship(argument="NodeEvent", uselist=False, lazy="joined")
    watcher = relationship(argument="Watcher", uselist=False, lazy="joined")
    user = relationship(argument="User", uselist=False, lazy="joined")

    @property
    def frequency(self):
        return self.watcher.notification_frequency

    @property
    def method(self):
        return self.watcher.notification_method

    # TODO: take into account user's timezone?
    @property
    def human_created_timestamp(self):
        return timestamp_to_ago_string(self.created_timestamp)

    @property
    def created_date(self):
        return timestamp_to_date_string(self.created_timestamp)

    @property
    def created_datetime(self):
        return timestamp_to_datetime(self.created_timestamp)

    @property
    def human_changed_timestamp(self):
        return timestamp_to_ago_string(self.changed_timestamp)

    @property
    def changed_date(self):
        return timestamp_to_date_string(self.changed_timestamp)

    @property
    def changed_datetime(self):
        return timestamp_to_datetime(self.changed_timestamp)


def get_node_event_notification_by_id(dbsession, node_event_notification_id):
    """Try to get NodeEventNotification object by id or return None."""
    return get_object_by_id(dbsession, node_event_notfication_id, NodeEventNotification)


def get_topsecret_notifications(dbsession, limit=100, offset=0):
    """Return all NodeEventNotifications."""
    return (
        dbsession.query(NodeEventNotification)
        .order_by(
            NodeEventNotification.created_timestamp.desc(),
            NodeEventNotification.user_id,
        )
        .limit(limit)
        .offset(offset)
    )
