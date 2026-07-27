# Income Strategy — What We Can Actually Sell

**Status:** proposed (2026-07-27)
**Context:** our old monetization was unhooked deliberately. What remains is an
optional pay-what-you-can flow plus a PayPal link, and it is rarely used. Our
source is **public domain and open source**.

## The constraint, stated plainly

Public domain means anyone may take our code, run it, sell it, and owe us
nothing. So these are off the table permanently:

- Selling licenses or "pro" builds
- Gating features in our codebase behind payment — a fork strips the check
- Anything whose value is *access to our software*

That is not a defeat. It removes a whole category of bad ideas and leaves us
with the honest question: **what do we have that is scarce?**

## Why pay-what-you-can underperformed

Worth naming, because the instinct is to ask harder. Voluntary payment for a
free good converts at roughly 0.1–1% of active users, and that ratio is
stubborn — it is a property of donation psychology, not of our copy or button
placement. On our current traffic that rounds to nothing no matter how it is
phrased.

The lesson is not "ask better." It is that **people pay reliably for things
with a marginal cost they can feel** — compute that runs, labor that happens,
a service that would otherwise cost them time. PWYC should stay (it costs
nothing to keep, and patronage is real for a small number of people) but it
cannot be our primary line.

## What is actually scarce

Our code is free. These are not:

| Scarce thing | Why a fork can't take it | We already have |
|---|---|---|
| **ML inference** | Needs GPUs and a running model; forking our repo gives you the API client, not the model | Hermes spam pipeline (`models/spam_llm.py`), uncloseai.com infra |
| **Human labor** | Migration, moderation, support are people-hours | Import pipeline, moderation tooling |
| **Operational convenience** | Someone must run, patch, back up, and keep TLS valid | Live production, salt states, CI/CD |
| **Rendering compute** | Pandoc + wkhtmltopdf at scale costs CPU | 67-format export, provenance QR |
| **Audience** | Attention accrues to a destination, not a codebase | undigg.com (planned), meta/faq |
| **Trust & identity** | Reputation is earned, not cloned | Verified namespaces, moderation history |

WordPress is the proof that this works: GPL software anyone may self-host,
and Automattic sells hosting on it. "You can fork it" has never been fatal —
almost nobody wants to be a sysadmin.

## Ranked candidates

Ranked by revenue realism × fork-resistance × effort. Lead with #1 because it
can bill this month; #2 is the line that eventually scales without fox.

### 1. Services: migration, setup, moderation — *the only line that bills now*

Human labor, invoiced. Disqus/Discourse migration, self-hosting setup,
moderation-as-a-service for communities without volunteers.

- **Fork-resistant:** completely. Nobody forks a person.
- **Revenue today:** no new code required — `views/authenticated/import_comments.py`
  already handles imports. This can be sold this month.
- **Not scalable, and that's the point:** its job is to fund the rest.
- **Watch the workaholic trap:** this scales with fox's hours, and fox's hours
  are the bottleneck for everything else on this page. Set a hard weekly cap
  before taking the first client, not after.

### 2. Managed hosting (undigg.com + remarkbox.com)

Free tier that is genuinely free and useful; paid tier for things with real
cost: custom domain, higher rate limits, priority export rendering, larger
storage, backups, uptime commitment.

- **Fork-resistant:** by convenience only — and that is sufficient (WordPress).
- **Nearly built:** Stripe Checkout, `Payment`, `PayWhatYouCan`, `subscription_type`,
  and the `PROTECTED_ATTRIBUTES` freeze mechanism all exist. The webhook marks a
  payment complete and then changes no state. Wiring it is roughly a day.
- **Caveat that matters:** this only earns once undigg.com has users. It is a
  *consequence* of the roadmap, not a substitute for it.
- **Ethical line:** free tier must not be crippled bait. Charge for cost
  (compute, domains, support), never for the right to participate.

### 3. Publishing / print — the differentiator nobody else has

No aggregator turns a thread into a book. We turn one into 67 formats with a
provenance QR that resolves back to the living source. Charge per rendered
book (real CPU cost), optionally partner with print-on-demand.

- **Fork-resistant:** moderate — pandoc is free, the rendering cost is not.
- **Genuinely novel:** archival-grade community history. Sells to communities
  with something worth keeping: conferences, courses, long-running projects.
- **Small but high-margin,** and it makes our export work (T15) earn.

### 4. Spam filtering as an API — *speculative, verify before investing*

