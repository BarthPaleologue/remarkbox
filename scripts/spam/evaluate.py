#!/usr/bin/env python3
"""
Run our whole spam pipeline over a labelled corpus and report what it got wrong.

Tuning a filter by looking at one post at a time is how we end up holding real
comments. This scores every labelled sample through our real `check_spam` and
prints a confusion matrix, so a threshold change can be judged on our whole
corpus instead of on whatever example is in front of us.

False positives are reported first and loudest. A missed spam is an annoyance
a moderator cleans up; a held comment is a person who thinks we ate their
words. Those costs are not symmetric and this output should not pretend they
are.

Usage:
    python scripts/spam/evaluate.py                        # heuristics only
    python scripts/spam/evaluate.py --llm                  # with relevance check
    python scripts/spam/evaluate.py --llm --soft 0.4       # try a threshold
    python scripts/spam/evaluate.py --llm --json

Exit code is non-zero when any ham would be held or rejected.
"""

import argparse
import json
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)

DEFAULT_CORPUS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "corpus.json"
)


def evaluate_entry(entry, args, index):
    """Score one corpus entry through our real pipeline."""
    from remarkbox.api import views
    from remarkbox.models import spam
    from remarkbox.models.spam_llm import current_model

    # Import our fakes from our simulator so both tools model a request the
    # same way; two copies would drift.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from simulate import (
        _FakeNamespace, _FakeParent, _FakeRoot, _FakeRequest, build_settings,
    )

    # Each sample gets its own address, and our recent-hash cache is cleared,
    # so identical bodies in our corpus do not read as duplicate content.
    spam._recent_hashes.clear()

    namespace = _FakeNamespace(
        entry.get("namespace") or "example.com", entry.get("description")
    )
    parent_node = None
    if entry.get("kind") == "reply":
        parent_node = _FakeParent(
            entry.get("parent_content"),
            _FakeRoot(entry.get("thread_title"), entry.get("thread_content")),
        )

    request = _FakeRequest(
        build_settings(args), "198.51.100.{}".format(index % 250 + 1)
    )
    result = views.check_spam(
        request,
        entry["data"],
        user=None,
        namespace=namespace,
        title=entry.get("title"),
        parent_node=parent_node,
    )
    return {
        "id": entry["id"],
        "label": entry["label"],
        "action": result["action"] or "allowed",
        "spam_score": round(result["spam_score"], 4),
        "signals": result["signals"],
        "llm_model": current_model() if args.llm else None,
        "llm_reason": result["spam_reason"],
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate our filter on a corpus")
    parser.add_argument("--corpus", default=DEFAULT_CORPUS)
    parser.add_argument("--llm", action="store_true")
    parser.add_argument(
        "--endpoint", default="https://hermes.ai.unturf.com/v1/chat/completions")
    parser.add_argument("--model", default=None)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--hard", type=float, default=0.8)
    parser.add_argument("--soft", type=float, default=0.5)
    parser.add_argument("--irrelevant-weight", type=float, default=0.4)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    import logging
    logging.getLogger("remarkbox.models.spam_event").setLevel(logging.ERROR)

    if not os.path.exists(args.corpus):
        print("no corpus at {}. Build one with corpus.py".format(args.corpus),
              file=sys.stderr)
        return 2
    with open(args.corpus) as handle:
        entries = json.load(handle)
    if args.limit:
        entries = entries[: args.limit]
    if not entries:
        print("corpus is empty", file=sys.stderr)
        return 2

    results = [evaluate_entry(e, args, i) for i, e in enumerate(entries)]

    # "Acted on" means held or rejected. Both are visible to a poster.
    acted = lambda r: r["action"] in ("held", "rejected")
    spam_results = [r for r in results if r["label"] == "spam"]
    ham_results = [r for r in results if r["label"] == "ham"]

    caught = [r for r in spam_results if acted(r)]
    missed = [r for r in spam_results if not acted(r)]
    false_positives = [r for r in ham_results if acted(r)]
    correct_ham = [r for r in ham_results if not acted(r)]

    summary = {
        "corpus": args.corpus,
        "llm_enabled": args.llm,
        "soft_threshold": args.soft,
        "hard_threshold": args.hard,
        "irrelevant_weight": args.irrelevant_weight,
        "spam_total": len(spam_results),
        "spam_caught": len(caught),
        "spam_missed": len(missed),
        "ham_total": len(ham_results),
        "ham_false_positives": len(false_positives),
        "ham_correct": len(correct_ham),
    }

    if args.json:
        print(json.dumps(
            {"summary": summary, "results": results}, indent=2, sort_keys=True))
    else:
        print("corpus: {} ({} spam, {} ham)  llm={}".format(
            os.path.basename(args.corpus), len(spam_results), len(ham_results),
            "on" if args.llm else "off"))
        print("thresholds: hold>={} reject>={} irrelevant_weight={}".format(
            args.soft, args.hard, args.irrelevant_weight))
        print()

        if false_positives:
            print("FALSE POSITIVES -- real comments we would have acted on:")
            for r in false_positives:
                print("  {:<22} {:<8} score={:.2f} signals={}".format(
                    r["id"], r["action"], r["spam_score"],
                    ",".join(r["signals"]) or "none"))
            print()
        else:
            print("false positives: none\n")

        if missed:
            print("MISSED SPAM -- would have been published:")
            for r in missed:
                print("  {:<22} score={:.2f} signals={}".format(
                    r["id"], r["spam_score"], ",".join(r["signals"]) or "none"))
            print()

        print("spam caught: {}/{}".format(len(caught), len(spam_results)))
        print("ham kept:    {}/{}".format(len(correct_ham), len(ham_results)))
        if not ham_results:
            print("\nNo ham in our corpus, so this says nothing about false")
            print("positives. Harvest some: corpus.py harvest --namespace X")

    # Non-zero when we would have eaten someone's real comment.
    return 1 if false_positives else 0


if __name__ == "__main__":
    sys.exit(main())
