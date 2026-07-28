# Postmortem — thread indexes returned 403 for ~11 minutes (2026-07-27)

**Impact:** every namespace's thread index — home page listing, thread-list
API, search, RSS, sitemap, whole-namespace export — returned
`403 This namespace's thread list is private` to anonymous visitors on
`meta.remarkbox.com`, `faq.remarkbox.com`, and `my.remarkbox.com`.

Individual thread permalinks and embedded comment widgets were unaffected,
because our privacy flag governs our index only.

**Duration:** roughly 01:04–01:15 UTC, from `6ddaf33` deploying to `b112576`
(its revert) deploying.

**Cause:** mine. I enabled namespace list-privacy enforcement by default on
the belief that production rows had been backfilled to `public = True`. They
had not.

## What actually happened

`Namespace.public` defaulted to `False` and was never read by any code, so
every row in production carried `0` while behaving publicly. Migration
`554e2329ebf0` backfills those rows to `True`, and enforcement was originally
shipped behind `namespace.enforce_private_lists`, defaulting to **off**,
precisely so that code could not outrun its data.

I then flipped that default to on, reasoning that production must already be
backfilled. My evidence was indirect: a bearer-authenticated request returned
401 rather than 500, which proves `rb_api_token` exists, and that table is
created by `df0217588814` — a migration whose parent is the backfill. If
alembic had created the table, the backfill must have run first.

That inference was wrong, and the likely reason is instructive. Salt runs
`initialize-database-for-{{ site }}` — which calls `Base.metadata.create_all()`
— immediately *before* `alembic upgrade head`
(`foxhop-states/uwsgi/sites.sls`). `create_all` builds any missing table
straight from our models, with no reference to alembic at all. So
`rb_api_token` can exist while the alembic chain is stalled or failing at some
earlier revision and has never reached `554e2329ebf0`.

If that is right, it means **tables appear on production while data migrations
silently do not apply**, which matters well beyond this feature.

## Detection

The deploy poll was extended to fetch `meta`, `faq`, `demo`, and two API
endpoints the moment the new version appeared. It reported 403s within about a
minute of the deploy landing.

Reading the 403 *body* is what made the diagnosis honest: a bare status code
was ambiguous between our application and our edge bot gate, and one host in
the same check returned `000`, which pointed at network-level blocking. The
body carried our own message, which settled it.

## What went wrong in my reasoning

- I substituted inference for verification on an access-control change with
  platform-wide blast radius. I had already stated I could not read the
  production database; the correct conclusion was to not enable, rather than
  to enable and watch.
- I treated a chain of plausible steps ("table exists → alembic ran → parent
  ran") as equivalent to evidence. It had an unexamined alternative
  explanation — `create_all` — that was visible in the same salt file I had
  read minutes earlier.
- The original design was right and I talked myself out of it. Shipping
  disabled-by-default was not over-caution; it was the thing standing between
  a wrong assumption and an outage.

## What went right

- The kill switch existed, so recovery was a one-commit revert rather than a
  data repair.
- Post-deploy verification was automated and specific, so detection took about
  a minute instead of waiting for a user report.
- Blast radius was bounded by design: privacy governs our index only, so
  permalinks and embeds — the bulk of what Remarkbox serves — stayed up.

## Follow-ups

1. **Establish why alembic has not applied `554e2329ebf0` on production.**
   Run `alembic current` against `origin.remarkbox.com` and compare with our
   local head. This needs production access and is not something our
   application should answer over HTTP.
2. **Do not re-enable enforcement until the backfill is confirmed applied**,
   by inspecting the data, not by inference.
3. **Consider whether `create_all` belongs in our deploy path at all.** Having
   it mask a failing migration chain is worse than a loud failure: schema
   drifts into place while data migrations are skipped.
4. **Consider failing our deploy when `alembic upgrade head` errors.** If a
   release can go live with a broken migration chain, our database and our
   code disagree in silence.
