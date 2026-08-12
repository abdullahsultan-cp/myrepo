#!/usr/bin/env python3
"""The pure logic behind pipeline/migrate/spaces — no network, no git, no disk.

The heavyweight end-to-end suite lives beside the scripts
(pipeline/migrate/spaces/test_spaces_e2e.py, 61 checks) because it opens sockets
and runs git, and the pre-push hook should stay quick. What is pinned here is
the part that is pure, easy to break by accident, and silent when it does break:

  * credential scrubbing -- Storyblok returns a preview_token on every story and
    a first_token on the space. Both are live credentials, and this output is
    committed to a git remote. A regression here leaks them and nothing
    complains.
  * asset path mirroring -- the local path is derived from the asset URL, which
    is what makes a restore able to rewrite references mechanically. It also has
    to survive Windows-illegal characters and refuse to escape its own folder.
  * reference remapping -- a rebuild rewrites asset urls and ids and story links
    inside content. Storyblok stores the same asset reference three ways; fixing
    only the tidy one is how a rebuilt space renders with half its images gone.
  * deterministic output -- the whole value of the backup is `git diff` between
    two snapshots. Any ordering that varies per process turns into a diff that
    means nothing, which this repo has already been bitten by once.
"""

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline", "migrate", "spaces"))

import sb_common as C
from sb_restore import remap_content

SPACE = "289824742951963"


def asset(url, aid=1, **kw):
    return dict({"id": aid, "filename": url}, **kw)


class TestScrub(unittest.TestCase):
    """Nothing that can authenticate may reach a committed file."""

    def test_drops_credentials_at_every_depth(self):
        got = C.scrub({
            "id": 1,
            "preview_token": "LIVE",
            "content": {"title": "ok", "api_key": "LIVE"},
            "list": [{"first_token": "LIVE", "keep": 2}],
        })
        self.assertEqual(got, {"id": 1, "content": {"title": "ok"},
                               "list": [{"keep": 2}]})

    def test_drops_personal_data(self):
        got = C.scrub([{"real_email": "a@b.c", "alt_email": "d@e.f",
                        "name": "kept"}])
        self.assertEqual(got, [{"name": "kept"}])

    def test_every_secret_key_is_actually_removed(self):
        payload = dict.fromkeys(C.SECRET_KEYS, "LIVE")
        payload["keep"] = 1
        self.assertEqual(C.scrub(payload), {"keep": 1})

    def test_leaves_ordinary_values_alone(self):
        # A story body must survive untouched -- scrub is not a cleaner.
        body = {"type": "doc", "content": [{"text": "  spaced  "}],
                "n": 0, "f": False, "none": None}
        self.assertEqual(C.scrub(body), body)


class TestAssetPath(unittest.TestCase):
    """The local path mirrors the asset URL, so a restore can remap by URL."""

    def test_mirrors_the_url_after_the_space_id(self):
        p = C.asset_path(
            asset(f"https://a.storyblok.com/f/{SPACE}/1200x800/abc123/photo.jpg"),
            SPACE)
        self.assertEqual(p.split(os.sep), ["assets", "1200x800", "abc123",
                                           "photo.jpg"])

    def test_percent_escapes_are_decoded(self):
        p = C.asset_path(
            asset(f"https://a.storyblok.com/f/{SPACE}/x/d1/My%20Report.pdf"),
            SPACE)
        self.assertTrue(p.endswith("My Report.pdf"), p)

    def test_a_different_space_in_the_url_still_mirrors(self):
        # Assets moved between spaces, and S3-style hosts, both show up.
        p = C.asset_path(
            asset("https://s3.amazonaws.com/a.storyblok.com/f/99/500x500/aa/l.png"),
            SPACE)
        self.assertEqual(p.split(os.sep), ["assets", "500x500", "aa", "l.png"])

    def test_no_url_falls_back_to_the_asset_id(self):
        p = C.asset_path(asset("", aid=4242), SPACE)
        self.assertEqual(p.split(os.sep), ["assets", "by-id", "4242",
                                           "asset.bin"])

    def test_cannot_escape_the_assets_folder(self):
        # A '..' in a URL must not write outside the snapshot.
        p = C.asset_path(
            asset(f"https://a.storyblok.com/f/{SPACE}/../../evil/x.jpg"), SPACE)
        parts = p.split(os.sep)
        self.assertEqual(parts[0], "assets")
        self.assertNotIn("..", parts)

    def test_windows_illegal_characters_are_replaced(self):
        p = C.asset_path(
            asset(f'https://a.storyblok.com/f/{SPACE}/x/d1/a:b"c.jpg'), SPACE)
        for bad in ':"<>|?*':
            self.assertNotIn(bad, os.path.basename(p))

    def test_is_stable_across_calls(self):
        a = asset(f"https://a.storyblok.com/f/{SPACE}/800x600/aa/p.png")
        self.assertEqual(C.asset_path(a, SPACE), C.asset_path(a, SPACE))


