"""Security regression tests.

Each test here pins down a defect found in our 2026-07-27 security audit
(docs/security-audit-2026-07-27.md), which is where the finding IDs live.

Tests assert the SECURE behaviour. Where a defect is still unfixed, its test
is marked `xfail(strict=True)` so it fails loudly the moment someone fixes
it — drop the marker then and it becomes a permanent regression guard.
"""

import transaction
import unittest
import webtest

import pytest

from remarkbox.models import (
    Node,
    get_tm_session,
    get_or_create_user_by_email,
    get_or_create_namespace,
)

from remarkbox.models.meta import Base
from remarkbox.models.node import create_root_node

from pyramid.paster import get_appsettings


# Schema lives at module scope. Each test class creating and dropping every
# table in its own setUpClass/tearDownClass would pull the tables out from
# under sibling classes mid-module — that pollution produced phantom failures
# in the controls before this was hoisted.
_STATE = {}


def setUpModule():
    from remarkbox import main

    settings = get_appsettings("test.ini")
    app = main({}, **settings)
    session_factory = app.registry["dbsession_factory"]
    engine = session_factory.kw["bind"]
    Base.metadata.create_all(bind=engine)
    _STATE.update(
        settings=settings,
        app=app,
        testapp=webtest.TestApp(app),
        session_factory=session_factory,
        engine=engine,
        tm=transaction.manager,
        dbsession=get_tm_session(session_factory, transaction.manager),
    )


def tearDownModule():
    # Close our session but do NOT call Base.metadata.drop_all(): that is
    # global, and pytest-xdist interleaves modules onto shared workers, so
    # dropping here would pull tables out from under a sibling module still
    # running. conftest.pytest_unconfigure() deletes each worker's database
    # file at session end, so the schema is still cleaned up.
    #
    # The six older test modules DO drop in their tearDownClass, which is a
    # pre-existing source of cross-module flakiness (test_push.py carries a
    # comment describing the breakage it causes). Removing those drops was
    # tried on 2026-07-27 and made the suite worse, not better — the real fix
    # is per-test isolation, tracked separately. This module simply declines
    # to add a seventh dropper.
    _STATE["dbsession"].close()


class SecurityFunctionalTests(unittest.TestCase, object):
    """Base class for security functional tests."""

    @classmethod
    def setUpClass(cls):
        cls.settings = _STATE["settings"]
        cls.app = _STATE["app"]
        cls.testapp = _STATE["testapp"]
        cls.session_factory = _STATE["session_factory"]
        cls.engine = _STATE["engine"]
        cls.tm = _STATE["tm"]
        cls.dbsession = _STATE["dbsession"]

    def tearDown(self):
        self.testapp.get("/log-out")

    # -- helpers ----------------------------------------------------------

    def make_thread(self, namespace, title, data, **flags):
        """Create a root node in a namespace with arbitrary moderation flags."""
        user = get_or_create_user_by_email(self.dbsession, "sec-author@example.com")
        user.verified = True
        root = create_root_node()
        root.namespace = namespace
        root.user = user
        root.title = title
        root.verified = flags.get("verified", True)
        root.disabled = flags.get("disabled", False)
        root.approved = flags.get("approved", True)
        root.set_data(data, namespace=namespace, dbsession=self.dbsession)
        self.dbsession.add(root)
        self.dbsession.flush()
        return root

    def make_reply(self, root, data, **flags):
        """Create a child node under a root with arbitrary moderation flags."""
        user = get_or_create_user_by_email(self.dbsession, "sec-replier@example.com")
        user.verified = True
        child = root.new_child()
        child.user = user
        child.namespace = root.namespace
        child.verified = flags.get("verified", True)
        child.disabled = flags.get("disabled", False)
        child.approved = flags.get("approved", True)
        child.set_data(data, namespace=root.namespace, dbsession=self.dbsession)
        self.dbsession.add(child)
        self.dbsession.flush()
        return child


# ---------------------------------------------------------------------------
# Export must apply the same moderation visibility filters as every other read
# ---------------------------------------------------------------------------


