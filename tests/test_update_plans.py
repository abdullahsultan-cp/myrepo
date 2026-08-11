#!/usr/bin/env python3
"""The update engine's safety rules, and every plan's shape.

The engine reaches into published stories. Its whole safety model is that a
plan may only change the fields it declares, so that rule is tested rather than
trusted — and so is the blok walker, which is the piece most likely to be wrong
in a way nobody notices until 3,606 stories have been rewritten.
"""

import glob
import importlib.util
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPDATE = os.path.join(ROOT, "pipeline", "migrate", "update")
sys.path.insert(0, UPDATE)

from helpers import find_bloks, walk_bloks


def load(path):
    spec = importlib.util.spec_from_file_location(
        "plan_" + os.path.basename(path)[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def plan_files():
    return sorted(glob.glob(os.path.join(
        ROOT, "*-Pipeline", "pipeline", "updates", "*.py")))


class Helpers(unittest.TestCase):

    def test_walk_reaches_nested_bloks(self):
        tree = [{"component": "row", "columns": [
            {"component": "iframe", "src": "https://twitter.com/i/status/1"}]}]
        out = walk_bloks(tree, lambda b: dict(b, component="social_embed")
                         if b.get("component") == "iframe" else b)
        self.assertEqual(out[0]["columns"][0]["component"], "social_embed",
                         "a blok nested inside a row must be reached")
        self.assertEqual(out[0]["component"], "row",
                         "the container is passed to fn but fn left it alone")

    def test_walk_can_drop_and_splice(self):
        tree = [{"component": "a"}, {"component": "b"}]
        self.assertEqual(
            [b["component"] for b in
             walk_bloks(tree, lambda b: None if b["component"] == "a" else b)],
            ["b"])
        self.assertEqual(
            len(walk_bloks(tree, lambda b: [b, b])), 4)

    def test_find_bloks_counts_at_depth(self):
        tree = [{"component": "row", "cols": [
            {"component": "iframe"}, {"component": "iframe"}]}]
        self.assertEqual(len(find_bloks(tree, "iframe")), 2)

    def test_walk_leaves_a_tree_alone_when_fn_is_identity(self):
        tree = [{"component": "row", "cols": [{"component": "rich_text"}]}]
        self.assertEqual(walk_bloks(tree, lambda b: b), tree)


class Plans(unittest.TestCase):
    """Every plan in the repo, whoever wrote it."""

    def test_each_plan_declares_fields_and_patch(self):
        for path in plan_files():
            with self.subTest(plan=os.path.relpath(path, ROOT)):
                mod = load(path)
                self.assertTrue(getattr(mod, "FIELDS", None),
                                "a plan without FIELDS may change anything")
                self.assertTrue(callable(getattr(mod, "patch", None)))
                self.assertTrue(getattr(mod, "DESCRIPTION", ""),
                                "--list shows DESCRIPTION")

    def test_patch_returns_only_declared_fields(self):
        """The rule the engine enforces at run time, checked here too.

        Fed a story that should not change and one that should, no plan may
        name a key outside its own whitelist.
        """
        samples = [
            {"body": [{"component": "iframe",
                       "src": "https://twitter.com/i/status/1"}]},
            {"body": [{"component": "rich_text"}]},
            {"body": []},
            {},
        ]
        for path in plan_files():
            mod = load(path)
            ctx = mod.setup({}) if hasattr(mod, "setup") else {}
            for content in samples:
                with self.subTest(plan=os.path.basename(path), content=content):
                    out = mod.patch(dict(content), None, ctx) or {}
                    stray = [k for k in out if k not in mod.FIELDS]
                    self.assertEqual(stray, [], f"undeclared field(s) {stray}")

    def test_a_plan_leaves_unrelated_stories_alone(self):
        """No plan may rewrite a story that has nothing to do with it."""
        unrelated = {"body": [{"component": "rich_text", "content": {}}],
                     "title": "unrelated"}
        for path in plan_files():
            mod = load(path)
            ctx = mod.setup({}) if hasattr(mod, "setup") else {}
            with self.subTest(plan=os.path.basename(path)):
                self.assertEqual(mod.patch(dict(unrelated), None, ctx) or {},
                                 {})


class TwitterPlan(unittest.TestCase):
    """The one real plan, because it runs against 3,610 live stories."""

    def setUp(self):
        path = os.path.join(ROOT, "News-Pipeline", "pipeline", "updates",
                            "twitter_embeds.py")
        if not os.path.exists(path):
            self.skipTest("twitter_embeds plan not present")
        self.plan = load(path)

    def frame(self, src):
        return {"body": [{"component": "iframe", "src": src}]}

    def test_converts_a_tweet(self):
        out = self.plan.patch(self.frame("https://twitter.com/i/status/152"),
                              None, {})
        blok = out["body"][0]
        self.assertEqual(blok["component"], "social_embed")
        self.assertEqual(blok["variant"], "twitter")
        self.assertEqual(blok["url"], "https://twitter.com/i/status/152")

    def test_leaves_youtube_and_the_devs_test_hosts_alone(self):
        for src in ("https://www.youtube.com/embed/G476R4XCwVc",
                    "http://localhost:3010/whatever",
                    "https://aku-dev.vercel.app/x"):
            with self.subTest(src=src):
                self.assertEqual(self.plan.patch(self.frame(src), None, {}), {})

    def test_host_must_match_not_merely_appear(self):
        """`twitter.com` inside a path is not a tweet."""
        self.assertEqual(
            self.plan.patch(
                self.frame("https://example.com/twitter.com/status/1"),
                None, {}),
            {})


if __name__ == "__main__":
    unittest.main()
