"""Unit tests for remarkbox.lib.pandoc — pandoc subprocess wrapper."""

import shutil
import unittest
import subprocess

import pytest

from remarkbox.lib.pandoc import (
    convert,
    node_tree_to_markdown,
    namespace_to_markdown,
    get_available_output_formats,
    get_available_input_formats,
    CONTENT_TYPES,
    FILE_EXTENSIONS,
    BINARY_FORMATS,
    _get_author_name,
)


class TestConvert(unittest.TestCase):
    """Unit tests for the pandoc convert() function."""

    def test_markdown_to_html(self):
        result = convert("# Hello\n\nWorld.", "markdown", "html5", title="Test")
        self.assertIn("<h1", result)
        self.assertIn("World.", result)

    def test_markdown_to_rst(self):
        result = convert("# Hello\n\n**bold** text.", "markdown", "rst")
        self.assertIn("**bold**", result)

    def test_markdown_to_plain(self):
        result = convert("# Title\n\n- item 1\n- item 2", "markdown", "plain")
        self.assertIn("item 1", result)
        self.assertIn("item 2", result)

    def test_html_to_markdown(self):
        result = convert("<h1>Title</h1><p>Paragraph.</p>", "html", "markdown")
        self.assertIn("Title", result)
        self.assertIn("Paragraph.", result)

    def test_rst_to_html(self):
        rst = "Title\n=====\n\nA paragraph."
        result = convert(rst, "rst", "html5")
        self.assertIn("Title", result)
        self.assertIn("paragraph", result)

    def test_mediawiki_to_html(self):
        wiki = "== Section ==\n\n'''bold''' text"
        result = convert(wiki, "mediawiki", "html5")
        self.assertIn("Section", result)

    def test_latex_to_html(self):
        latex = r"\section{Hello}\textbf{bold}"
        result = convert(latex, "latex", "html5")
        self.assertIn("Hello", result)

    def test_markdown_to_json(self):
        result = convert("# Test", "markdown", "json")
        self.assertIn('"pandoc-api-version"', result)

    def test_markdown_to_epub_returns_bytes(self):
        result = convert("# Test\n\nContent.", "markdown", "epub", title="Test")
        self.assertIsInstance(result, bytes)
        self.assertGreater(len(result), 100)

    @pytest.mark.skipif(
        shutil.which("wkhtmltopdf") is None,
        reason="wkhtmltopdf not installed",
    )
    def test_markdown_to_pdf_returns_bytes(self):
        result = convert("# Test\n\nContent.", "markdown", "pdf", title="Test")
        self.assertIsInstance(result, bytes)
        # PDF starts with %PDF
        self.assertTrue(result[:4] == b"%PDF")

    def test_markdown_to_docx_returns_bytes(self):
        result = convert("# Test\n\nContent.", "markdown", "docx", title="Test")
        self.assertIsInstance(result, bytes)
        # DOCX is a ZIP file (starts with PK)
        self.assertTrue(result[:2] == b"PK")

    def test_title_metadata(self):
        result = convert("Content.", "markdown", "html5", title="My Title")
        self.assertIn("My Title", result)

    def test_empty_input(self):
        result = convert("", "markdown", "html5")
        self.assertIsInstance(result, str)

    def test_invalid_format_raises(self):
        with self.assertRaises(subprocess.CalledProcessError):
            convert("test", "markdown", "not_a_real_format_xyz")


class TestAvailableFormats(unittest.TestCase):
    """Test format discovery."""

    def test_output_formats_returns_frozenset(self):
        formats = get_available_output_formats()
        self.assertIsInstance(formats, frozenset)
        self.assertGreater(len(formats), 50)
        self.assertIn("html5", formats)
        self.assertIn("markdown", formats)
        self.assertIn("pdf", formats)
        self.assertIn("epub", formats)

    def test_input_formats_returns_frozenset(self):
        formats = get_available_input_formats()
        self.assertIsInstance(formats, frozenset)
        self.assertGreater(len(formats), 30)
        self.assertIn("html", formats)
        self.assertIn("markdown", formats)
        self.assertIn("rst", formats)

    def test_content_types_has_common_formats(self):
        self.assertIn("html5", CONTENT_TYPES)
        self.assertIn("pdf", CONTENT_TYPES)
        self.assertIn("epub", CONTENT_TYPES)
        self.assertIn("docx", CONTENT_TYPES)
        self.assertIn("markdown", CONTENT_TYPES)
        self.assertEqual(CONTENT_TYPES["pdf"], "application/pdf")

    def test_file_extensions_has_common_formats(self):
        self.assertEqual(FILE_EXTENSIONS["markdown"], ".md")
        self.assertEqual(FILE_EXTENSIONS["html5"], ".html")
        self.assertEqual(FILE_EXTENSIONS["pdf"], ".pdf")
        self.assertEqual(FILE_EXTENSIONS["epub"], ".epub")
        self.assertEqual(FILE_EXTENSIONS["docx"], ".docx")

    def test_binary_formats(self):
        self.assertIn("pdf", BINARY_FORMATS)
        self.assertIn("docx", BINARY_FORMATS)
        self.assertIn("epub", BINARY_FORMATS)
        self.assertNotIn("html5", BINARY_FORMATS)
        self.assertNotIn("markdown", BINARY_FORMATS)


