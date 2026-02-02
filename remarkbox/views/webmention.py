"""
Webmention receiving endpoint.

Implements the W3C Webmention spec (https://www.w3.org/TR/webmention/).
"""

import logging
import re
import urllib.request
import urllib.error

from pyramid.view import view_config
from pyramid.response import Response

from remarkbox.models.uri import get_uri_by_uri
from remarkbox.models.webmention import (
    get_webmention_by_source_and_target,
    Webmention,
)

log = logging.getLogger(__name__)

MAX_SOURCE_SIZE = 256 * 1024
FETCH_TIMEOUT = 10


def _is_valid_url(url):
    return url and (url.startswith("http://") or url.startswith("https://"))


def _fetch_source(source_url):
    try:
        req = urllib.request.Request(
            source_url,
            headers={"User-Agent": "Remarkbox Webmention/1.0"},
        )
        resp = urllib.request.urlopen(req, timeout=FETCH_TIMEOUT)
        body = resp.read(MAX_SOURCE_SIZE)
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError:
            return body.decode("latin-1")
    except Exception:
        log.warning("Failed to fetch source URL: %s", source_url, exc_info=True)
        return None


def _extract_author(html):
    author_name = None
    author_url = None
    h_card_match = re.search(
        r'class="[^"]*h-card[^"]*"[^>]*>.*?class="[^"]*p-name[^"]*"[^>]*>([^<]+)',
        html, re.DOTALL | re.IGNORECASE,
    )
    if h_card_match:
        author_name = h_card_match.group(1).strip()
    url_match = re.search(
        r'class="[^"]*h-card[^"]*"[^>]*>.*?class="[^"]*u-url[^"]*"[^>]*href="([^"]+)"',
        html, re.DOTALL | re.IGNORECASE,
    )
    if url_match:
        author_url = url_match.group(1).strip()
    return author_name, author_url


def _extract_content_snippet(html, target_url):
    pattern = re.escape(target_url)
    match = re.search(pattern, html)
    if match:
        start = max(0, match.start() - 200)
        end = min(len(html), match.end() + 200)
        snippet = html[start:end]
        snippet = re.sub(r"<[^>]+>", " ", snippet)
        snippet = re.sub(r"\s+", " ", snippet).strip()
        if len(snippet) > 300:
            snippet = snippet[:300] + "..."
        return snippet
    return None


@view_config(route_name="webmention", request_method="POST", require_csrf=False)
@view_config(route_name="api-webmention", request_method="POST", require_csrf=False)
def receive_webmention(request):
    try:
        body = request.json_body
    except Exception:
        body = {}

    source = body.get("source") or request.params.get("source", "")
    target = body.get("target") or request.params.get("target", "")

    if not source or not target:
        return Response(json_body={"error": "source and target parameters are required"}, status=400, content_type="application/json")
    if not _is_valid_url(source):
        return Response(json_body={"error": "source must be a valid HTTP or HTTPS URL"}, status=400, content_type="application/json")
    if not _is_valid_url(target):
        return Response(json_body={"error": "target must be a valid HTTP or HTTPS URL"}, status=400, content_type="application/json")
    if source == target:
        return Response(json_body={"error": "source and target must be different URLs"}, status=400, content_type="application/json")

    uri = get_uri_by_uri(request.dbsession, target)
    if uri is None or uri.node is None:
        return Response(json_body={"error": "target URL does not match any Remarkbox thread"}, status=400, content_type="application/json")

    root_node = uri.node if uri.node.is_root else uri.node.root
    existing = get_webmention_by_source_and_target(request.dbsession, source, target)

    source_html = _fetch_source(source)
    if source_html is None:
        return Response(json_body={"error": "Could not fetch source URL"}, status=400, content_type="application/json")
    if target not in source_html:
        return Response(json_body={"error": "Source URL does not contain a link to the target"}, status=400, content_type="application/json")

    author_name, author_url = _extract_author(source_html)
    content_snippet = _extract_content_snippet(source_html, target)

    if existing:
        existing.mark_verified(author_name=author_name, author_url=author_url, content=content_snippet)
        request.dbsession.add(existing)
        request.dbsession.flush()
        log.info("webmention updated: source=%s target=%s node=%s", source, target, root_node.id)
        return Response(json_body={"status": "updated", "id": str(existing.id)}, status=200, content_type="application/json")

    webmention = Webmention(source=source, target=target)
    webmention.node = root_node
    webmention.mark_verified(author_name=author_name, author_url=author_url, content=content_snippet)
    request.dbsession.add(webmention)
    request.dbsession.flush()
    log.info("webmention received: source=%s target=%s node=%s", source, target, root_node.id)
    return Response(json_body={"status": "accepted", "id": str(webmention.id)}, status=202, content_type="application/json")
