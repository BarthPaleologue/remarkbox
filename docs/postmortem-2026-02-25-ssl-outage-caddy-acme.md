# Postmortem: SSL/TLS Outage on meta.remarkbox.com and faq.remarkbox.com

**Date**: 2026-02-25 (recurred 2026-02-26 through 2026-03-02)
**Severity**: High
**Status**: Resolved
**Duration**: Initial ~8 hours; recurrence ~5 days

## Summary

meta.remarkbox.com and faq.remarkbox.com went down with SSL protocol errors
(`ERR_SSL_PROTOCOL_ERROR`) after the nginx-to-Caddy migration. The initial
outage (2026-02-25) was caused by missing domains in the remarkbox server's
Caddyfile and a cold-start chicken-and-egg problem. A temporary fix using
single-domain bootstrap resolved it, but the domains went down again on each
subsequent deploy because the **actual root cause** was in the ingress proxy
(`proxy.unturf.com` at 142.93.73.64), not the remarkbox server.

meta and faq are CNAMEs to `my.remarkbox.com`, which resolves to the ingress
proxy. The proxy's Caddyfile had no blocks for meta or faq, so they fell through
to the MPS on-demand TLS catch-all — routing to the wrong backend entirely.
The remarkbox server's Caddy could never obtain certs for these domains because
ACME challenges were directed at the proxy, not the backend.

## Impact

- meta.remarkbox.com and faq.remarkbox.com completely unreachable for ~8 hours
- my.remarkbox.com, www.remarkbox.com, origin.remarkbox.com also experienced
  brief downtime during troubleshooting (~30 minutes total across attempts)
- westworld2.com unaffected until cert state was nuked, then briefly down
- Grop3r reported the issue on Discord

## Root Cause

### The actual root cause: missing proxy blocks

meta.remarkbox.com and faq.remarkbox.com are CNAME records pointing to
`my.remarkbox.com`, which resolves to `142.93.73.64` — the ingress proxy
(`proxy.unturf.com`). The proxy's Caddyfile (`~/git/proxy.unturf.com/ingress/Caddyfile`)
had a block for `my.remarkbox.com` that reverse-proxied to `origin.remarkbox.com`,
but **no blocks for meta or faq**.

Without explicit blocks, requests to meta/faq fell through to the catch-all
`https://` block, which uses on-demand TLS and proxies to
`origin.makepostsell.com` — a completely different backend. This meant:

1. The proxy never obtained TLS certs for meta/faq (on-demand TLS asked MPS
   origin, which rejected these domains)
2. The remarkbox server's Caddy could never obtain certs either, because ACME
   challenges (both HTTP-01 and TLS-ALPN-01) were directed at the proxy IP,
   not the backend server

### Contributing factors during initial investigation (2026-02-25)

1. **Missing domains in remarkbox Caddyfile**: meta/faq were also missing from
   the remarkbox server's Caddyfile pillar (`foxhop-pillar/caddy/remarkbox.sls`)
   after the nginx-to-Caddy migration (commit 2d64d79). This was a real issue
   but fixing it alone could not resolve the outage because the proxy was the
   TLS termination point.

2. **Explicit HTTP blocks hijacking port 80**: An early fix attempt added
   explicit `http://` blocks that created a separate HTTP server without Caddy's
   built-in ACME handler, breaking HTTP-01 challenges.

3. **Cold-start chicken-and-egg**: Nuking cert state and restarting Caddy caused
   all domains to need certs simultaneously, which can fail when the TLS listener
   has zero certs. This was a red herring — the real problem was that ACME
   challenges never reached the remarkbox server regardless.

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

### Recurrence (2026-02-26 through 2026-03-02)

- **Feb 26** — Pushing the postmortem commit triggered CI/CD deploy, which
  restarted Caddy on the remarkbox server. meta/faq lost certs again because
  the single-domain bootstrap was a one-time workaround, not a permanent fix.
- **Feb 26-Mar 1** — Multiple debugging attempts: `on_demand_tls`,
  `auto_https disable_redirects`, self-signed cert bootstrapping, testing
  from the server locally (`openssl s_client` showed ACME challenges working
  on localhost but failing externally). Discovered server IP (162.243.167.224)
  differed from DNS IP (142.93.73.64) — initially attributed to a "floating IP
  proxy" stripping TLS-ALPN-01 extensions.
