#!/usr/bin/env python3
"""
export_dev_tree.py — emit the tree in the shape the front end consumes.

The dev's sync file is nested region -> entities -> departments with name, slug,
short_name, has_news. Ours is a flat folder list. Rather than have each side
hand-maintain its own copy and drift, this projects ours into their shape, so the
file they load is generated from the same source that computes every upload path.

has_news is emitted honestly: true when that exact folder holds stories itself.
An entity with has_news=false and populated departments is normal -- it means the
stories live one level down, not that the entity is empty.

Usage:
    python scripts/taxonomy/export_dev_tree.py [out.json]
"""

import json
import os
import sys
from collections import OrderedDict

import paths

SEED = os.path.join(paths.SEED, "folders.json")
OUT = os.path.join(paths.SEED, "regions_entities_departments.json")


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else OUT
    with open(SEED, encoding="utf-8") as f:
        folders = json.load(f)["folders"]

    # news folders carry the counts; a region/entity/department folder is a
    # container, so ask its child News folder whether anything lives there.
    news_at = {}
    for f in folders:
        if f["level"] == "news":
            news_at[f["parent_full_slug"]] = f.get("expected_news_count", 0)

    regions = OrderedDict()
    for f in folders:
        lvl = f["level"]
        if lvl == "region":
            regions[f["full_slug"]] = OrderedDict([
                ("name", f["name"]), ("slug", f["slug"]),
                ("short_name", f.get("short_name")),
                ("has_news", bool(news_at.get(f["full_slug"], 0))),
                ("entities", OrderedDict()),
            ])
    for f in folders:
        if f["level"] != "entity":
            continue
        reg = regions.get("/".join(f["full_slug"].split("/")[:2]))
        if reg is None:
            continue
        reg["entities"][f["full_slug"]] = OrderedDict([
            ("name", f["name"]), ("slug", f["slug"]),
            ("short_name", f.get("short_name")),
            ("address", None),
            ("has_news", bool(news_at.get(f["full_slug"], 0))),
            ("departments", []),
        ])
    for f in folders:
        if f["level"] != "department":
            continue
        parts = f["full_slug"].split("/")
        reg = regions.get("/".join(parts[:2]))
        ent = reg["entities"].get("/".join(parts[:4])) if reg else None
        if ent is None:
            continue
        ent["departments"].append(OrderedDict([
            ("name", f["name"]), ("slug", f["slug"]),
            ("short_name", f.get("short_name")),
            ("address", None),
            ("has_news", bool(news_at.get(f["full_slug"], 0))),
        ]))

    out = []
    for r in regions.values():
        r = OrderedDict(r)
        r["entities"] = list(r["entities"].values())
        out.append(r)

    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")

    n_e = sum(len(r["entities"]) for r in out)
    n_d = sum(len(e["departments"]) for r in out for e in r["entities"])
    print(f"  {len(out)} regions, {n_e} entities, {n_d} departments")
    print(f"  -> {out_path}")


if __name__ == "__main__":
    main()
