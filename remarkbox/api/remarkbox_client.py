"""
Remarkbox API Client (Python, stdlib only)

Download:
    curl -s https://REMARKBOX/api/v1/clients/python -o remarkbox_client.py
    wget -q https://REMARKBOX/api/v1/clients/python -O remarkbox_client.py

Quick start:
    from remarkbox_client import RemarkboxClient

    client = RemarkboxClient("https://my.remarkbox.com")

    # List threads
    result = client.list_threads("meta.remarkbox.com")
    for thread in result["threads"]:
        print(thread["title"])

    # Read a thread and its replies
    thread = client.get_thread(thread_id)
    for reply in thread["replies"]:
        print(reply["data"])

    # Post anonymously (namespace must allow anonymous)
    node = client.create_thread(
        namespace="meta.remarkbox.com",
        title="Hello from Python",
        data="This is a test post.",
        anonymous_name="MyBot",
    )

    # Reply to a thread
    reply = client.reply(node["node"]["id"], data="Nice thread!")

    # Authenticate via email OTP
    client.login("agent@example.com")
    # ... check inbox for 6-digit code ...
    client.verify("agent@example.com", "123456")

    # Now requests are authenticated
    thread = client.create_thread(
        namespace="meta.remarkbox.com",
        title="Verified post",
        data="Posted with a session.",
    )

    # Edit your own post
    client.edit_node(thread["node"]["id"], data="Updated content.")

Configuration:
    # From arguments (highest priority)
    client = RemarkboxClient("https://my.remarkbox.com")

    # From environment variables
    #   REMARKBOX_URL=https://my.remarkbox.com
    #   REMARKBOX_EMAIL=agent@example.com
    client = RemarkboxClient.from_env()

    # From config file (~/.config/remarkbox/config.json)
    #   {"url": "https://my.remarkbox.com", "email": "agent@example.com"}
    client = RemarkboxClient.from_config()

Requires: Python 3.6+ (stdlib only, no pip install needed)
License: Same as Remarkbox
"""

import json
import os
import http.cookiejar
import urllib.request
import urllib.error
import urllib.parse


__version__ = "0.1.0"


class RemarkboxError(Exception):
    """Raised when the API returns an error response."""

    def __init__(self, status, body):
        self.status = status
        self.body = body
        msg = body.get("error", str(body)) if isinstance(body, dict) else str(body)
        super().__init__("HTTP {}: {}".format(status, msg))


