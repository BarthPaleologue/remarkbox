from sqlalchemy import (
    Integer,
    BigInteger,
    Boolean,
    Column,
    Enum,
    Unicode,
    UnicodeText,
    or_,
)

from sqlalchemy.orm import relationship, backref

from sqlalchemy.ext.associationproxy import association_proxy

import uuid

from collections import defaultdict

from .meta import Base, RBase
from .meta import UUIDType
from .meta import SUBSCRIPTION_TYPES
from .meta import now_timestamp, foreign_key

from .node import Node, get_nodes_who_share_roots_query

from .namespace_user import NamespaceUser

from .oauth import Oauth

from remarkbox.lib import timestamp_to_ago_string, timestamp_to_datetime

try:
    unicode("")
except:
    from six import u as unicode


# these attributes are protected such that they return the defaults
# when a Namespace is frozen or subscription is expired.
PROTECTED_ATTRIBUTES = {
    "description": None,
    "placeholder_text": None,
    "no_nodes_text": None,
    "theme": None,
    "theme_embed": None,
    "stylesheet": None,
    "stylesheet_uri": None,
    "stylesheet_embed": None,
    "stylesheet_embed_uri": None,
    "wiki": False,
    "google_analytics_id": None,
    "hide_unverified": False,
    "hide_unless_approved": False,
    "allow_anonymous": False,
    "hide_powered_by": False,
    "mathjax": False,
    "link_protection": False,
    "ignore_query_string": False,
    "reverse_order": False,
    "group_conversations": False,
}


