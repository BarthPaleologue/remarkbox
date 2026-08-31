import transaction
import unittest
import webtest

from remarkbox.models import (
    Node,
    get_tm_session,
    get_or_create_user_by_email,
    get_user_by_email,
    get_or_create_namespace,
    UserSurrogate,
)

from remarkbox.models.meta import Base, id_to_uuid

from pyramid.paster import get_appsettings

from unittest.mock import patch


class APIFunctionalTests(unittest.TestCase, object):
    """Base class for API functional tests."""

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


class TestAPIAnonymousPosting(APIFunctionalTests):
    """Functional tests for anonymous posting via the API."""

    @classmethod
    def setUpClass(cls):
        try:
            APIFunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            APIFunctionalTests.setUpClass.__func__(cls)

    def setUp(self):
        ns = get_or_create_namespace(self.dbsession, "api-test.example.com")
        ns.allow_anonymous = True
        self.dbsession.add(ns)
        self.dbsession.flush()
        self.namespace_name = str(ns.name)
        self.namespace_id = ns.id
        self.tm.commit()

    def tearDown(self):
        super(TestAPIAnonymousPosting, self).tearDown()
        # Clean up surrogates and nodes
        self.dbsession.query(UserSurrogate).filter(
            UserSurrogate.namespace_id == self.namespace_id
        ).delete(synchronize_session=False)
        self.dbsession.query(Node).filter(
            Node.namespace_id == self.namespace_id
        ).delete(synchronize_session=False)
        self.dbsession.flush()
        self.tm.commit()

    def test_create_anonymous_thread(self):
        res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "Agent Thread",
                "data": "Hello from an AI agent",
                "anonymous_name": "ClaudeBot",
            },
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 201)
        body = res.json
        self.assertIn("node", body)
        self.assertEqual(body["node"]["title"], "Agent Thread")
        self.assertEqual(body["node"]["data"], "Hello from an AI agent")
        self.assertIn("<p>Hello from an AI agent</p>", body["node"]["data_html"])
        self.assertTrue(body["verified"])
        self.assertEqual(body["node"]["author"]["type"], "surrogate")
        self.assertEqual(body["node"]["author"]["name"], "ClaudeBot")

    def test_create_thread_with_uri(self):
        """thread_uri creates a root via get_or_create_node_by_uri and
        returns the comment as a child reply — same as the embed iframe."""
        res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "Page Thread",
                "data": "Linked to a URI",
                "thread_uri": "https://api-test.example.com/my-page/",
                "anonymous_name": "TestBot",
            },
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 201)
        reply_id = res.json["node"]["id"]
        root_id = res.json["root_node_id"]

        # The reply should be a child, not the root itself
        self.assertNotEqual(reply_id, root_id)

        # Verify the URI record links to the root node (not the reply)
        from remarkbox.models.uri import get_uri_by_uri
        uri = get_uri_by_uri(self.dbsession, "https://api-test.example.com/my-page/")
        self.assertIsNotNone(uri)
        self.assertEqual(str(uri.node.id), root_id)

    def test_create_thread_duplicate_uri_adds_reply(self):
        """Posting to the same thread_uri twice adds a second reply
        under the same root — it does not fail with 409."""
        res1 = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "First",
                "data": "First comment",
                "thread_uri": "https://api-test.example.com/dup-test/",
                "anonymous_name": "Bot",
            },
            expect_errors=True,
        )
        self.assertEqual(res1.status_int, 201)
        root_id_1 = res1.json["root_node_id"]

        # Second post to same URI creates another reply under the same root
        res2 = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "First",
                "data": "Second comment",
                "thread_uri": "https://api-test.example.com/dup-test/",
                "anonymous_name": "Bot",
            },
            expect_errors=True,
        )
        self.assertEqual(res2.status_int, 201)
        root_id_2 = res2.json["root_node_id"]

        # Both replies share the same root
        self.assertEqual(root_id_1, root_id_2)
        # But the reply nodes are different
        self.assertNotEqual(res1.json["node"]["id"], res2.json["node"]["id"])

    def test_create_anonymous_thread_default_name(self):
        res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "Default Anon",
                "data": "No name given",
            },
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 201)
        self.assertEqual(res.json["node"]["author"]["name"], "Anonymous")

    def test_create_thread_missing_namespace(self):
        res = self.testapp.post_json(
            "/api/v1/threads",
            {"title": "Test", "data": "Test"},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 400)
        self.assertIn("namespace", res.json["error"])

    def test_create_thread_nonexistent_namespace(self):
        res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": "does-not-exist.example.com",
                "title": "Test",
                "data": "Should fail",
            },
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 404)
        self.assertIn("does not exist", res.json["error"])

    def test_create_thread_missing_title(self):
        res = self.testapp.post_json(
            "/api/v1/threads",
            {"namespace": self.namespace_name, "data": "Test"},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 400)
        self.assertIn("title", res.json["error"])

    def test_create_thread_missing_data(self):
        res = self.testapp.post_json(
            "/api/v1/threads",
            {"namespace": self.namespace_name, "title": "Test"},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 400)
        self.assertIn("data", res.json["error"])

    def test_create_thread_content_too_long(self):
        res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "Test",
                "data": "x" * 600000,
            },
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 400)
        self.assertIn("maximum length", res.json["error"])

    def test_reply_to_thread(self):
        # Create thread
        create_res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "Thread for replies",
                "data": "Original post",
                "anonymous_name": "Bot1",
            },
            expect_errors=True,
        )
        node_id = create_res.json["node"]["id"]

        # Reply
        reply_res = self.testapp.post_json(
            "/api/v1/threads/{}/replies".format(node_id),
            {
                "data": "A reply from an agent",
                "anonymous_name": "Bot2",
            },
            expect_errors=True,
        )
        self.assertEqual(reply_res.status_int, 201)
        self.assertIn("node", reply_res.json)
        self.assertEqual(reply_res.json["node"]["author"]["name"], "Bot2")
        self.assertFalse(reply_res.json["node"]["is_root"])
        self.assertEqual(reply_res.json["node"]["parent_id"], node_id)

    def test_reply_missing_data(self):
        create_res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "Thread",
                "data": "Content",
                "anonymous_name": "Bot",
            },
            expect_errors=True,
        )
        node_id = create_res.json["node"]["id"]

        reply_res = self.testapp.post_json(
            "/api/v1/threads/{}/replies".format(node_id),
            {"anonymous_name": "Bot"},
            expect_errors=True,
        )
        self.assertEqual(reply_res.status_int, 400)

    def test_reply_to_nonexistent_node(self):
        res = self.testapp.post_json(
            "/api/v1/threads/00000000-0000-0000-0000-000000000000/replies",
            {"data": "Should fail", "anonymous_name": "Bot"},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 404)

    def test_reply_to_locked_thread(self):
        # Create thread
        create_res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "Will Be Locked",
                "data": "Content",
                "anonymous_name": "Bot",
            },
            expect_errors=True,
        )
        node_id = create_res.json["node"]["id"]

        # Lock the thread directly in DB
        node = self.dbsession.query(Node).filter(
            Node.id == id_to_uuid(node_id)
        ).first()
        node.locked = True
        self.dbsession.add(node)
        self.dbsession.flush()
        self.tm.commit()

        reply_res = self.testapp.post_json(
            "/api/v1/threads/{}/replies".format(node_id),
            {"data": "Should fail", "anonymous_name": "Bot"},
            expect_errors=True,
        )
        self.assertEqual(reply_res.status_int, 403)
        self.assertIn("locked", reply_res.json["error"])

    def test_list_threads(self):
        # Create a thread
        self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "Listable Thread",
                "data": "Some content",
                "anonymous_name": "Bot",
            },
            expect_errors=True,
        )

        res = self.testapp.get(
            "/api/v1/threads",
            {"namespace": self.namespace_name},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertIn("threads", res.json)
        self.assertIn("namespace", res.json)
        self.assertEqual(res.json["namespace"]["name"], self.namespace_name)
        self.assertGreater(len(res.json["threads"]), 0)

        thread = res.json["threads"][0]
        self.assertIn("id", thread)
        self.assertIn("title", thread)
        self.assertIn("author", thread)

    def test_list_threads_missing_namespace(self):
        res = self.testapp.get(
            "/api/v1/threads",
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 400)

    def test_get_thread_detail(self):
        # Create thread with a reply
        create_res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "Detail Thread",
                "data": "Content here",
                "anonymous_name": "Bot",
            },
            expect_errors=True,
        )
        node_id = create_res.json["node"]["id"]

        self.testapp.post_json(
            "/api/v1/threads/{}/replies".format(node_id),
            {"data": "A reply", "anonymous_name": "ReplyBot"},
            expect_errors=True,
        )

        res = self.testapp.get(
            "/api/v1/threads/{}".format(node_id),
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertIn("thread", res.json)
        self.assertIn("replies", res.json)
        self.assertEqual(res.json["thread"]["id"], node_id)
        self.assertEqual(len(res.json["replies"]), 1)
        self.assertEqual(res.json["replies"][0]["author"]["name"], "ReplyBot")
        # Pagination metadata
        self.assertEqual(res.json["total_replies"], 1)
        self.assertEqual(res.json["page"], 1)
        self.assertIn("limit", res.json)
        self.assertIn("offset", res.json)
        self.assertIn("has_more", res.json)
        self.assertFalse(res.json["has_more"])

    def test_get_nonexistent_thread(self):
        res = self.testapp.get(
            "/api/v1/threads/00000000-0000-0000-0000-000000000000",
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 404)

    def test_get_single_node(self):
        create_res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "Node Test",
                "data": "Content",
                "anonymous_name": "Bot",
            },
            expect_errors=True,
        )
        node_id = create_res.json["node"]["id"]

        res = self.testapp.get(
            "/api/v1/nodes/{}".format(node_id),
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.json["node"]["id"], node_id)

    def test_get_nonexistent_node(self):
        res = self.testapp.get(
            "/api/v1/nodes/00000000-0000-0000-0000-000000000000",
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 404)

    def test_reply_content_too_long(self):
        create_res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "Thread",
                "data": "Content",
                "anonymous_name": "Bot",
            },
            expect_errors=True,
        )
        node_id = create_res.json["node"]["id"]

        reply_res = self.testapp.post_json(
            "/api/v1/threads/{}/replies".format(node_id),
            {"data": "x" * 600000, "anonymous_name": "Bot"},
            expect_errors=True,
        )
        self.assertEqual(reply_res.status_int, 400)
        self.assertIn("maximum length", reply_res.json["error"])

    def test_pagination(self):
        res = self.testapp.get(
            "/api/v1/threads",
            {"namespace": self.namespace_name, "page": "1"},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.json["page"], 1)
        self.assertIn("page_size", res.json)


