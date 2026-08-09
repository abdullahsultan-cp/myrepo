#!/usr/bin/env python3
"""
resolve_media_urls.py — find the live SharePoint URL for every image.

The export renamed media on the way out (2198-BannerImage.jpg), so the local
filename says nothing about where the file lives on aku.edu. Two cases:

  rich-text images   carry source_key, and https://www.aku.edu{source_key}
                     resolves directly — no network needed to build the URL
  banner / medium    have no source_key and the real name is unguessable
                     (2198-BannerImage.jpg is really /news/PublishingImages/
                     CapBanner.jpg), so the story page has to be read

So this fetches each SharePoint news page once, pulls the content images out of
the chrome, and caches the result. Resumable: already-cached stories are skipped,
so it can be interrupted and re-run.

Read-only. GET requests against the public site.

Usage:
    python scripts/migrate/download/resolve_media_urls.py            # every story
    python scripts/migrate/download/resolve_media_urls.py --ids 2198,1177
    python scripts/migrate/download/resolve_media_urls.py --sample   # the 20-story sample
    python scripts/migrate/download/resolve_media_urls.py --workers 6 --verify

Output: data/migrate/media_urls.json
    {"<sharepoint_id>": {"page": url, "images": [...], "iframes": [...],
                         "by_role": {...}, "fetched": true}}
"""

import argparse
import concurrent.futures as cf
import json
import os
import re
import sys
import threading
import time
import urllib.parse

try:
    import requests
except ImportError:
    sys.exit("pip install -r requirements.txt")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _bootstrap  # noqa: F401,E402  -- paths_root now lives in pipeline/core/
from paths import BASE  # noqa: E402

# Paths come from the shared module so this script works for any content
# type; see pipeline/paths_root.py.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from paths_root import P  # noqa: E402
STORIES = P.STORIES
OUT = os.path.join(P.MIGRATE, "media_urls.json")

SP = "https://www.aku.edu"
PAGE = SP + "/news/Pages/news_details.aspx?nid={nid}"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# Site furniture that appears on every page and is never article content.
# Matched against URL-ENCODED paths, so "Style Library" arrives as
# "Style%20Library" — a naive [%\s]* class silently lets AKU_logo.gif through
# and it ends up assigned as a story's banner. Keep these tolerant of %XX.
CHROME = re.compile(
    r"_layouts|_catalogs|SiteCollectionImages|favicon|nodearrow|spcommon"
    r"|searchresultui|themedpng|/_vti_|blank\.gif|spacer\.gif"
    r"|Style(?:%20|[\s_])*Library"
    r"|AKU[_%\d]*logo"
    r"|InternetSlowdown_Day"
    r"|/SiteAssets/", re.I)
# NOT in CHROME: "/Pages/". It was added to skip .aspx links, but many real
# banner images live under /news/PublishingImages/pages/News_Admin/... and
# /pages/Environment/..., so the pattern was silently deleting content images
# and left 165 stories looking like they had none. Anchors are filtered by
# extension instead (ASSET_EXT below), which is what that rule was actually for.

IMG_RE = re.compile(r"<img[^>]+src=([\"'])(.*?)\1", re.I)
IFRAME_RE = re.compile(r"<iframe[^>]+src=([\"'])(.*?)\1", re.I)
# <video src>, <source src>, and <object data> — hosted video lives in these,
# never in an <img>, which is why video1 roles never resolved.
VIDEO_RE = re.compile(
    r"<(?:video|source|embed)[^>]+src=([\"'])(.*?)\1"
    r"|<object[^>]+data=([\"'])(.*?)\3", re.I)
# any anchor pointing at a downloadable file: PDFs, Word docs, mp4s
HREF_RE = re.compile(r"<a[^>]+href=([\"'])(.*?)\1", re.I)
ASSET_EXT = re.compile(
    r"\.(jpe?g|png|gif|webp|bmp|tiff?|svg"
    r"|pdf|docx?|xlsx?|pptx?|zip|rtf"
    r"|mp4|mov|m4v|webm|avi|wmv|mp3|wav)(\?|$)", re.I)
