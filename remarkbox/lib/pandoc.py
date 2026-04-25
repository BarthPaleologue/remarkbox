"""Pandoc integration for remarkbox.

Converts node trees to documents in any format pandoc supports.
Subprocess-based — no pip dependencies.
"""

import logging
import subprocess
import tempfile
import os

log = logging.getLogger(__name__)

# Formats that produce binary output (need file-based output, not stdout text).
BINARY_FORMATS = frozenset({
    "pdf", "docx", "odt", "epub", "epub2", "epub3", "pptx", "fb2",
})

# Formats we generate by default for namespace/thread-level export.
DEFAULT_FORMATS = [
    "markdown", "gfm", "commonmark", "html5", "rst",
    "mediawiki", "latex", "man", "plain", "rtf",
    "asciidoc", "textile", "org", "json",
    "epub", "docx", "odt", "pdf",
]

# Content types for HTTP responses.
CONTENT_TYPES = {
    "markdown": "text/markdown; charset=utf-8",
    "gfm": "text/markdown; charset=utf-8",
    "commonmark": "text/markdown; charset=utf-8",
    "commonmark_x": "text/markdown; charset=utf-8",
    "html": "text/html; charset=utf-8",
    "html5": "text/html; charset=utf-8",
    "html4": "text/html; charset=utf-8",
    "rst": "text/x-rst; charset=utf-8",
    "latex": "application/x-latex; charset=utf-8",
    "beamer": "application/x-latex; charset=utf-8",
    "man": "text/troff; charset=utf-8",
    "plain": "text/plain; charset=utf-8",
    "json": "application/json; charset=utf-8",
    "mediawiki": "text/plain; charset=utf-8",
    "asciidoc": "text/plain; charset=utf-8",
    "asciidoctor": "text/plain; charset=utf-8",
    "textile": "text/plain; charset=utf-8",
    "org": "text/plain; charset=utf-8",
    "rtf": "application/rtf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "odt": "application/vnd.oasis.opendocument.text",
    "epub": "application/epub+zip",
    "epub2": "application/epub+zip",
    "epub3": "application/epub+zip",
    "pdf": "application/pdf",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "fb2": "application/xml",
    "jira": "text/plain; charset=utf-8",
    "dokuwiki": "text/plain; charset=utf-8",
    "xwiki": "text/plain; charset=utf-8",
    "zimwiki": "text/plain; charset=utf-8",
    "typst": "text/plain; charset=utf-8",
    "context": "text/plain; charset=utf-8",
    "texinfo": "text/plain; charset=utf-8",
    "opml": "application/xml; charset=utf-8",
    "tei": "application/xml; charset=utf-8",
    "docbook": "application/xml; charset=utf-8",
    "docbook5": "application/xml; charset=utf-8",
    "icml": "application/xml; charset=utf-8",
}

# File extensions for download filenames.
FILE_EXTENSIONS = {
    "markdown": ".md",
    "gfm": ".md",
    "commonmark": ".md",
    "commonmark_x": ".md",
    "html": ".html",
    "html5": ".html",
    "html4": ".html",
    "rst": ".rst",
    "latex": ".tex",
    "beamer": ".tex",
    "man": ".1",
    "plain": ".txt",
    "json": ".json",
    "mediawiki": ".wiki",
    "asciidoc": ".adoc",
    "asciidoctor": ".adoc",
    "textile": ".textile",
    "org": ".org",
    "rtf": ".rtf",
    "docx": ".docx",
    "odt": ".odt",
    "epub": ".epub",
    "epub2": ".epub",
    "epub3": ".epub",
    "pdf": ".pdf",
    "pptx": ".pptx",
    "fb2": ".fb2",
    "jira": ".jira",
    "dokuwiki": ".txt",
    "xwiki": ".txt",
    "zimwiki": ".txt",
    "typst": ".typ",
    "context": ".tex",
    "texinfo": ".texi",
    "opml": ".opml",
    "tei": ".xml",
    "docbook": ".xml",
    "docbook5": ".xml",
    "icml": ".icml",
}


# URL extension → pandoc format name. Lets users hit intuitive extensions
# (`thread.md`, `thread.html`, `thread.tex`) instead of pandoc's internal
# names (`markdown`, `html5`, `latex`).
EXTENSION_ALIASES = {
    "md": "markdown",
    "markdown": "markdown",
    "htm": "html5",
    "html": "html5",
    "tex": "latex",
    "txt": "plain",
    "1": "man",
    "wiki": "mediawiki",
    "adoc": "asciidoc",
    "asciidoc": "asciidoc",
    "rst": "rst",
    "org": "org",
    "rtf": "rtf",
    "docx": "docx",
    "odt": "odt",
    "epub": "epub3",
    "pdf": "pdf",
    "pptx": "pptx",
    "fb2": "fb2",
    "jira": "jira",
    "typ": "typst",
    "texi": "texinfo",
    "opml": "opml",
    "icml": "icml",
    "json": "json",
    "xml": "docbook5",
    "ipynb": "ipynb",
}


