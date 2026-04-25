"""Provenance for exported documents.

Every exported snapshot (PDF, EPUB, DOCX, HTML, plain markdown, ...) carries:
  - a top banner with canonical source URI, snapshot timestamp, generator version
  - a QR code linking back to the living source on Remarkbox
  - per-reply permalinks (academic citation style — date hyperlinks to anchor)
  - a footer repeating source URI + commit hash

A PDF printed today should still resolve to its living wiki source years from
now, scannable from paper. Documents are dead the moment they ship; we keep a
return path open.
"""

import base64
import io
from datetime import datetime, timezone

import segno


# ---------------------------------------------------------------------------
# Canonical URIs
# ---------------------------------------------------------------------------


def canonical_uri_for_namespace(namespace):
    """Return the canonical URI of a namespace's living index.

    A namespace's name IS its host (e.g. `meta.remarkbox.com`). This holds even
    for namespaces fronted only by `my.remarkbox.com/ns/{name}` — the name
    remains the unique identifier.
    """
    return "https://{}/".format(namespace.name)


def canonical_uri_for_node(node):
    """Return the canonical URI of a node's living source.

    Uses the namespace's name as host. Path comes from `node.path`
    (`/{id}/{slug}` or `/{id}`).
    """
    return "https://{}{}".format(node.root.namespace.name, node.path)


def permalink_for_node(node):
    """Return a deep link to a single reply: thread URI plus node-id anchor.

    Replies live inside a thread page, so the deep link is the thread URI with
    a fragment identifier.
    """
    root = node.root
    return "https://{}{}#{}".format(root.namespace.name, root.path, node.id)


# ---------------------------------------------------------------------------
# QR codes
# ---------------------------------------------------------------------------


def qr_png_data_uri(uri, scale=4, border=2):
    """Encode a URI as a PNG QR code wrapped in a data URI.

    PNG (not SVG) because pandoc's downstream renderers — wkhtmltopdf,
    rsvg-convert paths in DOCX/ODT/EPUB — handle PNG uniformly. A QR code's
    two-color palette compresses to a few hundred bytes; resolution is fine
    at print sizes.
    """
    qr = segno.make(uri, error="M")
    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=scale, border=border)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return "data:image/png;base64,{}".format(b64)


# ---------------------------------------------------------------------------
# Markdown blocks
# ---------------------------------------------------------------------------


def _utc_now_iso():
    """ISO 8601 UTC timestamp, second precision, with `Z` suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def header_md(canonical_uri, snapshot_iso=None, version="dev",
              qr_data_uri=None, kind="document"):
    """Top-of-document provenance banner + QR code.

    Args:
        canonical_uri: https://... URI of the living source.
        snapshot_iso: ISO 8601 timestamp; defaults to UTC now.
        version: Remarkbox build identifier (short git hash).
        qr_data_uri: Result of `qr_png_data_uri`; if None, no QR rendered.
        kind: "thread", "namespace", "subthread" — used in the snapshot caption.

    Returns markdown intended to sit at the very top of a document. When a QR
    is present we lay out text on the left and QR on the right via an HTML
    table; pandoc converts the table cleanly into HTML, PDF (wkhtmltopdf),
    DOCX, ODT, EPUB native table cells. Without a QR we fall back to a plain
    blockquote.
    """
    if snapshot_iso is None:
        snapshot_iso = _utc_now_iso()

    text_lines = [
        "> **Source:** [{}]({})  ".format(canonical_uri, canonical_uri),
        "> **Snapshot:** {}  ".format(snapshot_iso),
        "> **Generator:** Remarkbox `{}`  ".format(version),
        ">",
        "> *This is a {} snapshot. The living document lives at the source URI above — it may have been edited, extended, or replied-to since.*".format(kind),
    ]

    if not qr_data_uri:
        return "\n".join(text_lines + [""])

    text_block = "\n".join(text_lines)
    return (
        '<table class="provenance-header" style="border: 0; border-collapse: collapse; margin: 0 0 16px 0; width: 100%;">\n'
        '<tr style="border: 0;">\n'
        '<td style="border: 0; vertical-align: top; padding: 0 24px 0 0;">\n\n'
        '{text}\n\n'
        '</td>\n'
        '<td style="border: 0; vertical-align: top; width: 160px; text-align: right;">\n\n'
        '![Scan to visit the living source]({qr})\n\n'
        '</td>\n'
        '</tr>\n'
        '</table>\n'
    ).format(text=text_block, qr=qr_data_uri)


def footer_md(canonical_uri, snapshot_iso=None, version="dev"):
    """End-of-document provenance footer."""
    if snapshot_iso is None:
        snapshot_iso = _utc_now_iso()
    return "\n".join([
        "",
        "---",
        "",
        "**Source:** [{}]({})  ".format(canonical_uri, canonical_uri),
        "**Snapshot:** {}  ".format(snapshot_iso),
        "**Generator:** Remarkbox `{}`".format(version),
        "",
    ])


def reply_heading_md(level, author, date, permalink=None):
    """Render a reply heading with optional permalink hyperlinking the date.

    Hyperlinking the date keeps academic-citation style readable: the visible
    text is still `Author — date`, the date itself becomes the anchor.
    """
    if permalink:
        return "{} {} — [{}]({})".format("#" * level, author, date, permalink)
    return "{} {} — {}".format("#" * level, author, date)


# ---------------------------------------------------------------------------
# One-shot bundle (convenience)
# ---------------------------------------------------------------------------


def build(canonical_uri, version, kind="document", include_qr=True):
    """Build a complete provenance bundle in one call.

    Returns a dict suitable for splatting into `node_tree_to_markdown` or
    `namespace_to_markdown` as `**provenance`.
    """
    snapshot_iso = _utc_now_iso()
    qr_data_uri = qr_png_data_uri(canonical_uri) if include_qr else None
    return {
        "canonical_uri": canonical_uri,
        "snapshot_iso": snapshot_iso,
        "version": version,
        "qr_data_uri": qr_data_uri,
        "kind": kind,
    }
