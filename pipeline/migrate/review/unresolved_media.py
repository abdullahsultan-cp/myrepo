#!/usr/bin/env python3
"""
unresolved_media.py — the pages whose declared media could not be found.

The SharePoint export declares a filename per role (banner, medium, thumbnail,
video1). The resolver reads each live page and matches those declarations to real
URLs. Some never match, and the interesting question is always the same: is the
image genuinely absent from the page, or did the resolver miss it?

So this lists one row per affected page with the live URL, what the export
claimed, and what the resolver DID find — because "declared 3, page renders 1" is
an export artefact, while "declared 1, page renders 0" is a real gap.

Usage:
    python scripts/migrate/review/unresolved_media.py [--csv] [--role banner]
"""

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict

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
import _bootstrap  # noqa: F401,E402
from paths import BASE  # noqa: E402

# Paths come from the shared module so this script works for any content
# type; see pipeline/paths_root.py.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from paths_root import P  # noqa: E402

CACHE = os.path.join(P.MIGRATE, "media_urls.json")
STORIES = P.STORIES
OUT = os.path.join(P.MIGRATE, "unresolved_media.csv")
PAGE = "https://www.aku.edu/news/Pages/news_details.aspx?nid={nid}"

# What a missing role costs the rendered story, in plain terms.
IMPACT = {
    "banner": "hero image at the top of the article",
    "medium": "second/inline image beside the body",
    "thumbnail": "card image in listings and 'similar news'",
    "video1": "embedded video file",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", action="store_true", help=f"also write {OUT}")
    ap.add_argument("--role", help="only this role")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    with open(CACHE, encoding="utf-8") as f:
        cache = json.load(f)

    rows = []
    for sid, rec in cache.items():
        by_role = rec.get("by_role") or {}
        missing, found = [], []
        for role, entries in by_role.items():
            for e in entries:
                if e.get("url"):
                    found.append((role, os.path.basename(e["url"].split("?")[0])))
                else:
                    missing.append((role, e.get("filename") or e.get("source_filename")
                                    or "?"))
        if not missing:
            continue
        if a.role and not any(r == a.role for r, _ in missing):
            continue

        title, seq = "", ""
        p = os.path.join(STORIES, f"{sid}.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                c = json.load(f)["content"]
            title = c.get("title") or ""
            seq = (c.get("sequence_number") or "").upper()

        rows.append({
            "sharepoint_id": sid,
            "page": PAGE.format(nid=seq) if seq else "",
            "title": title,
            "missing_roles": " + ".join(sorted({r for r, _ in missing})),
            "missing_count": len(missing),
            "declared_but_not_found": "; ".join(f for _, f in missing),
            "what_is_missing_on_the_page": "; ".join(
                IMPACT.get(r, r) for r in sorted({r for r, _ in missing})),
            "found_on_page": "; ".join(f"{r}={f}" for r, f in found) or "(nothing)",
            "found_count": len(found),
            "verdict": ("export declared more images than the page shows"
                        if found else "page appears to have no media at all"),
        })

    rows.sort(key=lambda r: (-r["missing_count"], r["sharepoint_id"]))

    total_media = sum(r["missing_count"] for r in rows)
    print(f"  {total_media} unresolved media across {len(rows)} pages\n")

    by_role = Counter()
    for r in rows:
        for role in r["missing_roles"].split(" + "):
            by_role[role] += 1
    print("  pages affected, by role")
    for role, n in by_role.most_common():
        print(f"    {n:>4}  {role:<10} {IMPACT.get(role, '')}")

    verdicts = Counter(r["verdict"] for r in rows)
    print("\n  why")
    for v, n in verdicts.most_common():
        print(f"    {n:>4}  {v}")

    shown = rows[:a.limit] if a.limit else rows
    print(f"\n{'=' * 100}")
    for i, r in enumerate(shown, 1):
        print(f"\n{i:>3}. story {r['sharepoint_id']}   MISSING: {r['missing_roles']}")
        print(f"     {r['title'][:88]}")
        print(f"     {r['page']}")
        print(f"     declared but absent : {r['declared_but_not_found'][:80]}")
        print(f"     page actually has   : {r['found_on_page'][:80]}")

    if a.csv:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, lineterminator="\n",
                               fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"\n  -> {OUT}   ({len(rows)} rows)")


if __name__ == "__main__":
    main()
