import json
import os
import sys
import tempfile
import unittest
from os.path import abspath, dirname, join

SCRIPTS_DIR = abspath(join(dirname(__file__), "..", "pipeline"))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)
# The steps live in pipeline/{core,content,media,analyze}/ now; _bootstrap puts
# each on sys.path so a test can import a step by its module name as before.
import _bootstrap  # noqa: F401,E402

from richtext_media_utils import (
    apply_story_media_updates,
    attach_richtext_media_to_stories,
    build_catalog,
    build_replacement_map,
    build_richtext_media_blok,
    build_verification_report,
    collect_story_references,
    extract_html_references,
    generate_local_filename,
    is_media_reference,
    replace_richtext_reference,
    source_key,
)


class RichtextMediaUtilsTests(unittest.TestCase):
    def test_is_media_reference_detects_pdf_and_skips_icons(self):
        self.assertTrue(is_media_reference("/news/Documents/report.pdf"))
        self.assertTrue(is_media_reference("https://www.aku.edu/news/PublishingImages/foo.jpg"))
        self.assertFalse(is_media_reference("/_layouts/15/images/icpdf.png"))
        self.assertFalse(is_media_reference("/news-media/123-BannerImage.jpg"))

    def test_is_media_reference_skips_windows_paths(self):
        self.assertFalse(is_media_reference("C:/Users/example/report.pdf"))
        self.assertFalse(is_media_reference("/C:/Users/example/report.pdf"))
        self.assertFalse(is_media_reference("G:\\AKU - WORK\\file.pdf"))

    def test_source_key_normalizes_aku_absolute_urls(self):
        key = source_key(
            "https://www.aku.edu/news/Documents/report.pdf",
            "https://www.aku.edu",
        )
        self.assertEqual(key, "/news/Documents/report.pdf")

    def test_collect_story_references_from_body(self):
        story = {
            "meta_data": {"sharepoint_id": 2294},
            "content": {
                "body": {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Brief.pdf",
                                    "marks": [
                                        {
                                            "type": "link",
                                            "attrs": {
                                                "href": "/news/Documents/Brief.pdf",
                                            },
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            },
        }
        refs = collect_story_references(story, "2294.json")
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["kind"], "link")
        self.assertEqual(refs[0]["ref"], "/news/Documents/Brief.pdf")

    def test_extract_html_references_skips_sharepoint_icon(self):
        html = (
            '<p><a href="/news/Documents/report.pdf">'
            '<img src="/_layouts/15/images/icpdf.png"/>report.pdf</a></p>'
        )
        refs = extract_html_references(html, "2294")
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["kind"], "link")

    def test_replace_richtext_reference_updates_image_and_link(self):
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "image",
                    "attrs": {"src": "/news/PublishingImages/photo.jpg"},
                },
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "file",
                            "marks": [
                                {
                                    "type": "link",
                                    "attrs": {"href": "/news/Documents/file.pdf"},
                                }
                            ],
                        }
                    ],
                },
            ],
        }
        replacements = {
            "/news/PublishingImages/photo.jpg": "/news-media/1-richtext-photo.jpg",
            "/news/Documents/file.pdf": "/news-media/1-richtext-file.pdf",
        }
        updated, changed = replace_richtext_reference(doc, replacements)
        self.assertTrue(changed)
        self.assertEqual(
            updated["content"][0]["attrs"]["src"],
            "/news-media/1-richtext-photo.jpg",
        )
        self.assertEqual(
            updated["content"][1]["content"][0]["marks"][0]["attrs"]["href"],
            "/news-media/1-richtext-file.pdf",
        )

    def test_generate_local_filename_is_stable(self):
        first = generate_local_filename("/news/Documents/report.pdf", ["2294"])
        second = generate_local_filename("/news/Documents/report.pdf", ["2294"])
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("2294-richtext-"))

    def test_build_catalog_marks_missing_assets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stories_dir = join(temp_dir, "stories")
            media_dir = join(temp_dir, "media")
            os.makedirs(stories_dir)
            os.makedirs(media_dir)

            story = {
                "meta_data": {"sharepoint_id": 999},
                "content": {
                    "body": {
                        "type": "doc",
                        "content": [
                            {
                                "type": "image",
                                "attrs": {
                                    "src": "https://www.aku.edu/news/PublishingImages/sample.jpg",
                                },
                            }
                        ],
                    }
                },
            }
            with open(join(stories_dir, "999.json"), "w",
                      encoding="utf-8") as handle:
                json.dump(story, handle)

            catalog = build_catalog(
                stories_dir=stories_dir,
                normalized_dir=None,
                media_dir=media_dir,
                map_path=None,
            )
            self.assertEqual(catalog["summary"]["unique_media_references"], 1)
            self.assertEqual(catalog["summary"]["missing_assets"], 1)

    def test_build_verification_report_splits_downloaded_and_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stories_dir = join(temp_dir, "stories")
            media_dir = join(temp_dir, "media")
            os.makedirs(stories_dir)
            os.makedirs(media_dir)

            story = {
                "meta_data": {"sharepoint_id": 100},
                "content": {
                    "body": {
                        "type": "doc",
                        "content": [
                            {
                                "type": "image",
                                "attrs": {
                                    "src": "https://www.aku.edu/news/PublishingImages/a.jpg",
                                },
                            },
                            {
                                "type": "paragraph",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "doc",
                                        "marks": [
                                            {
                                                "type": "link",
                                                "attrs": {
                                                    "href": "/news/Documents/b.pdf",
                                                },
                                            }
                                        ],
                                    }
                                ],
                            },
                        ],
                    }
                },
            }
            with open(join(stories_dir, "100.json"), "w",
                      encoding="utf-8") as handle:
                json.dump(story, handle)

            map_path = join(temp_dir, "map.json")
            with open(map_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "assets": [
                            {
                                "source_key": "/news/PublishingImages/a.jpg",
                                "local_filename": "100-richtext-a.jpg",
                                "download_status": "downloaded",
                            }
                        ]
                    },
                    handle,
                )
            with open(join(media_dir, "100-richtext-a.jpg"), "w",
                      encoding="utf-8") as handle:
                handle.write("fake")

            report = build_verification_report(
                stories_dir=stories_dir,
                normalized_dir=None,
                media_dir=media_dir,
                map_path=map_path,
            )
            self.assertEqual(report["summary"]["downloaded_assets"], 1)
            self.assertEqual(report["summary"]["missing_assets"], 1)
            self.assertFalse(report["summary"]["validation_passed"])
            self.assertEqual(report["downloaded_assets"][0]["local_filename"], "100-richtext-a.jpg")

    def test_build_replacement_map_includes_all_reference_variants(self):
        asset = {
            "local_src": "/news-media/local.pdf",
            "source_ref": "https://www.aku.edu/Documents/local.pdf",
            "absolute_url": "https://www.aku.edu/Documents/local.pdf",
            "source_key": "/Documents/local.pdf",
            "references": [{"ref": "/Documents/local.pdf"}],
        }
        replacements = build_replacement_map(asset)
        self.assertEqual(replacements["/Documents/local.pdf"], "/news-media/local.pdf")
        self.assertEqual(
            replacements["https://www.aku.edu/Documents/local.pdf"],
            "/news-media/local.pdf",
        )

    def test_attach_adds_news_media_bloks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            stories_dir = join(temp_dir, "stories")
            os.makedirs(stories_dir)

            story = {
                "meta_data": {"sharepoint_id": 100},
                "content": {
                    "title": "Example",
                    "media": [
                        {
                            "_uid": "banner",
                            "component": "news_media",
                            "role": "banner",
                            "filename": "100-BannerImage.jpg",
                            "src": "/news-media/100-BannerImage.jpg",
                            "media_type": "image",
                        }
                    ],
                    "body": {
                        "type": "doc",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "Download",
                                        "marks": [
                                            {
                                                "type": "link",
                                                "attrs": {"href": "/Documents/local.pdf"},
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    },
                },
            }
            with open(join(stories_dir, "100.json"), "w",
                      encoding="utf-8") as handle:
                json.dump(story, handle)

            assets = [
                {
                    "source_key": "/Documents/local.pdf",
                    "source_ref": "/Documents/local.pdf",
                    "absolute_url": "https://www.aku.edu/Documents/local.pdf",
                    "local_filename": "100-richtext-local.pdf",
                    "local_src": "/news-media/100-richtext-local.pdf",
                    "media_type": "other",
                    "basename": "local.pdf",
                    "story_ids": ["100"],
                    "references": [
                        {
                            "story_id": "100",
                            "field": "body",
                            "kind": "link",
                            "ref": "/Documents/local.pdf",
                        }
                    ],
                }
            ]

            summary = attach_richtext_media_to_stories(
                stories_dir,
                assets,
                "https://www.aku.edu",
                add_media_bloks=True,
            )
            self.assertEqual(summary["stories_updated"], 1)
            self.assertEqual(summary["media_bloks_added"], 1)

            with open(join(stories_dir, "100.json"),
                      encoding="utf-8") as handle:
                updated = json.load(handle)

            media = updated["content"]["media"]
            self.assertEqual(len(media), 2)
            self.assertEqual(media[1]["role"], "richtext")
            self.assertEqual(
                updated["content"]["body"]["content"][0]["content"][0]["marks"][0]["attrs"]["href"],
                "/news-media/100-richtext-local.pdf",
            )


if __name__ == "__main__":
    unittest.main()