def resolve_format(ext):
    """Map a URL extension (lowercase) to its pandoc format name.

    Falls back to the raw extension so pandoc's own format names
    (`commonmark_x`, `docbook5`, etc.) pass through unchanged.
    """
    ext = ext.lower()
    return EXTENSION_ALIASES.get(ext, ext)


def get_available_output_formats():
    """Return the set of output formats pandoc supports on this system."""
    try:
        result = subprocess.run(
            ["pandoc", "--list-output-formats"],
            capture_output=True, text=True, timeout=5,
        )
        return frozenset(result.stdout.strip().split("\n"))
    except Exception:
        log.exception("Failed to query pandoc output formats")
        return frozenset()


def get_available_input_formats():
    """Return the set of input formats pandoc supports on this system."""
    try:
        result = subprocess.run(
            ["pandoc", "--list-input-formats"],
            capture_output=True, text=True, timeout=5,
        )
        return frozenset(result.stdout.strip().split("\n"))
    except Exception:
        log.exception("Failed to query pandoc input formats")
        return frozenset()


def convert(source, from_format="markdown", to_format="html5", title=None, standalone=True):
    """Convert source text from one format to another via pandoc.

    Args:
        source: Input text.
        from_format: Pandoc input format name.
        to_format: Pandoc output format name.
        title: Optional document title (sets pandoc metadata).
        standalone: Pass --standalone to pandoc (full document). Set False
            for body fragments — required when storing HTML in data_html.

    Returns:
        bytes for binary formats (pdf, docx, etc.), str for text formats.

    Raises:
        subprocess.CalledProcessError on pandoc failure.
        ValueError if format is not supported.
    """
    is_binary = to_format in BINARY_FORMATS

    cmd = ["pandoc", "-f", from_format, "-t", to_format]
    if standalone:
        cmd.append("--standalone")

    if title:
        # For HTML-family outputs (and PDF, which we render through HTML via
        # wkhtmltopdf), set the template's pagetitle so we get <title> without
        # an extra title-block in the body — the rendered document already
        # carries its own H1 from the thread data. For every other format,
        # set the proper document metadata.
        if to_format in ("html", "html5", "html4", "chunkedhtml", "pdf"):
            cmd.extend(["-V", "pagetitle={}".format(title)])
        else:
            cmd.extend(["--metadata", "title={}".format(title)])

    # PDF needs explicit engine since no pdflatex.
    if to_format == "pdf":
        cmd.extend(["--pdf-engine=wkhtmltopdf"])

    if is_binary:
        # Binary formats need file output.
        with tempfile.NamedTemporaryFile(
            suffix=FILE_EXTENSIONS.get(to_format, ""), delete=False
        ) as tmp:
            tmp_path = tmp.name

        try:
            cmd.extend(["-o", tmp_path])
            subprocess.run(
                cmd, input=source, text=True,
                capture_output=True, timeout=60, check=True,
            )
            with open(tmp_path, "rb") as f:
                return f.read()
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    else:
        result = subprocess.run(
            cmd, input=source, text=True,
            capture_output=True, timeout=30, check=True,
        )
        return result.stdout


def _node_data_as_markdown(node):
    """Return node content rendered as markdown.

    The canonical rendered form of a node is node.data_html — produced at
    write time regardless of what source syntax the author used (markdown,
    rst, mediawiki, latex, html...). Converting HTML → markdown always
    yields real markdown, and sidesteps bugs where a node's source_format
    label disagrees with the actual bytes stored in node.data (observed
    in the wild: RST content labelled source_format="markdown").

    Falls back to raw node.data if data_html is absent or the conversion
    fails — better a rough dump than an empty export.
    """
    html = getattr(node, "data_html", None)
    if html:
        try:
            return convert(
                html, from_format="html", to_format="markdown",
                standalone=False,
            ).rstrip()
        except Exception:
            log.exception(
                "Pandoc failed converting node %s data_html to markdown; "
                "falling back to raw source",
                node.id,
            )
    return (node.data or "")


