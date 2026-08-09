#!/usr/bin/env python3
"""
guess_media_variants.py — recover medium/thumbnail images by name pattern.

Why this is needed. The live news page renders ONE content image, but the export
often declares two or three files (banner + medium + thumbnail). So 284 records
have no URL — not because the extractor missed them, but because the page never
showed them.

The names, however, are paired. Story 1177 is CapBanner.jpg and CapMed.jpg;
story 35's banner is "...-large-image.jpg". So when the banner resolved and the
medium did not, the medium's URL can be guessed from the banner's — and then
verified by fetching it. A guess that 404s is discarded, so nothing is invented.

Usage:
    python scripts/migrate/download/guess_media_variants.py            # report only
    python scripts/migrate/download/guess_media_variants.py --limit 40 # sample first
    python scripts/migrate/download/guess_media_variants.py --apply    # write to cache
"""

import argparse
import concurrent.futures as cf
import json
import os
import re
import sys
import threading
import urllib.parse

try:
    import requests
except ImportError:
    sys.exit("pip install -r requirements.txt")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import BASE  # noqa: E402

# Paths come from the shared module so this script works for any content
# type; see pipeline/paths_root.py.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from paths_root import P  # noqa: E402
CACHE = os.path.join(P.MIGRATE, "media_urls.json")
OUT = os.path.join(P.MIGRATE, "variant_guesses.json")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# (pattern, replacement) applied to the filename of an already-resolved sibling.
# Most likely first; every hit is verified before it is accepted.
#   Fiona-large.jpg                            -> Fiona-small.jpg
#   Geneva-...-Award---Banner_cropped.jpg      -> ...---Medium_cropped.jpg
#   SDG large image.jpg                        -> SDG Medium image.jpg
# The separator varies (space, %20, -, _) and the case varies, so each token
# swap is tried in several spellings. Applied case-insensitively.
_MED_WORDS = ["Med", "Medium", "Small", "small", "medium", "med"]
_THUMB_WORDS = ["Thumb", "Thumbnail", "thumb", "thumbnail", "Small", "small"]


def _swaps(words):
    out = []
    for w in words:
        for token in ("Banner", "banner", "BANNER", "Large", "large", "LARGE",
                      "lead", "Lead", "big", "Big"):
            out.append((token, w))
    return out


SUBS = {"medium": _swaps(_MED_WORDS), "thumbnail": _swaps(_THUMB_WORDS)}

_lock = threading.Lock()


def variants(url, role):
    head, _, fname = url.rpartition("/")
    out = []
    for pat, rep in SUBS.get(role, []):
        new = re.sub(pat, rep, fname)
        if new != fname:
            cand = f"{head}/{new}"
            if cand not in out:
                out.append(cand)
    # try the other common extensions too
    extra = []
    for c in out:
        stem, dot, ext = c.rpartition(".")
        if dot and ext.lower() in ("jpg", "jpeg", "png"):
            for alt in ("jpg", "jpeg", "png"):
                if alt != ext.lower():
                    cand = f"{stem}.{alt}"
                    if cand not in out and cand not in extra:
                        extra.append(cand)
    return out + extra


def check(url):
    try:
        r = requests.get(url, headers=UA, timeout=25, stream=True)
        ok = (r.status_code == 200
              and "image" in r.headers.get("Content-Type", "")
              and int(r.headers.get("Content-Length") or 1000) > 500)
        r.close()
        return ok
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    with open(CACHE, encoding="utf-8") as f:
        cache = json.load(f)

    jobs = []
    for sid, e in cache.items():
        roles = e.get("by_role") or {}
        known = [x["url"] for lst in roles.values() for x in lst if x.get("url")]
        if not known:
            continue
        for role in ("medium", "thumbnail"):
            for i, x in enumerate(roles.get(role, [])):
                if x.get("url"):
                    continue
                for src in known:
                    cands = variants(src, role)
                    if cands:
                        jobs.append((sid, role, i, src, cands))
                        break
    if a.limit:
        jobs = jobs[:a.limit]
    print(f"  {len(jobs)} unresolved medium/thumbnail records have a sibling "
          f"URL to guess from")
    if not jobs:
        return

    found, tried = [], [0]

    def work(job):
        sid, role, i, src, cands = job
        for c in cands:
            if check(c):
                with _lock:
                    found.append({"sharepoint_id": sid, "role": role,
                                  "index": i, "from": src, "url": c})
                    print(f"    HIT  {sid} {role}: "
                          f"{urllib.parse.unquote(c)[-58:]}")
                return
        with _lock:
            tried[0] += 1
            if tried[0] % 25 == 0:
                print(f"    ... {tried[0]} misses, {len(found)} hits")

    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        list(ex.map(work, jobs))

    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"attempted": len(jobs), "found": found}, f, indent=2,
                  ensure_ascii=False)

    print(f"\n{'=' * 62}")
    print(f"  attempted : {len(jobs)}")
    print(f"  recovered : {len(found)}")
    print(f"  -> {OUT}")

    if a.apply and found:
        for hit in found:
            lst = ((cache.get(hit["sharepoint_id"]) or {})
                   .get("by_role") or {}).get(hit["role"]) or []
            if hit["index"] < len(lst) and not lst[hit["index"]].get("url"):
                lst[hit["index"]]["url"] = hit["url"]
                lst[hit["index"]]["source"] = "name-variant"
        with open(CACHE, "w", encoding="utf-8", newline="\n") as f:
            json.dump(cache, f, ensure_ascii=False)
        print(f"  applied {len(found)} URLs to the cache")
        print("  next: python scripts/migrate/download/download_media.py")


if __name__ == "__main__":
    main()