- **Mar 2** — Identified the **actual root cause**: 142.93.73.64 is the
  `proxy.unturf.com` ingress proxy running Caddy, not a transparent floating IP.
  The proxy's Caddyfile had no blocks for meta/faq. Added the blocks, reloaded
  the proxy's Caddy, and both domains came up immediately with valid LE certs.

## Resolution

### The permanent fix: add proxy blocks (2026-03-02)

Added `meta.remarkbox.com` and `faq.remarkbox.com` blocks to the ingress
proxy Caddyfile (`proxy.unturf.com/ingress/Caddyfile`), identical to the
existing `my.remarkbox.com` block:

```
meta.remarkbox.com {
    forward_auth localhost:8003 {
        uri /assholes/gate
    }
    reverse_proxy https://origin.remarkbox.com {
        header_up Host {http.request.host}
        header_up X-Real-IP {http.request.remote.host}
        header_up X-Forwarded-For {http.request.remote.host}
        header_up X-Forwarded-Proto {http.request.scheme}
        transport http {
            tls_server_name origin.remarkbox.com
        }
    }
    log {
        output file /var/log/caddy/meta.remarkbox.com.log
    }
}
```

The proxy handles TLS termination and ACME for meta/faq. Traffic forwards to
the remarkbox backend via `origin.remarkbox.com`. The remarkbox server's Caddy
no longer needs to obtain certs for these domains — the proxy owns that
responsibility.

Commit: `f12a56d` in `proxy.unturf.com` repo.

### Earlier workaround: two-phase cert bootstrap (2026-02-25)

The initial fix used single-domain bootstrap on the remarkbox server to obtain
certs. This worked temporarily but broke on every Caddy restart because the
underlying proxy routing was wrong.

### Pillar changes (foxhop-pillar)

| Commit | Change |
|--------|--------|
| `12417db` | Remove explicit HTTP blocks and `disable_tlsalpn` |
| `3c9ca52` | Force TLS-ALPN-01 by disabling HTTP challenge (reverted) |
| `d3d68f5` | Final: add `{email admin@remarkbox.com}` global block, clean config |

### Architecture after fix

```
Client → meta.remarkbox.com (CNAME → my.remarkbox.com → 142.93.73.64)
       → proxy.unturf.com Caddy (TLS termination, ACME, cert management)
       → origin.remarkbox.com (162.243.167.224, remarkbox backend Caddy)
       → localhost:6001 (uwsgi, Host header determines namespace)
```

## Lessons Learned

1. **Know which server terminates TLS.** When domains use CNAMEs through a
   proxy, the proxy must have explicit blocks for those domains. The backend
   server cannot obtain ACME certs for domains whose DNS points elsewhere.
   This was the fundamental misunderstanding that prolonged the outage by 5 days.

2. **Trace the full request path before debugging.** The investigation spent
   days debugging ACME on the remarkbox server when the problem was on the
   proxy. A `dig` + understanding of the proxy architecture would have
   identified this immediately.

3. **Catch-all blocks mask routing errors.** The proxy's `https://` on-demand
   TLS catch-all silently absorbed meta/faq requests and routed them to the
   wrong backend, producing TLS errors instead of a clear "no route" signal.

4. **Never use explicit `http://` site blocks in Caddy for domains that need
   auto-HTTPS.** They create a separate HTTP server that hijacks port 80 without
   the ACME handler.

5. **`caddy reload` preserves TLS state; `systemctl restart caddy` does not.**
   Always prefer reload when updating the Caddyfile.

6. **Let's Encrypt has rate limits that bite during incident response.**
   Failed Validations: 5 per account per hostname per hour. Caddy fell back
   to ZeroSSL automatically — a useful safety net.

## Prevention

- [ ] When adding CNAME domains that route through the ingress proxy, always
  add corresponding blocks to `proxy.unturf.com/ingress/Caddyfile`
- [ ] Add monitoring/alerting for SSL certificate validity across all domains
- [ ] Document the proxy architecture in the remarkbox ops runbook: which
  domains go through the proxy vs direct

## Action Items

- [x] Add meta.remarkbox.com and faq.remarkbox.com to remarkbox Caddyfile
- [x] Add meta.remarkbox.com and faq.remarkbox.com to proxy Caddyfile (f12a56d)
- [x] Remove explicit HTTP blocks that broke ACME
- [x] Add global `{email admin@remarkbox.com}` for ACME registration
- [x] Verify all domains serving valid TLS
- [x] Push final proxy config
- [x] Document in postmortem
