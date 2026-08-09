#!/usr/bin/env python3
"""media_progress.py — one-line progress report for the media URL resolver."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _bootstrap  # noqa: F401,E402  -- paths_root now lives in pipeline/core/
from paths import BASE  # noqa: E402

# Paths come from the shared module so this script works for any content
# type; see pipeline/paths_root.py.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from paths_root import P  # noqa: E402
CACHE = os.path.join(P.MIGRATE, "media_urls.json")
STORIES = P.STORIES

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
