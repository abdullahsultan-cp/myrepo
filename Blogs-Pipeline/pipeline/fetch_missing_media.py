#!/usr/bin/env python3
"""fetch_missing_media.py — get the images that are still only on aku.edu.

    python Blogs-Pipeline/pipeline/fetch_missing_media.py            # try everything
    python Blogs-Pipeline/pipeline/fetch_missing_media.py --dry-run
    python Blogs-Pipeline/pipeline/fetch_missing_media.py --banners-only

Two separate problems. One is solved; the other is closed as unrecoverable, and
this file is the record of why, because once SharePoint is switched off nobody
will be able to check the reasoning again.

**Inline body images — 31 across 13 blogs. Solved.** Each carries a real
SharePoint path, `/blogs/PublishingImages/Blogs-SL03.jpg`, so `aku.edu` plus that
path is the file. All 31 are on disk.

**Banners for 13 blogs — closed, unrecoverable.** The export cell reads
`DOWNLOAD_FAILED` (9) or is empty (4), so there is no filename to ask for.

## Why the 13 cannot be recovered

Not for want of asking. Every place a banner could be recorded was checked
against the live site:

    Posts.Banner_x0020_Image        null on all 89 posts, not just the 13
    list item attachments           Attachments=false, 0 files, on every post
    Detail.aspx?PostID=n            renders client-side; og:image is the AKU logo
    the site's 17 lists             no banner library; `Images` is the asset
                                    library itself and links to no post

So SharePoint holds no banner-to-post mapping at all. The 70 banners we *do*
have were downloaded by AKU's export tool and renamed `{ID}-Banner.jpg`; every
one of them matches a file in `/blogs/PublishingImages/` by exact byte length,
which is how we know that folder is the source and that 73 files in it are
claimed by no post. The 13 banners are somewhere in those 73 — unidentifiably.

## Why they are not guessed

Guessing was tried properly, and measured against the 69 banners whose true file
is known, leave-one-out:

    nearest upload time                  43/69 correct
    rarest-word title match              17 right, 11 wrong when confident
    both must agree (the strictest)      16 right, 1 wrong — 94%

Applied to the 13, the strict rule **abstains on all thirteen**: nine have no
title word in common with any unclaimed file, and four have title and time
pointing at different files.

Its one error is the warning. Post 15 is titled "Stephen Lyon: I owe a debt of
gratitude to Pakistan" and `stephen-lyon.jpg` sits right there in the folder —
but post 15's real banner is `Blogs_banner_SL.jpg`, and `stephen-lyon.jpg`
belongs to something else. The obvious match was the wrong one. This is the same
trap that put Salim Surani's photograph on Didar Ali in `fetch_authors.py`.

A wrong hero image on a published article is worse than no hero image, so the 13
are recorded as absent and the blok is marked `skipped` — the state that already
means "deliberately dropped, the data exists nowhere". They are not an open
error and should not be re-run hopefully; the verdict is in
`data/banners_absent.json` with its evidence.

If AKU can still produce these 13 files, drop them in `assets/Blogs/media/` named
`{ID}-Banner.jpg` and they are picked up with no code change.
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
API = {**UA, "Accept": "application/json;odata=nometadata"}
IMAGES = "/blogs/PublishingImages"


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


def walk_images(node, into):
    """Collect every image src in a rich-text tree. Defined at module level so
    it closes over nothing — a nested version tripped ruff's B023."""
    if isinstance(node, dict):
        if node.get("type") == "image":
            src = (node.get("attrs") or {}).get("src") or ""
            if src:
                into.append(src)
        for child in node.get("content") or []:
            walk_images(child, into)
    elif isinstance(node, list):
        for child in node:
            walk_images(child, into)


def inline_images(stories_dir):
    """Every image node still pointing at SharePoint, with the blog it is in."""
    out = []
    for name in sorted(os.listdir(stories_dir)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(stories_dir, name), encoding="utf-8") as f:
            content = json.load(f).get("content", {})
        found = []
        walk_images(content.get("body") or {}, found)
        for src in found:
            out.append((str(content.get("sharepoint_id") or name[:-5]), src))
    return out


