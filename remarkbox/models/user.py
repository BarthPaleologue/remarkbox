from sqlalchemy import BigInteger, Boolean, Integer, Column, Unicode, Enum, func, or_

from sqlalchemy.orm import relationship, backref

from sqlalchemy.ext.associationproxy import association_proxy

import uuid

import bcrypt

from remarkbox.lib import timestamp_to_ago_string, gravatar_client

from remarkbox.lib.svgtar import inline_svgtar

from .meta import NOTIFICATION_FREQUENCIES
from .meta import Base, RBase, UUIDType, now_timestamp, foreign_key, get_object_by_id

from .node import Node

from .namespace_request import NamespaceRequest

from .watcher import Watcher

from .notification import NodeEventNotification

import logging

log = logging.getLogger(__name__)

try:
    unicode("")
except:
    from six import u as unicode


def generate_password(size=32):
    """Return a system generated password"""
    from random import choice
    letters = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    digits = "0123456789"
    pool = letters + digits
    return "".join([choice(pool) for i in range(size)])


class UserSurrogate(RBase, Base):
    """
    This class represents a user surrogate account, a stand in.

    A user surrogate may not log in; has no email. It is not a "real"
    User, but a surrogate, a ghost of a user imported from another system.
    """

    id = Column(UUIDType, primary_key=True, index=True)
    # the namespace which imported this user surrogate.
    namespace_id = Column(UUIDType, foreign_key("Namespace", "id"), index=True)
    # the display name.
    name = Column(Unicode(64), nullable=False)
    created_timestamp = Column(BigInteger, nullable=False)

    namespace = relationship(argument="Namespace", uselist=False, lazy="joined")

    # lazy='dynamic' returns a query object instead of collection.
    # Reference: http://docs.sqlalchemy.org/en/latest/orm/collections.html
    nodes = relationship(
        argument="Node",
        lazy="dynamic",
        order_by=Node.created.desc(),
        back_populates="user_surrogate",
    )

    def __init__(self, name, namespace):
        self.name = name
        self.namespace_id = namespace.id
        self.created_timestamp = now_timestamp()
        self.id = uuid.uuid1()

    def svgtar(self, **kwargs):
        if "text" not in kwargs:
            kwargs["text"] = self.name[:1]
        return inline_svgtar(h=str(self.id), **kwargs)

    def avatar_uri(self, **kwargs):
        return self.svgtar(**kwargs)


