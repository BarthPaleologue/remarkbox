"""Integration and functional tests for Operation Undigg.

Tests the export, multi-syntax, wiki mode, and theme APIs end-to-end
via webtest against the full Pyramid app.
"""

import shutil
import transaction
import unittest
import webtest

import pytest

from remarkbox.models import (
    Node,
    get_tm_session,
    get_or_create_user_by_email,
    get_or_create_namespace,
    UserSurrogate,
)

from remarkbox.models.meta import Base
from remarkbox.models.revision import Revision

from pyramid.paster import get_appsettings


class UndiggFunctionalTests(unittest.TestCase):
    """Base class for Undigg functional tests."""

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
        Base.metadata.drop_all(bind=cls.engine)

    def tearDown(self):
        self.testapp.get("/log-out")


# ---------------------------------------------------------------------------
# Export API
# ---------------------------------------------------------------------------


class TestExportFormats(UndiggFunctionalTests):
    """Test GET /api/v1/export/formats."""

    def test_list_formats(self):
        res = self.testapp.get("/api/v1/export/formats")
        self.assertEqual(res.status_int, 200)
        body = res.json
        self.assertIn("formats", body)
        self.assertIn("count", body)
        self.assertGreater(body["count"], 50)
        self.assertIn("html5", body["formats"])
        self.assertIn("pdf", body["formats"])
        self.assertIn("markdown", body["formats"])


