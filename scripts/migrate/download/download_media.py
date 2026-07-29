#!/usr/bin/env python3
"""
download_media.py — pull every resolved file off SharePoint, once.

Recording URLs was the wrong shape. Uploading straight from aku.edu would hit the
site a second time, story by story, and the same rate limiting that produced 69
ReadTimeouts during resolution would come back mid-upload — with a half-finished
Storyblok space to clean up.

So fetch each file exactly once, to disk, and upload from there. This also
reconstructs `assets/News/media/`, the bundle that was never in the repo, using
the export's own filenames — which is precisely where upload.py already looks.

Deduplicated by URL, so a file shared by several stories is fetched once.
Resumable: a file already on disk with a plausible size is skipped, so it can be
interrupted and re-run. Records path, size and sha256 in the tracking DB.

Usage:
    python scripts/migrate/download/download_media.py             # everything resolved
    python scripts/migrate/download/download_media.py --sample    # the 20-story sample
    python scripts/migrate/download/download_media.py --workers 6
    python scripts/migrate/download/download_media.py --verify    # re-check what is on disk
"""

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import sys
import re
import threading
import time
import urllib.parse

try:
    import requests
except ImportError:
    sys.exit("pip install -r requirements.txt")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import BASE  # noqa: E402
CACHE = os.path.join(BASE, "data", "migrate", "media_urls.json")
MEDIA_DIR = os.path.join(BASE, "assets", "News", "media")
REPORT = os.path.join(BASE, "data", "migrate", "download_report.json")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
MIN_BYTES = 200          # anything smaller is an error page, not an image
_lock = threading.Lock()


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url, dest, tries=3):
    """Download to a temp file then rename, so an interrupted run never leaves a
    truncated file that a later pass would treat as complete."""
    tmp = dest + ".part"
    for attempt in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=60, stream=True)
            if r.status_code != 200:
                r.close()
                return None, f"http {r.status_code}"
            ctype = r.headers.get("Content-Type", "")
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            n = 0
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    if chunk:
                        f.write(chunk)
                        n += len(chunk)
            r.close()
            if n < MIN_BYTES:
                os.remove(tmp)
                return None, f"too small ({n} bytes, {ctype[:30]})"
            os.replace(tmp, dest)
            return {"bytes": n, "content_type": ctype}, None
        except Exception as e:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            if attempt == tries - 1:
                return None, f"{type(e).__name__}: {str(e)[:80]}"
            time.sleep(1.5 * (attempt + 1))
    return None, "exhausted retries"


def name_from_url(sid, url):
    """A stable local filename for an asset the export never declared."""
    base = urllib.parse.unquote(url.split("?")[0].rsplit("/", 1)[-1])
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-") or "asset"
    return f"{sid}-extra-{hashlib.sha1(url.encode()).hexdigest()[:10]}-{base}"


# Characters Windows refuses in a filename. Some export filenames carry the
# source query string — "UNCRC-vrs-ACC.pdf?sequence=1&isallowed=y" — which is a
# legal SharePoint URL but an illegal path, and open() fails with
# OSError errno 22 rather than anything that names the cause.
ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(filename):
    """The on-disk name for a declared file. Reversible enough to match back:
    only the query string and illegal characters change."""
    name = filename.split("?")[0]
    name = ILLEGAL.sub("-", name).rstrip(". ")
    return name[:180] or "asset"


