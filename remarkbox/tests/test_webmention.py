"""
Tests for T7: Webmentions / IndieWeb support.

Covers:
  - Unit tests for the Webmention model
  - API tests for the webmention endpoints (both /webmention and /api/v1/webmention)
  - Validation of source/target parameters
  - Integration with URI lookup for finding threads
  - Mocked HTTP fetches for source verification
  - Author extraction and content snippet extraction
"""

import transaction
import unittest
import uuid
import webtest

from unittest import mock
from unittest.mock import patch, MagicMock

from remarkbox.models import (
    Node,
    get_tm_session,
    get_or_create_user_by_email,
    get_user_by_email,
    get_or_create_namespace,
)
from remarkbox.models.meta import Base, now_timestamp
from remarkbox.models.webmention import (
    Webmention,
    get_webmention_by_id,
    get_webmention_by_source_and_target,
    get_verified_webmentions_for_node,
)
from remarkbox.models.uri import Uri, get_uri_by_uri

from pyramid.paster import get_appsettings


# ---------------------------------------------------------------------------
# Unit tests -- no database, no app.
# ---------------------------------------------------------------------------


class TestWebmentionModel(unittest.TestCase):
    """Unit tests for the Webmention SQLAlchemy model."""

    def test_init_sets_source_and_target(self):
        wm = Webmention(
            source="https://example.com/post",
            target="https://my.remarkbox.com/thread",
        )
        self.assertEqual(wm.source, "https://example.com/post")
        self.assertEqual(wm.target, "https://my.remarkbox.com/thread")

    def test_init_defaults_verified_false(self):
        wm = Webmention(
            source="https://example.com/post",
            target="https://my.remarkbox.com/thread",
        )
        self.assertFalse(wm.verified)

    def test_init_sets_timestamps(self):
        wm = Webmention(
            source="https://example.com/post",
            target="https://my.remarkbox.com/thread",
        )
        self.assertIsNotNone(wm.created_timestamp)
        self.assertIsNotNone(wm.updated_timestamp)
        self.assertGreater(wm.created_timestamp, 0)

    def test_init_generates_uuid(self):
        wm = Webmention(
            source="https://example.com/post",
            target="https://my.remarkbox.com/thread",
        )
        self.assertIsNotNone(wm.id)
        self.assertIsInstance(wm.id, uuid.UUID)

    def test_mark_verified_sets_verified(self):
        wm = Webmention(
            source="https://example.com/post",
            target="https://my.remarkbox.com/thread",
        )
        old_timestamp = wm.updated_timestamp
        wm.mark_verified()
        self.assertTrue(wm.verified)
        self.assertGreaterEqual(wm.updated_timestamp, old_timestamp)

    def test_mark_verified_with_author(self):
        wm = Webmention(
            source="https://example.com/post",
            target="https://my.remarkbox.com/thread",
        )
        wm.mark_verified(
            author_name="Jane Doe",
            author_url="https://janedoe.example.com",
            content="Here is a snippet of the content.",
        )
        self.assertTrue(wm.verified)
        self.assertEqual(wm.author_name, "Jane Doe")
        self.assertEqual(wm.author_url, "https://janedoe.example.com")
        self.assertEqual(wm.content, "Here is a snippet of the content.")

    def test_mark_verified_truncates_long_content(self):
        wm = Webmention(
            source="https://example.com/post",
            target="https://my.remarkbox.com/thread",
        )
        long_content = "x" * 1000
        wm.mark_verified(content=long_content)
        self.assertEqual(len(wm.content), 500)

    def test_mark_verified_no_author(self):
        """mark_verified without author fields leaves them as None."""
        wm = Webmention(
            source="https://example.com/post",
            target="https://my.remarkbox.com/thread",
        )
        wm.mark_verified()
        self.assertIsNone(wm.author_name)
        self.assertIsNone(wm.author_url)
        self.assertIsNone(wm.content)

    def test_node_id_default_none(self):
        wm = Webmention(
            source="https://example.com/post",
            target="https://my.remarkbox.com/thread",
        )
        self.assertIsNone(wm.node_id)


