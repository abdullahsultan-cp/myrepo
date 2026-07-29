#!/usr/bin/env python3
"""
build_folders_only.py — folder structure only, for creating the Storyblok tree.

No stories. The backend creates folders from this; content is uploaded
separately through Storyblok.

Usage:
    python build_folders_only.py <tree_dir> <output_dir>

Outputs:
    folders.json       meta + flat ordered list + nested tree
    folders_tree.txt   ASCII tree
    folders.csv        the flat list as a spreadsheet

The flat `folders` list is ordered **parent before child**, so a seeder can walk
it once and resolve each `parent_full_slug` against folders it has already
created. `expected_news_count` is informational only — it says how many stories
will eventually land directly in that folder, so an empty folder that should not
be empty is easy to spot.
"""

import csv
import json
import os
import sys
from collections import Counter, OrderedDict


def read(path):
    if not os.path.exists(path):
        sys.exit(f"missing input: {path}")
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def short_for(r):
    """The short name of the deepest level this folder actually names.

    A department folder is identified by its department, an entity folder by its
    entity, a region folder by its region. Deepest-first, because a department
    row also carries region and entity for permissions.
    """
    for key, level in (("department_short", "department"),
                       ("entity_short", "entity"),
                       ("region_short", "region")):
        if (r.get(level) or "").strip():
            return (r.get(key) or "").strip() or None
    return None


def parent_of(full_slug):
    return full_slug.rsplit("/", 1)[0] if "/" in full_slug else None


def main(treedir, outdir):
    os.makedirs(outdir, exist_ok=True)
    src = read(os.path.join(treedir, "folder_structure.csv"))

    folders = []
    for r in src:
        folders.append(OrderedDict([
            ("level", r["level"]),
            ("name", r["folder_name"]),
            ("slug", r["folder_slug"]),
            ("full_slug", r["sb_path"]),
            ("parent_full_slug", parent_of(r["sb_path"])),
            ("display_path", r["path"]),
            ("region", r["region"] or None),
            ("entity", r["entity"] or None),
            ("region_short", r.get("region_short") or None),
            ("entity_short", r["entity_short"] or None),
            ("department", r["department"] or None),
            ("department_short", r.get("department_short") or None),
            # short_name mirrors whichever level this folder is, so a consumer
            # reads one field instead of picking between the three above.
            ("short_name", short_for(r)),
            ("expected_news_count", int(r["news_count"] or 0)),
        ]))
    folders.sort(key=lambda f: (f["full_slug"].count("/"), f["full_slug"]))

    # ---- every parent must exist and come first
    seen, orphan, out_of_order = set(), [], []
    all_slugs = {f["full_slug"] for f in folders}
    for f in folders:
        p = f["parent_full_slug"]
        if p and p not in seen:
            (out_of_order if p in all_slugs else orphan).append(f["full_slug"])
        seen.add(f["full_slug"])
    if orphan:
        sys.exit(f"folders with a missing parent: {orphan[:5]}")
    if out_of_order:
        sys.exit(f"children listed before parents: {out_of_order[:5]}")
    dupes = [k for k, v in Counter(f["full_slug"] for f in folders).items()
             if v > 1]
    if dupes:
        sys.exit(f"duplicate folder slugs: {dupes[:5]}")

    # ---- nested
    node_of = {f["full_slug"]: OrderedDict(list(f.items()) + [("children", [])])
               for f in folders}
    roots = []
    for f in folders:
        p = f["parent_full_slug"]
        (node_of[p]["children"] if p else roots).append(node_of[f["full_slug"]])

    doc = OrderedDict()
    doc["meta"] = OrderedDict([
        ("purpose", "Storyblok folder structure only — no stories"),
        ("slug_convention", "lowercase-hyphenated; entities use the full name, "
                            "not the abbreviation"),
        ("folder_order", "the flat 'folders' list is ordered parent-before-"
                         "child; walk it once and resolve parent_full_slug "
                         "against folders already created"),
        ("counts", OrderedDict([
            ("folders", len(folders)),
            ("regions", sum(1 for f in folders if f["level"] == "region")),
            ("entities", len({f["entity"] for f in folders
                              if f["level"] == "entity"})),
            ("region_entity_nodes", sum(1 for f in folders
                                        if f["level"] == "entity")),
            ("department_folders", sum(1 for f in folders
                                       if f["level"] == "department")),
            ("news_folders", sum(1 for f in folders if f["level"] == "news")),
            ("by_level", dict(Counter(f["level"] for f in folders))),
        ])),
    ])
    doc["folders"] = folders
    doc["tree"] = roots

    jp = os.path.join(outdir, "folders.json")
    with open(jp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)

    cp = os.path.join(outdir, "folders.csv")
    with open(cp, "w", newline="", encoding="utf-8-sig") as f:
        cols = [k for k in folders[0] if k != "children"]
        cw = csv.DictWriter(f, lineterminator="\n",
                            fieldnames=cols, extrasaction="ignore")
        cw.writeheader()
        cw.writerows(folders)

    # ---- ASCII tree
    tp = os.path.join(outdir, "folders_tree.txt")
    lines = []

    def walk(nodes, prefix=""):
        for i, n in enumerate(nodes):
            last = i == len(nodes) - 1
            lines.append(f"{prefix}{'└── ' if last else '├── '}{n['name']}/")
            if n["children"]:
                walk(n["children"], prefix + ("    " if last else "│   "))

    c = doc["meta"]["counts"]
    lines.append("AKU NEWS — STORYBLOK FOLDER STRUCTURE")
    lines.append("=" * 60)
    lines.append(f"{c['folders']} folders  |  {c['regions']} regions  |  "
                 f"{c['entities']} entities  |  "
                 f"{c['region_entity_nodes']} region-entity nodes  |  "
                 f"{c['department_folders']} department folders")
    lines.append("")
    walk(roots)
    with open(tp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    print(f"  {os.path.basename(jp):<22} {os.path.getsize(jp)/1024:,.0f} KB")
    print(f"  {os.path.basename(cp):<22} {len(folders)} rows")
    print(f"  {os.path.basename(tp):<22} {len(lines)} lines\n")
    for k, v in c.items():
        print(f"  {k:<22} {v}")
    print("\n  parents all resolve and precede children, no duplicate slugs")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
