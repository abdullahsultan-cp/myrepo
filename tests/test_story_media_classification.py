import sys
import unittest
from os.path import abspath, dirname, join

SCRIPTS_DIR = abspath(join(dirname(__file__), "..", "pipeline"))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from story_media_classification import classify_story_media, filter_stories


class StoryMediaClassificationTests(unittest.TestCase):
    def test_classify_thumbnail_gif_video(self):
        story = {
            "slug": "example",
            "name": "Example",
            "meta_data": {"sharepoint_id": 3876},
            "content": {
                "title": "Digital Learning",
                "media": [
                    {
                        "role": "thumbnail",
                        "media_type": "image",
                        "filename": "3876-ThumbnailImage.jpg",
                    },
                    {
                        "role": "banner",
                        "media_type": "gif",
                        "filename": "100-BannerImage.gif",
                    },
                    {
                        "role": "video1",
                        "media_type": "video",
                        "filename": "100-Video1.mp4",
                    },
                ],
                "body": {
                    "type": "doc",
                    "content": [
                        {
                            "type": "blok",
                            "attrs": {
                                "body": [
                                    {
                                        "component": "video_embed",
                                        "provider": "youtube",
                                    }
                                ]
                            },
                        }
                    ],
                },
            },
        }
        entry = classify_story_media(story, "3876.json")
        self.assertTrue(entry["flags"]["thumbnail"])
        self.assertTrue(entry["flags"]["gif"])
        self.assertTrue(entry["flags"]["video_file"])
        self.assertTrue(entry["flags"]["video_embed"])

    def test_filter_stories_requires_all_selected_filters(self):
        report = {
            "stories": [
                {"story_id": "1", "title": "A", "filters": ["gif", "video_embed"]},
                {"story_id": "2", "title": "B", "filters": ["gif"]},
            ]
        }
        matched = filter_stories(report, ["gif", "video_embed"])
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["story_id"], "1")


if __name__ == "__main__":
    unittest.main()
