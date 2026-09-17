"""mirror_asset_tree.py — the asset tree, shaped like the content tree, under one root.

    python pipeline/migrate/review/mirror_asset_tree.py                 # dry run
    python pipeline/migrate/review/mirror_asset_tree.py --apply         # create folders
    python pipeline/migrate/review/mirror_asset_tree.py --apply --limit 5
    python pipeline/migrate/review/mirror_asset_tree.py --moves --apply # re-file assets
    python pipeline/migrate/review/mirror_asset_tree.py --prune --apply # drop emptied folders

`regions` is the only parent. Every content folder under it gets an asset folder
at the same path, so a page's media is findable from the page's own address and
nothing has to be searched for by filename.

Three things this does, in this order, each one separately opted into:

  1. **create** the asset folders the content tree has and the asset tree does
     not — parents before children, looking each one up first.
  2. **move**   the assets filed outside `regions/` into their place in it. The
     mapping is the MOVES table below and nothing else; it is deliberately a
     written list, not a guess from a name.
  3. **prune**  the folders emptied by step 2 — deepest first, and only ones
     holding neither an asset nor a child.

Why each rule is here, and what broke to put it there:

* **Look up before creating.** Storyblok does NOT reject a duplicate name under
  one parent — it makes a second folder. Posting first and searching only on
  failure is how the space reached 769 asset folders, 444 of them redundant,
  with 7 `regions` roots and 5 `global` roots.
* **Read the live API, never the snapshot, to decide a write.**
  `storyblok_space/asset_folder_tree.json` is written by `dump_asset_tree.py` and
  is as old as the last person to run it. Seeding a create decision from a stale
  file is the same bug as not looking up at all. The snapshot is refreshed
  *after* this runs, not consulted before.
* **Deleting an asset folder does not delete its children — it moves them to the
  root.** Cleaning up duplicates without re-parenting first left 142 folders at
  the top level and emptied `regions/` and `global/`. So `--prune` refuses any
  folder that still holds an asset or a child, and works deepest first.
* **`204 No Content` is success.** A PUT on an asset and a DELETE on a folder
  both return it. Accepting only (200, 201) is how a run that moved 786 assets
  reported `0 moved, 786 failed`.
* **Moving an asset cannot break a published page.** The public URL is
  `a.storyblok.com/f/<space>/<size>/<hash>/<filename>` — the folder appears
  nowhere in it. `asset_folder_id` is metadata. Checked, not assumed.
* **The dev's test scaffolds are excluded by PATH.** Not by matching the word
  "test": `regions/pk/announce/test` is a real folder and AKU publishes pages
  about testing.

Writes `storyblok_space/asset_mirror_plan.csv` every run, dry or not, so the plan
is reviewable in a diff before anyone applies it.

**Take the snapshot and the backup the moment this finishes:**

    python pipeline/migrate/review/dump_asset_tree.py
    python pipeline/migrate/review/backup.py --type news
"""
import argparse
import csv
import os
import sys
import time
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

from paths_root import P
from storyblok_config import load_config

ROOT = "regions"

# The dev's own scaffolding. Excluded by exact path — a prefix test anchored on a
# path separator — because `regions/pk/announce/test` is a genuine folder holding
# genuine pages, and matching the word would take it with them.
EXCLUDE = (
    "regions/test",
    "regions/gl/entities/test2",
    "regions/global2",
)

# Where the assets filed outside `regions/` belong inside it. Every target was
# checked against the live content tree; the run stops if one is missing rather
# than inventing it.
#
# `global/*` is here because the content moved and the assets did not: the dev
# renamed content `global` to `regions/gl` on 9 Sep, leaving 354 assets behind at
# a root whose content no longer exists.
#
# `Migration/*` is the pages work, filed by hand under readable names. Each maps
# to the folder the same section's pages are placed in.
MOVES = {
    "Migration/ Medical College, Pakistan":
        "regions/pk/entities/mc",
    "Migration/ Medical College, Pakistan/About":
        "regions/pk/entities/mc/about",
    "Migration/ Medical College, Pakistan/Allied Health":
        "regions/pk/entities/mc/allied-health",
    "Migration/ Medical College, Pakistan/CBCB":
        "regions/pk/entities/mc/cbcb",
    "Migration/ Medical College, Pakistan/CCBP":
        "regions/pk/entities/mc/ccbp",
    "Migration/ Medical College, Pakistan/CCIT":
        "regions/pk/entities/mc/critical-creative-innovative-thinking",
    "Migration/ Medical College, Pakistan/Data Science":
        "regions/pk/entities/mc/data-science",
    "Migration/ Medical College, Pakistan/cgsc":
        "regions/pk/entities/mc/cgsc",
    "Migration/ Medical College, Pakistan/mc":
        "regions/pk/entities/mc",
    "Migration/Centre for Regenerative Medicine":
        "regions/pk/entities/crm",
    "Migration/Centre of Excellence for Trauma & Emergencies":
        "regions/pk/entities/cete",
    "Migration/Clinical Trials Unit":
        "regions/pk/entities/clinical-trials-unit",
    "Migration/Institute for Educational Development":
        "regions/pk/entities/ied",
    "global/news": "regions/gl/news",
    "global/blogs": "regions/gl/blogs",
    "global/events": "regions/gl/events",
}

