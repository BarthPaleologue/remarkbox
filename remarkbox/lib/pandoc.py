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


def node_tree_to_markdown(root_node, nodes, include_root=True):
    """Render a node tree as a nested markdown document.

    Args:
        root_node: The root Node object.
        nodes: Iterable of all Node objects in the tree (flat, any order).
        include_root: Whether to include the root node content.

    Returns:
        Markdown string with the full tree rendered as a document.
    """
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

    if include_root and root_node.title:
        lines.append("# {}".format(root_node.title))
        lines.append("")

    if include_root and root_node.data:
        lines.append(root_node.data)
        lines.append("")

    def _render_children(parent_id, depth):
        for child in children_map.get(parent_id, []):
            if child.disabled:
                continue
            # Heading level based on depth (h2 for first-level replies, etc.)
            heading_level = min(depth + 2, 6)
            author = _get_author_name(child)
            date = child.created_date or ""
            lines.append("{} {} — {}".format("#" * heading_level, author, date))
            lines.append("")
            if child.data:
                lines.append(child.data)
                lines.append("")
            _render_children(child.id, depth + 1)

    _render_children(root_node.id, 0)

    return "\n".join(lines)


def namespace_to_markdown(namespace, roots, node_fetcher):
    """Render an entire namespace as a markdown book.

    Args:
        namespace: The Namespace object.
        roots: Iterable of root Node objects (chapters).
        node_fetcher: Callable(root_node) -> list of all nodes in that tree.

    Returns:
        Markdown string with the full namespace as a document.
    """
    lines = []

    # Book title
    title = namespace.description or namespace.name
    lines.append("# {}".format(title))
    lines.append("")

    for root in roots:
        if root.disabled:
            continue
        # Chapter heading
        chapter_title = root.title or str(root.id)
        lines.append("## {}".format(chapter_title))
        lines.append("")
        if root.data:
            lines.append(root.data)
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
                lines.append("{} {} — {}".format(
                    "#" * heading_level, author, date
                ))
                lines.append("")
                if child.data:
                    lines.append(child.data)
                    lines.append("")
                _render(child.id, depth + 1)

        _render(root.id, 0)

    return "\n".join(lines)


def _get_author_name(node):
    """Extract display name from a node's user or surrogate."""
    if node.user:
        return node.user.name
    if node.user_surrogate:
        return node.user_surrogate.name
    return "Anonymous"
