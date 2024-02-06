from collections import (
    OrderedDict,
    deque,
)

from sqlalchemy import (
    BigInteger, Boolean, Column, Integer, Unicode, UnicodeText, or_, func
)

from sqlalchemy.orm import relationship, backref

import uuid

from slugify import slugify

from remarkbox.lib import (
    timestamp_to_datetime,
    timestamp_to_ago_string,
    timestamp_to_date_string,
)

from remarkbox.lib.render import markdown_to_html

from .meta import Base, RBase
from .meta import UUIDType
from .meta import now_timestamp, foreign_key, get_object_by_id

from .uri import get_or_create_uri

from .event import NodeEvent

import codecs

import logging

try:
    unicode("")
except:
    from six import u as unicode

log = logging.getLogger(__name__)


class Node(RBase, Base):
    """
    Node class acts like a linked list to support nested:

        Question -> Answers -> Comments

        Thread -> Posts -> Remarks

    The `parent_id` column is only used by children nodes.

    The class will allow 3 layer nesting like StackOverflow or unlimited
    nesting like reddit.  The frontend code determines the particular
    nesting strategy.

    For more information checkout this section of the SQLAlchemy Docs:

    http://docs.sqlalchemy.org/en/latest/orm/relationships.html#adjacency-list-relationships
    """

    id = Column(UUIDType, primary_key=True, index=True)
    root_id = Column(UUIDType, index=True, default=None)
    parent_id = Column(UUIDType, foreign_key("Node", "id"), default=None)
    namespace_id = Column(UUIDType, foreign_key("Namespace", "id"), default=None)
    user_id = Column(UUIDType, foreign_key("User", "id"), default=None)
    user_surrogate_id = Column(
        UUIDType, foreign_key("UserSurrogate", "id"), default=None
    )
    title = Column(Unicode(256), default=None)
    data = Column(UnicodeText, default=None)
    data_html = Column(UnicodeText, default=None)
    # the depth of this node in the thread's graph / tree.
    graph_depth = Column(Integer, nullable=False, default=-1)
    # TODO: someday this should be renamed to created_timestamp
    created = Column(BigInteger, nullable=False)
    # TODO: someday this should be renamed to changed_timestamp
    changed = Column(BigInteger, nullable=False)
    disabled_timestamp = Column(BigInteger)
    disabled = Column(Boolean, default=False)
    verified = Column(Boolean, default=False)
    # a locked thread (root node) prevents new commenting.
    locked = Column(Boolean, default=False)
    # by default comments are approved. unless Namespace hide_unless_approved.
    approved = Column(Boolean, default=True)
    # is there a related Uri model to this node?
    has_uri = Column(Boolean, default=False, nullable=False)
    ip_address = Column(Unicode(45), default=None)

    # lazy='joined' performs a left join to reduce queries, it's magic.
    user = relationship(argument="User", lazy="joined")

    # lazy='joined' performs a left join to reduce queries, it's magic.
    user_surrogate = relationship(argument="UserSurrogate", lazy="joined")

    # lazy='dynamic' returns a query object instead of collection.
    # Reference: http://docs.sqlalchemy.org/en/latest/orm/collections.html
    children = relationship(
        argument="Node",
        lazy="dynamic",
        order_by="Node.created",
        foreign_keys=[parent_id],
        backref=backref("parent", remote_side=[id]),
    )

    # lazy='dynamic' returns a query object instead of collection.
    # Reference: http://docs.sqlalchemy.org/en/latest/orm/collections.html
    children_desc = relationship(
        argument="Node",
        lazy="dynamic",
        order_by="desc(Node.created)",
        foreign_keys=[parent_id],
    )

    votes = relationship(argument="Vote", backref="node", order_by="desc(Vote.created)")

    # set uselist to false to create one-to-one relationship.
    uri = relationship(argument="Uri", uselist=False, back_populates="node")

    # set uselist to false to create one-to-one relationship.
    namespace = relationship(argument="Namespace", uselist=False)

    # lazy='joined' performs a left join to reduce queries, it's magic.
    # this is used for denormalized stats like counts, etc.
    cache = relationship(
        argument="NodeCache", lazy="joined", back_populates="node", uselist=False
    )

    watchers = relationship(argument="Watcher", lazy="dynamic", back_populates="node")

    events = relationship(argument="NodeEvent", lazy="dynamic", back_populates="node")

    def __init__(self):
        self.id = uuid.uuid1()
        self.created = now_timestamp()
        self.changed = self.created

    def get_children(self, order_by="asc"):
        if order_by == "desc":
            return self.children_desc
        return self.children

    @property
    def verified_children(self):
        return self.children.filter(Node.verified == True)

    @property
    def unverified_children(self):
        return self.children.filter(Node.verified == False)

    @property
    def path_to_root(self):
        """The path from this node to the root node."""
        # TODO: memoize this result? how / when to deal with cache busting?
        node = self
        path_to_root = []
        path_to_root.append(node)
        while node.parent is not None:
            node = node.parent
            path_to_root.append(node)
        return path_to_root

    @property
    def path_from_root(self):
        """The path from the root node to this node."""
        return list(reversed(self.path_to_root))

    @property
    def root2(self):
        """The origin or top most parent node without a parent."""
        if self.is_root:
            return self
        return self.path_to_root[-1]

    @property
    def root(self):
        """The origin or top most parent node without a parent."""
        if self.is_root:
            return self
        return self.dbsession.query(Node).filter(Node.id == self.root_id).one()

    @property
    def is_root(self):
        if not self.parent_id or not self.root_id or self.root_id == self.id:
            return True
        return False

    def recompute_depth(self):
        """recompute the depth of a node in the thread."""
        self.graph_depth = len(self.path_to_root) - 1

    @property
    def depth(self):
        if self.graph_depth == -1:
            self.recompute_depth()
        return self.graph_depth

    @property
    def stats(self):
        """The denormalized stats for this node."""
        from .node_cache import NodeCache

        if self.cache is None:
            self.cache = NodeCache(self.id)
        return self.cache.stats

    def score(self):
        # this doesn't actually exist right now. I removed voting from this
        # iteration of the codebase. maybe worth adding in at some point.
        return sum([vote.value for vote in self.votes])

    def children_order_by_score(self):
        # TODO: this should be optimized, we should craft a query and have
        # database to return results in the expected order instead of multiple
        # queries.  First we select children then we sort by selecting each
        # vote for each child and sum the result.
        return sorted(self.children, key=lambda x: x.score(), reverse=True)

    def new_child(self):
        """create and return new child node of this node, in memory"""
        child = Node()
        child.parent = self
        child.root_id = self.root_id
        return child

    def new_event(self, user, action):
        """create and return new node_event for this node, in memory"""
        event = NodeEvent(node=self, user=user, action=action)
        self.events.append(event)
        return event

    def avatar_uri(self, **kwargs):
        """Return invatar URI. Optionally return gravatar URI."""
        u = self.user if self.user else self.user_surrogate
        if self.disabled:
            kwargs["text"] = "-"
            kwargs["bg"] = "#aaaaaa"
        if self.disabled or not self.verified:
            return u.svgtar(**kwargs)
        return u.avatar_uri(**kwargs)

    @property
    def created_timestamp(self):
        return self.created

    @property
    def human_created_timestamp(self):
        return timestamp_to_ago_string(self.created)

    # TODO: take into account user's timezone?
    @property
    def created_date(self):
        return timestamp_to_date_string(self.created)

    # TODO: take into account user's timezone?
    @property
    def created_datetime(self):
        return timestamp_to_datetime(self.created)

    @property
    def changed_timestamp(self):
        return self.changed

    @property
    def human_changed_timestamp(self):
        return timestamp_to_ago_string(self.changed)

    # TODO: take into account user's timezone?
    @property
    def changed_date(self):
        return timestamp_to_date_string(self.changed)

    # TODO: take into account user's timezone?
    @property
    def changed_datetime(self):
        return timestamp_to_datetime(self.changed)

    @property
    def title_ascii(self):
        """return the ascii version of the title, ignoring errors or None."""
        if self.title:
            return self.title.encode('ascii', 'ignore')

    @property
    def slug(self):
        """return slug from title or empty string"""
        if self.title:
            return slugify(self.title)
        return ""

    @property
    def path(self):
        """return a node's path part of uri"""
        if self.slug:
            return "/{}/{}".format(self.id, self.slug)
        else:
            return "/{}".format(self.id)

    @property
    def short_id(self):
        """return the base64 representation of UUID: 36 -> 22 unicode chars"""
        base_64_id = codecs.encode(self.id.bytes, "base64")
        base_64_id = base_64_id.rstrip(b"=\n").replace(b"/", b"_").replace(b"+", b"-")
        return base_64_id.decode("utf-8")

    @property
    def was_edited(self):
        return not self.created == self.changed

    @property
    def enabled(self):
        return not self.disabled

    def set_data(self, data, namespace=None):
        if namespace is None:
            namespace = self.root.namespace
        self.data = data
        self.data_html = markdown_to_html(data, namespace)

    def _invalidate_cache(self):
        if self.root.cache:
            self.root.cache.invalidate()

    def edit(self, data):
        """edit node."""
        self.set_data(data)
        self.changed = now_timestamp()
        self._invalidate_cache()

    def disable(self):
        """disable node."""
        self.disabled = True
        self.disabled_timestamp = now_timestamp()
        self._invalidate_cache()

    def enable(self):
        """enable node."""
        self.disabled = False
        self.disabled_timestamp = None
        self._invalidate_cache()

    def verify(self):
        """verify node."""
        self.verified = True
        self._invalidate_cache()

    def unverify(self):
        """unverify node."""
        self.verified = False
        self._invalidate_cache()

    def approve(self):
        """verify node."""
        self.approved = True
        self._invalidate_cache()

    def deny(self):
        """unverify node."""
        self.approved = False
        self._invalidate_cache()

    def visible(self):
        if self.disabled:
            return False
        return True

    def is_owner(self, user):
        """Return True if given user owns this node, else False."""
        if user and user.authenticated and user == self.user:
            return True
        return False


