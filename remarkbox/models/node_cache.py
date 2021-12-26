from sqlalchemy import BigInteger, Boolean, Column, UnicodeText

from sqlalchemy.orm import relationship, backref

import uuid

from .meta import Base, RBase
from .meta import UUIDType
from .meta import now_timestamp, foreign_key

import json

from .node import get_node_count_who_share_root, get_visible_node_count_who_share_root


class NodeCache(RBase, Base):
    """
    The NodeCache class duplicates and denormalizes results of intensive
    queries, like full table scans, into a lookup table indexed by the node_id.

    You can think of this table and class as a cache for statistics.

    Always invalidate before writing to the underlying normalized relations.
    """

    id = Column(UUIDType, primary_key=True, index=True)
    node_id = Column(UUIDType, foreign_key("Node", "id"), index=True, default=None)
    valid = Column(Boolean, default=False)
    updated_timestamp = Column(BigInteger, nullable=False)
    # Statistics stored as JSON in the database.
    json_stats = Column(UnicodeText, default=None)

    # lazy='joined' performs a left join and reduces amount of queries
    #  from N different users to 1. It's magic.
    node = relationship(
        argument="Node",
        lazy="joined",
        back_populates="cache",
        uselist=False,
        foreign_keys=[node_id],
    )

    def __init__(self, node_id):
        self.id = uuid.uuid1()
        self.node_id = node_id
        self.updated_timestamp = now_timestamp()

    def _recompute_stats(self, new_stats=None):
        # todo: this might make recomputations automatic / easier.
        # https://sqlalchemy-utils.readthedocs.io/en/latest/aggregates.html
        if new_stats is None:
            new_stats = {}
            if self.node.is_root:
                new_stats["root"] = {}
                # don't consider the root node itself in the counts, so minus 1.
                new_stats["root"]["count"] = (
                    get_node_count_who_share_root(self.dbsession, self.node) - 1
                )
                new_stats["root"]["visible_count"] = (
                    get_visible_node_count_who_share_root(self.dbsession, self.node) - 1
                )

        self.valid = True
        self.json_stats = json.dumps(new_stats)
        self.updated_timestamp = now_timestamp()

    def invalidate(self):
        """invalidate stats to force a full recomputation on next read request."""
        self.valid = False
        self.updated_timestamp = now_timestamp()

    @property
    def stats(self):
        if not self.valid:
            self._recompute_stats()
        return json.loads(self.json_stats)

    @stats.setter
    def stats(self, new_stats):
        self._recompute_stats(new_stats)


def invalidate_all_node_cache_objects(dbsession):
    """Only use this if you change the NodeCache stats JSON schema."""
    dbsession.query(NodeCache).update(
        {"valid": False, "updated_timestamp": now_timestamp()}
    )
    dbsession.flush()