class TestExportRespectsModerationVisibility(SecurityFunctionalTests):
    """/api/v1/export/* used to filter only `disabled`, ignoring the namespace's
    `hide_unless_approved` / `hide_unverified` settings that every other read
    path honours. Content held in a moderation queue is served to anonymous
    callers as markdown."""


    def setUp(self):
        ns = get_or_create_namespace(self.dbsession, "export-moderation.example.com")
        ns.hide_unless_approved = True
        ns.hide_unverified = True
        self.dbsession.add(ns)
        self.dbsession.flush()
        self.namespace = ns
        self.namespace_name = str(ns.name)
        self.namespace_id = ns.id

        self.root = self.make_thread(ns, "exported public thread", "public body")
        # A reply held for moderation — invisible in the web UI and in
        # /api/v1/threads/{id}, which both apply approved/verified filters.
        self.held = self.make_reply(
            self.root, "QUARANTINED-SECRET-BODY", approved=False, verified=False
        )
        self.root_id = str(self.root.id)
        self.tm.commit()

    def test_thread_json_hides_unapproved_reply(self):
        """Control: the JSON thread endpoint correctly hides held content."""
        res = self.testapp.get("/api/v1/threads/{}".format(self.root_id), status=200)
        self.assertNotIn("QUARANTINED-SECRET-BODY", res.body.decode("utf-8"))

    def test_export_thread_hides_unapproved_reply(self):
        """Export of the same thread must not leak moderation-held content."""
        res = self.testapp.get(
            "/api/v1/export/threads/{}.markdown".format(self.root_id), status=200
        )
        self.assertNotIn("QUARANTINED-SECRET-BODY", res.body.decode("utf-8"))

    def test_export_namespace_hides_unapproved_reply(self):
        """Namespace book export must not leak moderation-held content."""
        res = self.testapp.get(
            "/api/v1/export/namespace/{}.markdown".format(self.namespace_name),
            status=200,
        )
        self.assertNotIn("QUARANTINED-SECRET-BODY", res.body.decode("utf-8"))


class TestExportRefusesDisabledThreads(SecurityFunctionalTests):
    """`api_export_thread` used to fetch the root by id and render it without
    ever checking `root.disabled`. A thread a moderator has removed is still
    fully exportable by anyone holding (or guessing from logs/feeds) its id."""


    def setUp(self):
        ns = get_or_create_namespace(self.dbsession, "export-disabled.example.com")
        self.dbsession.add(ns)
        self.dbsession.flush()
        self.namespace_id = ns.id
        # A thread a moderator has taken down.
        self.root = self.make_thread(
            ns, "moderator-removed thread", "REMOVED-THREAD-BODY", disabled=True
        )
        self.root_id = str(self.root.id)
        self.tm.commit()

    def test_export_of_disabled_thread_is_refused(self):
        """Exporting a disabled (moderator-removed) thread must not serve it."""
        res = self.testapp.get(
            "/api/v1/export/threads/{}.markdown".format(self.root_id),
            status="*",
        )
        body = res.body.decode("utf-8")
        self.assertNotIn("REMOVED-THREAD-BODY", body)


# ---------------------------------------------------------------------------
# Cross-site forgery of API writes
# ---------------------------------------------------------------------------


