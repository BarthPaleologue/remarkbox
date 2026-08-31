"""A durable record of every spam decision we make.

We could not answer "is our spam filter catching anything?" because the
evidence was thrown away. `check_spam` runs before a node exists, and a
rejected post returns immediately, so blocked attacks were never written
anywhere. Held and allowed posts kept their score on the node, which means
our only records were of spam we let through.

This records the decision itself rather than the content. Rejections are the
whole point: they are what a filter is for, and they were invisible.

We deliberately do not store IP addresses or post bodies. This table exists
to answer "is the filter working", which needs counts, scores and verdicts,
not the text someone typed or where they sat. A moderation log should not
quietly become a surveillance log.
"""

from sqlalchemy import Boolean, Column, Float, ForeignKey, Index, Unicode, BigInteger
from sqlalchemy.orm import relationship
from sqlalchemy_utils import UUIDType

from uuid import uuid1

from .meta import Base, RBase, now_timestamp


# What we decided to do with a post.
ACTION_ALLOWED = "allowed"
ACTION_HELD = "held"
ACTION_REJECTED = "rejected"

# Where the post came from, so a gap in coverage is visible as a gap in data
# rather than having to be inferred from reading our views.
SOURCE_API = "api"
SOURCE_BROWSER = "browser"


class SpamEvent(RBase, Base):
    """One spam decision: what we scored, what we did, and who answered."""

    __tablename__ = "rb_spam_event"

    id = Column(UUIDType(binary=False), primary_key=True, index=True)
    created_timestamp = Column(BigInteger, nullable=False, index=True)

    namespace_id = Column(
        UUIDType(binary=False),
        ForeignKey("rb_namespace.id"),
        nullable=True,
        index=True,
    )
    # Null for anonymous posts; we keep the link so a moderator can see a
    # pattern from one account, and so GDPR erasure can find these rows.
    user_id = Column(
        UUIDType(binary=False), ForeignKey("rb_user.id"), nullable=True, index=True
    )

    action = Column(Unicode(16), nullable=False, index=True)
    source = Column(Unicode(16), nullable=False, default=SOURCE_API)
    spam_score = Column(Float, nullable=True)
    # Comma-joined signal names from score_content, e.g. "link_density,
    # llm_irrelevant". Free text because our signal set changes over time.
    signals = Column(Unicode(512), nullable=True)

    # Did our relevance check actually run, and what did it say? `llm_ran`
    # false with the feature enabled means the endpoint failed us, which is
    # exactly the silent degradation we could not see before.
    llm_ran = Column(Boolean, nullable=False, default=False)
    # True relevant, False irrelevant, None inconclusive.
    llm_verdict = Column(Boolean, nullable=True)
    # Which model answered. A swap under us is what started all of this.
    llm_model = Column(Unicode(128), nullable=True)

    namespace = relationship("Namespace", backref="spam_events")
    user = relationship("User", backref="spam_events")

    def __init__(self, action, namespace=None, user=None, source=SOURCE_API,
                 spam_score=None, signals=None, llm_ran=False,
                 llm_verdict=None, llm_model=None):
        self.id = uuid1()
        self.created_timestamp = now_timestamp()
        self.action = action
        self.source = source
        self.spam_score = spam_score
        self.signals = signals
        self.llm_ran = llm_ran
        self.llm_verdict = llm_verdict
        self.llm_model = llm_model
        if namespace is not None:
            self.namespace = namespace
        if user is not None:
            self.user = user


# Our common question is "what happened in this namespace lately", so index
# the pair rather than making the database sort a namespace's whole history.
Index(
    "ix_rb_spam_event_namespace_created",
    SpamEvent.namespace_id,
    SpamEvent.created_timestamp,
)


def record_spam_event(dbsession, action, namespace=None, user=None,
                      source=SOURCE_API, spam_score=None, signals=None,
                      llm_ran=False, llm_verdict=None, llm_model=None):
    """Write one decision. Never raises: telemetry must not break posting.

    A metrics table that can reject a legitimate comment is worse than no
    metrics table, so a failure here is logged and swallowed.
    """
    import logging

    log = logging.getLogger(__name__)
    try:
        event = SpamEvent(
            action=action,
            namespace=namespace,
            user=user,
            source=source,
            spam_score=spam_score,
            signals=",".join(signals)[:512] if signals else None,
            llm_ran=llm_ran,
            llm_verdict=llm_verdict,
            llm_model=llm_model,
        )
        dbsession.add(event)
        return event
    except Exception as e:
        log.warning("failed to record spam event: %s", e)
        return None


def spam_event_summary(dbsession, namespace=None, days=7):
    """Counts by action over a window, plus how our relevance check fared."""
    from sqlalchemy import func

    since = now_timestamp() - (days * 86400)
    query = dbsession.query(SpamEvent).filter(
        SpamEvent.created_timestamp >= since
    )
    if namespace is not None:
        query = query.filter(SpamEvent.namespace_id == namespace.id)

    summary = {
        "days": days,
        "total": 0,
        "allowed": 0,
        "held": 0,
        "rejected": 0,
        "llm_ran": 0,
        "llm_irrelevant": 0,
        "llm_inconclusive": 0,
        "models": {},
    }

    for event in query:
        summary["total"] += 1
        if event.action in (ACTION_ALLOWED, ACTION_HELD, ACTION_REJECTED):
            summary[event.action] += 1
        if event.llm_ran:
            summary["llm_ran"] += 1
            if event.llm_verdict is False:
                summary["llm_irrelevant"] += 1
            elif event.llm_verdict is None:
                summary["llm_inconclusive"] += 1
            if event.llm_model:
                summary["models"][event.llm_model] = (
                    summary["models"].get(event.llm_model, 0) + 1
                )

    return summary
