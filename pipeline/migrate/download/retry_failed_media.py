#!/usr/bin/env python3
"""
retry_failed_media.py — re-attempt only the downloads that failed.

Separates the retryable from the permanent, because they need different answers:

  transient  429 / 403 / 406 / 202 / timeouts / connection resets — the file is
             probably there, the server just refused us at that moment. Retried
             slowly, one worker, with a pause between each.
  permanent  404 — the file is gone from SharePoint. No number of retries helps.
  malformed  the href held a pasted local path (C:\\Users\\...) or a mangled
             absolute URL. Not fetchable by anyone.

Usage:
    python scripts/migrate/download/retry_failed_media.py            # transient only
    python scripts/migrate/download/retry_failed_media.py --all      # 404s too
    python scripts/migrate/download/retry_failed_media.py --delay 2  # slower
"""

import argparse
import json
import os
import re
import sys
import time

from download_media import MEDIA_DIR, MIN_BYTES, fetch, sha256_of

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _bootstrap  # noqa: F401,E402  -- paths_root now lives in pipeline/core/
from paths import BASE  # noqa: E402

# Paths come from the shared module so this script works for any content
# type; see pipeline/paths_root.py.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from paths_root import P  # noqa: E402
REPORT = os.path.join(P.MIGRATE, "download_report.json")
OUT = os.path.join(P.MIGRATE, "retry_report.json")

PERMANENT = re.compile(r"http 404")
# A drive letter INSIDE the path, e.g. .../C:/Users/... — the naive
# [A-Za-z]:[/\\] also matches the "s:/" in "https://" and swallowed everything.
MALFORMED = re.compile(r"/[A-Za-z]:[/\\]|eduhttp|file://|\\\\", re.I)


def classify(f):
    url, err = f.get("url", ""), f.get("error", "")
    if MALFORMED.search(url):
        return "malformed"
    if PERMANENT.search(err):
        return "permanent"
    return "transient"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true",
                    help="retry 404s as well (rarely helps)")
    ap.add_argument("--delay", type=float, default=1.2,
                    help="seconds between attempts; the 429 came from haste")
    a = ap.parse_args()

    if not os.path.exists(REPORT):
        sys.exit(f"no {REPORT} — run download_media.py first")
    with open(REPORT, encoding="utf-8") as f:
        failed = json.load(f).get("failed") or []
    if not failed:
        print("  nothing failed — nothing to retry")
        return

    buckets = {"transient": [], "permanent": [], "malformed": []}
    for f in failed:
        buckets[classify(f)].append(f)

    print(f"  {len(failed)} failures on record")
    for k, v in buckets.items():
        print(f"    {len(v):>4}  {k}")

    todo = buckets["transient"] + (buckets["permanent"] if a.all else [])
    if buckets["malformed"]:
        print("\n  not retryable — the reference itself is broken:")
        for f in buckets["malformed"]:
            print(f"      {f['filename'][:56]}")
            print(f"        {f['url'][:96]}")

    print(f"\n  retrying {len(todo)} one at a time, {a.delay}s apart")
    ok, still = [], []
    for i, f in enumerate(todo, 1):
        fn, url = f["filename"], f["url"]
        dest = os.path.join(MEDIA_DIR, fn)
        if os.path.exists(dest) and os.path.getsize(dest) >= MIN_BYTES:
            ok.append(fn)
            continue
        meta, err = fetch(url, dest, tries=4)
        if meta:
            ok.append(fn)
            print(f"    [{i}/{len(todo)}] OK   {fn[:64]}  "
                  f"({meta['bytes'] / 1024:.0f} KB)")
        else:
            still.append({**f, "error": err})
            print(f"    [{i}/{len(todo)}] fail {fn[:52]}  {err[:44]}")
        time.sleep(a.delay)

    # write recovered files into the tracking DB
    updated = 0
    if ok:
        try:
            import db as tracking
            rows = []
            for fn in ok:
                dest = os.path.join(MEDIA_DIR, fn)
                if os.path.exists(dest):
                    rows.append((dest, os.path.getsize(dest),
                                 sha256_of(dest), fn))
            with tracking.connect() as c:
                c.execute("SET search_path TO migration, public")
                with c.cursor() as cur:
                    cur.executemany("""
                        UPDATE asset SET source_path=%s, bytes=%s, sha256=%s,
                               exists_on_disk=true, error=NULL,
                               status = CASE WHEN status IN ('uploaded','reused')
                                             THEN status ELSE 'pending' END
                         WHERE source_filename=%s""", rows)
                    updated = cur.rowcount
                c.commit()
        except Exception as e:
            print(f"  (DB not updated: {type(e).__name__})")

    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"retried": len(todo), "recovered": len(ok),
                   "still_failing": still,
                   "permanent_404": [x["filename"] for x in
                                     buckets["permanent"]],
                   "malformed": buckets["malformed"]},
                  f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 62}")
    print(f"  recovered        : {len(ok)}")
    print(f"  still failing    : {len(still)}")
    print(f"  permanent 404s   : {len(buckets['permanent'])}"
          f"{' (retried)' if a.all else ' (skipped)'}")
    print(f"  malformed refs   : {len(buckets['malformed'])}")
    print(f"  DB rows updated  : {updated}")
    print(f"  -> {OUT}")


if __name__ == "__main__":
    main()
