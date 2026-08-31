#!/usr/bin/env python3
"""
Simulate what our spam pipeline would do with a post, without posting it.

For triaging spam that got past our edge defences and reached our app. Paste
our content in, see our score, our signals, our model's verdict and what
action we would take.

This drives our real `check_spam` rather than reimplementing it. A simulator
that copies our logic drifts from our app and starts lying; this one cannot
disagree with production because it *is* production's code path.

Usage:
    # a new thread, heuristics only (matches production today, LLM is off)
    python scripts/spam/simulate.py --title "Buy watches" --text "cheap watches at ..."

    # ask what our model would say too
    python scripts/spam/simulate.py --llm --namespace meta.remarkbox.com \\
        --description "Discussion about Remarkbox" --file /tmp/spam.txt

    # a reply, with the thread it landed in for context
    python scripts/spam/simulate.py --llm --reply \\
        --thread-title "Dark mode?" --thread-content "Should we add one" \\
        --text "+1 also visit my site"

    # machine readable
    python scripts/spam/simulate.py --llm --file /tmp/spam.txt --json

Reads our post body from --text, --file, or stdin.

Not simulated: IP reputation. That signal counts disabled posts from an
address in our database, and we deliberately run without a session so a
simulation can never write to or depend on production data. Our real score
for a repeat offender may be higher than what we print.
"""

import argparse
import json
import sys


class _FakeNamespace:
    """Enough of a Namespace for check_spam and our relevance prompts."""

    def __init__(self, name, description=None, spam_filter_enabled=True):
        self.name = name
        self.description = description
        self.spam_filter_enabled = spam_filter_enabled


class _FakeUri:
    def __init__(self, data):
        self.data = data


class _FakeRoot:
    def __init__(self, title, data, page_uri=None):
        self.title = title
        self.data = data
        self.has_uri = page_uri is not None
        self.uri = _FakeUri(page_uri) if page_uri else None


class _FakeParent:
    """A parent node, so reply relevance sees the thread it landed in."""

    def __init__(self, data, root):
        self.data = data
        self.root = root


class _FakeResponse:
    def __init__(self):
        self.status_code = 200


class _FakeRequest:
    def __init__(self, settings, ip):
        self.registry = type("_Registry", (), {"settings": settings})()
        self.response = _FakeResponse()
        # No session: skips IP reputation, and makes telemetry a no-op so a
        # simulation never writes rows into a real database.
        self.dbsession = None
        self.client_addr = ip


def build_settings(args):
    """Production-shaped settings, overridden only by explicit flags."""
    settings = {
        "spam.enabled": "true",
        "spam.hard_threshold": str(args.hard),
        "spam.soft_threshold": str(args.soft),
        # Production has no spam.llm.* keys at all, so this is off unless asked.
        "spam.llm.enabled": "true" if args.llm else "false",
        "spam.llm.endpoint": args.endpoint,
        "spam.llm.timeout": str(args.timeout),
        "spam.llm.irrelevant_weight": str(args.irrelevant_weight),
    }
    if args.model:
        settings["spam.llm.model"] = args.model
    return settings


def read_content(args):
    if args.text:
        return args.text
    if args.file:
        with open(args.file) as handle:
            return handle.read()
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Simulate our spam pipeline against a post",
    )
    parser.add_argument("--text", help="Post body")
    parser.add_argument("--file", help="Read post body from a file")
    parser.add_argument("--title", default=None, help="Thread title")
    parser.add_argument(
        "--namespace", default="meta.remarkbox.com", help="Namespace name")
    parser.add_argument(
        "--description", default=None, help="Namespace description")
    parser.add_argument(
        "--reply", action="store_true",
        help="Treat as a reply rather than a new thread")
    parser.add_argument("--thread-title", default=None)
    parser.add_argument("--thread-content", default=None)
    parser.add_argument("--parent-content", default=None)
    parser.add_argument(
        "--page-url", default=None, help="Embed mode: page the thread is on")
    parser.add_argument(
        "--llm", action="store_true",
        help="Also run our relevance check (off in production today)")
    parser.add_argument(
        "--endpoint", default="https://hermes.ai.unturf.com/v1/chat/completions")
    parser.add_argument("--model", default=None, help="Fallback model id")
    # Measured 22-34s per classification against our 27B model. A tight
    # timeout here does not fail loudly: it returns no verdict, which reads
    # as "nothing to flag" and silently turns our check off.
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--hard", type=float, default=0.8)
    parser.add_argument("--soft", type=float, default=0.5)
    parser.add_argument("--irrelevant-weight", type=float, default=0.4)
    parser.add_argument(
        "--ip", default="203.0.113.1", help="Client address to attribute")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args()

    content = read_content(args)
    if not content:
        parser.error("give --text, --file, or pipe our content on stdin")

    import logging

    from remarkbox.api import views
    from remarkbox.models import spam
    from remarkbox.models.spam_llm import current_model, forget_discovered_model

    # check_spam records telemetry, which cannot work against our fake objects
    # and correctly swallows its own failure. Silence that one warning so our
    # report is not muddied by a message about something we chose not to do.
    logging.getLogger("remarkbox.models.spam_event").setLevel(logging.ERROR)

    # score_content keeps a process-global hash of recent posts per address.
    # Without clearing it, simulating our same text twice reports
    # duplicate_content and inflates our score by 0.4 -- an artifact of
    # simulating, not a property of our post.
    spam._recent_hashes.clear()
    forget_discovered_model()

    namespace = _FakeNamespace(args.namespace, args.description)
    parent_node = None
    if args.reply:
        root = _FakeRoot(
            args.thread_title, args.thread_content, page_uri=args.page_url)
        parent_node = _FakeParent(args.parent_content, root)

    request = _FakeRequest(build_settings(args), args.ip)
    result = views.check_spam(
        request,
        content,
        user=None,
        namespace=namespace,
        title=args.title,
        parent_node=parent_node,
    )

    action = result["action"] or "allowed"
    llm_signals = [s for s in result["signals"] if s.startswith("llm_")]
    report = {
        "action": action,
        "http_status": request.response.status_code,
        "spam_score": round(result["spam_score"], 4),
        "hard_threshold": args.hard,
        "soft_threshold": args.soft,
        "signals": result["signals"],
        "llm_enabled": args.llm,
        "llm_model": current_model() if args.llm else None,
        "llm_flagged_irrelevant": "llm_irrelevant" in llm_signals,
        "llm_reason": result["spam_reason"],
        "note": "IP reputation not simulated; real score may be higher",
    }

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        verdict = {
            "rejected": "REJECTED (403, never stored)",
            "held": "HELD for moderation (stored, approved=False)",
            "allowed": "ALLOWED (published)",
        }[action]
        print("action:      {}".format(verdict))
        print("spam_score:  {:.2f}  (hold >= {}, reject >= {})".format(
            result["spam_score"], args.soft, args.hard))
        print("signals:     {}".format(", ".join(result["signals"]) or "none"))
        if args.llm:
            print("llm model:   {}".format(current_model() or "unresolved"))
            print("llm verdict: {}".format(
                "IRRELEVANT" if report["llm_flagged_irrelevant"]
                else "relevant or inconclusive"))
            if result["spam_reason"]:
                print("llm reason:  {}".format(result["spam_reason"][:300]))
        else:
            print("llm:         not run (matches production, spam.llm.enabled unset)")
        print("note:        {}".format(report["note"]))

    # Exit code carries our verdict so this composes in a pipeline.
    sys.exit({"allowed": 0, "held": 1, "rejected": 2}[action])


if __name__ == "__main__":
    main()