def get_node_by_id(dbsession, node_id):
    """Try to get Node object by id or return None."""
    return get_object_by_id(dbsession, node_id, Node)


def get_node_by_uri(dbsession, node_uri):
    return get_or_create_uri(dbsession, node_uri).node


def create_root_node():
    node = Node()
    node.root_id = node.id
    node.graph_depth = 0
    return node


def get_or_create_node_by_uri(dbsession, node_uri, node_title=None):
    """Try to get Node object by uri or return new Node"""
    uri = get_or_create_uri(dbsession, node_uri)

    if uri.node is None:
        # create new root node for external page (embed).

        # imported here to prevent circular import.
        from .namespace import get_or_create_namespace

        uri.node = create_root_node()
        uri.node.verified = True
        uri.node.has_uri = True
        uri.node.title = node_title
        uri.node.namespace = get_or_create_namespace(dbsession, uri.parsed.hostname)

    elif node_title:
        # if the external page title has changed, update our database.
        if node_title != uri.node.title:
            uri.node.title = node_title
            dbsession.add(uri.node)
            dbsession.flush()

    return uri.node


def get_topsecret_roots(dbsession):
    """Return all verified parent nodes by descending created order."""
    return (
        dbsession.query(Node)
        .filter(Node.parent_id == None, Node.verified == True, Node.disabled == False)
        .order_by(Node.changed.desc())
    )


