# Postmortem: SSL/TLS Outage on meta.remarkbox.com and faq.remarkbox.com

**Date**: 2026-02-25
**Severity**: High
**Status**: Resolved
**Duration**: ~8 hours (approx 03:44 UTC - 12:00 UTC)

## Summary

meta.remarkbox.com and faq.remarkbox.com went down with SSL protocol errors
(`ERR_SSL_PROTOCOL_ERROR`) after the nginx-to-Caddy migration. The domains were
missing from the Caddyfile entirely. Once added, ACME certificate provisioning
failed due to a cold-start chicken-and-egg problem where all 7 domains needed
certs simultaneously and neither HTTP-01 nor TLS-ALPN-01 challenges could succeed.

## Impact

- meta.remarkbox.com and faq.remarkbox.com completely unreachable for ~8 hours
- my.remarkbox.com, www.remarkbox.com, origin.remarkbox.com also experienced
  brief downtime during troubleshooting (~30 minutes total across attempts)
- westworld2.com unaffected until cert state was nuked, then briefly down
- Grop3r reported the issue on Discord

## Root Cause

Three layered issues:

### 1. Missing domains in Caddyfile (primary)

During the nginx-to-Caddy migration (commit 2d64d79), meta.remarkbox.com and
faq.remarkbox.com were not included in the new Caddyfile pillar at
`foxhop-pillar/caddy/remarkbox.sls`. Caddy had no configuration for these
domains, so it could not serve them or obtain certificates.

### 2. Explicit HTTP blocks hijacking port 80

An early fix attempt added explicit `http://meta.remarkbox.com` and
`http://faq.remarkbox.com` blocks to redirect HTTP to HTTPS. This created a
separate Caddy HTTP server (`srv1`) on port 80 that handled requests for those
domains WITHOUT injecting Caddy's built-in ACME HTTP-01 challenge handler.
Result: Let's Encrypt HTTP-01 validation requests hit the redirect block,
got a 308 redirect to HTTPS (which had no cert), and failed.

### 3. Caddy cold-start chicken-and-egg problem

After removing the explicit HTTP blocks and nuking all cert state to start
fresh, Caddy needed to provision certs for ALL 7 domains simultaneously:

- **HTTP-01 fails on cold start**: Caddy's auto-HTTPS redirects port 80 to 443,
  but port 443 has no cert yet. Let's Encrypt follows the redirect, hits an
  incomplete TLS handshake, and fails.
- **TLS-ALPN-01 fails on cold start**: Caddy can't present the ACME challenge
  cert because the TLS listener isn't fully ready when zero certs exist.

This is a known Caddy behavior, NOT a bug. Confirmed by testing with both the
custom Caddy binary (with L4/ratelimit/cache modules) and a stock Caddy v2.11.1
binary — identical failure.

## Timeline (UTC)

- **~03:44** — meta.remarkbox.com goes down (SSL protocol error)
- **~04:00** — Grop3r reports the issue on Discord
- **08:30** — Investigation begins; SSH to remarkbox.com fails (connection reset)
- **08:45** — Connected via salt master (akuma.foxhop.net); confirmed Caddy
  running with ACME errors for all domains
- **09:00** — Identified missing meta/faq domains, found explicit HTTP blocks
  creating srv1 without ACME handler
- **09:15** — First fix: removed explicit HTTP blocks, pushed pillar (12417db),
  applied via salt highstate
- **09:30** — www.remarkbox.com and remarkbox.com come back online; meta/faq
  still failing with HTTP-01 "tls: internal error"
- **09:45** — Second fix: disabled HTTP challenge to force TLS-ALPN-01 (3c9ca52)
- **10:00** — TLS-ALPN-01 also failing with "tls: internal error" for ALL domains
- **10:15** — Tested standard Caddy binary; same failure. Confirmed NOT a
  module issue. Restored custom binary immediately.
- **10:30** — Nuked all Caddy cert state (`rm -rf /root/.local/share/caddy/`).
  Fresh start: same failure.
- **10:45** — Research confirmed cold-start chicken-and-egg is expected behavior
- **11:00** — **Breakthrough: single-domain bootstrap**. Started Caddy with ONLY
  my.remarkbox.com. Got cert via TLS-ALPN-01 within seconds.
- **11:05** — Reloaded (not restarted) with full Caddyfile. Remaining domains
  obtained certs: some via TLS-ALPN-01 (origin, westworld2), others fell back
  to ZeroSSL after stale LE orders failed.
