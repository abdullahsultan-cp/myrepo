#!/usr/bin/env python3
"""dump_asset_tree.py — the live asset folder tree, shared by every type.

    python pipeline/migrate/review/dump_asset_tree.py
    python pipeline/migrate/review/dump_asset_tree.py --tree
    python pipeline/migrate/review/dump_asset_tree.py --check

Read-only. GET requests only. Writes `storyblok_space/asset_folder_tree.json`.

## Why this exists

Asset folders were being created blind. `ensure_asset_folder` kept its map of
what exists in memory, so every fresh process started with nothing and rebuilt
the whole tree beside the last one — **seven `regions` roots, five `global`
roots, 444 redundant folders holding 2,311 assets**.

The content tree has had a snapshot for this reason since the dev renamed every
folder under us (`dump_sb_tree.py`). The asset tree now has the same thing, in
the same place, read by the same `P.` accessor:

    P.SPACE_TREE   storyblok_space/folder_tree.json         where stories go
    P.ASSET_TREE   storyblok_space/asset_folder_tree.json   where media goes

`storyblok_space/` describes the **space**, not a content type — news, blogs and
events all read the same file, and none of them owns it.

## For the developer

The tree mirrors the content tree: an asset lives beside the story that uses it.

    regions/<region>/entities/<entity>/departments/<dept>/news
    global/news
    Blogs                     blogs media, flat for now
    events-detail             the dev's

Refresh it after any change to the folders, and **before an upload run**, the
same way `dump_sb_tree.py` is refreshed. A stale snapshot is not dangerous — the
uploader falls back to asking the API — but a fresh one saves several hundred
lookups.

## `--check`

Reports duplicated paths and folders orphaned at the root without changing
anything. Both are symptoms of the bug above; both should read zero.
`merge_asset_folders.py` and `rebuild_asset_tree.py` are the repairs.
"""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
_up = HERE
while _up != os.path.dirname(_up) and not os.path.exists(
        os.path.join(_up, "_bootstrap.py")):
    _up = os.path.dirname(_up)
sys.path.insert(0, _up)
import _bootstrap

_bootstrap.ensure()

sys.path.insert(0, os.path.join(os.path.dirname(HERE), "upload"))
from upload import SB

from paths_root import ROOT, P
from storyblok_config import load_config

# Roots that belong to somebody else, or to no content type. Reported, never
# touched, and never counted as an orphan.
FOREIGN_ROOTS = {"Test", "aku-media-dev", "events-detail"}


def fetch(sb):
    r = sb.get("asset_folders")
    if r is None or r.status_code != 200:
        sys.exit(f"  cannot read asset folders: "
                 f"{getattr(r, 'status_code', 'no response')}")
    return r.json().get("asset_folders") or []


def paths_of(folders):
    """{id: full path}, cycle-safe — a corrupt parent chain must not hang this."""
    by_id = {f["id"]: f for f in folders}
    out = {}
    for folder in folders:
        parts, seen, node = [], set(), folder
        while node and node["id"] not in seen:
            seen.add(node["id"])
            parts.append(node["name"])
            node = by_id.get(node.get("parent_id"))
        out[folder["id"]] = "/".join(reversed(parts))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tree", action="store_true", help="print it")
    ap.add_argument("--check", action="store_true",
                    help="report duplicates and orphans, change nothing")
    a = ap.parse_args()

    sb = SB(load_config())
    folders = fetch(sb)
    paths = paths_of(folders)

    by_path = defaultdict(list)
    for folder in folders:
        by_path[paths[folder["id"]]].append(folder["id"])
    dupes = {p: v for p, v in by_path.items() if len(v) > 1}
    roots = [f for f in folders if not f.get("parent_id")]
    orphans = [f for f in roots if f["name"] not in FOREIGN_ROOTS
               and f["name"] not in {"regions", "global", "Blogs"}]

    print(f"  {len(folders)} asset folder(s), {len(by_path)} distinct path(s)")
    print(f"  roots: {sorted({f['name'] for f in roots})}")
    print(f"  duplicated paths : {len(dupes)}")
    print(f"  orphaned at root : {len(orphans)}"
          + (f"  {dict(Counter(f['name'] for f in orphans).most_common(5))}"
             if orphans else ""))

    if a.check:
        for path in sorted(dupes)[:15]:
            print(f"    duplicate  {path[:64]:<66}x{len(dupes[path])}")
        if dupes or orphans:
            print("\n  repair:  merge_asset_folders.py  then  "
                  "rebuild_asset_tree.py")
        return 1 if (dupes or orphans) else 0

    snapshot = {
        "count": len(folders),
        "roots": sorted({f["name"] for f in roots}),
        "duplicated_paths": len(dupes),
        "orphans_at_root": len(orphans),
        "folders": sorted(
            ({"id": f["id"], "name": f["name"],
              "parent_id": f.get("parent_id"),
              "path": paths[f["id"]],
              "depth": paths[f["id"]].count("/")} for f in folders),
            key=lambda f: f["path"]),
    }
    os.makedirs(os.path.dirname(P.ASSET_TREE), exist_ok=True)
    with open(P.ASSET_TREE, "w", encoding="utf-8", newline="\n") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    print(f"  -> {os.path.relpath(P.ASSET_TREE, ROOT)}")

    if a.tree:
        for folder in snapshot["folders"]:
            print("    " + "  " * folder["depth"] + folder["name"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
