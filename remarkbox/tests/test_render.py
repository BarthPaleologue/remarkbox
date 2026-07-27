import time
import unittest
from packaging.version import Version

from remarkbox.models import Namespace, User

from remarkbox.lib.render import (
    markdown_to_raw_html,
    clean_raw_html,
    make_cleaner_from_namespace,
)


SAMPLE_MARKDOWN = """
Hi
===

* this
* is
* a

Bullet.

[internal relative](/about/)

[internal absolute](https://russell.ballestrini.net/about/)

[external](https://www.remarkbox.com/)

<script type="math/tex; mode=display">y=x^2</script> 

<script>alert(document.cookie);</script>
"""


class TestRenderMarkdown(unittest.TestCase):

    def test_markdown_to_raw_html(self):
        self.assertEqual(
            markdown_to_raw_html(SAMPLE_MARKDOWN),
            """<h1>Hi</h1>\n<ul>\n<li>this</li>\n<li>is</li>\n<li>a</li>\n</ul>\n<p>Bullet.</p>\n<p><a href="/about/">internal relative</a></p>\n<p><a href="https://russell.ballestrini.net/about/">internal absolute</a></p>\n<p><a href="https://www.remarkbox.com/">external</a></p>\n<script type="math/tex; mode=display">y=x^2</script>\n\n<script>alert(document.cookie);</script>""",
        )

    def test_make_cleaner_from_default_namespace(self):
        namespace = Namespace("russell.ballestrini.net")
        cleaner = make_cleaner_from_namespace(namespace)
        self.assertFalse(cleaner.link_protection)
        self.assertEqual("russell.ballestrini.net", cleaner.absolute_domain)
        self.assertIn("russell.ballestrini.net", cleaner.whitelist_domains)

    def test_make_cleaner_from_custom_namespace(self):
        namespace = Namespace("russell.ballestrini.net")
        namespace.subscription_type = "production"
        namespace.mathjax = True
        namespace.link_protection = True
        cleaner = make_cleaner_from_namespace(namespace)
        self.assertTrue(cleaner.link_protection)
        self.assertIn("script", cleaner.tags)
        self.assertEqual("russell.ballestrini.net", cleaner.absolute_domain)
        self.assertIn("russell.ballestrini.net", cleaner.whitelist_domains)

    def test_mathjax_enabled_and_disabled(self):
        raw_html = markdown_to_raw_html(SAMPLE_MARKDOWN)
        namespace = Namespace("russell.ballestrini.net")
        namespace.subscription_type = "production"

        # test mathjax enabled.
        namespace.mathjax = True
        cleaner = make_cleaner_from_namespace(namespace)
        self.assertTrue(cleaner.mathjax)
        clean_html = clean_raw_html(raw_html, cleaner)
        self.assertIn(
            '<script type="math/tex; mode=display">y=x^2</script>', clean_html
        )

        # test mathjax disabled.
        namespace.mathjax = False
        cleaner = make_cleaner_from_namespace(namespace)
        self.assertFalse(cleaner.mathjax)
        clean_html = clean_raw_html(raw_html, cleaner)
        self.assertNotIn(
            '<script type="math/tex; mode=display">y=x^2</script>', clean_html
        )

    def test_link_protection_enabled(self):
        raw_html = markdown_to_raw_html(SAMPLE_MARKDOWN)
        namespace = Namespace("russell.ballestrini.net")
        namespace.subscription_type = "production"
        namespace.link_protection = True
        cleaner = make_cleaner_from_namespace(namespace)
        clean_html = clean_raw_html(raw_html, cleaner)

        self.assertIn(
            '<a href="https://russell.ballestrini.net/about/">internal relative</a>',
            clean_html,
        )
        self.assertIn(
            '<a href="https://russell.ballestrini.net/about/">internal absolute</a>',
            clean_html,
        )
        self.assertIn("<p>[link removed]</p>", clean_html)
        self.assertNotIn(
            '<a href="https://www.remarkbox.com/">external</a>',
            clean_html,
        )

    def test_link_protection_enabled_in_development_mode(self):
        """
        When a Namespace moves from production to development, we stop
        loading custom settings, and fall back to defaults attributes.
        """
        raw_html = markdown_to_raw_html(SAMPLE_MARKDOWN)
        namespace = Namespace("russell.ballestrini.net")
        namespace.subscription_type = "development"
        namespace.link_protection = True
        self.assertFalse(namespace.link_protection)
        cleaner = make_cleaner_from_namespace(namespace)
        clean_html = clean_raw_html(raw_html, cleaner)
        self.assertNotIn("<p>[link removed]</p>", clean_html)
        self.assertIn(
            '<a href="https://www.remarkbox.com/" rel="nofollow" target="_blank">', clean_html
        )


