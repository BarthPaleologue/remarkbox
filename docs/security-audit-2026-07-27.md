# Security Audit — 2026-07-27

**Scope:** full `remarkbox` codebase (159 Python files, ~28k lines) — models,
views, API, auth, session, export/wiki/theme surfaces, config defaults.
**Method:** manual read of every auth, input, and output path; findings
confirmed with executable tests, not inference.
**Regression suite:** `remarkbox/tests/test_security.py` — one test per
finding, `xfail(strict=True)` while a finding is open, so each flips to a
permanent guard the moment it is fixed.

Run our suite:

```bash
env/bin/python -m pytest remarkbox/tests/test_security.py -q
# 41 passed   ← no xfails: every finding is fixed
```

> `make test` is our canonical whole-suite invocation. Serial runs used to
> cascade into ~150 phantom failures through a shared transaction manager;
> T19 (resolved 2026-07-27) isolated per-module databases and transactions,
> so both parallel and serial runs are green and deterministic now.

## Findings

| ID | Severity | Title | Status |
|----|----------|-------|--------|
| S1 | **High** | Export API bypasses moderation visibility filters | **fixed** |
| S2 | **High** | Export API serves disabled (moderator-removed) threads | **fixed** |
| S3 | **High** | CSRF on API write endpoints | **fixed** |
| S4 | Medium | `Namespace.public` is never enforced | **fixed** |
| S5 | **High** | OTP bcrypt hash written to logs on every login | **fixed** |
| S6 | Medium | `/preview-post` — uncapped, unauthenticated pandoc execution | **fixed** |
| S8 | Medium | `session.samesite = none` + `session.secure = False` is self-defeating | **fixed** |

---

### S1 — Export API bypasses moderation visibility filters (High) — FIXED

`remarkbox/api/export.py:143`, `:224`, `:302`

Every export view filters only `{"disabled": False}`. It never consults the
namespace's `hide_unless_approved` or `hide_unverified` settings, which
`api_get_thread` *does* honour (`api/views.py:427-431`) and which the web UI
honours through `namespace.can_see_node`.

Consequence: on a namespace running pre-moderation, content sitting in a
moderation queue — including posts our spam pipeline soft-flagged at
`spam.soft_threshold` and held as `approved=False` — is served in full to any
anonymous caller:

```
GET /api/v1/export/threads/{root_id}.markdown
```

The web UI shows nothing. The export shows everything. This is the highest-value
finding because our spam pipeline's *entire* soft-fail strategy — hold, don't
reject — assumes held content is not readable.

**Fixed** in `api/export.py`: added `_visibility_filters(namespace)`, which
mirrors `api_get_thread`, and applied it to all three export views including
`node_fetcher` in `api_export_namespace`. Like the JSON endpoint it does not
widen for moderators — held content is visible in our web UI, not in exports.
Guarded by `TestExportRespectsModerationVisibility` (3 tests).

### S2 — Export API serves disabled threads (High) — FIXED

`remarkbox/api/export.py:126-133`

`api_export_thread` resolves the root with `get_node_by_id` and renders it via
`node_tree_to_markdown(root, ...)`, which includes the root unconditionally
(`lib/pandoc.py:339`). Nothing checks `root.disabled`. A thread a moderator has
taken down — our removal mechanism — remains fully exportable by node id, and
node ids are not secret (they appear in RSS, sitemaps, permalinks, and prior
exports).

**Fixed** in `api/export.py`: `api_export_thread` now 404s when `root.disabled`
or `namespace.can_see_node` refuses; `api_export_node` does the same for the
subtree's anchor node. `api_export_namespace` was already safe at the root level
via `visible_roots`. Guarded by `TestExportRefusesDisabledThreads`.

### S3 — CSRF on API write endpoints (High) — FIXED

`remarkbox/api/views.py` — every write view; `remarkbox/__init__.py:239`;
`development.ini:39`

Three properties combine into a working cross-site attack:

1. Auth rides on a session **cookie**, and `session.samesite = none` means the
   browser attaches it to cross-site requests.
2. Every `/api/v1/` write view sets `require_csrf=False`, opting out of the
   global `config.set_default_csrf_options(require_csrf=True)`.
