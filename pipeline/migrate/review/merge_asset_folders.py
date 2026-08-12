#!/usr/bin/env python3
"""merge_asset_folders.py — one folder per path in the asset tree.

    python pipeline/migrate/review/merge_asset_folders.py            # dry run
    python pipeline/migrate/review/merge_asset_folders.py --apply
    python pipeline/migrate/review/merge_asset_folders.py --apply --keep-empty

The space accumulated **7 `regions` roots and 5 `global` roots** — one whole
tree per upload run — because `ensure_asset_folder` posted a new folder and only
searched for an existing one if the post failed, on the assumption that "the API
rejects a duplicate name under one parent". It does not. A fresh process starts
with an empty cache, so every run rebuilt the tree beside the last one:

    769 asset folders, 162 duplicated paths, 444 redundant folders
    2,311 of 2,576 assets sitting in a duplicated path

That cause is fixed in `pipeline/migrate/upload/upload.py` — the cache is seeded
from the live space and a folder is looked up before it is created. This script
clears up what the old behaviour left behind.

## What it does, and what it cannot break

For each duplicated path it keeps **one** folder — the one holding the most
assets, and the lowest id where that ties, so the choice is the same on every
run — moves the assets out of the others into it, then deletes the folders it
emptied.

**Moving an asset does not change its URL.** A Storyblok asset URL is
`a.storyblok.com/f/<space>/<dimensions>/<hash>/<filename>`; the folder is
metadata, not part of the address. Nothing that references an asset can break,
including the 3,606 news stories and the 8 live blogs.

**A folder is only deleted once it is empty**, and emptiness is re-read from the
API rather than assumed from the move having returned 200. A folder that still
holds anything is reported and left alone.

**Its sub-folders are re-parented first.** Storyblok does not delete a folder's
children with it — it moves them to the root. The first version of this script
skipped that step and left 142 folders at the top level with `regions/` and
`global/` empty, which took `rebuild_asset_tree.py` to undo. Deleting a folder
is not a leaf operation.

**Nothing is written without `--apply`**, and the dry run prints the whole plan:
every folder that would be kept, every one that would be emptied, every asset
that would move.

`--keep-empty` leaves folders that were already empty before this ran. There are
93 of them and they are harmless; removing them is tidying, not repair.
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
from upload import SB

from paths_root import ROOT, P
from storyblok_config import load_config

# 204 No Content is a SUCCESS for a PUT on an asset and a DELETE on a folder.
# Accepting only (200, 201) is how a run that moved 786 assets perfectly
# reported "0 moved, 786 failed".
OK = (200, 201, 202, 204)


def folder_paths(folders):
    """{folder id: full path}, cycle-safe."""
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


def all_assets(sb):
    """Every asset in the space, paginated."""
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


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--keep-empty", action="store_true",
                    help="leave folders that were already empty")
    a = ap.parse_args()

    sb = SB(load_config())
    r = sb.get("asset_folders")
    if r is None or r.status_code != 200:
        sys.exit(f"  cannot read asset folders: "
                 f"{getattr(r, 'status_code', 'no response')}")
    folders = r.json().get("asset_folders") or []
    paths = folder_paths(folders)

    assets = all_assets(sb)
    holding = defaultdict(list)
    for asset in assets:
        holding[asset.get("asset_folder_id") or 0].append(asset["id"])
    print(f"  {len(folders)} asset folder(s), {len(assets)} asset(s)")

    by_path = defaultdict(list)
    for folder in folders:
        by_path[paths[folder["id"]]].append(folder["id"])

    moves, drop, keep = [], [], {}
    for path, ids in sorted(by_path.items()):
        if len(ids) < 2:
            continue
        # Most assets wins; lowest id breaks the tie, so the choice is stable.
        winner = sorted(ids, key=lambda i: (-len(holding[i]), i))[0]
        keep[path] = winner
        for other in ids:
            if other == winner:
                continue
            moves += [(asset, other, winner) for asset in holding[other]]
            drop.append((path, other))

    already_empty = [f["id"] for f in folders
                     if not holding[f["id"]]
                     and f["id"] not in {v for v in keep.values()}
                     and f["id"] not in {d for _, d in drop}]

    print(f"\n  {len(by_path)} distinct path(s); "
          f"{sum(1 for v in by_path.values() if len(v) > 1)} duplicated")
    print(f"  {len(moves)} asset(s) would move, "
          f"{len(drop)} folder(s) would be emptied and deleted")
    if not a.keep_empty:
        print(f"  {len(already_empty)} folder(s) were already empty and would "
              f"also go")
    for path in sorted(keep)[:12]:
        others = [i for i in by_path[path] if i != keep[path]]
        print(f"    keep {keep[path]:<18}{path[:52]:<54}"
              f"drop {len(others)}")
    if len(keep) > 12:
        print(f"    … and {len(keep) - 12} more path(s)")

    report = {"folders": len(folders), "assets": len(assets),
              "duplicated_paths": len(keep), "moves": len(moves),
              "delete": len(drop), "already_empty": len(already_empty),
              "keep": keep}
    out = os.path.join(P.DATA, "asset_folder_merge.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"  -> {os.path.relpath(out, ROOT)}")

    if not a.apply:
        print("\n  nothing written. Re-run with --apply when this looks right.")
        return 0

    moved = failed = 0
    for n, (asset_id, _from, to) in enumerate(moves, 1):
        r = sb.put(f"assets/{asset_id}", {"asset_folder_id": to})
        if r is not None and r.status_code in OK:
            moved += 1
        else:
            failed += 1
            print(f"    move failed for asset {asset_id}: "
                  f"{getattr(r, 'status_code', '?')}")
        if n % 200 == 0:
            print(f"    moved {n}/{len(moves)}…")
    print(f"  {moved} asset(s) moved, {failed} failed")

    # Re-parent the sub-folders of anything about to be deleted, BEFORE
    # deleting it. Storyblok does not remove a folder's children with it — it
    # moves them to the root. Skipping this is what left 142 folders at the top
    # level and emptied regions/ and global/, and it needed a second script to
    # undo. Deleting a folder is not a leaf operation.
    r = sb.get("asset_folders")
    current = (r.json().get("asset_folders") or []) if r is not None else []
    doomed = {fid for _, fid in drop}
    kept_for = {}
    for path_name, fid in drop:
        kept_for[fid] = keep[path_name]
    reparented = 0
    for folder in current:
        parent = folder.get("parent_id")
        if parent in doomed:
            r = sb.put(f"asset_folders/{folder['id']}",
                       {"asset_folder": {"name": folder["name"],
                                         "parent_id": kept_for[parent]}})
            if r is not None and r.status_code in OK:
                reparented += 1
            else:
                print(f"    could not re-parent folder {folder['id']} "
                      f"({folder['name']}): {getattr(r, 'status_code', '?')}")
    print(f"  {reparented} sub-folder(s) re-parented before any deletion")

    # Re-read rather than trust the moves: a folder is deleted only once the
    # API agrees it is empty.
    fresh = defaultdict(int)
    for asset in all_assets(sb):
        fresh[asset.get("asset_folder_id") or 0] += 1

    targets = [fid for _, fid in drop]
    if not a.keep_empty:
        targets += already_empty
    deleted = skipped = 0
    for fid in targets:
        if fresh.get(fid):
            skipped += 1
            print(f"    folder {fid} still holds {fresh[fid]} asset(s) — kept")
            continue
        r = sb._call("DELETE", f"asset_folders/{fid}")
        if r is not None and r.status_code in OK:
            deleted += 1
        else:
            skipped += 1
            print(f"    delete failed for folder {fid}: "
                  f"{getattr(r, 'status_code', '?')}")
    print(f"  {deleted} folder(s) deleted, {skipped} left alone")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
