from sqlalchemy import Boolean, Column, Unicode, BigInteger
from sqlalchemy.orm import relationship
import uuid
from .meta import Base, RBase
from .meta import UUIDType
from .meta import now_timestamp, foreign_key, get_object_by_id
import requests
import logging

log = logging.getLogger(__name__)


class NamespaceRequest(RBase, Base):
    id = Column(UUIDType, primary_key=True, index=True)
    user_id = Column(UUIDType, foreign_key("User", "id"), index=True)
    namespace_id = Column(UUIDType, foreign_key("Namespace", "id"), index=True)
    created_timestamp = Column(BigInteger, nullable=False, index=True)
    # this is the endpoint uri to scrape looking for the namespace request id.
    target = Column(Unicode(256), nullable=True)
    verified = Column(Boolean, default=False)
    last_scrape_timestamp = Column(
        BigInteger, nullable=True
    )  # New column to track last scrape time

    user = relationship(
        argument="User",
        uselist=False,
        lazy="joined",
        back_populates="namespace_owner_requests",
    )

    namespace = relationship(
        argument="Namespace",
        uselist=False,
        lazy="joined",
        back_populates="namespace_owner_requests",
    )

    def __init__(self, user, namespace, target=None):
        self.created_timestamp = now_timestamp()
        self.id = uuid.uuid1()
        self.user = user
        self.namespace = namespace
        self.target = target

    def verify(self):
        self.namespace.owner_request_timestamp = now_timestamp()
        self.verified = True

    def unverify(self):
        self.namespace.owner_request_timestamp = now_timestamp()
        self.verified = False

    def verify_target(self, target):
        self.target = target
        if self.scrape_target():
            self.verify()
        else:
            self.unverify()

    def scrape_target(self):
        """Scrape the given target for NamespaceRequest id
        Return True if found else False.
        """
        current_time = now_timestamp()
        # Check if the last scrape was within the last 5 minutes (300 seconds)
        if (
            self.last_scrape_timestamp
            and (current_time - self.last_scrape_timestamp) < 300
        ):
            return self.verified

        namespace_request_id = str(self.id)
        if self.target:
            # https://en.wikipedia.org/wiki/List_of_HTTP_header_fields#Request_fields
            headers = {
                "User-Agent": "remarkbox.com",
            }

            log.info(
                "scraping target={} looking for uuid={}".format(
                    self.target, namespace_request_id
                )
            )
            resp = requests.get(self.target, timeout=8.50)
            if resp.ok:
                if namespace_request_id in resp.text:
                    log.info(
                        "scraping target={} looking for uuid={} status=hit".format(
                            self.target,
                            namespace_request_id,
                        )
                    )
                    self.last_scrape_timestamp = current_time
                    return True

                log.info(
                    "scraping target={} looking for uuid={} status=miss".format(
                        self.target,
                        namespace_request_id,
                    )
                )
                self.last_scrape_timestamp = current_time
                return False
            log.info(
                "scraping target={} looking for uuid={} status={} reason={}".format(
                    self.target,
                    namespace_request_id,
                    resp.status_code,
                    resp.reason,
                )
            )
            self.last_scrape_timestamp = current_time
            return False


def get_namespace_request_by_id(dbsession, namespace_request_id):
    """Try to get NamespaceRequest object by id or return None."""
    return get_object_by_id(dbsession, namespace_request_id, NamespaceRequest)


def get_namespace_request(dbsession, user, namespace):
    if user and namespace:
        return (
            dbsession.query(NamespaceRequest)
            .filter(
                NamespaceRequest.user_id == user.id,
                NamespaceRequest.namespace_id == namespace.id,
            )
            .one_or_none()
        )


def get_or_create_namespace_request(dbsession, user, namespace):
    namespace_request = get_namespace_request(dbsession, user, namespace)
    if namespace_request is None:
        namespace_request = NamespaceRequest(user, namespace)
    return namespace_request


def get_topsecret_namespace_requests(dbsession, limit=100, offset=0):
    return (
        dbsession.query(NamespaceRequest)
        .order_by(NamespaceRequest.created_timestamp.desc())
        .limit(limit)
        .offset(offset)
    )
