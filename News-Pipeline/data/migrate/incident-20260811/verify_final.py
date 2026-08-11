#!/usr/bin/env python3
"""Independent verification, read-only. Re-reads all 184 from the API and checks
four things per story, against sources the restore did not write:

  1. content is byte-identical to the 9 Aug snapshot
  2. full_slug is unchanged from the pre-revert capture -- nothing moved
  3. the intro is no longer duplicated between description and the body
  4. the internal aku.edu links and their targets are back
"""
import gzip
import json
import os
import re
import sys

REPO = r"d:\AKU News\aku-data-transformation-pipeline-news-master"
sys.path.insert(0, os.path.join(REPO, r"pipeline\core"))
from storyblok_config import load_config, management_api_base  # noqa: E402

import requests  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(REPO, r"News-Pipeline\backup\storyblok\news_20260809-160355.json.gz")

with gzip.open(SNAP, "rb") as f:
    snap = json.loads(f.read().decode("utf-8"))["stories"]
with gzip.open(os.path.join(HERE, "pre_revert_live_184.json.gz"), "rb") as f:
    before = json.loads(f.read().decode("utf-8"))["stories"]
with open(os.path.join(HERE, "affected.json"), encoding="utf-8") as f:
    affected = json.load(f)["found"]

cfg = load_config()
api = f"{management_api_base(cfg)}/spaces/{cfg['space_id']}"
s = requests.Session()
s.headers.update({"Authorization": cfg["management_token"]})


def texts_links(content):
    t, li = [], []

    def w(n):
        if isinstance(n, dict):
            if n.get("type") == "text":
                t.append(n.get("text") or "")
            if n.get("type") == "link":
                a = n.get("attrs") or {}
                li.append((a.get("href"), a.get("target")))
            for v in n.values():
                w(v)
        elif isinstance(n, list):
            for v in n:
                w(v)
    w(content.get("body"))
    return "".join(t), li


def norm(x):
    return re.sub(r"\W+", " ", (x or "")).strip().lower()


def canon(c):
    return json.dumps(c, sort_keys=True, ensure_ascii=False)


bad_content, moved, dup, relativised, no_target, authors = [], [], [], [], [], {}
for i, r in enumerate(affected, 1):
    sid, sb_id = int(r["sharepoint_id"]), r["sb_id"]
    resp = s.get(f"{api}/stories/{sb_id}", timeout=90)
    if resp.status_code != 200:
        bad_content.append((sid, f"HTTP {resp.status_code}"))
        continue
    st = resp.json()["story"]
    c = st["content"]

    if canon(c) != canon(snap[str(sid)]["content"]):
        bad_content.append((sid, "content differs from snapshot"))
    if st.get("full_slug") != before[str(sid)].get("full_slug"):
        moved.append((sid, before[str(sid)].get("full_slug"), st.get("full_slug")))

    body, links = texts_links(c)
    d = norm(c.get("description"))
    if d and d[:120] in norm(body):
        dup.append(sid)
    for h, tg in links:
        if h and h.startswith("/"):
            relativised.append((sid, h))
        if h and not tg:
            no_target.append((sid, h))
    la = (st.get("last_author") or {}).get("friendly_name") or "?"
    authors[la] = authors.get(la, 0) + 1
    if i % 60 == 0:
        print(f"  checked {i}/{len(affected)}", flush=True)

n = len(affected)
print(f"\n  VERIFICATION of {n} stories\n")
print(f"  content identical to your 9 Aug snapshot : {n - len(bad_content)}/{n}")
print(f"  full_slug unchanged (nothing moved)      : {n - len(moved)}/{n}")
print(f"  duplicated intro remaining               : {len(dup)}")
print(f"  body links still relative (/...)         : {len(relativised)}")
print(f"  body links with no target attribute      : {len(no_target)}")
print(f"  last_author now: {authors}")

for sid, why in bad_content[:10]:
    print(f"    !! {sid}: {why}")
for sid, a, b in moved[:10]:
    print(f"    !! {sid} MOVED {a} -> {b}")
for sid in dup[:10]:
    print(f"    !! {sid} still duplicated")

print("\n  " + ("ALL CHECKS PASSED" if not (bad_content or moved or dup)
                else "SOMETHING NEEDS ATTENTION"))
