import json
import sys
import unittest
from os.path import abspath, dirname, join

SCRIPTS_DIR = abspath(join(dirname(__file__), "..", "pipeline"))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from convert_news_richtext import convert_news_item
from normalize_news_html import normalize_news_content_html
from storyblok_richtext import html_to_storyblok_richtext, validate_document

# The data lives per content type now; the shared module knows where.
from paths_root import P  # noqa: E402
DATA_DIR = P.DATA


def load_fixture(name):
    with open(join(P.CLEANED, name), "r",
              encoding="utf-8") as f:
        return json.load(f)


class StoryblokRichtextTests(unittest.TestCase):
    def test_paragraph_with_marks(self):
        html = "<p>The <strong>Aga Khan University</strong> offers <em>education</em>.</p>"
        result = html_to_storyblok_richtext(html)
        self.assertEqual(result.document["type"], "doc")
        paragraph = result.document["content"][0]
        self.assertEqual(paragraph["type"], "paragraph")
        bold = next(
            node for node in paragraph["content"] if node.get("marks") and node["marks"][0]["type"] == "bold"
        )
        self.assertEqual(bold["text"], "Aga Khan University")

    def test_heading_and_list(self):
        html = """
        <h2>About AKU</h2>
        <ul>
            <li>Medicine</li>
            <li>Nursing</li>
        </ul>
        """
        result = html_to_storyblok_richtext(html)
        self.assertEqual(result.document["content"][0]["type"], "heading")
        self.assertEqual(result.document["content"][0]["attrs"]["level"], 2)
        bullet_list = next(
            node for node in result.document["content"] if node["type"] == "bullet_list"
        )
        self.assertEqual(len(bullet_list["content"]), 2)

    def test_link_mark(self):
        html = '<p>Visit <a href="https://aku.edu" target="_blank">AKU</a> today.</p>'
        result = html_to_storyblok_richtext(html)
        paragraph = result.document["content"][0]
        link_node = next(node for node in paragraph["content"] if node.get("marks"))
        link_mark = link_node["marks"][0]
        self.assertEqual(link_mark["type"], "link")
        self.assertEqual(link_mark["attrs"]["href"], "https://aku.edu")
        self.assertEqual(link_mark["attrs"]["linktype"], "url")
        self.assertFalse(any(w.startswith("relative_link:") for w in result.warnings))

    def test_relative_link_warning(self):
        html = '<p><a href="/news/Pages/example.aspx">Internal</a></p>'
        result = html_to_storyblok_richtext(html)
        self.assertTrue(any(w.startswith("relative_link:") for w in result.warnings))

    def test_iframe_embed_blok(self):
        html = '<div data-storyblok-embed="youtube" data-src="https://www.youtube.com/embed/test"></div>'
        result = html_to_storyblok_richtext(html)
        self.assertEqual(result.document["content"][0]["type"], "blok")
        self.assertTrue(any(w.startswith("iframe_embedded:") for w in result.warnings))

    def test_wrapped_iframe_normalizes_to_embed_blok(self):
        html = (
            '<div class="embed-responsive embed-responsive-4by3 videoWP-border">'
            '<iframe class="embed-responsive-item" src="https&#58;//www.youtube.com/embed/6tpY9IQJ0-Y" '
            'frameborder="0"></iframe><br></div>'
        )
        normalized, stats, warnings = normalize_news_content_html(html)
        self.assertIn("data-storyblok-embed", normalized)
        self.assertNotIn("<iframe", normalized.lower())
        self.assertEqual(stats["iframes_replaced"], 1)
        result = html_to_storyblok_richtext(normalized)
        self.assertEqual(result.document["content"][0]["type"], "blok")
        self.assertEqual(
            result.document["content"][0]["attrs"]["body"][0]["component"],
            "video_embed",
        )

    def test_embed_inside_paragraph_becomes_blok(self):
        html = (
            '<p>Watch this video</p>'
            '<p>Intro<div data-storyblok-embed="youtube" '
            'data-src="https://www.youtube.com/embed/test"></div></p>'
        )
        result = html_to_storyblok_richtext(html)
        types = [node["type"] for node in result.document["content"]]
        self.assertEqual(types, ["paragraph", "paragraph", "blok"])

    def test_image_node(self):
        html = '<p><img src="/news/PublishingImages/test.jpg" alt="Photo"></p>'
        result = html_to_storyblok_richtext(html)
        image = result.document["content"][0]
        self.assertEqual(image["type"], "image")
        self.assertEqual(image["attrs"]["alt"], "Photo")
        self.assertTrue(any(w.startswith("sharepoint_image:") for w in result.warnings))

    def test_validate_document(self):
        html = "<p>Valid content</p>"
        document = html_to_storyblok_richtext(html).document
        self.assertEqual(validate_document(document), [])


