"""Unit and integration tests for LLM-based spam relevance checking.

Unit tests mock the HTTP call. Integration tests hit the real Hermes endpoint.
"""

import json
import unittest
from unittest.mock import patch, MagicMock

import pytest as _pytest

from remarkbox.models import spam_llm
from remarkbox.models.spam_llm import (
    check_thread_relevance,
    check_reply_relevance,
    _parse_verdict,
    _is_enabled,
    _llm_request,
    _discover_model,
    _choose_model,
    _post_chat,
    forget_discovered_model,
    health_check,
    DEFAULT_MODEL,
)


# ---------------------------------------------------------------------------
# Unit tests (mocked, no network)
# ---------------------------------------------------------------------------


class TestParseVerdict(unittest.TestCase):

    def test_relevant(self):
        relevant, explanation = _parse_verdict("RELEVANT\nThis is on topic.")
        self.assertTrue(relevant)
        self.assertEqual(explanation, "This is on topic.")

    def test_irrelevant(self):
        relevant, explanation = _parse_verdict("IRRELEVANT\nThis is spam.")
        self.assertFalse(relevant)
        self.assertEqual(explanation, "This is spam.")

    def test_relevant_no_explanation(self):
        relevant, explanation = _parse_verdict("RELEVANT")
        self.assertTrue(relevant)
        self.assertEqual(explanation, "")

    def test_irrelevant_no_explanation(self):
        relevant, explanation = _parse_verdict("IRRELEVANT")
        self.assertFalse(relevant)
        self.assertEqual(explanation, "")

    def test_none_response(self):
        relevant, explanation = _parse_verdict(None)
        self.assertIsNone(relevant)
        self.assertIsNone(explanation)

    def test_empty_response(self):
        relevant, explanation = _parse_verdict("")
        self.assertIsNone(relevant)
        self.assertIsNone(explanation)

    def test_ambiguous_response(self):
        relevant, explanation = _parse_verdict("I'm not sure about this.")
        self.assertIsNone(relevant)
        self.assertEqual(explanation, "I'm not sure about this.")

    def test_case_insensitive(self):
        relevant, _ = _parse_verdict("relevant\nYes it is.")
        self.assertTrue(relevant)

    def test_irrelevant_in_sentence(self):
        relevant, _ = _parse_verdict("IRRELEVANT - clearly spam\nPromo content.")
        self.assertFalse(relevant)


class TestIsEnabled(unittest.TestCase):

    def test_none_settings(self):
        self.assertFalse(_is_enabled(None))

    def test_missing_key(self):
        self.assertFalse(_is_enabled({}))

    def test_enabled_true(self):
        self.assertTrue(_is_enabled({"spam.llm.enabled": "true"}))

    def test_enabled_yes(self):
        self.assertTrue(_is_enabled({"spam.llm.enabled": "yes"}))

    def test_enabled_one(self):
        self.assertTrue(_is_enabled({"spam.llm.enabled": "1"}))

    def test_disabled_false(self):
        self.assertFalse(_is_enabled({"spam.llm.enabled": "false"}))

    def test_disabled_empty(self):
        self.assertFalse(_is_enabled({"spam.llm.enabled": ""}))


class TestCheckThreadRelevanceMocked(unittest.TestCase):

    def test_disabled_returns_none(self):
        relevant, explanation = check_thread_relevance(
            "example.com", None, "Hello", "World",
            settings={"spam.llm.enabled": "false"},
        )
        self.assertIsNone(relevant)
        self.assertIsNone(explanation)

    @patch("remarkbox.models.spam_llm._llm_request")
    def test_relevant_thread(self, mock_req):
        mock_req.return_value = "RELEVANT\nThe thread is about the site topic."
        relevant, explanation = check_thread_relevance(
            "cooking.example.com", "A cooking forum",
            "Best pasta recipe", "I love making pasta with fresh ingredients.",
            settings={"spam.llm.enabled": "true"},
        )
        self.assertTrue(relevant)
        mock_req.assert_called_once()

    @patch("remarkbox.models.spam_llm._llm_request")
    def test_irrelevant_thread(self, mock_req):
        mock_req.return_value = "IRRELEVANT\nThis is unrelated spam."
        relevant, explanation = check_thread_relevance(
            "cooking.example.com", "A cooking forum",
            "Buy cheap watches", "Best prices on luxury watches online!",
            settings={"spam.llm.enabled": "true"},
        )
        self.assertFalse(relevant)

    @patch("remarkbox.models.spam_llm._llm_request")
    def test_llm_failure_returns_none(self, mock_req):
        mock_req.return_value = None
        relevant, explanation = check_thread_relevance(
            "example.com", None, "Test", "Test",
            settings={"spam.llm.enabled": "true"},
        )
        self.assertIsNone(relevant)


