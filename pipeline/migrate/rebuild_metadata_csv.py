#!/usr/bin/env python3
"""
rebuild_metadata_csv.py — reconstruct assets/News/Metadata.csv from asset_map.csv.

Metadata.csv is part of the original SharePoint export bundle, which this repo
never had: assets/News/media/ was rebuilt from the live site, the manifest was
not. Without it, inject_story_media.py cannot run, and without that the story
payloads lose their media[] array entirely -- every banner, medium, thumbnail and
video reference.

asset_map.csv carries exactly the same facts (one row per story per role, with the
filename), so the manifest can be regenerated from it. It is derived data
standing in for a lost input, which is why it is written to a separate path by
default rather than silently overwriting a real export.

Usage:
    python scripts/migrate/rebuild_metadata_csv.py            # dry run
    python scripts/migrate/rebuild_metadata_csv.py --write    # write the file
"""

import argparse
import csv
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import BASE  # noqa: E402

# Paths come from the shared module so this script works for any content
# type; see pipeline/paths_root.py.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _bootstrap  # noqa: F401,E402  -- paths_root now lives in pipeline/core/
from paths_root import P  # noqa: E402

ASSET_MAP = os.path.join(P.MIGRATE, "asset_map.csv")
OUT = os.path.join(os.path.join(P.ASSETS, P.spec["assets"]), "Metadata.csv")

# asset_map role slug -> the Metadata.csv column inject_story_media expects
ROLE_COLUMN = {
    "thumbnail": "Thumbnail image",
    "banner": "Banner image",
    "medium": "Medium image",
    "alternate_banner": "Alternate banner image",
    "video1": "Video1",
    "video2": "Video2",
    "video3": "Video3",
}
COLUMNS = ["Id", "Title", "Video1", "Video2", "Video3", "Thumbnail image",
           "Medium image", "Banner image", "Alternate banner image"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()

    if not os.path.exists(ASSET_MAP):
        sys.exit(f"missing {ASSET_MAP} — run export_asset_map.py first")

    rows = defaultdict(dict)
    titles = {}
    used = Counter()
    skipped = Counter()
    with open(ASSET_MAP, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            sid = (r.get("sharepoint_id") or "").strip()
            role = (r.get("role") or "").strip()
            fn = (r.get("filename") or "").strip()
            if not sid or not fn:
                continue
            if r.get("title"):
                titles[sid] = r["title"]
            col = ROLE_COLUMN.get(role)
            if col is None:
                # richtext assets live inline in the body, not in the manifest
                skipped[role] += 1
                continue
            # one row per story per role; a repeat would mean the map is wrong
            if col in rows[sid] and rows[sid][col] != fn:
                print(f"  ! story {sid} has two {role} files: "
                      f"{rows[sid][col]} and {fn} — keeping the first")
                continue
            rows[sid][col] = fn
            used[role] += 1

    print(f"  {len(rows)} stories, {sum(used.values())} media references")
    for role, n in used.most_common():
        print(f"    {n:>5}  {role:<18} -> {ROLE_COLUMN[role]}")
    if skipped:
        print("  not in the manifest (inline in the body instead):")
        for role, n in skipped.most_common():
            print(f"    {n:>5}  {role}")

    out_rows = []
    for sid in sorted(rows, key=lambda x: int(x) if x.isdigit() else 0):
        row = {c: "" for c in COLUMNS}
        row["Id"] = sid
        row["Title"] = titles.get(sid, "")
        row.update(rows[sid])
        out_rows.append(row)

    if not a.write:
        print(f"\n  DRY RUN — would write {len(out_rows)} rows to {a.out}")
        print("  pass --write")
        return 0

    if os.path.exists(a.out):
        print(f"\n  {a.out} already exists — refusing to overwrite a real "
              f"export.\n  Delete it first if you are sure.")
        return 1

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, lineterminator="\n", fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(out_rows)
    print(f"\n  wrote {len(out_rows)} rows -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
