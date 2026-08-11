#!/usr/bin/env python3
"""restore.py -- put the 9 Aug content back on the 184 stories the 11 Aug run
changed. Update in place: same story id, so every review link already shared
stays valid, and no story moves.

Safety properties, deliberately:
  * `slug` and `parent_id` are read from the LIVE story immediately before the
    PUT, never from the DB -- the DB's target_full_slug is the pre-rename long
    form and would move all 184 pages.
  * only `name`, `slug`, `parent_id` and `content` are sent. No delete, no
    create: if a story has no id in the snapshot it is skipped and reported.
  * every PUT is followed by a re-read that compares content byte for byte;
    a mismatch is recorded as a failure rather than assumed to be fine.
  * 429 and 5xx are retried, and so are connection errors -- an aborted run
    halfway through 184 stories is the thing to avoid.

Usage:
    python restore.py --dry-run            # show what would be sent
    python restore.py --ids 2381           # one story
    python restore.py                      # all 184
"""
import argparse
import gzip
import json
import os
import sys
import time

REPO = r"d:\AKU News\aku-data-transformation-pipeline-news-master"
sys.path.insert(0, os.path.join(REPO, r"pipeline\core"))
from storyblok_config import load_config, management_api_base  # noqa: E402

import requests  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(REPO, r"News-Pipeline\backup\storyblok\news_20260809-160355.json.gz")

ap = argparse.ArgumentParser()
ap.add_argument("--dry-run", action="store_true")
ap.add_argument("--ids", help="comma-separated sharepoint ids")
ap.add_argument("--limit", type=int)
ap.add_argument("--sleep", type=float, default=0.35)
args = ap.parse_args()

with gzip.open(SNAP, "rb") as f:
    snap = json.loads(f.read().decode("utf-8"))["stories"]
with open(os.path.join(HERE, "affected.json"), encoding="utf-8") as f:
    affected = json.load(f)["found"]

if args.ids:
    want = {int(x) for x in args.ids.split(",")}
    affected = [r for r in affected if int(r["sharepoint_id"]) in want]
if args.limit:
    affected = affected[:args.limit]

cfg = load_config()
api = f"{management_api_base(cfg)}/spaces/{cfg['space_id']}"
s = requests.Session()
s.headers.update({"Authorization": cfg["management_token"]})


def call(method, path, **kw):
    """Retry 429/5xx and connection errors; return the response or None."""
    for attempt in range(6):
        try:
            r = s.request(method, f"{api}/{path}", timeout=120, **kw)
        except requests.exceptions.RequestException as e:
            wait = 2 ** attempt
            print(f"      {type(e).__name__}; retry in {wait}s", flush=True)
            time.sleep(wait)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            wait = 2 ** attempt
            print(f"      HTTP {r.status_code}; retry in {wait}s", flush=True)
            time.sleep(wait)
            continue
        return r
    return None


def canon(c):
    return json.dumps(c, sort_keys=True, ensure_ascii=False)


print(f"\n  restore -- {len(affected)} stories, "
      f"{'DRY RUN' if args.dry_run else 'WRITING'}")
print(f"  source : {os.path.basename(SNAP)}")
print(f"  space  : {cfg['space_id']}\n")

ok = failed = skipped = 0
log = []
for i, r in enumerate(affected, 1):
    sid, sb_id = int(r["sharepoint_id"]), r["sb_id"]
    want_content = snap[str(sid)].get("content")
    if not want_content:
        print(f"  !! {sid}: nothing in the snapshot; skipped")
        skipped += 1
        continue

    cur = call("GET", f"stories/{sb_id}")
    if cur is None or cur.status_code != 200:
        code = getattr(cur, "status_code", "conn")
        print(f"  !! {sid}: live read failed ({code}); skipped")
        failed += 1
        log.append({"sharepoint_id": sid, "sb_id": sb_id, "result": f"read {code}"})
        continue
    livestory = cur.json()["story"]

    if canon(livestory.get("content")) == canon(want_content):
        print(f"  = {sid} already matches the snapshot")
        skipped += 1
        log.append({"sharepoint_id": sid, "sb_id": sb_id, "result": "already ok"})
        continue

    payload = {"story": {"name": livestory.get("name"),
                         "slug": livestory.get("slug"),
                         "parent_id": livestory.get("parent_id"),
                         "content": want_content},
               "publish": 1}

    if args.dry_run:
        print(f"  ~ {sid} would PUT stories/{sb_id}  "
              f"slug={payload['story']['slug']}  "
              f"parent_id={payload['story']['parent_id']}  "
              f"fields={len(want_content)}")
        log.append({"sharepoint_id": sid, "sb_id": sb_id, "result": "dry-run",
                    "slug": payload["story"]["slug"],
                    "parent_id": payload["story"]["parent_id"]})
        continue

    put = call("PUT", f"stories/{sb_id}", json=payload)
    if put is None or put.status_code not in (200, 201):
        msg = f"{getattr(put, 'status_code', 'conn')} {getattr(put, 'text', '')[:200]}"
        print(f"  !! {sid} PUT FAILED  {msg}")
        failed += 1
        log.append({"sharepoint_id": sid, "sb_id": sb_id, "result": f"put {msg}"})
        continue

    back = call("GET", f"stories/{sb_id}")
    same = (back is not None and back.status_code == 200
            and canon(back.json()["story"].get("content")) == canon(want_content))
    fs = (back.json()["story"].get("full_slug") if back is not None
          and back.status_code == 200 else "?")
    moved = fs != livestory.get("full_slug")
    if same and not moved:
        ok += 1
        print(f"  + {sid} restored & verified  {fs}")
    else:
        failed += 1
        print(f"  !! {sid} verify FAILED  content_match={same} moved={moved} {fs}")
    log.append({"sharepoint_id": sid, "sb_id": sb_id,
                "result": "ok" if (same and not moved) else "verify failed",
                "full_slug": fs, "moved": moved})
    time.sleep(args.sleep)
    if i % 25 == 0:
        print(f"    -- {i}/{len(affected)}", flush=True)

print(f"\n  restored={ok}  failed={failed}  skipped={skipped}")
out = os.path.join(HERE, "restore_log.json")
with open(out, "w", encoding="utf-8", newline="\n") as f:
    json.dump(log, f, indent=2, ensure_ascii=False)
print(f"  log -> {out}")
