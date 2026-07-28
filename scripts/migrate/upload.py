#!/usr/bin/env python3
"""
upload.py — create the sample stories in Storyblok and record the result.

Idempotent without any schema change: the Postgres table holds sb_story_id, so a
second run PUTs instead of POSTing. If the database is ever lost, the slug is
looked up first, so a re-run still updates rather than duplicating.

Assets are uploaded only if assets/News/media/ is present. When it is absent the
story is still created — text, rich text, tables, links, quotes and embeds all
survive — and every missing file is recorded as 'missing' so a later run fills
them in and republishes.

Usage:
    python scripts/migrate/upload.py plan                 # what would happen
    python scripts/migrate/upload.py assets               # upload media only
    python scripts/migrate/upload.py stories              # upload stories
    python scripts/migrate/upload.py all
    python scripts/migrate/upload.py verify               # re-read from the API

Options:
    --folder news/rabee     parent folder path      (default news/rabee)
    --limit N               stop after N stories
    --ids 2198,3288         only these
    --all-stories           the whole corpus, not just the 20-story sample
    --publish / --draft     default --publish
"""

import argparse
import hashlib
import json
import mimetypes
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", ""))

try:
    import requests
except ImportError:
    sys.exit("pip install -r requirements.txt")

import db as tracking
from build_payload import build, load_story, slugify

SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
from storyblok_config import load_config, management_api_base

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MEDIA_DIR = os.path.join(BASE, "assets", "News", "media")

THROTTLE = 0.35          # seconds between write calls; starter plan is modest


class SB:
    """Thin Management API client with retry and rate-limit handling."""

    def __init__(self, cfg):
        self.api = f"{management_api_base(cfg)}/spaces/{cfg['space_id']}"
        self.s = requests.Session()
        self.s.headers.update({"Authorization": cfg["management_token"]})
        self.space = cfg["space_id"]

    def _call(self, method, path, *, json_body=None, params=None, tries=5,
              **kw):
        url = path if path.startswith("http") else f"{self.api}/{path}"
        last = None
        for attempt in range(tries):
            r = self.s.request(method, url, json=json_body, params=params,
                               timeout=120, **kw)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", 2 * (attempt + 1)))
                print(f"      rate limited; sleeping {wait}s")
                time.sleep(wait)
                continue
            if r.status_code >= 500 and attempt < tries - 1:
                time.sleep(1.5 * (attempt + 1))
                last = r
                continue
            return r
        return last

    def get(self, path, **kw):
        return self._call("GET", path, **kw)

    def post(self, path, body, **kw):
        time.sleep(THROTTLE)
        return self._call("POST", path, json_body=body, **kw)

    def put(self, path, body, **kw):
        time.sleep(THROTTLE)
        return self._call("PUT", path, json_body=body, **kw)


# ------------------------------------------------------------------ folders

def ensure_folder(sb, path, cache):
    """Create every missing segment of a folder path; return the leaf id."""
    parent = 0
    walked = ""
    for seg in [p for p in path.split("/") if p]:
        walked = f"{walked}/{seg}" if walked else seg
        if walked in cache:
            parent = cache[walked]
            continue
        r = sb.get("stories", params={"with_slug": walked, "per_page": 1})
        found = None
        if r.status_code == 200:
            for st in r.json().get("stories") or []:
                if st.get("full_slug") == walked and st.get("is_folder"):
                    found = st["id"]
                    break
        if found is None:
            r = sb.post("stories", {"story": {
                "name": seg.replace("-", " ").title(),
                "slug": seg, "is_folder": True, "parent_id": parent,
                "content": {"component": "page"},
            }})
            if r.status_code not in (200, 201):
                sys.exit(f"cannot create folder {walked}: "
                         f"{r.status_code} {r.text[:300]}")
            found = r.json()["story"]["id"]
            print(f"    created folder {walked}  (id {found})")
        else:
            print(f"    folder exists  {walked}  (id {found})")
        cache[walked] = found
        parent = found
    return parent


# ------------------------------------------------------------------ assets

