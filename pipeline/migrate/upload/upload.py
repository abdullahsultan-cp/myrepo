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
    python scripts/migrate/upload/upload.py plan                 # what would happen
    python scripts/migrate/upload/upload.py assets               # upload media only
    python scripts/migrate/upload/upload.py stories              # upload stories
    python scripts/migrate/upload/upload.py all
    python scripts/migrate/upload/upload.py verify               # re-read from the API

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
import re
import sys
import time
from urllib.parse import unquote


try:
    import requests
except ImportError:
    sys.exit("pip install -r requirements.txt")

# paths puts scripts/migrate/ and scripts/ on sys.path, so this has to come
# before the sibling and cross-stage imports below.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import BASE, MEDIA_DIR  # noqa: E402

import db as tracking  # noqa: E402
from build_payload import build, load_story, slugify  # noqa: E402
from storyblok_config import load_config, management_api_base  # noqa: E402

# Paths come from the shared module so this script works for any content
# type; see pipeline/paths_root.py.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from paths_root import P  # noqa: E402

THROTTLE = 0.35          # seconds between write calls; starter plan is modest


class SB:
    """Thin Management API client with retry and rate-limit handling."""

    def __init__(self, cfg):
        self.api = f"{management_api_base(cfg)}/spaces/{cfg['space_id']}"
        self.s = requests.Session()
        self.s.headers.update({"Authorization": cfg["management_token"]})
        self.space = cfg["space_id"]
        # A separate pooled session for the S3 uploads. requests.post() opened a
        # fresh socket per file, leaving thousands in TIME_WAIT -- which is how a
        # run reaches "WinError 10013, socket forbidden": Windows runs out of
        # ephemeral ports. Pooling reuses connections instead.
        self.s3 = requests.Session()

    def _call(self, method, path, *, json_body=None, params=None, tries=5,
              **kw):
        url = path if path.startswith("http") else f"{self.api}/{path}"
        last = None
        for attempt in range(tries):
            try:
                r = self.s.request(method, url, json=json_body, params=params,
                                   timeout=120, **kw)
            except requests.exceptions.RequestException as e:
                # Only 429 and 5xx were retried, so a dropped connection raised
                # straight out and ended the run -- twice, at 95 and 8 minutes.
                # A transient network fault is the most likely thing to happen
                # during a three-hour job, so it is retried like any other.
                if attempt == tries - 1:
                    raise
                wait = 5 * (attempt + 1)
                print(f"      {type(e).__name__} on {method} {path}; "
                      f"retrying in {wait}s ({attempt + 1}/{tries})")
                time.sleep(wait)
                continue
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

# The content tree is owned by the front-end developer and is final. This upload
# must never add to it: a folder it invents would sit alongside the real one,
# look plausible, and quietly collect stories nobody asked for. So the whole tree
# is read-only here and a missing folder is a hard stop, not something to fix.
NO_CREATE = ("regions", "global")


def ensure_folder(sb, path, cache):
    """Resolve a folder path to its leaf id. Never creates under NO_CREATE."""
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
            root = walked.split("/")[0]
            if root in NO_CREATE:
                sys.exit(
                    f"\n  STOPPING: folder {walked!r} does not exist, and this\n"
                    f"  script is not allowed to create anything under "
                    f"{root!r}.\n"
                    f"  The content tree belongs to the front-end developer.\n"
                    f"  Ask for the folder, then re-run:\n"
                    f"      python scripts/migrate/review/dump_sb_tree.py\n"
                    f"      python scripts/migrate/review/verify_folders.py")
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


# ------------------------------------------------------------------ asset tree

