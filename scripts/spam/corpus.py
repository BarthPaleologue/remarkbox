#!/usr/bin/env python3
"""
Build and grow a labelled corpus of spam and ham for evaluating our filter.

Our filter is only trustworthy if we know its false positive rate, and we can
only know that by testing it against real posts we have already judged. Spam
arrives from fox by hand. Ham is harvested here from comments already living
on our namespaces: real posts by real people that our filter must never hold.

A corpus entry:

    {
      "id": "peps-review-promo",
      "label": "spam",                     # or "ham"
      "title": "...",                      # optional
      "data": "...",                       # our post body
      "namespace": "meta.remarkbox.com",
      "description": "...",                # optional namespace description
      "kind": "thread",                    # or "reply"
      "thread_title": "...",               # reply context, optional
      "thread_content": "...",
      "parent_content": "...",
      "source": "harvested" | "manual",
      "note": "why we labelled it this way"
    }

Usage:
    # add a spam sample by hand (body on stdin or --file)
    python scripts/spam/corpus.py add --label spam --id peps-promo \\
        --namespace meta.remarkbox.com --title "..." --file /tmp/spam.txt

    # harvest ham from published comments on a namespace
    python scripts/spam/corpus.py harvest --namespace meta.remarkbox.com --limit 40

    # what have we got
    python scripts/spam/corpus.py stats

Harvest treats published, non-disabled comments as ham. That assumption is
only as good as our moderation: anything already disabled is skipped, but
unmoderated spam sitting in a namespace would be harvested as ham and teach
us the wrong lesson. Review what lands before trusting it, which is what
`--review` prints.
"""

import argparse
import json
import os
import sys

DEFAULT_CORPUS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "corpus.json"
)


def load_corpus(path):
    if not os.path.exists(path):
        return []
    with open(path) as handle:
        return json.load(handle)


def save_corpus(path, entries):
    with open(path, "w") as handle:
        json.dump(entries, handle, indent=2, sort_keys=True)
        handle.write("\n")


def cmd_add(args):
    entries = load_corpus(args.corpus)

    if args.file:
        with open(args.file) as handle:
            data = handle.read()
    elif args.data:
        data = args.data
    elif not sys.stdin.isatty():
        data = sys.stdin.read()
    else:
        print("give --data, --file, or pipe our body on stdin", file=sys.stderr)
        return 2

    entry_id = args.id or "manual-{}".format(len(entries) + 1)
    if any(e["id"] == entry_id for e in entries):
        print("id {!r} already in our corpus".format(entry_id), file=sys.stderr)
        return 2

    entries.append({
        "id": entry_id,
        "label": args.label,
        "title": args.title,
        "data": data,
        "namespace": args.namespace,
        "description": args.description,
        "kind": "reply" if args.reply else "thread",
        "thread_title": args.thread_title,
        "thread_content": args.thread_content,
        "parent_content": args.parent_content,
        "source": "manual",
        "note": args.note,
    })
    save_corpus(args.corpus, entries)
    print("added {} as {} ({} entries)".format(entry_id, args.label, len(entries)))
    return 0


def cmd_harvest(args):
    """Pull published comments off a namespace and label them ham."""
    sys.path.insert(
        0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                        "remarkbox", "api")
    )
    from remarkbox_client import RemarkboxClient

    client = RemarkboxClient(
        args.host,
        cookie_file=os.path.expanduser(args.cookie_file),
    )

    entries = load_corpus(args.corpus)
    known = {e["id"] for e in entries}

    threads = client.list_threads(args.namespace)
    items = threads.get("threads", threads) if isinstance(threads, dict) else threads

    harvested = 0
    skipped_disabled = 0
    for thread in items:
        if harvested >= args.limit:
            break
        detail = client.get_thread(thread["id"])
        root = detail.get("thread") or {}
        replies = detail.get("replies") or []

        # Our app passes a reply's immediate parent into our relevance check,
        # so a corpus without it judges replies stripped of the context that
        # makes them coherent. "Not bad, only 5 years!" is a normal reply and
        # nonsense on its own.
        by_id = {n["id"]: n for n in [root] + list(replies) if n.get("id")}

        for node in [root] + list(replies):
            if harvested >= args.limit:
                break
            if not node.get("data"):
                continue
            if node.get("disabled"):
                # Already judged spam by a human; not ham.
                skipped_disabled += 1
                continue
            entry_id = "ham-{}".format(node["id"][:12])
            if entry_id in known:
                continue
            is_root = node.get("is_root") or node is root
            entries.append({
                "id": entry_id,
                "label": "ham",
                "title": node.get("title") if is_root else None,
                "data": node["data"],
                "namespace": args.namespace,
                "description": args.description,
                "kind": "thread" if is_root else "reply",
                "thread_title": root.get("title") if not is_root else None,
                "thread_content": root.get("data") if not is_root else None,
                "parent_content": (
                    (by_id.get(node.get("parent_id")) or {}).get("data")
                    if not is_root else None
                ),
                "source": "harvested",
                "note": "published comment on {}".format(args.namespace),
            })
            known.add(entry_id)
            harvested += 1

    save_corpus(args.corpus, entries)
    print("harvested {} ham entries from {} (skipped {} disabled)".format(
        harvested, args.namespace, skipped_disabled))
    if args.review:
        for entry in entries[-harvested:] if harvested else []:
            body = " ".join(entry["data"].split())[:110]
            print("  {:<20} {}".format(entry["id"], body))
    return 0


def cmd_stats(args):
    entries = load_corpus(args.corpus)
    if not entries:
        print("corpus is empty: {}".format(args.corpus))
        return 0
    by_label = {}
    by_source = {}
    by_kind = {}
    for entry in entries:
        by_label[entry["label"]] = by_label.get(entry["label"], 0) + 1
        by_source[entry["source"]] = by_source.get(entry["source"], 0) + 1
        by_kind[entry["kind"]] = by_kind.get(entry["kind"], 0) + 1
    print("corpus:  {}".format(args.corpus))
    print("entries: {}".format(len(entries)))
    print("label:   {}".format(by_label))
    print("source:  {}".format(by_source))
    print("kind:    {}".format(by_kind))
    if by_label.get("ham", 0) == 0:
        print("\nno ham yet. A filter measured only against spam cannot show")
        print("its false positive rate. Run `corpus.py harvest`.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Manage our spam/ham corpus")
    parser.add_argument("--corpus", default=DEFAULT_CORPUS)
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="Add a sample by hand")
    add.add_argument("--label", choices=("spam", "ham"), required=True)
    add.add_argument("--id")
    add.add_argument("--data")
    add.add_argument("--file")
    add.add_argument("--title")
    add.add_argument("--namespace", default="meta.remarkbox.com")
    add.add_argument("--description")
    add.add_argument("--reply", action="store_true")
    add.add_argument("--thread-title")
    add.add_argument("--thread-content")
    add.add_argument("--parent-content")
    add.add_argument("--note")
    add.set_defaults(func=cmd_add)

    harvest = sub.add_parser("harvest", help="Harvest ham from a namespace")
    harvest.add_argument("--namespace", required=True)
    harvest.add_argument("--description")
    harvest.add_argument("--limit", type=int, default=25)
    harvest.add_argument("--host", default="https://my.remarkbox.com")
    harvest.add_argument("--cookie-file", default="~/.config/remarkbox/cookies.txt")
    harvest.add_argument("--review", action="store_true",
                         help="Print what we harvested so it can be eyeballed")
    harvest.set_defaults(func=cmd_harvest)

    stats = sub.add_parser("stats", help="Summarise our corpus")
    stats.set_defaults(func=cmd_stats)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
