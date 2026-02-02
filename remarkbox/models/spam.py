"""
Spam scoring for Remarkbox.

Scores content on a 0.0-1.0 scale where higher = more likely spam.
Used by API views to reject or hold posts for moderation.
"""

import hashlib
import os
import re
import time
from collections import defaultdict

from .node import Node

# In-memory caches (reset on process restart)
_recent_hashes = defaultdict(list)  # {ip_or_user_key: [(hash, timestamp), ...]}
_disabled_ip_counts = {}  # {ip: count} -- refreshed periodically
_disabled_ip_cache_time = 0

# Default spam patterns (common in comment spam)
DEFAULT_PATTERNS = [
    r"buy\s+now",
    r"click\s+here\s+to",
    r"free\s+trial",
    r"limited\s+time\s+offer",
    r"act\s+now",
    r"order\s+today",
    r"100%\s+free",
    r"make\s+money\s+fast",
    r"work\s+from\s+home",
    r"casino\s+online",
    r"viagra|cialis",
    r"payday\s+loan",
    r"seo\s+service",
    r"followers?\s+for\s+(free|sale|\$)",
    r"crypto\s+invest",
]

_compiled_patterns = None
_custom_patterns = None


def _get_patterns(settings=None):
    """Load and compile spam patterns. Cached after first call."""
    global _compiled_patterns, _custom_patterns

    patterns_file = None
    if settings:
        patterns_file = settings.get("spam.patterns_file")

    if _compiled_patterns is not None and _custom_patterns == patterns_file:
        return _compiled_patterns

    patterns = list(DEFAULT_PATTERNS)

    if patterns_file and os.path.exists(patterns_file):
        with open(patterns_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.append(line)

    _compiled_patterns = [re.compile(p, re.IGNORECASE) for p in patterns]
    _custom_patterns = patterns_file
    return _compiled_patterns


def _content_hash(text):
    """Return a short hash of the text for duplicate detection."""
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()[:16]


def _link_density(text):
    """Return the ratio of URL characters to total text length."""
    if not text:
        return 0.0
    urls = re.findall(r"https?://\S+", text)
    url_chars = sum(len(u) for u in urls)
    return url_chars / len(text) if text else 0.0


def _link_count(text):
    """Return number of URLs in text."""
    if not text:
        return 0
    return len(re.findall(r"https?://\S+", text))


def score_content(text, user=None, ip_address=None, dbsession=None, settings=None):
    """Score content for spam likelihood.

    Args:
        text: The post content.
        user: User object (may be None for anonymous).
        ip_address: Client IP address string.
        dbsession: SQLAlchemy session (for IP reputation checks).
        settings: Pyramid registry settings dict.

    Returns:
        (score, signals) where score is 0.0-1.0 and signals is a list
        of strings describing what triggered.
    """
    if not text:
        return 0.0, []

    signals = []
    score = 0.0

    # 1. Link density
    density = _link_density(text)
    links = _link_count(text)
    if density > 0.5:
        score += 0.4
        signals.append("link_density:{:.0%}".format(density))
    elif density > 0.3:
        score += 0.2
        signals.append("link_density:{:.0%}".format(density))
    if links > 5:
        score += 0.2
        signals.append("link_count:{}".format(links))

    # 2. Known spam patterns
    patterns = _get_patterns(settings)
    pattern_hits = 0
    for pattern in patterns:
        if pattern.search(text):
            pattern_hits += 1
    if pattern_hits >= 3:
        score += 0.5
        signals.append("spam_patterns:{}".format(pattern_hits))
    elif pattern_hits >= 1:
        score += 0.2
        signals.append("spam_patterns:{}".format(pattern_hits))

    # 3. Duplicate content (in-memory, recent posts by same IP/user)
    key = None
    if user and hasattr(user, "id"):
        key = "user:{}".format(user.id)
    elif ip_address:
        key = "ip:{}".format(ip_address)

    if key:
        content_hash = _content_hash(text)
        now = time.time()
        cutoff = now - 3600  # Look back 1 hour

        # Clean old entries
        _recent_hashes[key] = [
            (h, t) for h, t in _recent_hashes[key] if t > cutoff
        ]

        # Check for duplicates
        existing_hashes = [h for h, t in _recent_hashes[key]]
        if content_hash in existing_hashes:
            score += 0.4
            signals.append("duplicate_content")

        # Record this hash
        _recent_hashes[key].append((content_hash, now))

    # 4. New account velocity
    if user and hasattr(user, "created"):
        now_ms = int(time.time() * 1000)
        account_age_ms = now_ms - user.created
        one_hour_ms = 3600000

        if account_age_ms < one_hour_ms:
            # Account less than 1 hour old
            node_count = user.nodes.count() if hasattr(user.nodes, "count") else 0
            if node_count > 5:
                score += 0.3
                signals.append("new_account_velocity:{}posts_in_{}min".format(
                    node_count, account_age_ms // 60000
                ))
            elif node_count > 2:
                score += 0.1
                signals.append("new_account_velocity:{}posts".format(node_count))

    # 5. IP reputation (disabled posts from same IP)
    if ip_address and dbsession:
        global _disabled_ip_counts, _disabled_ip_cache_time
        now = time.time()

        # Refresh IP reputation cache every 5 minutes
        if now - _disabled_ip_cache_time > 300:
            _disabled_ip_counts = {}
            _disabled_ip_cache_time = now

        if ip_address not in _disabled_ip_counts:
            count = (
                dbsession.query(Node)
                .filter(Node.ip_address == ip_address, Node.disabled == True)
                .count()
            )
            _disabled_ip_counts[ip_address] = count

        disabled_count = _disabled_ip_counts[ip_address]
        if disabled_count > 3:
            score += 0.3
            signals.append("ip_reputation:{}disabled".format(disabled_count))

    # 6. Content length anomalies (from new users)
    is_new_user = False
    if user and hasattr(user, "created"):
        now_ms = int(time.time() * 1000)
        is_new_user = (now_ms - user.created) < 86400000  # < 1 day

    if is_new_user:
        if len(text) < 10:
            score += 0.1
            signals.append("very_short_content")
        elif len(text) > 50000:
            score += 0.2
            signals.append("very_long_content_new_user")

    # Cap at 1.0
    score = min(score, 1.0)

    return score, signals