def ensure_asset_folder(sb, path, cache):
    """Mirror a story's folder path in the ASSET tree, creating as needed.

    Asset folders are a separate namespace from the content tree, and creating
    them here is explicitly allowed. Filing each story's media alongside where
    the story itself lives is what keeps 3900 assets navigable instead of one
    flat pile.

    `path` is the story's folder path, e.g.
        regions/pakistan/entities/medical-college/departments/cardiology/news
    """
    parent = 0
    walked = ""
    for seg in [p for p in path.split("/") if p]:
        walked = f"{walked}/{seg}" if walked else seg
        if walked in cache:
            parent = cache[walked]
            continue
        r = sb.post("asset_folders", {"asset_folder": {
            "name": seg, "parent_id": parent or None}})
        if r.status_code in (200, 201):
            fid = (r.json().get("asset_folder") or {}).get("id")
            print(f"    asset folder created  {walked}  (id {fid})")
        else:
            # Already there: the API rejects a duplicate name under one parent,
            # so look it up rather than treat it as a failure.
            fid = find_asset_folder(sb, seg, parent)
            if fid is None:
                sys.exit(f"cannot create or find asset folder {walked}: "
                         f"{r.status_code} {r.text[:200]}")
        cache[walked] = fid
        parent = fid
    return parent


def find_asset_folder(sb, name, parent_id):
    r = sb.get("asset_folders")
    if r.status_code != 200:
        return None
    for f in r.json().get("asset_folders") or []:
        if f.get("name") == name and (f.get("parent_id") or 0) == (parent_id or 0):
            return f["id"]
    return None


# ------------------------------------------------------------------ assets