class TestCheckReplyRelevanceMocked(unittest.TestCase):

    @patch("remarkbox.models.spam_llm._llm_request")
    def test_relevant_reply(self, mock_req):
        mock_req.return_value = "RELEVANT\nThe reply contributes to the discussion."
        relevant, explanation = check_reply_relevance(
            thread_title="Best pasta recipe",
            thread_content="I love making pasta.",
            parent_content="What kind of pasta do you use?",
            reply_content="I prefer fresh fettuccine.",
            settings={"spam.llm.enabled": "true"},
        )
        self.assertTrue(relevant)

    @patch("remarkbox.models.spam_llm._llm_request")
    def test_irrelevant_reply(self, mock_req):
        mock_req.return_value = "IRRELEVANT\nThis is promotional spam."
        relevant, explanation = check_reply_relevance(
            thread_title="Best pasta recipe",
            thread_content="I love making pasta.",
            parent_content="What kind of pasta do you use?",
            reply_content="Buy cheap watches at watches.com!",
            settings={"spam.llm.enabled": "true"},
        )
        self.assertFalse(relevant)

    @patch("remarkbox.models.spam_llm._llm_request")
    def test_reply_with_page_url(self, mock_req):
        """Embed mode: page_url and namespace_name are included in context."""
        mock_req.return_value = "RELEVANT\nOn topic for the page."
        relevant, explanation = check_reply_relevance(
            thread_title="How to bake bread",
            thread_content="A guide to baking.",
            parent_content=None,
            reply_content="Great guide, thanks!",
            page_url="https://cooking-blog.com/bread-guide",
            namespace_name="cooking-blog.com",
            settings={"spam.llm.enabled": "true"},
        )
        self.assertTrue(relevant)
        # Verify the LLM was called with context containing the page URL
        call_args = mock_req.call_args
        messages = call_args[0][2]  # third positional arg
        user_msg = messages[1]["content"]
        self.assertIn("cooking-blog.com", user_msg)
        self.assertIn("https://cooking-blog.com/bread-guide", user_msg)


# ---------------------------------------------------------------------------
# Integration tests (real Hermes endpoint)
# ---------------------------------------------------------------------------


HERMES_ENDPOINT = "https://hermes.ai.unturf.com/v1/chat/completions"
HERMES_MODELS_URI = "https://hermes.ai.unturf.com/v1/models"

HERMES_SETTINGS = {
    "spam.llm.enabled": "true",
    "spam.llm.endpoint": HERMES_ENDPOINT,
    "spam.llm.model": DEFAULT_MODEL,
    "spam.llm.timeout": "10",
}


@_pytest.mark.integration
class LiveEndpointTestCase(unittest.TestCase):
    """Base for tests that need a real inference endpoint.

    These are excluded from `make test` by the `integration` marker, because a
    deploy must not hinge on a third party being up: our whole pipeline once
    sat blocked behind a red suite that our own code had not broken. Run them
    deliberately with `make test-integration`.

    They also skip rather than fail when the endpoint is unreachable, so a
    local run without network still reports honestly.
    """

    @classmethod
    def setUpClass(cls):
        import urllib.request
        try:
            req = urllib.request.Request(HERMES_MODELS_URI, method="GET")
            urllib.request.urlopen(req, timeout=5)
            cls.hermes_available = True
        except Exception:
            cls.hermes_available = False

    def setUp(self):
        if not self.hermes_available:
            self.skipTest("Hermes endpoint not reachable")


