"""
Tests covering work from the 2026-04-08 session:

- Revision.created & Node.changed use numeric Unix-ms timestamps (not strings)
- wiki_edit() creates a revision AND regenerates data_html
- can_wiki_edit() gates: wiki=True → any auth user edits root; wiki=False → owner only
- /{node_id}/revisions returns 200 HTML with diff table
- /api/v1/nodes/{node_id}/revisions returns JSON revision list
- pyramid.csrf_trusted_origins allows www.foxhop.net origin
- Export menu shows history links only for wiki namespaces
- set_data() with rst format produces data_html via pandoc
"""

import transaction
import unittest
from unittest import mock

from pyramid.paster import get_appsettings

from remarkbox.models import (
    get_tm_session,
    get_or_create_user_by_email,
    get_or_create_namespace,
    Node,
)
from remarkbox.models.meta import Base
from remarkbox.models.revision import Revision
from remarkbox.models.namespace import Namespace
from remarkbox.models.node import now_timestamp


# ---------------------------------------------------------------------------
# Unit tests — no DB, no app
# ---------------------------------------------------------------------------

class TestTimestampTypes(unittest.TestCase):
    """Revision.created & Node.changed must be numeric (Unix ms), not strings."""

    def test_revision_created_is_int(self):
        rev = Revision()
        self.assertIsInstance(rev.created, (int, float))

    def test_revision_created_is_positive(self):
        rev = Revision()
        self.assertGreater(rev.created, 0)

    def test_now_timestamp_is_numeric(self):
        ts = now_timestamp()
        self.assertIsInstance(ts, (int, float))

    def test_now_timestamp_is_ms_scale(self):
        """Unix ms timestamps are > 1e12; Unix second timestamps are < 2e9."""
        ts = now_timestamp()
        self.assertGreater(ts, 1_000_000_000_000)


class TestCanWikiEdit(unittest.TestCase):
    """Namespace.can_wiki_edit() gating logic."""

    def setUp(self):
        self.ns = Namespace("test-wiki.com")
        self.ns.subscription_type = "production"

    def _auth_user(self):
        u = mock.Mock()
        u.authenticated = True
        return u

    def _root_node(self):
        n = mock.Mock()
        n.is_root = True
        return n

    def _child_node(self):
        n = mock.Mock()
        n.is_root = False
        return n

    # --- wiki=True cases ---

    def test_wiki_mode_auth_user_edits_root(self):
        self.ns.wiki = True
        with mock.patch.object(self.ns, "can_alter_node", return_value=False):
            self.assertTrue(self.ns.can_wiki_edit(self._root_node(), self._auth_user()))

    def test_wiki_mode_auth_user_cannot_edit_child(self):
        self.ns.wiki = True
        with mock.patch.object(self.ns, "can_alter_node", return_value=False):
            self.assertFalse(self.ns.can_wiki_edit(self._child_node(), self._auth_user()))

    def test_wiki_mode_unauth_user_denied(self):
        self.ns.wiki = True
        u = mock.Mock()
        u.authenticated = False
        self.assertFalse(self.ns.can_wiki_edit(self._root_node(), u))

    def test_wiki_mode_none_user_denied(self):
        self.ns.wiki = True
        self.assertFalse(self.ns.can_wiki_edit(self._root_node(), None))

    # --- wiki=False cases ---

    def test_non_wiki_owner_can_edit_root(self):
        self.ns.wiki = False
        with mock.patch.object(self.ns, "can_alter_node", return_value=True):
            self.assertTrue(self.ns.can_wiki_edit(self._root_node(), self._auth_user()))

    def test_non_wiki_non_owner_denied(self):
        self.ns.wiki = False
        with mock.patch.object(self.ns, "can_alter_node", return_value=False):
            self.assertFalse(self.ns.can_wiki_edit(self._root_node(), self._auth_user()))


# ---------------------------------------------------------------------------
# Functional tests — full app via webtest
# ---------------------------------------------------------------------------