# ---------------------------------------------------------------------------
# Unit tests: bleach version contract
#
# These tests guard the requirements.py3.txt pin "bleach>=6.0.0".
# bleach < 3.3.0 had unpatched ReDoS (CVE-2021-23980) in its linkifier.
# bleach < 6.0.0 had API differences that break the LinkifyFilter import path
# used in sanitize_html.py. Pinning >=6.0.0 rules out all pre-fix versions.
# ---------------------------------------------------------------------------

class TestBleachVersionContract(unittest.TestCase):

    def test_bleach_version_gte_6(self):
        """Installed bleach must be >= 6.0.0 to rule out CVE-2021-23980 and
        earlier linkifier API breakage.  If this fails, tighten the pin in
        requirements.py3.txt to bleach>=6.0.0."""
        import bleach
        self.assertGreaterEqual(
            Version(bleach.__version__),
            Version("6.0.0"),
            "bleach must be >= 6.0.0 (CVE-2021-23980 was fixed in 3.3.0; "
            "LinkifyFilter API stabilised in 6.x).",
        )

    def test_linkify_filter_importable(self):
        """bleach.linkifier.LinkifyFilter must be importable.
        sanitize_html.py depends on this symbol; a bleach upgrade that removes
        it would silently break sanitization."""
        from bleach.linkifier import LinkifyFilter  # noqa: F401

    def test_bleach_cleaner_importable(self):
        """bleach.sanitizer.Cleaner must be importable."""
        from bleach.sanitizer import Cleaner  # noqa: F401


# ---------------------------------------------------------------------------
# Unit tests: sanitization correctness with bleach 6.x
#
# These verify that the behaviours relied upon by clean_raw_html still hold
# after a bleach upgrade: XSS stripping, auto-linkification, nofollow.
# ---------------------------------------------------------------------------

class TestSanitizationWithBleach6(unittest.TestCase):

    def _clean(self, html, namespace_name="example.com"):
        from remarkbox.lib.render import clean_raw_html, make_cleaner_from_namespace
        ns = Namespace(namespace_name)
        cleaner = make_cleaner_from_namespace(ns)
        return clean_raw_html(html, cleaner)

    def test_script_tag_stripped(self):
        """<script> tags must be removed — core XSS guard."""
        result = self._clean("<p>hi</p><script>alert(1)</script>")
        self.assertNotIn("<script>", result)
        self.assertIn("hi", result)

    def test_plain_url_autolinkified(self):
        """LinkifyFilter must convert bare URLs into anchor tags."""
        result = self._clean("<p>Visit https://example.com for more.</p>")
        self.assertIn('href="https://example.com"', result)

    def test_external_link_gets_nofollow(self):
        """Links to external domains must get rel=nofollow (spam deterrent)."""
        result = self._clean('<p><a href="https://evil.example/">click</a></p>')
        self.assertIn('rel="nofollow"', result)

    def test_redos_input_completes_fast(self):
        """Adversarial input that triggers O(2^N) backtracking in Python < 3.11
        must complete in under 2 s on Python 3.12+.  This guards against a
        runtime downgrade silently reintroducing the bleach linkifier ReDoS
        (demonstrated externally: N=30→1.0 s, N=35→12.8 s on older runtimes).

        Input: 35 dot-separated tokens with no valid TLD — forces the
        ([\w-]+\.)+ group in the URL regex to try every possible split."""
        from remarkbox.lib.sanitize_html import clean_raw_html, default_cleaner
        payload = ("aaa." * 35) + "zzzzz"  # no valid TLD, forces backtrack attempt
        cleaner = default_cleaner()
        t0 = time.monotonic()
        clean_raw_html(payload, cleaner)
        elapsed = time.monotonic() - t0
        self.assertLess(
            elapsed, 2.0,
            f"bleach sanitization took {elapsed:.2f}s on adversarial input — "
            "possible ReDoS regression (O(2^N) backtracking in URL regex).",
        )

# Keep this module's tests together on one xdist worker. Test modules share a
# per-worker database; when --dist=loadgroup deals unmarked tests out
# individually, classes from different modules interleave on a worker and one
# class's tearDownClass drop_all yanks tables from another class mid-run.
import pytest as _pytest

pytestmark = _pytest.mark.xdist_group("test_render")