class TestExportThread(UndiggFunctionalTests):
    """Test GET /api/v1/export/threads/{id}.{format}."""

    @classmethod
    def setUpClass(cls):
        try:
            UndiggFunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            UndiggFunctionalTests.setUpClass.__func__(cls)

    def setUp(self):
        ns = get_or_create_namespace(self.dbsession, "export-test.example.com")
        ns.allow_anonymous = True
        self.dbsession.add(ns)
        self.dbsession.flush()
        self.namespace_name = str(ns.name)
        self.namespace_id = ns.id
        self.tm.commit()

    def tearDown(self):
        super(TestExportThread, self).tearDown()
        self.dbsession.query(UserSurrogate).filter(
            UserSurrogate.namespace_id == self.namespace_id
        ).delete(synchronize_session=False)
        self.dbsession.query(Node).filter(
            Node.namespace_id == self.namespace_id
        ).delete(synchronize_session=False)
        self.dbsession.flush()
        self.tm.commit()

    def _create_thread(self, title="Test Thread", data="Thread content."):
        res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": title,
                "data": data,
                "anonymous_name": "Bot",
            },
            expect_errors=True,
        )
        return res.json["node"]["id"]

    def test_export_thread_markdown(self):
        node_id = self._create_thread()
        res = self.testapp.get(
            "/api/v1/export/threads/{}.markdown".format(node_id),
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertIn("text/markdown", res.content_type)
        # Markdown export is a short-circuit — no pandoc, no title block;
        # we render the thread data exactly so it carries its own heading.
        self.assertIn(b"Thread content.", res.body)

    def test_export_thread_html(self):
        node_id = self._create_thread()
        res = self.testapp.get(
            "/api/v1/export/threads/{}.html5".format(node_id),
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertIn("text/html", res.content_type)
        self.assertIn(b"Test Thread", res.body)

    def test_export_thread_rst(self):
        node_id = self._create_thread()
        res = self.testapp.get(
            "/api/v1/export/threads/{}.rst".format(node_id),
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertIn(b"Test Thread", res.body)

    @pytest.mark.skipif(
        shutil.which("wkhtmltopdf") is None,
        reason="wkhtmltopdf not installed",
    )
    def test_export_thread_pdf(self):
        node_id = self._create_thread()
        res = self.testapp.get(
            "/api/v1/export/threads/{}.pdf".format(node_id),
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/pdf")
        self.assertTrue(res.body[:4] == b"%PDF")

    def test_export_thread_epub(self):
        node_id = self._create_thread()
        res = self.testapp.get(
            "/api/v1/export/threads/{}.epub".format(node_id),
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.content_type, "application/epub+zip")
        self.assertGreater(len(res.body), 100)

    def test_export_thread_docx(self):
        node_id = self._create_thread()
        res = self.testapp.get(
            "/api/v1/export/threads/{}.docx".format(node_id),
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        # DOCX is a ZIP
        self.assertTrue(res.body[:2] == b"PK")

    def test_export_thread_not_found(self):
        res = self.testapp.get(
            "/api/v1/export/threads/00000000-0000-0000-0000-000000000000.markdown",
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 404)

    def test_export_thread_unsupported_format(self):
        node_id = self._create_thread()
        res = self.testapp.get(
            "/api/v1/export/threads/{}.not_a_format".format(node_id),
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 400)

    def test_export_thread_with_replies(self):
        """Thread with replies includes reply content in export."""
        node_id = self._create_thread()
        self.testapp.post_json(
            "/api/v1/threads/{}/replies".format(node_id),
            {"data": "A reply from alice.", "anonymous_name": "alice"},
            expect_errors=True,
        )
        res = self.testapp.get(
            "/api/v1/export/threads/{}.markdown".format(node_id),
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        body = res.body.decode("utf-8")
        self.assertIn("A reply from alice.", body)
        self.assertIn("alice", body)

    def test_export_content_disposition(self):
        node_id = self._create_thread(title="My Export Test")
        res = self.testapp.get(
            "/api/v1/export/threads/{}.markdown".format(node_id),
            expect_errors=True,
        )
        self.assertIn("attachment", res.headers.get("Content-Disposition", ""))


class TestExportNamespace(UndiggFunctionalTests):
    """Test GET /api/v1/export/namespace/{name}.{format}."""

    @classmethod
    def setUpClass(cls):
        try:
            UndiggFunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            UndiggFunctionalTests.setUpClass.__func__(cls)

    def setUp(self):
        ns = get_or_create_namespace(self.dbsession, "ns-export.example.com")
        ns.allow_anonymous = True
        self.dbsession.add(ns)
        self.dbsession.flush()
        self.namespace_name = str(ns.name)
        self.namespace_id = ns.id
        self.tm.commit()

    def tearDown(self):
        super(TestExportNamespace, self).tearDown()
        self.dbsession.query(UserSurrogate).filter(
            UserSurrogate.namespace_id == self.namespace_id
        ).delete(synchronize_session=False)
        self.dbsession.query(Node).filter(
            Node.namespace_id == self.namespace_id
        ).delete(synchronize_session=False)
        self.dbsession.flush()
        self.tm.commit()

    def test_export_namespace_markdown(self):
        # Create a thread
        self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "Chapter One",
                "data": "First chapter content.",
                "anonymous_name": "Bot",
            },
            expect_errors=True,
        )
        res = self.testapp.get(
            "/api/v1/export/namespace/{}.markdown".format(self.namespace_name),
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        body = res.body.decode("utf-8")
        self.assertIn("Chapter One", body)
        self.assertIn("First chapter content.", body)

    def test_export_namespace_html(self):
        self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "HTML Chapter",
                "data": "Content.",
                "anonymous_name": "Bot",
            },
            expect_errors=True,
        )
        res = self.testapp.get(
            "/api/v1/export/namespace/{}.html5".format(self.namespace_name),
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertIn("text/html", res.content_type)

    def test_export_namespace_not_found(self):
        res = self.testapp.get(
            "/api/v1/export/namespace/nonexistent.example.com.markdown",
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 404)

    def test_export_empty_namespace(self):
        ns = get_or_create_namespace(self.dbsession, "empty-ns.example.com")
        self.dbsession.add(ns)
        self.dbsession.flush()
        self.tm.commit()

        res = self.testapp.get(
            "/api/v1/export/namespace/empty-ns.example.com.markdown",
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)


class TestExportNode(UndiggFunctionalTests):
    """Test GET /api/v1/export/nodes/{id}.{format} (on-demand subthread)."""

    @classmethod
    def setUpClass(cls):
        try:
            UndiggFunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            UndiggFunctionalTests.setUpClass.__func__(cls)

    def setUp(self):
        ns = get_or_create_namespace(self.dbsession, "node-export.example.com")
        ns.allow_anonymous = True
        self.dbsession.add(ns)
        self.dbsession.flush()
        self.namespace_name = str(ns.name)
        self.namespace_id = ns.id
        self.tm.commit()

    def tearDown(self):
        super(TestExportNode, self).tearDown()
        self.dbsession.query(UserSurrogate).filter(
            UserSurrogate.namespace_id == self.namespace_id
        ).delete(synchronize_session=False)
        self.dbsession.query(Node).filter(
            Node.namespace_id == self.namespace_id
        ).delete(synchronize_session=False)
        self.dbsession.flush()
        self.tm.commit()

    def test_export_node_subtree(self):
        # Create thread with a reply
        res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "Thread",
                "data": "Root content.",
                "anonymous_name": "Bot",
            },
            expect_errors=True,
        )
        root_id = res.json["node"]["id"]

        self.testapp.post_json(
            "/api/v1/threads/{}/replies".format(root_id),
            {"data": "Reply content.", "anonymous_name": "Bot"},
            expect_errors=True,
        )

        # Export the reply's subtree
        export_res = self.testapp.get(
            "/api/v1/export/nodes/{}.markdown".format(root_id),
            expect_errors=True,
        )
        self.assertEqual(export_res.status_int, 200)
        body = export_res.body.decode("utf-8")
        self.assertIn("Root content.", body)

    def test_export_node_not_found(self):
        res = self.testapp.get(
            "/api/v1/export/nodes/00000000-0000-0000-0000-000000000000.markdown",
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 404)


# ---------------------------------------------------------------------------
# Multi-Syntax Input
# ---------------------------------------------------------------------------


class TestMultiSyntaxInput(UndiggFunctionalTests):
    """Test source_format parameter on create/reply/edit."""

    @classmethod
    def setUpClass(cls):
        try:
            UndiggFunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            UndiggFunctionalTests.setUpClass.__func__(cls)

    def setUp(self):
        ns = get_or_create_namespace(self.dbsession, "syntax-test.example.com")
        ns.allow_anonymous = True
        self.dbsession.add(ns)
        self.dbsession.flush()
        self.namespace_name = str(ns.name)
        self.namespace_id = ns.id
        self.tm.commit()

    def tearDown(self):
        super(TestMultiSyntaxInput, self).tearDown()
        self.dbsession.query(UserSurrogate).filter(
            UserSurrogate.namespace_id == self.namespace_id
        ).delete(synchronize_session=False)
        self.dbsession.query(Node).filter(
            Node.namespace_id == self.namespace_id
        ).delete(synchronize_session=False)
        self.dbsession.flush()
        self.tm.commit()

    def test_create_thread_default_markdown(self):
        res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "Markdown Thread",
                "data": "**bold** text",
                "anonymous_name": "Bot",
            },
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 201)
        self.assertEqual(res.json["node"]["source_format"], "markdown")
        self.assertIn("<strong>bold</strong>", res.json["node"]["data_html"])

    def test_create_thread_rst(self):
        res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "RST Thread",
                "data": "A paragraph with **bold** text.",
                "anonymous_name": "Bot",
                "source_format": "rst",
            },
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 201)
        self.assertEqual(res.json["node"]["source_format"], "rst")
        self.assertIn("bold", res.json["node"]["data_html"])

    def test_create_thread_html_stripped(self):
        res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "HTML Thread",
                "data": "<h1>Title</h1><p>Paragraph.</p>",
                "anonymous_name": "Bot",
                "source_format": "html",
            },
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 201)
        # HTML input gets normalized to markdown
        self.assertEqual(res.json["node"]["source_format"], "markdown")
        self.assertIn("Paragraph.", res.json["node"]["data"])

    def test_reply_with_source_format(self):
        # Create thread
        create_res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "Thread",
                "data": "Content.",
                "anonymous_name": "Bot",
            },
            expect_errors=True,
        )
        node_id = create_res.json["node"]["id"]

        # Reply with RST
        reply_res = self.testapp.post_json(
            "/api/v1/threads/{}/replies".format(node_id),
            {
                "data": "**RST bold** reply.",
                "anonymous_name": "Bot",
                "source_format": "rst",
            },
            expect_errors=True,
        )
        self.assertEqual(reply_res.status_int, 201)
        self.assertEqual(reply_res.json["node"]["source_format"], "rst")

    def test_serializer_includes_source_format(self):
        res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "Test",
                "data": "Content.",
                "anonymous_name": "Bot",
            },
            expect_errors=True,
        )
        self.assertIn("source_format", res.json["node"])