3. Each write view falls back to `request.params` when the JSON body is absent
   — e.g. `api_create_thread` reads `request.params.get("thread_title")`
   (`api/views.py:469-471`).

Point 3 is what makes it exploitable. A form-encoded POST is a CORS *simple
request*: no preflight, so the absence of CORS headers protects nothing. An
attacker page auto-submitting a plain HTML form posts, replies, or edits as
whatever Remarkbox user is logged in:

```html
<form method="POST" action="https://my.remarkbox.com/api/v1/threads">
  <input name="namespace" value="victim.example.com">
  <input name="thread_title" value="...">
  <input name="thread_data" value="...">
</form><script>document.forms[0].submit()</script>
```

Affected: `POST /api/v1/threads`, `POST /api/v1/threads/{id}/replies`,
`PATCH /api/v1/nodes/{id}` (including the `disabled`/`approved`/`locked`
moderation flags when the victim is a moderator).

**Not affected:** `PATCH /api/v1/user/profile` — it reads the JSON body only,
with no `request.params` fallback, so forging it would require
`Content-Type: application/json` and thus a preflight. That protection is
incidental to its parsing style, not deliberate; `test_profile_update_is_json_only`
pins it so adding a params fallback "for symmetry" fails loudly.

**Fixed — both paths, per fox 2026-07-27.**

*Bearer tokens* (`models/api_token.py`, `api/auth.py`): a revocable,
per-credential `Authorization: Bearer` token, stored as SHA-256 (256 bits of
entropy means nothing to brute force, and bcrypt would tax every request for
no gain). Resolved ahead of our session cookie in `add_user`. Token management
refuses bearer authentication, so a leaked token cannot mint more or lock its
owner out.

*Cookie-authenticated writes* (`api/csrf.py` tween) additionally require:

- `Content-Type: application/json` — a cross-site form can only send the three
  CORS simple types, so it cannot forge a write. Our Python and C clients
  already sent this, so no client broke.
- a same-origin `Origin` when present. Absent is allowed: non-browser clients
  omit it, and browsers are the threat. Hostnames are compared without ports,
  because a browser omits the default port while `request.host` behind our
  proxy may carry one.

Bearer-authenticated writes skip both, having never been forgeable. Reads are
untouched. Guarded by `TestApiWriteCsrf` and `TestBearerTokenAuth`.

### S4 — `Namespace.public` is never enforced (Medium) — FIXED

`remarkbox/models/namespace.py:109`; `remarkbox/routes.py:29-30`

The column exists, has a migration (`953d42406dbb`), defaults to `False`, and
is documented as *"should the list of root nodes in this namespace be public or
hidden?"* — and `routes.py` carries the matching TODO:

```python
# todo: if namespace.public == False:
#       lock this routes down to only load for namespace owners
```

No code path reads it. Every namespace lists its threads to anonymous callers
on both web and API, whatever the flag says. Nobody has been harmed yet because
the flag has never been advertised as working — but any operator who discovers
the column in their database will reasonably assume it does something.

**Fixed — enforced and made toggleable, per fox 2026-07-27.**

The dangerous part was our data, not our code: the column defaulted to `False`
and all 11,917 namespaces carried `0` or NULL, so naive enforcement would have
turned every namespace private on deploy. Migration `554e2329ebf0` backfills
every row to `True` first (data-only, no DDL, so it is safe on SQLite), our
model default flips to `True`, and NULL reads as public. `False` is now only
ever a choice an owner made.

**Deploy switch — off by default, and it stays off until data is observed.**
Enforcement sits behind `namespace.enforce_private_lists`, defaulting to
false. Enabling it on production on 2026-07-27 took every thread index to 403
for eleven minutes: rows still read `public = False` because migration
`554e2329ebf0` had not applied, even though salt runs `alembic upgrade head`
on every release. Salt also runs `Base.metadata.create_all()` first, which
creates missing tables from our models without alembic, so schema can be
present while data migrations are not. Re-enable only after reading the rows
themselves. See T22 and
`docs/postmortem-2026-07-27-thread-index-403.md`.