def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def upload_asset(sb, path, filename):
    """Storyblok asset upload: sign, PUT to S3, finalise."""
    size = os.path.getsize(path)
    ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    r = sb.post("assets", {"filename": filename, "size": str(size),
                           "content_type": ctype})
    if r.status_code not in (200, 201):
        return None, f"sign failed {r.status_code} {r.text[:200]}"
    sig = r.json()
    with open(path, "rb") as fh:
        files = {**{k: (None, v) for k, v in (sig.get("fields") or {}).items()},
                 "file": (filename, fh, ctype)}
        up = requests.post(sig["post_url"], files=files, timeout=300)
    if up.status_code not in (200, 201, 204):
        return None, f"s3 failed {up.status_code} {up.text[:200]}"
    fin = sb.get(f"assets/{sig['id']}/finish_upload")
    if fin.status_code not in (200, 204):
        return None, f"finish failed {fin.status_code} {fin.text[:200]}"
    meta = sb.get(f"assets/{sig['id']}")
    obj = meta.json().get("asset", meta.json()) if meta.status_code == 200 else {}
    return {
        "id": sig["id"],
        "filename": obj.get("filename") or sig.get("pretty_url") or "",
        "alt": "", "name": "", "focus": "", "title": "", "source": "",
        "copyright": "", "fieldtype": "asset", "meta_data": {},
        "is_external_url": False,
    }, None


def cmd_assets(sb, args, run_id):
    if not os.path.isdir(MEDIA_DIR):
        print(f"  assets/News/media/ not found — skipping media upload.\n"
              f"  Place the SharePoint bundle at {MEDIA_DIR} and re-run.")
        with tracking.connect() as c:
            c.execute("SET search_path TO migration, public")
            c.execute("""UPDATE asset SET status='missing', exists_on_disk=false
                         WHERE status='pending'
                           AND sharepoint_id IN (SELECT sharepoint_id FROM story
                                                 WHERE is_sample)""")
            n = c.execute("""SELECT count(*) FROM asset WHERE status='missing'
                             AND sharepoint_id IN (SELECT sharepoint_id
                             FROM story WHERE is_sample)""").fetchone()[0]
            c.commit()
        print(f"  marked {n} sample assets 'missing'")
        return

    with tracking.connect() as c:
        c.execute("SET search_path TO migration, public")
        rows = c.execute("""
            SELECT a.id, a.sharepoint_id, a.role, a.source_filename
            FROM asset a JOIN story s USING (sharepoint_id)
            WHERE a.status IN ('pending','failed','missing')
              AND (%s OR s.is_sample)
            ORDER BY a.sharepoint_id, a.role
        """, (args.all_stories,)).fetchall()

    seen = {}
    ok = fail = 0
    for aid, sid, role, fn in rows:
        path = os.path.join(MEDIA_DIR, fn)
        if not os.path.exists(path):
            with tracking.connect() as c:
                c.execute("SET search_path TO migration, public")
                c.execute("""UPDATE asset SET status='missing',
                             exists_on_disk=false WHERE id=%s""", (aid,))
                c.commit()
            fail += 1
            continue
        digest = sha256_of(path)
        if digest in seen:                       # same bytes already uploaded
            a = seen[digest]
            with tracking.connect() as c:
                c.execute("SET search_path TO migration, public")
                c.execute("""UPDATE asset SET status='reused', sha256=%s,
                             sb_asset_id=%s, sb_filename=%s, exists_on_disk=true
                             WHERE id=%s""",
                          (digest, a["id"], a["filename"], aid))
                c.commit()
            ok += 1
            continue
        obj, err = upload_asset(sb, path, fn)
        with tracking.connect() as c:
            c.execute("SET search_path TO migration, public")
            if obj:
                seen[digest] = obj
                c.execute("""UPDATE asset SET status='uploaded', sha256=%s,
                             bytes=%s, sb_asset_id=%s, sb_filename=%s,
                             exists_on_disk=true, uploaded_at=now(), error=NULL
                             WHERE id=%s""",
                          (digest, os.path.getsize(path), obj["id"],
                           obj["filename"], aid))
                ok += 1
                print(f"    uploaded {fn}")
            else:
                c.execute("UPDATE asset SET status='failed', error=%s WHERE id=%s",
                          (err, aid))
                c.execute("""INSERT INTO event (run_id, sharepoint_id, level,
                             stage, message) VALUES (%s,%s,'error','asset',%s)""",
                          (run_id, sid, err))
                fail += 1
                print(f"    !! {fn}: {err}")
            c.commit()
    print(f"  assets ok={ok} failed/missing={fail}")


# ------------------------------------------------------------------ stories

