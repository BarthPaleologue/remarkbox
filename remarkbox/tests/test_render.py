import unittest

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
