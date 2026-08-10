#!/usr/bin/env python3
"""fetch_missing_media.py — get the images that are still only on aku.edu.

    python Blogs-Pipeline/pipeline/fetch_missing_media.py            # try everything
    python Blogs-Pipeline/pipeline/fetch_missing_media.py --dry-run

Two separate problems, and only one of them is easy.

**Inline body images (31 across 13 blogs).** Each carries a real SharePoint path
-- `/blogs/PublishingImages/Blogs-SL03.jpg` -- so `https://www.aku.edu` plus that
path is the file. Straightforward.

**Banners the export never captured (9 blogs).** The cell reads the literal
string `DOWNLOAD_FAILED`, so there is no filename to ask for. The only route is
to open the blog's own page on aku.edu and read the hero image out of it, which
is what news had to do for all 3,606.

Anything that 404s is recorded and left alone. The site is being retired and
some of this was already gone before we started; a missing file is a fact to
report, not something to keep retrying.

Everything lands in `Blogs-Pipeline/assets/Blogs/media/` beside the banners we
already have, and `data/missing_media_report.json` says what happened to each.
"""

import argparse
import json
import os
import re
import sys
import time
from urllib.parse import unquote, urlparse

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "pipeline"))
import _bootstrap

_bootstrap.ensure()

from fields import F
from paths_root import ROOT, P

P.use("blogs")

BASE = "https://www.aku.edu"
UA = {"User-Agent": "Mozilla/5.0 (compatible; AKU-migration/1.0)"}
# The blog list pages, in the order most likely to carry a given post.
LIST_PAGES = ["/blogs/Pages/default.aspx", "/blogs"]


def safe_name(url):
    """A filename Windows will accept, from a URL that may carry a query."""
    name = os.path.basename(unquote(urlparse(url).path))
    return re.sub(r'[<>:"/\\|?*]', "_", name) or "unnamed"


def fetch(session, url, dest, tries=3):
    for attempt in range(tries):
        try:
            r = session.get(url, headers=UA, timeout=45)
            if r.status_code == 200 and r.content:
                with open(dest, "wb") as f:
                    f.write(r.content)
                return "ok", len(r.content)
            if r.status_code == 404:
                return "404", 0
            if attempt == tries - 1:
                return f"http {r.status_code}", 0
        except requests.RequestException as exc:
            if attempt == tries - 1:
                return type(exc).__name__, 0
        time.sleep(1.5 * (attempt + 1))
    return "failed", 0


def inline_images(stories_dir):
    """Every image node still pointing at SharePoint, with the blog it is in."""
    out = []
    for name in sorted(os.listdir(stories_dir)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(stories_dir, name), encoding="utf-8") as f:
            content = json.load(f).get("content", {})
        found = []

        def walk(node):
            if isinstance(node, dict):
                if node.get("type") == "image":
                    src = (node.get("attrs") or {}).get("src") or ""
                    if src:
                        found.append(src)
                for child in node.get("content") or []:
                    walk(child)

        walk(content.get("body") or {})
        for src in found:
            out.append((str(content.get("sharepoint_id") or name[:-5]), src))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-banners", action="store_true",
                    help="only the inline images, which are the certain ones")
    a = ap.parse_args()

    media = P.MEDIA_DIR
    os.makedirs(media, exist_ok=True)
    on_disk = set(os.listdir(media))
    session = requests.Session()

    results = []

    # ---- 1 · inline images, which carry their own path --------------------
    todo = inline_images(P.STORIES)
    print(f"  {len(todo)} inline image reference(s) across "
          f"{len({b for b, _ in todo})} blogs")
    seen = set()
    for blog_id, src in todo:
        url = src if src.lower().startswith("http") else BASE + src
        name = safe_name(url)
        row = {"blog": blog_id, "kind": "inline", "src": src, "url": url,
               "filename": name}
        if name in on_disk:
            row["status"] = "already on disk"
        elif url in seen:
            row["status"] = "duplicate of an earlier reference"
        elif a.dry_run:
            row["status"] = "would fetch"
        else:
            seen.add(url)
            status, size = fetch(session, url, os.path.join(media, name))
            row["status"], row["bytes"] = status, size
            if status == "ok":
                on_disk.add(name)
        results.append(row)
        print(f"    {row['status']:<28}{name[:44]:<46}{src[:44]}")

    # ---- 2 · banners the export never captured ----------------------------
    if not a.skip_banners:
        with open(P.SOURCE_JSON, encoding="utf-8") as f:
            source = json.load(f)
        failed = [i for i in source
                  if (F.get(i, "banner") or "").strip() in ("DOWNLOAD_FAILED", "")]
        print(f"\n  {len(failed)} blog(s) with no usable banner")
        for item in failed:
            blog_id = str(F.get(item, "id"))
            title = (F.get(item, "title") or "")[:52]
            row = {"blog": blog_id, "kind": "banner", "title": title,
                   "status": "no filename in the export — needs the live page"}
            # There is nothing to construct a URL from: the export recorded the
            # failure, not the name. Finding it means locating the post's own
            # page, and the blogs list has no detail-page pattern we have
            # confirmed. Recorded so the gap is countable rather than vague.
            results.append(row)
            print(f"    {blog_id:<6}{title}")

    report = os.path.join(P.DATA, "missing_media_report.json")
    ok = sum(1 for r in results if r.get("status") == "ok")
    gone = sum(1 for r in results if r.get("status") == "404")
    with open(report, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"fetched": ok, "gone": gone, "rows": results}, f,
                  ensure_ascii=False, indent=2)
    print(f"\n  fetched {ok}, gone {gone}")
    print(f"  -> {os.path.relpath(report, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