class TestHermesIntegration(LiveEndpointTestCase):
    """Integration tests that hit the real Hermes LLM endpoint.

    These are not mocked -- they make real HTTP requests to hermes.ai.unturf.com.
    Skipped if the endpoint is unreachable.
    """

    def test_thread_relevant_to_namespace(self):
        relevant, explanation = check_thread_relevance(
            namespace_name="meta.remarkbox.com",
            namespace_description="Discussion about the Remarkbox commenting platform",
            title="Feature request: dark mode",
            content="It would be great if Remarkbox had a dark mode option for embedded comments.",
            settings=HERMES_SETTINGS,
        )
        self.assertTrue(relevant, "Expected relevant, got: {}".format(explanation))

    def test_thread_irrelevant_to_namespace(self):
        relevant, explanation = check_thread_relevance(
            namespace_name="meta.remarkbox.com",
            namespace_description="Discussion about the Remarkbox commenting platform",
            title="Best pizza in New York",
            content="Looking for recommendations for pizza places in Manhattan. I love thin crust.",
            settings=HERMES_SETTINGS,
        )
        self.assertFalse(relevant, "Expected irrelevant, got: {}".format(explanation))

    def test_reply_relevant_to_thread(self):
        relevant, explanation = check_reply_relevance(
            thread_title="How to install Remarkbox",
            thread_content="I'm trying to install Remarkbox on my server and need help with the configuration.",
            parent_content="Have you tried checking the documentation?",
            reply_content="Yes, I followed the docs but got stuck on the database setup step.",
            settings=HERMES_SETTINGS,
        )
        self.assertTrue(relevant, "Expected relevant, got: {}".format(explanation))

    def test_reply_spam_irrelevant(self):
        relevant, explanation = check_reply_relevance(
            thread_title="How to install Remarkbox",
            thread_content="I'm trying to install Remarkbox on my server.",
            parent_content="Have you tried checking the documentation?",
            reply_content="Buy cheap designer watches at www.fake-watches-sale.com! Best prices guaranteed!",
            settings=HERMES_SETTINGS,
        )
        self.assertFalse(relevant, "Expected irrelevant, got: {}".format(explanation))

    def test_reply_with_embed_page_context(self):
        """Test that embed mode page URL helps the LLM understand context."""
        relevant, explanation = check_reply_relevance(
            thread_title="Getting Started with Python",
            thread_content="",
            parent_content=None,
            reply_content="This tutorial helped me understand list comprehensions, thanks!",
            page_url="https://python-tutorial.example.com/getting-started",
            namespace_name="python-tutorial.example.com",
            settings=HERMES_SETTINGS,
        )
        self.assertTrue(relevant, "Expected relevant, got: {}".format(explanation))

    def test_raw_llm_request(self):
        """Verify we can make a raw request to Hermes and get a response."""
        response = _llm_request(
            endpoint="https://hermes.ai.unturf.com/v1/chat/completions",
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": "Reply with exactly the word PONG."},
                {"role": "user", "content": "PING"},
            ],
            timeout=10,
        )
        self.assertIsNotNone(response)
        self.assertIn("PONG", response.upper())

    def test_stale_model_heals_via_discovery(self):
        """A stale configured model 404s; _llm_request must discover the
        served model from /v1/models and retry instead of failing."""
        response = _llm_request(
            endpoint="https://hermes.ai.unturf.com/v1/chat/completions",
            model="stale-publisher/model-that-no-longer-exists",
            messages=[
                {"role": "system", "content": "Reply with exactly the word PONG."},
                {"role": "user", "content": "PING"},
            ],
            timeout=10,
        )
        self.assertIsNotNone(response)
        self.assertIn("PONG", response.upper())


