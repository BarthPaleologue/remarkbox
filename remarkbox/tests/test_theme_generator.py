"""Unit tests for remarkbox.lib.theme_generator."""

import unittest

from remarkbox.lib.theme_generator import (
    generate_theme_css,
    _name_to_hue,
    _name_to_seed,
)


class TestNameToHue(unittest.TestCase):
    """Test deterministic hue generation."""

    def test_returns_int_in_range(self):
        hue = _name_to_hue("test.com")
        self.assertIsInstance(hue, int)
        self.assertGreaterEqual(hue, 0)
        self.assertLess(hue, 360)

    def test_deterministic(self):
        h1 = _name_to_hue("meta.remarkbox.com")
        h2 = _name_to_hue("meta.remarkbox.com")
        self.assertEqual(h1, h2)

    def test_different_names_different_hues(self):
        h1 = _name_to_hue("meta.remarkbox.com")
        h2 = _name_to_hue("faq.remarkbox.com")
        # Could theoretically collide but extremely unlikely
        self.assertNotEqual(h1, h2)


class TestNameToSeed(unittest.TestCase):
    """Test seed generation."""

    def test_returns_tuple_of_ints(self):
        seed = _name_to_seed("test.com")
        self.assertIsInstance(seed, tuple)
        self.assertEqual(len(seed), 8)
        for v in seed:
            self.assertIsInstance(v, int)

    def test_deterministic(self):
        s1 = _name_to_seed("test.com")
        s2 = _name_to_seed("test.com")
        self.assertEqual(s1, s2)


class TestGenerateThemeCSS(unittest.TestCase):
    """Test CSS theme generation."""

    def test_returns_string(self):
        css = generate_theme_css("test.com")
        self.assertIsInstance(css, str)
        self.assertGreater(len(css), 500)

    def test_deterministic(self):
        css1 = generate_theme_css("meta.remarkbox.com")
        css2 = generate_theme_css("meta.remarkbox.com")
        self.assertEqual(css1, css2)

    def test_different_namespaces_different_css(self):
        css1 = generate_theme_css("meta.remarkbox.com")
        css2 = generate_theme_css("faq.remarkbox.com")
        self.assertNotEqual(css1, css2)

    def test_contains_css_custom_properties(self):
        css = generate_theme_css("test.com")
        self.assertIn("--rb-bg:", css)
        self.assertIn("--rb-text:", css)
        self.assertIn("--rb-link:", css)
        self.assertIn("--rb-accent:", css)
        self.assertIn("--rb-border:", css)

    def test_contains_light_mode(self):
        css = generate_theme_css("test.com")
        self.assertIn(":root", css)
        self.assertIn(".theme-light", css)

    def test_contains_dark_mode(self):
        css = generate_theme_css("test.com")
        self.assertIn("prefers-color-scheme: dark", css)
        self.assertIn(".theme-dark", css)

    def test_contains_namespace_name_comment(self):
        css = generate_theme_css("my-forum.example.org")
        self.assertIn("my-forum.example.org", css)

    def test_contains_element_styles(self):
        css = generate_theme_css("test.com")
        self.assertIn(".node", css)
        self.assertIn("blockquote", css)
        self.assertIn(".rb-submit", css)
        self.assertIn("textarea", css)

    def test_uses_hsl_colors(self):
        css = generate_theme_css("test.com")
        self.assertIn("hsl(", css)

    def test_various_namespaces_all_valid(self):
        """Ensure no crashes for various namespace name patterns."""
        names = [
            "a.com",
            "very-long-domain-name-that-goes-on.example.com",
            "unicode-test-日本語.com",
            "123.456.789",
            "",
            "single",
        ]
        for name in names:
            css = generate_theme_css(name)
            self.assertIsInstance(css, str)
            self.assertGreater(len(css), 100)

# Keep this module's tests together on one xdist worker. Test modules share a
# per-worker database; when --dist=loadgroup deals unmarked tests out
# individually, classes from different modules interleave on a worker and one
# class's tearDownClass drop_all yanks tables from another class mid-run.
import pytest as _pytest

pytestmark = _pytest.mark.xdist_group("test_theme_generator")