# Folders nobody asked us to touch. Reported so they are visible, never moved.
LEAVE_ALONE = ("Test", "aku-media-dev", "events-detail", "Blogs",
               "imported-external")

PLAN_CSV = os.path.join(P.SPACE, "asset_mirror_plan.csv")


# ------------------------------------------------------------------ reading

def content_folders(sb):
    """Every content folder in the space, as full slugs. Live, not the snapshot."""
    out, page = [], 1
    while True:
        r = sb.get("stories", params={"per_page": 100, "page": page,
                                      "folder_only": 1})
        if r is None or r.status_code != 200:
            sys.exit(f"  cannot read content folders: "
                     f"{getattr(r, 'status_code', 'no response')}")
        got = r.json().get("stories") or []
        if not got:
            return out
        out += [s["full_slug"] for s in got]
        page += 1


def asset_folders(sb):
    """[(id, path, parent_id)] for every asset folder. Cycle-safe."""
    r = sb.get("asset_folders")
    if r is None or r.status_code != 200:
        sys.exit(f"  cannot read asset folders: "
                 f"{getattr(r, 'status_code', 'no response')}")
    folders = r.json().get("asset_folders") or []
    by_id = {f["id"]: f for f in folders}
    out = []
    for f in folders:
        parts, seen, node = [], set(), f
        while node and node["id"] not in seen:
            seen.add(node["id"])
            parts.append(node["name"])
            node = by_id.get(node.get("parent_id"))
        out.append((f["id"], "/".join(reversed(parts)), f.get("parent_id") or 0))
    return out


def assets_by_folder(sb):
    """{asset_folder_id: [asset id, ...]} for the whole space."""
    held, page = defaultdict(list), 1
    while True:
        r = sb.get("assets", params={"per_page": 100, "page": page})
        if r is None or r.status_code != 200:
            sys.exit(f"  cannot read assets: "
                     f"{getattr(r, 'status_code', 'no response')}")
        got = r.json().get("assets") or []
        if not got:
            return held
        for a in got:
            held[a.get("asset_folder_id") or 0].append(a["id"])
        page += 1


# ------------------------------------------------------------------ planning

def excluded(path):
    return any(path == e or path.startswith(e + "/") for e in EXCLUDE)


def plan_creates(content, existing):
    """Asset folder paths to create, parents before children."""
    want = {p for p in content
            if (p == ROOT or p.startswith(ROOT + "/")) and not excluded(p)}
    missing = want - existing
    return sorted(missing, key=lambda p: (p.count("/"), p))


# ------------------------------------------------------------------ writing

def create_folders(sb, paths, by_path, apply, limit):
    """Create each path, looking it up under its parent first. Never blind."""
    made, skipped = 0, 0
    for path in paths:
        if limit and made >= limit:
            print(f"    --limit {limit} reached; stopping")
            break
        parent_path, _, name = path.rpartition("/")
        parent_id = by_path.get(parent_path, 0) if parent_path else 0
        if parent_path and not parent_id:
            sys.exit(f"  STOPPING: parent {parent_path!r} of {path!r} does not "
                     f"exist. Folders are created parents-first, so this means "
                     f"the plan is out of order — do not force it.")
        if not apply:
            by_path[path] = -1                  # so children still plan cleanly
            made += 1
            continue
        found = find_under(sb, name, parent_id)
        if found is not None:
            by_path[path] = found
            skipped += 1
            print(f"    exists   {path}  (id {found})")
            continue
        r = sb.post("asset_folders",
                    {"asset_folder": {"name": name,
                                      "parent_id": parent_id or None}})
        if r is None or r.status_code not in (200, 201):
            sys.exit(f"  cannot create {path}: "
                     f"{getattr(r, 'status_code', '?')} "
                     f"{getattr(r, 'text', '')[:200]}")
        fid = (r.json().get("asset_folder") or {}).get("id")
        by_path[path] = fid
        made += 1
        print(f"    created  {path}  (id {fid})")
    return made, skipped