class TestHermesEmbedMode(LiveEndpointTestCase):
    """Integration tests for embed mode with parent page context.

    In embed mode, threads represent comment sections on external pages.
    The LLM receives the parent page URL and namespace to understand what
    the page is about, even when the thread has minimal content.
    """

    def test_embed_relevant_comment_on_blog(self):
        """Comment that's relevant to a blog post page."""
        relevant, explanation = check_reply_relevance(
            thread_title="10 Tips for Growing Tomatoes in Small Spaces",
            thread_content="",  # embed threads often have no body
            parent_content=None,
            reply_content="Tip #3 about container size really helped me. "
                          "I switched to 5-gallon buckets and my cherry "
                          "tomatoes are thriving now.",
            page_url="https://gardening-blog.example.com/tomatoes-small-spaces",
            namespace_name="gardening-blog.example.com",
            settings=HERMES_SETTINGS,
        )
        self.assertTrue(relevant, "Expected relevant: {}".format(explanation))

    def test_embed_spam_comment_on_blog(self):
        """Obvious spam comment on a gardening blog post."""
        relevant, explanation = check_reply_relevance(
            thread_title="10 Tips for Growing Tomatoes in Small Spaces",
            thread_content="",
            parent_content=None,
            reply_content="Amazing deals on designer handbags! Visit "
                          "cheapbags.example.com for 90% off Louis Vuitton!",
            page_url="https://gardening-blog.example.com/tomatoes-small-spaces",
            namespace_name="gardening-blog.example.com",
            settings=HERMES_SETTINGS,
        )
        self.assertFalse(relevant, "Expected irrelevant: {}".format(explanation))

    def test_embed_crypto_spam_on_tech_blog(self):
        """Crypto spam on an unrelated tech article."""
        relevant, explanation = check_reply_relevance(
            thread_title="Understanding CSS Grid Layout",
            thread_content="A comprehensive guide to CSS Grid for modern web layouts.",
            parent_content=None,
            reply_content="I made $5000 in one week with this crypto trading bot! "
                          "Sign up at crypto-scam.example.com and start earning now!",
            page_url="https://webdev-tutorials.example.com/css-grid-guide",
            namespace_name="webdev-tutorials.example.com",
            settings=HERMES_SETTINGS,
        )
        self.assertFalse(relevant, "Expected irrelevant: {}".format(explanation))

    def test_embed_tangential_but_relevant_comment(self):
        """A comment that's loosely related to the page topic."""
        relevant, explanation = check_reply_relevance(
            thread_title="Python asyncio Tutorial",
            thread_content="",
            parent_content="I found the event loop explanation very clear.",
            reply_content="If you liked asyncio, you should also check out "
                          "trio which has a simpler API for structured concurrency.",
            page_url="https://python-guides.example.com/asyncio-tutorial",
            namespace_name="python-guides.example.com",
            settings=HERMES_SETTINGS,
        )
        self.assertTrue(relevant, "Expected relevant: {}".format(explanation))

    def test_embed_no_thread_content_only_page_url(self):
        """Embed thread with only a page URL, no title or content."""
        relevant, explanation = check_reply_relevance(
            thread_title=None,
            thread_content=None,
            parent_content=None,
            reply_content="This recipe is delicious! I added extra garlic.",
            page_url="https://recipes.example.com/garlic-bread",
            namespace_name="recipes.example.com",
            settings=HERMES_SETTINGS,
        )
        self.assertTrue(relevant, "Expected relevant: {}".format(explanation))