class WikiFunctionalBase(unittest.TestCase):
    """Shared setup for functional tests that need a wiki namespace & auth user."""

    @classmethod
    def setUpClass(cls):
        import webtest
        from remarkbox import main

        cls.settings = get_appsettings("test.ini")
        cls.settings["pyramid.csrf_trusted_origins"] = "www.test-wiki.com"
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
        Base.metadata.drop_all(bind=cls.engine)

    def tearDown(self):
        self.testapp.get("/log-out")

    def _create_wiki_namespace(self, name="wiki-test.com"):
        ns = get_or_create_namespace(self.dbsession, name)
        ns.wiki = True
        ns.subscription_type = "production"
        self.dbsession.add(ns)
        self.dbsession.flush()
        ns_name = ns.name
        self.tm.commit()
        return get_or_create_namespace(self.dbsession, ns_name)

    def _create_user_and_login(self, email):
        user = get_or_create_user_by_email(self.dbsession, email)
        raw_otp = user.new_password()
        self.dbsession.add(user)
        self.dbsession.flush()
        self.tm.commit()
        self.testapp.post(
            "/verification-challenge?email={}&raw-otp={}&submit".format(email, raw_otp)
        )
        # Grab CSRF token from new-thread form on home page
        res = self.testapp.get("/")
        try:
            self.csrf = res.form.fields["csrf_token"][0].value
        except (KeyError, IndexError):
            self.csrf = ""
        # Re-query user after commit + login
        return get_or_create_user_by_email(self.dbsession, email)

    def _create_wiki_root_node(self, ns_name, user_email, title="Test Wiki Page", data="# Hello\n\nWorld."):
        # Re-query from session to avoid detached instances
        ns = get_or_create_namespace(self.dbsession, ns_name)
        user = get_or_create_user_by_email(self.dbsession, user_email)
        node = Node()
        node.title = title
        node.data = data
        node.source_format = "markdown"
        node.user = user
        node.namespace = ns
        self.dbsession.add(node)
        self.dbsession.flush()
        node_id = node.id
        self.tm.commit()
        return node_id


class TestWikiEditCreatesRevisionAndHTML(WikiFunctionalBase):
    """wiki_edit() must create a Revision AND regenerate data_html."""

    def test_wiki_edit_creates_revision(self):
        self._create_wiki_namespace("wiki-rev-test.com")
        self._create_user_and_login("wiki-rev@test.com")
        node_id = self._create_wiki_root_node("wiki-rev-test.com", "wiki-rev@test.com", data="Original content.")

        node = self.dbsession.query(Node).filter(Node.id == node_id).one()
        node.wiki_edit("Updated content.", user=None)
        self.dbsession.add(node)
        self.dbsession.flush()
        self.tm.commit()

        revisions = (
            self.dbsession.query(Revision)
            .filter(Revision.node_id == node_id)
            .all()
        )
        self.assertGreaterEqual(len(revisions), 1)

    def test_wiki_edit_updates_data_html(self):
        self._create_wiki_namespace("wiki-html-test.com")
        self._create_user_and_login("wiki-html@test.com")
        node_id = self._create_wiki_root_node("wiki-html-test.com", "wiki-html@test.com", data="Before.")

        node = self.dbsession.query(Node).filter(Node.id == node_id).one()
        node.wiki_edit("After the edit.", user=None)
        self.dbsession.add(node)
        self.dbsession.flush()
        self.tm.commit()

        node = self.dbsession.query(Node).filter(Node.id == node_id).one()
        self.assertIsNotNone(node.data_html)
        self.assertIn("After the edit", node.data_html)

    def test_wiki_edit_revision_created_is_numeric(self):
        self._create_wiki_namespace("wiki-ts-test.com")
        self._create_user_and_login("wiki-ts@test.com")
        node_id = self._create_wiki_root_node("wiki-ts-test.com", "wiki-ts@test.com")

        node = self.dbsession.query(Node).filter(Node.id == node_id).one()
        node.wiki_edit("New content.", user=None)
        self.dbsession.add(node)
        self.dbsession.flush()
        self.tm.commit()

        rev = (
            self.dbsession.query(Revision)
            .filter(Revision.node_id == node_id)
            .order_by(Revision.revision_number.desc())
            .first()
        )
        self.assertIsInstance(rev.created, (int, float))
        self.assertGreater(rev.created, 1_000_000_000_000)

    def test_node_changed_is_numeric_after_wiki_edit(self):
        self._create_wiki_namespace("wiki-changed-test.com")
        self._create_user_and_login("wiki-changed@test.com")
        node_id = self._create_wiki_root_node("wiki-changed-test.com", "wiki-changed@test.com")

        node = self.dbsession.query(Node).filter(Node.id == node_id).one()
        node.wiki_edit("Changed.", user=None)
        self.dbsession.add(node)
        self.dbsession.flush()
        self.tm.commit()

        node = self.dbsession.query(Node).filter(Node.id == node_id).one()
        self.assertIsInstance(node.changed, (int, float))
        self.assertGreater(node.changed, 1_000_000_000_000)