class TestApiWriteCsrf(SecurityFunctionalTests):
    """Every /api/v1/ write view sets `require_csrf=False` while auth rides
    on a `samesite=none` session cookie, and each view falls back to
    `request.params` — so a plain form-encoded cross-site POST (a CORS "simple
    request", no preflight) is accepted as the logged-in victim."""


    def setUp(self):
        ns = get_or_create_namespace(self.dbsession, "s3-csrf.example.com")
        self.dbsession.add(ns)
        user = get_or_create_user_by_email(self.dbsession, "s3-victim@example.com")
        user.verified = True
        # Mint the OTP here, in setUp's transaction. Minting it inside a test
        # body means committing after webtest has already driven a request
        # through the same transaction manager, which closes it out from under
        # us (ResourceClosedError).
        self.raw_otp = user.new_password()
        self.dbsession.add(user)
        self.dbsession.flush()
        self.namespace_name = str(ns.name)
        self.namespace_id = ns.id
        self.user_email = str(user.email)
        self.user_id = str(user.id)
        self.tm.commit()

    def _log_in(self):
        """Authenticate the victim's browser session via the OTP minted in setUp."""
        self.testapp.post(
            "/verification-challenge",
            {"email": self.user_email, "raw-otp": self.raw_otp},
            status="*",
        )

    def test_authenticated_session_is_established(self):
        """Control: our victim session really is authenticated."""
        self._log_in()
        res = self.testapp.get("/api/v1/user/profile", status="*")
        self.assertEqual(res.status_code, 200)

    @pytest.mark.xfail(
        strict=True,
        reason="unfixed: API writes accept cross-site form posts (require_csrf=False)",
    )
    def test_form_encoded_thread_creation_is_rejected(self):
        """A form-encoded POST carrying no CSRF token must be refused.

        This is the exact shape of an attacker's auto-submitting form:
        `Content-Type: application/x-www-form-urlencoded` is a CORS simple
        request, so no preflight protects us — only a CSRF token would.
        """
        self._log_in()
        res = self.testapp.post(
            "/api/v1/threads",
            {
                "namespace": self.namespace_name,
                "thread_title": "CSRF-FORGED-TITLE",
                "thread_data": "posted by a cross-site form",
            },
            status="*",
        )
        self.assertIn(
            res.status_code,
            (400, 403),
            "form-encoded write without CSRF token should be rejected, "
            "got {}".format(res.status_code),
        )

    def test_profile_update_is_json_only(self):
        """Scope boundary: `api_update_profile` reads only the JSON body.

        Unlike the thread/reply/edit views it has no `request.params` fallback,
        so a form-encoded cross-site POST arrives with an empty body and is
        refused. Forging it would need `Content-Type: application/json`, which
        is not a CORS simple request and so hits a preflight we never answer.
        The protection here is incidental — it comes from the parsing style,
        not from a CSRF token — so this test pins the behaviour in place: if
        someone later adds a `request.params` fallback for symmetry with the
        other views, this fails and says why.
        """
        self._log_in()
        res = self.testapp.request(
            "/api/v1/user/profile",
            method="PATCH",
            POST={"name": "csrf-forged-name"},
            status="*",
        )
        self.assertIn(res.status_code, (400, 403))


# ---------------------------------------------------------------------------
# A namespace owner can keep their thread list private
# ---------------------------------------------------------------------------