class TestAPIThreadDetailPagination(APIFunctionalTests):
    """Functional tests for thread detail pagination."""

    @classmethod
    def setUpClass(cls):
        try:
            APIFunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            APIFunctionalTests.setUpClass.__func__(cls)

    def setUp(self):
        ns = get_or_create_namespace(self.dbsession, "api-paginate.example.com")
        ns.allow_anonymous = True
        self.dbsession.add(ns)
        self.dbsession.flush()
        self.namespace_name = str(ns.name)
        self.namespace_id = ns.id
        self.tm.commit()

        # Create a thread with 5 replies
        res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "Pagination Thread",
                "data": "Root post",
                "anonymous_name": "Bot",
            },
            expect_errors=True,
        )
        self.thread_id = res.json["node"]["id"]
        for i in range(5):
            self.testapp.post_json(
                "/api/v1/threads/{}/replies".format(self.thread_id),
                {"data": "Reply {}".format(i), "anonymous_name": "Bot{}".format(i)},
                expect_errors=True,
            )

    def tearDown(self):
        super(TestAPIThreadDetailPagination, self).tearDown()
        self.dbsession.query(UserSurrogate).filter(
            UserSurrogate.namespace_id == self.namespace_id
        ).delete(synchronize_session=False)
        self.dbsession.query(Node).filter(
            Node.namespace_id == self.namespace_id
        ).delete(synchronize_session=False)
        self.dbsession.flush()
        self.tm.commit()

    def test_default_pagination(self):
        """Default request returns all replies with pagination metadata."""
        res = self.testapp.get(
            "/api/v1/threads/{}".format(self.thread_id),
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertEqual(len(res.json["replies"]), 5)
        self.assertEqual(res.json["total_replies"], 5)
        self.assertEqual(res.json["page"], 1)
        self.assertEqual(res.json["offset"], 0)
        self.assertEqual(res.json["limit"], 100)
        self.assertFalse(res.json["has_more"])

    def test_limit_param(self):
        """Limit restricts the number of returned replies."""
        res = self.testapp.get(
            "/api/v1/threads/{}".format(self.thread_id),
            {"limit": "2"},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertEqual(len(res.json["replies"]), 2)
        self.assertEqual(res.json["total_replies"], 5)
        self.assertEqual(res.json["limit"], 2)
        self.assertTrue(res.json["has_more"])

    def test_offset_param(self):
        """Offset skips replies."""
        res = self.testapp.get(
            "/api/v1/threads/{}".format(self.thread_id),
            {"limit": "2", "offset": "3"},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertEqual(len(res.json["replies"]), 2)
        self.assertEqual(res.json["total_replies"], 5)
        self.assertEqual(res.json["offset"], 3)
        self.assertFalse(res.json["has_more"])

    def test_offset_beyond_total(self):
        """Offset past the end returns empty replies."""
        res = self.testapp.get(
            "/api/v1/threads/{}".format(self.thread_id),
            {"limit": "10", "offset": "100"},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertEqual(len(res.json["replies"]), 0)
        self.assertEqual(res.json["total_replies"], 5)
        self.assertFalse(res.json["has_more"])

    def test_page_number_calculation(self):
        """Page number is calculated from offset and limit."""
        res = self.testapp.get(
            "/api/v1/threads/{}".format(self.thread_id),
            {"limit": "2", "offset": "2"},
            expect_errors=True,
        )
        self.assertEqual(res.json["page"], 2)

    def test_replies_exclude_root(self):
        """Root node is never included in the replies list."""
        res = self.testapp.get(
            "/api/v1/threads/{}".format(self.thread_id),
            expect_errors=True,
        )
        reply_ids = [r["id"] for r in res.json["replies"]]
        self.assertNotIn(self.thread_id, reply_ids)

    def test_disabled_replies_filtered(self):
        """Disabled replies are excluded from results."""
        root_uuid = id_to_uuid(self.thread_id)
        reply_node = self.dbsession.query(Node).filter(
            Node.root_id == root_uuid,
            Node.id != root_uuid,
        ).first()
        self.assertIsNotNone(reply_node)
        reply_node.disabled = True
        self.dbsession.add(reply_node)
        self.dbsession.flush()
        self.tm.commit()

        res = self.testapp.get(
            "/api/v1/threads/{}".format(self.thread_id),
            expect_errors=True,
        )
        self.assertEqual(res.json["total_replies"], 4)
        self.assertEqual(len(res.json["replies"]), 4)

    def test_limit_clamped_to_max(self):
        """Limit is clamped to 500 maximum."""
        res = self.testapp.get(
            "/api/v1/threads/{}".format(self.thread_id),
            {"limit": "9999"},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.json["limit"], 500)

    def test_invalid_limit_uses_default(self):
        """Non-integer limit falls back to default 100."""
        res = self.testapp.get(
            "/api/v1/threads/{}".format(self.thread_id),
            {"limit": "abc"},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.json["limit"], 100)

    def test_invalid_offset_uses_default(self):
        """Non-integer offset falls back to default 0."""
        res = self.testapp.get(
            "/api/v1/threads/{}".format(self.thread_id),
            {"offset": "abc"},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.json["offset"], 0)

    def test_zero_replies_thread(self):
        """Thread with zero replies returns valid empty pagination response."""
        # Create a thread with no replies
        res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "Empty Thread",
                "data": "Thread with no replies",
                "anonymous_name": "Loner",
            },
            expect_errors=True,
        )
        empty_thread_id = res.json["node"]["id"]

        res = self.testapp.get(
            "/api/v1/threads/{}".format(empty_thread_id),
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.json["total_replies"], 0)
        self.assertEqual(len(res.json["replies"]), 0)
        self.assertEqual(res.json["page"], 1)
        self.assertEqual(res.json["offset"], 0)
        self.assertEqual(res.json["limit"], 100)
        self.assertFalse(res.json["has_more"])
        # Thread data should still be present
        self.assertIn("thread", res.json)
        self.assertIn("namespace", res.json)


class TestAPIOTPAuthentication(APIFunctionalTests):
    """Functional tests for the OTP auth flow via API."""

    @classmethod
    def setUpClass(cls):
        try:
            APIFunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            APIFunctionalTests.setUpClass.__func__(cls)

    def tearDown(self):
        super(TestAPIOTPAuthentication, self).tearDown()
        # Clean up test users
        for email in [
            "api-login@example.com",
            "api-verify@example.com",
            "api-bad-otp@example.com",
            "api-throttle@example.com",
        ]:
            user = get_user_by_email(self.dbsession, email)
            if user:
                self.dbsession.delete(user)
        self.dbsession.flush()
        self.tm.commit()

    @patch("smtplib.SMTP")
    def test_login_sends_otp(self, mock_smtp):
        res = self.testapp.post_json(
            "/api/v1/auth/login",
            {"email": "api-login@example.com"},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.json["status"], "sent")
        self.assertIn("api-login@example.com", res.json["message"])

    def test_login_invalid_email(self):
        res = self.testapp.post_json(
            "/api/v1/auth/login",
            {"email": "not-an-email"},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 400)
        self.assertIn("email", res.json["error"])

    def test_login_missing_email(self):
        res = self.testapp.post_json(
            "/api/v1/auth/login",
            {},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 400)

    @patch("smtplib.SMTP")
    def test_login_throttle(self, mock_smtp):
        # First login sends OTP
        self.testapp.post_json(
            "/api/v1/auth/login",
            {"email": "api-throttle@example.com"},
            expect_errors=True,
        )

        # Second login within throttle window
        res = self.testapp.post_json(
            "/api/v1/auth/login",
            {"email": "api-throttle@example.com"},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.json["status"], "throttled")

    def test_verify_valid_otp(self):
        user = get_or_create_user_by_email(self.dbsession, "api-verify@example.com")
        raw_otp = user.new_password()
        self.dbsession.add(user)
        self.dbsession.flush()
        self.tm.commit()

        res = self.testapp.post_json(
            "/api/v1/auth/verify",
            {"email": "api-verify@example.com", "otp": raw_otp},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.json["status"], "authenticated")
        self.assertIn("user", res.json)
        self.assertEqual(res.json["user"]["email"], "api-verify@example.com")

    def test_verify_invalid_otp(self):
        user = get_or_create_user_by_email(self.dbsession, "api-bad-otp@example.com")
        user.new_password()
        self.dbsession.add(user)
        self.dbsession.flush()
        self.tm.commit()

        res = self.testapp.post_json(
            "/api/v1/auth/verify",
            {"email": "api-bad-otp@example.com", "otp": "000000"},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 401)

    def test_verify_missing_fields(self):
        res = self.testapp.post_json(
            "/api/v1/auth/verify",
            {"email": "test@example.com"},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 400)

        res = self.testapp.post_json(
            "/api/v1/auth/verify",
            {"otp": "123456"},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 400)


class TestAPIAuthenticatedEditing(APIFunctionalTests):
    """Functional tests for authenticated edit operations via API."""

    @classmethod
    def setUpClass(cls):
        try:
            APIFunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            APIFunctionalTests.setUpClass.__func__(cls)

    def setUp(self):
        # Ensure the namespace exists so api_create_thread doesn't 404
        ns = get_or_create_namespace(self.dbsession, "localhost")
        ns.api_access = True
        self.dbsession.add(ns)
        self.dbsession.flush()

        self.test_user = get_or_create_user_by_email(
            self.dbsession, "api-edit@remarkbox.com"
        )
        self.raw_otp = self.test_user.new_password()
        self.dbsession.add(self.test_user)
        self.dbsession.flush()
        self.tm.commit()
        self.test_user = get_or_create_user_by_email(
            self.dbsession, "api-edit@remarkbox.com"
        )

    def tearDown(self):
        super(TestAPIAuthenticatedEditing, self).tearDown()
        # Clean up nodes created by this user
        self.dbsession.query(Node).filter(
            Node.user_id == self.test_user.id
        ).delete(synchronize_session=False)
        self.dbsession.delete(self.test_user)
        self.dbsession.flush()
        self.tm.commit()

    def _login(self):
        self.testapp.post(
            "/verification-challenge?email={}&raw-otp={}".format(
                "api-edit@remarkbox.com", self.raw_otp
            )
        )

    def test_edit_own_node(self):
        self._login()

        # Create thread as authenticated user
        create_res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": "localhost",
                "title": "Editable Thread",
                "data": "Original content",
            },
            expect_errors=True,
        )
        self.assertEqual(create_res.status_int, 201)
        node_id = create_res.json["node"]["id"]

        # Edit it
        edit_res = self.testapp.patch_json(
            "/api/v1/nodes/{}".format(node_id),
            {"data": "Edited content"},
            expect_errors=True,
        )
        self.assertEqual(edit_res.status_int, 200)
        self.assertEqual(edit_res.json["node"]["data"], "Edited content")

    def test_edit_title_on_root(self):
        self._login()

        create_res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": "localhost",
                "title": "Original Title",
                "data": "Content",
            },
            expect_errors=True,
        )
        node_id = create_res.json["node"]["id"]

        edit_res = self.testapp.patch_json(
            "/api/v1/nodes/{}".format(node_id),
            {"title": "New Title"},
            expect_errors=True,
        )
        self.assertEqual(edit_res.status_int, 200)
        self.assertEqual(edit_res.json["node"]["title"], "New Title")

    def test_edit_requires_auth(self):
        self._login()

        # Create a node, then log out and try to edit
        create_res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": "localhost",
                "title": "Auth Test Thread",
                "data": "Content",
            },
            expect_errors=True,
        )
        node_id = create_res.json["node"]["id"]

        self.testapp.get("/log-out")

        res = self.testapp.patch_json(
            "/api/v1/nodes/{}".format(node_id),
            {"data": "Should fail"},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 401)

    def test_edit_nonexistent_node(self):
        self._login()
        res = self.testapp.patch_json(
            "/api/v1/nodes/00000000-0000-0000-0000-000000000000",
            {"data": "Should fail"},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 404)

    def test_edit_missing_data_and_title(self):
        self._login()

        create_res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": "localhost",
                "title": "Thread",
                "data": "Content",
            },
            expect_errors=True,
        )
        node_id = create_res.json["node"]["id"]

        edit_res = self.testapp.patch_json(
            "/api/v1/nodes/{}".format(node_id),
            {},
            expect_errors=True,
        )
        self.assertEqual(edit_res.status_int, 400)

    def test_edit_content_too_long(self):
        self._login()

        create_res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": "localhost",
                "title": "Thread",
                "data": "Content",
            },
            expect_errors=True,
        )
        node_id = create_res.json["node"]["id"]

        edit_res = self.testapp.patch_json(
            "/api/v1/nodes/{}".format(node_id),
            {"data": "x" * 600000},
            expect_errors=True,
        )
        self.assertEqual(edit_res.status_int, 400)

    def test_authenticated_thread_creation(self):
        self._login()

        res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": "localhost",
                "title": "Auth Thread",
                "data": "Authenticated post",
            },
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 201)
        self.assertTrue(res.json["verified"])
        self.assertEqual(res.json["node"]["author"]["type"], "user")


