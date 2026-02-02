"""
Parse @username mentions from comment text and resolve them to User objects.
"""

import re

import logging

log = logging.getLogger(__name__)

# Match @username where username is alphanumeric with dashes (matching
# is_user_name_valid from models/user.py).  Must be preceded by whitespace
# or start-of-string to avoid matching email addresses like foo@bar.
MENTION_RE = re.compile(r'(?:^|(?<=\s))@([A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)')


def parse_mention_usernames(text):
    """Return a set of unique usernames mentioned in text (without the @)."""
    if not text:
        return set()
    return set(MENTION_RE.findall(text))


def resolve_mentions(dbsession, text):
    """
    Parse @mentions from text, look up each username in the database.

    Returns a dict mapping lowercase username -> User object for users
    that exist. Non-existent usernames are omitted.
    """
    # Import here to avoid circular import (user -> node -> render -> mentions -> user).
    from remarkbox.models.user import get_user_by_name

    usernames = parse_mention_usernames(text)
    resolved = {}
    for username in usernames:
        user = get_user_by_name(dbsession, username)
        if user is not None:
            resolved[username.lower()] = user
    return resolved


def replace_mentions_with_links(html, resolved_users, link_prefix=""):
    """
    In rendered HTML, replace @username with profile links for resolved users.
    Non-existent usernames (not in resolved_users) are left as plain text.

    Args:
        html: the rendered HTML string
        resolved_users: dict of lowercase username -> User object
        link_prefix: URL prefix for profile links (e.g. "" or "/embed/ns/foo")

    Returns:
        HTML with @mentions converted to anchor tags for valid users.
    """
    if not resolved_users:
        return html

    def _replace(match):
        username = match.group(1)
        user = resolved_users.get(username.lower())
        if user is None:
            # Not a real user, leave as plain text.
            return match.group(0)
        # Use the user's canonical name for the display and link.
        return '<a href="{}/u/{}" class="mention">@{}</a>'.format(
            link_prefix, user.name, user.name
        )

    # Replace @username patterns in HTML, but skip anything inside tags
    # (e.g. inside href attributes). We use a two-pass approach:
    # first split on HTML tags, then only do replacements in text segments.
    parts = re.split(r'(<[^>]+>)', html)
    result = []
    for i, part in enumerate(parts):
        if part.startswith('<'):
            # This is an HTML tag, leave it alone.
            result.append(part)
        else:
            # This is a text segment, apply mention replacement.
            result.append(MENTION_RE.sub(_replace, part))
    return ''.join(result)
