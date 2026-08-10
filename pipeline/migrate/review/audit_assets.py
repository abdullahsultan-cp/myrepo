#!/usr/bin/env python3
"""
audit_assets.py — is every asset the stories reference actually on this machine?

Works from the source of truth rather than from any intermediate report: walks all
3606 story payloads, collects every asset each one declares in media[] and
richtext_media[], and checks the local file. The upload reads from disk, so a file
that is not here cannot reach Storyblok no matter what a summary says.

Reports separately, because they need different actions:

    ON DISK          nothing to do
    NO URL           the resolver never found it on the live page -- usually the
                     page genuinely renders fewer images than the export declares
    URL BUT NO FILE  we know where it is and the download did not land -> retry
    EXTRAS           on disk but declared by no story: images the resolver found
                     on a page beyond what the export listed

Usage:
    python scripts/migrate/review/audit_assets.py
    python scripts/migrate/review/audit_assets.py --csv
    python scripts/migrate/review/audit_assets.py --kind document
"""

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict

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

STORIES = P.STORIES
MEDIA_DIR = P.MEDIA_DIR
CACHE = os.path.join(P.MIGRATE, "media_urls.json")
OUT = os.path.join(P.MIGRATE, "asset_audit.csv")

IMAGE = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
DOC = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".csv"}
VIDEO = {".mp4", ".mov", ".wmv", ".avi", ".m4v", ".webm"}


def kind_of(name):
    ext = os.path.splitext(name.lower().split("?")[0])[1]
    if ext == ".gif":
        return "gif"
    if ext in IMAGE:
        return "image"
    if ext in DOC:
        return "document"
    if ext in VIDEO:
        return "video"
    return "other"