class RemarkboxClient:
    """Remarkbox API client. Manages sessions via cookies automatically."""

    def __init__(self, url, email=None, cookie_file=None):
        """
        Args:
            url: Base URL of the Remarkbox instance (e.g. https://my.remarkbox.com)
            email: Optional default email for login/verify
            cookie_file: Optional path to persist session cookies across runs.
                         If provided, cookies are loaded on init and saved
                         after login/verify. Use this to stay logged in.
        """
        self.url = url.rstrip("/")
        self.email = email
        self._cookie_file = cookie_file
        if cookie_file:
            self._cookie_jar = http.cookiejar.MozillaCookieJar(cookie_file)
            if os.path.exists(cookie_file):
                self._cookie_jar.load(ignore_discard=True, ignore_expires=True)
        else:
            self._cookie_jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._cookie_jar)
        )

    @classmethod
    def from_env(cls):
        """Create client from environment variables.

        Reads:
            REMARKBOX_URL (required)
            REMARKBOX_EMAIL (optional)
        """
        url = os.environ.get("REMARKBOX_URL")
        if not url:
            raise RemarkboxError(0, {"error": "REMARKBOX_URL environment variable not set"})
        email = os.environ.get("REMARKBOX_EMAIL")
        return cls(url, email=email)

    @classmethod
    def from_config(cls, path=None):
        """Create client from a JSON config file.

        Default path: ~/.config/remarkbox/config.json

        Config format:
            {"url": "https://my.remarkbox.com", "email": "agent@example.com"}
        """
        if path is None:
            path = os.path.join(
                os.path.expanduser("~"), ".config", "remarkbox", "config.json"
            )
        with open(path) as f:
            config = json.load(f)
        url = config.get("url")
        if not url:
            raise RemarkboxError(0, {"error": "url is required in config file"})
        return cls(url, email=config.get("email"), cookie_file=config.get("cookie_file"))

    def _save_cookies(self):
        """Persist cookies to disk if cookie_file was provided."""
        if self._cookie_file and hasattr(self._cookie_jar, "save"):
            self._cookie_jar.save(ignore_discard=True, ignore_expires=True)

    def _request(self, method, path, body=None):
        """Make an HTTP request and return parsed JSON."""
        url = self.url + path
        data = None
        headers = {}

        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            resp = self._opener.open(req)
            raw = resp.read().decode("utf-8")
            try:
                return json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                raise RemarkboxError(resp.status, {"error": "Non-JSON response"})
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8")
            try:
                body = json.loads(raw)
            except Exception:
                body = {"error": raw}
            raise RemarkboxError(e.code, body)

    # ----- Version -----

    def version(self):
        """Get the deployed version (git commit hash).

        Returns:
            dict with key: version
        """
        return self._request("GET", "/api/v1/version")

    # ----- Threads -----

    def list_threads(self, namespace, page=1):
        """List threads in a namespace.

        Args:
            namespace: The namespace name (e.g. "meta.remarkbox.com")
            page: Page number (default 1)

        Returns:
            dict with keys: namespace, threads, page, page_size
        """
        params = urllib.parse.urlencode({"namespace": namespace, "page": page})
        return self._request("GET", "/api/v1/threads?" + params)

    def get_thread(self, node_id):
        """Get a thread and all its replies.

        Args:
            node_id: UUID of the root thread node

        Returns:
            dict with keys: namespace, thread, replies
        """
        return self._request("GET", "/api/v1/threads/{}".format(node_id))

    def create_thread(self, namespace, title, data, anonymous_name=None, email=None):
        """Create a new thread.

        Args:
            namespace: Target namespace name
            title: Thread title
            data: Markdown content (max 500000 chars)
            anonymous_name: Name for anonymous posting (optional)
            email: Email to associate with post (optional)

        Returns:
            dict with keys: node, verified
        """
        body = {"namespace": namespace, "title": title, "data": data}
        if anonymous_name:
            body["anonymous_name"] = anonymous_name
        if email:
            body["email"] = email
        return self._request("POST", "/api/v1/threads", body)

    # ----- Replies -----

    def reply(self, node_id, data, anonymous_name=None, email=None):
        """Reply to a thread or another reply.

        Args:
            node_id: UUID of the parent node (thread or reply)
            data: Markdown content (max 500000 chars)
            anonymous_name: Name for anonymous posting (optional)
            email: Email to associate with post (optional)

        Returns:
            dict with keys: node, verified
        """
        body = {"data": data}
        if anonymous_name:
            body["anonymous_name"] = anonymous_name
        if email:
            body["email"] = email
        return self._request("POST", "/api/v1/threads/{}/replies".format(node_id), body)

    # ----- Nodes -----

    def get_node(self, node_id):
        """Get a single node by ID.

        Args:
            node_id: UUID of the node

        Returns:
            dict with key: node
        """
        return self._request("GET", "/api/v1/nodes/{}".format(node_id))

    def edit_node(self, node_id, data=None, title=None):
        """Edit a node (requires authentication).

        Args:
            node_id: UUID of the node to edit
            data: New markdown content (optional)
            title: New title, only for root nodes (optional)

        Returns:
            dict with key: node
        """
        body = {}
        if data is not None:
            body["data"] = data
        if title is not None:
            body["title"] = title
        if not body:
            raise ValueError("data or title is required")
        return self._request("PATCH", "/api/v1/nodes/{}".format(node_id), body)

    # ----- Auth -----

    def login(self, email=None):
        """Request an OTP code be sent to the email address.

        Args:
            email: Email address (uses self.email if not provided)

        Returns:
            dict with keys: status, message
        """
        email = email or self.email
        if not email:
            raise ValueError("email is required")
        return self._request("POST", "/api/v1/auth/login", {"email": email})

    def verify(self, email=None, otp=None):
        """Verify an OTP code and establish an authenticated session.

        After calling this, subsequent requests are authenticated
        via the session cookie (managed automatically).

        Args:
            email: Email address (uses self.email if not provided)
            otp: The 6-digit verification code from email

        Returns:
            dict with keys: status, user
        """
        email = email or self.email
        if not email:
            raise ValueError("email is required")
        if not otp:
            raise ValueError("otp is required")
        result = self._request("POST", "/api/v1/auth/verify", {"email": email, "otp": otp})
        self._save_cookies()
        return result

    # ----- Profile -----

    def get_profile(self):
        """Get the current authenticated user's profile.

        Returns:
            dict with key: user (id, name, email)
        """
        return self._request("GET", "/api/v1/user/profile")

    def update_profile(self, name):
        """Update the current user's display name.

        Args:
            name: New display name (alphanumeric and dashes only)

        Returns:
            dict with key: user (id, name, email)
        """
        return self._request("PATCH", "/api/v1/user/profile", {"name": name})


# ----- CLI -----

def main():
    """Simple CLI for quick testing."""
    import sys

    usage = """Usage: python remarkbox_client.py <url> <command> [args...]

Commands:
    threads <namespace>                     List threads
    thread <node_id>                        Get thread with replies
    node <node_id>                          Get a single node
    post <namespace> <title> <data> [name]  Create thread (anonymous)
    reply <node_id> <data> [name]           Reply to thread (anonymous)
    login <email>                           Request OTP
    verify <email> <otp>                    Verify OTP

Examples:
    python remarkbox_client.py https://my.remarkbox.com threads meta.remarkbox.com
    python remarkbox_client.py https://my.remarkbox.com post meta.remarkbox.com "Hello" "World" MyBot
"""

    if len(sys.argv) < 3:
        print(usage)
        sys.exit(1)

    url = sys.argv[1]
    cmd = sys.argv[2]
    args = sys.argv[3:]
    client = RemarkboxClient(url)

    try:
        if cmd == "threads" and len(args) >= 1:
            result = client.list_threads(args[0])
        elif cmd == "thread" and len(args) >= 1:
            result = client.get_thread(args[0])
        elif cmd == "node" and len(args) >= 1:
            result = client.get_node(args[0])
        elif cmd == "post" and len(args) >= 3:
            name = args[3] if len(args) > 3 else None
            result = client.create_thread(args[0], args[1], args[2], anonymous_name=name)
        elif cmd == "reply" and len(args) >= 2:
            name = args[2] if len(args) > 2 else None
            result = client.reply(args[0], args[1], anonymous_name=name)
        elif cmd == "login" and len(args) >= 1:
            result = client.login(args[0])
        elif cmd == "verify" and len(args) >= 2:
            result = client.verify(args[0], args[1])
        else:
            print(usage)
            sys.exit(1)

        print(json.dumps(result, indent=2))

    except RemarkboxError as e:
        print(json.dumps({"error": str(e), "status": e.status}, indent=2), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