class TestPrivateThreadList(SecurityFunctionalTests):
    """`Namespace.public` is enforced on every surface that
    enumerates threads, and is toggleable both ways from namespace settings.

    Scope is our *index*: list, search, RSS, sitemap, and whole-namespace
    export. Individual threads stay reachable by id so our embed product keeps
    working on a private namespace — see `Namespace.can_list_roots`.
    """

    def setUp(self):
        ns = get_or_create_namespace(self.dbsession, "private-list.example.com")
        ns.public = False
        self.dbsession.add(ns)
        self.dbsession.flush()
        self.namespace = ns
        self.namespace_name = str(ns.name)
        self.namespace_id = ns.id
        self.root = self.make_thread(ns, "private-list thread", "PRIVATE-NAMESPACE-BODY")
        self.root_id = str(self.root.id)
        self.tm.commit()

    def test_new_namespaces_are_public_by_default(self):
        """New namespaces are public by default.

        This inverts our original `default=False`, which was never enforced:
        every namespace on our platform has always listed publicly, so
        `False` has to be an explicit choice rather than a silent default.
        Migration 554e2329ebf0 backfilled existing rows to match.
        """
        ns = get_or_create_namespace(self.dbsession, "fresh-namespace.example.com")
        self.dbsession.flush()
        self.assertTrue(bool(ns.public))

    def test_private_namespace_thread_list_is_not_anonymous(self):
        """A non-public namespace must not list its threads to anonymous users."""
        res = self.testapp.get(
            "/api/v1/threads",
            {"namespace": self.namespace_name},
            status="*",
        )
        self.assertEqual(res.status_int, 403)
        self.assertNotIn("private-list thread", res.body.decode("utf-8"))

    def test_private_namespace_search_is_not_anonymous(self):
        """Search enumerates roots too, so it answers to the same flag."""
        res = self.testapp.get(
            "/api/v1/threads/search",
            {"namespace": self.namespace_name, "q": "private"},
            status="*",
        )
        self.assertEqual(res.status_int, 403)
        self.assertNotIn("private-list thread", res.body.decode("utf-8"))

    def test_private_namespace_export_is_not_anonymous(self):
        """A whole-namespace export is our index in book form."""
        res = self.testapp.get(
            "/api/v1/export/namespace/{}.markdown".format(self.namespace_name),
            status="*",
        )
        self.assertEqual(res.status_int, 403)
        self.assertNotIn("PRIVATE-NAMESPACE-BODY", res.body.decode("utf-8"))

    def test_individual_thread_still_readable_when_list_is_private(self):
        """Our embed product resolves threads by id and must keep working.

        If this ever starts failing, someone widened `public` from an index
        flag into full content privacy — a different, larger feature (T20).
        """
        res = self.testapp.get(
            "/api/v1/threads/{}".format(self.root_id), status="*"
        )
        self.assertEqual(res.status_int, 200)
        self.assertIn("PRIVATE-NAMESPACE-BODY", res.body.decode("utf-8"))

    def test_public_namespace_still_lists(self):
        """Our default path must be untouched: public namespaces still list."""
        name = "public-list.example.com"
        ns = get_or_create_namespace(self.dbsession, name)
        ns.public = True
        self.dbsession.add(ns)
        self.dbsession.flush()
        self.make_thread(ns, "public-list thread", "OPEN-NAMESPACE-BODY")
        self.tm.commit()

        res = self.testapp.get(
            "/api/v1/threads", {"namespace": name}, status="*"
        )
        self.assertEqual(res.status_int, 200)
        self.assertIn("public-list thread", res.body.decode("utf-8"))

    def test_null_public_reads_as_public(self):
        """Rows predating our column, or missed by our backfill, stay visible.

        Fail-open is deliberate here and only here: a NULL means "we never
        asked", and silently hiding a live namespace's index would be a
        self-inflicted outage.
        """
        name = "legacy-null-public.example.com"
        ns = get_or_create_namespace(self.dbsession, name)
        ns.public = None
        self.dbsession.add(ns)
        self.dbsession.flush()
        self.make_thread(ns, "legacy-namespace thread", "LEGACY-NAMESPACE-BODY")
        self.tm.commit()

        res = self.testapp.get(
            "/api/v1/threads", {"namespace": name}, status="*"
        )
        self.assertEqual(res.status_int, 200)
        self.assertIn("legacy-namespace thread", res.body.decode("utf-8"))

    def test_moderator_can_still_list_private_namespace(self):
        """Privacy hides our index from strangers, not from our own moderators."""
        ns = get_or_create_namespace(self.dbsession, self.namespace_name)
        self.assertFalse(ns.can_list_roots(None))
        self.assertTrue(ns.can_list_roots(_FakeSuperuser()))

    def test_toggle_is_reversible(self):
        """Fox's requirement: a namespace can go private and come back."""
        ns = get_or_create_namespace(self.dbsession, "toggle-list.example.com")
        self.dbsession.flush()
        self.assertTrue(ns.can_list_roots(None))

        ns.public = False
        self.dbsession.flush()
        self.assertFalse(ns.can_list_roots(None))

        ns.public = True
        self.dbsession.flush()
        self.assertTrue(ns.can_list_roots(None))


class _FakeSuperuser(object):
    """Minimal stand-in for our superuser branch of `is_moderator`."""

    authenticated = True
    is_superuser = True


# ---------------------------------------------------------------------------
# Credential material must never reach our logs
# ---------------------------------------------------------------------------


class TestPasswordCheckLogging(SecurityFunctionalTests):
    """`check_password` used to log both the computed and stored
    bcrypt hashes unconditionally, at every login attempt. Our OTP is six
    digits, so a logged hash is a recoverable credential for anyone holding our
    logs.

    These tests guard the fix in both directions: the hash must not be logged,
    and our deliberate debug-mode affordance in `lib/mail.py` must keep working.
    """

    def setUp(self):
        # No tm.commit() here: these assertions are pure model logic, and
        # committing detaches the User from our session (DetachedInstanceError
        # on the next attribute read).
        self.user = get_or_create_user_by_email(
            self.dbsession, "s5-logging@example.com"
        )
        self.user.verified = True
        self.raw_otp = self.user.new_password()
        self.dbsession.add(self.user)
        self.dbsession.flush()

    def test_check_password_does_not_log_hashes(self):
        """A login attempt must not write bcrypt material to our logs."""
        import logging

        with self.assertLogs("remarkbox.models.user", level=logging.DEBUG) as caught:
            self.user.check_password(self.raw_otp)

        blob = "\n".join(caught.output)
        stored_hash = self.user.password
        self.assertNotIn(stored_hash, blob)
        self.assertNotIn("stored_hash=", blob)
        self.assertNotIn("new_hash=", blob)

    def test_check_password_still_reports_outcome(self):
        """We kept an outcome signal — just not the material."""
        import logging

        with self.assertLogs("remarkbox.models.user", level=logging.DEBUG) as caught:
            result = self.user.check_password(self.raw_otp)

        self.assertTrue(result)
        self.assertIn("matched=True", "\n".join(caught.output))

    def test_wrong_otp_still_fails(self):
        """Behaviour guard: the refactor must not weaken verification."""
        self.assertFalse(self.user.check_password("000000"))


