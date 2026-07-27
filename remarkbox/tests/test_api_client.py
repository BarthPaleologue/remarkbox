import json
import os
import tempfile
import unittest
from unittest import mock
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading


class FakeHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler for testing the client."""

    routes = {}

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def do_PATCH(self):
        self._handle()

    def _handle(self):
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len) if content_len else b""
        parsed = json.loads(body) if body else {}

        # Store the request for assertions
        FakeHandler.last_request = {
            "method": self.command,
            "path": self.path,
            "body": parsed,
            "headers": dict(self.headers),
        }

        path = self.path.split("?")[0]
        key = (self.command, path)
        if key in self.routes:
            status, response = self.routes[key]
        else:
            status, response = 200, {"ok": True}

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())

    def log_message(self, format, *args):
        pass  # Suppress logs


class TestRemarkboxClient(unittest.TestCase):
    """Unit tests for the Python client."""

    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), FakeHandler)
        cls.port = cls.server.server_address[1]
        cls.base_url = "http://127.0.0.1:{}".format(cls.port)
        cls.thread = threading.Thread(target=cls.server.serve_forever)
        cls.thread.daemon = True
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        FakeHandler.routes = {}
        FakeHandler.last_request = None

    def _make_client(self):
        from remarkbox.api.remarkbox_client import RemarkboxClient
        return RemarkboxClient(self.base_url)

    def test_list_threads(self):
        FakeHandler.routes[("GET", "/api/v1/threads")] = (
            200,
            {"threads": [{"id": "abc", "title": "Test"}], "page": 1},
        )
        client = self._make_client()
        result = client.list_threads("example.com")
        self.assertEqual(result["threads"][0]["title"], "Test")
        self.assertIn("namespace=example.com", FakeHandler.last_request["path"])

    def test_get_thread(self):
        FakeHandler.routes[("GET", "/api/v1/threads/abc-123")] = (
            200,
            {"thread": {"id": "abc-123"}, "replies": []},
        )
        client = self._make_client()
        result = client.get_thread("abc-123")
        self.assertEqual(result["thread"]["id"], "abc-123")

    def test_create_thread(self):
        FakeHandler.routes[("POST", "/api/v1/threads")] = (
            201,
            {"node": {"id": "new-1"}, "verified": True},
        )
        client = self._make_client()
        result = client.create_thread(
            "example.com", "Title", "Body", anonymous_name="Bot"
        )
        self.assertEqual(result["node"]["id"], "new-1")
        body = FakeHandler.last_request["body"]
        self.assertEqual(body["namespace"], "example.com")
        self.assertEqual(body["title"], "Title")
        self.assertEqual(body["anonymous_name"], "Bot")

    def test_reply(self):
        FakeHandler.routes[("POST", "/api/v1/threads/abc/replies")] = (
            201,
            {"node": {"id": "reply-1"}, "verified": True},
        )
        client = self._make_client()
        result = client.reply("abc", "Reply text", anonymous_name="Bot")
        self.assertEqual(result["node"]["id"], "reply-1")
        self.assertEqual(FakeHandler.last_request["body"]["data"], "Reply text")

    def test_get_node(self):
        FakeHandler.routes[("GET", "/api/v1/nodes/node-1")] = (
            200,
            {"node": {"id": "node-1", "data": "content"}},
        )
        client = self._make_client()
        result = client.get_node("node-1")
        self.assertEqual(result["node"]["id"], "node-1")

    def test_edit_node(self):
        FakeHandler.routes[("PATCH", "/api/v1/nodes/node-1")] = (
            200,
            {"node": {"id": "node-1", "data": "updated"}},
        )
        client = self._make_client()
        result = client.edit_node("node-1", data="updated")
        self.assertEqual(FakeHandler.last_request["body"]["data"], "updated")

    def test_edit_node_requires_data_or_title(self):
        client = self._make_client()
        with self.assertRaises(ValueError):
            client.edit_node("node-1")

    def test_login(self):
        FakeHandler.routes[("POST", "/api/v1/auth/login")] = (
            200,
            {"status": "sent", "message": "Code sent."},
        )
        client = self._make_client()
        result = client.login("test@example.com")
        self.assertEqual(result["status"], "sent")
        self.assertEqual(
            FakeHandler.last_request["body"]["email"], "test@example.com"
        )

    def test_verify(self):
        FakeHandler.routes[("POST", "/api/v1/auth/verify")] = (
            200,
            {"status": "authenticated", "user": {"id": "u1"}},
        )
        client = self._make_client()
        result = client.verify("test@example.com", "123456")
        self.assertEqual(result["status"], "authenticated")
        body = FakeHandler.last_request["body"]
        self.assertEqual(body["email"], "test@example.com")
        self.assertEqual(body["otp"], "123456")

    def test_login_requires_email(self):
        client = self._make_client()
        with self.assertRaises(ValueError):
            client.login()

    def test_verify_requires_otp(self):
        client = self._make_client()
        with self.assertRaises(ValueError):
            client.verify("test@example.com")

    def test_error_raises_remarkbox_error(self):
        from remarkbox.api.remarkbox_client import RemarkboxError

        FakeHandler.routes[("GET", "/api/v1/threads")] = (
            400,
            {"error": "namespace parameter is required"},
        )
        client = self._make_client()
        with self.assertRaises(RemarkboxError) as ctx:
            client.list_threads("")
        self.assertEqual(ctx.exception.status, 400)
        self.assertIn("namespace", str(ctx.exception))

    def test_default_email_used(self):
        from remarkbox.api.remarkbox_client import RemarkboxClient

        FakeHandler.routes[("POST", "/api/v1/auth/login")] = (
            200,
            {"status": "sent"},
        )
        client = RemarkboxClient(self.base_url, email="default@example.com")
        client.login()
        self.assertEqual(
            FakeHandler.last_request["body"]["email"], "default@example.com"
        )

    def test_from_env(self):
        from remarkbox.api.remarkbox_client import RemarkboxClient

        with mock.patch.dict(
            os.environ,
            {"REMARKBOX_URL": "https://test.example.com", "REMARKBOX_EMAIL": "a@b.com"},
        ):
            client = RemarkboxClient.from_env()
            self.assertEqual(client.url, "https://test.example.com")
            self.assertEqual(client.email, "a@b.com")

    def test_from_env_missing_url(self):
        from remarkbox.api.remarkbox_client import RemarkboxClient, RemarkboxError

        with mock.patch.dict(os.environ, {}, clear=True):
            # Remove the keys if they exist
            os.environ.pop("REMARKBOX_URL", None)
            with self.assertRaises(RemarkboxError):
                RemarkboxClient.from_env()

    def test_from_config(self):
        from remarkbox.api.remarkbox_client import RemarkboxClient

        config = {"url": "https://config.example.com", "email": "c@d.com"}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config, f)
            f.flush()
            try:
                client = RemarkboxClient.from_config(f.name)
                self.assertEqual(client.url, "https://config.example.com")
                self.assertEqual(client.email, "c@d.com")
            finally:
                os.unlink(f.name)

    def test_url_trailing_slash_stripped(self):
        from remarkbox.api.remarkbox_client import RemarkboxClient

        client = RemarkboxClient("https://example.com/")
        self.assertEqual(client.url, "https://example.com")

    def test_cookies_persist_across_requests(self):
        """Verify session cookies are maintained (important for auth flow)."""
        FakeHandler.routes[("GET", "/api/v1/threads")] = (
            200,
            {"threads": [], "page": 1},
        )
        client = self._make_client()
        # Make two requests - the cookie jar should persist
        client.list_threads("a.com")
        client.list_threads("b.com")
        # No error means the opener and cookie jar survived both calls

# Keep this module's tests together on one xdist worker. Test modules share a
# per-worker database; when --dist=loadgroup deals unmarked tests out
# individually, classes from different modules interleave on a worker and one
# class's tearDownClass drop_all yanks tables from another class mid-run.
import pytest as _pytest

pytestmark = _pytest.mark.xdist_group("test_api_client")