def assets_for(sid):
    with tracking.connect() as c:
        c.execute("SET search_path TO migration, public")
        rows = c.execute("""SELECT role, source_filename, sb_asset_id,
                                   sb_filename
                            FROM asset
                            WHERE sharepoint_id=%s
                              AND status IN ('uploaded','reused')""",
                         (sid,)).fetchall()
    return {(r[0], r[1]): {"id": r[2], "filename": r[3], "alt": "", "name": "",
                           "focus": "", "title": "", "source": "",
                           "copyright": "", "fieldtype": "asset",
                           "meta_data": {}, "is_external_url": False}
            for r in rows}


def cmd_stories(sb, args, run_id):
    folder_cache = {}
    parent_id = ensure_folder(sb, args.folder, folder_cache)

    with tracking.connect() as c:
        c.execute("SET search_path TO migration, public")
        q = """SELECT sharepoint_id, title, entity, entity_short, target_slug,
                      sb_story_id, payload_hash
               FROM story
               WHERE (%s OR is_sample)
                 AND status <> 'uploaded' OR sb_story_id IS NOT NULL
               ORDER BY sharepoint_id"""
        rows = c.execute("""SELECT sharepoint_id, title, entity, entity_short,
                                   target_slug, sb_story_id, payload_hash
                            FROM story WHERE (%s OR is_sample)
                            ORDER BY sharepoint_id""",
                         (args.all_stories,)).fetchall()
    if args.ids:
        want = {int(x) for x in args.ids.split(",")}
        rows = [r for r in rows if r[0] in want]
    if args.limit:
        rows = rows[:args.limit]

    ok = fail = skipped = 0
    for sid, title, entity, short, slug, sb_id, old_hash in rows:
        try:
            st = load_story(sid)
        except FileNotFoundError:
            print(f"  !! {sid}: no built payload")
            fail += 1
            continue

        entity_slug = slugify(entity) if entity else ""
        content, warns = build(st, None, assets=assets_for(sid),
                               entity_slug=entity_slug)
        slug = slug or slugify(title) or f"news-{sid}"
        payload = {"story": {"name": content["title"][:255], "slug": slug,
                             "parent_id": parent_id, "content": content},
                   "publish": 1 if args.publish else 0}
        h = hashlib.sha256(json.dumps(payload, sort_keys=True,
                                      ensure_ascii=False).encode()).hexdigest()

        if sb_id and h == old_hash:
            print(f"  = {sid} unchanged")
            skipped += 1
            continue

        # if the DB lost the id, find the story by slug before creating
        if not sb_id:
            r = sb.get("stories", params={
                "with_slug": f"{args.folder}/{slug}", "per_page": 1})
            if r.status_code == 200:
                for s in r.json().get("stories") or []:
                    if s.get("full_slug") == f"{args.folder}/{slug}":
                        sb_id = s["id"]
                        break

        if sb_id:
            r = sb.put(f"stories/{sb_id}", payload)
            action = "updated"
        else:
            r = sb.post("stories", payload)
            action = "created"

        with tracking.connect() as c:
            c.execute("SET search_path TO migration, public")
            if r is not None and r.status_code in (200, 201):
                story = r.json()["story"]
                c.execute("""UPDATE story SET status='uploaded',
                             sb_story_id=%s, sb_uuid=%s, sb_parent_id=%s,
                             upload_folder=%s, upload_full_slug=%s,
                             payload_hash=%s, attempts=attempts+1,
                             uploaded_at=now(), error=NULL, updated_at=now()
                             WHERE sharepoint_id=%s""",
                          (story["id"], story.get("uuid"), parent_id,
                           args.folder, story.get("full_slug"), h, sid))
                for w in warns:
                    c.execute("""INSERT INTO event (run_id, sharepoint_id,
                                 level, stage, message)
                                 VALUES (%s,%s,'warn','build',%s)""",
                              (run_id, sid, w))
                ok += 1
                nb = len(content["body"])
                print(f"  + {sid} {action}  {story.get('full_slug')}  "
                      f"({nb} bloks, {len(warns)} warnings)")
            else:
                msg = f"{getattr(r, 'status_code', '?')} " \
                      f"{getattr(r, 'text', '')[:400]}"
                c.execute("""UPDATE story SET status='failed', error=%s,
                             attempts=attempts+1, updated_at=now()
                             WHERE sharepoint_id=%s""", (msg, sid))
                c.execute("""INSERT INTO event (run_id, sharepoint_id, level,
                             stage, message) VALUES (%s,%s,'error','story',%s)""",
                          (run_id, sid, msg))
                fail += 1
                print(f"  !! {sid} FAILED  {msg}")
            c.commit()

    print(f"\n  stories created/updated={ok} unchanged={skipped} failed={fail}")
    return ok, fail


