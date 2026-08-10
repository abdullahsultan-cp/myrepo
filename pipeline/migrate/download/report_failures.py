#!/usr/bin/env python3
"""
report_failures.py — everything that did not work, in one place.

Four kinds of failure, kept apart because they need different fixes:

  page       the SharePoint news page would not load, so no banner/medium URL
             could be found for that story
  unresolved a media record exists but no live URL was found for it
  dead       a resolved URL does not actually serve an image
  story      a Storyblok upload failed (from the tracking DB, if reachable)

Usage:
    python scripts/migrate/download/report_failures.py            # summary
    python scripts/migrate/download/report_failures.py --verify   # also HEAD every URL
    python scripts/migrate/download/report_failures.py --csv out.csv
"""

import argparse
import concurrent.futures as cf
import csv
import json
import os
import sys
from collections import Counter

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
STORIES = P.STORIES
OUT_DEFAULT = os.path.join(P.MIGRATE, "failures.csv")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def title_of(sid):
    p = os.path.join(STORIES, f"{sid}.json")
    if not os.path.exists(p):
        return ""
    return ((load(p).get("content") or {}).get("title") or "")[:90]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true",
                    help="fetch every resolved URL to find dead ones")
    ap.add_argument("--csv", nargs="?", const=OUT_DEFAULT)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()

    if not os.path.exists(CACHE):
        sys.exit(f"no cache at {CACHE} — run resolve_media_urls.py first")
    cache = load(CACHE)
    all_ids = sorted((n[:-5] for n in os.listdir(STORIES)
                      if n.endswith(".json")), key=int)

    rows = []

    # ---- 1. pages that would not load
    page_fail = Counter()
    for sid, v in cache.items():
        http = v.get("http")
        if http is not None and http != 200:
            page_fail[str(http)] += 1
            rows.append({"kind": "page", "sharepoint_id": sid,
                         "detail": str(http), "url": v.get("page", ""),
                         "title": title_of(sid)})

    # ---- 2. never fetched at all
    not_fetched = [s for s in all_ids if not cache.get(s, {}).get("fetched")]

    # ---- 3. media records with no URL
    unresolved = []
    for sid in all_ids:
        for role, lst in (cache.get(sid, {}).get("by_role") or {}).items():
            for e in lst:
                if not e.get("url"):
                    unresolved.append((sid, role, e.get("filename", "")))
                    rows.append({"kind": "unresolved", "sharepoint_id": sid,
                                 "detail": role,
                                 "url": e.get("filename", ""),
                                 "title": title_of(sid)})

    # ---- 4. dead URLs
    dead = []
    if a.verify:
        import requests
        pairs = [(sid, e["url"])
                 for sid in all_ids
                 for lst in (cache.get(sid, {}).get("by_role") or {}).values()
                 for e in lst if e.get("url")]
        seen, uniq = set(), []
        for sid, u in pairs:
            if u not in seen:
                seen.add(u)
                uniq.append((sid, u))
        print(f"  verifying {len(uniq)} distinct URLs ...")

        def chk(item):
            sid, u = item
            try:
                r = requests.get(u, headers=UA, timeout=20, stream=True)
                ct = r.headers.get("Content-Type", "")
                code = r.status_code
                r.close()
                good = code == 200 and ("image" in ct or "video" in ct
                                        or "pdf" in ct or "octet" in ct)
                return None if good else (sid, u, f"{code} {ct[:30]}")
            except Exception as e:
                return (sid, u, type(e).__name__)
        with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
            for res in ex.map(chk, uniq):
                if res:
                    dead.append(res)
                    rows.append({"kind": "dead", "sharepoint_id": res[0],
                                 "detail": res[2], "url": res[1],
                                 "title": title_of(res[0])})

    # ---- 5. failed Storyblok uploads
    upload_fail = []
    try:
        import db as tracking
        with tracking.connect() as c:
            c.execute("SET search_path TO migration, public")
            upload_fail = c.execute(
                """SELECT sharepoint_id, title, left(coalesce(error,''), 120)
                   FROM story WHERE status = 'failed'
                   ORDER BY sharepoint_id""").fetchall()
            asset_fail = c.execute(
                """SELECT sharepoint_id, role, source_filename,
                          left(coalesce(error,''), 90)
                   FROM asset WHERE status IN ('failed','missing')
                   ORDER BY sharepoint_id LIMIT 500""").fetchall()
        for sid, t, err in upload_fail:
            rows.append({"kind": "story-upload", "sharepoint_id": sid,
                         "detail": err, "url": "", "title": (t or "")[:90]})
        for sid, role, fn, err in asset_fail:
            rows.append({"kind": "asset-upload", "sharepoint_id": sid,
                         "detail": f"{role}: {err}", "url": fn,
                         "title": ""})
    except Exception as e:
        print(f"  (tracking DB unavailable: {type(e).__name__})")
        asset_fail = []

    # ---------------------------------------------------------------- report
    print(f"\n{'=' * 68}\n  FAILURE REPORT\n{'=' * 68}")
    print(f"  stories total            : {len(all_ids)}")
    print(f"  pages fetched OK         : "
          f"{sum(1 for v in cache.values() if v.get('http') == 200)}")
    print(f"  not fetched yet          : {len(not_fetched)}")
    print(f"\n  PAGE FETCH FAILURES     : {sum(page_fail.values())}")
    for k, n in page_fail.most_common():
        print(f"      {n:>5}  http/{k}")
    print(f"\n  MEDIA WITH NO URL       : {len(unresolved)}")
    byrole = Counter(r for _, r, _ in unresolved)
    for k, n in byrole.most_common():
        print(f"      {n:>5}  role={k}")
    if a.verify:
        print(f"\n  DEAD URLs               : {len(dead)}")
        for k, n in Counter(d[2] for d in dead).most_common(8):
            print(f"      {n:>5}  {k}")
    print(f"\n  FAILED STORY UPLOADS    : {len(upload_fail)}")
    for sid, t, err in upload_fail[:10]:
        print(f"      {sid}  {err[:70]}")
    print(f"  ASSET UPLOAD PROBLEMS   : {len(asset_fail)}")

    if page_fail:
        print(f"\n  the {sum(page_fail.values())} stories whose page failed:")
        pf = [r for r in rows if r["kind"] == "page"]
        for r in pf[:25]:
            print(f"      {r['sharepoint_id']:>5}  {r['detail']:<22} "
                  f"{r['title'][:56]}")
        if len(pf) > 25:
            print(f"      ... and {len(pf) - 25} more (see the CSV)")

    if a.csv:
        os.makedirs(os.path.dirname(os.path.abspath(a.csv)), exist_ok=True)
        with open(a.csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, lineterminator="\n",
                               fieldnames=["kind", "sharepoint_id", "detail",
                                             "url", "title"])
            w.writeheader()
            w.writerows(rows)
        print(f"\n  {len(rows)} rows -> {a.csv}")


if __name__ == "__main__":
    main()
