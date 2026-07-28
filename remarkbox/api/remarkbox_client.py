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

    def __init__(self, url, email=None, cookie_file=None, token=None):
        """
        Args:
            url: Base URL of the Remarkbox instance (e.g. https://my.remarkbox.com)
            email: Optional default email for login/verify
            cookie_file: Optional path to persist session cookies across runs.
                         If provided, cookies are loaded on init and saved
                         after login/verify. Use this to stay logged in.
            token: Optional API bearer token. Preferred over cookies for
                   unattended clients: it never expires with a session, it is
                   revocable on its own, and it authenticates writes without
                   relying on an ambient cookie. Mint one with create_token().
        """
        self.url = url.rstrip("/")
        self.email = email
        self.token = token
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
            REMARKBOX_TOKEN (optional API bearer token)
        """
        url = os.environ.get("REMARKBOX_URL")
        if not url:
            raise RemarkboxError(0, {"error": "REMARKBOX_URL environment variable not set"})
        email = os.environ.get("REMARKBOX_EMAIL")
        return cls(url, email=email, token=os.environ.get("REMARKBOX_TOKEN"))

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
        return cls(
            url,
            email=config.get("email"),
            cookie_file=config.get("cookie_file"),
            token=config.get("token"),
        )

    def _save_cookies(self):
        """Persist cookies to disk if cookie_file was provided."""
        if self._cookie_file and hasattr(self._cookie_jar, "save"):
            self._cookie_jar.save(ignore_discard=True, ignore_expires=True)

    def _request(self, method, path, body=None, headers=None):
        """Make an HTTP request and return parsed JSON."""
        url = self.url + path
        data = None
        _headers = {}

        if body is not None:
            data = json.dumps(body).encode("utf-8")
            _headers["Content-Type"] = "application/json"

        if self.token:
            _headers["Authorization"] = "Bearer {}".format(self.token)

        if headers:
            _headers.update(headers)

        req = urllib.request.Request(url, data=data, headers=_headers, method=method)

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

    def get_thread(self, node_id, limit=None, offset=None):
        """Get a thread and its replies (paginated).

        Args:
            node_id: UUID of the root thread node
            limit: Maximum replies to return (default 100, max 500)
            offset: Number of replies to skip (default 0)

        Returns:
            dict with keys: namespace, thread, replies, total_replies,
            page, limit, offset, has_more
        """
        params = {}
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        path = "/api/v1/threads/{}".format(node_id)
        if params:
            path += "?" + urllib.parse.urlencode(params)
        return self._request("GET", path)

    def create_thread(self, namespace, title, data, anonymous_name=None, email=None,
                       source_format=None):
        """Create a new thread.

        Args:
            namespace: Target namespace name
            title: Thread title
            data: Content (max 500000 chars)
            anonymous_name: Name for anonymous posting (optional)
            email: Email to associate with post (optional)
            source_format: Input format — markdown (default), html, rst,
                mediawiki, latex, textile, org, etc. (any pandoc input format)

        Returns:
            dict with keys: node, verified
        """
        body = {"namespace": namespace, "title": title, "data": data}
        if anonymous_name:
            body["anonymous_name"] = anonymous_name
        if email:
            body["email"] = email
        if source_format:
            body["source_format"] = source_format
        return self._request("POST", "/api/v1/threads", body)

    # ----- Replies -----

    def reply(self, node_id, data, anonymous_name=None, email=None, source_format=None):
        """Reply to a thread or another reply.

        Args:
            node_id: UUID of the parent node (thread or reply)
            data: Content (max 500000 chars)
            anonymous_name: Name for anonymous posting (optional)
            email: Email to associate with post (optional)
            source_format: Input format (default: markdown)

        Returns:
            dict with keys: node, verified
        """
        body = {"data": data}
        if anonymous_name:
            body["anonymous_name"] = anonymous_name
        if email:
            body["email"] = email
        if source_format:
            body["source_format"] = source_format
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

    def edit_node(self, node_id, data=None, title=None, source_format=None):
        """Edit a node (requires authentication).

        Args:
            node_id: UUID of the node to edit
            data: New content (optional)
            title: New title, only for root nodes (optional)
            source_format: Input format (default: markdown)

        Returns:
            dict with key: node
        """
        body = {}
        if data is not None:
            body["data"] = data
        if title is not None:
            body["title"] = title
        if source_format is not None:
            body["source_format"] = source_format
        if not body:
            raise ValueError("data or title is required")
        return self._request("PATCH", "/api/v1/nodes/{}".format(node_id), body)

    def disable_node(self, node_id):
        """Disable a node (requires authentication, moderator or owner).

        Args:
            node_id: UUID of the node to disable

        Returns:
            dict with key: node
        """
        return self._request("PATCH", "/api/v1/nodes/{}".format(node_id), {"disabled": True})

    def enable_node(self, node_id):
        """Enable a previously disabled node (requires authentication, moderator or owner).

        Args:
            node_id: UUID of the node to enable

        Returns:
            dict with key: node
        """
        return self._request("PATCH", "/api/v1/nodes/{}".format(node_id), {"disabled": False})

    def approve_node(self, node_id):
        """Approve a node (requires authentication, moderator or owner).

        Args:
            node_id: UUID of the node to approve

        Returns:
            dict with key: node
        """
        return self._request("PATCH", "/api/v1/nodes/{}".format(node_id), {"approved": True})

    def lock_node(self, node_id):
        """Lock a thread (requires authentication, moderator or owner). Root nodes only.

        Args:
            node_id: UUID of the root node to lock

        Returns:
            dict with key: node
        """
        return self._request("PATCH", "/api/v1/nodes/{}".format(node_id), {"locked": True})

    def unlock_node(self, node_id):
        """Unlock a thread (requires authentication, moderator or owner). Root nodes only.

        Args:
            node_id: UUID of the root node to unlock

        Returns:
            dict with key: node
        """
        return self._request("PATCH", "/api/v1/nodes/{}".format(node_id), {"locked": False})

    def delete_node(self, node_id, sudo_otp=None):
        """Delete a node permanently (requires moderator + sudo OTP).

        First call without sudo_otp returns 202 and emails a code.
        Second call with the code performs the deletion.

        Args:
            node_id: UUID of the node to delete
            sudo_otp: 8-digit confirmation code from email (optional)

        Returns:
            dict with key: deleted (the node ID), or status/message if OTP required
        """
        headers = {}
        if sudo_otp:
            headers["X-Sudo-OTP"] = sudo_otp
        return self._request("DELETE", "/api/v1/nodes/{}".format(node_id), headers=headers)

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

    # ----- API tokens -----

    def create_token(self, name=None):
        """Mint an API bearer token for the logged-in user.

        Requires cookie authentication: a token cannot mint another token, so
        a leaked one cannot multiply itself. Log in first, then call this.

        The raw token comes back exactly once, under key "token" — store it
        then, because only its hash is kept server-side.

        Returns:
            dict with keys: id, name, created, last_used, token, warning
        """
        return self._request("POST", "/api/v1/user/tokens", {"name": name})

    def list_tokens(self):
        """List our live tokens, metadata only. Requires cookie authentication.

        Returns:
            dict with key: tokens (list of id, name, created, last_used)
        """
        return self._request("GET", "/api/v1/user/tokens")

    def revoke_token(self, token_id):
        """Revoke one of our tokens. Requires cookie authentication.

        Returns:
            dict with keys: revoked, id
        """
        return self._request("DELETE", "/api/v1/user/tokens/{}".format(token_id))

    # ----- Export -----

    def export_formats(self):
        """List all available export formats.

        Returns:
            dict with keys: formats (list of strings), count
        """
        return self._request("GET", "/api/v1/export/formats")

    def export_thread(self, node_id, fmt="markdown"):
        """Export a thread in the specified format.

        Args:
            node_id: UUID of the root thread node
            fmt: Pandoc output format (e.g. markdown, html5, pdf, epub, docx)

        Returns:
            bytes (binary formats) or str (text formats)
        """
        return self._raw_request(
            "GET", "/api/v1/export/threads/{}.{}".format(node_id, fmt)
        )

    def export_namespace(self, namespace, fmt="markdown"):
        """Export an entire namespace as a book in the specified format.

        Args:
            namespace: Namespace name (e.g. "meta.remarkbox.com")
            fmt: Pandoc output format

        Returns:
            bytes (binary formats) or str (text formats)
        """
        return self._raw_request(
            "GET", "/api/v1/export/namespace/{}.{}".format(namespace, fmt)
        )

    def export_node(self, node_id, fmt="markdown"):
        """Export a node and its subtree in the specified format (on-demand).

        Args:
            node_id: UUID of the node
            fmt: Pandoc output format

        Returns:
            bytes (binary formats) or str (text formats)
        """
        return self._raw_request(
            "GET", "/api/v1/export/nodes/{}.{}".format(node_id, fmt)
        )

    def _raw_request(self, method, path):
        """Make an HTTP request and return raw response body."""
        url = self.url + path
        req = urllib.request.Request(url, method=method)
        try:
            resp = self._opener.open(req)
            content_type = resp.headers.get("Content-Type", "")
            body = resp.read()
            if "text/" in content_type or "json" in content_type or "xml" in content_type:
                return body.decode("utf-8")
            return body
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8")
            try:
                body = json.loads(raw)
            except Exception:
                body = {"error": raw}
            raise RemarkboxError(e.code, body)

    # ----- Wiki / Revisions -----

    def wiki_edit(self, node_id, data, source_format=None):
        """Wiki-edit a node (creates revision, any authenticated user if wiki mode).

        Args:
            node_id: UUID of the node to edit
            data: New content
            source_format: Input format (default: markdown)

        Returns:
            dict with key: node
        """
        body = {"data": data}
        if source_format:
            body["source_format"] = source_format
        return self._request("POST", "/api/v1/nodes/{}/wiki-edit".format(node_id), body)

    def get_revisions(self, node_id):
        """Get revision history for a node.

        Args:
            node_id: UUID of the node

        Returns:
            dict with keys: node_id, revisions, count
        """
        return self._request("GET", "/api/v1/nodes/{}/revisions".format(node_id))

    def get_revision(self, revision_id):
        """Get a specific revision by ID.

        Args:
            revision_id: UUID of the revision

        Returns:
            dict with key: revision
        """
        return self._request("GET", "/api/v1/revisions/{}".format(revision_id))

    def diff_revisions(self, revision_id, other_id):
        """Compare two revisions of the same node via unified diff.

        Args:
            revision_id: UUID of the first (from) revision
            other_id: UUID of the second (to) revision

        Returns:
            dict with keys: from_revision, to_revision, from_number,
            to_number, node_id, diff
        """
        return self._request(
            "GET", "/api/v1/revisions/{}/diff/{}".format(revision_id, other_id)
        )

    # ----- Themes -----

    def get_theme_css(self, namespace):
        """Get the auto-generated theme CSS for a namespace.

        Args:
            namespace: Namespace name

        Returns:
            CSS string
        """
        return self._raw_request(
            "GET", "/api/v1/themes/{}/css".format(namespace)
        )

    def get_theme_preview(self, namespace):
        """Get theme palette preview for a namespace.

        Args:
            namespace: Namespace name

        Returns:
            dict with keys: namespace, palette, css_url
        """
        return self._request(
            "GET", "/api/v1/themes/{}/preview".format(namespace)
        )

    # ----- Admin (superuser only) -----

    def admin_list_namespaces(self):
        """List all namespaces (requires superuser).

        Returns:
            dict with key: namespaces (list of namespace dicts)
        """
        return self._request("GET", "/api/v1/admin/namespaces")

    def admin_recent_nodes(self, days=7, limit=100):
        """List recent nodes across all namespaces (requires superuser).

        Args:
            days: Number of days to look back (default 7, max 90)
            limit: Max results (default 100, max 500)

        Returns:
            dict with keys: days, count, nodes
        """
        params = urllib.parse.urlencode({"days": days, "limit": limit})
        return self._request("GET", "/api/v1/admin/recent-nodes?" + params)


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
    disable <node_id>                       Disable a node (auth required)
    enable <node_id>                        Enable a node (auth required)
    approve <node_id>                       Approve a node (auth required)
    lock <node_id>                          Lock a thread (auth required)
    unlock <node_id>                        Unlock a thread (auth required)
    delete <node_id>                        Delete a node (moderator only)
    login <email>                           Request OTP
    verify <email> <otp>                    Verify OTP
    formats                                 List export formats
    export-thread <node_id> [format]        Export thread (default: markdown)
    export-ns <namespace> [format]          Export namespace as book
    export-node <node_id> [format]          Export node subtree

Examples:
    python remarkbox_client.py https://my.remarkbox.com threads meta.remarkbox.com
    python remarkbox_client.py https://my.remarkbox.com export-ns meta.remarkbox.com epub
    python remarkbox_client.py https://my.remarkbox.com export-thread <node_id> pdf
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
        elif cmd == "disable" and len(args) >= 1:
            result = client.disable_node(args[0])
        elif cmd == "enable" and len(args) >= 1:
            result = client.enable_node(args[0])
        elif cmd == "approve" and len(args) >= 1:
            result = client.approve_node(args[0])
        elif cmd == "lock" and len(args) >= 1:
            result = client.lock_node(args[0])
        elif cmd == "unlock" and len(args) >= 1:
            result = client.unlock_node(args[0])
        elif cmd == "delete" and len(args) >= 1:
            result = client.delete_node(args[0])
        elif cmd == "login" and len(args) >= 1:
            result = client.login(args[0])
        elif cmd == "verify" and len(args) >= 2:
            result = client.verify(args[0], args[1])
        elif cmd == "formats":
            result = client.export_formats()
        elif cmd == "export-thread" and len(args) >= 1:
            fmt = args[1] if len(args) > 1 else "markdown"
            output = client.export_thread(args[0], fmt)
            if isinstance(output, bytes):
                sys.stdout.buffer.write(output)
            else:
                print(output)
            sys.exit(0)
        elif cmd == "export-ns" and len(args) >= 1:
            fmt = args[1] if len(args) > 1 else "markdown"
            output = client.export_namespace(args[0], fmt)
            if isinstance(output, bytes):
                sys.stdout.buffer.write(output)
            else:
                print(output)
            sys.exit(0)
        elif cmd == "export-node" and len(args) >= 1:
            fmt = args[1] if len(args) > 1 else "markdown"
            output = client.export_node(args[0], fmt)
            if isinstance(output, bytes):
                sys.stdout.buffer.write(output)
            else:
                print(output)
            sys.exit(0)
        else:
            print(usage)
            sys.exit(1)

        print(json.dumps(result, indent=2))

    except RemarkboxError as e:
        print(json.dumps({"error": str(e), "status": e.status}, indent=2), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