def node_tree_to_markdown(root_node, nodes, include_root=True, provenance=None):
    """Render a node tree as a nested markdown document.

    Args:
        root_node: The root Node object.
        nodes: Iterable of all Node objects in the tree (flat, any order).
        include_root: Whether to include the root node content.
        provenance: Optional dict from `provenance.build(...)` — when present,
            the document is wrapped in a header banner + QR code, with each
            reply heading hyperlinking its date to the canonical permalink,
            and a footer repeating the source URI.

    Returns:
        Markdown string with the full tree rendered as a document.
    """
    from remarkbox.lib import provenance as prov

    # Build lookup: parent_id -> sorted children
    children_map = {}
    node_map = {}
    for node in nodes:
        node_map[node.id] = node
        pid = node.parent_id
        if pid not in children_map:
            children_map[pid] = []
        children_map[pid].append(node)

    # Include root in the map
    if include_root and root_node.id not in node_map:
        node_map[root_node.id] = root_node

    # Sort children by created timestamp
    for pid in children_map:
        children_map[pid].sort(key=lambda n: n.created)

    lines = []

    if provenance:
        lines.append(prov.header_md(
            canonical_uri=provenance["canonical_uri"],
            snapshot_iso=provenance["snapshot_iso"],
            version=provenance["version"],
            qr_data_uri=provenance.get("qr_data_uri"),
            kind=provenance.get("kind", "thread"),
        ))

    # Thread bodies already carry their own H1 (or RST ==== underline that
    # becomes H1 after conversion). Don't prepend another `# {title}` — it
    # triples the title when pandoc then also adds a title-block in HTML/PDF.
    if include_root and root_node.data:
        lines.append(_node_data_as_markdown(root_node))
        lines.append("")

    def _render_children(parent_id, depth):
        for child in children_map.get(parent_id, []):
            if child.disabled:
                continue
            # Heading level based on depth (h2 for first-level replies, etc.)
            heading_level = min(depth + 2, 6)
            author = _get_author_name(child)
            date = child.created_date or ""
            permalink = prov.permalink_for_node(child) if provenance else None
            lines.append(prov.reply_heading_md(
                heading_level, author, date, permalink=permalink,
            ))
            lines.append("")
            if child.data:
                lines.append(_node_data_as_markdown(child))
                lines.append("")
            _render_children(child.id, depth + 1)

    _render_children(root_node.id, 0)

    if provenance:
        lines.append(prov.footer_md(
            canonical_uri=provenance["canonical_uri"],
            snapshot_iso=provenance["snapshot_iso"],
            version=provenance["version"],
        ))

    return "\n".join(lines)


def namespace_to_markdown(namespace, roots, node_fetcher, provenance=None):
    """Render an entire namespace as a markdown book.

    Args:
        namespace: The Namespace object.
        roots: Iterable of root Node objects (chapters).
        node_fetcher: Callable(root_node) -> list of all nodes in that tree.
        provenance: Optional dict from `provenance.build(...)` — when present,
            wraps the book with a header banner + QR pointing at the namespace
            index, hyperlinks every chapter title to the live thread, and
            hyperlinks every reply date to the live permalink.

    Returns:
        Markdown string with the full namespace as a document.
    """
    from remarkbox.lib import provenance as prov

    lines = []

    if provenance:
        lines.append(prov.header_md(
            canonical_uri=provenance["canonical_uri"],
            snapshot_iso=provenance["snapshot_iso"],
            version=provenance["version"],
            qr_data_uri=provenance.get("qr_data_uri"),
            kind=provenance.get("kind", "namespace"),
        ))

    # Book title
    title = namespace.description or namespace.name
    lines.append("# {}".format(title))
    lines.append("")

    for root in roots:
        if root.disabled:
            continue
        # Chapter heading — hyperlink to the live thread when provenance is on
        chapter_title = root.title or str(root.id)
        if provenance:
            lines.append("## [{}]({})".format(
                chapter_title, prov.canonical_uri_for_node(root),
            ))
        else:
            lines.append("## {}".format(chapter_title))
        lines.append("")
        if root.data:
            lines.append(_node_data_as_markdown(root))
            lines.append("")

        # Fetch all nodes in this thread
        thread_nodes = node_fetcher(root)

        # Build children map for this thread
        children_map = {}
        for node in thread_nodes:
            pid = node.parent_id
            if pid not in children_map:
                children_map[pid] = []
            children_map[pid].append(node)

        for pid in children_map:
            children_map[pid].sort(key=lambda n: n.created)

        def _render(parent_id, depth):
            for child in children_map.get(parent_id, []):
                if child.disabled:
                    continue
                heading_level = min(depth + 3, 6)
                author = _get_author_name(child)
                date = child.created_date or ""
                permalink = prov.permalink_for_node(child) if provenance else None
                lines.append(prov.reply_heading_md(
                    heading_level, author, date, permalink=permalink,
                ))
                lines.append("")
                if child.data:
                    lines.append(_node_data_as_markdown(child))
                    lines.append("")
                _render(child.id, depth + 1)

        _render(root.id, 0)

    if provenance:
        lines.append(prov.footer_md(
            canonical_uri=provenance["canonical_uri"],
            snapshot_iso=provenance["snapshot_iso"],
            version=provenance["version"],
        ))

    return "\n".join(lines)


def _get_author_name(node):
    """Extract display name from a node's user or surrogate."""
    if node.user:
        return node.user.name
    if node.user_surrogate:
        return node.user_surrogate.name
    return "Anonymous"
