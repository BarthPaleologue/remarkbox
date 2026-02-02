"""Unit tests for spam scoring module."""

import unittest
from unittest.mock import MagicMock, patch

from remarkbox.models.spam import (
    score_content,
    _link_density,
    _link_count,
    _content_hash,
)


class TestLinkDensity(unittest.TestCase):

    def test_no_links(self):
        self.assertEqual(_link_density("Hello world"), 0.0)

    def test_all_links(self):
        text = "https://example.com"
        density = _link_density(text)
        self.assertAlmostEqual(density, 1.0)

    def test_mixed_content(self):
        text = "Check out https://example.com for more info"
        density = _link_density(text)
        self.assertGreater(density, 0.0)
        self.assertLess(density, 1.0)

    def test_empty_string(self):
        self.assertEqual(_link_density(""), 0.0)

    def test_none(self):
        self.assertEqual(_link_density(None), 0.0)


class TestLinkCount(unittest.TestCase):

    def test_no_links(self):
        self.assertEqual(_link_count("Hello world"), 0)

    def test_multiple_links(self):
        text = "Visit https://a.com and https://b.com and https://c.com"
        self.assertEqual(_link_count(text), 3)

    def test_empty(self):
        self.assertEqual(_link_count(""), 0)


class TestContentHash(unittest.TestCase):

    def test_same_content(self):
        self.assertEqual(_content_hash("hello"), _content_hash("hello"))

    def test_different_content(self):
        self.assertNotEqual(_content_hash("hello"), _content_hash("world"))

    def test_whitespace_normalization(self):
        self.assertEqual(
            _content_hash("hello  world"),
            _content_hash("hello world"),
        )

    def test_case_normalization(self):
        self.assertEqual(_content_hash("HELLO"), _content_hash("hello"))


class TestScoreContent(unittest.TestCase):

    def test_clean_content_scores_zero(self):
        score, signals = score_content("This is a normal discussion post.")
        self.assertEqual(score, 0.0)
        self.assertEqual(signals, [])

    def test_empty_content(self):
        score, signals = score_content("")
        self.assertEqual(score, 0.0)

    def test_high_link_density(self):
        text = "https://spam1.com https://spam2.com https://spam3.com"
        score, signals = score_content(text)
        self.assertGreater(score, 0.0)
        self.assertTrue(any("link_density" in s for s in signals))

    def test_many_links(self):
        text = "Visit " + " ".join(
            "https://site{}.com".format(i) for i in range(10)
        )
        score, signals = score_content(text)
        self.assertTrue(any("link_count" in s for s in signals))

    def test_spam_pattern_single(self):
        text = "You should buy now before the sale ends!"
        score, signals = score_content(text)
        self.assertGreater(score, 0.0)
        self.assertTrue(any("spam_patterns" in s for s in signals))

    def test_spam_pattern_multiple(self):
        text = "Buy now! Click here to get a free trial. Act now! Limited time offer!"
        score, signals = score_content(text)
        self.assertGreaterEqual(score, 0.5)

    def test_duplicate_content(self):
        # First post is fine
        score1, signals1 = score_content(
            "Duplicate test post xyz123",
            ip_address="10.99.99.99",
        )
        # Second identical post from same IP triggers duplicate
        score2, signals2 = score_content(
            "Duplicate test post xyz123",
            ip_address="10.99.99.99",
        )
        self.assertTrue(any("duplicate_content" in s for s in signals2))

    def test_score_capped_at_one(self):
        # Content with every signal firing should not exceed 1.0
        text = (
            "Buy now! Click here to free trial! Act now! "
            + " ".join("https://spam{}.com".format(i) for i in range(20))
        )
        score, signals = score_content(text)
        self.assertLessEqual(score, 1.0)

    def test_short_content_from_new_user(self):
        import time
        user = MagicMock()
        user.id = "test-short"
        user.created = int(time.time() * 1000) - 1000  # 1 second old
        user.nodes.count.return_value = 0
        score, signals = score_content("Hi", user=user)
        self.assertTrue(any("very_short_content" in s for s in signals))