class NormalizeHtmlTests(unittest.TestCase):
    def test_external_class_unwrapped_and_divs_converted(self):
        html = (
            '<div class="ExternalClassABC"><div>First paragraph.</div>'
            '<div><br></div><div>Second paragraph.</div></div>'
        )
        normalized, stats, warnings = normalize_news_content_html(html)
        self.assertNotIn("ExternalClass", normalized)
        self.assertNotIn("<div", normalized.lower())
        self.assertIn("<p>First paragraph.</p>", normalized)
        self.assertIn("<p>Second paragraph.</p>", normalized)
        self.assertGreater(stats["divs_converted_to_p"], 0)

    def test_iframe_replaced_with_embed_placeholder(self):
        html = '<p>Video</p><iframe src="https://www.youtube.com/embed/test"></iframe>'
        normalized, stats, warnings = normalize_news_content_html(html)
        self.assertNotIn("<iframe", normalized)
        self.assertIn("data-storyblok-embed", normalized)
        self.assertEqual(stats["iframes_replaced"], 1)

    def test_wrapped_iframe_survives_normalization(self):
        html = (
            '<div class="embed-responsive embed-responsive-4by3 videoWP-border">'
            '<iframe src="https://www.youtube.com/embed/test"></iframe><br></div>'
        )
        normalized, stats, warnings = normalize_news_content_html(html)
        self.assertIn("data-storyblok-embed", normalized)
        self.assertNotIn("<iframe", normalized.lower())
        self.assertEqual(stats["iframes_replaced"], 1)
        self.assertGreaterEqual(stats.get("embed_wrappers_hoisted", 0), 1)

    def test_fixture_35_normalizes_without_sharepoint_artifacts(self):
        news_item = load_fixture("35.json")
        normalized, stats, warnings = normalize_news_content_html(news_item["NewsContent"])
        self.assertNotIn("ExternalClass", normalized)
        self.assertNotIn("<div", normalized.lower())

    def test_fixture_100_normalizes(self):
        news_item = load_fixture("100.json")
        normalized, stats, warnings = normalize_news_content_html(news_item["NewsContent"])
        self.assertNotIn("ExternalClass", normalized)


class EndToEndFixtureTests(unittest.TestCase):
    def convert_fixture(self, filename):
        news_item = load_fixture(filename)
        normalized_html, _, _ = normalize_news_content_html(news_item["NewsContent"])
        news_item["NewsContent"] = normalized_html
        converted, warnings, errors = convert_news_item(news_item)
        return converted, warnings, errors

    def test_fixture_35_converts_to_valid_doc(self):
        converted, warnings, errors = self.convert_fixture("35.json")
        self.assertIsNone(converted.get("NewsContentRichtextError"))
        self.assertEqual(converted["NewsContent"]["type"], "doc")
        self.assertGreater(len(converted["NewsContent"]["content"]), 0)
        self.assertEqual(errors, [])

    def test_fixture_100_converts_to_valid_doc(self):
        converted, warnings, errors = self.convert_fixture("100.json")
        self.assertIsNone(converted.get("NewsContentRichtextError"))
        self.assertEqual(converted["NewsContent"]["type"], "doc")
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
