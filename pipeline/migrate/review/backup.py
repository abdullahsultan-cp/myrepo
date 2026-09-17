#!/usr/bin/env python3
"""
backup.py — snapshot the source export and what is live in Storyblok.

Two things are worth being able to get back to, and they sit at opposite ends of
the migration:

    raw        the SharePoint export exactly as it arrived. The site is being
               retired, so once it is gone this file is the only record of what
               the content used to be.
    storyblok  every story as it currently exists in the space, read back from
               the API rather than assumed from the payload we sent.

Having both means any question of "did the migration do this, or was it always
like that?" is answerable by diff instead of argument. That question has already
come up more than once.

Each snapshot is a single file per type, timestamped, so they are small enough to
commit and a history of them accumulates in git.

Usage:
    python pipeline/migrate/review/backup.py                  # both, for news
    python pipeline/migrate/review/backup.py --type blogs
    python pipeline/migrate/review/backup.py --raw            # source only
    python pipeline/migrate/review/backup.py --storyblok      # live only
    python pipeline/migrate/review/backup.py --verify         # compare, no write
"""

import argparse
import gzip
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone

# Walk up for _bootstrap.py rather than counting dirname() calls. The counted
# version reached `pipeline/` — and `paths_root` lives in `pipeline/core/`, so
# this script could not run at all. Fifth time this exact fault has appeared;
# `_bootstrap.ensure()` puts every folder on the path and cannot miscount.
_d = os.path.dirname(os.path.abspath(__file__))
while _d != os.path.dirname(_d):
    if os.path.exists(os.path.join(_d, "_bootstrap.py")):
        sys.path.insert(0, _d)
        break
    _d = os.path.dirname(_d)
import _bootstrap

_bootstrap.ensure()

from paths_root import TYPES, P

# This flow's own helpers (migrate/paths.py, migrate/db.py) sit beside and above
# this file; _bootstrap.ensure() above has already put the shared pipeline
# folders on the path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from storyblok_config import load_config, management_api_base

try:
    import requests
except ImportError:
    sys.exit("pip install -r requirements.txt")


def stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def write(path, payload):
    """Gzipped, because a 3606-story snapshot is 40 MB of very repetitive JSON."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    blob = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    with gzip.open(path, "wb") as f:
        f.write(blob)
    digest = hashlib.sha256(blob).hexdigest()
    mb = os.path.getsize(path) / 1e6
    print(f"    {os.path.relpath(path, P.PIPELINE):<48} {mb:>6.1f} MB  "
          f"sha256 {digest[:12]}")
    return digest


def backup_raw():
    """The SharePoint export, unchanged."""
    src = P.SOURCE_JSON
    if not os.path.exists(src):
        print(f"    no source export at {os.path.relpath(src, P.PIPELINE)}")
        return None
    with open(src, encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("value") if isinstance(data, dict) else data
    out = os.path.join(P.BACKUP, "raw", f"{P.type}_{stamp()}.json.gz")
    digest = write(out, {
        "taken_at": stamp(), "type": P.type, "source": os.path.basename(src),
        "count": len(items or []), "data": data,
    })
    return {"file": out, "count": len(items or []), "sha256": digest}


def live_ids(session, api):
    """[(key, storyblok id)] for THIS type's stories, from the space.

    Selected by the type's own component — `blog_article`, `news_article`,
    `event_article` — because that is the only thing that is true for every
    type. The tracking database holds news and nothing else, so asking it for
    "this type's stories" during a blogs run returned all 3,606 NEWS stories
    and wrote them into `Blogs-Pipeline/backup/storyblok/`: the wrong content,
    in the wrong place, under a name saying otherwise. A backup that quietly
    contains somebody else's data is worse than no backup.

    Keyed by `sharepoint_id` where the payload carries one — blogs and events
    do — and by the Storyblok id where it does not, which is news.
    """
    component = P.storyblok.get("component")
    out, page = [], 1
    while True:
        r = session.get(f"{api}/stories", timeout=90,
                        params={"contain_component": component,
                                "per_page": 100, "page": page})
        if r.status_code != 200:
            print(f"    listing stories failed: {r.status_code}")
            return out
        chunk = r.json().get("stories", [])
        for story in chunk:
            out.append((None, story["id"]))
        if len(chunk) < 100:
            print(f"    {len(out)} live story/stories using {component}")
            return out
        page += 1


def read_story(session, url, tries=6):
    """GET one story, honouring the rate limiter. Returns the response or None.

    This used to be a bare `session.get()`. A `429` was therefore recorded as a
    permanent failure and the story simply left out of the archive — **49 of
    3,860 news stories on 15 Sep, then 59 on the retry**, with the script still
    exiting 0. Every other caller in this repo has retried 429 and 5xx since
    `SB._call` was written; the backup, the one thing that must be complete,
    never got it.

    A backup with a silent hole in it is worse than no backup: Storyblok keeps
    no version history, so the archive is the only record of what the space
    held, and nobody can settle "was it always like that?" against a file that
    quietly dropped the story being asked about.
    """
    for attempt in range(tries):
        try:
            r = session.get(url, timeout=90)
        except requests.exceptions.RequestException:
            if attempt == tries - 1:
                raise
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code == 429:
            wait = int(r.headers.get("Retry-After", 2 * (attempt + 1)))
            time.sleep(wait)
            continue
        if r.status_code >= 500 and attempt < tries - 1:
            time.sleep(1.5 * (attempt + 1))
            continue
        return r
    return r


def backup_storyblok():
    """Every story this type has in the space, read back from the API."""
    cfg = load_config()
    api = f"{management_api_base(cfg)}/spaces/{cfg['space_id']}"
    s = requests.Session()
    s.headers.update({"Authorization": cfg["management_token"]})

    rows = live_ids(s, api)
    if not rows:
        print("    nothing uploaded yet for this type")
        return None

    stories, failed = {}, []
    for i, (sid, sb_id) in enumerate(rows, 1):
        try:
            r = read_story(s, f"{api}/stories/{sb_id}")
        except requests.exceptions.RequestException as e:
            failed.append((sid, type(e).__name__))
            continue
        if r.status_code == 200:
            story = r.json()["story"]
            # Key on sharepoint_id when the payload carries one, so the backup
            # is keyed the same way the source is. News predates that field and
            # falls back to the Storyblok id.
            key = str((story.get("content") or {}).get("sharepoint_id")
                      or sid or story["id"])
            stories[key] = story
        else:
            failed.append((sid or sb_id, r.status_code))
        if i % 250 == 0:
            print(f"      read {i}/{len(rows)}", flush=True)

    out = os.path.join(P.BACKUP, "storyblok", f"{P.type}_{stamp()}.json.gz")
    digest = write(out, {
        "taken_at": stamp(), "type": P.type, "space_id": cfg["space_id"],
        "count": len(stories), "failed": failed, "stories": stories,
    })
    if failed:
        print(f"    {len(failed)} could not be read: {failed[:5]}")
    return {"file": out, "count": len(stories), "sha256": digest}


def latest(kind):
    d = os.path.join(P.BACKUP, kind)
    if not os.path.isdir(d):
        return None
    files = sorted(f for f in os.listdir(d) if f.startswith(f"{P.type}_"))
    return os.path.join(d, files[-1]) if files else None


def verify():
    """Compare the newest Storyblok snapshot against what is live now.

    The point of a backup nobody reads is nothing, so this is the read: it says
    which stories have changed since the snapshot, which is how "something went
    sideways" gets noticed rather than discovered months later.
    """
    p = latest("storyblok")
    if not p:
        print("    no Storyblok snapshot yet; run without --verify first")
        return 1
    with gzip.open(p, "rb") as f:
        snap = json.loads(f.read().decode("utf-8"))
    print(f"    comparing against {os.path.basename(p)} "
          f"({snap['count']} stories, taken {snap['taken_at']})")

    cfg = load_config()
    api = f"{management_api_base(cfg)}/spaces/{cfg['space_id']}"
    s = requests.Session()
    s.headers.update({"Authorization": cfg["management_token"]})

    changed, gone, same = [], [], 0
    for sid, old in snap["stories"].items():
        r = read_story(s, f"{api}/stories/{old['id']}")
        if r.status_code == 404:
            gone.append(sid)
            continue
        if r.status_code != 200:
            continue
        new = r.json()["story"]
        a = json.dumps(old.get("content"), sort_keys=True, ensure_ascii=False)
        b = json.dumps(new.get("content"), sort_keys=True, ensure_ascii=False)
        if a != b:
            changed.append((sid, old.get("full_slug"), new.get("full_slug")))
        else:
            same += 1

    print(f"\n    unchanged {same}   changed {len(changed)}   deleted {len(gone)}")
    for sid, was, now in changed[:25]:
        moved = f"  moved: {was} -> {now}" if was != now else ""
        print(f"      {sid}{moved}")
    if gone:
        print(f"    DELETED since the snapshot: {gone[:20]}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", choices=sorted(TYPES))
    ap.add_argument("--raw", action="store_true", help="source export only")
    ap.add_argument("--storyblok", action="store_true", help="live space only")
    ap.add_argument("--verify", action="store_true",
                    help="compare the newest snapshot with the live space")
    a = ap.parse_args()
    if a.type:
        P.use(a.type)

    print(f"\n  backup — {P.type} ({P.label})")
    if a.verify:
        return verify()

    both = not (a.raw or a.storyblok)
    if a.raw or both:
        print("\n  raw source export")
        backup_raw()
    if a.storyblok or both:
        print("\n  live Storyblok content")
        backup_storyblok()
    print(f"\n  -> {os.path.relpath(P.BACKUP, P.PIPELINE)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