def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def upload_asset(sb, path, filename, asset_folder_id=None):
    """Storyblok asset upload: sign, PUT to S3, finalise."""
    size = os.path.getsize(path)
    ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    body = {"filename": filename, "size": str(size), "content_type": ctype}
    if asset_folder_id:
        body["asset_folder_id"] = asset_folder_id
    r = sb.post("assets", body)
    if r.status_code not in (200, 201):
        return None, f"sign failed {r.status_code} {r.text[:200]}"
    sig = r.json()
    # The S3 PUT goes straight to amazonaws.com, so it does not pass through
    # SB._call and gets none of its retry. A single dropped connection used to
    # raise out of here, out of cmd_assets, and end a 95-minute run --
    # "WinError 10065, unreachable host" after 1,700 successful uploads. Retry
    # with backoff, and reopen the file each time because the handle is consumed.
    up = None
    for attempt in range(5):
        try:
            with open(path, "rb") as fh:
                files = {**{k: (None, v)
                            for k, v in (sig.get("fields") or {}).items()},
                         "file": (filename, fh, ctype)}
                up = sb.s3.post(sig["post_url"], files=files, timeout=300)
            break
        except requests.exceptions.RequestException as e:
            if attempt == 4:
                return None, f"s3 unreachable after 5 tries: {e}"
            wait = 3 * (attempt + 1)
            print(f"      s3 {type(e).__name__}; retrying in {wait}s "
                  f"({attempt + 1}/5)")
            time.sleep(wait)
    if up is None or up.status_code not in (200, 201, 204):
        return None, (f"s3 failed {getattr(up, 'status_code', '?')} "
                      f"{getattr(up, 'text', '')[:200]}")
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
            SELECT a.id, a.sharepoint_id, a.role, a.source_filename,
                   coalesce(s.target_full_slug, '')
            FROM asset a JOIN story s USING (sharepoint_id)
            WHERE a.status IN ('pending','failed','missing')
              AND (%s OR s.is_sample)
            ORDER BY a.sharepoint_id, a.role
        """, (args.all_stories,)).fetchall()

    seen = {}
    folders = {}          # story folder path -> asset folder id
    ok = fail = 0
    total = len(rows)
    t_start = time.time()
    print(f"  {total} assets to upload")

    def progress(n):
        """Position, rate and an ETA, so a long stage is visibly alive."""
        el = time.time() - t_start
        rate = n / el * 60 if el > 0 else 0
        left = (total - n) / rate if rate > 0 else 0
        return (f"[{n}/{total} {100 * n / total:.0f}%  "
                f"{rate:.0f}/min  ~{left:.0f} min left]")

    for n, (aid, sid, role, fn, full_slug) in enumerate(rows, 1):
        # Each story's media is filed under the same hierarchy as the story, so
        # an editor looking for an article's images knows where to look. Asset
        # folders are a separate namespace from the content tree, so creating
        # them is allowed where creating a content folder is not.
        #
        # full_slug ends with the story's own slug; the folder is everything
        # before it, e.g. regions/pakistan/entities/medical-college/news
        afid = None
        story_folder = full_slug.rsplit("/", 1)[0] if "/" in full_slug else ""
        if story_folder:
            afid = ensure_asset_folder(sb, story_folder, folders)
        path = os.path.join(MEDIA_DIR, fn)
        if not os.path.exists(path):
            with tracking.connect() as c:
                c.execute("SET search_path TO migration, public")
                c.execute("""UPDATE asset SET status='missing',
                             exists_on_disk=false WHERE id=%s""", (aid,))
                c.commit()
            fail += 1
            print(f"    {progress(n)} MISSING on disk  {fn}")
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
            print(f"    {progress(n)} reused           {fn}")
            continue
        # Nothing about one asset should be able to end the run. Anything the
        # retries above did not absorb is recorded against that asset and the
        # loop moves on; a re-run picks it up because its status is not
        # 'uploaded'.
        try:
            obj, err = upload_asset(sb, path, fn, asset_folder_id=afid)
        except Exception as e:                       # noqa: BLE001
            obj, err = None, f"{type(e).__name__}: {e}"[:400]
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
                print(f"    {progress(n)} uploaded  {role:<10} {fn}")
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

LOCAL_PREFIX = re.compile(r"^\d+-[a-z0-9]+-[0-9a-f]{6,}-")


def media_key(name):
    """A filename reduced to something that matches across renamings.

    The downloader rewrote "Dar (2).jpeg" as "3405-richtext-<hash>-Dar-2.jpeg",
    so neither the basename nor the stem compares equal to the source. Stripping
    the prefix and keeping only alphanumerics makes both sides land on
    "dar2.jpeg", which is enough to be unique within one story.
    """
    base = os.path.basename(unquote((name or "").split("?")[0]))
    base = LOCAL_PREFIX.sub("", base)
    stem, ext = os.path.splitext(base)
    stem = re.sub(r"[^a-z0-9]+", "", stem.lower())
    return f"{stem}{ext.lower()}" if stem else ""


def assets_for(sid):
    with tracking.connect() as c:
        c.execute("SET search_path TO migration, public")
        rows = c.execute("""SELECT role, source_filename, sb_asset_id,
                                   sb_filename, coalesce(source_url, '')
                            FROM asset
                            WHERE sharepoint_id=%s
                              AND status IN ('uploaded','reused')""",
                         (sid,)).fetchall()
    def obj(aid, fn):
        return {"id": aid, "filename": fn, "alt": "", "name": "", "focus": "",
                "title": "", "source": "", "copyright": "",
                "fieldtype": "asset", "meta_data": {}, "is_external_url": False}

    out = {(r[0], r[1]): obj(r[2], r[3]) for r in rows}
    # A body image node carries whatever src the enhance step left on it: a
    # /news-media/ path in some runs, the absolute aku.edu URL in others. So key
    # a second time on a normalised form of the ORIGINAL filename, which the
    # local name still carries after its "{id}-{role}-{hash}-" prefix. Without
    # this the lookup silently resolves to nothing and every inline image is
    # dropped from the article.
    for role, local_fn, aid, sb_fn, src_url in rows:
        for cand in (src_url or "", local_fn or ""):
            k = media_key(cand)
            if k:
                out.setdefault(("by_key", k), obj(aid, sb_fn))
    return out


def entity_folder_ids():
    """{(region_slug, entity_slug): folder_id} from the live-tree snapshot.

    `entities` on news_article is a list of entity FOLDER IDS, so the ids have
    to come from the space rather than be derived. dump_sb_tree.py writes the
    snapshot; it is read here rather than re-fetched so a story upload cannot
    silently depend on a live listing call.
    """
    p = os.path.join(P.MIGRATE, "sb_folder_tree.json")
    if not os.path.exists(p):
        sys.exit("missing data/migrate/sb_folder_tree.json — run\n"
                 "  python scripts/migrate/review/dump_sb_tree.py")
    with open(p, encoding="utf-8") as f:
        folders = json.load(f)["folders"]
    out = {}
    for x in folders:
        parts = x["full_slug"].split("/")
        # regions/<region>/entities/<entity>
        if len(parts) == 4 and parts[0] == "regions" and parts[2] == "entities":
            out[(parts[1], parts[3])] = x["id"]
    return out


def entities_for(sid, region, entity, folder_ids, warn):
    """The story's own entity folder plus every entity it is shared into."""
    ids, seen = [], set()

    def add(reg, ent):
        if not reg or not ent:
            return
        key = (slugify(reg), slugify(ent))
        fid = folder_ids.get(key)
        if fid is None:
            warn.append(f"no entity folder for {key[0]}/{key[1]}")
            return
        if fid not in seen:
            seen.add(fid)
            ids.append(fid)

    add(region, entity)
    with tracking.connect() as c:
        c.execute("SET search_path TO migration, public")
        for reg, ent in c.execute("""SELECT ref_region, ref_entity
                                     FROM share_target
                                     WHERE sharepoint_id=%s""",
                                  (sid,)).fetchall():
            add(reg, ent)
    return ids