class TestMailDebugAffordance(SecurityFunctionalTests):
    """Our deliberate exception to that rule, per fox 2026-07-27: when SMTP fails and
    our debug toolbar is enabled, `send_email` logs the full message — OTP
    included — and returns None instead of raising, so local development works
    without a mail relay. This test exists so a future credential-logging
    sweep does not quietly delete it."""

    def _send_with_smtp_down(self, debug_mode):
        """Drive send_email with SMTP raising, capturing our log output."""
        import logging
        from unittest.mock import patch

        from remarkbox.lib import mail as mail_lib

        with patch.object(mail_lib.smtplib, "SMTP", side_effect=OSError("smtp down")):
            with self.assertLogs("remarkbox.lib.mail", level=logging.DEBUG) as caught:
                result = mail_lib.send_email(
                    relay="localhost",
                    sender_email="noreply@example.com",
                    to_email="s5-mail@example.com",
                    subject="Verification Code - 123456",
                    message_text="Your code is 123456",
                    message_html="<p>Your code is 123456</p>",
                    debug_mode=debug_mode,
                )
        return result, "\n".join(caught.output)

    def test_smtp_failure_logs_otp_when_debug_mode_enabled(self):
        """SMTP down + debug toolbar on: our OTP must still reach our log."""
        result, blob = self._send_with_smtp_down(debug_mode=True)

        self.assertIsNone(result, "debug mode should swallow the error, not raise")
        self.assertIn("123456", blob)
        self.assertIn("Failed to send email", blob)

    def test_smtp_failure_raises_when_debug_mode_disabled(self):
        """Without debug mode we raise instead of logging message contents."""
        from unittest.mock import patch

        from remarkbox.lib import mail as mail_lib

        with patch.object(mail_lib.smtplib, "SMTP", side_effect=OSError("smtp down")):
            with self.assertRaises(OSError):
                mail_lib.send_email(
                    relay="localhost",
                    sender_email="noreply@example.com",
                    to_email="s5-mail@example.com",
                    subject="Verification Code - 123456",
                    message_text="Your code is 123456",
                    message_html="<p>Your code is 123456</p>",
                    debug_mode=False,
                )


# ---------------------------------------------------------------------------
# Session signing secret and cookie flags
# ---------------------------------------------------------------------------


class TestSessionSecretBootGuard(SecurityFunctionalTests):
    """`session.secret = test-secret` shipped as a literal in our
    public `development.ini`, and `make config` downloads that file as a new
    install's configuration. Session cookies are signed with it, so the value
    forges any session. We now fail closed at startup outside development."""

    def test_production_boot_refuses_known_weak_secret(self):
        """No debug toolbar (i.e. a real deploy) + known secret must not boot."""
        from remarkbox import assert_session_secret_is_safe

        for weak in ("test-secret", "insecure-development-secret", ""):
            with self.assertRaises(RuntimeError):
                assert_session_secret_is_safe(
                    {"session.secret": weak, "pyramid.includes": ""}
                )

    def test_development_boot_allows_fallback_secret(self):
        """Dev keeps working: the toolbar marks a dev box, so we allow it."""
        from remarkbox import assert_session_secret_is_safe

        assert_session_secret_is_safe(
            {
                "session.secret": "insecure-development-secret",
                "pyramid.includes": "pyramid_debugtoolbar",
            }
        )

    def test_real_secret_boots_anywhere(self):
        """A properly set secret boots with or without our toolbar."""
        from remarkbox import assert_session_secret_is_safe

        strong = "PQ3n_uWx1kZr8aVt6Yc0LmHgJdSfB2eN5oXiTpAqRw"
        assert_session_secret_is_safe(
            {"session.secret": strong, "pyramid.includes": ""}
        )
        assert_session_secret_is_safe(
            {"session.secret": strong, "pyramid.includes": "pyramid_debugtoolbar"}
        )


