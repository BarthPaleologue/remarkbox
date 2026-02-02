#!/usr/bin/env python3
"""
Bulk disable spam nodes on Remarkbox.

Requires a superuser session cookie.

Usage:
    python scripts/spam/disable_spam.py node_id [node_id ...]
    python scripts/spam/scan.py --json | python scripts/spam/disable_spam.py --from-json

Examples:
    python scripts/spam/disable_spam.py abc123 def456
    python scripts/spam/scan.py --json --threshold=0.8 | python scripts/spam/disable_spam.py --from-json
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "remarkbox", "api"))
from remarkbox_client import RemarkboxClient


def main():
    parser = argparse.ArgumentParser(description="Bulk disable spam nodes")
    parser.add_argument("node_ids", nargs="*", help="Node IDs to disable")
    parser.add_argument("--from-json", action="store_true",
                        help="Read node IDs from JSON on stdin (from scan.py --json)")
    parser.add_argument("--url", default="https://my.remarkbox.com", help="Remarkbox URL")
    parser.add_argument("--cookie", default=os.path.expanduser("~/.config/remarkbox/cookies.txt"),
                        help="Cookie file path")
    parser.add_argument("--dry-run", action="store_true", help="Just print what would be disabled")
    args = parser.parse_args()

    node_ids = list(args.node_ids)

    if args.from_json:
        data = json.load(sys.stdin)
        if isinstance(data, list):
            node_ids.extend(item["id"] for item in data if "id" in item)
        elif isinstance(data, dict) and "nodes" in data:
            node_ids.extend(item["id"] for item in data["nodes"] if "id" in item)

    if not node_ids:
        print("No node IDs provided. Use positional args or --from-json.", file=sys.stderr)
        sys.exit(1)

    # Deduplicate
    node_ids = list(dict.fromkeys(node_ids))

    client = RemarkboxClient(args.url, cookie_file=args.cookie)

    disabled = 0
    failed = 0
    skipped = 0

    for node_id in node_ids:
        if args.dry_run:
            print("[dry-run] would disable {}".format(node_id))
            continue

        try:
            client.disable_node(node_id)
            print("[ok] disabled {}".format(node_id))
            disabled += 1
            time.sleep(0.5)
        except Exception as e:
            print("[FAIL] {}: {}".format(node_id, e), file=sys.stderr)
            failed += 1

    if args.dry_run:
        print("\nDry run: {} nodes would be disabled.".format(len(node_ids)))
    else:
        print("\nDone. {} disabled, {} failed.".format(disabled, failed))


if __name__ == "__main__":
    main()
