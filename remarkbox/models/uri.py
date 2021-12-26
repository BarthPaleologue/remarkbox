from .meta import Base, RBase
from .meta import foreign_key
from .meta import UUIDType

from sqlalchemy import Unicode, Column, BigInteger

from sqlalchemy.orm import relationship

import uuid

import miniuri

from remarkbox.lib import (
    timestamp_to_datetime,
    timestamp_to_ago_string,
    timestamp_to_date_string,
)

from .meta import now_timestamp

import logging

try:
    unicode("")
except:
    from six import u as unicode

log = logging.getLogger(__name__)


class Uri(RBase, Base):
    id = Column(UUIDType, primary_key=True, index=True)
    node_id = Column(UUIDType, foreign_key("Node", "id"))
    accessed_timestamp = Column(BigInteger, nullable=False, default=0, index=True)
    data = Column(Unicode(256), nullable=False, index=True, unique=True)

    node = relationship(argument="Node", uselist=False, back_populates="uri")

    def __init__(self, data=None):
        self.id = uuid.uuid1()
        self.data = unicode(data)

    @property
    def data_ascii(self):
        return self.data.encode('ascii', 'ignore')

    @property
    def parsed(self):
        return miniuri.Uri(self.data)

    @property
    def favicon(self):
        favicon = self.parsed
        favicon.path = "/favicon.ico"
        return favicon

    @property
    def robots(self):
        robots = self.parsed
        robots.path = "/robots.txt"
        return robots

    # TODO: take into account user's timezone?
    @property
    def accessed_date(self):
        return timestamp_to_date_string(self.accessed_timestamp)

    # TODO: take into account user's timezone?
    @property
    def accessed_datetime(self):
        return timestamp_to_datetime(self.accessed_timestamp)


def get_all_uris(dbsession):
    return dbsession.query(Uri).order_by(Uri.access_timestamp.desc()).all()


def get_uri_by_uri(dbsession, external_uri):
    """Try to get Uri object by external_uri or return None"""
    if external_uri:
        return (
            dbsession.query(Uri).filter(Uri.data == unicode(external_uri)).one_or_none()
        )


def get_or_create_uri_by_uri(dbsession, external_uri):
    uri = get_uri_by_uri(dbsession, external_uri)
    if uri is None:
        uri = Uri(external_uri)
    return uri


def get_or_create_uri(dbsession, external_uri):
    """Try to get Uri object by external_uri or return a new Uri."""
    # imported here to prevent circular import.
    from .namespace import get_or_create_namespace

    if external_uri.count("://") >= 2:
        # example:
        # https://webcache.googleusercontent.com/search?
        #   q=cache:pSxEzC1gfeIJ:https://www.crazygames.com/game/shellshockersio+&cd=2&hl=en&ct=clnk&gl=us
        if "webcache.googleusercontent.com" in external_uri:
            # deal with google web cache to get at the real uri.
            # https://www.crazygames.com/game/shellshockersio
            external_uri_parts = external_uri.split(":")
            external_uri = ":".join(external_uri_parts[-2:])
            external_uri = external_uri.split("+")[0]
        else:
            # ignore the query string without consulting Namespace.
            # thread_uri=https://www.crazygames.com/game/happy-wheels?
            #   utm_source=https%3A%2F%2Fwww.crazygames.com%2Fgame%2Fhappy-wheels
            external_uri = external_uri.split("?")[0]

    elif "?" in external_uri:
        # check if we should ignore query string.
        log.info("parsing hostname with miniuri: {}".format(external_uri))
        muri = miniuri.Uri(external_uri)
        namespace = get_or_create_namespace(dbsession, muri.hostname)

        if namespace.ignore_query_string:
            # search for uri without query string.
            external_uri = external_uri.split("?")[0]

    # by default remove any anchor fragments from external uri.
    # TODO: configurable from Namespace settings?
    if "#" in external_uri:
        # search for uri without fragment string.
        external_uri = external_uri.split("#")[0]

    # https://www.example.com/index.html -> https://www.example.com
    # https://www.example.com/asdf/index.php -> https://www.example.com/asdf
    # TODO: configurable from Namespace settings?
    if "/index." in external_uri:
        for extension in ["html", "php"]:
            file_part = "/index.{}".format(extension)
            if external_uri.endswith(file_part):
                external_uri = external_uri.rstrip(file_part)

    return get_or_create_uri_by_uri(dbsession, external_uri)