class TestRemapContent(unittest.TestCase):
    """A rebuild rewrites every reference. All three shapes, or images break."""

    def setUp(self):
        self.old_png = f"https://a.storyblok.com/f/{SPACE}/800x600/aa/p.png"
        self.new_png = "https://a.storyblok.com/f/999/900x900/bb/p.png"
        self.urls = {self.old_png: self.new_png}
        self.assets = {9001: 7001}
        self.uuids = {"old-uuid": "new-uuid"}
        self.content = {
            "component": "news_article",
            "hero": {"id": 9001, "filename": self.old_png,
                     "fieldtype": "asset"},
            "body": {"type": "doc", "content": [
                {"type": "image", "attrs": {"id": 9001, "src": self.old_png}},
                {"type": "paragraph", "content": [
                    {"type": "text", "text": f"see {self.old_png} now"}]},
            ]},
            "link": {"linktype": "story", "id": "old-uuid",
                     "cached_url": "news/b"},
        }

    def out(self):
        return remap_content(self.content, self.urls, self.assets, self.uuids)

    def test_asset_object_url_and_id(self):
        hero = self.out()["hero"]
        self.assertEqual(hero["filename"], self.new_png)
        self.assertEqual(hero["id"], 7001)

    def test_richtext_image_node(self):
        attrs = self.out()["body"]["content"][0]["attrs"]
        self.assertEqual(attrs["src"], self.new_png)
        self.assertEqual(attrs["id"], 7001)

    def test_url_sitting_in_prose(self):
        text = self.out()["body"]["content"][1]["content"][0]["text"]
        self.assertIn(self.new_png, text)
        self.assertNotIn(self.old_png, text)

    def test_internal_story_link(self):
        self.assertEqual(self.out()["link"]["id"], "new-uuid")

    def test_no_old_reference_survives_anywhere(self):
        self.assertNotIn(self.old_png, json.dumps(self.out()))

    def test_unknown_references_are_left_alone(self):
        # An asset this backup does not know about must not be mangled.
        self.content["other"] = {"id": 5, "filename": "https://x/f/1/y/z.png"}
        self.assertEqual(self.out()["other"],
                         {"id": 5, "filename": "https://x/f/1/y/z.png"})

    def test_empty_maps_change_nothing(self):
        self.assertEqual(remap_content(self.content, {}, {}, {}), self.content)

    def test_does_not_mutate_its_input(self):
        before = json.dumps(self.content, sort_keys=True)
        self.out()
        self.assertEqual(json.dumps(self.content, sort_keys=True), before)

    def test_survives_a_none_and_an_empty_doc(self):
        self.assertEqual(remap_content({}, self.urls, {}, {}), {})
        self.assertEqual(
            remap_content({"a": None, "b": []}, self.urls, {}, {}),
            {"a": None, "b": []})