def cmd_verify(sb, args, run_id):
    with tracking.connect() as c:
        c.execute("SET search_path TO migration, public")
        rows = c.execute("""SELECT sharepoint_id, sb_story_id, upload_full_slug
                            FROM story WHERE sb_story_id IS NOT NULL
                            ORDER BY sharepoint_id""").fetchall()
    print(f"  verifying {len(rows)} stories")
    good = bad = 0
    for sid, sb_id, slug in rows:
        r = sb.get(f"stories/{sb_id}")
        if r.status_code != 200:
            print(f"  !! {sid}: {r.status_code}")
            bad += 1
            continue
        st = r.json()["story"]
        c_ = st.get("content") or {}
        nb = len(c_.get("body") or [])
        comps = [b.get("component") for b in (c_.get("body") or [])]
        issues = []
        if not c_.get("title"):
            issues.append("no title")
        if nb == 0:
            issues.append("empty body")
        if not st.get("published"):
            issues.append("not published")
        print(f"  {'!!' if issues else 'ok'} {sid} {slug}  {nb} bloks "
              f"{comps}  {'; '.join(issues)}")
        (bad if issues else good).__class__  # noqa
        if issues:
            bad += 1
        else:
            good += 1
        with tracking.connect() as c:
            c.execute("SET search_path TO migration, public")
            c.execute("""UPDATE story SET status=%s, verified_at=now()
                         WHERE sharepoint_id=%s""",
                      ("verified" if not issues else "failed", sid))
            c.commit()
    print(f"\n  verified ok={good} problems={bad}")


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["plan", "assets", "stories", "all",
                                        "verify"])
    ap.add_argument("--folder", default="news/rabee")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ids")
    ap.add_argument("--all-stories", action="store_true")
    ap.add_argument("--draft", dest="publish", action="store_false")
    ap.add_argument("--publish", dest="publish", action="store_true")
    ap.set_defaults(publish=True)
    args = ap.parse_args()

    cfg = load_config()
    if not cfg.get("management_token") or "YOUR_" in str(cfg["management_token"]):
        sys.exit("no Storyblok token — see config/storyblok.json")
    sb = SB(cfg)

    if args.command == "plan":
        with tracking.connect() as c:
            c.execute("SET search_path TO migration, public")
            n = c.execute("""SELECT count(*) FROM story
                             WHERE (%s OR is_sample)""",
                          (args.all_stories,)).fetchone()[0]
            a = c.execute("""SELECT count(*) FROM asset a
                             JOIN story s USING (sharepoint_id)
                             WHERE (%s OR s.is_sample)""",
                          (args.all_stories,)).fetchone()[0]
        print(f"  folder        : {args.folder}")
        print(f"  stories       : {n}")
        print(f"  assets        : {a}")
        print(f"  media on disk : "
              f"{'yes' if os.path.isdir(MEDIA_DIR) else 'NO — assets/News/media missing'}")
        print(f"  publish       : {args.publish}")
        print(f"  space         : {cfg['space_id']}")
        return

    with tracking.connect() as c:
        c.execute("SET search_path TO migration, public")
        run_id = c.execute("""INSERT INTO run (mode, space_id, folder_prefix,
                              note) VALUES (%s,%s,%s,%s) RETURNING id""",
                           (args.command, cfg["space_id"], args.folder,
                            "sample" if not args.all_stories else "full")
                           ).fetchone()[0]
        c.commit()

    ok = fail = 0
    if args.command in ("assets", "all"):
        cmd_assets(sb, args, run_id)
    if args.command in ("stories", "all"):
        ok, fail = cmd_stories(sb, args, run_id)
    if args.command == "verify":
        cmd_verify(sb, args, run_id)

    with tracking.connect() as c:
        c.execute("SET search_path TO migration, public")
        c.execute("""UPDATE run SET finished_at=now(), stories_ok=%s,
                     stories_failed=%s WHERE id=%s""", (ok, fail, run_id))
        c.commit()


if __name__ == "__main__":
    main()