class TestAPIDisabledNode(APIFunctionalTests):
    """Test replying to disabled nodes."""

    @classmethod
    def setUpClass(cls):
        try:
            APIFunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            APIFunctionalTests.setUpClass.__func__(cls)

    def setUp(self):
        ns = get_or_create_namespace(self.dbsession, "api-disabled.example.com")
        ns.allow_anonymous = True
        self.dbsession.add(ns)
        self.dbsession.flush()
        self.namespace_name = str(ns.name)
        self.namespace_id = ns.id
        self.tm.commit()

    def tearDown(self):
        super(TestAPIDisabledNode, self).tearDown()
        self.dbsession.query(UserSurrogate).filter(
            UserSurrogate.namespace_id == self.namespace_id
        ).delete(synchronize_session=False)
        self.dbsession.query(Node).filter(
            Node.namespace_id == self.namespace_id
        ).delete(synchronize_session=False)
        self.dbsession.flush()
        self.tm.commit()

    def test_reply_to_disabled_node(self):
        # Create thread
        create_res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "Will Be Disabled",
                "data": "Content",
                "anonymous_name": "Bot",
            },
            expect_errors=True,
        )
        node_id = create_res.json["node"]["id"]

        # Disable it
        node = self.dbsession.query(Node).filter(
            Node.id == id_to_uuid(node_id)
        ).first()
        node.disabled = True
        self.dbsession.add(node)
        self.dbsession.flush()
        self.tm.commit()

        # Try to reply
        reply_res = self.testapp.post_json(
            "/api/v1/threads/{}/replies".format(node_id),
            {"data": "Should fail", "anonymous_name": "Bot"},
            expect_errors=True,
        )
        self.assertEqual(reply_res.status_int, 403)
        self.assertIn("disabled", reply_res.json["error"])


