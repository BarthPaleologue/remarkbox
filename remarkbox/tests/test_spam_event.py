"""Tests for spam decision telemetry.

The defect these guard against: a rejected post is never written as a node,
so before this table our blocked spam left no trace and nobody could tell
whether the filter had ever caught anything.
"""

import unittest

from remarkbox.models.spam_event import (
    SpamEvent,
    record_spam_event,
    spam_event_summary,
    ACTION_ALLOWED,
    ACTION_HELD,
    ACTION_REJECTED,
    SOURCE_API,
    SOURCE_BROWSER,
)
from remarkbox.models.meta import now_timestamp


class TestSpamEventModel(unittest.TestCase):
    """Construction and field handling, no database required."""

    def test_defaults(self):
        event = SpamEvent(action=ACTION_REJECTED)
        self.assertEqual(event.action, ACTION_REJECTED)
        self.assertEqual(event.source, SOURCE_API)
        self.assertFalse(event.llm_ran)
        self.assertIsNone(event.llm_verdict)
        self.assertIsNotNone(event.id)
        self.assertIsNotNone(event.created_timestamp)

    def test_records_which_model_answered(self):
        """A model swapped in under us must be visible in the record."""
        event = SpamEvent(
            action=ACTION_HELD, llm_ran=True, llm_verdict=False,
            llm_model="vendor/some-reasoning-model",
        )
        self.assertEqual(event.llm_model, "vendor/some-reasoning-model")
        self.assertIs(event.llm_verdict, False)

    def test_browser_source_is_representable(self):
        """Coverage gaps should show up as data, not need code archaeology."""
        event = SpamEvent(action=ACTION_ALLOWED, source=SOURCE_BROWSER)
        self.assertEqual(event.source, SOURCE_BROWSER)


class TestRecordSpamEvent(unittest.TestCase):
    """record_spam_event must never be able to break posting."""

    class _Session:
        def __init__(self):
            self.added = []

        def add(self, obj):
            self.added.append(obj)

    def test_writes_event(self):
        session = self._Session()
        event = record_spam_event(
            session, action=ACTION_REJECTED, spam_score=0.9,
            signals=["link_density", "llm_irrelevant"],
        )
        self.assertIsNotNone(event)
        self.assertEqual(len(session.added), 1)
        self.assertEqual(session.added[0].action, ACTION_REJECTED)

    def test_signals_are_joined(self):
        session = self._Session()
        event = record_spam_event(
            session, action=ACTION_HELD, signals=["a", "b", "c"],
        )
        self.assertEqual(event.signals, "a,b,c")

    def test_no_signals_is_none(self):
        session = self._Session()
        event = record_spam_event(session, action=ACTION_ALLOWED, signals=[])
        self.assertIsNone(event.signals)

    def test_long_signals_are_truncated(self):
        """A pathological signal list must not blow the column."""
        session = self._Session()
        event = record_spam_event(
            session, action=ACTION_HELD, signals=["x" * 100] * 20,
        )
        self.assertLessEqual(len(event.signals), 512)

    def test_failure_is_swallowed(self):
        """Telemetry must never reject a legitimate comment."""
        class Exploding:
            def add(self, obj):
                raise RuntimeError("database on fire")

        result = record_spam_event(Exploding(), action=ACTION_ALLOWED)
        self.assertIsNone(result)


class TestSpamEventSummary(unittest.TestCase):
    """Summary counts, over a fake query so no database is needed."""

    class _Query:
        def __init__(self, events):
            self._events = events

        def filter(self, *args, **kwargs):
            return self

        def __iter__(self):
            return iter(self._events)

    class _Session:
        def __init__(self, events):
            self._events = events

        def query(self, model):
            return TestSpamEventSummary._Query(self._events)

    def _event(self, action, llm_ran=False, verdict=None, model=None):
        return SpamEvent(
            action=action, llm_ran=llm_ran, llm_verdict=verdict, llm_model=model,
        )

    def test_counts_by_action(self):
        events = [
            self._event(ACTION_ALLOWED),
            self._event(ACTION_HELD),
            self._event(ACTION_REJECTED),
            self._event(ACTION_REJECTED),
        ]
        summary = spam_event_summary(self._Session(events))
        self.assertEqual(summary["total"], 4)
        self.assertEqual(summary["allowed"], 1)
        self.assertEqual(summary["held"], 1)
        self.assertEqual(summary["rejected"], 2)

    def test_counts_llm_participation(self):
        events = [
            self._event(ACTION_REJECTED, llm_ran=True, verdict=False, model="m1"),
            self._event(ACTION_ALLOWED, llm_ran=True, verdict=True, model="m1"),
            self._event(ACTION_ALLOWED, llm_ran=False),
        ]
        summary = spam_event_summary(self._Session(events))
        self.assertEqual(summary["llm_ran"], 2)
        self.assertEqual(summary["llm_irrelevant"], 1)
        self.assertEqual(summary["models"], {"m1": 2})

    def test_inconclusive_verdicts_are_visible(self):
        """The silent-degradation signature must be countable."""
        events = [
            self._event(ACTION_ALLOWED, llm_ran=True, verdict=None, model="reasoner"),
            self._event(ACTION_ALLOWED, llm_ran=True, verdict=None, model="reasoner"),
        ]
        summary = spam_event_summary(self._Session(events))
        self.assertEqual(summary["llm_ran"], 2)
        self.assertEqual(summary["llm_inconclusive"], 2)
        self.assertEqual(summary["llm_irrelevant"], 0)


import pytest as _pytest

pytestmark = _pytest.mark.xdist_group("test_spam_event")
