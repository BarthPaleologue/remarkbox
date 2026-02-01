import time
from collections import defaultdict

from pyramid.response import Response


def rate_limit_tween_factory(handler, registry):
    """
    Pyramid tween that rate-limits /api/v1/ requests and enforces
    the global api.enabled kill-switch.

    Configuration (from .ini):
        api.enabled = true
        api.rate_limit.read_requests = 120
        api.rate_limit.write_requests = 30
        api.rate_limit.window = 60
    """
    settings = registry.settings
    api_enabled = settings.get("api.enabled", "true").strip().lower() in ("true", "1", "yes")
    read_limit = int(settings.get("api.rate_limit.read_requests", 120))
    write_limit = int(settings.get("api.rate_limit.write_requests", 30))
    window = int(settings.get("api.rate_limit.window", 60))

    # In-memory storage: {key: [timestamp, ...]}
    request_log = defaultdict(list)

    def rate_limit_tween(request):
        if not request.path.startswith("/api/v1/"):
            return handler(request)

        if not api_enabled:
            return Response(
                json_body={"error": "API is disabled"},
                status=404,
                content_type="application/json",
            )

        auth_id = request.session.get("authenticated_user_id")
        key = "user:{}".format(auth_id) if auth_id else "ip:{}".format(request.client_addr)

        now = time.time()
        cutoff = now - window

        # Clean old entries
        request_log[key] = [t for t in request_log[key] if t > cutoff]

        # Determine limit based on method
        limit = write_limit if request.method in ("POST", "PUT", "PATCH", "DELETE") else read_limit

        if len(request_log[key]) >= limit:
            retry_after = int(request_log[key][0] + window - now) + 1
            return Response(
                json_body={
                    "error": "Rate limit exceeded",
                    "retry_after": retry_after,
                },
                status=429,
                content_type="application/json",
            )

        request_log[key].append(now)
        return handler(request)

    return rate_limit_tween