class TestAPINamespaceOptOut(APIFunctionalTests):
    """Test per-namespace api_access opt-out."""

    @classmethod
    def setUpClass(cls):
        try:
            APIFunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            APIFunctionalTests.setUpClass.__func__(cls)

    def setUp(self):
        ns = get_or_create_namespace(self.dbsession, "api-blocked.example.com")
        ns.allow_anonymous = True
        ns.api_access = False
        self.dbsession.add(ns)
        self.dbsession.flush()
        self.namespace_name = str(ns.name)
        self.namespace_id = ns.id
        self.tm.commit()

    def tearDown(self):
        super(TestAPINamespaceOptOut, self).tearDown()
        self.dbsession.query(UserSurrogate).filter(
            UserSurrogate.namespace_id == self.namespace_id
        ).delete(synchronize_session=False)
        self.dbsession.query(Node).filter(
            Node.namespace_id == self.namespace_id
        ).delete(synchronize_session=False)
        self.dbsession.flush()
        self.tm.commit()

    def test_list_threads_blocked(self):
        res = self.testapp.get(
            "/api/v1/threads",
            {"namespace": self.namespace_name},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 403)
        self.assertIn("disabled", res.json["error"])

    def test_create_thread_blocked(self):
        res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "Should fail",
                "data": "Content",
                "anonymous_name": "Bot",
            },
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 403)

    def test_reply_blocked(self):
        # Re-enable temporarily to create a thread, then disable
        ns = get_or_create_namespace(self.dbsession, self.namespace_name)
        ns.api_access = True
        self.dbsession.add(ns)
        self.dbsession.flush()
        self.tm.commit()

        create_res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "Thread",
                "data": "Content",
                "anonymous_name": "Bot",
            },
            expect_errors=True,
        )
        node_id = create_res.json["node"]["id"]

        # Disable API access
        ns = get_or_create_namespace(self.dbsession, self.namespace_name)
        ns.api_access = False
        self.dbsession.add(ns)
        self.dbsession.flush()
        self.tm.commit()

        reply_res = self.testapp.post_json(
            "/api/v1/threads/{}/replies".format(node_id),
            {"data": "Should fail", "anonymous_name": "Bot"},
            expect_errors=True,
        )
        self.assertEqual(reply_res.status_int, 403)

    def test_get_thread_blocked(self):
        # Re-enable temporarily to create a thread, then disable
        ns = get_or_create_namespace(self.dbsession, self.namespace_name)
        ns.api_access = True
        self.dbsession.add(ns)
        self.dbsession.flush()
        self.tm.commit()

        create_res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "Thread",
                "data": "Content",
                "anonymous_name": "Bot",
            },
            expect_errors=True,
        )
        node_id = create_res.json["node"]["id"]

        # Disable API access
        ns = get_or_create_namespace(self.dbsession, self.namespace_name)
        ns.api_access = False
        self.dbsession.add(ns)
        self.dbsession.flush()
        self.tm.commit()

        res = self.testapp.get(
            "/api/v1/threads/{}".format(node_id),
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 403)