class User(RBase, Base):
    """This class represents a user account"""

    # was this User object authenticated?
    authenticated = False

    id = Column(UUIDType, primary_key=True, index=True)
    name = Column(Unicode(64), unique=True, nullable=False)
    email = Column(Unicode(64), unique=True, nullable=False)
    # the email_id is a random string added to otp links to prevent an
    # attacker from looping/triggering otp emails for a list of addresses.
    # we only share this string with the owner of an email box. not-in-use...
    email_id = Column(Unicode(8))
    password = Column(Unicode(64))
    password_attempts = Column(Integer, default=0)
    password_timestamp = Column(BigInteger)
    # TODO: someday this should be renamed to created_timestamp
    created = Column(BigInteger, nullable=False)
    gravatar = Column(Boolean, default=False)
    verified = Column(Boolean, default=False)
    disabled = Column(Boolean, default=False)
    # automatically watch any threads I create.
    auto_watch_threads_i_create = Column(Boolean, default=True, nullable=False)
    # automatically watch any threads I participate in.
    auto_watch_threads_i_participate = Column(Boolean, default=False, nullable=False)
    # By default, when I watch a Thread, I want to be notified:
    default_node_watcher_frequency = Column(
        Enum(*NOTIFICATION_FREQUENCIES, name="frequency"),
        default="daily",
        nullable=False,
    )
    # Theme mode preference: 'auto', 'light', or 'dark'. 'auto' respects parent site.
    theme_mode = Column(
        Enum('auto', 'light', 'dark', name='theme_mode_enum'),
        default='auto',
        nullable=False,
    )
    votes = relationship(argument="Vote", backref="user", order_by="desc(Vote.created)")

    # lazy='dynamic' returns a query object instead of collection.
    # Reference: http://docs.sqlalchemy.org/en/latest/orm/collections.html
    nodes = relationship(
        argument="Node",
        lazy="dynamic",
        order_by=Node.created.desc(),
        back_populates="user",
    )

    namespaces = association_proxy(
        "user_namespaces", "namespace", creator=lambda n: NamespaceUser(namespace=n)
    )

    oauth_records = relationship(
        argument="Oauth", lazy="dynamic", back_populates="user"
    )

    namespace_owner_requests = relationship(
        argument="NamespaceRequest", lazy="dynamic", back_populates="user"
    )

    watchers = relationship(
        argument="Watcher",
        lazy="dynamic",
        back_populates="user",
        order_by=Watcher.created_timestamp,
        cascade="save-update, merge, delete",
    )

    # 1-to-1 relationships.
    pay_what_you_can = relationship(argument="PayWhatYouCan", uselist=False, lazy="joined")

    # Payment history
    payments = relationship(
        argument="Payment",
        lazy="dynamic",
        back_populates="user",
        order_by="desc(Payment.created_timestamp)",
        cascade="save-update, merge, delete",
    )

    @property
    def node_watchers(self):
        return self.watchers.filter(Watcher.type == "node")

    @property
    def namespace_watchers(self):
        return self.watchers.filter(Watcher.type == "namespace")

    @property
    def reply_watchers(self):
        return self.watchers.filter(Watcher.type == "reply")

    @property
    def reply_watcher(self):
        """for now we only support one reply_watcher in the UI."""
        return self.watchers.filter(Watcher.type == "reply").one()

    def get_watcher_by_id(self, watcher_id):
        """Return a Watcher object for by ID or None."""
        return self.node_watchers.filter(Watcher.id == watcher_id).one_or_none()

    def get_watcher_by_node_id(self, node_id):
        """Return a Watcher object for the node (thread) or None."""
        return self.node_watchers.filter(Watcher.node_id == node_id).one_or_none()

    def watch_node(self, node):
        """create and return new Watcher object for this node and user in memory"""
        watcher = Watcher(
            user=self,
            type="node",
            node=node,
            notification_frequency=self.default_node_watcher_frequency,
        )
        self.watchers.append(watcher)
        return watcher

    def watch_namespace(self, namespace):
        """create and return new Watcher object for this namespace and user in memory"""
        watcher = self.get_watcher_by_namespace_id(namespace.id)
        if watcher:
            return watcher

        watcher = Watcher(
            user=self,
            type="namespace",
            namespace=namespace,
            notification_frequency="daily",
        )
        self.watchers.append(watcher)
        return watcher

    def get_watcher_by_namespace_id(self, namespace_id):
        """Return a Watcher object for the Namespace or None."""
        return self.namespace_watchers.filter(
            Watcher.namespace_id == namespace_id
        ).one_or_none()

    def unwatch_namespace(self, namespace):
        """Stop watching a Namespace."""
        watcher = self.get_watcher_by_namespace_id(namespace.id)
        if watcher:
            self.dbsession.delete(watcher)
            self.dbsession.flush()

    node_notifications = relationship(
        argument="NodeEventNotification", lazy="dynamic", back_populates="user"
    )

    @property
    def unsent_node_notifications(self):
        return self.node_notifications.filter(NodeEventNotification.sent == False)

    @property
    def sent_node_notifications(self):
        return self.node_notifications.filter(NodeEventNotification.sent == True)

    @property
    def verified_namespace_owner_requests(self):
        return [nr for nr in self.namespace_owner_requests if nr.verified]

    @property
    def unverified_namespace_owner_requests(self):
        return [nr for nr in self.namespace_owner_requests if not nr.verified]

    @property
    def verified_nodes(self):
        return self.nodes.filter(Node.verified == True, Node.disabled == False)

    @property
    def unverified_nodes(self):
        return self.nodes.filter(Node.verified == False, Node.disabled == False)

    @property
    def disabled_nodes(self):
        return self.nodes.filter(Node.verified == True, Node.disabled == True)

    @property
    def unapproved_nodes(self):
        return self.nodes.filter(or_(Node.approved == False, Node.approved.is_(None)))

    def page_nodes(self, limit=100, offset=0):
        if self.nodes.count() == 0:
            return []
        return (
            self.nodes.filter(
                Node.disabled == False, Node.verified == True, Node.user_id != None, Node.approved == True
            )
            .order_by(Node.changed.desc())
            .limit(limit)
            .offset(offset)
        )

    def __init__(self, email):
        self.name = unicode(generate_password(size=8))
        self.created = now_timestamp()
        self.id = uuid.uuid1()
        self.email = unicode(email)

        # TODO: this field was never used & should be sunset.
        self.email_id = unicode(generate_password(size=8))

        self.new_password()
        # don't password throttle new User objects.
        self.password_timestamp = 0

    def _generate_raw_password(self):
        """Return a system generated password"""
        #return generate_password(size)
        from random import choice
        numbers = '0123456789'
        return "".join([choice(numbers) for i in range(0,6)])

    def new_password(self):
        """Generate and return raw password, store password hash into DB."""
        raw_password = self._generate_raw_password()

        # bcrypt works with bytes so we encode to utf-8.
        self.password = bcrypt.hashpw(
            raw_password.encode("utf-8"),
            bcrypt.gensalt()
        ).decode("utf-8")
        self.password_timestamp = now_timestamp()
        self.password_attempts = 0
        return raw_password

    def check_password(self, password):
        """Accept plain-text raw password, create hash, compare with DB."""
        stored_hash = self.password

        # increment password attempts.
        self.password_attempts += 1

        # expire password after 15 minutes.
        # 900000 milliseconds == 15 minutes
        if self.password_timestamp_delta >= 900000:
            return False

        # prevent brute force, allow 10 invalid verification code attempts.
        if self.password_attempts >= 10:
            return False

        # bcrypt works with bytes so we encode to utf-8.
        new_hash = bcrypt.hashpw(
            password.encode("utf-8"),
            stored_hash.encode("utf-8"),
        ).decode("utf-8")

        log.info("new_hash={} stored_hash={}".format(new_hash, stored_hash))

        if new_hash == stored_hash:
            return True
        return False

    def throttle_password(self, needed_delta=90000):
        """Return True when throttled, else False"""
        if self.password_timestamp_delta <= needed_delta:
            return True
        return False

    @property
    def password_timestamp_delta(self):
        return now_timestamp() - self.password_timestamp

    @property
    def human_password_timestamp(self):
        return timestamp_to_ago_string(self.password_timestamp)

    @property
    def human_timestamp(self):
        return timestamp_to_ago_string(self.created)

    def gravatar_uri(self, **kwargs):
        return gravatar_client(self.email, **kwargs)

    def svgtar(self, **kwargs):
        if "text" not in kwargs:
            kwargs["text"] = self.name[:1]
        return inline_svgtar(h=str(self.id), **kwargs)

    def avatar_uri(self, **kwargs):
        if self.gravatar:
            return self.gravatar_uri(**kwargs)
        return self.svgtar(**kwargs)

    def create_default_reply_watcher(self):
        if self.reply_watchers.count() == 0:
            reply_watcher = Watcher(self, "reply")
            self.watchers.append(reply_watcher)
            return reply_watcher
        return self.reply_watchers.first()


