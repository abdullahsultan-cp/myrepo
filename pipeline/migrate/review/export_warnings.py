#!/usr/bin/env python3
"""
export_warnings.py — every warning, with links to check it.

One row per warning, carrying the SharePoint page it came from and both
Storyblok links, so a warning can be judged by opening the two side by side
rather than by reading its text.

`kind` groups warnings whose message differs only by filename, so a spreadsheet
can be filtered to one class of problem at a time.

Usage:
    python scripts/migrate/review/export_warnings.py
    python scripts/migrate/review/export_warnings.py --kind "body was empty"
"""

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import BASE  # noqa: E402

import db as tracking  # noqa: E402

# Paths come from the shared module so this script works for any content
# type; see pipeline/paths_root.py.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from paths_root import P  # noqa: E402

OUT = os.path.join(P.MIGRATE, "reports", "warnings.csv")
PAGE = "https://www.aku.edu/news/Pages/news_details.aspx?nid={nid}"
EDITOR = "https://app.storyblok.com/#/me/spaces/{sp}/stories/0/0/{id}"

# Whether each class needs action, so the sheet can be triaged rather than read
# top to bottom. Anything not listed is treated as needing a look.
BY_DESIGN = {
    "no entity: 'entities' left empty",
    "asset not uploaded: <file>",
    "table(s) skipped, as agreed",
    "secondary_language label is not a language; dropped",
    "news_in_urdu label is not a language; dropped",
    "pull_quote embed nested in rich_text",
    "no first paragraph; used the summary as description",
    "body image not resolved: <url>",
    "thumbnail image has no field on news_article; skipped",
    "no date on the source item",
    "no author on the source item",
}


def kind_of(msg):
    """Collapse a message to its class, so per-file text does not fragment it."""
    m = msg
    m = re.sub(r"asset not uploaded: \w+/.*", "asset not uploaded: <file>", m)
    m = re.sub(r"body image not resolved:.*",
               "body image not resolved: <url>", m)
    m = re.sub(r"^.*file not uploaded; linked the legacy URL",
               "language PDF not uploaded; linked the legacy URL", m)
    m = re.sub(r"no entity folder for .*",
               "no entity folder for <region/entity>", m)
    m = re.sub(r"\d+ table\(s\) skipped.*", "table(s) skipped, as agreed", m)
    m = re.sub(r"pull_quote \w+ nested.*",
               "pull_quote embed nested in rich_text", m)
    m = re.sub(r"secondary_language_\d .* is not a language; dropped",
               "secondary_language label is not a language; dropped", m)
    m = re.sub(r"news_in_urdu .* is not a language; dropped",
               "news_in_urdu label is not a language; dropped", m)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", help="only warnings whose kind contains this")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()

    with open(os.path.join(BASE, "config", "storyblok.json"),
              encoding="utf-8") as f:
        cfg = json.load(f)
    space = cfg["space_id"]
    domain = (cfg.get("frontend_domain")
              or "https://aku-dev.vercel.app").rstrip("/")

    with tracking.connect() as c:
        c.execute("SET search_path TO migration, public")
        rows = c.execute("""
            SELECT e.level, e.stage, e.message, e.sharepoint_id,
                   s.sequence_number, s.title, s.region, s.entity, s.department,
                   s.placement, s.sb_story_id, s.upload_full_slug
            FROM event e LEFT JOIN story s USING (sharepoint_id)
            WHERE e.level IN ('warn', 'error')
            ORDER BY e.sharepoint_id, e.level, e.message
        """).fetchall()

    out = []
    for (level, stage, msg, sid, seq, title, region, entity, dept, placement,
         sb_id, slug) in rows:
        k = kind_of(msg)
        if a.kind and a.kind.lower() not in k.lower():
            continue
        out.append({
            "sr_no": len(out) + 1,
            "level": level,
            "kind": k,
            "needs_action": "no" if k in BY_DESIGN else "YES",
            "message": msg,
            "stage": stage or "",
            "sharepoint_id": sid,
            "title": title or "",
            "region": region or "", "entity": entity or "",
            "department": dept or "", "placement": placement or "",
            "sharepoint_link": (PAGE.format(nid=(seq or "").upper())
                                if seq else ""),
            "sb_editorial_link": (EDITOR.format(sp=space, id=sb_id)
                                  if sb_id else ""),
            "sb_preview_link": f"{domain}/{slug}" if slug else "",
        })

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, lineterminator="\n", fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)

    print(f"  {len(out)} rows -> {os.path.relpath(a.out, BASE)}")
    print(f"  {len({r['sharepoint_id'] for r in out})} distinct stories\n")

    print(f"  {'needs':<6}{'count':>7}  kind")
    for k, n in Counter(r["kind"] for r in out).most_common():
        print(f"  {'no' if k in BY_DESIGN else 'YES':<6}{n:>7}  {k}")

    todo = sum(1 for r in out if r["needs_action"] == "YES")
    print(f"\n  {todo} warnings need action; {len(out) - todo} are by design")


if __name__ == "__main__":
    main()
