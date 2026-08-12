#!/usr/bin/env python3
"""rebuild_asset_tree.py — put every asset back under the path its story uses.

    python pipeline/migrate/review/rebuild_asset_tree.py          # dry run
    python pipeline/migrate/review/rebuild_asset_tree.py --apply

## Why this exists

`merge_asset_folders.py` collapsed 162 duplicated paths into one each. It moved
the assets correctly — all 2,576 are accounted for and none was lost — but it
deleted a duplicate folder **without first re-parenting that folder's
sub-folders**. Storyblok does not delete children with their parent; it moves
them to the root. So 142 folders ended up at the top level, `regions/` and
`global/` were left empty, and the tree read as 95 folders called `news`.

Assets were never at risk: the URL of a Storyblok asset does not contain its
folder, so nothing that references one could break. What broke was navigation.

The fix is not to guess where an orphan belongs — the information to do it
properly is already here. Every asset is joined to its story in the tracking
database, and every story's folder path is read **live from the space**, so the
asset tree is rebuilt to mirror the content tree exactly as it stands now.

## Live slugs, never recorded ones

`story.upload_full_slug` in the database is the path as it was at upload time —
`regions/pakistan/entities/medical-college`. The dev has since renamed every
folder to a short code, `regions/pk/entities/mc`. Rebuilding from the database
would recreate a tree that matches nothing. Paths come from the API.

## What it will not do

Assets it cannot place are **left exactly where they are**, and counted. That
covers the 80 that are in no folder at all and anything the database does not
join to a story. An asset in the wrong folder is untidy; an asset moved somewhere
on a guess is worse, because nobody will know to look for it.
"""

import argparse
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
_up = HERE
while _up != os.path.dirname(_up) and not os.path.exists(
        os.path.join(_up, "_bootstrap.py")):
    _up = os.path.dirname(_up)
sys.path.insert(0, _up)
import _bootstrap

_bootstrap.ensure()

sys.path.insert(0, os.path.join(os.path.dirname(HERE), "upload"))
sys.path.insert(0, os.path.dirname(HERE))
from upload import SB, ensure_asset_folder, load_asset_folders

from paths_root import ROOT, P
from storyblok_config import load_config

# 204 No Content is what Storyblok returns for a successful PUT on an asset and
# a successful DELETE on a folder. Treating it as failure is how a run that
# worked perfectly reported "0 moved, 786 failed".
OK = (200, 201, 202, 204)


def all_assets(sb):
    out, page = [], 1
    while True:
        r = sb.get("assets", params={"per_page": 100, "page": page})
        if r is None or r.status_code != 200:
            sys.exit(f"  listing assets failed: "
                     f"{getattr(r, 'status_code', 'no response')}")
        chunk = r.json().get("assets", [])
        out += chunk
        if len(chunk) < 100:
            return out
        page += 1


def live_story_paths(sb):
    """{storyblok story id: its folder path}, read from the space."""
    out, page = {}, 1
    while True:
        r = sb.get("stories", params={"per_page": 100, "page": page,
                                      "story_only": 1})
        if r is None or r.status_code != 200:
            sys.exit(f"  listing stories failed: "
                     f"{getattr(r, 'status_code', 'no response')}")
        chunk = r.json().get("stories", [])
        for story in chunk:
            slug = (story.get("full_slug") or "").strip("/")
            if "/" in slug:
                out[story["id"]] = slug.rsplit("/", 1)[0]
        if len(chunk) < 100:
            return out
        page += 1


