# Roadmap — Operation Undigg II: Hobby → Profits

**Status:** proposed (2026-07-27)
**Domain:** undigg.com
**Thesis:** Remarkbox already contains ~80% of a reddit/digg-class community
platform. Our missing 20% is voting UI, ranking, a front page, and wiring our
existing Stripe rails to actual entitlements. Generative machine learning
makes per-community theming — historically a moderator chore — free and
infinite. We launch undigg.com as our flagship deployment, keep remarkbox.com
as our embedded-comments product, and both share one codebase.

This extends Operation Undigg (T15, resolved) — which built our document layer
(pandoc export, wiki mode, revisions, auto-themes) — into a full community
platform play.

---

## 1. Audit — what we already have

Audited 2026-07-27: 159 Python files, ~28k lines, 449 passing tests.
Hand-written core, coherent architecture. These are launch-ready assets:

| Asset | Where | Reddit/digg role |
|-------|-------|------------------|
| Adjacency-list `Node` tree, unlimited nesting | `models/node.py` (docstring literally says "unlimited nesting like reddit") | Threads + comment trees, done |
| `Namespace` = community primitive | `models/namespace.py` | Sub-forums: roles (owner/moderator), public flag, per-namespace settings, wiki mode, nesting/collapse depth |
| Namespace-per-hostname resolution | `__init__.py` `add_namespace()` → `get_or_create_namespace(request.domain)` | **Wildcard DNS gives us infinite sub-forums for free**: `python.undigg.com` auto-creates community `python.undigg.com` on first visit |
| Deterministic auto-themes, light+dark | `lib/theme_generator.py`, `api/themes.py` | Every community already gets a unique palette from a SHA-256 of its name. Seed for generative themes |
| Per-namespace custom stylesheets | `Namespace.stylesheet`, `stylesheet_embed` columns | Storage for generated themes already exists — no migration needed |
| `Vote` model + `rb_vote` table | `models/vote.py`, `node.score()`, `children_order_by_score()` | Dormant — table live in production schema, zero routes/views/UI |
| `Uri` model, unique, query-string normalization | `models/uri.py` | Link submissions with built-in dedup (unique constraint on `data`) |
| Passwordless email OTP + anonymous posting | `models/user.py`, `views/authentication.py` | Lowest-friction onboarding in the space |
| Spam pipeline: heuristics + Hermes LLM relevance | `models/spam.py`, `models/spam_llm.py`, `scripts/spam/` | Community-scale moderation leverage, thresholds per `.ini` |
| Moderation: approve/disable/verify/lock, bulk ops, superuser | `views/authenticated/`, `topsecret` | Site + community-level mod tooling |
| JSON API v1 + rate limits + Python/C clients | `api/` | Third-party clients, bots, agent participation |
| Notifications: email digests, web push, Slack, RSS, @mentions | `lib/notify.py`, `lib/push.py`, `lib/mentions.py` | Retention loops |
| Pandoc export (67 formats) + provenance QR | `lib/pandoc.py`, `lib/provenance.py` | Differentiator no aggregator has: any thread → PDF/EPUB with living-source QR |
| Wiki mode + revisions | `api/wiki.py`, `models/revision.py` | Community wikis (reddit's wiki, but with revision provenance) |
| Stripe Checkout + `Payment` + `PayWhatYouCan` | `views/authenticated/stripe.py`, `models/payment.py` | Payment rails live; entitlements not wired (see gaps) |
| Attribute-freeze mechanism | `PROTECTED_ATTRIBUTES` in `models/namespace.py` | Ready-made free/paid feature gate: frozen namespaces revert to defaults |
| Webmention, sitemaps, SEO slugs, RSS | `views/webmention.py`, `views/list_nodes.py` | IndieWeb + organic discovery |
| Import pipeline (Disqus etc.) | `views/authenticated/import_comments.py` | Community migration path |

## 2. Audit — gaps (our missing 20%)

| # | Gap | Detail | Effort |
|---|-----|--------|--------|
| G1 | Voting is dormant | No routes, no views, no API endpoints, no JS. `node.score()` is O(votes) Python-side sum; `children_order_by_score()` is O(N·V) — its own TODO admits it. No unique constraint on `(user_id, node_id)` — double-vote defect waiting | medium |
| G2 | No ranking / no front page | `home.j2` lists roots by `changed desc` only. No hot/top/new sorts, no time-decay, no cross-community aggregated front page | medium |
| G3 | No karma | `User` has no reputation; nothing to gate privileges or reward contribution | small |
| G4 | Community creation UX | `/setup` flow is built for website-owner verification (embed product). undigg needs one-click "create community" with reserved-name list | small–medium |
| G5 | Link posts second-class | `Uri` exists but is embed-oriented (external page ↔ thread). No submit-a-link flow, no OG/thumbnail fetch, no outbound-click tracking | medium |
| G6 | Payments are unhooked | Old monetization was deliberately unhooked; what remains is optional pay-what-you-can plus a rarely-used PayPal link. `subscription_type` defaults to `"production"`, so every namespace is permanently powered-up and the webhook changes no state. **Our code is public domain — feature-gating it is not a viable strategy.** See [income-strategy.md](income-strategy.md) | see doc |
| G7 | Search is `ilike` table-scan | `get_root_nodes_by_keywords` — capped (CWE-407 audit) but won't rank or scale | medium |
| G8 | SQLite + single uwsgi origin | Fine to ~low-millions of rows / modest concurrency; write-heavy voting will hurt first. Postgres path exists (`psycopg2` shipped, `readme-postgres-notes.rst`) | medium |
| G9 | Security findings block open signup | Eight findings, five High — export leaks moderation-held and removed content, API writes are CSRF-able, OTP hashes hit logs, shipped session secret. See [security-audit-2026-07-27.md](security-audit-2026-07-27.md) | see doc |
| G10 | No mobile-first front-page design | Templates are comment-embed heavy; an aggregator front page is a different reading surface | medium |

## 3. Architecture decision — undigg.com shape

**Communities are paths, not subdomains** (fox, 2026-07-28). Reddit is
`reddit.com/r/foo`, not `foo.reddit.com`, and the path form is both cheaper
and closer to what already works here.

`undigg.com/ns/{name}` needs **no new routing at all**. `add_namespace`
(`remarkbox/__init__.py:413`) resolves from `matchdict` first and only falls
back to the host header, and we already carry 37 routes on `/ns/{namespace}/`.
Path addressing is not a port; it is the path our embed product has used all
along.

Keep our own vocabulary: `/ns/` means namespace. We do **not** add an `/r/`
alias — `/r/{node_id}` is already `redirect-to-root` in `routes.py:62`, and
copying reddit's letter into a namespace we already named would collide with
a live route to say nothing new.

Why paths beat subdomains here:

- **No wildcard certificate.** One ordinary Caddy block for `undigg.com`
  instead of wildcard DNS plus wildcard TLS. That deletes an entire failure
  class from our critical path — the one that took `demo.remarkbox.com` down
  (T21) and caused our five-day T14 outage.
- **One origin.** Subdomains are separate origins needing a `wild_domain`
  session cookie spread across all of them; paths keep one cookie on one host,
  which matters after tightening our cookie and CSRF posture.
- **SEO consolidates** on one domain rather than splitting link equity across
  thousands of subdomains.
- **Nothing auto-creates.** Host-based resolution would mint a namespace for
  any subdomain anyone resolved; path routes are explicit.

Design notes that follow:

- Apex `undigg.com` = aggregated front page (new view, G2).
- Reserved names list (www, api, my, mail, admin, topsecret, ...) enforced in
  community creation (G4). Still needed — a path segment can collide with a
  route prefix just as a subdomain can collide with a host.
- remarkbox.com embed product unchanged; one codebase, two skins.

### Open questions before building on this

- `add_link_prefix` returns `""` in basic mode, so templates may assume
  host-based addressing when generating namespace-relative URIs. Needs a read
  before the front-door work.
- `request.domain` fallback would still resolve bare `undigg.com` to a
  namespace of that name. Decide whether the apex is a real namespace or a
  view that never touches `add_namespace`.

## 4. Phases

Ordering follows our prime mission: stage capacity before unblocking
bottlenecks. Moderation + spam capacity (already strong) land before growth
levers; monetization wiring lands before marketing spend, so every new user
enters a system that can already convert and can already say no to abuse.

### Phase 0 — Stand up undigg.com (foundation)
0. **Close our High-severity security findings first** (G9). Opening public
   signup on a system that leaks moderation-held content (S1/S2) and accepts
   cross-site writes (S3) converts a private defect into a public incident.
   S5 and S7 are one-line changes; S1/S2 share one fix.
1. DNS: `undigg.com` → proxy; ordinary cert; one proxy Caddy block → origin
   :6001 (same request flow as my.remarkbox.com). No wildcard DNS or wildcard
   TLS — communities are paths.
2. Reserved-name list + one-click community creation view (G4):
   authenticated user names a community, becomes owner, lands on themed page.
   Blocked on deciding S4 — do not offer "private community" until
   `Namespace.public` is either enforced or removed.
3. Front-door template: aggregator-style `home.j2` variant for undigg mode
   (title, link/domain, comment count from `NodeCache`, community badge).

**Done when:** creating `foo.undigg.com` end-to-end takes < 30 seconds and
looks intentionally designed (auto-theme), with tests.

### Phase 1 — Voting, karma, ranking (G1, G2, G3)
1. Migration (`make migration`): unique constraint `(user_id, node_id)` on
   `rb_vote`; add `score` column to `rb_node` (denormalized, indexed);
   add `karma` to `rb_user`.
2. Vote write path: `POST /api/v1/nodes/{id}/vote` (value ∈ {-1, 0, 1}) +
   browser route; updates `Node.score` atomically, bumps author karma,
   invalidates `NodeCache`; `voted` joins `NODE_EVENT_ACTIONS` (our meta.py
   comment already anticipates it).
3. Ranking: `hot` (score with time-decay, computed at write into an indexed
   `hot_rank` column — read path stays one ORDER BY), `top` (score, windowed),
   `new` (created). Apex front page = union across public namespaces.
4. Progressive enhancement per our capability-driven practice: vote arrows
   work as form POST, upgrade to fetch() with `js-only` class.
5. Client + functional test coverage (`remarkbox_client.py`, `rb.c`, tests).

**Done when:** sorts work on community pages and apex; double-vote impossible
at DB layer; karma visible on `/u/{name}`.

### Phase 2 — Link submissions (G5)
1. Submit flow: URI + title (+ optional text) creates root node with
   `has_uri=True`; `Uri` unique constraint gives dedup — resubmission
   redirects to existing thread (digg's core mechanic).
2. Server-side OG/title/thumbnail fetch (respect robots.txt — our own rule),
   cached; favicon per `Uri.favicon` already modeled.
3. Outbound domain display + `rel="nofollow ugc"`; spam pipeline scores link
   posts with existing link-density signals.

**Done when:** a link post renders card-style on front page with thumbnail,
domain, score, comment count; duplicate URIs merge into one thread.

### Phase 3 — Generative machine learning themes (our unfair advantage)
1. Extend `theme_generator.py` with a Hermes-driven layer: community
   name + description → structured palette/typography/mood JSON → validated
   CSS custom-properties block. Deterministic fallback stays (offline safe,
   fail-closed to hash theme).
2. Store output in existing `Namespace.stylesheet` (no migration); version
   with `stylesheet_timestamp`; "regenerate theme" button for owners with
   preview + accept (owner decides — same consent pattern we live by).
3. Optional image layer: header/banner art via local diffusion, stored under
   `static/attachment`; strict size budget.
4. Pre-seed catalog: script generates ~200 communities we'd want on day one
   (topic list curated by fox), each with generated theme + description +
   seed thread. Ghost-town risk managed by seeding depth-first: 20 active
   communities beat 200 dead ones — launch gate is seeded content quality.
5. Contrast/accessibility validator on every generated theme (WCAG AA
   minimum) — generated ≠ unreadable.

**Done when:** every new community gets a distinct, accessible, regenerable
theme with zero human design labor; theme generation costs < 1 cent each.

### Phase 4 — Discovery (G7 + retention)
1. SQLite FTS5 (or Postgres tsvector post-G8) behind `/search`; rank by
   score + recency; per-community and global scopes.
2. Trending sidebar (windowed vote velocity from `rb_vote.created`).
3. RSS already exists per namespace — add apex firehose + per-sort feeds.
4. `llms.txt` + clean OG cards on every thread: agents and link-unfurlers
   are first-class readers (our API-first stance already positions this).

### Phase 5 — Income (G6)

Our old monetization was unhooked deliberately; optional pay-what-you-can plus
a PayPal link is what remains, and it is rarely used. Our source is public
domain, so gating features behind a license is not available to us.

Full analysis and ranked candidates live in
**[income-strategy.md](income-strategy.md)**. Summary: we stop selling software
(we cannot) and start selling things with real marginal cost — human labor,
operational convenience, and metered compute. Lead with services (migration,
setup, moderation) because it is the only line that can bill this month, and
wire the Stripe webhook now (~1 day) so hosting revenue has somewhere to land
when undigg.com has users.

### Phase 6 — Scale & operations
1. Postgres migration for undigg deployment when write volume (votes) says so
   — alembic chain + `psycopg2` already in place; SQLite stays fine for
   embed-product tenants.
2. Hot-rank/front-page caching (redis hook already exists in `__init__.py`).
3. Moderator recruitment per community = **caretakers before surge**. Our
   halt rule applies: no growth push (HN/lobsters launch posts) while any
   high-traffic community lacks an active moderator. Baby-crying condition
   for a community site is unmoderated virality.
4. Legal: UGC terms, DMCA agent registration, per-community rules page
   (wiki-mode node), GDPR paths already exist (T3, delete/export account).

## 5. Sequencing & effort (rough)

```
P0 foundation      ~1 week    (mostly DNS/proxy + one view + one form)
P1 vote/rank       ~2 weeks   (migration + write path + sorts + tests)
P2 links           ~1 week
P3 gen-ml themes   ~1-2 weeks (generator + validator + seed catalog)
P4 discovery       ~1 week
P5 monetization    ~1 week    (G6 itself: ~1 day)
P6 scale           continuous
```

P0→P1→P2 is our critical path to "it feels like digg." P3 can run parallel
after P0. P5-G6 (entitlement wiring) can land any time — earliest is best.

## 6. Risks

| Risk | Mitigation |
|------|-----------|
| Ghost-town launch | Seed depth over breadth (P3.4); launch gate on content quality, not community count |
| Vote manipulation / rings | DB-level constraint, karma-gated voting weight, IP-reputation signals already in spam pipeline, `rb_vote` audit trail from day one |
| Spam surge on open signup | Hermes relevance check + thresholds already live; superuser bulk tools exist; G9 closes body-size hole |
| SQLite write contention on votes | Denormalized score column keeps reads cheap; Postgres path staged (P6) |
| Moderation load = fox burnout | Caretakers-before-surge rule (P6.3); a community without a moderator gets frozen, not babysat |
| Name conflict: "Operation Undigg" already = T15 document platform | This doc names the pivot **Undigg II**; T15 features become differentiators of the same brand |
| Generated themes look samey/broken | Deterministic fallback + WCAG validator + owner preview/accept |

## 7. Metrics that matter

- Time-to-community (target < 30s), time-to-first-post
- Weekly posting users per community (depth), not community count (breadth)
- Vote actions / reader (engagement without infinite-scroll mechanics)
- PWYC conversion + powered-up communities (revenue)
- Mod actions per 1k posts + spam catch rate (health)
- Export/API usage (differentiator adoption)

## 8. Immediate next actions (pending fox approval)

1. Ticket T17 tracks this roadmap (created alongside this doc).
2. P0.3 (body-size cap, G9) — small, closes a known audit gap, ship first.
3. P5-G6 (webhook → entitlement wiring) — one day, unlocks all revenue.
4. DNS/proxy staging for undigg.com (needs fox: registrar +
   PowerDNS zone + proxy Caddyfile).
