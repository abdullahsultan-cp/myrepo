#!/usr/bin/env python3
"""media_progress.py — one-line progress report for the media URL resolver."""

import json
import os

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CACHE = os.path.join(BASE, "data", "migrate", "media_urls.json")
STORIES = os.path.join(BASE, "data", "storyblok_stories")

total = len([n for n in os.listdir(STORIES) if n.endswith(".json")]) \
    if os.path.isdir(STORIES) else 0

if not os.path.exists(CACHE):
    print(f"    0 / {total} fetched  (nothing cached yet)")
else:
    with open(CACHE, encoding="utf-8") as f:
        c = json.load(f)
    ok = sum(1 for v in c.values() if v.get("http") == 200)
    bad = sum(1 for v in c.values()
              if v.get("http") not in (200, None) and not v.get("fetched"))
    resolved = sum(1 for v in c.values()
                   for lst in (v.get("by_role") or {}).values()
                   for e in lst if e.get("url"))
    pct = (100 * ok // total) if total else 0
    bar = "#" * (pct // 4) + "." * (25 - pct // 4)
    print(f"    [{bar}] {pct}%")
    print(f"    {ok} / {total} pages fetched   {total - ok} remaining"
          f"   {resolved} media URLs resolved"
          + (f"   {bad} failed" if bad else ""))