# ---------------------------------------------------------------------------
# Helper extraction function tests.
# ---------------------------------------------------------------------------


class TestWebmentionHelpers(unittest.TestCase):
    """Test the helper functions in remarkbox.views.webmention."""

    def test_is_valid_url_http(self):
        from remarkbox.views.webmention import _is_valid_url

        self.assertTrue(_is_valid_url("http://example.com"))
        self.assertTrue(_is_valid_url("https://example.com"))
        self.assertFalse(_is_valid_url("ftp://example.com"))
        self.assertFalse(_is_valid_url(""))
        self.assertFalse(_is_valid_url(None))

    def test_extract_author_with_hcard(self):
        from remarkbox.views.webmention import _extract_author

        html = """
        <div class="h-card">
            <a class="p-name u-url" href="https://janedoe.example.com">Jane Doe</a>
        </div>
        """
        name, url = _extract_author(html)
        self.assertEqual(name, "Jane Doe")
        self.assertEqual(url, "https://janedoe.example.com")

    def test_extract_author_no_hcard(self):
        from remarkbox.views.webmention import _extract_author

        html = "<html><body><p>No h-card here.</p></body></html>"
        name, url = _extract_author(html)
        self.assertIsNone(name)
        self.assertIsNone(url)

    def test_extract_content_snippet(self):
        from remarkbox.views.webmention import _extract_content_snippet

        html = '<p>Check out this great article at <a href="https://target.com/thread">target link</a> for more info.</p>'
        snippet = _extract_content_snippet(html, "https://target.com/thread")
        self.assertIsNotNone(snippet)
        self.assertIn("target", snippet.lower())

    def test_extract_content_snippet_no_match(self):
        from remarkbox.views.webmention import _extract_content_snippet

        html = "<p>Nothing here.</p>"
        snippet = _extract_content_snippet(html, "https://notfound.com")
        self.assertIsNone(snippet)


# ---------------------------------------------------------------------------
# Functional / API tests -- require running app.
# All webmention functional tests are in one class to avoid DB teardown issues.
# ---------------------------------------------------------------------------


