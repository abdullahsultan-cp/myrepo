#!/usr/bin/env python3
"""The two things the owner had to fix by hand on the first demo upload.

Both were caught by a person looking at three published stories, not by any
check here — so they are pinned down now.
"""

import importlib.util
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))


def load():
    path = os.path.join(ROOT, "Blogs-Pipeline", "pipeline", "build_payload.py")
    spec = importlib.util.spec_from_file_location("blogs_build_payload", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class BlankParagraphs(unittest.TestCase):
    """Blog 70 shipped with 20 paragraphs of pure whitespace in it."""

    def setUp(self):
        self.m = load()

    def para(self, *kids):
        return {"type": "paragraph", "content": list(kids)}

    def test_a_paragraph_of_only_line_breaks_goes(self):
        doc = {"type": "doc", "content": [
            self.para(*[{"type": "hard_break"}] * 17),
            self.para({"type": "text", "text": "Real words."}),
        ]}
        out = self.m.strip_blank_paragraphs(doc)
        self.assertEqual(len(out["content"]), 1)
        self.assertEqual(out["content"][0]["content"][0]["text"], "Real words.")

    def test_a_paragraph_of_whitespace_text_goes(self):
        doc = {"type": "doc", "content": [
            self.para({"type": "text", "text": "   "}),
            self.para({"type": "text", "text": "Kept."}),
        ]}
        self.assertEqual(len(self.m.strip_blank_paragraphs(doc)["content"]), 1)

    def test_a_paragraph_holding_only_an_image_STAYS(self):
        """The one that would silently delete a picture.

        Images live inside the rich text for blogs, so a paragraph whose only
        child is an image has no text and is not blank.
        """
        doc = {"type": "doc", "content": [
            self.para({"type": "image", "attrs": {"src": "/x.jpg"}}),
        ]}
        out = self.m.strip_blank_paragraphs(doc)
        self.assertEqual(len(out["content"]), 1)

    def test_headings_and_lists_are_never_touched(self):
        doc = {"type": "doc", "content": [
            {"type": "heading", "attrs": {"level": 1}, "content": [
                {"type": "text", "text": "A Brief History"}]},
            {"type": "bullet_list", "content": []},
            {"type": "horizontal_rule"},
        ]}
        self.assertEqual(len(self.m.strip_blank_paragraphs(doc)["content"]), 3)

    def test_it_does_not_mutate_its_input(self):
        doc = {"type": "doc", "content": [self.para()]}
        self.m.strip_blank_paragraphs(doc)
        self.assertEqual(len(doc["content"]), 1, "the source doc must survive")


class Pills(unittest.TestCase):
    """Pills went up with a variant and no colour, and rendered uncoloured."""

    def setUp(self):
        self.m = load()

    def test_every_pill_carries_both_colours(self):
        row = self.m.pill_row(["Education", "Simulation"],
                              {"Education": "green", "Simulation": "terracotta"})
        self.assertEqual(len(row["items"]), 2)
        for item in row["items"]:
            pill = item["body"][0]
            self.assertEqual(pill["component"], "pill")
            self.assertTrue(pill["custom_bg_color"]["color"].startswith("#"))
            self.assertEqual(pill["custom_text_color"]["color"], "#000000")

    def test_adjacent_pills_do_not_share_a_background(self):
        row = self.m.pill_row(["a", "b"], {})
        self.assertNotEqual(row["items"][0]["body"][0]["custom_bg_color"]["color"],
                            row["items"][1]["body"][0]["custom_bg_color"]["color"])

    def test_only_colours_aku_chose_are_used(self):
        """No invented hexes: both come from the demo and the owner's fix."""
        self.assertEqual(self.m.PILL_COLOURS, ["#06923E96", "#B2CEFF"])

    def test_a_tag_keeps_its_variant_across_blogs(self):
        palette = self.m.pill_palette(["Education"] * 3 + ["Students"] * 2)
        self.assertNotEqual(palette["Education"], palette["Students"])
        again = self.m.pill_palette(["Education"] * 3 + ["Students"] * 2)
        self.assertEqual(palette, again, "the palette must be reproducible")


if __name__ == "__main__":
    unittest.main()