# The article body sits inside this publishing field on AKU's template.
BODY_RE = re.compile(
    r"(<div[^>]+class=\"[^\"]*ExternalClass[^\"]*\".*?)(?=<div[^>]+id=\"aku-)",
    re.S | re.I)

_lock = threading.Lock()


def quote(u):
    return urllib.parse.quote(u, safe="/:?=&%#")


def absolute(src):
    s = (src or "").replace("&#58;", ":").replace("&amp;", "&").strip()
    if not s:
        return ""
    if s.startswith("//"):
        return "https:" + s
    if s.startswith("http"):
        return s
    if s.startswith("/"):
        return SP + s
    return f"{SP}/news/{s}"


def is_youtube(u):
    return "youtube.com" in u or "youtu.be" in u


def scrape(nid, tries=3):
    """Fetch one story page.

    SharePoint times out under concurrency rather than refusing: every failure
    seen so far is a ReadTimeout, never a 404. Retrying with backoff clears them
    in the same pass instead of needing another run.
    """
    url = PAGE.format(nid=nid)
    last = None
    for attempt in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=45)
            break
        except (requests.Timeout, requests.ConnectionError) as e:
            last = e
            if attempt == tries - 1:
                raise
            time.sleep(1.5 * (attempt + 1))
    if r.status_code != 200:
        return {"page": url, "http": r.status_code, "images": [], "iframes": [],
                "fetched": False}
    html = r.text
    body = BODY_RE.search(html)
    scope = body.group(1) if body else html

    images, seen = [], set()
    for _, src in IMG_RE.findall(scope):
        u = absolute(src)
        if not u or CHROME.search(u) or u in seen:
            continue
        seen.add(u)
        images.append(quote(u))

    iframes = []
    for _, src in IFRAME_RE.findall(html):
        u = absolute(src)
        # facebook/twitter SDK frames are chrome, not content
        if not u or "facebook.com" in u or "platform.twitter" in u:
            continue
        if u not in iframes:
            iframes.append(u)

    # hosted video: <video>/<source>/<embed>/<object>, never <img>
    videos = []
    for m in VIDEO_RE.finditer(scope):
        u = absolute(m.group(2) or m.group(4))
        if u and not CHROME.search(u) and u not in videos:
            videos.append(quote(u))

    # downloadable files linked from the body, on our own host only
    files = []
    for _, href in HREF_RE.findall(scope):
        u = absolute(href)
        if not u or CHROME.search(u) or not ASSET_EXT.search(u):
            continue
        # an editor pasted local Windows paths into a few hrefs; skip those
        if re.search(r"[A-Za-z]:[/\\]|file://", u):
            continue
        if "aku.edu" not in u:
            continue                      # someone else's file, link not host
        if u not in files:
            files.append(quote(u))

    return {"page": url, "http": 200, "images": images, "iframes": iframes,
            "videos": videos, "page_files": files, "fetched": True}


