#!/usr/bin/env python3
"""
sync_from_sb.py — reconcile the tracking DB with what is actually in Storyblok.

Stories get moved, renamed and edited in the Storyblok UI. Anything the DB
recorded at upload time goes stale the moment that happens, so this re-reads the
space and updates parent, slug and publish state, and records any story it finds
that the DB does not know about.

Also snapshots the current content of every story the DB tracks, so manual
editorial changes can be diffed against what the migration generated.

Read-only against Storyblok. GET requests only.

Usage:
    python scripts/migrate/upload/sync_from_sb.py            # reconcile
    python scripts/migrate/upload/sync_from_sb.py --snapshot # also save content JSON
"""

import argparse
import json
import os
import sys


# paths puts scripts/migrate/ and scripts/ on sys.path, so it comes first.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import BASE  # noqa: E402

import db as tracking  # noqa: E402
from storyblok_config import load_config  # noqa: E402
from upload import SB  # noqa: E402

# Paths come from the shared module so this script works for any content
# type; see pipeline/paths_root.py.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from paths_root import P  # noqa: E402

SNAP_DIR = os.path.join(P.MIGRATE, "sb_snapshot")


def all_stories(sb):
    out, page = [], 1
    while True:
        r = sb.get("stories", params={"per_page": 100, "page": page})
        if r.status_code != 200:
            sys.exit(f"list failed: {r.status_code} {r.text[:200]}")
        chunk = r.json().get("stories") or []
        out.extend(chunk)
        total = int(r.headers.get("Total", len(out)))
        if len(out) >= total or not chunk:
            break
        page += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", action="store_true")
    a = ap.parse_args()

    cfg = load_config()
    sb = SB(cfg)
    live = all_stories(sb)
    folders = {s["id"]: s for s in live if s.get("is_folder")}
    articles = [s for s in live if not s.get("is_folder")]
    print(f"  space has {len(live)} entries: {len(folders)} folders, "
          f"{len(articles)} stories")

    with tracking.connect() as c:
        c.execute("SET search_path TO migration, public")
        tracked = {r[0]: r[1] for r in c.execute(
            "SELECT sb_story_id, sharepoint_id FROM story "
            "WHERE sb_story_id IS NOT NULL").fetchall()}

    moved, unchanged, untracked = [], 0, []
    for st in articles:
        sid = tracked.get(st["id"])
        if sid is None:
            untracked.append(st)
            continue
        parent = st.get("parent_id") or 0
        folder = folders.get(parent, {}).get("full_slug", "")
        with tracking.connect() as c:
            c.execute("SET search_path TO migration, public")
            old = c.execute("""SELECT upload_folder, upload_full_slug
                               FROM story WHERE sharepoint_id=%s""",
                            (sid,)).fetchone()
            if old and (old[0] != folder or old[1] != st.get("full_slug")):
                moved.append((sid, old[1], st.get("full_slug")))
            c.execute("""UPDATE story
                         SET upload_folder=%s, upload_full_slug=%s,
                             sb_parent_id=%s, target_slug=%s, updated_at=now()
                         WHERE sharepoint_id=%s""",
                      (folder, st.get("full_slug"), parent, st.get("slug"),
                       sid))
            c.commit()
            if not (old and (old[0] != folder or old[1] != st.get("full_slug"))):
                unchanged += 1

    if moved:
        print(f"\n  {len(moved)} stories moved or renamed:")
        for sid, was, now in moved[:25]:
            print(f"    {sid}  {was or '(none)'}\n        -> {now}")
    print(f"  {unchanged} unchanged")

    if untracked:
        print(f"\n  {len(untracked)} stories in the space the DB does not track:")
        for st in untracked[:15]:
            comp = ((st.get("content") or {}).get("component")) or "?"
            print(f"    {st['id']}  {comp:<14} {st.get('full_slug')}")

    if a.snapshot:
        os.makedirs(SNAP_DIR, exist_ok=True)
        n = 0
        for st in articles:
            sid = tracked.get(st["id"])
            if sid is None:
                continue
            r = sb.get(f"stories/{st['id']}")
            if r.status_code == 200:
                with open(os.path.join(SNAP_DIR, f"{sid}.json"), "w",
                          encoding="utf-8", newline="\n") as f:
                    json.dump(r.json()["story"], f, indent=2,
                              ensure_ascii=False)
                n += 1
        print(f"\n  snapshotted {n} stories -> {SNAP_DIR}")

    with tracking.connect() as c:
        c.execute("SET search_path TO migration, public")
        for r in c.execute("""SELECT coalesce(upload_folder,'(none)'), count(*)
                              FROM story WHERE sb_story_id IS NOT NULL
                              GROUP BY 1 ORDER BY 2 DESC""").fetchall():
            print(f"  {r[1]:>4}  {r[0]}")


if __name__ == "__main__":
    main()
