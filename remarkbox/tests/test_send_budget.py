"""First-contact send budget (lib/send_budget.py): allowance math, queue
ordering & the drain, against a real SQLite auth schema."""
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from remarkbox.lib import send_budget
from remarkbox.lib.send_budget import CONVERSION_WINDOW_MS, SPEND_WINDOW_MS
from remarkbox.models.meta import Base as AuthBase
from remarkbox.models.send_budget import SendLedger, SendQueue
from remarkbox import models  # noqa: F401  (registers every mapper)
from remarkbox.models.meta import now_timestamp

SETTINGS = {"app.send_budget.floor": "2", "app.send_budget.per_conversion": "3"}


class BudgetCase(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://")
        AuthBase.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

    def tearDown(self):
        self.db.close()

    def _ledger(self, kind, age_ms=0):
        row = SendLedger(kind, "login")
        row.created_timestamp = now_timestamp() - age_ms
        self.db.add(row)
        self.db.flush()

    def _queue(self, email, priority=0, age_ms=0):
        row = send_budget.enqueue(self.db, email, "login", "x.test", priority=priority)
        row.created_timestamp -= age_ms
        self.db.flush()
        return row


class TestAllowance(BudgetCase):
    def test_floor_without_conversions(self):
        self.assertEqual(send_budget.allowance(self.db, SETTINGS), 2)

    def test_each_recent_conversion_adds(self):
        self._ledger("conversion")
        self._ledger("conversion", age_ms=CONVERSION_WINDOW_MS - 60_000)
        self.assertEqual(send_budget.allowance(self.db, SETTINGS), 2 + 2 * 3)

    def test_old_conversion_expires(self):
        self._ledger("conversion", age_ms=CONVERSION_WINDOW_MS + 60_000)
        self.assertEqual(send_budget.allowance(self.db, SETTINGS), 2)

    def test_spend_rolls_over_24h(self):
        self._ledger("send")
        self._ledger("send", age_ms=SPEND_WINDOW_MS + 60_000)
        self.assertEqual(send_budget.spent(self.db), 1)

    def test_defaults_when_unset_or_garbage(self):
        self.assertEqual(send_budget.allowance(self.db, {}), 20)
        self.assertEqual(
            send_budget.allowance(self.db, {"app.send_budget.floor": "x"}), 20
        )


class TestTrySpend(BudgetCase):
    def test_spends_until_exhausted(self):
        self.assertTrue(send_budget.try_spend(self.db, SETTINGS, "login"))
        self.assertTrue(send_budget.try_spend(self.db, SETTINGS, "login"))
        self.assertFalse(send_budget.try_spend(self.db, SETTINGS, "login"))

    def test_waits_behind_queue_even_with_budget(self):
        self._queue("a@example.com")
        self.assertFalse(send_budget.try_spend(self.db, SETTINGS, "login"))

    def test_conversion_reopens(self):
        send_budget.try_spend(self.db, SETTINGS, "login")
        send_budget.try_spend(self.db, SETTINGS, "login")
        send_budget.record_conversion(self.db, "login")
        self.assertTrue(send_budget.try_spend(self.db, SETTINGS, "login"))


class TestQueue(BudgetCase):
    def test_one_row_per_address_priority_only_rises(self):
        self._queue("a@example.com", priority=1)
        self._queue("a@example.com", priority=0)
        rows = self.db.query(SendQueue).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].priority, 1)

    def test_drain_order_priority_then_age_within_budget(self):
        self._queue("old-plain@example.com", age_ms=5000)
        self._queue("new-pow@example.com", priority=1)
        self._queue("new-plain@example.com")
        order = []
        sent = send_budget.drain(
            self.db, SETTINGS, lambda row: order.append(row.email) or True
        )
        self.assertEqual(sent, 2)
        self.assertEqual(order, ["new-pow@example.com", "old-plain@example.com"])
        self.assertEqual(
            [r.email for r in self.db.query(SendQueue)], ["new-plain@example.com"]
        )

    def test_dropped_row_costs_no_budget(self):
        self._queue("verified-meanwhile@example.com")
        self._queue("b@example.com", age_ms=-1000)
        sent = send_budget.drain(
            self.db, SETTINGS, lambda row: row.email == "b@example.com"
        )
        self.assertEqual(sent, 1)
        self.assertEqual(send_budget.spent(self.db), 1)
        self.assertEqual(self.db.query(SendQueue).count(), 0)

    def test_expired_rows_never_send(self):
        row = self._queue("late@example.com")
        row.expires_timestamp = now_timestamp() - 1
        self.db.flush()
        self.assertEqual(send_budget.drain(self.db, SETTINGS, lambda r: True), 0)
        self.assertEqual(self.db.query(SendQueue).count(), 0)

    def test_ledger_pruned_past_conversion_window(self):
        self._ledger("send", age_ms=CONVERSION_WINDOW_MS + 60_000)
        send_budget.prune(self.db)
        self.assertEqual(self.db.query(SendLedger).count(), 0)


class TestSmsGateway(unittest.TestCase):
    def test_match_is_exact_domain_case_insensitive(self):
        self.assertTrue(send_budget.is_sms_gateway("5555550123@TMOMAIL.net"))
        self.assertFalse(send_budget.is_sms_gateway("me@nottmomail.net"))