class TestHermesSiteMode(LiveEndpointTestCase):
    """Integration tests for site mode (standalone threads with full context).

    In site mode, threads have titles and content. The LLM checks whether
    new threads are relevant to the namespace and replies to the discussion.
    """

    def test_site_relevant_thread_on_forum(self):
        """Thread about Remarkbox features on meta.remarkbox.com."""
        relevant, explanation = check_thread_relevance(
            namespace_name="meta.remarkbox.com",
            namespace_description="Discussion about Remarkbox, the privacy-first comment system",
            title="Email notifications are delayed",
            content="I noticed that email notifications for new replies are taking "
                    "about 30 minutes to arrive. Is this expected or is something "
                    "wrong with the mail server? I'm using the hosted version at "
                    "my.remarkbox.com with the default settings.",
            settings=HERMES_SETTINGS,
        )
        self.assertTrue(relevant, "Expected relevant: {}".format(explanation))

    def test_site_irrelevant_thread_on_forum(self):
        """Completely unrelated thread on meta.remarkbox.com."""
        relevant, explanation = check_thread_relevance(
            namespace_name="meta.remarkbox.com",
            namespace_description="Discussion about Remarkbox, the privacy-first comment system",
            title="How to train for a marathon",
            content="I'm starting my marathon training plan and wondering about "
                    "the best shoes for long distance running. I currently run "
                    "about 20 miles per week and want to increase to 40.",
            settings=HERMES_SETTINGS,
        )
        self.assertFalse(relevant, "Expected irrelevant: {}".format(explanation))

    def test_site_reply_to_deep_thread(self):
        """Reply deep in a conversation thread, relevant to the discussion."""
        relevant, explanation = check_reply_relevance(
            thread_title="Custom CSS for embedded comments",
            thread_content="I want to customize the look of Remarkbox comments "
                           "on my website. The default styling clashes with my "
                           "dark theme. How can I override the default CSS?",
            parent_content="You can use the remarkbox-theme-meta approach. "
                           "Add a <meta> tag with name='remarkbox-css' and "
                           "point it to your custom stylesheet URL.",
            reply_content="Thanks! I added the meta tag and it works. One issue "
                          "though - the reply form textarea still uses the default "
                          "white background. Do I need a more specific selector?",
            namespace_name="meta.remarkbox.com",
            settings=HERMES_SETTINGS,
        )
        self.assertTrue(relevant, "Expected relevant: {}".format(explanation))

    def test_site_gibberish_reply(self):
        """Gibberish/nonsense reply to a legitimate thread."""
        relevant, explanation = check_reply_relevance(
            thread_title="Custom CSS for embedded comments",
            thread_content="I want to customize the look of Remarkbox comments "
                           "on my website.",
            parent_content="You can use remarkbox-theme-meta.",
            reply_content="asdf jkl; qwerty uiop zxcv bnm 12345 "
                          "hgfdsa poiuytrewq mnbvcxz",
            namespace_name="meta.remarkbox.com",
            settings=HERMES_SETTINGS,
        )
        self.assertFalse(relevant, "Expected irrelevant: {}".format(explanation))

    def test_site_thread_with_rich_namespace_description(self):
        """Namespace with a detailed description gives the LLM more context."""
        relevant, explanation = check_thread_relevance(
            namespace_name="recipes.cooking-community.example.com",
            namespace_description=(
                "A community for sharing and discussing recipes. "
                "Topics include baking, grilling, meal prep, international cuisine, "
                "dietary restrictions, and kitchen equipment reviews."
            ),
            title="Best cast iron skillet for beginners",
            content="I want to get my first cast iron skillet. I've been using "
                    "non-stick pans but want to try cast iron for better searing. "
                    "Budget is around $40. Any recommendations?",
            settings=HERMES_SETTINGS,
        )
        self.assertTrue(relevant, "Expected relevant: {}".format(explanation))

    def test_site_seo_spam_thread(self):
        """SEO spam disguised as a question."""
        relevant, explanation = check_thread_relevance(
            namespace_name="recipes.cooking-community.example.com",
            namespace_description="A community for sharing and discussing recipes.",
            title="Best SEO services for your website",
            content="Are you looking to rank #1 on Google? Our professional SEO "
                    "team can help you get more traffic and leads. Visit "
                    "seo-services.example.com for a free audit. We guarantee "
                    "first page rankings within 30 days or your money back!",
            settings=HERMES_SETTINGS,
        )
        self.assertFalse(relevant, "Expected irrelevant: {}".format(explanation))


