#!/usr/bin/env python3
"""Every entity and marker found in the real exports, plus a shipping guard.

The entity list is not invented — it is every distinct form counted across the
blogs and news exports:

    &#58;   13,042    a colon, usually inside a URL
    &#160;  14,698    non-breaking space
    &quot;   8,190
    &amp;      864
    &#123;     137    an opening brace
    &#125;     137    a closing brace
    &mdash;      68
    &gt; &lt; &#39;

`&#123;` matters more than it looks: it decodes to `{`, so decoding has to
happen BEFORE markers are matched or `&#123;pullquote&#125;` survives as
visible text. That ordering is tested here.
"""

import glob
import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import _bootstrap

_bootstrap.ensure()

from text_clean import clean_richtext, clean_text, looks_encoded, strip_html

ENTITY = re.compile(r"&[a-zA-Z][a-zA-Z0-9]{1,10};|&#x?[0-9a-fA-F]{1,6};")
MARKER = re.compile(r"\{(?:pullquote|EmbeddedCode|embeddedcode|PullQuote)\}")


class Entities(unittest.TestCase):

    def test_every_entity_seen_in_the_exports(self):
        cases = {
            "Dr&#160;Asad I Mian": "Dr Asad I Mian",
            "Media Contact&#58; Victoria": "Media Contact: Victoria",
            "Economics &amp; Political Science": "Economics & Political Science",
            "he said &quot;hello&quot;": 'he said "hello"',
            "one &mdash; two": "one — two",
            "a &lt;b&gt; c": "a <b> c",
            "it&#39;s": "it's",
        }
        for raw, want in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(clean_text(raw), want)

    def test_every_real_form_decodes_completely(self):
        out = clean_text("&#58;&#160;&quot;&amp;&#123;&#125;&mdash;")
        self.assertEqual(looks_encoded(out), [], f"{out!r} still has an entity")

    def test_double_encoded_is_REPORTED_not_silently_decoded(self):
        """Decoding happens once, on purpose.

        `&amp;#160;` decodes to `&#160;`, which is still visible. Looping until
        stable would fix that — and would also destroy a sentence that
        legitimately shows markup, where `&amp;amp;` is meant to render as
        `&amp;`. Neither export contains one (counted, not assumed), so the
        loop would fix nothing real and risk something real. It is surfaced
        instead, and the payload guard below fails on it.
        """
        self.assertEqual(clean_text("&amp;#160;"), "&#160;")
        self.assertEqual(looks_encoded(clean_text("&amp;#160;")), ["&#160;"])

    def test_looks_encoded_is_quiet_on_clean_text(self):
        self.assertEqual(looks_encoded("Dr Asad I Mian, Karachi — 37°C"), [])

    def test_accents_and_scripts_survive(self):
        """711 non-ASCII characters are real content, not damage."""
        for raw in ("Zulfiqar Bhutta", "café", "Müller", "£40", "37°C",
                    "الجامعة", "یونیورسٹی"):
            self.assertEqual(clean_text(raw), raw)

    def test_invisibles_go_but_only_those_three(self):
        self.assertEqual(clean_text("a​b﻿c­d"), "abcd")
        self.assertEqual(clean_text("a b"), "a b", "nbsp becomes a space")


class Markers(unittest.TestCase):

    def test_markers_are_removed(self):
        self.assertEqual(clean_text("Text {pullquote} more"), "Text more")
        self.assertEqual(clean_text("{EmbeddedCode}"), "")

    def test_an_encoded_marker_is_still_a_marker(self):
        """The ordering trap: decode first, then match.

        `&#123;` is `{`. Match markers before decoding and this survives all
        the way to the page.
        """
        self.assertEqual(clean_text("a &#123;pullquote&#125; b"), "a b")

    def test_other_braces_are_left_alone(self):
        """Only the known markers go. Braces occur in CSS and in prose."""
        for raw in ("{font-family:Calibri}", "a {b} c", "{1}"):
            self.assertIn("{", clean_text(raw), raw)


class RichText(unittest.TestCase):

    def test_a_node_emptied_by_cleaning_is_dropped(self):
        doc = {"type": "doc", "content": [
            {"type": "paragraph", "content": [
                {"type": "text", "text": "{pullquote}"}]},
            {"type": "paragraph", "content": [
                {"type": "text", "text": "Real."}]}]}
        out = clean_richtext(doc)
        self.assertEqual(len(out["content"]), 1)
        self.assertEqual(out["content"][0]["content"][0]["text"], "Real.")

    def test_line_breaks_inside_rich_text_are_not_collapsed(self):
        doc = {"type": "doc", "content": [
            {"type": "paragraph", "content": [
                {"type": "text", "text": "one\ntwo"}]}]}
        self.assertEqual(
            clean_richtext(doc)["content"][0]["content"][0]["text"], "one\ntwo")

    def test_it_does_not_mutate_its_input(self):
        doc = {"type": "doc", "content": [
            {"type": "paragraph", "content": [
                {"type": "text", "text": "Dr&#160;X"}]}]}
        clean_richtext(doc)
        self.assertEqual(doc["content"][0]["content"][0]["text"], "Dr&#160;X")


class NothingShipsDirty(unittest.TestCase):
    """The guard. Built payloads must carry no entity and no marker.

    This is the check that did not exist when 88 `&#160;` reached published
    author biographies and `{pullquote}` reached published prose.
    """

    def payloads(self):
        return sorted(glob.glob(os.path.join(
            ROOT, "*-Pipeline", "data", "payloads", "*.json")))

    def test_no_payload_carries_an_entity_or_a_marker(self):
        files = self.payloads()
        if not files:
            self.skipTest("no payloads built")
        for path in files:
            with open(path, encoding="utf-8") as f:
                blob = json.dumps(json.load(f), ensure_ascii=False)
            name = os.path.relpath(path, ROOT)
            with self.subTest(payload=name):
                found = ENTITY.findall(blob)
                self.assertEqual(found[:5], [], f"{name} has entities")
                self.assertEqual(MARKER.findall(blob)[:5], [],
                                 f"{name} has position markers")


if __name__ == "__main__":
    unittest.main()