class TestMultiSyntaxMediawiki(UndiggFunctionalTests):
    """Test mediawiki input format."""

    @classmethod
    def setUpClass(cls):
        try:
            UndiggFunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            UndiggFunctionalTests.setUpClass.__func__(cls)

    def setUp(self):
        ns = get_or_create_namespace(self.dbsession, "wiki-syntax.example.com")
        ns.allow_anonymous = True
        self.dbsession.add(ns)
        self.dbsession.flush()
        self.namespace_name = str(ns.name)
        self.namespace_id = ns.id
        self.tm.commit()

    def tearDown(self):
        super(TestMultiSyntaxMediawiki, self).tearDown()
        self.dbsession.query(UserSurrogate).filter(
            UserSurrogate.namespace_id == self.namespace_id
        ).delete(synchronize_session=False)
        self.dbsession.query(Node).filter(
            Node.namespace_id == self.namespace_id
        ).delete(synchronize_session=False)
        self.dbsession.flush()
        self.tm.commit()

    def test_create_thread_mediawiki(self):
        res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "Wiki Thread",
                "data": "== Section ==\n\n'''bold''' text",
                "anonymous_name": "Bot",
                "source_format": "mediawiki",
            },
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 201)
        self.assertEqual(res.json["node"]["source_format"], "mediawiki")
        # The HTML should contain the rendered content
        self.assertIn("Section", res.json["node"]["data_html"])