class TestAPIVersion(APIFunctionalTests):
    """Test the version endpoint."""

    def test_version_returns_commit(self):
        res = self.testapp.get("/api/v1/version")
        self.assertEqual(res.status_int, 200)
        self.assertIn("version", res.json)
        self.assertIsInstance(res.json["version"], str)
        self.assertGreater(len(res.json["version"]), 0)


class TestAPIClientDownload(APIFunctionalTests):
    """Test the client download endpoint."""

    def test_download_python_client(self):
        res = self.testapp.get("/api/v1/clients/python")
        self.assertEqual(res.status_int, 200)
        self.assertIn("text/plain", res.content_type)
        self.assertIn("RemarkboxClient", res.text)
        self.assertIn("def list_threads", res.text)
        self.assertIn("def reply", res.text)
        self.assertIn("def login", res.text)
        self.assertIn("def verify", res.text)


# ---------------------------------------------------------------------------
# T8: Nesting depth enforcement via API
# ---------------------------------------------------------------------------


class TestAPIMaxNestingDepth(APIFunctionalTests):
    """API tests for T8: max nesting depth enforcement."""

    @classmethod
    def setUpClass(cls):
        try:
            APIFunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            APIFunctionalTests.setUpClass.__func__(cls)

    def setUp(self):
        from remarkbox.models.namespace import get_or_create_namespace

        ns = get_or_create_namespace(self.dbsession, "api-depth-test.example.com")
        ns.allow_anonymous = True
        # Set max nesting depth to 2 (root=0, child=1, grandchild=2, no deeper)
        ns.max_nesting_depth = 2
        self.dbsession.add(ns)
        self.dbsession.flush()
        self.namespace_name = str(ns.name)
        self.namespace_id = ns.id
        self.tm.commit()

    def tearDown(self):
        super(TestAPIMaxNestingDepth, self).tearDown()
        self.dbsession.query(UserSurrogate).filter(
            UserSurrogate.namespace_id == self.namespace_id
        ).delete(synchronize_session=False)
        self.dbsession.query(Node).filter(
            Node.namespace_id == self.namespace_id
        ).delete(synchronize_session=False)
        self.dbsession.flush()
        self.tm.commit()

    def test_reply_within_max_depth_succeeds(self):
        """Reply within max depth (depth 0 -> 1) should succeed."""
        # Create root thread (depth 0)
        create_res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "Depth Test Thread",
                "data": "Root post",
                "anonymous_name": "Bot",
            },
            expect_errors=True,
        )
        self.assertEqual(create_res.status_int, 201)
        root_id = create_res.json["node"]["id"]

        # Reply to root (creating depth 1 child) - should succeed
        reply_res = self.testapp.post_json(
            "/api/v1/threads/{}/replies".format(root_id),
            {"data": "Depth 1 reply", "anonymous_name": "Bot"},
            expect_errors=True,
        )
        self.assertEqual(reply_res.status_int, 201)

    def test_reply_at_max_depth_succeeds(self):
        """Reply creating a node at exactly max depth should succeed."""
        # Create root thread (depth 0)
        create_res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "Depth Boundary Thread",
                "data": "Root post",
                "anonymous_name": "Bot",
            },
            expect_errors=True,
        )
        root_id = create_res.json["node"]["id"]

        # Reply to root (depth 1 child) - parent.depth=0 < max=2, OK
        reply_res1 = self.testapp.post_json(
            "/api/v1/threads/{}/replies".format(root_id),
            {"data": "Depth 1 reply", "anonymous_name": "Bot"},
            expect_errors=True,
        )
        self.assertEqual(reply_res1.status_int, 201)
        child_id = reply_res1.json["node"]["id"]

        # Reply to depth-1 child (creating depth 2) - parent.depth=1 < max=2, OK
        reply_res2 = self.testapp.post_json(
            "/api/v1/threads/{}/replies".format(child_id),
            {"data": "Depth 2 reply", "anonymous_name": "Bot"},
            expect_errors=True,
        )
        self.assertEqual(reply_res2.status_int, 201)

    def test_reply_beyond_max_depth_returns_403(self):
        """Reply beyond max depth should return 403."""
        # Create root thread (depth 0)
        create_res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "Too Deep Thread",
                "data": "Root post",
                "anonymous_name": "Bot",
            },
            expect_errors=True,
        )
        root_id = create_res.json["node"]["id"]

        # Reply to root (depth 1)
        reply_res1 = self.testapp.post_json(
            "/api/v1/threads/{}/replies".format(root_id),
            {"data": "Depth 1 reply", "anonymous_name": "Bot"},
            expect_errors=True,
        )
        child_id = reply_res1.json["node"]["id"]

        # Reply to depth-1 (creating depth 2)
        reply_res2 = self.testapp.post_json(
            "/api/v1/threads/{}/replies".format(child_id),
            {"data": "Depth 2 reply", "anonymous_name": "Bot"},
            expect_errors=True,
        )
        grandchild_id = reply_res2.json["node"]["id"]

        # Reply to depth-2 (would create depth 3) - parent.depth=2 >= max=2, REJECT
        reply_res3 = self.testapp.post_json(
            "/api/v1/threads/{}/replies".format(grandchild_id),
            {"data": "Too deep reply", "anonymous_name": "Bot"},
            expect_errors=True,
        )
        self.assertEqual(reply_res3.status_int, 403)
        self.assertIn("depth", reply_res3.json["error"].lower())