Enforced by `Namespace.can_list_roots` everywhere we enumerate: home listing,
node list, RSS, sitemap, thread-list API, search API, and whole-namespace
export. Search was additionally missing its `api_access` gate entirely; it now
has both. Owners and moderators still see their own index. Toggle lives in
namespace settings as "Public Thread List" and reverses cleanly.

**Scope — read this before promising privacy.** `public` governs our *index*,
not our content. A thread reached by direct link, and every embedded comment
widget, still works on a private namespace, because our embed product resolves
threads by page URI and hiding those would break it. That is honest as
"unlisted", not as "private". T20 tracks genuine content privacy, which
undigg.com needs before its creation flow can offer a "private community".
Guarded by `TestPrivateThreadList`.

### S5 — OTP bcrypt hash written to logs on every login (High) — FIXED

`remarkbox/models/user.py:360`

```python
log.info("new_hash={} stored_hash={}".format(new_hash, stored_hash))
```

`logger_remarkbox` runs at `DEBUG` (`development.ini:157-158`), so this fires on
every `check_password` call — i.e. every login attempt in production.

Our OTP is six digits (`_generate_raw_password`, `user.py:321-324`): a keyspace
of 10^6. bcrypt is deliberately slow, but a million candidates against one known
hash is minutes on commodity hardware — and the log line hands over both the
salt and the target. Anyone with log read access (log aggregation, a backup, a
support tunnel, an exfiltrated volume) recovers live OTPs and authenticates as
those users.

This is our MOAD-0004 pattern — The Logged Secret — in our own codebase.

**Fixed** in `models/user.py`: the hash log is replaced with
`log.debug("otp check for user_id=%s matched=%s", ...)` — outcome, never
material. OTPs expire in 15 minutes, so exposure is bounded to our log
retention window; no rotation needed beyond that.

**Deliberately preserved (fox, 2026-07-27):** `lib/mail.py` still logs full
message contents — OTP included — when SMTP fails *and* our debug toolbar is
enabled, so local development works without a mail relay. That is a different
call site with a real conditional, and it is now pinned by
`TestMailDebugAffordance` so a future credential-logging sweep cannot delete
it silently. Verified end-to-end against our real `development.ini` logging
config: with SMTP refused, the OTP prints to console.

### S6 — `/preview-post`: uncapped, unauthenticated pandoc execution (Medium) — FIXED

`remarkbox/views/misc.py:55-86`; `remarkbox/api/rate_limit.py:33`

`preview_post` accepts any `source_format` and shells out to a pandoc
subprocess. It requires no authentication. Our rate-limit tween returns early
for any path not starting with `/api/v1/`, so this endpoint has **no rate limit
at all**, and unlike every other content path it enforces no
`MAX_CONTENT_LENGTH`.

One HTTP request = one pandoc process on our single origin uwsgi. Concurrent
requests with large bodies are a cheap CPU/memory exhaustion vector.

Related exposure, same shape but currently rate-limited: the export endpoints
run pandoc — and `wkhtmltopdf` for `.pdf` — over an entire namespace,
unauthenticated. `GET /api/v1/export/namespace/{name}.pdf` is the most
expensive request our app can be asked to serve, at 120 reads/min per IP.

**Fixed** in `views/misc.py` and `api/rate_limit.py`: preview input is capped at
`MAX_CONTENT_LENGTH`, and the tween grew `api.rate_limit.extra_paths`
(default `/preview-post`) so non-API paths can be throttled under the same
buckets. Configurable rather than hardcoded, per our standing rule that a value
which can differ per site should not be baked in. Guarded by
`TestPreviewPandocAmplification`.

**Fixed 2026-07-28:** expensive export formats now have their own bucket —
`api.rate_limit.export_{requests,window,formats}`, defaulting to 5 per minute
for `pdf`, `epub`, `docx`, and `odt`. They previously shared our ordinary
120/min read allowance, so one anonymous caller could ask for 120
whole-namespace PDF renders a minute. Markdown and HTML exports stay on the
ordinary bucket: they short-circuit pandoc or cost about as much as any other
read. Guarded by `TestExpensiveExportThrottle`.