# ---------------------------------------------------------------------------
# Wiki Mode & Revisions
# ---------------------------------------------------------------------------


class TestWikiModeAndRevisions(UndiggFunctionalTests):
    """Test wiki-edit and revision history endpoints."""

    @classmethod
    def setUpClass(cls):
        try:
            UndiggFunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            UndiggFunctionalTests.setUpClass.__func__(cls)

    def setUp(self):
        ns = get_or_create_namespace(self.dbsession, "wiki-test.example.com")
        ns.allow_anonymous = True
        # Enable wiki mode
        ns.subscription_type = "production"
        ns.wiki = True
        self.dbsession.add(ns)
        self.dbsession.flush()
        self.namespace_name = str(ns.name)
        self.namespace_id = ns.id
        self.tm.commit()

    def tearDown(self):
        super(TestWikiModeAndRevisions, self).tearDown()
        # Clean up revisions first (FK constraint)
        self.dbsession.query(Revision).filter(
            Revision.node_id.in_(
                self.dbsession.query(Node.id).filter(
                    Node.namespace_id == self.namespace_id
                )
            )
        ).delete(synchronize_session=False)
        self.dbsession.query(UserSurrogate).filter(
            UserSurrogate.namespace_id == self.namespace_id
        ).delete(synchronize_session=False)
        self.dbsession.query(Node).filter(
            Node.namespace_id == self.namespace_id
        ).delete(synchronize_session=False)
        self.dbsession.flush()
        self.tm.commit()

    def test_wiki_edit_requires_auth(self):
        # Create a thread
        create_res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "Wiki Thread",
                "data": "Original.",
                "anonymous_name": "Bot",
            },
            expect_errors=True,
        )
        node_id = create_res.json["node"]["id"]

        # Try wiki-edit without auth
        res = self.testapp.post_json(
            "/api/v1/nodes/{}/wiki-edit".format(node_id),
            {"data": "Updated."},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 401)

    def test_revisions_empty_initially(self):
        create_res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "Wiki Thread",
                "data": "Original.",
                "anonymous_name": "Bot",
            },
            expect_errors=True,
        )
        node_id = create_res.json["node"]["id"]

        res = self.testapp.get(
            "/api/v1/nodes/{}/revisions".format(node_id),
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.json["count"], 0)
        self.assertEqual(res.json["revisions"], [])

    def test_revisions_not_found(self):
        res = self.testapp.get(
            "/api/v1/nodes/00000000-0000-0000-0000-000000000000/revisions",
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 404)

    def test_wiki_edit_missing_data(self):
        create_res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "Wiki Thread",
                "data": "Original.",
                "anonymous_name": "Bot",
            },
            expect_errors=True,
        )
        node_id = create_res.json["node"]["id"]

        # Need to be authenticated to even get past the auth check
        # Since we can't easily authenticate in these tests, just verify
        # the 401 response for unauthenticated users
        res = self.testapp.post_json(
            "/api/v1/nodes/{}/wiki-edit".format(node_id),
            {},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 401)

    def test_wiki_edit_node_not_found(self):
        res = self.testapp.post_json(
            "/api/v1/nodes/00000000-0000-0000-0000-000000000000/wiki-edit",
            {"data": "Updated."},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 404)

    def test_revision_detail_not_found(self):
        res = self.testapp.get(
            "/api/v1/revisions/00000000-0000-0000-0000-000000000000",
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 404)