def local_roles(sid):
    """role -> source_key-derived URL, for the media that needs no scraping."""
    p = os.path.join(STORIES, f"{sid}.json")
    if not os.path.exists(p):
        return {}, []
    with open(p, encoding="utf-8") as f:
        c = (json.load(f).get("content") or {})
    by_role, need = {}, []
    # media[] and richtext_media[] overlap: a rich-text asset is listed in both,
    # so dedupe on filename or every inline image is reported twice.
    seen_files = set()
    for m in (c.get("media") or []) + (c.get("richtext_media") or []):
        role = m.get("role") or "richtext"
        fname = m.get("filename") or m.get("local_filename") or ""
        if fname and fname in seen_files:
            continue
        seen_files.add(fname)
        sk = m.get("source_key")
        entry = {"filename": m.get("filename") or m.get("local_filename") or "",
                 "media_type": m.get("media_type"),
                 "caption": m.get("caption") or "",
                 "alt": m.get("alt") or ""}
        if sk:
            # A few source_keys are already absolute URLs; prefixing the host
            # produced "www.aku.eduhttp://..." and a ConnectionError.
            entry["url"] = quote(sk if sk.lower().startswith(("http://",
                                                              "https://"))
                                 else SP + sk)
            entry["source"] = "source_key"
        else:
            entry["url"] = ""
            entry["source"] = "needs-page-scrape"
            need.append(role)
        by_role.setdefault(role, []).append(entry)
    return by_role, need


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids")
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--priority", choices=["with-media", "rich", "recent"],
                    help="do the interesting stories first: with-media = has "
                         "any media at all; rich = 3+ media or an embed; "
                         "recent = newest first")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--refresh", action="store_true",
                    help="re-fetch pages already cached")
    ap.add_argument("--verify", action="store_true",
                    help="GET each resolved image to confirm it loads")
    a = ap.parse_args()

    # Always load the cache. --refresh means "re-fetch the stories I named", not
    # "throw away everything already resolved": skipping the load here once wiped
    # 731 resolved entries, because the run then saved only the 20 it touched.
    cache = {}
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            cache = json.load(f)
        print(f"  cache has {len(cache)} stories"
              + ("  (--refresh: re-fetching the requested ones)"
                 if a.refresh else ""))

    ids = []
    if a.ids:
        ids = [x.strip() for x in a.ids.split(",")]
    elif a.sample:
        import db as tracking
        with tracking.connect() as c:
            c.execute("SET search_path TO migration, public")
            ids = [str(r[0]) for r in c.execute(
                "SELECT sharepoint_id FROM story WHERE is_sample "
                "ORDER BY sharepoint_id").fetchall()]
    else:
        ids = sorted((n[:-5] for n in os.listdir(STORIES)
                      if n.endswith(".json")), key=int)

    if a.priority:
        # Rank so the stories worth reviewing resolve first. A story with no
        # media has nothing to resolve, so leaving it for last costs nothing.
        def rank(sid):
            p = os.path.join(STORIES, f"{sid}.json")
            try:
                with open(p, encoding="utf-8") as f:
                    c = json.load(f).get("content") or {}
            except Exception:
                return (9, "")
            media = (c.get("media") or []) + (c.get("richtext_media") or [])
            n = len(media)
            has_embed = "video_embed" in json.dumps(c.get("body") or {}) \
                or bool(c.get("pull_quote"))
            date = (c.get("schedule_start_date") or "")[:10]
            if a.priority == "with-media":
                return (0 if n else 1, "" if n else date)
            if a.priority == "rich":
                return (0 if (n >= 3 or has_embed) else (1 if n else 2), date)
            return (0, date)                      # recent
        ids = sorted(ids, key=rank)
        if a.priority == "with-media":
            keep = [s for s in ids if rank(s)[0] == 0]
            print(f"  priority 'with-media': {len(keep)} of {len(ids)} "
                  f"stories have media")
            ids = keep

    # sequence number per story, needed for the page URL
    seqs = {}
    for sid in ids:
        p = os.path.join(STORIES, f"{sid}.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                seqs[sid] = ((json.load(f).get("content") or {})
                             .get("sequence_number") or "")

    todo = [s for s in ids
            if (a.refresh or not cache.get(s, {}).get("fetched"))
            and seqs.get(s)]
    if a.limit:
        todo = todo[:a.limit]
    print(f"  {len(ids)} stories requested, {len(todo)} need a page fetch")

    done = [0]

    def work(sid):
        try:
            res = scrape(seqs[sid].upper())
        except Exception as e:
            res = {"page": PAGE.format(nid=seqs[sid].upper()),
                   "http": type(e).__name__, "images": [], "iframes": [],
                   "fetched": False}
        with _lock:
            cache[sid] = {**cache.get(sid, {}), **res}
            done[0] += 1
            if done[0] % 25 == 0 or len(todo) < 25:
                n_img = len(res.get("images") or [])
                print(f"    [{done[0]}/{len(todo)}] {sid} "
                      f"http={res.get('http')} images={n_img}")
            if done[0] % 200 == 0:
                with open(OUT, "w", encoding="utf-8", newline="\n") as f:
                    json.dump(cache, f, ensure_ascii=False)

    if todo:
        with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
            list(ex.map(work, todo))

    # merge in the source_key-derived URLs and assign scraped images to roles
    for sid in ids:
        by_role, need = local_roles(sid)
        entry = cache.setdefault(sid, {"images": [], "iframes": [],
                                       "fetched": False})
        # Re-apply the chrome filter here as well as at scrape time, so a cache
        # built by an older, leakier pattern is cleaned without re-fetching
        # 3606 pages.
        scraped = [u for u in (entry.get("images") or [])
                   if not CHROME.search(u)]
        entry["images"] = scraped
        used = {e["url"] for lst in by_role.values() for e in lst if e["url"]}
        spare = [u for u in scraped if u not in used]
        # banner first, then medium: the template renders them in that order
        for role in ("banner", "medium", "thumbnail"):
            for e in by_role.get(role, []):
                if not e["url"] and spare:
                    e["url"] = spare.pop(0)
                    e["source"] = "page-scrape"

        # One image can serve two roles. Story 2027's single page image is both
        # its banner and its inline rich-text image; because the rich-text record
        # claimed it via source_key it landed in `used`, so `spare` was empty and
        # the banner stayed blank even though the image was right there.
        if len(scraped) == 1:
            for e in by_role.get("banner", []):
                if not e["url"]:
                    e["url"] = scraped[0]
                    e["source"] = "page-scrape-shared"

        # hosted video comes from <video>/<source>, so it never appeared in the
        # image list — this is why every video1 role stayed unresolved.
        vids = [u for u in (entry.get("videos") or []) if u not in used]
        for role, lst in by_role.items():
            if not str(role).startswith("video"):
                continue
            for e in lst:
                if not e["url"] and vids:
                    e["url"] = vids.pop(0)
                    e["source"] = "page-video"

        entry["by_role"] = by_role
        entry["unmatched_page_images"] = spare
        # everything else on the page worth keeping: leftover video sources and
        # linked documents that no export record claims
        entry["extra_files"] = sorted(set(vids) | set(entry.get("page_files")
                                                      or []) - used)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(cache, f, ensure_ascii=False)

    resolved = sum(1 for s in ids for lst in
                   (cache[s].get("by_role") or {}).values() for e in lst
                   if e.get("url"))
    total = sum(1 for s in ids for lst in
                (cache[s].get("by_role") or {}).values() for _ in lst)
    pages_ok = sum(1 for s in ids if cache.get(s, {}).get("http") == 200)
    print(f"\n  pages fetched OK : {pages_ok}/{len(ids)}")
    print(f"  media resolved   : {resolved}/{total}")
    print(f"  -> {OUT}")

    if a.verify:
        import collections
        codes = collections.Counter()
        urls = {e["url"] for s in ids
                for lst in (cache[s].get("by_role") or {}).values()
                for e in lst if e.get("url")}
        print(f"\n  verifying {len(urls)} image URLs")
        def chk(u):
            try:
                r = requests.get(u, headers=UA, timeout=20, stream=True)
                ok = r.status_code == 200 and "image" in r.headers.get(
                    "Content-Type", "")
                r.close()
                return "ok" if ok else f"{r.status_code}"
            except Exception as e:
                return type(e).__name__
        with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
            for res in ex.map(chk, list(urls)):
                codes[res] += 1
        for k, v in codes.most_common():
            print(f"    {v:>6}  {k}")


if __name__ == "__main__":
    main()
