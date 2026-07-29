#!/usr/bin/env python3
"""
build_seed_json.py — one JSON file the backend can seed Storyblok from.

Reads the two sheets produced by build_folder_tree.py and emits a single
document containing:

    meta      counts, so a run can be sanity-checked at a glance
    folders   FLAT and ORDERED — every parent appears before its children, so a
              seeder can walk the list once, create each folder, and look up
              parent_id from the folders it has already created
    tree      the same structure nested, for inspection or recursive creation
    stories   one entry per news item: where it lives, plus the folders it is
              shared into (view only) and whether it also surfaces globally

Slugs are lowercase-hyphenated and use the FULL entity name, never the
abbreviation. Story slugs are unique within their folder — 108 had the
SharePoint id appended to resolve a collision.

Usage:
    python build_seed_json.py <tree_dir> <output_json>

Example:
    python build_seed_json.py out_tree out_tree/storyblok_seed.json
"""

import csv
import json
import os
import sys
from collections import Counter, OrderedDict

SHARE_COLS = 5


def read(path):
    if not os.path.exists(path):
        sys.exit(f"missing input: {path}")
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def short_for(r):
    """The short name of the deepest level this folder actually names."""
    for key, level in (("department_short", "department"),
                       ("entity_short", "entity"),
                       ("region_short", "region")):
        if (r.get(level) or "").strip():
            return (r.get(key) or "").strip() or None
    return None


def parent_of(full_slug):
    return full_slug.rsplit("/", 1)[0] if "/" in full_slug else None


def main(treedir, outpath):
    folders_csv = read(os.path.join(treedir, "folder_structure.csv"))
    routing = read(os.path.join(treedir, "news_routing.csv"))

    # ---- folders, flat and ordered (the CSV is already parent-before-child;
    # sorting by depth is a belt-and-braces guarantee for the seeder)
    folders = []
    for r in folders_csv:
        folders.append({
            "level": r["level"],
            "name": r["folder_name"],
            "slug": r["folder_slug"],
            "full_slug": r["sb_path"],
            "parent_full_slug": parent_of(r["sb_path"]),
            "display_path": r["path"],
            "region": r["region"] or None,
            "entity": r["entity"] or None,
            "region_short": r.get("region_short") or None,
            "entity_short": r["entity_short"] or None,
            "department": r["department"] or None,
            "department_short": r.get("department_short") or None,
            "short_name": short_for(r),
            "is_folder": True,
            "direct_news_count": int(r["news_count"] or 0),
        })
    folders.sort(key=lambda f: (f["full_slug"].count("/"), f["full_slug"]))

    # ---- verify every parent exists and precedes its child
    known, bad_order, orphans = set(), [], []
    for f in folders:
        p = f["parent_full_slug"]
        if p and p not in known:
            (bad_order if any(x["full_slug"] == p for x in folders)
             else orphans).append(f["full_slug"])
        known.add(f["full_slug"])
    if orphans:
        sys.exit(f"folders with no parent: {orphans[:5]}")
    if bad_order:
        sys.exit(f"children before parents: {bad_order[:5]}")

    # ---- nested tree
    by_slug = {f["full_slug"]: dict(f, children=[]) for f in folders}
    roots = []
    for f in folders:
        node = by_slug[f["full_slug"]]
        p = f["parent_full_slug"]
        (by_slug[p]["children"] if p else roots).append(node)

    # ---- stories
    stories = []
    for r in routing:
        shares = [r[f"shared_path_{i}"] for i in range(1, SHARE_COLS + 1)
                  if r.get(f"shared_path_{i}")]
        stories.append({
            "story_id": int(r["news_id"]),
            "name": r["title"],
            "slug": r["sb_path"].rsplit("/", 1)[-1],
            "full_slug": r["sb_path"],
            "folder_full_slug": parent_of(r["sb_path"]),
            "published_date": r["published_date"] or None,
            "region": r["region"] or None,
            "entity": r["entity"] or None,
            "department": r["department"] or None,
            "placement": r["level"],
            "surface_global": r["surface_global"] == "True",
            "shared_folder_full_slugs": shares,
            "provenance": {
                "region_source": r["region_source"],
                "entity_source": r["entity_source"],
            },
        })
    stories.sort(key=lambda s: s["story_id"])

    folder_slugs = {f["full_slug"] for f in folders}
    missing = [s["story_id"] for s in stories
               if s["folder_full_slug"] not in folder_slugs]
    if missing:
        sys.exit(f"stories whose folder does not exist: {missing[:5]}")
    bad_share = sorted({p for s in stories
                        for p in s["shared_folder_full_slugs"]
                        if p not in folder_slugs})
    if bad_share:
        sys.exit(f"share targets that do not exist: {bad_share[:5]}")
    dupes = [k for k, v in Counter(s["full_slug"] for s in stories).items()
             if v > 1]
    if dupes:
        sys.exit(f"duplicate story slugs: {dupes[:5]}")

    doc = OrderedDict()
    doc["meta"] = {
        "source": "AKU SharePoint news export (3606 items)",
        "slug_convention": "lowercase-hyphenated; entities use the full name, "
                           "not the abbreviation",
        "folder_order": "flat 'folders' list is ordered parent-before-child; "
                        "walk it once and resolve parent_id as you go",
        "counts": {
            "folders": len(folders),
            "stories": len(stories),
            "regions": len({f["region"] for f in folders
                            if f["level"] == "region"}),
            "entities": len({f["entity"] for f in folders
                             if f["level"] == "entity"}),
            "region_entity_nodes": sum(1 for f in folders
                                       if f["level"] == "entity"),
            "department_folders": sum(1 for f in folders
                                      if f["level"] == "department"),
            "folders_by_level": dict(Counter(f["level"] for f in folders)),
            "stories_by_placement": dict(Counter(s["placement"]
                                                 for s in stories)),
            "stories_with_shares": sum(1 for s in stories
                                       if s["shared_folder_full_slugs"]),
            "stories_surfacing_global": sum(1 for s in stories
                                            if s["surface_global"]),
        },
    }
    doc["folders"] = folders
    doc["tree"] = roots
    doc["stories"] = stories

    os.makedirs(os.path.dirname(os.path.abspath(outpath)), exist_ok=True)
    with open(outpath, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)

    size = os.path.getsize(outpath) / 1024
    print(f"  {outpath}  ({size:,.0f} KB)\n")
    for k, v in doc["meta"]["counts"].items():
        print(f"  {k:<26} {v}")
    print("\n  all folder parents resolve, all story folders exist, "
          "all share targets exist, no duplicate slugs")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