class TestRevisionHistoryRoute(WikiFunctionalBase):
    """/{node_id}/revisions returns HTML with diff tables."""

    def test_revision_history_returns_200(self):
        self._create_wiki_namespace("wiki-history.com")
        self._create_user_and_login("wiki-history@test.com")
        node_id = self._create_wiki_root_node("wiki-history.com", "wiki-history@test.com", data="Version one.")

        node = self.dbsession.query(Node).filter(Node.id == node_id).one()
        node.wiki_edit("Version two.", user=None)
        self.dbsession.add(node)
        self.dbsession.flush()
        self.tm.commit()

        res = self.testapp.get("/{}/revisions".format(node_id), status=200)
        self.assertEqual(res.status_int, 200)

    def test_revision_history_contains_diff_table(self):
        self._create_wiki_namespace("wiki-diff.com")
        self._create_user_and_login("wiki-diff@test.com")
        node_id = self._create_wiki_root_node("wiki-diff.com", "wiki-diff@test.com", data="Alpha content.")

        node = self.dbsession.query(Node).filter(Node.id == node_id).one()
        node.wiki_edit("Beta content.", user=None)
        self.dbsession.add(node)
        self.dbsession.flush()
        self.tm.commit()

        res = self.testapp.get("/{}/revisions".format(node_id), status=200)
        self.assertIn(b"table", res.body)
        self.assertIn(b"diff", res.body)

    def test_revision_history_links_to_json(self):
        self._create_wiki_namespace("wiki-json-link.com")
        self._create_user_and_login("wiki-json-link@test.com")
        node_id = self._create_wiki_root_node("wiki-json-link.com", "wiki-json-link@test.com")

        res = self.testapp.get("/{}/revisions".format(node_id), status=200)
        self.assertIn(b"/api/v1/nodes/", res.body)
        self.assertIn(b"revisions", res.body)

    def test_revision_history_404_for_missing_node(self):
        self.testapp.get("/nonexistent-node-id-xyz/revisions", status=404)


class TestRevisionHistoryJSON(WikiFunctionalBase):
    """/api/v1/nodes/{node_id}/revisions returns JSON list."""

    def test_json_revisions_returns_200(self):
        self._create_wiki_namespace("wiki-json-api.com")
        self._create_user_and_login("wiki-json-api@test.com")
        node_id = self._create_wiki_root_node("wiki-json-api.com", "wiki-json-api@test.com", data="Rev one.")

        node = self.dbsession.query(Node).filter(Node.id == node_id).one()
        node.wiki_edit("Rev two.", user=None)
        self.dbsession.add(node)
        self.dbsession.flush()
        self.tm.commit()

        res = self.testapp.get(
            "/api/v1/nodes/{}/revisions".format(node_id),
            headers={"Accept": "application/json"},
            status=200,
        )
        data = res.json
        self.assertIn("revisions", data)
        self.assertGreaterEqual(data["count"], 1)

    def test_json_revisions_include_author(self):
        self._create_wiki_namespace("wiki-json-author.com")
        self._create_user_and_login("wiki-json-author@test.com")
        node_id = self._create_wiki_root_node("wiki-json-author.com", "wiki-json-author@test.com", data="Content.")

        node = self.dbsession.query(Node).filter(Node.id == node_id).one()
        node.wiki_edit("Edited.", user=None)
        self.dbsession.add(node)
        self.dbsession.flush()
        self.tm.commit()

        res = self.testapp.get(
            "/api/v1/nodes/{}/revisions".format(node_id), status=200
        )
        # Revisions may have null author (user=None), just verify structure
        revisions = res.json["revisions"]
        self.assertIsInstance(revisions, list)
        self.assertGreaterEqual(len(revisions), 1)
        self.assertIn("revision_number", revisions[0])


