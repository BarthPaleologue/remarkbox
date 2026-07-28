"""Cross-site request forgery guards for API writes.

Our API write views opt out of Pyramid's CSRF token check, because our own
clients are not browsers and hold no token. That is safe only if a hostile
page cannot make an authenticated write on a victim's behalf — and by default
it can, because our session cookie is ambient and `SameSite=None` (required by
our embed product, which lives in third-party iframes).

Two guards close that, applied only to cookie-authenticated writes:

1. **Require a JSON content type.** A cross-site HTML form can only send
   `application/x-www-form-urlencoded`, `multipart/form-data`, or
   `text/plain` — those three are CORS "simple requests" that skip preflight.
   Asking for `application/json` forces a preflight our CORS policy never
   answers, so the write never happens. Our own Python and C clients already
   send this header.

2. **Validate `Origin` when present.** Defence in depth for anything that
   manages to send JSON cross-site (a misconfigured CORS policy, a future
   proxy). Absent `Origin` is allowed: non-browser clients omit it, and it is
   browsers we are defending against.

Bearer-authenticated requests skip both. A header cannot be attached
cross-site, so they were never forgeable.
"""

from pyramid.response import Response

from .auth import is_bearer_authenticated


WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")
JSON_CONTENT_TYPE = "application/json"


def _json_response(status, message):
    return Response(json_body={"error": message}, status=status)


def _hostname(netloc):
    """Return the bare hostname from a netloc, dropping any port.

    Ports are dropped on both sides of our comparison because they do not
    survive our deployment intact: a browser omits the default port from
    `Origin`, while `request.host` behind our proxy may carry one. Comparing
    with ports would reject legitimate writes. A different hostname is still a
    different host, which is what we are actually filtering on.
    """
    if not netloc:
        return ""
    netloc = netloc.lower().strip()
    # Bracketed IPv6 literal, e.g. [::1]:6543
    if netloc.startswith("["):
        return netloc.split("]")[0] + "]"
    return netloc.split(":")[0]


def _allowed_origin_hosts(request):
    """Hostnames an API write may legitimately originate from.

    Our own host, plus `app.app_url`'s host when configured — a cluster can
    serve many namespace hostnames from one app URI.
    """
    hosts = {_hostname(request.host)}

    app_url = request.registry.settings.get("app.app_url", "")
    if app_url:
        try:
            from urllib.parse import urlparse

            parsed = urlparse(app_url)
            if parsed.netloc:
                hosts.add(_hostname(parsed.netloc))
        except Exception:
            pass

    hosts.discard("")
    return hosts


def api_csrf_tween_factory(handler, registry):
    """Reject cross-site-forgeable writes to our API."""

    def api_csrf_tween(request):
        if not request.path.startswith("/api/v1/"):
            return handler(request)

        if request.method not in WRITE_METHODS:
            return handler(request)

        # Header auth is not ambient, so nothing to forge.
        if is_bearer_authenticated(request):
            return handler(request)

        # An HTML form can only issue GET or POST, so POST is the one write
        # method a hostile page can send without a preflight. PATCH, PUT, and
        # DELETE always preflight, and we answer no CORS headers, so a browser
        # blocks them before they reach us — which is why a bodyless DELETE
        # (our own `delete_node` sends one) does not need a content type.
        content_type = (request.content_type or "").split(";")[0].strip().lower()
        has_body = bool(request.body)

        if (request.method == "POST" or has_body) and content_type != JSON_CONTENT_TYPE:
            return _json_response(
                415,
                "API writes require Content-Type: application/json. "
                "Send a JSON body, or authenticate with an "
                "Authorization: Bearer token.",
            )

        origin = request.headers.get("Origin")
        if origin:
            try:
                from urllib.parse import urlparse

                origin_host = _hostname(urlparse(origin).netloc)
            except Exception:
                origin_host = ""

            if origin_host not in _allowed_origin_hosts(request):
                return _json_response(
                    403, "Cross-origin API writes are not allowed."
                )

        return handler(request)

    return api_csrf_tween