def get_topsecret_nodes(dbsession, limit=100, offset=0):
    """Return all nodes by descending created order."""
    return (
        dbsession.query(Node)
        .filter(Node.disabled == False, Node.user_id != None)
        .order_by(Node.changed.desc())
        .limit(limit)
        .offset(offset)
    )


def get_root_nodes(dbsession):
    """Return a list of all root nodes (nodes without a parent.)"""
    return (
        dbsession.query(Node)
        .filter(Node.parent_id == None)
        .order_by(Node.changed.desc())
    )


def get_root_nodes_by_keywords(dbsession, keywords, namespace=None):

    # make dictionary mapping of root_node_ids to accumulated scores
    root_scores = {}

    # make dictionary mapping of root_node_ids to root_node_objects
    root_nodes = {}

    # a list of matched node objects.
    nodes = []

    if namespace:
        node_query = namespace.visible_nodes
    else:
        node_query = get_nodes_who_share_roots_query(
            dbsession, get_topsecret_roots(dbsession)
        )

    for keyword in keywords:

        # extend nodes, with a list of nodes which match this keyword. 
        keyword_filter = Node.data.ilike("%{}%".format(keyword))
        nodes.extend(node_query.filter(keyword_filter).all())

    # accumulate scores and root node objects.
    for node in nodes:
        if node.root.id not in root_scores:
            root_scores[node.root.id] = 0
        root_scores[node.root.id] += 1

        if node.root.id not in root_nodes:
            root_nodes[node.root.id] = node.root

    # sort the scores dictionary by value (score),
    # but get the key (object id),
    # reversed (highest score first)
    sorted_root_ids = sorted(root_scores, key=root_scores.get, reverse=True)

    # return root node objects in sorted order by score.
    return [root_nodes[root_id] for root_id in sorted_root_ids]


def get_nodes_who_share_roots_query(dbsession, root_nodes):
    # a giant n "or" query, where n is the number of root_nodes.
    if root_nodes.count() == 0:
        # return a "null" query object. still hits database...
        # this allows us to pass around the query object.
        from sqlalchemy.sql import text
        return dbsession.query(Node).filter(text("0 == 1"))
    return dbsession.query(Node).filter(or_(Node.root_id == n.id for n in root_nodes))