class TestHermesEdgeCases(LiveEndpointTestCase):
    """Integration tests for edge cases and tricky content.

    Tests that exercise Hermes with content that might be ambiguous,
    minimal, or challenging to classify.
    """

    def test_short_agreement_reply(self):
        """Very short reply that just agrees -- should be relevant."""
        relevant, explanation = check_reply_relevance(
            thread_title="Should we add dark mode?",
            thread_content="I think Remarkbox needs a dark mode option.",
            parent_content="I agree, dark mode would be great.",
            reply_content="+1",
            namespace_name="meta.remarkbox.com",
            settings=HERMES_SETTINGS,
        )
        self.assertTrue(relevant, "Expected relevant: {}".format(explanation))

    def test_link_that_is_relevant(self):
        """A reply that's mostly a link but is relevant to the discussion."""
        relevant, explanation = check_reply_relevance(
            thread_title="Resources for learning Python",
            thread_content="Let's collect good resources for learning Python.",
            parent_content="I found the official tutorial helpful.",
            reply_content="Here's another great resource: "
                          "https://docs.python.org/3/tutorial/index.html",
            namespace_name="programming.example.com",
            settings=HERMES_SETTINGS,
        )
        self.assertTrue(relevant, "Expected relevant: {}".format(explanation))

    def test_promotional_but_relevant(self):
        """Self-promotion that is still on-topic for the namespace."""
        relevant, explanation = check_thread_relevance(
            namespace_name="meta.remarkbox.com",
            namespace_description="Discussion about the Remarkbox comment system",
            title="I built a Remarkbox plugin for WordPress",
            content="Hey everyone, I created a WordPress plugin that makes it "
                    "easy to embed Remarkbox comments. It handles the JavaScript "
                    "snippet injection and lets you configure settings from the "
                    "WP admin panel. Free and open source on GitHub.",
            settings=HERMES_SETTINGS,
        )
        self.assertTrue(relevant, "Expected relevant: {}".format(explanation))

    def test_different_language_spam(self):
        """Spam in a different language on an English namespace."""
        relevant, explanation = check_reply_relevance(
            thread_title="How to configure email notifications",
            thread_content="I want to set up email notifications for Remarkbox.",
            parent_content="Check the namespace settings panel.",
            reply_content="Compre relogios baratos! Melhor preco garantido! "
                          "Visite nossa loja online: relogios-baratos.example.com",
            namespace_name="meta.remarkbox.com",
            settings=HERMES_SETTINGS,
        )
        self.assertFalse(relevant, "Expected irrelevant: {}".format(explanation))


# ---------------------------------------------------------------------------
# Unit tests for model discovery and reasoning suppression (mocked, no network)
# ---------------------------------------------------------------------------


class TestModelDiscoveryAndThinking(unittest.TestCase):
    """Upstream owns the model id, and reasoning is off on every request."""

    ENDPOINT = "https://llm.example.com/v1/chat/completions"

    def setUp(self):
        forget_discovered_model()

    def tearDown(self):
        forget_discovered_model()

    def test_served_model_overrides_configured_model(self):
        """The id from /v1/models wins over the configured fallback."""
        with patch("remarkbox.models.spam_llm._discover_model") as discover, \
                patch("remarkbox.models.spam_llm._post_chat") as post:
            discover.return_value = "vendor/actually-served"
            post.return_value = "RELEVANT\nfine"
            _llm_request(self.ENDPOINT, "stale/configured", [], 5)

        self.assertEqual(post.call_args[0][1], "vendor/actually-served")

    def test_configured_model_used_when_discovery_fails(self):
        """A dead /v1/models falls back to settings instead of giving up."""
        with patch("remarkbox.models.spam_llm._discover_model") as discover, \
                patch("remarkbox.models.spam_llm._post_chat") as post:
            discover.return_value = None
            post.return_value = "RELEVANT\nfine"
            _llm_request(self.ENDPOINT, "stale/configured", [], 5)

        self.assertEqual(post.call_args[0][1], "stale/configured")

    def test_discovery_result_is_cached(self):
        """We do not re-ask /v1/models on every classification."""
        payload = json.dumps({"data": [{"id": "vendor/served"}]}).encode("utf-8")
        with patch("remarkbox.models.spam_llm.urllib.request.urlopen") as urlopen:
            urlopen.return_value = MagicMock(
                read=MagicMock(return_value=payload)
            )
            first = _discover_model(self.ENDPOINT, 5)
            second = _discover_model(self.ENDPOINT, 5)

        self.assertEqual(first, "vendor/served")
        self.assertEqual(second, "vendor/served")
        self.assertEqual(urlopen.call_count, 1)

    def test_request_body_disables_thinking(self):
        """Every chat completion asks the server to skip its monologue."""
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return MagicMock(read=MagicMock(return_value=json.dumps({
                "choices": [{"message": {"content": "RELEVANT\nfine"}}]
            }).encode("utf-8")))

        with patch("remarkbox.models.spam_llm.urllib.request.urlopen", fake_urlopen):
            _post_chat(self.ENDPOINT, "vendor/served", [], 5)

        body = captured["body"]
        self.assertEqual(
            body["chat_template_kwargs"], {"enable_thinking": False}
        )
        self.assertEqual(body["reasoning_effort"], "none")
        self.assertEqual(body["temperature"], 0.0)