def asset_to_story(sb):
    """{storyblok asset id: storyblok story id} from the tracking database."""
    sys.path.insert(0, os.path.join(ROOT, "pipeline", "migrate"))
    try:
        import db
        with db.connect() as c:
            c.execute("SET search_path TO migration, public")
            rows = c.execute(
                "SELECT a.sb_asset_id, min(s.sb_story_id) "
                "FROM asset a JOIN story s USING (sharepoint_id) "
                "WHERE a.sb_asset_id IS NOT NULL "
                "  AND s.sb_story_id IS NOT NULL "
                "GROUP BY a.sb_asset_id").fetchall()
    except Exception as exc:
        sys.exit(f"  tracking database unavailable ({type(exc).__name__}); "
                 f"without it an asset cannot be traced to its story")
    # An asset shared between stories goes with the lowest story id, so the
    # answer is the same every run.
    return {int(a): int(s) for a, s in rows}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    sb = SB(load_config())
    assets = all_assets(sb)
    story_path = live_story_paths(sb)
    owner = asset_to_story(sb)
    print(f"  {len(assets)} asset(s), {len(story_path)} live story path(s), "
          f"{len(owner)} asset(s) traceable to a story")

    r = sb.get("asset_folders")
    folders = (r.json().get("asset_folders") or []) if r is not None else []
    by_id = {f["id"]: f for f in folders}

    def path_of(fid):
        parts, seen = [], set()
        node = by_id.get(fid)
        while node and node["id"] not in seen:
            seen.add(node["id"])
            parts.append(node["name"])
            node = by_id.get(node.get("parent_id"))
        return "/".join(reversed(parts))

    wanted, unplaceable = defaultdict(list), 0
    for asset in assets:
        story = owner.get(asset["id"])
        target = story_path.get(story) if story else None
        if not target:
            unplaceable += 1
            continue
        if path_of(asset.get("asset_folder_id") or 0) == target:
            continue
        wanted[target].append(asset["id"])

    to_move = sum(len(v) for v in wanted.values())
    print(f"  {to_move} asset(s) would move into {len(wanted)} path(s)")
    print(f"  {unplaceable} left where they are — no story to trace them to")
    for target in sorted(wanted)[:10]:
        print(f"    {target[:64]:<66}{len(wanted[target]):>4}")
    if len(wanted) > 10:
        print(f"    … and {len(wanted) - 10} more")

    if not a.apply:
        print("\n  nothing written. Re-run with --apply when this looks right.")
        return 0

    cache = {}
    load_asset_folders(sb, cache)
    moved = failed = 0
    for target in sorted(wanted):
        fid = ensure_asset_folder(sb, target, cache)
        for asset_id in wanted[target]:
            resp = sb.put(f"assets/{asset_id}", {"asset_folder_id": fid})
            if resp is not None and resp.status_code in OK:
                moved += 1
            else:
                failed += 1
                print(f"    move failed for asset {asset_id}: "
                      f"{getattr(resp, 'status_code', '?')}")
        print(f"    {len(wanted[target]):>4} -> {target[:60]}")
    print(f"\n  {moved} moved, {failed} failed")

    # Delete what is now empty, deepest first so a parent is only considered
    # once its children are gone.
    held = defaultdict(int)
    for asset in all_assets(sb):
        held[asset.get("asset_folder_id") or 0] += 1
    r = sb.get("asset_folders")
    folders = (r.json().get("asset_folders") or []) if r is not None else []
    by_id = {f["id"]: f for f in folders}
    children = defaultdict(int)
    for f in folders:
        if f.get("parent_id"):
            children[f["parent_id"]] += 1
    order = sorted(folders, key=lambda f: -len(path_of(f["id"]).split("/")))
    removed = 0
    for f in order:
        if held.get(f["id"]) or children.get(f["id"]):
            continue
        resp = sb._call("DELETE", f"asset_folders/{f['id']}")
        if resp is not None and resp.status_code in OK:
            removed += 1
            children[f.get("parent_id")] = max(
                0, children.get(f.get("parent_id"), 1) - 1)
    print(f"  {removed} empty folder(s) removed")

    out = os.path.join(P.DATA, "asset_tree_rebuild.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"moved": moved, "failed": failed,
                   "unplaceable": unplaceable, "removed": removed}, f,
                  ensure_ascii=False, indent=2)
    print(f"  -> {os.path.relpath(out, ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