_folder_cache = {"at": 0, "rows": []}


def find_under(sb, name, parent_id):
    """The existing folder with this name under this parent, or None.

    Re-reads the folder list at most once every few seconds: a fresh POST must be
    visible to the next lookup, and 900 full listings would be 900 round trips.
    Where duplicates exist the lowest id wins, so every caller agrees which copy
    is canonical.
    """
    if time.time() - _folder_cache["at"] > 3:
        r = sb.get("asset_folders")
        if r is not None and r.status_code == 200:
            _folder_cache["rows"] = r.json().get("asset_folders") or []
            _folder_cache["at"] = time.time()
    hits = [f["id"] for f in _folder_cache["rows"]
            if f.get("name") == name and (f.get("parent_id") or 0) == (parent_id or 0)]
    return min(hits) if hits else None


def move_assets(sb, moves, apply):
    """Re-file assets. 204 is success; so are 200 and 201."""
    moved, failed = 0, 0
    for src, dst, asset_ids, dst_id in moves:
        print(f"    {len(asset_ids):>5} asset(s)  {src}  ->  {dst}")
        if not apply:
            moved += len(asset_ids)
            continue
        for aid in asset_ids:
            r = sb.put(f"assets/{aid}", {"asset_folder_id": dst_id})
            # 204 No Content is what a successful asset PUT returns. Accepting
            # only (200, 201) is how a run that moved 786 assets reported
            # "0 moved, 786 failed".
            if r is None or r.status_code not in (200, 201, 204):
                failed += 1
                print(f"      FAILED asset {aid}: "
                      f"{getattr(r, 'status_code', '?')} "
                      f"{getattr(r, 'text', '')[:120]}")
                continue
            moved += 1
    return moved, failed


def prune(sb, folders, held, by_path, apply):
    """Delete the folders step 2 emptied — deepest first, empty ones only.

    Storyblok moves a deleted folder's children to the ROOT rather than deleting
    them, so a folder with any child is never a candidate however empty it looks.
    """
    has_child = {parent for _, _, parent in folders}
    candidates = []
    for fid, path, _parent in folders:
        root = path.split("/")[0]
        if root == ROOT or root in LEAVE_ALONE:
            continue
        if held.get(fid):
            continue
        if fid in has_child:
            continue
        candidates.append((path.count("/"), path, fid))
    gone = 0
    for _depth, path, fid in sorted(candidates, reverse=True):
        print(f"    {'delete ' if apply else 'would delete'}  {path}")
        if not apply:
            gone += 1
            continue
        r = sb._call("DELETE", f"asset_folders/{fid}")
        if r is None or r.status_code not in (200, 204):
            print(f"      FAILED: {getattr(r, 'status_code', '?')}")
            continue
        gone += 1
    return gone


# ------------------------------------------------------------------ report