class TestChooseModel(unittest.TestCase):
    """Which served id we classify with, when a server offers several."""

    def test_none_served(self):
        self.assertIsNone(_choose_model([], "vendor/configured"))

    def test_single_served_wins(self):
        self.assertEqual(_choose_model(["vendor/only"], "vendor/stale"), "vendor/only")

    def test_configured_preferred_when_served(self):
        """Operator intent wins whenever upstream actually offers it."""
        served = ["vendor/reasoning", "vendor/configured", "vendor/other"]
        self.assertEqual(
            _choose_model(served, "vendor/configured"), "vendor/configured"
        )

    def test_ambiguous_choice_is_deterministic(self):
        """Several served, none configured: same answer regardless of order."""
        served = ["vendor/zeta", "vendor/alpha", "vendor/mid"]
        first = _choose_model(served, "vendor/absent")
        second = _choose_model(list(reversed(served)), "vendor/absent")
        self.assertEqual(first, second)
        self.assertEqual(first, "vendor/alpha")

    def test_ambiguous_choice_warns(self):
        """An arbitrary pick must not happen quietly."""
        with self.assertLogs("remarkbox.models.spam_llm", level="WARNING") as logs:
            _choose_model(["vendor/b", "vendor/a"], "vendor/absent")
        self.assertTrue(any("none match configured" in m for m in logs.output))


class TestSilentDegradationIsLogged(unittest.TestCase):
    """An inert relevance check must leave a trace."""

    def test_unparseable_verdict_warns(self):
        with self.assertLogs("remarkbox.models.spam_llm", level="WARNING") as logs:
            relevant, _ = _parse_verdict("Here's a thinking process:\nStep 1...")
        self.assertIsNone(relevant)
        self.assertTrue(any("unparseable" in m for m in logs.output))

    def test_clean_verdict_does_not_warn(self):
        with patch.object(spam_llm.log, "warning") as warn:
            relevant, _ = _parse_verdict("RELEVANT\nOn topic.")
        self.assertTrue(relevant)
        warn.assert_not_called()


class TestHealthCheck(unittest.TestCase):
    """The health check has to be able to go red, or it is decoration."""

    SETTINGS = {
        "spam.llm.enabled": "true",
        "spam.llm.endpoint": "https://llm.example.com/v1/chat/completions",
        "spam.llm.model": "vendor/configured",
        "spam.llm.timeout": "5",
    }

    def tearDown(self):
        forget_discovered_model()

    def test_healthy(self):
        with patch("remarkbox.models.spam_llm._discover_model") as discover, \
                patch("remarkbox.models.spam_llm._llm_request") as req:
            discover.return_value = "vendor/served"
            req.return_value = "RELEVANT\nOn topic."
            result = health_check(self.SETTINGS)

        self.assertTrue(result["ok"])
        self.assertEqual(result["model"], "vendor/served")

    def test_discovery_failure_is_not_ok(self):
        with patch("remarkbox.models.spam_llm._discover_model") as discover:
            discover.return_value = None
            result = health_check(self.SETTINGS)

        self.assertFalse(result["ok"])
        self.assertIn("discovery failed", result["detail"])

    def test_no_response_is_not_ok(self):
        with patch("remarkbox.models.spam_llm._discover_model") as discover, \
                patch("remarkbox.models.spam_llm._llm_request") as req:
            discover.return_value = "vendor/served"
            req.return_value = None
            result = health_check(self.SETTINGS)

        self.assertFalse(result["ok"])

    def test_thinking_preamble_is_caught(self):
        """The exact regression that went unnoticed must now report red."""
        with patch("remarkbox.models.spam_llm._discover_model") as discover, \
                patch("remarkbox.models.spam_llm._llm_request") as req:
            discover.return_value = "vendor/reasoning"
            req.return_value = "Here's a thinking process:\n1. Consider..."
            result = health_check(self.SETTINGS)

        self.assertFalse(result["ok"])
        self.assertIn("unparseable", result["detail"])


# Keep this module's tests together on one xdist worker. Test modules share a
# per-worker database; when --dist=loadgroup deals unmarked tests out
# individually, classes from different modules interleave on a worker and one
# class's tearDownClass drop_all yanks tables from another class mid-run.
pytestmark = _pytest.mark.xdist_group("test_spam_llm")