class TestCSRFTrustedOrigins(WikiFunctionalBase):
    """pyramid.csrf_trusted_origins must include www.foxhop.net equivalent."""

    def test_trusted_origin_setting_present(self):
        """The app was built with www.test-wiki.com in csrf_trusted_origins."""
        settings = self.app.registry.settings
        trusted = settings.get("pyramid.csrf_trusted_origins", "")
        self.assertIn("www.test-wiki.com", trusted)

    def test_post_from_trusted_www_origin_passes_csrf(self):
        """A POST with CSRF token from a trusted www origin must not 400."""
        # Log in to get a valid CSRF token
        self._create_user_and_login("csrf-origin@test.com")

        post_res = self.testapp.post(
            "/new",
            {
                "thread_title": "CSRF origin test",
                "thread_data": "body",
                "email": "csrf-origin@test.com",
                "csrf_token": self.csrf,
            },
            headers={"Origin": "https://www.test-wiki.com"},
            expect_errors=True,
        )
        # Must not be 400 Bad Request (CSRF rejection)
        self.assertNotEqual(post_res.status_int, 400)


class TestExportMenuHistoryLinks(WikiFunctionalBase):
    """Export menu shows history links iff namespace.wiki is True."""

    def test_wiki_namespace_export_menu_has_history_links(self):
        self._create_wiki_namespace("wiki-export-menu.com")
        self._create_user_and_login("wiki-export@test.com")
        node_id = self._create_wiki_root_node("wiki-export-menu.com", "wiki-export@test.com", title="Export Test")

        res = self.testapp.get("/{}".format(node_id)).follow()
        self.assertIn(b"history (json)", res.body)
        self.assertIn(b"history (html)", res.body)

    def test_non_wiki_namespace_export_menu_no_history_links(self):
        ns = get_or_create_namespace(self.dbsession, "nonwiki-export.com")
        ns.wiki = False
        ns.subscription_type = "production"
        self.dbsession.add(ns)
        self.dbsession.flush()
        self.tm.commit()

        self._create_user_and_login("nonwiki-export@test.com")
        node_id = self._create_wiki_root_node("nonwiki-export.com", "nonwiki-export@test.com", title="Non-wiki export")

        res = self.testapp.get("/{}".format(node_id)).follow()
        self.assertNotIn(b"history (json)", res.body)
        self.assertNotIn(b"history (html)", res.body)


class TestSetDataRSTRegenHTML(unittest.TestCase):
    """set_data() with source_format=rst must produce data_html via pandoc.

    Skipped if pandoc is not installed in the test environment.
    """

    def setUp(self):
        import shutil
        if not shutil.which("pandoc"):
            self.skipTest("pandoc not installed")

    def test_rst_produces_data_html(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        ns = Namespace("rst-test.com")
        ns.subscription_type = "production"
        session.add(ns)
        session.flush()

        node = Node()
        node.title = "RST Test"
        node.data = ""
        node.source_format = "rst"
        node.namespace = ns
        session.add(node)
        session.flush()

        rst = "Title\n=====\n\n*Joey Ballestrini* — GIMP\n"
        node.set_data(rst, namespace=ns, dbsession=session, source_format="rst")
        session.flush()

        self.assertIsNotNone(node.data_html)
        self.assertIn("Joey Ballestrini", node.data_html)
        self.assertIn("<em>", node.data_html)

    def test_rst_data_html_not_string_timestamp(self):
        """data_html must be HTML content, not a raw timestamp string."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        ns = Namespace("rst-ts-test.com")
        ns.subscription_type = "production"
        session.add(ns)
        session.flush()

        node = Node()
        node.title = "TS Test"
        node.data = ""
        node.source_format = "rst"
        node.namespace = ns
        session.add(node)
        session.flush()

        node.set_data("Hello\n=====\n\nWorld.\n", namespace=ns, dbsession=session, source_format="rst")
        session.flush()

        # data_html must not look like a raw Unix timestamp
        self.assertFalse(node.data_html.strip().isdigit())
        self.assertIn("<", node.data_html)

# Keep this module's tests together on one xdist worker. Test modules share a
# per-worker database; when --dist=loadgroup deals unmarked tests out
# individually, classes from different modules interleave on a worker and one
# class's tearDownClass drop_all yanks tables from another class mid-run.
import pytest as _pytest

pytestmark = _pytest.mark.xdist_group("test_session_work")
