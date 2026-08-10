#!/usr/bin/env python3
"""media_progress.py — one-line progress report for the media URL resolver."""

import json
import os
import sys

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
import _bootstrap

_bootstrap.ensure()

# Paths come from the shared module so this script works for any content
# type; see pipeline/paths_root.py.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from paths_root import P

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