**Correction to our standing docs:** `CLAUDE.md`'s CWE-407 section states the
browser form paths lack a content cap. That is now stale — `new_thread.py:42`,
`reply_node.py:95`, and `modify_node.py:33` all enforce `MAX_CONTENT_LENGTH`.
`/preview-post` is the one remaining uncapped content path.

### S8 — `samesite = none` with `secure = False` (Medium) — FIXED

`development.ini:39-40`

```ini
session.samesite = none
session.secure = False
```

`SameSite=None` without `Secure` is rejected outright by every current browser —
the cookie is dropped. So this pairing either breaks login entirely, or
production overrides `secure` and the shipped file is misleading. Both are
problems worth resolving explicitly.

`SameSite=None` itself is a legitimate requirement — our embed product lives in
third-party iframes and needs cross-site cookies. That is precisely why S3
matters: choosing `SameSite=None` forfeits our browser's built-in CSRF defence,
so token or header-based protection is not optional.

**Fixed** in `development.ini`: `session.secure = True`, `samesite` stays `none`
for embed support. http://localhost counts as a secure context, so development
is unaffected. `foxhop-local.ini` needs no change — it pairs `samesite = lax`
with `secure = False`, which browsers accept. Guarded by `TestSessionCookieFlags`,
which asserts the pairing rather than the literal values, so it holds if the
config is retuned. S3 remains the reason this matters.

---

## Not findings (checked, sound)

Recording these so a future audit does not re-litigate them:

- **Content caps** — all four write paths (API create/reply/edit, browser
  new/reply/edit, wiki-edit) enforce `MAX_CONTENT_LENGTH`. Only `/preview-post`
  is uncapped (S6).
- **OTP brute force** — `check_password` expires OTPs at 15 minutes and stops at
  10 attempts (`user.py:340-350`). `throttle_password` rate-limits issuance.
- **Email body logging** (`lib/mail.py:125`) — **not a finding.** This logs
  message contents only inside the `except (socket_error, SMTPException)`
  branch *and* only when `debug_mode` is set: it fires when SMTP is down with
  our debug toolbar enabled, which is precisely when an operator needs to see
  the message that failed to send. Deliberate, correctly conditioned, and not
  reachable in a normal production configuration. Contrast S5, which is
  unconditional and fires on every successful login.
- **SQL injection** — every query goes through SQLAlchemy expressions; no string
  interpolation into SQL anywhere in our codebase.
- **XSS** — `bleach` cleaner runs on every render path including our multi-format
  pandoc inputs (`node.set_data`, `sanitize_html.clean_raw_html`).
- **Superuser gating** — `super_fly_required` and `_require_superuser` check
  `is_superuser` correctly; admin API endpoints are guarded.
- **Webmention SSRF** — bounded read (`MAX_SOURCE_SIZE`), timeout, and a
  requirement that the target already exist as a Remarkbox `Uri`. Note it can
  still be pointed at internal hosts; low value given the response is not
  reflected, but worth a denylist if we ever expose it more widely.
- **CWE-407 caps** from our 2026-03-30 audit are all still in place.
- **Session secret** — **not a finding.** `REMARKBOX_SESSION_SECRET` is set in
  production (fox, 2026-07-27), and our deployed hosts each carry their own
  salt-managed uwsgi ini rather than `development.ini`. Retained as hardening
  for self-hosters, who fetch `development.ini` over the network via
  `make config`: `development.ini` reads the secret from that environment
  variable, and `assert_session_secret_is_safe()` (`__init__.py`, pinned by
  `TestSessionSecretBootGuard`) refuses to boot on a known development value unless
  our debug toolbar is on. Nothing to action.

## Remaining work

**Content privacy** ([T20](tickets/20.md)): `Namespace.public` hides a thread
*index*, not thread *content*. undigg.com cannot honestly offer a "private
community" until that exists.

## Verification

```bash
env/bin/python -m pytest remarkbox/tests/test_security.py -q
# 41 passed — every finding fixed, no xfails remain

make test    # whole suite
```

Every test here now asserts secure behaviour with no `xfail` markers left, so
each one is a permanent regression guard.
