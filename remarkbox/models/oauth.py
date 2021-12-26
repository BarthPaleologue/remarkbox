from .meta import Base, RBase, UUIDType, foreign_key, get_object_by_id, now_timestamp

from sqlalchemy import Column, BigInteger, Unicode, UnicodeText

from sqlalchemy.orm import relationship

import uuid

import json

try:
    unicode("")
except:
    from six import u as unicode


class Oauth(RBase, Base):
    id = Column(UUIDType, primary_key=True, index=True)
    # the related user this oauth record belongs to.
    user_id = Column(UUIDType, foreign_key("User", "id"), index=True)
    # the related namespace this oauth record belongs to.
    namespace_id = Column(UUIDType, foreign_key("Namespace", "id"), index=True)
    # the name of the service (type of oauth record), for example slack.
    service = Column(Unicode(16), nullable=False)
    # the token provided after oauth dance used to communicate with 3rd party.
    token = Column(Unicode(256), nullable=False)
    # optional json_data without defined schema.
    json_data = Column(UnicodeText, default=None)
    # timestamp when Namespace owner authorized consent to connect with 3rd party oauth.
    created_timestamp = Column(BigInteger, nullable=False)
    # the last time this record was modified.
    updated_timestamp = Column(BigInteger, nullable=False)

    def __init__(self, user, namespace, service, token, data=None):
        self.id = uuid.uuid1()
        self.user = user
        self.namespace = namespace
        self.service = unicode(service)
        self.token = unicode(token)
        self.created_timestamp = now_timestamp()
        self.data = data

    # 1-to-1 relationships.
    user = relationship(argument="User", uselist=False, lazy="joined")
    namespace = relationship(argument="Namespace", uselist=False, lazy="joined")

    @property
    def data(self):
        if self.json_data:
            return json.loads(self.json_data)
        return None

    @data.setter
    def data(self, new_data):
        if new_data:
            self.json_data = json.dumps(new_data)
        else:
            self.json_data = None
        self.updated_timestamp = now_timestamp()


def get_oauth_by_id(dbsession, oauth_id):
    """Try to get Oauth object by id or return None"""
    return get_object_by_id(dbsession, oauth_id, Oauth)
