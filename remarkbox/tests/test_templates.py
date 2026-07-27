"""
Template validation tests.

These tests ensure all Jinja2 templates have valid syntax and can be compiled.
This catches errors like mismatched {% if %}/{% endif %} blocks before deployment.
"""
import os
import unittest
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, TemplateSyntaxError


class TestTemplateValidation(unittest.TestCase):
    """Test that all Jinja2 templates have valid syntax."""

    @classmethod
    def setUpClass(cls):
        """Set up Jinja2 environment for template testing."""
        # Find templates directory
        tests_dir = Path(__file__).parent
        templates_dir = tests_dir.parent / "templates"
        cls.templates_dir = templates_dir

        # Create Jinja2 environment matching the app configuration
        cls.env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            # Don't fail on undefined variables during syntax check
            autoescape=True,
        )

    def test_all_templates_have_valid_syntax(self):
        """
        Verify all .j2 templates can be parsed without syntax errors.

        This catches issues like:
        - Mismatched {% if %}/{% endif %} blocks
        - Unclosed {% block %} tags
        - Invalid Jinja2 syntax
        """
        errors = []

        # Walk through all templates
        for root, dirs, files in os.walk(self.templates_dir):
            for filename in files:
                if filename.endswith(".j2"):
                    # Get relative path for Jinja2 loader
                    full_path = Path(root) / filename
                    rel_path = full_path.relative_to(self.templates_dir)
                    template_name = str(rel_path)

                    try:
                        # Attempt to parse the template
                        self.env.get_template(template_name)
                    except TemplateSyntaxError as e:
                        errors.append(
                            f"{template_name}:{e.lineno}: {e.message}"
                        )

        if errors:
            self.fail(
                f"Template syntax errors found:\n" + "\n".join(errors)
            )

    def test_base_template_exists(self):
        """Verify the base template exists and is valid."""
        try:
            template = self.env.get_template("base.j2")
            self.assertIsNotNone(template)
        except TemplateSyntaxError as e:
            self.fail(f"base.j2 has syntax error at line {e.lineno}: {e.message}")

    def test_home_template_exists(self):
        """Verify home.j2 template exists and is valid."""
        try:
            template = self.env.get_template("home.j2")
            self.assertIsNotNone(template)
        except TemplateSyntaxError as e:
            self.fail(f"home.j2 has syntax error at line {e.lineno}: {e.message}")

    def test_show_node_template_exists(self):
        """Verify show-node.j2 template exists and is valid."""
        try:
            template = self.env.get_template("show-node.j2")
            self.assertIsNotNone(template)
        except TemplateSyntaxError as e:
            self.fail(f"show-node.j2 has syntax error at line {e.lineno}: {e.message}")


class TestCapabilityDrivenPresentation(unittest.TestCase):
    """Test capability-driven presentation patterns (js-only / noscript)."""

    @classmethod
    def setUpClass(cls):
        tests_dir = Path(__file__).parent
        cls.templates_dir = tests_dir.parent / "templates"
        cls.static_dir = tests_dir.parent / "static"

    def test_base_template_has_noscript_js_only_pattern(self):
        """Verify base.j2 contains the noscript/js-only hide pattern."""
        base_content = (self.templates_dir / "base.j2").read_text()
        self.assertIn("<noscript>", base_content)
        self.assertIn(".js-only", base_content)
        self.assertIn("display: none", base_content)

    def test_reply_form_preview_uses_js_only_class(self):
        """Verify preview elements in reply form have js-only class."""
        forms_content = (self.templates_dir / "snippets" / "forms.j2").read_text()
        self.assertIn('class="preview-details js-only"', forms_content)
        self.assertIn("class='preview js-only'", forms_content)

    def test_reply_form_works_as_plain_html(self):
        """Verify reply form has method=post and action — works without JS."""
        forms_content = (self.templates_dir / "snippets" / "forms.j2").read_text()
        self.assertIn('method="post"', forms_content)
        self.assertIn('/reply"', forms_content)
        self.assertIn("thread_data", forms_content)

    def test_custom_js_has_ajax_comment_init(self):
        """Verify custom.js contains AJAX comment form initialization."""
        js_content = (self.static_dir / "js" / "custom.js").read_text()
        self.assertIn("initAjaxCommentForms", js_content)
        self.assertIn("X-Requested-With", js_content)
        self.assertIn("XMLHttpRequest", js_content)

    def test_custom_js_has_graceful_fallback(self):
        """Verify AJAX submission falls back to form.submit() on error."""
        js_content = (self.static_dir / "js" / "custom.js").read_text()
        self.assertIn("form.submit()", js_content)

    def test_create_form_works_as_plain_html(self):
        """Verify create thread form has method=post — works without JS."""
        create_content = (self.templates_dir / "snippets" / "create.j2").read_text()
        self.assertIn('method="post"', create_content)
        self.assertIn("thread_title", create_content)
        self.assertIn("thread_data", create_content)


if __name__ == "__main__":
    unittest.main()

# Keep this module's tests together on one xdist worker. Test modules share a
# per-worker database; when --dist=loadgroup deals unmarked tests out
# individually, classes from different modules interleave on a worker and one
# class's tearDownClass drop_all yanks tables from another class mid-run.
import pytest as _pytest

pytestmark = _pytest.mark.xdist_group("test_templates")