class TestAPINoMaxDepthAllowsUnlimited(APIFunctionalTests):
    """API test: NULL max_nesting_depth allows unlimited nesting."""

    @classmethod
    def setUpClass(cls):
        try:
            APIFunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            APIFunctionalTests.setUpClass.__func__(cls)

    def setUp(self):
        from remarkbox.models.namespace import get_or_create_namespace

        ns = get_or_create_namespace(self.dbsession, "api-nolimit-depth.example.com")
        ns.allow_anonymous = True
        # max_nesting_depth is NULL by default = unlimited
        self.dbsession.add(ns)
        self.dbsession.flush()
        self.namespace_name = str(ns.name)
        self.namespace_id = ns.id
        self.tm.commit()

    def tearDown(self):
        super(TestAPINoMaxDepthAllowsUnlimited, self).tearDown()
        self.dbsession.query(UserSurrogate).filter(
            UserSurrogate.namespace_id == self.namespace_id
        ).delete(synchronize_session=False)
        self.dbsession.query(Node).filter(
            Node.namespace_id == self.namespace_id
        ).delete(synchronize_session=False)
        self.dbsession.flush()
        self.tm.commit()

    def test_deep_nesting_allowed_when_no_limit(self):
        """With NULL max_nesting_depth, deep nesting is allowed."""
        create_res = self.testapp.post_json(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "title": "Unlimited Depth Thread",
                "data": "Root post",
                "anonymous_name": "Bot",
            },
            expect_errors=True,
        )
        self.assertEqual(create_res.status_int, 201)
        current_id = create_res.json["node"]["id"]

        # Nest 5 levels deep - all should succeed
        for i in range(5):
            reply_res = self.testapp.post_json(
                "/api/v1/threads/{}/replies".format(current_id),
                {"data": "Reply at depth {}".format(i + 1), "anonymous_name": "Bot"},
                expect_errors=True,
            )
            self.assertEqual(reply_res.status_int, 201, "Reply at depth {} failed".format(i + 1))
            current_id = reply_res.json["node"]["id"]


