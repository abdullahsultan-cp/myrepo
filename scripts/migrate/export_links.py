#!/usr/bin/env python3
"""
export_links.py — side-by-side review sheet: SharePoint vs Storyblok.

One row per uploaded story with the original SharePoint page, the published
Storyblok page, and the Storyblok editor link, so each migrated story can be
compared against its source and corrected in place.

SharePoint exposed two URLs per item. Both are emitted:
    canonical  /news/pages/news_details.aspx?nid=news-003589   (sequence number)
    friendly   /news/{slug}                                    (rewrite)

Usage:
    python scripts/migrate/export_links.py [out.csv] [--all] [--internal-links FILE]

Default output: data/migrate/links.csv  (only stories that have been uploaded)
--all                 include stories not yet uploaded, with blank SB columns
--internal-links FILE  also export the internal-link rewrite queue
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..")))

import json

import db as tracking
from storyblok_config import load_config

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

SHAREPOINT_BASE = "https://www.aku.edu"
EDITOR = "https://app.storyblok.com/#/me/spaces/{space}/stories/0/0/{story}"

# The live SharePoint page. Verified against the site: this returns 200 with the
# matching article title. The slug form (/news/{slug}) is NOT a SharePoint URL —
# it 404s. It only ever existed inside the pipeline's own link lookup.
# Note the server rejects HEAD; validation must use GET.
SHAREPOINT_NEWS = SHAREPOINT_BASE + "/news/Pages/news_details.aspx?nid={nid}"


def sharepoint_link(sequence_number):
    if not sequence_number:
        return ""
    return SHAREPOINT_NEWS.format(nid=sequence_number.upper())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?",
                    default=os.path.join(BASE, "data", "migrate", "links.csv"))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--internal-links")
    ap.add_argument("--check", action="store_true",
                    help="GET each SharePoint URL and record the status code")
    a = ap.parse_args()

    cfg = load_config()
    space = cfg.get("space_id") or ""
    domain = (cfg.get("frontend_domain")
              or "https://aku-dev.vercel.app").rstrip("/")

    where = "" if a.all else "WHERE sb_story_id IS NOT NULL"
    with tracking.connect() as c:
        c.execute("SET search_path TO migration, public")
        rows = c.execute(f"""
            SELECT sharepoint_id, sequence_number, title, target_slug,
                   sb_story_id, upload_full_slug, status, region, entity,
                   department, placement
            FROM story {where}
            ORDER BY sb_story_id NULLS LAST, sharepoint_id
        """).fetchall()

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    cols = ["sr_no", "sharepoint_live_link", "sb_live_link",
            "sb_editorial_link", "sharepoint_id", "sequence_number", "title",
            "sb_story_id", "status", "region", "entity", "department"]
    out_rows = []
    for i, r in enumerate(rows, 1):
        (sid, seq, title, slug, sb_id, full_slug, status,
         region, entity, dept, placement) = r
        out_rows.append([
            i, sharepoint_link(seq),
            f"{domain}/{full_slug}" if full_slug else "",
            EDITOR.format(space=space, story=sb_id) if sb_id else "",
            sid, seq or "", title, sb_id or "", status,
            region or "", entity or "", dept or "",
        ])

    if a.check:
        import requests
        ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        cols.insert(2, "sharepoint_http")
        for row in out_rows:
            url = row[1]
            code = ""
            if url:
                try:
                    # GET, not HEAD: the SharePoint server rejects HEAD
                    code = requests.get(url, headers=ua, timeout=25).status_code
                except Exception as e:
                    code = type(e).__name__
            row.insert(2, code)
            print(f"    {code}  {url}")

    with open(a.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(out_rows)

    print(f"  {len(rows)} rows -> {a.out}")
    print(f"  frontend domain: {domain}")
    print(f"  space          : {space}")

    if a.internal_links:
        with tracking.connect() as c:
            c.execute("SET search_path TO migration, public")
            lrows = c.execute("""
                SELECT id, sharepoint_id, from_title, from_sb_id, from_slug,
                       raw_href, link_text, target_sharepoint_id, target_title,
                       target_sb_id, target_sb_uuid, target_slug,
                       resolved, resolution_method
                FROM internal_links_todo
            """).fetchall()
        lcols = ["sr_no", "link_id", "from_sharepoint_id", "from_title",
                 "from_sb_story_id", "from_sb_slug", "raw_href", "link_text",
                 "target_sharepoint_id", "target_title", "target_sb_story_id",
                 "target_sb_uuid", "target_sb_slug", "resolved",
                 "resolution_method"]
        os.makedirs(os.path.dirname(os.path.abspath(a.internal_links)),
                    exist_ok=True)
        with open(a.internal_links, "w", newline="",
                  encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(lcols)
            for i, r in enumerate(lrows, 1):
                w.writerow([i] + ["" if x is None else x for x in r])
        print(f"  {len(lrows)} internal/document links -> {a.internal_links}")


if __name__ == "__main__":
    main()