def safe_name(url_or_name):
    """Same sanitising download_media.py applies, so lookups match what landed.

    A query string is legal in a URL and illegal in a Windows path, and it was
    an OSError errno 22 before this existed.
    """
    base = os.path.basename((url_or_name or "").split("?")[0])
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base).strip() or "unnamed"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", nargs="?", const=OUT)
    ap.add_argument("--kind", choices=["image", "gif", "document", "video",
                                       "other"])
    ap.add_argument("--list-missing", action="store_true")
    a = ap.parse_args()

    on_disk = {}
    if os.path.isdir(MEDIA_DIR):
        for n in os.listdir(MEDIA_DIR):
            p = os.path.join(MEDIA_DIR, n)
            if os.path.isfile(p) and not n.endswith(".part"):
                on_disk[n] = os.path.getsize(p)
    print(f"  assets/News/media/ holds {len(on_disk)} files, "
          f"{sum(on_disk.values()) / 1e9:.2f} GB\n")

    urls = {}
    if os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as f:
            cache = json.load(f)
        for sid, rec in cache.items():
            for role, entries in (rec.get("by_role") or {}).items():
                for e in entries:
                    key = (sid, role, e.get("filename") or "")
                    urls[key] = e.get("url") or ""

    # ---- walk every story and collect what it declares
    declared = {}          # filename -> record
    uses = 0
    per_story = defaultdict(list)
    for name in sorted(os.listdir(STORIES)):
        if not name.endswith(".json"):
            continue
        sid = name[:-5]
        with open(os.path.join(STORIES, name), encoding="utf-8") as f:
            c = json.load(f)["content"]
        for bucket in ("media", "richtext_media"):
            for m in c.get(bucket) or []:
                fn = m.get("filename") or ""
                if not fn:
                    continue
                uses += 1
                role = m.get("role") or ("richtext" if bucket == "richtext_media"
                                         else "")
                local = safe_name(fn)
                url = urls.get((sid, role, fn), "")
                # richtext assets resolve through their own source_key
                if not url and m.get("source_key"):
                    url = "https://www.aku.edu" + m["source_key"]
                rec = declared.setdefault(local, {
                    "filename": local, "declared_as": fn, "role": role,
                    "kind": kind_of(fn), "stories": set(), "url": url,
                })
                rec["stories"].add(sid)
                if url and not rec["url"]:
                    rec["url"] = url
                per_story[sid].append(local)

    # ---- classify
    rows = []
    for fn, r in sorted(declared.items()):
        if fn in on_disk:
            status = "ON DISK"
        elif r["url"]:
            status = "URL BUT NO FILE"
        else:
            status = "NO URL"
        # story_set stays a set for the per-story roll-up below; `stories` is the
        # flattened form for the CSV. Keeping one key for both silently made the
        # roll-up iterate characters of the joined string.
        rows.append({**r, "status": status,
                     "bytes": on_disk.get(fn, 0),
                     "story_set": r["stories"],
                     "story_count": len(r["stories"]),
                     "stories": ";".join(sorted(r["stories"])[:6])})

    if a.kind:
        rows = [r for r in rows if r["kind"] == a.kind]

    total = len(rows)
    by_status = Counter(r["status"] for r in rows)
    print(f"{'=' * 74}")
    print(f"  DECLARED BY THE STORIES: {total} distinct files "
          f"({uses} uses across {len(per_story)} stories)")
    print("=" * 74)
    for s in ("ON DISK", "URL BUT NO FILE", "NO URL"):
        n = by_status.get(s, 0)
        pct = 100 * n / total if total else 0
        print(f"  {s:<18} {n:>5}   {pct:5.1f}%")

    print("\n  by kind")
    print(f"    {'kind':<10}{'declared':>10}{'on disk':>9}{'missing':>9}")
    for k in ("image", "gif", "document", "video", "other"):
        sel = [r for r in rows if r["kind"] == k]
        if not sel:
            continue
        ok = sum(1 for r in sel if r["status"] == "ON DISK")
        print(f"    {k:<10}{len(sel):>10}{ok:>9}{len(sel) - ok:>9}")

    print("\n  by role")
    for role, n in Counter(r["role"] for r in rows).most_common():
        sel = [r for r in rows if r["role"] == role]
        ok = sum(1 for r in sel if r["status"] == "ON DISK")
        print(f"    {role or '(none)':<12}{n:>6} declared{ok:>7} on disk")

    # ---- extras: on disk but no story declares them
    extras = sorted(set(on_disk) - set(declared))
    ex_bytes = sum(on_disk[f] for f in extras)
    print(f"\n  EXTRAS: {len(extras)} files on disk that no story declares "
          f"({ex_bytes / 1e6:.0f} MB)")
    print("    Images the resolver found on a page beyond what the export "
          "listed.\n    Harmless: nothing references them, so nothing uploads "
          "them.")
    for f in extras[:6]:
        print(f"      {f}")

    retry = [r for r in rows if r["status"] == "URL BUT NO FILE"]
    if retry:
        print(f"\n  {len(retry)} have a known URL but no file — these are"
              f" recoverable:")
        for r in retry[:15]:
            print(f"    {r['filename'][:52]:<52} {r['url'][:60]}")
        print("\n    Fix: python scripts/migrate/download/download_media.py")

    if a.list_missing:
        print(f"\n  NO URL ({by_status.get('NO URL', 0)}):")
        for r in rows:
            if r["status"] == "NO URL":
                print(f"    {r['filename']:<50} stories {r['stories']}")

    # ---- what this means for the upload
    blocked = defaultdict(list)
    for r in rows:
        if r["status"] != "ON DISK":
            for sid in r["story_set"]:
                blocked[sid].append(r["filename"])
    print(f"\n{'=' * 74}")
    print(f"  {len(per_story) - len(blocked)} of {len(per_story)} stories have "
          f"every declared asset on disk")
    print(f"  {len(blocked)} stories are missing at least one")
    print("=" * 74)

    if a.csv:
        os.makedirs(os.path.dirname(os.path.abspath(a.csv)), exist_ok=True)
        cols = ["status", "filename", "declared_as", "role", "kind", "bytes",
                "story_count", "stories", "url"]
        with open(a.csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, lineterminator="\n", fieldnames=cols,
                               extrasaction="ignore")
            w.writeheader()
            w.writerows(sorted(rows, key=lambda r: (r["status"] == "ON DISK",
                                                    r["kind"], r["filename"])))
        print(f"\n  -> {a.csv}  ({len(rows)} rows)")

    return 0 if by_status.get("URL BUT NO FILE", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