class Namespace(RBase, Base):
    id = Column(UUIDType, primary_key=True, index=True)
    name = Column(Unicode(256), nullable=False, unique=True, index=True)
    description = Column(Unicode(256), default=None)
    # optional placeholder text for new node textarea.
    placeholder_text = Column(Unicode(256), default=None, nullable=True)
    # optional placeholder text when there are no nodes in thread.
    no_nodes_text = Column(Unicode(256), default=None, nullable=True)
    # the basic mode theme. TODO: change this column name to `theme_basic`.
    theme = Column(Unicode(256), default=None)
    # the embed mode theme.
    theme_embed = Column(Unicode(256), default=None)
    avatar_size = Column(Integer, default=None)
    # TODO: change this to `stylesheet_basic` and `stylesheet_basic_timestamp`.
    stylesheet = Column(UnicodeText, default=None)
    stylesheet_timestamp = Column(BigInteger)
    stylesheet_uri = Column(Unicode(256), default=None)
    stylesheet_embed = Column(UnicodeText, default=None)
    stylesheet_embed_timestamp = Column(BigInteger)
    stylesheet_embed_uri = Column(Unicode(256), default=None)
    # when was the last time we tested/verified the namespace owner request?
    owner_request_timestamp = Column(BigInteger, nullable=True)
    # optional google analytics id for stand alone mode.
    google_analytics_id = Column(Unicode(18), nullable=True)
    # allow anyone to edit the root node. (not implemented yet)
    wiki = Column(Boolean, default=False)
    # by default we show all nodes but a Namespace can change this behavior.
    # should a node be hidden if unverified by owner or moderator?
    hide_unverified = Column(Boolean, default=False)
    # should a node be hidden until approved by a moderator?
    hide_unless_approved = Column(Boolean, default=False)
    # allow anonymous commenting (name only, no email required)
    allow_anonymous = Column(Boolean, default=False)
    # should we hide the poweredby Remarkbox logo?
    hide_powered_by = Column(Boolean, default=False)
    # should the list of root nodes in this namespace be public or hidden?
    public = Column(Boolean, default=False)
    # should we enable MathJax?
    mathjax = Column(Boolean, default=False)
    # should we enable Link Protection to prevent comments from having links?
    link_protection = Column(Boolean, default=False)
    # check this box if the external site does _not_ use
    # query strings for page identification or navigation.
    ignore_query_string = Column(Boolean, default=False)
    # should we reverse the node order and put newest on top?
    reverse_order = Column(Boolean, default=False)
    # should we group conversations and limit to nesting 2 deep?
    group_conversations = Column(Boolean, default=False)
    # the group postfix used for imports (e.g., "rb" creates "Anonymous-rb")
    # Once set, this becomes permanent for all imported surrogates
    import_group_postfix = Column(Unicode(6), default=None, nullable=True)
    # the type of subscription of this Namespace.
    subscription_type = Column(
        Enum(*SUBSCRIPTION_TYPES, name="subscription_type"),
        # Hooray, Remarkbox becomes pay-what-you-can!
        # https://en.wikipedia.org/wiki/Pay_what_you_can
        default="production",
        nullable=False,
    )

    # lazy='dynamic' returns a query object instead of collection.
    # Reference: http://docs.sqlalchemy.org/en/latest/orm/collections.html
    roots = relationship(argument="Node", lazy="dynamic", back_populates="namespace")

    users = association_proxy(
        "namespace_users", "user", creator=lambda u: NamespaceUser(user=u)
    )

    user_surrogates = relationship(
        argument="UserSurrogate", lazy="dynamic", back_populates="namespace"
    )

    namespace_owner_requests = relationship(
        argument="NamespaceRequest", lazy="dynamic", back_populates="namespace"
    )

    oauth_records = relationship(
        argument="Oauth", lazy="dynamic", back_populates="namespace"
    )

    watchers = relationship(
        argument="Watcher", lazy="dynamic", back_populates="namespace"
    )

    @property
    def powered_up(self):
        if self.subscription_type in ["production", "trial"]:
            return True
        return False

    def reload_memoized_attr_protection(self):
        """If True, protect attributes from access."""
        if self.powered_up:
            # do not protect attributes, the namespace is powered up.
            self.memoized_attr_protection = False
        else:
            # protect attributes, the namespace is not powered up.
            self.memoized_attr_protection = True

    def __getattribute__(self, attr):
        """Protect certain attributes."""
        # return early if attribute isn't protected.
        if attr not in PROTECTED_ATTRIBUTES:
            return object.__getattribute__(self, attr)

        if not hasattr(self, "memoized_attr_protection"):
            self.reload_memoized_attr_protection()

        if self.memoized_attr_protection:
            # attributes currently under protection.
            # load and return the attribute's default value.
            return PROTECTED_ATTRIBUTES[attr]

        # attributes currently not under protection.
        # load and return the attribute's real value.
        return object.__getattribute__(self, attr)

    def __init__(self, name=None):
        self.id = uuid.uuid1()
        self.name = unicode(name)

    def add_oauth_record(self, user, service, token, data=None):
        self.oauth_records.append(
            Oauth(user=user, namespace=self, service=service, token=token, data=data)
        )

    @property
    def slack_oauth_records(self):
        return [oauth for oauth in self.oauth_records if oauth.service == "slack"]

    def get_namespace_user_for_user(self, user):
        """Given a User object, return the NamespaceUser object."""
        for nsu in self.namespace_users:
            if nsu.user == user:
                return nsu

    def set_role_for_user(self, user, role=None):
        """Add User object to NamespaceUser. Default role is moderator."""
        nsu = self.get_namespace_user_for_user(user)
        if nsu is not None:
            nsu.role = role
        else:
            nsu = NamespaceUser(role=role, namespace=self, user=user)
            self.namespace_users.append(nsu)

        user.watch_namespace(self)

    def disable_user(self, user):
        nsu = self.get_namespace_user_for_user(user)
        if nsu is not None:
            user.unwatch_namespace(self)
            nsu.disabled = True

    def enable_user(self, user):
        nsu = self.get_namespace_user_for_user(user)
        if nsu is not None:
            user.watch_namespace(self)
            nsu.disabled = None

    def remove_user(self, user):
        nsu = self.get_namespace_user_for_user(user)
        if nsu is not None:
            self.disable_user(user)
            self.dbsession.delete(nsu)

    @property
    def enabled_namespace_users(self):
        """Return not disabled NamespaceUser objects for this Namespace."""
        return [nsu for nsu in self.namespace_users if not nsu.disabled]

    @property
    def enabled_users(self):
        """Return not disabled User objects for this Namespace."""
        return [nsu.user for nsu in self.enabled_namespace_users]

    @property
    def roles(self):
        """Return dict with role name as key and list of Users as value."""
        roles = defaultdict(list)
        for ns_user in self.enabled_namespace_users:
            roles[ns_user.role].append(ns_user.user)
        return roles

    @property
    def owners(self):
        """Return a list of owner role User objects."""
        return self.roles.get("owner", [])

    @property
    def moderators(self):
        """Return a list of moderator role User objects."""
        return self.enabled_users

    @property
    def visible_roots(self):
        return self.roots.filter(
            Node.verified == True, Node.disabled == False
        ).order_by(Node.changed.desc())

    @property
    def visible_root_stats(self):
        stats = {}
        for root in self.visible_roots:
            if root.title:
                stats[root.path] = root.stats
            elif root.uri:
                stats[root.uri.data] = root.stats
        return stats

    @property
    def nodes(self):
        return (
            get_nodes_who_share_roots_query(self.dbsession, self.roots)
            .filter(Node.parent_id.isnot(None))
            .order_by(Node.changed.desc())
        )

    def page_nodes(self, limit=100, offset=0):
        if self.roots.count() == 0:
            return []

        query = get_nodes_who_share_roots_query(self.dbsession, self.roots).filter(
            Node.disabled == False, Node.user_id != None
        )

        if self.hide_unless_approved:
            query = query.filter(Node.approved == True)

        if self.hide_unverified:
            query = query.filter(Node.verified == True)

        return query.order_by(Node.changed.desc()).limit(limit).offset(offset)

    @property
    def verified_nodes(self):
        return self.nodes.filter(Node.verified == True)

    @property
    def disabled_nodes(self):
        return self.nodes.filter(Node.disabled == True)

    @property
    def approved_nodes(self):
        return self.nodes.filter(Node.approved == True, Node.disabled == False)

    @property
    def unapproved_nodes(self):
        return self.nodes.filter(
            or_(Node.approved == False, Node.approved.is_(None)), Node.disabled == False
        )

    @property
    def visible_nodes(self):
        return get_nodes_who_share_roots_query(self.dbsession, self.visible_roots)

    @property
    def owner_request_pending(self):
        """Is this Namespace due for a owner request verification?"""
        if self.owner_request_timestamp:
            delta = now_timestamp() - self.owner_request_timestamp
            # 5 minutes.
            if delta <= 300:
                return False
        return True

    @property
    def node_order(self):
        if self.reverse_order:
            return "newest-first"
        return "oldest-first"

    def update_owner_request_timestamp(self):
        self.owner_request_timestamp = now_timestamp()

    def clear_owner_request_timestamp(self):
        self.owner_request_timestamp = None

    def set_stylesheet(self, body):
        self.stylesheet = body
        self.stylesheet_timestamp = now_timestamp()

    def set_stylesheet_embed(self, body):
        self.stylesheet_embed = body
        self.stylesheet_embed_timestamp = now_timestamp()

    def is_owner(self, user):
        """Return True if given user owns this namespace, else False."""
        if user and user.authenticated and user in self.owners:
            return True
        return False

    def is_moderator(self, user):
        """Return True if given user moderates this namespace, else False."""
        if user and user.authenticated and user in self.moderators:
            return True
        return False

    def can_alter_node(self, node, user):
        return self.is_moderator(user) or node.is_owner(user)

    def can_see_node(self, node, user):
        visible = True
        if node.disabled:
            visible = False
        if self.hide_unless_approved and not node.approved:
            visible = False
        if self.hide_unverified and not node.verified:
            visible = False

        if user:
            if self.is_moderator(user) or node.is_owner(user):
                # owners can see node.
                visible = True

        return visible

    @property
    def dict_dump(self):
        dump = {}
        for root in self.roots:
            if root.has_uri:
                root_identifier = root.uri.data
            else:
                root_identifier = root.slug
            root_dump = {
                "name" : root_identifier,
                "title" : root.title,
                # TODO: fix when root.created becomes root.created_timestamp.
                "timestamp" : root.created,
            }
            comments = [] 
            for node in root.children:
                comment = {
                    "date" : node.created_date,
                    # TODO: when root.created becomes root.created_timestamp.
                    "timestamp" : node.created,
                    "content" : node.data,
                    "author" : node.user.name,
                    "author_ip" : node.ip_address,
                }
                if self.subscription_type == "production":
                    comment["email"] = node.user.email
                comments.append(comment)
            root_dump["comments"] = comments
            dump[root_identifier] = root_dump
        return dump


def get_topsecret_namespaces(dbsession):
    return dbsession.query(Namespace).all()


def get_namespace_by_name(dbsession, name):
    if name:
        return (
            dbsession.query(Namespace)
            .filter(Namespace.name == unicode(name))
            .one_or_none()
        )


def get_or_create_namespace(dbsession, name):
    namespace = get_namespace_by_name(dbsession, name)
    if not namespace:
        namespace = Namespace(name)
        # commit namespace to db right away to prevent detached instances.
        # causes some trash namespaces to accumulate but better then errors.
        dbsession.add(namespace)
        dbsession.flush()
    return namespace
