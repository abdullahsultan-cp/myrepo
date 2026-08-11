#!/usr/bin/env python3
"""export_internal_links.py — every aku.edu link, in one sheet, to be replaced.

    python pipeline/migrate/review/export_internal_links.py
    -> data/internal_links.csv

Read-only. Writes a CSV and nothing else.

**SharePoint is being switched off, so every link into it dies.** Some can be
rerouted today — a news page whose story is already migrated, a document we can
upload. The rest point at pages that do not exist in Storyblok *yet*: faculty
profiles, section home pages, programme pages. Those are the Pages migration's
content and their destinations will exist later.

Nothing is dropped and nothing is guessed. Every link lands in this sheet with
what we know about it, so when a Storyblok page appears the row can be filled in
and the replacement run from `new_target`.

Columns:

    type              news | blogs
    sharepoint_id     the story the link is in
    story_slug        where that story lives in Storyblok
    link_text         the words the reader clicks
    href              the link exactly as authored
    kind              story | document | site page
    status            what can be done about it now
    suggested_target  filled in where we can already resolve it
    new_target        EMPTY — put the Storyblok path here and it gets used
    occurrences       how many times it appears

`new_target` is the column to fill in. It is deliberately last and deliberately
empty: the sheet is meant to be edited, and a column that is already populated
invites somebody to overwrite a correct value.
"""

import argparse
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_up = HERE
while _up != os.path.dirname(_up) and not os.path.exists(
        os.path.join(_up, "_bootstrap.py")):
    _up = os.path.dirname(_up)
sys.path.insert(0, _up)
import _bootstrap

_bootstrap.ensure()

from link_routing import classify, is_ours, rewrite_href
from paths_root import ROOT, P

COLUMNS = ["type", "sharepoint_id", "story_slug", "link_text", "href", "kind",
           "status", "suggested_target", "new_target", "occurrences"]


def live_story_slugs():
    """{slug: full_slug} read from the SPACE, never from the database.

    The database holds `upload_full_slug` as it was at upload time — the long
    form, `regions/pakistan/news/...`. **The dev has since renamed every folder
    to a short code**, so those are now `regions/pk/news/...`. Storyblok moved
    the stories with the folders, but the recorded paths did not move with them.

    Rewriting a link from the database would therefore point every one of them
    at a path that no longer exists — a link that looks correct, is not, and
    would be very hard to notice. Read live and take the slug the space
    actually serves.
    """
    import requests

    from storyblok_config import load_config
    cfg = load_config()
    base = f"https://mapi.storyblok.com/v1/spaces/{cfg['space_id']}"
    head = {"Authorization": cfg["management_token"]}
    out, page = {}, 1
    while True:
        r = requests.get(f"{base}/stories", headers=head, timeout=90,
                         params={"per_page": 100, "page": page,
                                 "story_only": 1})
        if r.status_code != 200:
            print(f"  could not read live slugs ({r.status_code}); "
                  f"story links will be left unresolved")
            return {}
        chunk = r.json().get("stories", [])
        for s in chunk:
            full = s.get("full_slug") or ""
            if full:
                out[full.rstrip("/").split("/")[-1].lower()] = full
        if len(chunk) < 100:
            print(f"  {len(out)} live story slug(s) read from the space")
            return out
        page += 1


def news_rows(story_slugs):
    """From the tracking database, which already catalogued every news link."""
    sys.path.insert(0, os.path.join(ROOT, "pipeline", "migrate"))
    try:
        import db
        with db.connect() as c:
            c.execute("SET search_path TO migration, public")
            rows = c.execute(
                "SELECT l.sharepoint_id, l.raw_href, l.link_text, "
                "       l.occurrences, s.upload_full_slug "
                "FROM link l LEFT JOIN story s USING (sharepoint_id)").fetchall()
    except Exception as exc:
        print(f"  news skipped — tracking database unavailable "
              f"({type(exc).__name__})")
        return []
    out = []
    for sid, href, text, occ, slug in rows:
        if not is_ours(href):
            continue
        kind, _ = classify(href)
        target, why = rewrite_href(href, story_slugs=story_slugs)
        out.append({
            "type": "news", "sharepoint_id": sid, "story_slug": slug or "",
            "link_text": (text or "").strip()[:120], "href": href, "kind": kind,
            "status": "ready — rerouted on upload" if target else why,
            "suggested_target": target or "", "new_target": "",
            "occurrences": occ or 1})
    return out


def blogs_rows():
    """Blogs are not uploaded yet, so the links come from the payloads."""
    P.use("blogs")
    if not os.path.isdir(P.STORIES):
        return []
    routing = {}
    rp = os.path.join(P.DATA, "taxonomy", "routing.csv")
    if os.path.exists(rp):
        with open(rp, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                routing[str(r["id"])] = r.get("target_full_slug", "")
    out = []
    for name in sorted(os.listdir(P.STORIES)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(P.STORIES, name), encoding="utf-8") as f:
            content = json.load(f).get("content", {})
        sid = str(content.get("sharepoint_id") or name[:-5])
        found = {}

        def walk(node, text_of):
            if isinstance(node, dict):
                for mark in node.get("marks") or []:
                    if mark.get("type") == "link":
                        href = (mark.get("attrs") or {}).get("href") or ""
                        if is_ours(href):
                            key = (href, node.get("text") or "")
                            found[key] = found.get(key, 0) + 1
                for value in node.values():
                    if isinstance(value, (list, dict)):
                        walk(value, text_of)
            elif isinstance(node, list):
                for child in node:
                    walk(child, text_of)

        walk(content.get("body"), None)
        for (href, text), occ in found.items():
            kind, _ = classify(href)
            target, why = rewrite_href(href)
            out.append({
                "type": "blogs", "sharepoint_id": sid,
                "story_slug": routing.get(sid, ""),
                "link_text": text.strip()[:120], "href": href, "kind": kind,
                "status": "ready — rerouted on upload" if target else why,
                "suggested_target": target or "", "new_target": "",
                "occurrences": occ})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out")
    a = ap.parse_args()

    P.use("news")
    story_slugs = live_story_slugs()

    rows = news_rows(story_slugs) + blogs_rows()
    P.use("news")
    out = a.out or os.path.join(P.DATA, "internal_links.csv")
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)

    from collections import Counter
    by_kind = Counter(r["kind"] for r in rows)
    ready = sum(1 for r in rows if r["suggested_target"])
    print(f"  {len(rows)} aku.edu link(s) across news and blogs")
    for kind, n in by_kind.most_common():
        print(f"    {n:>5}  {kind}")
    print(f"\n  {ready} can be rerouted today")
    print(f"  {len(rows) - ready} need a Storyblok page that does not exist yet"
          f" — fill in `new_target` as they appear")
    print(f"  -> {os.path.relpath(out, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