class MockNode:
    """Minimal mock of Node for tree rendering tests."""

    def __init__(self, id, title=None, data=None, parent_id=None,
                 created=0, disabled=False, user=None, user_surrogate=None,
                 created_date="2026-01-01"):
        self.id = id
        self.title = title
        self.data = data
        self.parent_id = parent_id
        self.created = created
        self.disabled = disabled
        self.user = user
        self.user_surrogate = user_surrogate
        self.created_date = created_date
        self.is_root = parent_id is None


class MockUser:
    def __init__(self, name):
        self.name = name


class MockNamespace:
    def __init__(self, name, description=None):
        self.name = name
        self.description = description


class TestNodeTreeToMarkdown(unittest.TestCase):
    """Test tree-to-markdown rendering."""

    def test_single_root_node(self):
        root = MockNode(1, title="Thread Title", data="Root content.")
        md = node_tree_to_markdown(root, [])
        self.assertIn("# Thread Title", md)
        self.assertIn("Root content.", md)

    def test_root_with_children(self):
        root = MockNode(1, title="Thread", data="Root.")
        child = MockNode(2, data="Reply text.", parent_id=1, created=1,
                         user=MockUser("alice"))
        md = node_tree_to_markdown(root, [child])
        self.assertIn("# Thread", md)
        self.assertIn("Root.", md)
        self.assertIn("alice", md)
        self.assertIn("Reply text.", md)

    def test_disabled_children_excluded(self):
        root = MockNode(1, title="Thread", data="Root.")
        child = MockNode(2, data="Visible.", parent_id=1, created=1,
                         user=MockUser("bob"))
        disabled = MockNode(3, data="Hidden.", parent_id=1, created=2,
                            disabled=True, user=MockUser("spam"))
        md = node_tree_to_markdown(root, [child, disabled])
        self.assertIn("Visible.", md)
        self.assertNotIn("Hidden.", md)

    def test_nested_children(self):
        root = MockNode(1, title="Thread", data="Root.")
        child = MockNode(2, data="Level 1.", parent_id=1, created=1,
                         user=MockUser("alice"))
        grandchild = MockNode(3, data="Level 2.", parent_id=2, created=2,
                              user=MockUser("bob"))
        md = node_tree_to_markdown(root, [child, grandchild])
        self.assertIn("Level 1.", md)
        self.assertIn("Level 2.", md)
        # Grandchild should have deeper heading
        self.assertIn("### bob", md)

    def test_exclude_root(self):
        root = MockNode(1, title="Hidden Title", data="Hidden root.")
        md = node_tree_to_markdown(root, [], include_root=False)
        self.assertNotIn("Hidden Title", md)
        self.assertNotIn("Hidden root.", md)

    def test_anonymous_author(self):
        root = MockNode(1, title="Thread")
        child = MockNode(2, data="Anon post.", parent_id=1, created=1)
        md = node_tree_to_markdown(root, [child])
        self.assertIn("Anonymous", md)

    def test_surrogate_author(self):
        root = MockNode(1, title="Thread")
        child = MockNode(2, data="Bot post.", parent_id=1, created=1,
                         user_surrogate=MockUser("MyBot"))
        md = node_tree_to_markdown(root, [child])
        self.assertIn("MyBot", md)


class TestNamespaceToMarkdown(unittest.TestCase):
    """Test namespace (book) rendering."""

    def test_empty_namespace(self):
        ns = MockNamespace("test.com", "Test Forum")
        md = namespace_to_markdown(ns, [], lambda r: [])
        self.assertIn("# Test Forum", md)

    def test_namespace_with_threads(self):
        ns = MockNamespace("test.com", "My Forum")
        root1 = MockNode(1, title="First Thread", data="Content 1.")
        root2 = MockNode(2, title="Second Thread", data="Content 2.")

        def fetcher(root):
            return []

        md = namespace_to_markdown(ns, [root1, root2], fetcher)
        self.assertIn("# My Forum", md)
        self.assertIn("## First Thread", md)
        self.assertIn("## Second Thread", md)
        self.assertIn("Content 1.", md)
        self.assertIn("Content 2.", md)

    def test_namespace_name_as_fallback_title(self):
        ns = MockNamespace("test.com")
        md = namespace_to_markdown(ns, [], lambda r: [])
        self.assertIn("# test.com", md)

    def test_disabled_roots_excluded(self):
        ns = MockNamespace("test.com")
        root = MockNode(1, title="Visible", data="Yes.", disabled=False)
        hidden = MockNode(2, title="Hidden", data="No.", disabled=True)
        md = namespace_to_markdown(ns, [root, hidden], lambda r: [])
        self.assertIn("Visible", md)
        self.assertNotIn("Hidden", md)


class TestGetAuthorName(unittest.TestCase):
    """Test _get_author_name helper."""

    def test_user(self):
        node = MockNode(1, user=MockUser("alice"))
        self.assertEqual(_get_author_name(node), "alice")

    def test_surrogate(self):
        node = MockNode(1, user_surrogate=MockUser("BotName"))
        self.assertEqual(_get_author_name(node), "BotName")

    def test_anonymous(self):
        node = MockNode(1)
        self.assertEqual(_get_author_name(node), "Anonymous")