def plan(cache, ids, include_extras=True):
    """(filename, url, [(sharepoint_id, role)]) — one entry per distinct file.

    Covers three sources, because the export's media list is not the whole set:
      by_role                declared media (banner/medium/thumbnail/video/richtext)
      unmatched_page_images  content images on the page with no export record
      extra_files            hosted video and linked documents found on the page
    """
    jobs = {}

    def add(fn, url, sid, role):
        if not url or not fn:
            return
        j = jobs.setdefault(fn, {"url": url, "refs": [], "role": role})
        j["refs"].append((sid, role))
        # prefer a source_key URL: it is exact, not inferred from a page
        if role == "declared" and j.get("source") != "source_key":
            j["url"] = url

    for sid in ids:
        e = cache.get(sid) or {}
        for role, lst in (e.get("by_role") or {}).items():
            for x in lst:
                add(x.get("filename"), x.get("url"), sid, role)
        if not include_extras:
            continue
        for u in (e.get("unmatched_page_images") or []):
            add(name_from_url(sid, u), u, sid, "page-image")
        for u in (e.get("extra_files") or []):
            add(name_from_url(sid, u), u, sid, "page-file")
    return jobs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--ids")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--verify", action="store_true",
                    help="re-hash files already on disk and update the DB")
    a = ap.parse_args()

    if not os.path.exists(CACHE):
        sys.exit(f"no {CACHE} — run resolve_media_urls.py first")
    with open(CACHE, encoding="utf-8") as f:
        cache = json.load(f)

    if a.ids:
        ids = [x.strip() for x in a.ids.split(",")]
    elif a.sample:
        import db as tracking
        with tracking.connect() as c:
            c.execute("SET search_path TO migration, public")
            ids = [str(r[0]) for r in c.execute(
                "SELECT sharepoint_id FROM story WHERE is_sample").fetchall()]
    else:
        ids = list(cache.keys())

    jobs = plan(cache, ids)
    print(f"  {len(ids)} stories -> {len(jobs)} distinct files")

    todo, have = [], 0
    for fn, j in jobs.items():
        dest = os.path.join(MEDIA_DIR, safe_name(fn))
        if os.path.exists(dest) and os.path.getsize(dest) >= MIN_BYTES:
            have += 1
            continue
        todo.append((fn, j["url"], dest))
    if a.limit:
        todo = todo[:a.limit]
    print(f"  {have} already on disk, {len(todo)} to download")

    ok, failed, done = [], [], [0]

    def work(item):
        fn, url, dest = item
        meta, err = fetch(url, dest)
        with _lock:
            done[0] += 1
            if meta:
                ok.append((fn, dest, meta))
            else:
                failed.append((fn, url, err))
                print(f"    !! {fn}: {err}")
            if done[0] % 25 == 0 or len(todo) <= 25:
                print(f"    [{done[0]}/{len(todo)}] "
                      f"{len(ok)} ok, {len(failed)} failed")

    if todo:
        with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
            list(ex.map(work, todo))

    # ---- record everything on disk in the tracking DB
    updated = 0
    try:
        import db as tracking
        rows = []
        for fn, j in jobs.items():
            dest = os.path.join(MEDIA_DIR, safe_name(fn))
            if not (os.path.exists(dest) and os.path.getsize(dest) >= MIN_BYTES):
                continue
            digest = sha256_of(dest) if (a.verify or fn in
                                         {o[0] for o in ok}) else None
            for sid, role in j["refs"]:
                if role in ("page-image", "page-file"):
                    continue        # no asset row exists for undeclared extras
                rows.append((dest, os.path.getsize(dest), digest,
                             int(sid), role, fn))
        with tracking.connect() as c:
            c.execute("SET search_path TO migration, public")
            with c.cursor() as cur:
                cur.executemany("""
                    UPDATE asset
                       SET source_path = %s, bytes = %s,
                           sha256 = COALESCE(%s, sha256),
                           exists_on_disk = true,
                           status = CASE WHEN status IN ('uploaded','reused')
                                         THEN status ELSE 'pending' END,
                           error = NULL
                     WHERE sharepoint_id = %s AND role = %s
                       AND source_filename = %s
                """, rows)
                updated = cur.rowcount
            c.commit()
    except Exception as e:
        print(f"  (tracking DB not updated: {type(e).__name__}: {e})")

    on_disk = sum(1 for fn in jobs
                  if os.path.exists(os.path.join(MEDIA_DIR, safe_name(fn))))
    total_bytes = sum(os.path.getsize(os.path.join(MEDIA_DIR, safe_name(fn)))
                      for fn in jobs
                      if os.path.exists(os.path.join(MEDIA_DIR, safe_name(fn))))

    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump({"stories": len(ids), "distinct_files": len(jobs),
                   "on_disk": on_disk, "downloaded_now": len(ok),
                   "failed": [{"filename": f_, "url": u, "error": e}
                              for f_, u, e in failed],
                   "bytes": total_bytes, "media_dir": MEDIA_DIR},
                  f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 62}")
    print(f"  distinct files   : {len(jobs)}")
    print(f"  on disk now      : {on_disk}  ({total_bytes / 1024 / 1024:.1f} MB)")
    print(f"  downloaded now   : {len(ok)}")
    print(f"  failed           : {len(failed)}")
    print(f"  DB rows updated  : {updated}")
    print(f"  media dir        : {MEDIA_DIR}")
    print(f"  report           : {REPORT}")
    if failed:
        from collections import Counter
        print("\n  failure reasons:")
        for k, n in Counter(e.split(":")[0] for _, _, e in failed).most_common():
            print(f"    {n:>5}  {k}")


if __name__ == "__main__":
    main()