**We do not have a spam API.** Stating that plainly because it is easy to
mistake our internal filter for a product. What exists today:

- `models/spam.py` — heuristic scoring: ~15 hardcoded regex patterns, link
  density, duplicate-content hashes, new-account velocity, IP reputation.
  State lives in **in-memory dicts that reset on every process restart**.
- `models/spam_llm.py` — a Hermes relevance check ("is this post on-topic for
  this namespace?") over an OpenAI-compatible endpoint.
- Both are called only from `check_spam()` in `api/views.py`, on our own
  thread-create and reply paths.

There is **no** route, no API key model, no metering, no multi-tenancy, no
persistence, no labeled corpus, and no accuracy benchmark. Turning this into a
sellable product is building a new product, not exposing an existing one.

The idea still has the best fork-resistance on this page — a forker gets our
client code and still needs GPUs and a model — and LLM *relevance* checking is
genuinely differentiated, since classifier-based incumbents don't ask whether a
post is on-topic, and on-topic-looking machine-generated spam is the growth
category. That is why it stays on the list.

But it would be competing with Akismet's decade of labeled data using fifteen
regexes and an 8B model. Before spending real time here:

1. Benchmark what we have against a labeled public spam corpus. If it does not
   beat a naive baseline convincingly, stop — that is a cheap, decisive test.
2. Only if the number is good: persistence for reputation state, an API key +
   metering model, a public endpoint, docs.

Treat step 1 as a go/no-go gate, not a formality.

### 5. Support contracts for self-hosters

They have our code — that is the point. What they lack is our expertise when
it breaks. Annual retainer, priority response, upgrade help.

- **Fork-resistant:** completely; it is expertise, not software.
- **Requires** a self-hosting population large enough to have paying members.
  Downstream of adoption, so: later.

### 6. Community sponsorship with revenue share

A community owner may pin one clearly-labeled supporter note. Owner keeps the
majority; we take a small platform share.

- **Not surveillance advertising.** No tracking, no auction, no profiling —
  one honest note the community chose.
- **Deferred** until undigg.com has traffic worth sponsoring.

## Explicitly rejected

- **Surveillance advertising** — drains living and spiritual capital to grow
  financial capital. This is the exact extraction our platform exists to oppose.
- **Selling user data** — same, worse.
- **Engagement-maximizing mechanics** (infinite scroll, manufactured urgency,
  streaks) — the WALL-E hover chair. We are building for people who want to
  leave the site having gotten something.
- **Open-core relicensing** — abandoning public domain to sell licenses would
  trade our intellectual-capital contribution for a revenue line we can get
  more honestly elsewhere. It also breaks faith with anyone who already built
  on our promise.
- **Lock-in through export friction** — our 67 export formats and `dump.json`
  are a *feature*. Retention through exit rights, not hostages.

## Sequencing

```
Now        #1 services  — bill this month, fund the rest, hard weekly cap
Now        #2 hosting   — wire the Stripe webhook (~1 day) so revenue can land
Month 1    #4 spam      — run the benchmark ONLY. Go/no-go, cheap, decisive
Month 2-3  #2 hosting   — tiers follow undigg.com's user count
Month 3+   #3 publishing — make our T15 export work earn
Later      #5 support, #6 sponsorship — both need population first
Keep       PWYC — costs nothing, patronage is real for a few
```

## Honest expectations

- **#1 services** is the only line that can produce revenue this month, and it
  is capped by fox's hours by construction. That cap is the whole risk: it can
  crowd out the work that would eventually remove fox from the loop.
- **#2 hosting** cannot outrun undigg.com's user count, so it earns later. But
  wiring the webhook is ~1 day and every future line rides on it, so do it now
  regardless of when tiers launch.
- **#4 spam API** is the only candidate that could scale without fox in the
  loop — and it is also the least real. It is a new product competing with an
  entrenched incumbent. Spend one benchmark on it, then decide honestly.
- None of this is a large business soon. The realistic near-term goal is
  **covering infrastructure costs and buying back fox's hours** — not exit
  money. Sized honestly, that is achievable; sized as a startup, it isn't.

## Stewardship check (Eight Forms)

Charging for compute and labor prices what actually costs us something, and
leaves knowledge free. Our code stays public domain (intellectual capital), our
exports stay open (exit rights → social trust), our moderation tooling reduces
volunteer burnout (living capital), and our spam API returns hours to other
communities' moderators (social capital, beyond our own walls). No line here
drains a workaholic to feed a glutton.