class TestSessionCookieFlags(SecurityFunctionalTests):
    """`samesite = none` with `secure = False` is rejected outright
    by current browsers — the cookie is simply dropped. `none` is genuinely
    required for our embed product's third-party iframes, so `secure` must be
    true alongside it. http://localhost is a secure context, so development
    is unaffected."""

    def test_shipped_config_pairs_samesite_none_with_secure(self):
        from pyramid.paster import get_appsettings

        settings = get_appsettings("development.ini")
        samesite = (settings.get("session.samesite") or "").strip().lower()
        secure = (settings.get("session.secure") or "").strip().lower()

        if samesite == "none":
            self.assertIn(
                secure,
                ("true", "1", "yes", "on"),
                "SameSite=None without Secure is dropped by browsers",
            )


# ---------------------------------------------------------------------------
# Unauthenticated pandoc conversion is a CPU amplification surface
# ---------------------------------------------------------------------------


class TestPreviewPandocAmplification(SecurityFunctionalTests):
    """`/preview-post` shells out to pandoc for any anonymous caller, and
    the rate-limit tween only covers `/api/v1/` paths — so this endpoint has
    no limit at all. Recorded here as an executable statement of the exposure;
    the guard we want is a rate limit plus an input cap."""


    def test_preview_post_is_reachable_anonymously(self):
        """Control: no auth is required to make us run a pandoc subprocess."""
        res = self.testapp.post(
            "/preview-post",
            {"data": "Title\n=====\n\nbody", "source_format": "rst"},
            headers={"X-Requested-With": "XMLHttpRequest"},
            status="*",
        )
        self.assertEqual(res.status_code, 200)

    def test_oversized_preview_is_refused(self):
        """Preview input must be capped like every other content path.

        Every other write path enforces `MAX_CONTENT_LENGTH`. Preview used to
        cap nothing and hand the body straight to a pandoc subprocess.
        """
        from remarkbox.views import MAX_CONTENT_LENGTH

        oversized = "a " * MAX_CONTENT_LENGTH  # ~1MB, 2x the cap
        res = self.testapp.post(
            "/preview-post",
            {"data": oversized, "source_format": "markdown"},
            headers={"X-Requested-With": "XMLHttpRequest"},
            status="*",
        )
        self.assertIn(res.status_code, (400, 413, 429))

    def test_preview_post_is_rate_limited(self):
        """`/preview-post` must fall under our rate-limit tween.

        The tween used to return early for every path outside `/api/v1/`, so
        this endpoint — one pandoc process per request, no auth — had no limit
        at all. It is now covered via `api.rate_limit.extra_paths`.
        """
        from remarkbox.api.rate_limit import rate_limit_tween_factory

        settings = {
            "api.rate_limit.write_requests": "2",
            "api.rate_limit.window": "60",
            "api.rate_limit.extra_paths": "/preview-post",
        }

        class _Registry:
            pass

        registry = _Registry()
        registry.settings = settings

        seen = []

        def handler(request):
            seen.append(request.path)
            return "handled"

        tween = rate_limit_tween_factory(handler, registry)

        class _Request:
            path = "/preview-post"
            method = "POST"
            client_addr = "203.0.113.9"
            session = {}

        # Two allowed by our configured write limit, the third throttled.
        self.assertEqual(tween(_Request()), "handled")
        self.assertEqual(tween(_Request()), "handled")
        throttled = tween(_Request())
        self.assertEqual(len(seen), 2, "third request should not reach our handler")
        self.assertEqual(throttled.status_code, 429)

# Keep this module's tests together on one xdist worker. Test modules share a
# per-worker database; when --dist=loadgroup deals unmarked tests out
# individually, classes from different modules interleave on a worker and one
# class's tearDownClass drop_all yanks tables from another class mid-run.
import pytest as _pytest

pytestmark = _pytest.mark.xdist_group("test_security")