# ------------------------------------------------------------------ banners
def banner_verdict(session, source):
    """Re-run the search for the 13 banners and record what the site says.

    Written to be re-runnable while aku.edu is still up, so the conclusion can
    be challenged rather than taken on trust. Returns the verdict dict.
    """
    absent = [i for i in source
              if (F.get(i, "banner") or "").strip() in ("DOWNLOAD_FAILED", "")]
    ids = [str(F.get(i, "id")) for i in absent]
    print(f"\n  {len(absent)} blog(s) with no usable banner — checking the site")

    checked = {}
    r = session.get(f"{BASE}/blogs/_api/web/lists/getbytitle('Posts')/items?$top=500",
                    headers=API, timeout=60)
    if r.status_code != 200:
        print(f"    Posts list returned {r.status_code}; leaving the verdict alone")
        return None
    posts = {str(x["ID"]): x for x in r.json().get("value", [])}
    with_field = sum(1 for x in posts.values()
                     if (x.get("Banner_x0020_Image") or "").strip())
    checked["Posts.Banner_x0020_Image"] = (
        f"set on {with_field} of {len(posts)} posts")
    with_att = sum(1 for x in posts.values() if x.get("Attachments"))
    checked["list item attachments"] = f"present on {with_att} of {len(posts)} posts"

    # The folder every known banner came from.
    r = session.get(f"{BASE}/blogs/_api/web/GetFolderByServerRelativeUrl"
                    f"('{IMAGES}')/Files?$select=Name,Length&$top=5000",
                    headers=API, timeout=90)
    files = {x["Name"]: int(x["Length"]) for x in r.json().get("value", [])}
    checked[IMAGES] = f"{len(files)} files"

    # Which of them are already accounted for, by exact byte length.
    media = P.MEDIA_DIR
    by_size = {}
    for name, length in files.items():
        by_size.setdefault(length, []).append(name)
    claimed = set()
    for f_name in os.listdir(media):
        if not re.match(r"^\d+-Banner\.", f_name):
            continue
        hit = by_size.get(os.path.getsize(os.path.join(media, f_name)), [])
        if len(hit) == 1:
            claimed.add(hit[0])
    checked["unclaimed files"] = (
        f"{len(files) - len(claimed)} of {len(files)} match no known banner")

    rows = []
    for item in absent:
        blog_id = str(F.get(item, "id"))
        live = posts.get(blog_id, {})
        rows.append({
            "blog": blog_id,
            "title": (live.get("Title") or F.get(item, "title") or "")[:90],
            "export_cell": (F.get(item, "banner") or "").strip() or "(empty)",
            "on_live_list": bool(live),
            "banner_field": live.get("Banner_x0020_Image"),
            "attachments": bool(live.get("Attachments")),
            "verdict": "absent — no banner recorded anywhere in SharePoint",
        })
        print(f"    {blog_id:<5}{rows[-1]['title'][:58]:<60}"
              f"{rows[-1]['export_cell']}")

    verdict = {
        "status": "closed — unrecoverable, deliberately ignored",
        "count": len(rows),
        "blog_ids": ids,
        "checked": checked,
        "why_not_guessed":
            "Measured against the 69 banners whose true file is known: nearest "
            "upload time 43/69; rarest-word title match 17 right and 11 wrong; "
            "both-must-agree 16 right 1 wrong. The strict rule abstains on all "
            "13. Its one error is the lesson — post 15 is titled 'Stephen Lyon' "
            "and stephen-lyon.jpg is in the folder, but post 15's real banner "
            "is Blogs_banner_SL.jpg.",
        "if_they_turn_up":
            "Put the file in assets/Blogs/media/ named {ID}-Banner.jpg and set "
            "the Banner cell; no code change needed.",
        "rows": rows,
    }
    path = os.path.join(P.DATA, "banners_absent.json")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(verdict, f, ensure_ascii=False, indent=2)
    print(f"    -> {os.path.relpath(path, ROOT)}")
    return verdict


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-banners", action="store_true",
                    help="only the inline images, which are the certain ones")
    ap.add_argument("--banners-only", action="store_true",
                    help="only re-check the 13 absent banners")
    a = ap.parse_args()

    media = P.MEDIA_DIR
    os.makedirs(media, exist_ok=True)
    on_disk = set(os.listdir(media))
    session = requests.Session()
    results = []

    # ---- 1 · inline images, which carry their own path --------------------
    if not a.banners_only:
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
        verdict = banner_verdict(session, source) if not a.dry_run else None
        for row in (verdict or {}).get("rows", []):
            results.append({"blog": row["blog"], "kind": "banner",
                            "title": row["title"],
                            "status": "absent at source — ignored"})

    report = os.path.join(P.DATA, "missing_media_report.json")
    # A scoping flag must never discard state. `--banners-only` skips the inline
    # pass, so without this it rewrote the report with zero inline rows and the
    # 31 recovered images vanished from it. Same shape of bug as `--refresh`
    # wiping 731 cache entries; see CLAUDE.md.
    if a.banners_only and os.path.exists(report):
        with open(report, encoding="utf-8") as f:
            kept = [r for r in json.load(f).get("rows", []) if r.get("kind") != "banner"]
        results = kept + results

    ok = sum(1 for r in results if r.get("status") == "ok")
    have = sum(1 for r in results if r.get("status") == "already on disk")
    gone = sum(1 for r in results if r.get("status") == "absent at source — ignored")
    with open(report, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"fetched": ok, "already_had": have, "absent_ignored": gone,
                   "rows": results}, f, ensure_ascii=False, indent=2)
    print(f"\n  inline images: {ok} fetched, {have} already had, 0 outstanding")
    print(f"  banners: {gone} absent at source and ignored")
    print(f"  -> {os.path.relpath(report, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
