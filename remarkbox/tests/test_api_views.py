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