class TestWebmentionEndpoint(unittest.TestCase, object):
    """
    Test the POST /webmention and /api/v1/webmention endpoints.
    Also tests query helpers with live database.
    """

    @classmethod
    def setUpClass(cls):
        from remarkbox import main

        cls.settings = get_appsettings("test.ini")
        cls.app = main({}, **cls.settings)
        cls.testapp = webtest.TestApp(cls.app)

        cls.session_factory = cls.app.registry["dbsession_factory"]
        cls.engine = cls.session_factory.kw["bind"]
        Base.metadata.create_all(bind=cls.engine)

        cls.tm = transaction.manager
        cls.dbsession = get_tm_session(cls.session_factory, cls.tm)

    @classmethod
    def tearDownClass(cls):
        cls.dbsession.close()

    def setUp(self):
        """Create a namespace, user, and a thread with a URI so webmentions can resolve."""
        from remarkbox.models import create_root_node

        # Ensure we have a clean transaction state.
        try:
            self.dbsession.rollback()
        except Exception:
            pass

        self.test_user = get_or_create_user_by_email(
            self.dbsession, "wm-test@remarkbox.com"
        )
        self.dbsession.add(self.test_user)

        self.ns = get_or_create_namespace(self.dbsession, "wm-test.example.com")
        self.dbsession.add(self.ns)

        self.root = create_root_node()
        self.root.namespace = self.ns
        self.root.user = self.test_user
        self.root.verified = True
        self.root.title = "Webmention Thread"
        self.root.set_data("Content for the webmention test thread")
        self.dbsession.add(self.root)
        self.dbsession.flush()

        # Create a URI mapping so the webmention endpoint can find the thread.
        self.target_url = "https://wm-test.example.com/my-post"
        self.uri = Uri(data=self.target_url)
        self.uri.node = self.root
        self.dbsession.add(self.uri)
        self.dbsession.flush()

        self.root_id = self.root.id
        self.ns_id = self.ns.id

        self.tm.commit()

    def tearDown(self):
        self.testapp.get("/log-out")
        try:
            # Clean up webmentions.
            self.dbsession.query(Webmention).filter(
                Webmention.node_id == self.root_id,
            ).delete(synchronize_session=False)
            # Clean up URI.
            self.dbsession.query(Uri).filter(
                Uri.data == self.target_url
            ).delete(synchronize_session=False)
            # Clean up nodes.
            self.dbsession.query(Node).filter(
                Node.id == self.root_id
            ).delete(synchronize_session=False)
            user = get_user_by_email(self.dbsession, "wm-test@remarkbox.com")
            if user:
                self.dbsession.delete(user)
            self.dbsession.flush()
            self.tm.commit()
        except Exception:
            self.tm.abort()
            self.tm.begin()

    # -----------------------------------------------------------------------
    # Validation tests (POST /webmention).
    # -----------------------------------------------------------------------

    def test_missing_source_returns_400(self):
        """POST with missing source parameter returns 400."""
        res = self.testapp.post_json(
            "/webmention",
            {"target": self.target_url},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 400)
        self.assertIn("source", res.json["error"])

    def test_missing_target_returns_400(self):
        """POST with missing target parameter returns 400."""
        res = self.testapp.post_json(
            "/webmention",
            {"source": "https://example.com/post"},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 400)
        self.assertIn("source", res.json["error"])

    def test_missing_both_returns_400(self):
        """POST with no parameters returns 400."""
        res = self.testapp.post_json(
            "/webmention",
            {},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 400)

    def test_invalid_source_url_returns_400(self):
        """POST with non-HTTP source URL returns 400."""
        res = self.testapp.post_json(
            "/webmention",
            {"source": "ftp://example.com/post", "target": self.target_url},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 400)
        self.assertIn("source", res.json["error"])

    def test_invalid_target_url_returns_400(self):
        """POST with non-HTTP target URL returns 400."""
        res = self.testapp.post_json(
            "/webmention",
            {"source": "https://example.com/post", "target": "ftp://example.com/x"},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 400)
        self.assertIn("target", res.json["error"])

    def test_source_equals_target_returns_400(self):
        """POST where source == target returns 400."""
        res = self.testapp.post_json(
            "/webmention",
            {"source": self.target_url, "target": self.target_url},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 400)
        self.assertIn("different", res.json["error"])

    def test_target_not_matching_thread_returns_400(self):
        """POST with target URL that does not match any Remarkbox thread returns 400."""
        res = self.testapp.post_json(
            "/webmention",
            {
                "source": "https://example.com/post",
                "target": "https://nonexistent.example.com/no-thread",
            },
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 400)
        self.assertIn("does not match", res.json["error"])

    # -----------------------------------------------------------------------
    # Source fetch / verification tests.
    # -----------------------------------------------------------------------

    @patch("remarkbox.views.webmention._fetch_source")
    def test_unreachable_source_returns_400(self, mock_fetch):
        """Source URL that cannot be fetched returns 400."""
        mock_fetch.return_value = None
        res = self.testapp.post_json(
            "/webmention",
            {
                "source": "https://example.com/unreachable",
                "target": self.target_url,
            },
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 400)
        self.assertIn("Could not fetch", res.json["error"])

    @patch("remarkbox.views.webmention._fetch_source")
    def test_source_without_link_to_target_returns_400(self, mock_fetch):
        """Source HTML that does not contain the target URL returns 400."""
        mock_fetch.return_value = "<html><body>No link here.</body></html>"
        res = self.testapp.post_json(
            "/webmention",
            {
                "source": "https://example.com/post",
                "target": self.target_url,
            },
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 400)
        self.assertIn("does not contain", res.json["error"])

    # -----------------------------------------------------------------------
    # Successful webmention flow.
    # -----------------------------------------------------------------------

    @patch("remarkbox.views.webmention._fetch_source")
    def test_valid_webmention_accepted(self, mock_fetch):
        """Valid webmention with source linking to target is accepted (202)."""
        html = '<html><body><a href="{}">Link</a></body></html>'.format(
            self.target_url
        )
        mock_fetch.return_value = html
        res = self.testapp.post_json(
            "/webmention",
            {
                "source": "https://example.com/valid-post",
                "target": self.target_url,
            },
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 202)
        self.assertEqual(res.json["status"], "accepted")
        self.assertIn("id", res.json)

    @patch("remarkbox.views.webmention._fetch_source")
    def test_valid_webmention_stores_verified(self, mock_fetch):
        """Valid webmention is stored as verified in the database."""
        html = '<html><body><a href="{}">Link</a></body></html>'.format(
            self.target_url
        )
        mock_fetch.return_value = html
        res = self.testapp.post_json(
            "/webmention",
            {
                "source": "https://example.com/store-test",
                "target": self.target_url,
            },
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 202)

        wm = get_webmention_by_source_and_target(
            self.dbsession, "https://example.com/store-test", self.target_url
        )
        self.assertIsNotNone(wm)
        self.assertTrue(wm.verified)
        self.assertEqual(wm.node_id, self.root_id)

    @patch("remarkbox.views.webmention._fetch_source")
    def test_duplicate_webmention_updates(self, mock_fetch):
        """Sending the same webmention twice updates the existing one (200)."""
        html = '<html><body><a href="{}">Link</a></body></html>'.format(
            self.target_url
        )
        mock_fetch.return_value = html

        source = "https://example.com/dupe-post"
        res1 = self.testapp.post_json(
            "/webmention",
            {"source": source, "target": self.target_url},
            expect_errors=True,
        )
        self.assertEqual(res1.status_int, 202)
        first_id = res1.json["id"]

        # Second send should update, not create a new one.
        res2 = self.testapp.post_json(
            "/webmention",
            {"source": source, "target": self.target_url},
            expect_errors=True,
        )
        self.assertEqual(res2.status_int, 200)
        self.assertEqual(res2.json["status"], "updated")
        self.assertEqual(res2.json["id"], first_id)

    @patch("remarkbox.views.webmention._fetch_source")
    def test_webmention_extracts_author(self, mock_fetch):
        """Webmention extracts h-card author info from source HTML."""
        html = '''
        <html><body>
        <div class="h-card">
            <a class="p-name u-url" href="https://author.example.com">Test Author</a>
        </div>
        <a href="{}">Link to thread</a>
        </body></html>
        '''.format(self.target_url)
        mock_fetch.return_value = html

        res = self.testapp.post_json(
            "/webmention",
            {
                "source": "https://example.com/author-test",
                "target": self.target_url,
            },
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 202)

        wm = get_webmention_by_source_and_target(
            self.dbsession, "https://example.com/author-test", self.target_url
        )
        self.assertIsNotNone(wm)
        self.assertEqual(wm.author_name, "Test Author")
        self.assertEqual(wm.author_url, "https://author.example.com")

    @patch("remarkbox.views.webmention._fetch_source")
    def test_form_encoded_webmention(self, mock_fetch):
        """Webmention endpoint also accepts form-encoded POST."""
        html = '<html><body><a href="{}">Link</a></body></html>'.format(
            self.target_url
        )
        mock_fetch.return_value = html
        res = self.testapp.post(
            "/webmention",
            {
                "source": "https://example.com/form-post",
                "target": self.target_url,
            },
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 202)
        self.assertEqual(res.json_body["status"], "accepted")

    # -----------------------------------------------------------------------
    # /api/v1/webmention alias tests.
    # -----------------------------------------------------------------------

    @patch("remarkbox.views.webmention._fetch_source")
    def test_api_webmention_accepted(self, mock_fetch):
        """POST /api/v1/webmention with valid data returns 202."""
        html = '<html><body><a href="{}">Link</a></body></html>'.format(
            self.target_url
        )
        mock_fetch.return_value = html
        res = self.testapp.post_json(
            "/api/v1/webmention",
            {
                "source": "https://example.com/api-wm-post",
                "target": self.target_url,
            },
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 202)
        self.assertEqual(res.json["status"], "accepted")

    def test_api_webmention_missing_params(self):
        """POST /api/v1/webmention with missing params returns 400."""
        res = self.testapp.post_json(
            "/api/v1/webmention",
            {},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 400)

    @patch("remarkbox.views.webmention._fetch_source")
    def test_api_webmention_source_no_link(self, mock_fetch):
        """POST /api/v1/webmention where source does not link to target."""
        mock_fetch.return_value = "<html><body>No link here</body></html>"
        res = self.testapp.post_json(
            "/api/v1/webmention",
            {
                "source": "https://example.com/nolink",
                "target": self.target_url,
            },
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 400)
        self.assertIn("does not contain", res.json["error"])

    # -----------------------------------------------------------------------
    # Query helper integration tests.
    # -----------------------------------------------------------------------

    @patch("remarkbox.views.webmention._fetch_source")
    def test_get_verified_webmentions_for_node(self, mock_fetch):
        """get_verified_webmentions_for_node returns only verified webmentions."""
        html = '<html><body><a href="{}">Link</a></body></html>'.format(
            self.target_url
        )
        mock_fetch.return_value = html

        self.testapp.post_json(
            "/webmention",
            {
                "source": "https://example.com/query-test",
                "target": self.target_url,
            },
            expect_errors=True,
        )

        verified = get_verified_webmentions_for_node(self.dbsession, self.root_id)
        self.assertGreaterEqual(len(verified), 1)
        for wm in verified:
            self.assertTrue(wm.verified)

    def test_get_verified_webmentions_empty_for_nonexistent_node(self):
        """get_verified_webmentions_for_node returns empty for non-existent node."""
        fake_id = uuid.uuid1()
        verified = get_verified_webmentions_for_node(self.dbsession, fake_id)
        self.assertEqual(len(verified), 0)

    @patch("remarkbox.views.webmention._fetch_source")
    def test_get_webmention_by_source_and_target(self, mock_fetch):
        """get_webmention_by_source_and_target finds an existing webmention."""
        html = '<html><body><a href="{}">Link</a></body></html>'.format(
            self.target_url
        )
        mock_fetch.return_value = html

        self.testapp.post_json(
            "/webmention",
            {
                "source": "https://example.com/lookup-test",
                "target": self.target_url,
            },
            expect_errors=True,
        )

        wm = get_webmention_by_source_and_target(
            self.dbsession,
            "https://example.com/lookup-test",
            self.target_url,
        )
        self.assertIsNotNone(wm)
        self.assertTrue(wm.verified)

    def test_get_webmention_by_source_and_target_not_found(self):
        """get_webmention_by_source_and_target returns None for non-existent pair."""
        wm = get_webmention_by_source_and_target(
            self.dbsession,
            "https://nonexistent.example.com/post",
            "https://nonexistent.example.com/thread",
        )
        self.assertIsNone(wm)

# Keep this module's tests together on one xdist worker. Test modules share a
# per-worker database; when --dist=loadgroup deals unmarked tests out
# individually, classes from different modules interleave on a worker and one
# class's tearDownClass drop_all yanks tables from another class mid-run.
import pytest as _pytest

pytestmark = _pytest.mark.xdist_group("test_webmention")