# ---------------------------------------------------------------------------
# T9: Thread search API
# ---------------------------------------------------------------------------


class TestAPISearchThreads(APIFunctionalTests):
    """API tests for T9: duplicate thread prevention (AJAX search)."""

    @classmethod
    def setUpClass(cls):
        try:
            APIFunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            APIFunctionalTests.setUpClass.__func__(cls)

    def setUp(self):
        from remarkbox.models.namespace import get_or_create_namespace

        ns = get_or_create_namespace(self.dbsession, "api-search-test.example.com")
        ns.allow_anonymous = True
        self.dbsession.add(ns)
        self.dbsession.flush()
        self.namespace_name = str(ns.name)
        self.namespace_id = ns.id
        self.tm.commit()

        # Create some threads for searching
        for title in [
            "How to deploy Remarkbox",
            "How to customize themes",
            "How to moderate comments",
            "Getting started guide",
            "FAQ about pricing",
        ]:
            self.testapp.post_json(
                "/api/v1/threads",
                {
                    "namespace": self.namespace_name,
                    "title": title,
                    "data": "Content for {}".format(title),
                    "anonymous_name": "Bot",
                },
                expect_errors=True,
            )

    def tearDown(self):
        super(TestAPISearchThreads, self).tearDown()
        self.dbsession.query(UserSurrogate).filter(
            UserSurrogate.namespace_id == self.namespace_id
        ).delete(synchronize_session=False)
        self.dbsession.query(Node).filter(
            Node.namespace_id == self.namespace_id
        ).delete(synchronize_session=False)
        self.dbsession.flush()
        self.tm.commit()

    def test_search_returns_matching_threads(self):
        """Search with matching query returns relevant threads."""
        res = self.testapp.get(
            "/api/v1/threads/search",
            {"q": "How to", "namespace": self.namespace_name},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertIn("threads", res.json)
        titles = [t["title"] for t in res.json["threads"]]
        self.assertTrue(any("How to" in t for t in titles))
        # Should match the "How to" threads
        self.assertGreaterEqual(len(res.json["threads"]), 2)

    def test_search_no_matches_returns_empty(self):
        """Search with no matching query returns empty list."""
        res = self.testapp.get(
            "/api/v1/threads/search",
            {"q": "zzzznonexistent", "namespace": self.namespace_name},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.json["threads"], [])

    def test_search_without_namespace_returns_error(self):
        """Search without namespace param returns 400."""
        res = self.testapp.get(
            "/api/v1/threads/search",
            {"q": "test"},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 400)
        self.assertIn("namespace", res.json["error"])

    def test_search_short_query_returns_empty(self):
        """Search with query shorter than 2 characters returns empty list."""
        res = self.testapp.get(
            "/api/v1/threads/search",
            {"q": "H", "namespace": self.namespace_name},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.json["threads"], [])

    def test_search_empty_query_returns_empty(self):
        """Search with empty query returns empty list."""
        res = self.testapp.get(
            "/api/v1/threads/search",
            {"q": "", "namespace": self.namespace_name},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.json["threads"], [])

    def test_search_results_limited_to_10(self):
        """Search results are limited to at most 10."""
        # Create 12 threads all starting with "Limit test"
        for i in range(12):
            self.testapp.post_json(
                "/api/v1/threads",
                {
                    "namespace": self.namespace_name,
                    "title": "Limit test thread number {}".format(i),
                    "data": "Content",
                    "anonymous_name": "Bot",
                },
                expect_errors=True,
            )

        res = self.testapp.get(
            "/api/v1/threads/search",
            {"q": "Limit test", "namespace": self.namespace_name},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertLessEqual(len(res.json["threads"]), 10)

    def test_search_sql_injection_safe(self):
        """Special SQL characters in query are handled safely."""
        # These should not cause 500 errors
        for dangerous_query in [
            "'; DROP TABLE rb_node; --",
            "%_%_%",
            "test' OR '1'='1",
            "test%",
            "test_",
        ]:
            res = self.testapp.get(
                "/api/v1/threads/search",
                {"q": dangerous_query, "namespace": self.namespace_name},
                expect_errors=True,
            )
            # Should return 200 with empty or non-empty results, never 500
            self.assertIn(res.status_int, [200])
            self.assertIn("threads", res.json)

    def test_search_results_include_expected_fields(self):
        """Each search result includes id, title, and path."""
        res = self.testapp.get(
            "/api/v1/threads/search",
            {"q": "Getting", "namespace": self.namespace_name},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        self.assertGreater(len(res.json["threads"]), 0)
        thread = res.json["threads"][0]
        self.assertIn("id", thread)
        self.assertIn("title", thread)
        self.assertIn("path", thread)

    def test_search_case_insensitive(self):
        """Search is case-insensitive (ilike)."""
        res = self.testapp.get(
            "/api/v1/threads/search",
            {"q": "how to", "namespace": self.namespace_name},
            expect_errors=True,
        )
        self.assertEqual(res.status_int, 200)
        # "how to" should match "How to ..." threads
        self.assertGreater(len(res.json["threads"]), 0)

# Keep this module's tests together on one xdist worker. Test modules share a
class TestSpamEventsEndpoint(APIFunctionalTests):
    """Access control on the spam telemetry endpoint.

    Scoped to moderators and owners so a site operator can see whether their
    filter works without holding network-wide superuser.
    """

    @classmethod
    def setUpClass(cls):
        try:
            APIFunctionalTests.setUpClass.im_func(cls)
        except AttributeError:
            APIFunctionalTests.setUpClass.__func__(cls)

    def setUp(self):
        self.owner = get_or_create_user_by_email(
            self.dbsession, "spamev-owner@remarkbox.com"
        )
        self.owner_otp = self.owner.new_password()
        self.dbsession.add(self.owner)

        self.stranger = get_or_create_user_by_email(
            self.dbsession, "spamev-stranger@remarkbox.com"
        )
        self.stranger_otp = self.stranger.new_password()
        self.dbsession.add(self.stranger)
        self.dbsession.flush()

        ns = get_or_create_namespace(self.dbsession, "spamev.example.com")
        ns.set_role_for_user(self.owner, "owner")
        self.dbsession.add(ns)
        self.dbsession.flush()

        self.namespace_id = ns.id
        self.namespace_name = str(ns.name)
        self.tm.commit()

    def tearDown(self):
        super(TestSpamEventsEndpoint, self).tearDown()
        from remarkbox.models.namespace import Namespace

        ns = (
            self.dbsession.query(Namespace)
            .filter(Namespace.id == self.namespace_id)
            .one_or_none()
        )
        if ns:
            ns.owners[:] = []
            ns.moderators[:] = []
            self.dbsession.delete(ns)
        for email in (
            "spamev-owner@remarkbox.com",
            "spamev-stranger@remarkbox.com",
        ):
            user = get_user_by_email(self.dbsession, email)
            if user:
                self.dbsession.delete(user)
        self.dbsession.flush()
        self.tm.commit()

    def _log_in(self, email, otp):
        return self.testapp.post(
            "/verification-challenge?email={}&raw-otp={}&submit".format(email, otp)
        )

    def _uri(self):
        return "/api/v1/namespaces/{}/spam-events".format(self.namespace_name)

    def test_anonymous_is_rejected(self):
        res = self.testapp.get(self._uri(), status=401)
        self.assertIn("Authentication required", res.json.get("error", ""))

    def test_stranger_is_rejected(self):
        self._log_in("spamev-stranger@remarkbox.com", self.stranger_otp)
        res = self.testapp.get(self._uri(), status=403)
        self.assertIn("Moderator access required", res.json.get("error", ""))

    def test_owner_may_read(self):
        """Owners are implicit moderators, so no promotion is needed."""
        self._log_in("spamev-owner@remarkbox.com", self.owner_otp)
        res = self.testapp.get(self._uri(), status=200)
        self.assertEqual(res.json["namespace"], self.namespace_name)
        self.assertIn("summary", res.json)
        self.assertIn("events", res.json)
        for key in ("allowed", "held", "rejected", "llm_ran", "llm_inconclusive"):
            self.assertIn(key, res.json["summary"])

    def test_unknown_namespace_is_404(self):
        self._log_in("spamev-owner@remarkbox.com", self.owner_otp)
        self.testapp.get(
            "/api/v1/namespaces/nope.example.com/spam-events", status=404
        )


# per-worker database; when --dist=loadgroup deals unmarked tests out
# individually, classes from different modules interleave on a worker and one
# class's tearDownClass drop_all yanks tables from another class mid-run.
import pytest as _pytest

pytestmark = _pytest.mark.xdist_group("test_api_views")