- **11:15** — All 7 domains confirmed working with valid TLS certs
- **11:30** — Final pillar committed (d3d68f5) and pushed

## Resolution

### The fix: two-phase cert bootstrap

1. Write a minimal Caddyfile with only one domain (`my.remarkbox.com`) and the
   global `{email admin@remarkbox.com}` block
2. Nuke existing cert state: `rm -rf /root/.local/share/caddy/`
3. Start Caddy — single domain gets cert via TLS-ALPN-01
4. Write the full Caddyfile with all 7 domains
5. Reload Caddy (`caddy reload`, NOT restart) — remaining domains obtain certs
   because the TLS listener is already active with a valid cert

### Pillar changes (foxhop-pillar)

Three commits during the incident:

| Commit | Change |
|--------|--------|
| `12417db` | Remove explicit HTTP blocks and `disable_tlsalpn` |
| `3c9ca52` | Force TLS-ALPN-01 by disabling HTTP challenge (reverted in final) |
| `d3d68f5` | Final: add `{email admin@remarkbox.com}` global block, clean config |

### Final Caddyfile structure

```
{
    email admin@remarkbox.com
}

remarkbox.com       { redir https://www.remarkbox.com{uri} }
www.remarkbox.com   { root * /www/www.remarkbox.com; file_server }
my.remarkbox.com    { reverse_proxy localhost:6001 }
origin.remarkbox.com { reverse_proxy localhost:6001 }
meta.remarkbox.com  { reverse_proxy localhost:6001 }
faq.remarkbox.com   { reverse_proxy localhost:6001 }
westworld2.com      { reverse_proxy localhost:6002 }
```

All domains use standard HTTPS blocks. No explicit HTTP blocks. Caddy handles
ACME challenges, redirects, and cert renewal automatically.

### Certificate authorities in use

- **Let's Encrypt** — primary CA for most domains
- **ZeroSSL** — automatic fallback for domains where LE orders went stale

## Lessons Learned

1. **Never use explicit `http://` site blocks in Caddy for domains that need
   auto-HTTPS.** They create a separate HTTP server that hijacks port 80 without
   the ACME handler. Let Caddy manage HTTP-to-HTTPS redirects automatically.

2. **Caddy cannot cold-start with many domains needing certs simultaneously.**
   Both HTTP-01 and TLS-ALPN-01 can fail when the TLS listener has zero certs.
   Bootstrap one domain first, then reload with the rest.

3. **`caddy reload` preserves TLS state; `systemctl restart caddy` does not.**
   Always prefer reload when updating the Caddyfile. A restart re-triggers the
   cold-start problem if cert state is missing.

4. **Custom Caddy modules (L4, ratelimit, cache) do NOT affect ACME behavior.**
   Confirmed by testing with stock Caddy v2.11.1 — identical failure. Don't
   blame custom builds before testing.

5. **CNAME records work fine with Caddy ACME.** meta and faq use CNAME pointing
   to my.remarkbox.com. This is not the issue — the cert is issued for the
   hostname, not the IP.

6. **Caddy stores cert data under the running user's home directory.**
   Running as root: `/root/.local/share/caddy/`. NOT `/var/lib/caddy/`.
   Know your data paths when debugging.

7. **Let's Encrypt has rate limits that bite during incident response.**
   Failed Validations: 5 per account per hostname per hour. After exhausting
   these, Caddy fell back to ZeroSSL automatically — a useful safety net.

## Prevention

- [ ] Add a smoke test to salt highstate that verifies all expected domains
  are present in the rendered Caddyfile before applying
- [ ] Document the single-domain bootstrap procedure in the remarkbox ops
  runbook for future Caddy cert state recovery
- [ ] Consider adding `on_demand_tls` as a safety net for CNAME domains
- [ ] Add monitoring/alerting for SSL certificate expiry across all domains

## Action Items

- [x] Add meta.remarkbox.com and faq.remarkbox.com to Caddyfile
- [x] Remove explicit HTTP blocks that broke ACME
- [x] Add global `{email admin@remarkbox.com}` for ACME registration
- [x] Bootstrap certs via single-domain approach
- [x] Verify all 7 domains serving valid TLS
- [x] Push final pillar config (d3d68f5)
- [x] Document in postmortem
- [ ] Verify next salt highstate applies cleanly without cert loss
