import json
import sys
import unittest
from os.path import abspath, dirname, join

SCRIPTS_DIR = abspath(join(dirname(__file__), "..", "pipeline"))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from build_link_map import build_link_map, resolve_href
from build_storyblok_stories import build_story_payload, convert_pull_quote
from enhance_richtext import enhance_richtext_node
from storyblok_config import load_config
from storyblok_embeds import pull_quote_to_blok_or_richtext

# The data lives per content type now; the shared module knows where.
from paths_root import P  # noqa: E402
DATA_DIR = P.DATA


class PhaseTwoTests(unittest.TestCase):
    def test_link_map_resolves_sequence_number(self):
        link_map = build_link_map(P.CLEANED)
        stories = link_map["stories"]
        sample = next(item for item in stories if item["sequence_number"])
        resolution = resolve_href(
            f"/news/Pages/News_Details.aspx?nid={sample['sequence_number']}",
            {sample["sequence_number"]: {
                "sharepoint_id": sample["sharepoint_id"],
                "sequence_number": sample["sequence_number"],
                "slug": sample["slug"],
                "story_uuid": sample["story_uuid"],
                "story_path": sample["story_path"],
            }},
            by_slug={sample["slug"]: {
                "sharepoint_id": sample["sharepoint_id"],
                "sequence_number": sample["sequence_number"],
                "slug": sample["slug"],
                "story_uuid": sample["story_uuid"],
                "story_path": sample["story_path"],
            }},
        )
        self.assertTrue(resolution["resolved"])
        self.assertEqual(resolution["match_type"], "sequence_number")

    def test_enhance_resolves_story_link(self):
        url_lookup = {
            "/news/pages/news_details.aspx?nid=news-000005": {
                "story_path": "/news/feminine-voice-of-urdu-poetry",
                "story_uuid": "00000000-0000-4000-8000-000000000001",
            }
        }
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "See article",
                            "marks": [
                                {
                                    "type": "link",
                                    "attrs": {
                                        "href": "/news/Pages/News_Details.aspx?nid=NEWS-000005",
                                        "linktype": "url",
                                    },
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        warnings = []
        enhanced = enhance_richtext_node(
            doc,
            url_lookup,
            {},
            "https://www.aku.edu",
            "/news",
            warnings,
        )
        mark = enhanced["content"][0]["content"][0]["marks"][0]
        self.assertEqual(mark["attrs"]["linktype"], "story")
        self.assertIn("story_link_resolved", warnings)

    def test_pull_quote_twitter_becomes_embed(self):
        html = load_fixture_pullquote("99.json")
        blok, mode = pull_quote_to_blok_or_richtext(html, config=load_config())
        self.assertEqual(mode, "twitter_embed")
        self.assertEqual(blok["type"], "blok")

    def test_build_story_payload_shape(self):
        with open(join(P.CLEANED, "35.json"), "r",
                  encoding="utf-8") as f:
            item = json.load(f)
        item["NewsContent"] = {"type": "doc", "content": []}
        story, notes = build_story_payload(item, load_config())
        self.assertEqual(story["slug"], "feminine-voice-of-urdu-poetry")
        self.assertEqual(story["content"]["component"], "news_article")
        self.assertEqual(story["content"]["sharepoint_id"], 35)
        self.assertEqual(story["content"]["category"]["title"], "Event coverage")
        self.assertEqual(story["content"]["author"]["email"], "akber.iqbal@aku.edu")


def load_fixture_pullquote(filename):
    with open(join(P.CLEANED, filename), "r",
              encoding="utf-8") as f:
        return json.load(f)["PullQuote"]


if __name__ == "__main__":
    unittest.main()
