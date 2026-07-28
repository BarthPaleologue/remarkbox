"""Bearer-token authentication for our API.

Two ways to authenticate an API request:

* `Authorization: Bearer <token>` — not ambient. A cross-site page cannot add
  this header, so a token-authenticated write cannot be forged.
* our session cookie — ambient, and our embed product needs
  `SameSite=None`, so browsers attach it cross-site. Those requests get our
  extra guards in `csrf.py`.
"""

from remarkbox.models.api_token import get_api_token_by_raw


BEARER_PREFIX = "bearer "


def get_bearer_token(request):
    """Return the raw bearer token on this request, or None."""
    header = request.headers.get("Authorization", "")
    if not header:
        return None
    if not header.lower().startswith(BEARER_PREFIX):
        return None
    token = header[len(BEARER_PREFIX):].strip()
    return token or None


def resolve_bearer_user(request):
    """Return the authenticated User for this request's bearer token, or None.

    Marks the user authenticated the same way our session path does, so views
    need no knowledge of which credential arrived.
    """
    raw_token = get_bearer_token(request)
    if not raw_token:
        return None

    token = get_api_token_by_raw(request.dbsession, raw_token)
    if token is None or token.user is None:
        return None

    token.touch()
    user = token.user
    user.authenticated = True
    return user


def is_bearer_authenticated(request):
    """True when this request carries a bearer token we accepted."""
    return get_bearer_token(request) is not None