def cmd_stories(sb, args, run_id):
    folder_cache = {}
    # --folder pins every story to one place, which is what the review sample
    # wanted. Without it each story goes to its real destination, computed by the
    # taxonomy. That folder must already exist: ensure_folder refuses to create
    # under regions/ or global/.
    fixed_parent = ensure_folder(sb, args.folder, folder_cache) \
        if args.folder else None
    folder_ids = entity_folder_ids()
    print(f"  {len(folder_ids)} entity folders available for 'entities'")
    if fixed_parent is None:
        print("  routing each story to its own folder from the taxonomy")

    with tracking.connect() as c:
        c.execute("SET search_path TO migration, public")
        rows = c.execute("""SELECT sharepoint_id, title, region, entity,
                                   target_slug, sb_story_id, payload_hash,
                                   surface_global, coalesce(target_full_slug,'')
                            FROM story WHERE (%s OR is_sample)
                            ORDER BY sharepoint_id""",
                         (args.all_stories,)).fetchall()
    if args.ids:
        want = {int(x) for x in args.ids.split(",")}
        rows = [r for r in rows if r[0] in want]
    if args.limit:
        rows = rows[:args.limit]

    ok = fail = skipped = 0
    for (sid, title, region, entity, slug, sb_id, old_hash,
         surface_global, target_full_slug) in rows:
        try:
            st = load_story(sid)
        except FileNotFoundError:
            print(f"  !! {sid}: no built payload")
            fail += 1
            continue

        slug = slug or slugify(title) or f"news-{sid}"
        if fixed_parent is not None:
            parent_id, folder_path = fixed_parent, args.folder
        else:
            if "/" not in target_full_slug:
                print(f"  !! {sid}: no target_full_slug; run the taxonomy")
                fail += 1
                continue
            folder_path = target_full_slug.rsplit("/", 1)[0]
            slug = target_full_slug.rsplit("/", 1)[1] or slug
            try:
                parent_id = ensure_folder(sb, folder_path, folder_cache)
            except SystemExit:
                raise
        full_slug = f"{folder_path}/{slug}"

        warns = []
        ents = entities_for(sid, region, entity, folder_ids, warns)
        content, warns = build(st, None, assets=assets_for(sid),
                               entities=ents, is_global=bool(surface_global),
                               warn=warns)
        payload = {"story": {"name": content["title"][:255], "slug": slug,
                             "parent_id": parent_id, "content": content},
                   "publish": 1 if args.publish else 0}
        h = hashlib.sha256(json.dumps(payload, sort_keys=True,
                                      ensure_ascii=False).encode()).hexdigest()

        if sb_id and h == old_hash:
            print(f"  = {sid} unchanged")
            skipped += 1
            continue

        # The DB is the primary record of what exists, but it is not the only
        # one. If it was lost or reset, creating blind would duplicate every
        # story, so the destination slug is checked first. This is what makes a
        # resumed run safe.
        if not sb_id:
            r = sb.get("stories", params={"with_slug": full_slug,
                                          "per_page": 1})
            if r is not None and r.status_code == 200:
                for s in r.json().get("stories") or []:
                    if s.get("full_slug") == full_slug and not s.get("is_folder"):
                        sb_id = s["id"]
                        print(f"    {sid}: already in the space, updating")
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
                           folder_path, story.get("full_slug"), h, sid))
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
    # No default: the real migration routes each story to its own folder from
    # the taxonomy. Passing --folder pins them all to one place instead, which
    # is only what a review sample wants.
    ap.add_argument("--folder", default=None,
                    help="pin every story to this one folder (review only)")
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
