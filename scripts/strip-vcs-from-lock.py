#!/usr/bin/env python3
"""Strip VCS (git+) entries from a uv/pip-compile lock file.

pip's --require-hashes mode rejects every requirement that lacks a hash, and a
VCS dependency (git+ssh / git+https) cannot be hashed. Our git-hosted themes are
first-party repos, integrity-pinned by their own commit SHAs, and install via
'pip install .' at deploy time — so we remove them from the hash-locked PyPI set.

Usage: strip-vcs-from-lock.py requirements-prod.lock
"""
import re
import sys

path = sys.argv[1]
lines = open(path).read().splitlines()
out, skip, removed = [], False, []
for ln in lines:
    if skip:
        if ln[:1] in (" ", "\t"):  # continuation (# via) of a skipped VCS entry
            continue
        skip = False
    if re.match(r"^\S.*@ git\+", ln):
        removed.append(ln.split(" @ ")[0])
        skip = True
        continue
    out.append(ln)
open(path, "w").write("\n".join(out) + "\n")
print("stripped VCS deps:", removed or "(none)")
