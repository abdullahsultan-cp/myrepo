#!/usr/bin/env python3
"""Where a SharePoint link should point once the site is gone.

Every case here is a real href taken from the link table or from a blog body,
not an invented one.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import _bootstrap

_bootstrap.ensure()

from link_routing import classify, is_ours, rewrite_href


class Classify(unittest.TestCase):

    def test_news_page_gives_its_slug(self):
        self.assertEqual(
            classify("/news/aku-pledges-commitment-to-every-woman-every-child"),
            ("story", "aku-pledges-commitment-to-every-woman-every-child"))

    def test_blog_page_gives_its_id_despite_being_aspx(self):
        """The trap: every blog link is an .aspx URL."""
        self.assertEqual(
            classify("https://www.aku.edu/blogs/pages/detail-page.aspx?pid=42"),
            ("story", 42))
        self.assertEqual(
            classify("/blogs/Pages/Detail.aspx?PostID=16"), ("story", 16))

    def test_documents(self):
        for href in ("/qtl/Documents/Transforming%20Teaching%20A5-1.pdf",
                     "/admissions/Documents/policy-use-of-generative-ai.pdf"):
            kind, name = classify(href)
            self.assertEqual(kind, "document")
            self.assertTrue(name.endswith(".pdf"))
            self.assertNotIn("%20", name, "the filename must be decoded")

    def test_site_pages_are_left_for_the_pages_migration(self):
        for href in ("/coe-wch/about/Pages/east-africa.aspx",
                     "/mcpk/faculty/Pages/profile.aspx?ProfileID=153",
                     "https://www.aku.edu/admissions/registraroffice/Pages/x.aspx"):
            self.assertEqual(classify(href)[0], "site page", href)

    def test_other_sites_are_never_touched(self):
        for href in ("http://hec.gov.pk/english/universities/Documents/R.pdf",
                     "https://twitter.com/i/status/1", "mailto:x@aku.edu",
                     "#section", ""):
            self.assertEqual(classify(href)[0], "external", href)

    def test_is_ours(self):
        self.assertTrue(is_ours("/qtl/pages/home.aspx"))
        self.assertTrue(is_ours("https://www.aku.edu/news/x"))
        self.assertFalse(is_ours("https://example.com/aku.edu/x"))
        self.assertFalse(is_ours("mailto:talha.nadeem@aku.edu"))


class Rewrite(unittest.TestCase):

    def test_news_link_becomes_the_story(self):
        new, why = rewrite_href(
            "/news/some-story",
            story_slugs={"some-story": "regions/pk/news/some-story"})
        self.assertEqual(new, "/regions/pk/news/some-story")
        self.assertIn("story", why)

    def test_blog_link_becomes_the_story(self):
        new, _ = rewrite_href("/blogs/pages/detail-page.aspx?pid=42",
                              blog_ids={42: "global/blogs/a-post"})
        self.assertEqual(new, "/global/blogs/a-post")

    def test_document_becomes_its_asset(self):
        new, _ = rewrite_href(
            "/qtl/Documents/Transforming%20Teaching%20A5-1.pdf",
            assets={"Transforming Teaching A5-1.pdf":
                    "https://a.storyblok.com/f/1/x/transforming.pdf"})
        self.assertTrue(new.startswith("https://a.storyblok.com/"))

    def test_nothing_is_invented_when_the_target_is_unknown(self):
        """The important one: an unresolved link is left alone, not guessed."""
        for href in ("/news/a-story-we-never-migrated",
                     "/blogs/pages/detail-page.aspx?pid=9999",
                     "/qtl/Documents/never-uploaded.pdf"):
            new, why = rewrite_href(href, story_slugs={}, blog_ids={},
                                    assets={})
            self.assertIsNone(new, href)
            self.assertTrue(why)

    def test_site_pages_and_external_are_left_alone(self):
        for href in ("/coe-wch/about/Pages/east-africa.aspx",
                     "http://hec.gov.pk/x.pdf"):
            self.assertIsNone(rewrite_href(href)[0], href)


if __name__ == "__main__":
    unittest.main()