def write_plan(rows):
    os.makedirs(os.path.dirname(PLAN_CSV), exist_ok=True)
    with open(PLAN_CSV, "w", encoding="utf-8", newline="\n") as f:
        w = csv.writer(f)
        w.writerow(["action", "path", "target", "depth", "assets", "note"])
        w.writerows(rows)
    print(f"\n  plan -> {os.path.relpath(PLAN_CSV)}  ({len(rows)} row(s))")


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true",
                    help="actually write; without it nothing is changed")
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after N folder creations — prove it on five first")
    ap.add_argument("--moves", action="store_true",
                    help="also re-file the assets outside regions/")
    ap.add_argument("--prune", action="store_true",
                    help="also delete the folders the moves emptied")
    a = ap.parse_args()

    sb = SB(load_config())

    print("  reading the live space (the snapshot is not trusted for a write)")
    content = content_folders(sb)
    folders = asset_folders(sb)
    held = assets_by_folder(sb)
    by_path = {}
    for fid, path, _parent in folders:
        by_path.setdefault(path, fid)           # lowest id wins on a duplicate
    print(f"    {len(content)} content folder(s), {len(folders)} asset folder(s), "
          f"{sum(len(v) for v in held.values())} asset(s)")

    content_set = set(content)
    creates = plan_creates(content_set, set(by_path))
    rows = [["create", p, "", p.count("/"), 0, ""] for p in creates]

    print(f"\n  1 · create — {len(creates)} folder(s) the content tree has and "
          f"the asset tree does not")
    if creates:
        by_depth = Counter(p.count("/") for p in creates)
        print("      by depth: " + ", ".join(f"{d}:{n}"
                                             for d, n in sorted(by_depth.items())))
        for p in creates[:8]:
            print(f"      {p}")
        if len(creates) > 8:
            print(f"      ... and {len(creates) - 8} more")
    skipped = sorted(p for p in content_set
                     if (p == ROOT or p.startswith(ROOT + "/")) and excluded(p))
    print(f"      {len(skipped)} scaffold folder(s) excluded by path")
    rows += [["exclude", p, "", p.count("/"), 0, "dev scaffold"] for p in skipped]

    # ---- moves. Every target must already be a content folder, or stop.
    move_plan = []
    for src, dst in sorted(MOVES.items()):
        if dst not in content_set:
            sys.exit(f"\n  STOPPING: {src!r} is mapped to {dst!r}, which is not a "
                     f"content folder in the live space. Fix the MOVES table — "
                     f"do not let it create one.")
        fid = by_path.get(src)
        if fid is None:
            rows.append(["move", src, dst, "", 0, "source folder absent"])
            continue
        ids = held.get(fid) or []
        if ids:
            move_plan.append((src, dst, ids, by_path.get(dst)))
        rows.append(["move", src, dst, "", len(ids), ""])

    total_moving = sum(len(ids) for _s, _d, ids, _t in move_plan)
    print(f"\n  2 · move — {total_moving} asset(s) into the mirror"
          f"{'' if a.moves else '   (not requested; pass --moves)'}")
    for src, dst, ids, _t in move_plan:
        print(f"      {len(ids):>5}  {src}  ->  {dst}")

    # What is left outside regions/ and is nobody's to move.
    outside = Counter()
    for fid, path, _p in folders:
        root = path.split("/")[0]
        if root != ROOT and path not in MOVES:
            outside[path] = len(held.get(fid) or [])
    loose = len(held.get(0) or [])
    print("\n      left outside regions/ and untouched:")
    for path, n in sorted(outside.items()):
        if n or path.split("/")[0] in LEAVE_ALONE:
            print(f"      {n:>5}  {path}")
            rows.append(["leave", path, "", "", n, "not in scope"])
    print(f"      {loose:>5}  (assets with no folder at all)")
    rows.append(["leave", "(root)", "", "", loose, "no folder"])

    # Asset folders under regions/ with no content folder behind them.
    orphan = sorted(p for p in by_path
                    if (p == ROOT or p.startswith(ROOT + "/"))
                    and p not in content_set)
    if orphan:
        print(f"\n      {len(orphan)} asset folder(s) under regions/ that the "
              f"content tree does not have — left alone, reported only:")
        for p in orphan:
            print(f"      {len(held.get(by_path[p]) or []):>5}  {p}")
            rows.append(["orphan", p, "", p.count("/"),
                         len(held.get(by_path[p]) or []), "no content folder"])

    write_plan(rows)

    if not a.apply:
        print("\n  DRY RUN — nothing was written. Re-run with --apply "
              "(and --limit 5 first).")
        return 0

    print("\n  applying")
    made, exists = create_folders(sb, creates, by_path, True, a.limit)
    print(f"    created {made}, already there {exists}")

    if a.moves:
        # Re-resolve targets: the folders they point at may have just been made.
        resolved = []
        for src, dst, ids, _t in move_plan:
            dst_id = by_path.get(dst) or find_under(
                sb, dst.rpartition("/")[2], by_path.get(dst.rpartition("/")[0], 0))
            if not dst_id or dst_id < 0:
                sys.exit(f"  STOPPING: target asset folder {dst!r} does not "
                         f"exist. Run the create step first, without --limit.")
            resolved.append((src, dst, ids, dst_id))
        moved, failed = move_assets(sb, resolved, True)
        print(f"    moved {moved}, failed {failed}")
        if failed:
            print("    re-run to retry the failures; moving is idempotent")

    if a.prune:
        folders = asset_folders(sb)
        held = assets_by_folder(sb)
        gone = prune(sb, folders, held, by_path, True)
        print(f"    deleted {gone} empty folder(s)")

    print("\n  NOW, before anything else:")
    print("    python pipeline/migrate/review/dump_asset_tree.py")
    print("    python pipeline/migrate/review/backup.py --type news")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
