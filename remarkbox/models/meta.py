from sqlalchemy.ext.declarative import declarative_base, declared_attr

from sqlalchemy.orm.session import object_session

from sqlalchemy.schema import MetaData
from sqlalchemy import ForeignKey

from time import time

import base64
import uuid
from sqlalchemy_utils import UUIDType as TempUUIDType

UUIDType = TempUUIDType(binary=False)

# Recommended naming convention used by Alembic, as various different database
# providers will autogenerate vastly different names making migrations more
# difficult. See: http://alembic.zzzcomputing.com/en/latest/naming.html
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

CLASS_TO_TABLE = {
    "Uri": "rb_uri",
    "User": "rb_user",
    "UserSurrogate": "rb_user_surrogate",
    "Vote": "rb_vote",
    "Node": "rb_node",
    "NodeCache": "rb_node_cache",
    "Namespace": "rb_namespace",
    "NamespaceUser": "rb_namespace_user",
    "NamespaceRequest": "rb_namespace_request",
    "Oauth": "rb_oauth",
    "Watcher": "rb_watcher",
    "NodeEvent": "rb_node_event",
    "NodeEventNotification": "rb_node_event_notification",
    "PayWhatYouCan": "rb_pay_what_you_can",
    "Payment": "rb_payment",
}

# node (threads), namespace (forum)
WATCHER_TYPES = {"reply", "node", "namespace"}

NOTIFICATION_FREQUENCIES = {"never", "immediately", "daily", "weekly"}

NOTIFICATION_METHODS = {"email"}

NODE_EVENT_ACTIONS = {
    "enabled",
    "disabled",
    "deleted",
    "verified",
    "created",  # this is a new thread.
    "commented",  # this is a reply to an existing thread.
    "approved",
    "edited",
    # These event type actions don't exist yet, but could fuel some ideas for the future.
    # "flagged",
    # "voted",
}

SUBSCRIPTION_TYPES = {"development", "production", "trial"}

# currently not used anywhere.
USER_EVENT_ACTIONS = {"granted", "promoted", "demoted", "blocked"}

metadata = MetaData(naming_convention=NAMING_CONVENTION)
# Base = declarative_base(metadata=metadata)
Base = declarative_base()


def short_id_to_bytes(short_id):
    """Accept a short_id (sanitized url safe base64 string) and return a byte string.

    >>> short_id_to_bytes('dbHeSEFLEeeuz5xONpxxWA')
    b'u\xb1\xdeHAK\x11\xe7\xae\xcf\x9cN6\x9cqX'

    """
    return base64.b64decode((short_id + "===").replace("_", "/").replace("-", "+"))


def id_to_uuid(the_id):
    """
    Accept an id string, return a UUID object.

    >>> id_to_uuid('dbHeSEFLEeeuz5xONpxxWA')
    UUID('75b1de48-414b-11e7-aecf-9c4e369c7158')

    >>> id_to_uuid('75b1de48414b11e7aecf9c4e369c7158')
    UUID('75b1de48-414b-11e7-aecf-9c4e369c7158')

    >>> id_to_uuid('75b1de48-414b-11e7-aecf-9c4e369c7158')
    UUID('75b1de48-414b-11e7-aecf-9c4e369c7158')
    """
    if isinstance(the_id, uuid.UUID):
        # if the_id is already a UUID object, return it.
        return the_id

    try:
        # assume the_id is already a hex uuid string.
        return uuid.UUID(hex=the_id)

    except ValueError:
        try:
            # assume the_id is a base64 "short_id" string.
            return uuid.UUID(bytes=short_id_to_bytes(the_id))
        except ValueError:
            pass

    return None


def get_object_by_id(dbsession, object_id, cls):
    """Try to get object from database by id or return None"""
    object_uuid = id_to_uuid(object_id)
    if object_uuid:
        return dbsession.query(cls).filter(cls.id == object_uuid).one_or_none()


def now_timestamp():
    return int(time() * 1000)


def foreign_key(class_name, column_name):
    return ForeignKey("{}.{}".format(CLASS_TO_TABLE[class_name], column_name))


class RBase(object):
    """Mixin for RemarkBox models."""

    def __eq__(self, other):
        """Determine if equal by id."""
        if other:
            return self.id == other.id
        return False

    def __ne__(self, other):
        """Determine if not equal by user id."""
        return not self.__eq__(other)

    def __hash__(self):
        return hash(self.id)

    @declared_attr
    def __tablename__(cls):
        return CLASS_TO_TABLE[cls.__name__]

    @property
    def dbsession(self):
        return object_session(self)

    @property
    def id_without_dashes(self):
        return self.id.__str__().replace("-","")
