#!/usr/bin/env python3
"""
Check that our LLM relevance pipeline is actually working.

Our spam relevance check and theme palette generation both degrade to a safe
default when the model misbehaves: an unreadable verdict adds no spam signal,
and a rejected palette falls back to a hash. That is the right runtime
behaviour and a terrible alerting story -- when the endpoint stopped serving
our configured model, both features went inert for weeks and nothing said so.

This exercises the whole path against a canary post and exits non-zero when
it is not usable, so a cron job or monitor can notice.

Usage:
    python scripts/check_llm_health.py --ini development.ini
    python scripts/check_llm_health.py --endpoint https://host/v1/chat/completions
    python scripts/check_llm_health.py --ini development.ini --json
"""

import argparse
import json
import sys

from remarkbox.models.spam_llm import (
    DEFAULT_ENDPOINT,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT,
    health_check,
)


def main():
    parser = argparse.ArgumentParser(description="Check LLM relevance health")
    parser.add_argument("--ini", help="Path to .ini config file")
    parser.add_argument(
        "--endpoint",
        help="Override the chat completions endpoint (skips .ini lookup)",
    )
    parser.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT,
        help="Seconds to wait per request (default: {})".format(DEFAULT_TIMEOUT),
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args()

    if args.endpoint:
        settings = {
            "spam.llm.enabled": "true",
            "spam.llm.endpoint": args.endpoint,
            "spam.llm.model": DEFAULT_MODEL,
            "spam.llm.timeout": str(args.timeout),
        }
    elif args.ini:
        from pyramid.paster import get_appsettings

        settings = get_appsettings(args.ini)
        settings.setdefault("spam.llm.timeout", str(args.timeout))
    else:
        parser.error("give --ini or --endpoint")

    endpoint = settings.get("spam.llm.endpoint", DEFAULT_ENDPOINT)
    result = health_check(settings)
    result["endpoint"] = endpoint

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("endpoint: {}".format(endpoint))
        print("model:    {}".format(result["model"]))
        print("verdict:  {}".format(result["verdict"]))
        print("status:   {}".format("OK" if result["ok"] else "DEGRADED"))
        print("detail:   {}".format(result["detail"]))

    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