def _user_by_name_query(dbsession, name):
    """query User by case insensitive name."""
    return dbsession.query(User).filter(func.lower(User.name) == unicode(name.lower()))


def is_user_name_available(dbsession, name):
    return not _user_by_name_query(dbsession, unicode(name)).count()


def generate_user_name(dbsession, desired_name=""):
    size = 8
    sep = ""
    if desired_name:
        size = 3
        sep = "-"
    name = sep.join([desired_name, generate_password(size)])
    while is_user_name_available(dbsession, name) == False:
        name = sep.join([desired_name, generate_password(size)])
    return name


def is_user_name_valid(name):
    """Test if user name meets our criteria for validity."""
    # The choices here are subject to change.  Right now we allow dashes.
    name = name.replace("-", "")
    return name.isalnum()


def get_user_by_name(dbsession, name):
    """Try to get User object by name or return None"""
    if name:
        return _user_by_name_query(dbsession, name).one_or_none()


def get_user_by_id(dbsession, user_id):
    """Try to get User object by id or return None."""
    return get_object_by_id(dbsession, user_id, User)


def get_user_by_email(dbsession, email):
    """Try to get User object by email or return None"""
    if email:
        return dbsession.query(User).filter(User.email == unicode(email)).one_or_none()


def get_or_create_user_by_email(dbsession, email):
    """Try to get User object by email or return new User"""
    user = get_user_by_email(dbsession, email)
    if user is None:
        # create new User for unverified user.
        user = User(email)
        if not is_user_name_available(dbsession, user.name):
            user.name = generate_user_name(dbsession)
    return user


def get_user_surrogate_by_name(dbsession, name, namespace):
    """Try to get UserSurrogate object by case insensitive name or return None"""
    if name:
        return (
            dbsession.query(UserSurrogate)
            .filter(func.lower(User.name) == unicode(name.lower()))
            .filter(UserSurrogate.namespace_id == namespace.id)
            .one_or_none()
        )


def get_or_create_user_surrogate_by_name(dbsession, name, namespace):
    """
    Try to get UserSurrogate object by case insensitive name
    or create and return a new UserSurrogate
    """
    user_surrogate = get_user_surrogate_by_name(dbsession, name, namespace)
    if user_surrogate is None:
        user_surrogate = UserSurrogate(name=name, namespace=namespace)
    return user_surrogate
