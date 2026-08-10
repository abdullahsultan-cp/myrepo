#!/usr/bin/env python3
"""
export_asset_map.py — the asset map: every file, where it came from, where it
goes, and which story field will point at it.

This is what the Storyblok upload consumes. One row per (story, role, file), so a
file shared by several stories appears once per use but is only uploaded once —
the sha256 column is what makes that safe.

Usage:
    python scripts/migrate/download/export_asset_map.py [--csv] [--json]

Outputs (data/migrate/):
    asset_map.csv        one row per story/role/file
    asset_map.json       the same, plus per-story grouping for the uploader
    asset_summary.txt    counts by role, type, status and target field
"""

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
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
import _bootstrap

_bootstrap.ensure()

# Paths come from the shared module so this script works for any content
# type; see pipeline/paths_root.py.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from paths_root import P

CACHE = os.path.join(P.MIGRATE, "media_urls.json")
MEDIA_DIR = P.MEDIA_DIR
OUT_DIR = P.MIGRATE
STORIES = P.STORIES

# Which news_article field each role lands in. Decided in
# docs/STORYBLOK_TARGET_SCHEMA.md; thumbnail became available when the dev
# added the field, so it is no longer dropped.
ROLE_TARGET = {
    "banner": "content.banner_image",
    "medium": "body[] media_section(type=image)",
    "thumbnail": "content.thumbnail",
    "richtext": "inline in rich_text.content",
    "video1": "body[] media_section(type=video)",
    "video2": "body[] media_section(type=video)",
    "video3": "body[] media_section(type=video)",
    "page-image": "body[] media_section (undeclared page image)",
    "page-file": "link target in rich_text",
}


def kind_of(fn):
    f = (fn or "").lower().split("?")[0]
    if f.endswith(".gif"):
        return "gif"
    if f.endswith((".mp4", ".mov", ".m4v", ".webm", ".avi", ".wmv")):
        return "video"
    if f.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                   ".zip", ".rtf")):
        return "document"
    if f.endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff",
                   ".svg", ".jfif", ".jpe")):
        return "image"
    return "other"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if not (a.csv or a.json):
        a.csv = a.json = True

    if not os.path.exists(CACHE):
        sys.exit(f"no {CACHE} — run resolve_media_urls.py first")
    with open(CACHE, encoding="utf-8") as f:
        cache = json.load(f)

    titles = {}
    for n in os.listdir(STORIES):
        if n.endswith(".json"):
            with open(os.path.join(STORIES, n), encoding="utf-8") as f:
                titles[n[:-5]] = ((json.load(f).get("content") or {})
                                  .get("title") or "")

    # sha256 / upload state from the tracking DB, if reachable
    db_state = {}
    try:
        import db as tracking
        with tracking.connect() as c:
            c.execute("SET search_path TO migration, public")
            for r in c.execute("""SELECT sharepoint_id, role, source_filename,
                                         status, sha256, bytes, sb_asset_id,
                                         sb_filename
                                  FROM asset""").fetchall():
                db_state[(str(r[0]), r[1], r[2])] = r[3:]
    except Exception as e:
        print(f"  (tracking DB unavailable: {type(e).__name__})")

    rows = []
    for sid, e in cache.items():
        for role, lst in (e.get("by_role") or {}).items():
            for x in lst:
                fn = x.get("filename") or ""
                path = os.path.join(MEDIA_DIR, fn) if fn else ""
                on_disk = bool(fn and os.path.exists(path))
                st = db_state.get((sid, role, fn), (None,) * 5)
                rows.append({
                    "sharepoint_id": sid,
                    "title": titles.get(sid, "")[:80],
                    "role": role,
                    "target_field": ROLE_TARGET.get(role, "?"),
                    "kind": kind_of(fn),
                    "filename": fn,
                    "source_url": x.get("url") or "",
                    "url_source": x.get("source") or "",
                    "local_path": path if on_disk else "",
                    "on_disk": on_disk,
                    "bytes": os.path.getsize(path) if on_disk else "",
                    "sha256": st[1] or "",
                    "upload_status": st[0] or ("pending" if on_disk
                                              else "missing"),
                    "sb_asset_id": st[2] or "",
                    "sb_filename": st[3] or "",
                    "caption": x.get("caption") or "",
                    "alt": x.get("alt") or "",
                })
        # undeclared extras: real assets with no export record
        for key, role in (("unmatched_page_images", "page-image"),
                          ("extra_files", "page-file")):
            for u in (e.get(key) or []):
                rows.append({
                    "sharepoint_id": sid, "title": titles.get(sid, "")[:80],
                    "role": role, "target_field": ROLE_TARGET[role],
                    "kind": kind_of(u), "filename": "",
                    "source_url": u, "url_source": "page-scrape",
                    "local_path": "", "on_disk": "", "bytes": "",
                    "sha256": "", "upload_status": "extra",
                    "sb_asset_id": "", "sb_filename": "",
                    "caption": "", "alt": "",
                })

    rows.sort(key=lambda r: (int(r["sharepoint_id"]), r["role"]))
    os.makedirs(OUT_DIR, exist_ok=True)
    cols = list(rows[0].keys()) if rows else []

    if a.csv and rows:
        p = os.path.join(OUT_DIR, "asset_map.csv")
        with open(p, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, lineterminator="\n", fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        print(f"  {len(rows)} rows -> {p}")

    if a.json and rows:
        by_story = defaultdict(list)
        for r in rows:
            by_story[r["sharepoint_id"]].append(r)
        p = os.path.join(OUT_DIR, "asset_map.json")
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"generated_rows": len(rows),
                       "media_dir": MEDIA_DIR,
                       "role_targets": ROLE_TARGET,
                       "by_story": by_story}, f, ensure_ascii=False,
                      separators=(",", ":"))
        print(f"  {len(by_story)} stories -> {p}")

    # ---------------------------------------------------------------- summary
    lines = []
    def add(s=""):
        lines.append(s)
        print(s)

    declared = [r for r in rows if r["upload_status"] != "extra"]
    on_disk = [r for r in declared if r["on_disk"]]
    add(f"\n{'=' * 66}\n  ASSET MAP\n{'=' * 66}")
    add(f"  declared asset uses      : {len(declared)}")
    add(f"  distinct files declared  : "
        f"{len({r['filename'] for r in declared if r['filename']})}")
    add(f"  on disk                  : {len(on_disk)}")
    add(f"  still missing            : {len(declared) - len(on_disk)}")
    add(f"  undeclared page extras   : {len(rows) - len(declared)}")
    total = sum(r["bytes"] for r in on_disk if isinstance(r["bytes"], int))
    add(f"  bytes on disk            : {total / 1024 / 1024:.1f} MB")

    add("\n  by role -> target field:")
    for (role, tgt), n in Counter(
            (r["role"], r["target_field"]) for r in declared).most_common():
        got = sum(1 for r in declared if r["role"] == role and r["on_disk"])
        add(f"    {n:>6}  {got:>6} on disk   {role:<11} -> {tgt}")

    add("\n  by kind:")
    for k, n in Counter(r["kind"] for r in declared).most_common():
        add(f"    {n:>6}  {k}")

    add("\n  by upload status:")
    for k, n in Counter(r["upload_status"] for r in rows).most_common():
        add(f"    {n:>6}  {k}")

    with open(os.path.join(OUT_DIR, "asset_summary.txt"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
