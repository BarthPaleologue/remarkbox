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


if __name__ == "__main__":
    unittest.main()
