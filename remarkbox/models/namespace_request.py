from sqlalchemy import Boolean, Column, Unicode, BigInteger
from sqlalchemy.orm import relationship
import uuid
from .meta import Base, RBase
from .meta import UUIDType
from .meta import now_timestamp, foreign_key, get_object_by_id
import requests
import logging
import threading
from datetime import datetime, timedelta
from miniuri import Uri

log = logging.getLogger(__name__)

# Dictionary to track when scraping is allowed again for specific domains
domain_skip_until = {}


class NamespaceRequest(RBase, Base):
    id = Column(UUIDType, primary_key=True, index=True)
    user_id = Column(UUIDType, foreign_key("User", "id"), index=True)
    namespace_id = Column(UUIDType, foreign_key("Namespace", "id"), index=True)
    created_timestamp = Column(BigInteger, nullable=False, index=True)
    target = Column(Unicode(256), nullable=True)
    verified = Column(Boolean, default=False)
    last_scrape_timestamp = Column(BigInteger, nullable=True)

    _scrape_lock = threading.Lock()

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
        """Verify the target only if not already verified or if a day has passed since last verification."""
        current_time = now_timestamp()
        one_day_in_milliseconds = 24 * 60 * 60 * 1000

        # Skip verification if already verified and last scrape was within a day
        if (
            self.verified
            and self.last_scrape_timestamp
            and (current_time - self.last_scrape_timestamp) < one_day_in_milliseconds
        ):
            log.info(
                f"Skipping target verification for verified namespace request id={self.id}"
            )
            return None

        self.target = target
        if self.scrape_target():
            self.verify()
        else:
            self.unverify()

    def scrape_target(self, max_redirects=5):
        """Scrape the given target for NamespaceRequest id
        Return True if found else False.
        """
        current_time = now_timestamp()
        one_day_in_milliseconds = 24 * 60 * 60 * 1000

        # Skip scraping if already verified and last scrape was within a day
        if (
            self.verified
            and self.last_scrape_timestamp
            and (current_time - self.last_scrape_timestamp) < one_day_in_milliseconds
        ):
            log.info(f"Skipping scrape for verified namespace request id={self.id}")
            return True

        # Extract domain from target using miniuri
        domain = self._get_domain_from_target(self.target)

        # Check if the domain is currently being skipped
        if domain in domain_skip_until and datetime.now() < domain_skip_until[domain]:
            log.info(
                f"Skipping scrape for domain={domain} until {domain_skip_until[domain]}"
            )
            return self.verified

        if not self._scrape_lock.acquire(blocking=False):
            log.info("Scrape already in progress for uuid={}".format(self.id))
            return self.verified

        try:
            if (
                self.last_scrape_timestamp
                and (current_time - self.last_scrape_timestamp) < 300
            ):
                return self.verified

            namespace_request_id = str(self.id)
            if self.target:
                headers = {
                    "User-Agent": "remarkbox.com",
                }

                log.info(
                    "scraping target={} looking for uuid={}".format(
                        self.target, namespace_request_id
                    )
                )
                try:
                    # Follow redirects up to max_redirects
                    resp = requests.get(
                        self.target, headers=headers, timeout=8.50, allow_redirects=True
                    )
                    redirect_count = 0
                    while resp.is_redirect and redirect_count < max_redirects:
                        redirect_count += 1
                        next_url = resp.headers.get("Location")
                        if not next_url:
                            break
                        log.info(f"Redirecting to {next_url}")
                        resp = requests.get(next_url, headers=headers, timeout=8.50)

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
                    elif resp.status_code == 429:  # Too Many Requests
                        # Set skip time for the domain
                        domain_skip_until[domain] = datetime.now() + timedelta(
                            minutes=30
                        )
                        log.info(
                            f"Rate limited by domain={domain}, skipping until {domain_skip_until[domain]}"
                        )
                except requests.RequestException as e:
                    log.error(f"Error scraping target={self.target}: {e}")

                self.last_scrape_timestamp = current_time
                return False
        finally:
            self._scrape_lock.release()

    def _get_domain_from_target(self, target):
        """Extract the domain from the target URL using miniuri."""
        uri = Uri(target)
        return uri.hostname


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
