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
        api.rate_limit.create_thread_requests = 1
        api.rate_limit.create_thread_window = 420
        api.rate_limit.extra_paths = /preview-post
        api.rate_limit.export_requests = 5
        api.rate_limit.export_window = 60
        api.rate_limit.export_formats = pdf epub docx odt

    `extra_paths` is a whitespace-separated list of non-API paths to throttle
    under the same buckets. It exists because `/preview-post` runs a pandoc
    subprocess for anonymous callers: one request is one process, and before
    this the tween returned early for every path outside /api/v1/, so that
    endpoint had no limit at all. Configurable rather than hardcoded so a
    deployment can throttle any other expensive path without a code change.

    Exports get their own, much smaller bucket. A whole-namespace export in a
    heavy format is the most expensive request we serve — pandoc plus, for
    `.pdf`, a `wkhtmltopdf` subprocess, over every thread in a namespace — and
    it needs no authentication. Sharing our ordinary 120/min read bucket meant
    an anonymous caller could ask for 120 of those a minute. Markdown and HTML
    exports stay on the ordinary bucket: they short-circuit pandoc entirely or
    cost about as much as any other read.
    """
    settings = registry.settings
    api_enabled = settings.get("api.enabled", "true").strip().lower() in ("true", "1", "yes")
    read_limit = int(settings.get("api.rate_limit.read_requests", 120))
    write_limit = int(settings.get("api.rate_limit.write_requests", 30))
    window = int(settings.get("api.rate_limit.window", 60))
    create_thread_limit = int(settings.get("api.rate_limit.create_thread_requests", 5))
    create_thread_window = int(settings.get("api.rate_limit.create_thread_window", 3600))
    extra_paths = tuple(
        settings.get("api.rate_limit.extra_paths", "/preview-post").split()
    )
    export_limit = int(settings.get("api.rate_limit.export_requests", 5))
    export_window = int(settings.get("api.rate_limit.export_window", 60))
    export_formats = tuple(
        "." + fmt.lstrip(".").lower()
        for fmt in settings.get(
            "api.rate_limit.export_formats", "pdf epub docx odt"
        ).split()
    )

    # In-memory storage: {key: [timestamp, ...]}
    request_log = defaultdict(list)
    create_thread_log = defaultdict(list)
    export_log = defaultdict(list)

    def rate_limit_tween(request):
        is_api = request.path.startswith("/api/v1/")
        # Match extra paths exactly, so a prefix can't be widened by accident.
        is_extra = request.path in extra_paths

        if not is_api and not is_extra:
            return handler(request)

        # The kill-switch governs our API only; extra paths are ordinary app
        # endpoints that happen to be expensive, and must keep working when
        # the API is switched off.
        if is_api and not api_enabled:
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

        # Stricter limit for expensive export formats. Checked after our
        # ordinary bucket so an export still counts as a read too.
        is_expensive_export = (
            request.path.startswith("/api/v1/export/")
            and request.path.lower().endswith(export_formats)
        )
        if is_expensive_export:
            ex_cutoff = now - export_window
            export_log[key] = [t for t in export_log[key] if t > ex_cutoff]
            if len(export_log[key]) >= export_limit:
                retry_after = int(
                    export_log[key][0] + export_window - now
                ) + 1
                return Response(
                    json_body={
                        "error": "Export rate limit exceeded",
                        "retry_after": retry_after,
                    },
                    status=429,
                    content_type="application/json",
                )
            export_log[key].append(now)

        # Stricter limit for thread creation to prevent spam floods
        is_create_thread = (
            request.method == "POST" and request.path == "/api/v1/threads"
        )
        if is_create_thread:
            ct_cutoff = now - create_thread_window
            create_thread_log[key] = [
                t for t in create_thread_log[key] if t > ct_cutoff
            ]
            if len(create_thread_log[key]) >= create_thread_limit:
                retry_after = int(
                    create_thread_log[key][0] + create_thread_window - now
                ) + 1
                return Response(
                    json_body={
                        "error": "Thread creation rate limit exceeded",
                        "retry_after": retry_after,
                    },
                    status=429,
                    content_type="application/json",
                )
            create_thread_log[key].append(now)

        request_log[key].append(now)
        return handler(request)

    return rate_limit_tween
