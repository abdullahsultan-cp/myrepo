#!/usr/bin/env python3
"""
dump_sb_tree.py — the live Storyblok folder tree, with ids.

Read-only. GET requests only.

The folder structure in the space is now authoritative, and the upload needs a
parent id per destination. So this snapshots every folder with its id, slug,
parent and depth, writes it as JSON + CSV, and prints the tree.

Unlike verify_folders.py this makes no judgement about what should exist. It
records what does, so our data can be mapped onto it.

Usage:
    python scripts/migrate/review/dump_sb_tree.py
    python scripts/migrate/review/dump_sb_tree.py --tree          # print it
    python scripts/migrate/review/dump_sb_tree.py --under regions
"""

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict

try:
    import requests
except ImportError:
    sys.exit("pip install -r requirements.txt")

# Walk up to the pipeline/ root rather than counting dirname() calls: the
# scripts using this sit at two different depths (migrate/ and
# migrate/review/), and a fixed count is right for one and wrong for the
# other -- which is exactly how this broke.
# Two things have to be importable: this flow's own helpers (migrate/paths.py,
# migrate/db.py) and the shared pipeline modules. The scripts using this sit at
# two different depths -- migrate/ and migrate/review/ -- so the pipeline root is
# found by walking up for _bootstrap.py rather than by counting dirname() calls,
# which is right for one depth and silently wrong for the other.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_d = os.path.dirname(os.path.abspath(__file__))
while _d != os.path.dirname(_d):
    if os.path.exists(os.path.join(_d, "_bootstrap.py")):
        sys.path.insert(0, _d)
        break
    _d = os.path.dirname(_d)
import _bootstrap  # noqa: F401,E402
from paths import BASE  # noqa: E402

from storyblok_config import load_config, management_api_base  # noqa: E402

# Paths come from the shared module so this script works for any content
# type; see pipeline/paths_root.py.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from paths_root import P  # noqa: E402

OUT_JSON = os.path.join(P.MIGRATE, "sb_folder_tree.json")
OUT_CSV = os.path.join(P.MIGRATE, "sb_folder_tree.csv")


def fetch_all(cfg, folders_only=True):
    api = f"{management_api_base(cfg)}/spaces/{cfg['space_id']}"
    s = requests.Session()
    s.headers.update({"Authorization": cfg["management_token"]})
    out, page = [], 1
    params = {"per_page": 100}
    if folders_only:
        params["folder_only"] = 1
    while True:
        r = s.get(f"{api}/stories", params={**params, "page": page}, timeout=120)
        if r.status_code != 200:
            sys.exit(f"list failed: {r.status_code} {r.text[:300]}")
        chunk = r.json().get("stories") or []
        out.extend(chunk)
        total = int(r.headers.get("Total", len(out)))
        print(f"    {len(out)}/{total}", end="\r", flush=True)
        if len(out) >= total or not chunk:
            break
        page += 1
    print(" " * 40, end="\r")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", action="store_true", help="print the tree")
    ap.add_argument("--under", help="only this subtree, by full_slug prefix")
    ap.add_argument("--max-depth", type=int, default=99)
    a = ap.parse_args()

    cfg = load_config()
    print(f"  space {cfg['space_id']} (read-only)")
    live = fetch_all(cfg)
    folders = [f for f in live if f.get("is_folder")]

    # Anything at a folder path that is NOT a folder is worth surfacing: a story
    # sitting where a folder is expected cannot have children.
    print(f"  {len(folders)} folders\n")

    rows = []
    for f in sorted(folders, key=lambda x: (x["full_slug"].count("/"),
                                            x["full_slug"])):
        fs = f["full_slug"]
        if a.under and not (fs == a.under or fs.startswith(a.under + "/")):
            continue
        rows.append({
            "id": f["id"],
            "uuid": f.get("uuid") or "",
            "full_slug": fs,
            "slug": f.get("slug") or "",
            "name": f.get("name") or "",
            "parent_id": f.get("parent_id") or 0,
            "depth": fs.count("/"),
            "is_folder": True,
        })

    by_id = {r["id"]: r for r in rows}
    for r in rows:
        p = by_id.get(r["parent_id"])
        r["parent_full_slug"] = p["full_slug"] if p else ""

    print("  folders by depth")
    for d, n in sorted(Counter(r["depth"] for r in rows).items()):
        print(f"    depth {d}: {n}")

    print("\n  leaf folder names (what stories get filed into)")
    leaf = Counter(r["slug"] for r in rows
                   if r["slug"] in ("news", "blogs", "events", "articles"))
    for k, n in leaf.most_common():
        print(f"    {k:<10} {n}")

    print("\n  roots")
    for r in rows:
        if r["depth"] == 0:
            print(f"    id={r['id']:<18} {r['full_slug']:<24} name={r['name']!r}")

    if a.tree:
        kids = defaultdict(list)
        for r in rows:
            kids[r["parent_id"]].append(r)
        roots = [r for r in rows if r["depth"] == 0 or not by_id.get(r["parent_id"])]

        def walk(node, prefix="", last=True):
            if node["depth"] > a.max_depth:
                return
            branch = "└─ " if last else "├─ "
            print(f"  {prefix}{branch}{node['name']}   "
                  f"[{node['slug']}]  id={node['id']}")
            ch = sorted(kids.get(node["id"], []), key=lambda x: x["slug"])
            for i, c in enumerate(ch):
                walk(c, prefix + ("   " if last else "│  "), i == len(ch) - 1)

        print(f"\n{'=' * 74}\n  TREE\n{'=' * 74}")
        for i, r in enumerate(sorted(roots, key=lambda x: x["full_slug"])):
            walk(r, "", i == len(roots) - 1)

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"space_id": cfg["space_id"], "folder_count": len(rows),
                   "folders": rows}, f, indent=2, ensure_ascii=False)
    cols = ["id", "uuid", "full_slug", "slug", "name", "parent_id",
            "parent_full_slug", "depth"]
    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, lineterminator="\n", fieldnames=cols,
                           extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"\n  -> {OUT_JSON}")
    print(f"  -> {OUT_CSV}   ({len(rows)} folders)")


if __name__ == "__main__":
    main()