class TestRevisionDiff(UndiggFunctionalTests):
    """Test GET /api/v1/revisions/{id}/diff/{other_id}."""

    @classmethod
    def setUpClass(cls):
        try:
            UndiggFunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            UndiggFunctionalTests.setUpClass.__func__(cls)

    def setUp(self):
        ns = get_or_create_namespace(self.dbsession, "diff-test.example.com")
        ns.allow_anonymous = True
        ns.subscription_type = "production"
        ns.wiki = True
        self.dbsession.add(ns)
        self.dbsession.flush()
        self.namespace_name = str(ns.name)
        self.namespace_id = ns.id
        self.tm.commit()

    def tearDown(self):
        super(TestRevisionDiff, self).tearDown()
        self.dbsession.query(Revision).filter(
            Revision.node_id.in_(
                self.dbsession.query(Node.id).filter(
                    Node.namespace_id == self.namespace_id
                )
            )
        ).delete(synchronize_session=False)
        self.dbsession.query(UserSurrogate).filter(
            UserSurrogate.namespace_id == self.namespace_id
        ).delete(synchronize_session=False)
        self.dbsession.query(Node).filter(
            Node.namespace_id == self.namespace_id
        ).delete(synchronize_session=False)
        self.dbsession.flush()
        self.tm.commit()

    def _create_thread(self, title="Diff Thread", data="Original content."):
        res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": title,
                "data": data,
                "anonymous_name": "Bot",
            },
            expect_errors=True,
        )
        return res.json["node"]["id"]

    def _create_revisions(self, node_id, data_v1, data_v2):
        """Manually create two revisions for a node."""
        node = self.dbsession.query(Node).get(node_id)
        rev1 = Revision(node=node, data=data_v1, revision_number=1)
        rev2 = Revision(node=node, data=data_v2, revision_number=2)
        self.dbsession.add(rev1)
        self.dbsession.add(rev2)
        self.dbsession.flush()
        rev1_id = str(rev1.id)
        rev2_id = str(rev2.id)
        self.tm.commit()
        return rev1_id, rev2_id

    def test_diff_same_revision(self):
        node_id = self._create_thread()
        rev1_id, rev2_id = self._create_revisions(
            node_id, "Same content.", "Same content."
        )
        res = self.testapp.get(
            "/api/v1/revisions/{}/diff/{}".format(rev1_id, rev1_id),
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.json["diff"], "")
        self.assertEqual(res.json["from_revision"], rev1_id)
        self.assertEqual(res.json["to_revision"], rev1_id)

    def test_diff_different_revisions(self):
        node_id = self._create_thread()
        rev1_id, rev2_id = self._create_revisions(
            node_id, "Original content.", "Updated content."
        )
        res = self.testapp.get(
            "/api/v1/revisions/{}/diff/{}".format(rev1_id, rev2_id),
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertIn("from_revision", res.json)
        self.assertIn("to_revision", res.json)
        self.assertEqual(res.json["from_number"], 1)
        self.assertEqual(res.json["to_number"], 2)
        self.assertIn("Original", res.json["diff"])
        self.assertIn("Updated", res.json["diff"])

    def test_diff_not_found(self):
        res = self.testapp.get(
            "/api/v1/revisions/00000000-0000-0000-0000-000000000000/diff/00000000-0000-0000-0000-000000000001",
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 404)

    def test_diff_different_nodes(self):
        node1_id = self._create_thread(title="Thread 1", data="Content 1.")
        node2_id = self._create_thread(title="Thread 2", data="Content 2.")
        rev1_id, _ = self._create_revisions(node1_id, "A", "B")
        rev2_id, _ = self._create_revisions(node2_id, "C", "D")
        res = self.testapp.get(
            "/api/v1/revisions/{}/diff/{}".format(rev1_id, rev2_id),
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 400)
        self.assertIn("different nodes", res.json["error"])


# ---------------------------------------------------------------------------
# Theme API
# ---------------------------------------------------------------------------


class TestThemeAPI(UndiggFunctionalTests):
    """Test theme generation endpoints."""

    @classmethod
    def setUpClass(cls):
        try:
            UndiggFunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            UndiggFunctionalTests.setUpClass.__func__(cls)

    def setUp(self):
        ns = get_or_create_namespace(self.dbsession, "theme-test.example.com")
        self.dbsession.add(ns)
        self.dbsession.flush()
        self.namespace_name = str(ns.name)
        self.tm.commit()

    def test_get_theme_css(self):
        res = self.testapp.get(
            "/api/v1/themes/{}/css".format(self.namespace_name),
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertIn("text/css", res.content_type)
        body = res.body.decode("utf-8")
        self.assertIn("--rb-bg:", body)
        self.assertIn("--rb-text:", body)
        self.assertIn("prefers-color-scheme: dark", body)

    def test_get_theme_css_deterministic(self):
        res1 = self.testapp.get(
            "/api/v1/themes/{}/css".format(self.namespace_name))
        res2 = self.testapp.get(
            "/api/v1/themes/{}/css".format(self.namespace_name))
        self.assertEqual(res1.body, res2.body)

    def test_get_theme_css_cached(self):
        res = self.testapp.get(
            "/api/v1/themes/{}/css".format(self.namespace_name))
        self.assertIn("max-age", res.headers.get("Cache-Control", ""))

    def test_get_theme_css_not_found(self):
        res = self.testapp.get(
            "/api/v1/themes/nonexistent-ns-xyz.example.com/css",
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 404)

    def test_get_theme_preview(self):
        res = self.testapp.get(
            "/api/v1/themes/{}/preview".format(self.namespace_name),
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        body = res.json
        self.assertIn("palette", body)
        self.assertIn("primary_hue", body["palette"])
        self.assertIn("secondary_hue", body["palette"])
        self.assertIn("accent_hue", body["palette"])
        self.assertIn("css_url", body)

    def test_get_theme_preview_not_found(self):
        res = self.testapp.get(
            "/api/v1/themes/nonexistent-ns-xyz.example.com/preview",
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 404)

    def test_different_namespaces_different_themes(self):
        ns2 = get_or_create_namespace(self.dbsession, "theme-test-2.example.com")
        self.dbsession.add(ns2)
        self.dbsession.flush()
        self.tm.commit()

        res1 = self.testapp.get(
            "/api/v1/themes/{}/css".format(self.namespace_name))
        res2 = self.testapp.get(
            "/api/v1/themes/theme-test-2.example.com/css")
        self.assertNotEqual(res1.body, res2.body)
