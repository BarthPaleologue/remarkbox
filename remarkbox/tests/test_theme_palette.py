"""Tests for machine-learning-chosen theme palettes.

The contract these pin down: the model picks numbers, never CSS; every answer
is validated before it reaches a stylesheet; contrast is enforced by us; and
anything going wrong falls back to a deterministic palette rather than leaving
a community unstyled.
"""

import unittest

from unittest.mock import patch

from remarkbox.lib.theme_generator import generate_theme_css, hash_palette
from remarkbox.lib.theme_palette import (
    MIN_CONTRAST,
    choose_palette,
    contrast_ratio,
    enforce_contrast,
    _validate,
)

ENABLED = {
    "theme.llm.enabled": "true",
    "spam.llm.endpoint": "https://hermes.example.com/v1/chat/completions",
    "spam.llm.model": "test-model",
    "spam.llm.timeout": "5",
}


class ContrastTests(unittest.TestCase):
    def test_black_on_white_is_maximum(self):
        self.assertAlmostEqual(contrast_ratio((0, 0, 0), (0, 0, 100)), 21.0, places=1)

    def test_identical_colours_have_no_contrast(self):
        self.assertAlmostEqual(contrast_ratio((200, 50, 50), (200, 50, 50)), 1.0, places=2)

    def test_enforcement_reduces_saturation_until_readable(self):
        palette = enforce_contrast(
            {"hue": 55, "secondary_hue": 90, "accent_hue": 235, "sat_base": 100}
        )
        self.assertLessEqual(palette["sat_base"], 100)
        self.assertGreaterEqual(palette["contrast_light"], MIN_CONTRAST)
        self.assertGreaterEqual(palette["contrast_dark"], MIN_CONTRAST)

    def test_every_hue_ends_up_readable(self):
        """A community must never get an unreadable theme, whatever hue it lands on."""
        for hue in range(0, 360, 15):
            p = enforce_contrast(
                {"hue": hue, "secondary_hue": hue, "accent_hue": hue, "sat_base": 75}
            )
            self.assertGreaterEqual(
                p["contrast_light"], MIN_CONTRAST, "hue {} light".format(hue)
            )
            self.assertGreaterEqual(
                p["contrast_dark"], MIN_CONTRAST, "hue {} dark".format(hue)
            )


class ValidationTests(unittest.TestCase):
    def test_accepts_a_well_formed_answer(self):
        p = _validate(
            {"hue": 25, "secondary_hue": 45, "accent_hue": 210,
             "saturation": 55, "rationale": "warm and earthy"},
            "cooking.example.com",
        )
        self.assertEqual(p["hue"], 25)
        self.assertEqual(p["source"], "hermes")
        self.assertEqual(p["rationale"], "warm and earthy")

    def test_rejects_prose_instead_of_numbers(self):
        self.assertIsNone(_validate({"hue": "warm orange"}, "x"))

    def test_rejects_out_of_range_values(self):
        self.assertIsNone(
            _validate({"hue": 4000, "secondary_hue": 10, "accent_hue": 20,
                       "saturation": 50}, "x")
        )
        self.assertIsNone(
            _validate({"hue": 10, "secondary_hue": 10, "accent_hue": 20,
                       "saturation": -1}, "x")
        )

    def test_rejects_missing_keys(self):
        self.assertIsNone(_validate({"hue": 10}, "x"))

    def test_rejects_a_non_object(self):
        self.assertIsNone(_validate(["not", "a", "dict"], "x"))

    def test_clamps_saturation_into_a_renderable_band(self):
        p = _validate({"hue": 10, "secondary_hue": 20, "accent_hue": 30,
                       "saturation": 100}, "x")
        self.assertLessEqual(p["sat_base"], 75)


class ChoosePaletteTests(unittest.TestCase):
    def test_disabled_falls_back_to_hash(self):
        p = choose_palette("x.example.com", settings={})
        self.assertEqual(p["source"], "hash")

    @patch("remarkbox.lib.theme_palette._llm_request")
    def test_uses_the_model_answer_when_valid(self, mock_llm):
        mock_llm.return_value = (
            '{"hue": 25, "secondary_hue": 45, "accent_hue": 210, '
            '"saturation": 55, "rationale": "warm"}'
        )
        p = choose_palette("cooking.example.com", "a forum about bread", ENABLED)
        self.assertEqual(p["source"], "hermes")
        self.assertEqual(p["hue"], 25)

    @patch("remarkbox.lib.theme_palette._llm_request")
    def test_tolerates_a_fenced_or_chatty_answer(self, mock_llm):
        """Models wrap JSON in prose; that must not cost a community its theme."""
        mock_llm.return_value = (
            'Sure! Here is a palette:\n```json\n'
            '{"hue": 200, "secondary_hue": 220, "accent_hue": 30, "saturation": 40}\n'
            '```\nHope that helps.'
        )
        p = choose_palette("ocean.example.com", None, ENABLED)
        self.assertEqual(p["source"], "hermes")
        self.assertEqual(p["hue"], 200)

    @patch("remarkbox.lib.theme_palette._llm_request")
    def test_unreachable_model_falls_back(self, mock_llm):
        mock_llm.return_value = None
        p = choose_palette("x.example.com", None, ENABLED)
        self.assertEqual(p["source"], "hash")

    @patch("remarkbox.lib.theme_palette._llm_request")
    def test_garbage_answer_falls_back(self, mock_llm):
        mock_llm.return_value = "I'm sorry, I can't help with that."
        p = choose_palette("x.example.com", None, ENABLED)
        self.assertEqual(p["source"], "hash")

    @patch("remarkbox.lib.theme_palette._llm_request")
    def test_model_output_never_reaches_css_verbatim(self, mock_llm):
        """The model returns numbers, so injection has nothing to ride in on."""
        mock_llm.return_value = (
            '{"hue": 25, "secondary_hue": 45, "accent_hue": 210, "saturation": 55, '
            '"rationale": "}<script>alert(1)</script>{ background: url(//evil) "}'
        )
        p = choose_palette("x.example.com", None, ENABLED)
        css = generate_theme_css("x.example.com", p)
        self.assertNotIn("<script>", css)
        self.assertNotIn("evil", css)
        self.assertNotIn("rationale", css)


class GeneratorPaletteTests(unittest.TestCase):
    def test_default_matches_the_hash_palette(self):
        """Existing callers keep their exact themes."""
        self.assertEqual(
            generate_theme_css("meta.remarkbox.com"),
            generate_theme_css("meta.remarkbox.com", hash_palette("meta.remarkbox.com")),
        )

    def test_a_different_palette_produces_different_css(self):
        a = generate_theme_css("x", {"hue": 10, "secondary_hue": 30,
                                     "accent_hue": 200, "sat_base": 50})
        b = generate_theme_css("x", {"hue": 300, "secondary_hue": 330,
                                     "accent_hue": 120, "sat_base": 50})
        self.assertNotEqual(a, b)

    def test_renders_even_from_an_absurd_palette(self):
        """Belt and braces: this function must never emit broken CSS."""
        css = generate_theme_css("x", {"hue": 99999, "sat_base": 500})
        self.assertIn("--rb-bg:", css)
        self.assertNotIn("99999", css)


import pytest as _pytest

pytestmark = _pytest.mark.xdist_group("test_theme_palette")
