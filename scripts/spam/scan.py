#!/usr/bin/env python3
"""
Scan recent Remarkbox posts for spam.

Requires a superuser session cookie.

Usage:
    python scripts/spam/scan.py [--days=7] [--threshold=0.3] [--namespace=X] [--limit=100]

Examples:
    python scripts/spam/scan.py
    python scripts/spam/scan.py --days=30 --threshold=0.1
    python scripts/spam/scan.py --namespace=meta.remarkbox.com
"""

import argparse
import json
import os
import re
import sys

# Add the remarkbox api dir to path for the client
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "remarkbox", "api"))
from remarkbox_client import RemarkboxClient


# Client-side spam scoring (mirrors server-side logic in remarkbox/models/spam.py)
DEFAULT_PATTERNS = [
    r"buy\s+now", r"click\s+here\s+to", r"free\s+trial",
    r"limited\s+time\s+offer", r"act\s+now", r"order\s+today",
    r"100%\s+free", r"make\s+money\s+fast", r"work\s+from\s+home",
    r"casino\s+online", r"viagra|cialis", r"payday\s+loan",
    r"seo\s+service", r"followers?\s+for\s+(free|sale|\$)",
    r"crypto\s+invest",
]

COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in DEFAULT_PATTERNS]


def score_content_client(text):
    """Score content for spam (client-side, no DB access)."""
    if not text:
        return 0.0, []

    signals = []
    score = 0.0

    # Link density
    urls = re.findall(r"https?://\S+", text)
    url_chars = sum(len(u) for u in urls)
    density = url_chars / len(text) if text else 0.0
    if density > 0.5:
        score += 0.4
        signals.append("link_density:{:.0%}".format(density))
    elif density > 0.3:
        score += 0.2
        signals.append("link_density:{:.0%}".format(density))
    if len(urls) > 5:
        score += 0.2
        signals.append("link_count:{}".format(len(urls)))

    # Spam patterns
    hits = sum(1 for p in COMPILED_PATTERNS if p.search(text))
    if hits >= 3:
        score += 0.5
        signals.append("spam_patterns:{}".format(hits))
    elif hits >= 1:
        score += 0.2
        signals.append("spam_patterns:{}".format(hits))

    # Very short
    if len(text) < 10:
        score += 0.1
        signals.append("very_short")

    return min(score, 1.0), signals


def main():
    parser = argparse.ArgumentParser(description="Scan Remarkbox for spam")
    parser.add_argument("--days", type=int, default=7, help="Days to look back (default 7)")
    parser.add_argument("--threshold", type=float, default=0.3, help="Minimum score to report (default 0.3)")
    parser.add_argument("--namespace", help="Limit to a specific namespace")
    parser.add_argument("--limit", type=int, default=100, help="Max nodes to scan (default 100)")
    parser.add_argument("--url", default="https://my.remarkbox.com", help="Remarkbox URL")
    parser.add_argument("--cookie", default=os.path.expanduser("~/.config/remarkbox/cookies.txt"),
                        help="Cookie file path")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    client = RemarkboxClient(args.url, cookie_file=args.cookie)

    # Fetch recent nodes via admin endpoint
    try:
        result = client._request("GET", "/api/v1/admin/recent-nodes?days={}&limit={}".format(
            args.days, args.limit
        ))
    except Exception as e:
        print("Error: {}".format(e), file=sys.stderr)
        print("Make sure you are authenticated as a superuser.", file=sys.stderr)
        sys.exit(1)

    flagged = []
    for node in result.get("nodes", []):
        # Filter by namespace if specified
        if args.namespace and node.get("namespace") != args.namespace:
            continue

        text = node.get("data", "") or ""
        spam_score, signals = score_content_client(text)

        if spam_score >= args.threshold:
            flagged.append({
                "id": node["id"],
                "namespace": node.get("namespace"),
                "author": node.get("author"),
                "ip": node.get("ip_address"),
                "score": round(spam_score, 2),
                "signals": signals,
                "disabled": node.get("disabled"),
                "preview": text[:100].replace("\n", " "),
                "created_ago": node.get("created_ago"),
            })

    if args.json:
        print(json.dumps(flagged, indent=2))
    else:
        if not flagged:
            print("No spam found above threshold {}.".format(args.threshold))
            return

        print("Found {} suspicious posts (threshold {}):".format(len(flagged), args.threshold))
        print()
        for item in flagged:
            status = "DISABLED" if item["disabled"] else "active"
            print("  [{:.1f}] {} [{}]".format(item["score"], item["id"], status))
            print("    namespace: {}  author: {}  ip: {}".format(
                item["namespace"], item["author"], item["ip"]
            ))
            print("    signals: {}".format(", ".join(item["signals"])))
            print("    preview: {}".format(item["preview"]))
            print()


if __name__ == "__main__":
    main()