def get_nodes_who_share_roots(dbsession, root_nodes):
    return get_nodes_who_share_roots_query(dbsession, root_nodes).all()


def get_nodes_who_share_root(dbsession, root_node, order="oldest-first"):
    nodes = dbsession.query(Node).filter(Node.root_id == root_node.id)
    if order == "oldest-first":
        nodes = nodes.order_by(Node.created)
    elif order == "newest-first":
        nodes = nodes.order_by(Node.created.desc())
    return nodes


def get_node_count_who_share_root(dbsession, root_node):
    return (
        dbsession.query(func.count("id"))
        .select_from(Node)
        .filter(Node.root_id == root_node.id)
        .scalar()
    )


def get_visible_node_count_who_share_root(dbsession, root_node):
    return (
        dbsession.query(func.count("id"))
        .select_from(Node)
        .filter(
            Node.root_id == root_node.id, Node.disabled == False, Node.approved == True
        )
        .scalar()
    )


def get_node_id_map(nodes):
    """return a dictionary of all nodes who share this root."""
    node_id_map = {}
    for node in nodes:
        node_id_map[node.id] = node
    return node_id_map


def get_graph_from_nodes(nodes):
    """infinite nested graph or tree of nodes."""
    graph = OrderedDict()

    # create all node keys in graph.
    for node in nodes:
        graph[node.id] = []

    for node in nodes:
        if node.parent is not None:
            graph[node.parent.id].append(node.id)

    return graph


def get_group_conversation_ids(nodes):
    """Return a list of node ids whose parent is root."""
    if len(list(nodes)) == 0:
        return []
    root = nodes[0].root
    return [node.id for node in nodes if node.parent and node.parent.id == root.id]


# Reference post:
# http://kmkeen.com/python-trees/2010-09-18-08-55-50-039.html
# strategy queue.
def flatten_graph(node_id, graph, include_given_node_id=False):
    """
    Given a node_id and graph (or tree),
    return a list of every descendant node_id, depth first order.
    """
    flat_graph = []

    to_crawl = deque([node_id])

    while to_crawl:
        current_id = to_crawl.pop()

        flat_graph.append(current_id)

        children_ids = graph[current_id]

        # reverse so that we extend the queue in the expected order.
        children_ids.reverse()

        to_crawl.extend(children_ids)

    if include_given_node_id:
        return flat_graph
    return flat_graph[1:]


def get_conversation_graph_from_nodes(nodes, graph=None, node_id_map=None, order="oldest-first"):
    """
    Given a list of nodes, return a grouped conversation graph which is a
    dictionary of ids where the keys are the top level conversation node ids
    and the values are a list of all decendant node ids.

    If you already have it computed, you may optionally provide an existing
    graph (dictionary tree of node ids), and/or an existing node_id_map.
    """
    def get_timestamp(node_id):
        return node_id_map[node_id].created

    if graph is None:
        graph = get_graph_from_nodes(nodes)

    if node_id_map is None:
        node_id_map = get_node_id_map(nodes)

    _reverse = False
    if order == "newest-first":
        _reverse = True

    convo_graph = OrderedDict()

    convo_ids = sorted(
        get_group_conversation_ids(nodes),
        key=get_timestamp,
        reverse=_reverse
    )

    for convo_node_id in convo_ids:
        descendant_ids = flatten_graph(
            convo_node_id,
            graph,
        )
        # sort by timestamp, oldest first.
        convo_graph[convo_node_id] = sorted(
            descendant_ids,
            key=get_timestamp,
        )

    return convo_graph


def recompute_depth_on_all_node_objects(dbsession, chunk_lenth=500):
    """Only use this if a many nodes were moved and/or re-nested."""

    #
    # WARNING, this could take a long time and be computationally expensive
    #          both on the host running it, and the database, respectively.
    #

    import math

    log.info("loading and querying nodes...")

    node_count = dbsession.query(Node).count()

    nodes = dbsession.query(Node).all()

    log.info("node_count={}".format(node_count))

    for i, node in enumerate(nodes):

        # this is the computationally intense part.
        node.recompute_depth()
        dbsession.add(node)

        if i % chunk_lenth == 0:
            progress = int(math.floor((i / float(node_count)) * 100))
            log.info(
                "Flushing chunk={}/{}, chunk_lenth={} progress={}%".format(
                    i, node_count, chunk_lenth, progress
                )
            )
            dbsession.flush()

    # one final flush to database for the last partial chunk.
    log.info(
        "Flushing chunk={}/{}, chunk_lenth={} progress={}%".format(
            i + 1, node_count, chunk_lenth, 100
        )
    )
    dbsession.flush()