class TestDeterminism(unittest.TestCase):
    """A committed snapshot must be byte-identical when nothing changed.

    This repo has already lost a day to the opposite: build_url_lookup built its
    variants in a set literal, Python randomises string hashing per process, and
    every regeneration wrote the same 7,057 entries in a different order -- a
    5,774-line diff meaning nothing.
    """

    def test_lists_are_sorted_by_id(self):
        self.assertEqual([i["id"] for i in
                          C.sort_by_id([{"id": 10}, {"id": 2}, {"id": 33}])],
                         [2, 10, 33])

    def test_mixed_id_types_do_not_raise(self):
        got = C.sort_by_id([{"id": "b"}, {"id": 2}, {"id": "a"}])
        self.assertEqual(len(got), 3)

    def test_lists_without_ids_keep_their_order(self):
        items = [{"name": "z"}, {"name": "a"}]
        self.assertEqual(C.sort_by_id(items), items)

    def test_write_json_is_stable_and_utf8(self):
        import tempfile
        a = {"z": 1, "a": {"n": "Dr Asad I Mian — café", "m": 2}}
        b = {"a": {"m": 2, "n": "Dr Asad I Mian — café"}, "z": 1}
        with tempfile.TemporaryDirectory() as d:
            p1, p2 = os.path.join(d, "1.json"), os.path.join(d, "2.json")
            C.write_json(p1, a)
            C.write_json(p2, b)
            r1 = open(p1, "rb").read()
            self.assertEqual(r1, open(p2, "rb").read())
            # non-ASCII is written as itself, and lines end \n on every platform
            self.assertIn("café".encode(), r1)
            self.assertNotIn(b"\r\n", r1)


class TestRegions(unittest.TestCase):
    def test_every_region_has_a_host(self):
        for r in ("eu", "us", "ca", "ap", "cn"):
            self.assertTrue(C.REGION_HOSTS[r].startswith("https://"))

    def test_api_base_defaults_to_eu(self):
        self.assertEqual(C.api_base({"name": "X", "space_id": "1"}),
                         C.REGION_HOSTS["eu"])

    def test_region_is_case_insensitive(self):
        self.assertEqual(C.api_base({"name": "X", "region": "US"}),
                         C.REGION_HOSTS["us"])


class TestTokenSelection(unittest.TestCase):
    """The environment wins, so CI never needs a token on disk."""

    def test_env_overrides_the_file(self):
        os.environ["SB_TOKEN_AKUEB"] = "from-env"
        try:
            self.assertEqual(
                C.token_for({"name": "AKUEB", "management_token": "from-file"}),
                "from-env")
        finally:
            del os.environ["SB_TOKEN_AKUEB"]

    def test_falls_back_to_the_file(self):
        self.assertEqual(
            C.token_for({"name": "AKUH", "management_token": "from-file"}),
            "from-file")

    def test_site_name_maps_to_a_legal_env_var(self):
        os.environ["SB_TOKEN_AKU_EB"] = "x"
        try:
            self.assertEqual(C.token_for({"name": "aku-eb"}), "x")
        finally:
            del os.environ["SB_TOKEN_AKU_EB"]


SITES = [{"name": "AKUH"}, {"name": "AKU"}, {"name": "AKUEB"}]


class TestPickSites(unittest.TestCase):
    def test_all(self):
        self.assertEqual(len(C.pick_sites(SITES, "all")), 3)

    def test_one_case_insensitively(self):
        self.assertEqual(C.pick_sites(SITES, "akueb"), [{"name": "AKUEB"}])

    def test_a_comma_list(self):
        self.assertEqual(
            [s["name"] for s in C.pick_sites(SITES, "AKUH,AKUEB")],
            ["AKUH", "AKUEB"])

    def test_an_unknown_name_exits_rather_than_silently_doing_nothing(self):
        # Backing up nothing because of a typo must not look like success.
        with self.assertRaises(SystemExit):
            C.pick_sites(SITES, "AKUX")


class TestOkStatus(unittest.TestCase):
    def test_204_counts_as_success(self):
        # A PUT on an asset and a DELETE on a folder both answer 204. Accepting
        # only (200, 201) is how a run that moved 786 assets perfectly reported
        # 0 moved, 786 failed.
        self.assertIn(204, C.OK_STATUS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
