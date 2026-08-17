#!/usr/bin/env python3
"""
sb_backup.py — back up complete Storyblok spaces into per-site git repos.

READ ONLY against Storyblok. Every request is a GET; nothing in a space is
created, updated or deleted. The only writes are to local disk and, with
--push, to each repo's git remote.

AKUH, AKU and AKUEB are three separate spaces with three separate component
libraries, and each one gets its own repo. Nothing is shared between them.

What is captured, per site:

    schema      components (content types), component groups, presets,
                datasources and every datasource entry, internal tags,
                field-type plugins
    settings    the space record, roles, webhooks, workflows and stages,
                releases, tasks, deployment branches
    content     one JSON file per story, holding its full draft content
    assets      assets.json metadata AND the binary of every file, committed
                through Git LFS
    tools       a copy of these scripts, so the repo restores on its own

Usage (from the repo root):
    python pipeline/migrate/spaces/sb_backup.py --check      credentials only
    python pipeline/migrate/spaces/sb_backup.py --site AKU
    python pipeline/migrate/spaces/sb_backup.py --site all
    python pipeline/migrate/spaces/sb_backup.py --site all --push
    python pipeline/migrate/spaces/sb_backup.py --site AKUEB --only schema,stories
    python pipeline/migrate/spaces/sb_backup.py --site AKUH --no-assets

Credentials come from config/sites.json (gitignored — see
config/sites.example.json), or from SB_TOKEN_AKUH / SB_TOKEN_AKU /
SB_TOKEN_AKUEB in the environment, which is what CI should use.

This is a different job from migrate/review/backup.py, which snapshots one
content type's stories for the SharePoint migration. This backs up whole spaces
— schema, assets and all — for three sites that are not this migration.

Two choices worth knowing about, both about keeping git history readable:

  * One file per story, not one big stories_full.json. A single-file dump of a
    few thousand stories is tens of megabytes, and editing one story then
    produces a diff nobody can read.
  * No timestamp in any tracked file. A "taken_at" field guarantees a commit on
    every run even when nothing changed. The commit date already records when
    the snapshot was taken, so an unchanged space produces no commit at all.
"""

import argparse
import csv
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sb_common import (
    CDN_HOSTS,
    asset_path,
    fetch_list,
    folder_path_map,
    get,
    git,
    have_lfs,
    install_tools,
    load_json,
    load_sites,
    pick_sites,
    repo_paths,
    save,
    space_api,
    token_for,
    write_csv,
    write_json,
)
from sb_portal import build_assets_portal
from sb_storage import make_backend

# name -> (path, key holding the list, paginated)
#
# Ordered cheapest first, so a credential or permission problem shows up in the
# first second rather than after the assets have finished downloading.
RESOURCES = [
    ("components",        "components",        "components",        True),
    ("component_groups",  "component_groups",  "component_groups",  False),
    ("presets",           "presets",           "presets",           False),
    ("internal_tags",     "internal_tags",     "internal_tags",     True),
    ("datasources",       "datasources",       "datasources",       True),
    ("asset_folders",     "asset_folders",     "asset_folders",     False),
    ("space_roles",       "space_roles",       "space_roles",       False),
    ("webhook_endpoints", "webhook_endpoints", "webhook_endpoints", False),
    ("workflows",         "workflows",         "workflows",         False),
    ("workflow_stages",   "workflow_stages",   "workflow_stages",   False),
    ("releases",          "releases",          "releases",          False),
    ("tasks",             "tasks",             "tasks",             False),
    ("branches",          "branches",          "branches",          False),
    # Installed apps and extensions. Storyblok exposes these under more than one
    # name depending on the plan and the token, and a space with none simply
    # 403s or 404s, so all three are tried and whichever answers is kept.
    # Recorded for reference, not restored: a marketplace app is installed
    # through an OAuth flow a script cannot drive. RESTORE.md lists them as a
    # manual step, which is better than a silent gap.
    ("apps",              "apps",              "apps",              False),
    ("app_provisions",    "app_provisions",    "app_provisions",    False),
    ("extensions",        "extensions",        "extensions",        False),
]

# Not fetched, on purpose:
#   /api_keys       the space's own access tokens. Live credentials, and this
#                   output is committed to a remote.
#   /collaborators  real_email, alt_email and the full name of every member.
#                   Personal data, and not needed to restore content.
#                   --collaborators if you are deliberately capturing access.
#   /activities     an audit log that grows without bound and restores nothing.
#                   --activities if you want it.

# Everything under assets/ goes to Git LFS, with these excepted because they
# diff usefully as text.
#
# A catch-all rather than a list of binary extensions, for two reasons. A list
# has to predict what editors will upload, and the format it misses -- .heic,
# .dwg, .indd -- lands in normal git objects and stays in history forever. And
# gitattributes matching is case-sensitive, so a list needs every pattern
# twice; a photo saved as .JPG is exactly the file you least want stored raw.
LFS_TEXT_EXCEPTIONS = ["svg", "json", "txt", "csv", "xml", "md", "srt", "vtt"]


# --------------------------------------------------------------------------
# assets
# --------------------------------------------------------------------------

def rel_path(asset, space_id):
    """The asset's path relative to the storage root.

    `asset_path` yields "assets/<mirrored>"; the leading segment is dropped
    because the storage root already IS that folder -- which is what lets the
    same relative path address a file in the repo, on a share, or as a blob.
    """
    rel = asset_path(asset, space_id)
    if not rel:
        return None
    rel = rel.split(os.sep, 1)[1] if os.sep in rel else rel
    return rel.replace(os.sep, "/")


def download_assets(assets, store, space_id, prev_sha=None, workers=6,
                    force=None):
    """Send every binary not already stored at the right size to `store`.

    Nothing is staged for the whole space: each file streams from Storyblok
    through a single temp file -- which is what makes the checksum trustworthy,
    see sb_storage._hash_and_spool -- and straight into the container.

    A file already stored at the right size keeps the checksum the last run
    recorded rather than being read back. Re-hashing 42 GB nightly would make
    the job unaffordable, and a checksum nobody can afford to compute is a
    checksum nobody has. A stored file with no checksum on record is hashed once
    and carried from then on.
    """
    prev_sha = prev_sha or {}
    # What is already there, in one listing rather than a probe per file.
    print("      listing what is already stored", flush=True)
    present = store.list_all()
    print(f"      {len(present)} file(s) already in storage", flush=True)
    jobs = []
    for a in assets:
        rel, url = rel_path(a, space_id), a.get("filename")
        if rel and url:
            jobs.append((a, url, rel))

    got = skipped = failed = rehashed = 0
    errors, sha, lock, total = [], {}, threading.Lock(), len(jobs)

    def one(job):
        a, url, rel = job
        aid = a.get("id")
        try:
            expected = int(a.get("content_length") or 0)
        except (TypeError, ValueError):
            expected = 0
        try:
            stored = present.get(rel)
            # `force` exists because skipping by size cannot see corruption that
            # kept the size: eight bytes overwritten by eight other bytes is a
            # broken file the fast path will skip forever. --repair feeds the
            # deep audit's findings in here so they are actually re-fetched.
            if str(aid) in (force or ()):
                stored = None
            if stored is not None and (not expected or stored == expected):
                known = prev_sha.get(str(aid))
                if known:
                    return "skip", None, aid, known
                digest = store.sha256(rel)
                return "rehash", None, aid, digest

            # Retried around the WHOLE fetch, not just the opening request.
            # get() already retries a request that fails to start, but these
            # bodies stream: the connection can be reset part way through a
            # 40 MB image long after a 200 came back, and that break happens
            # inside iter_content where the earlier retry could not see it. It
            # cost 21 of AKU's assets before this existed.
            # MemoryError is in here deliberately, and it is not paranoia: seven
            # of AKUEB's files died on it, and they were 1-11 MB each, so it was
            # never about their size. It is this process running out of room --
            # six workers each holding a spooled copy while the Azure SDK stages
            # blocks alongside them -- and it clears on its own moments later.
            # Left uncaught it skipped straight to "failed" with no retry at all,
            # because MemoryError is neither a RequestException nor an OSError.
            #
            # Five attempts rather than three because three was not enough: four
            # more files were lost to connections reset on every one of them.
            RETRIABLE = (requests.exceptions.RequestException, OSError,
                         MemoryError)
            last = None
            for attempt in range(5):
                try:
                    r = get(url, stream=True)   # no token: asset URLs are public
                    if r.status_code != 200:
                        return "fail", f"{aid} {url} -> {r.status_code}", aid, None
                    digest, _ = store.write(rel, r.iter_content(65536),
                                            a.get("content_type"),
                                            expected or None)
                    return "ok", None, aid, digest
                except RETRIABLE as e:
                    last = e
                    time.sleep(min(3 * (attempt + 1), 20))
            raise last
        except Exception as e:
            # Broad on purpose: one unreadable asset out of thousands must be
            # reported and skipped, not end the run. The type and message go
            # into _summary.json so it stays visible afterwards.
            return "fail", f"{aid} {url} -> {type(e).__name__}: {e}", aid, None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, j) for j in jobs]
        for n, fut in enumerate(as_completed(futures), 1):
            status, err, aid, digest = fut.result()
            with lock:
                if status == "ok":
                    got += 1
                elif status in ("skip", "rehash"):
                    skipped += 1
                    rehashed += status == "rehash"
                else:
                    failed += 1
                    errors.append(err)
                    # Printed now, not just collected: a later stall would
                    # otherwise take the only record of why 14 files failed.
                    if failed <= 20:
                        print(f"      FAILED {err}", flush=True)
                if digest:
                    sha[str(aid)] = digest
            if n % 100 == 0 or n == total:
                print(f"      {n}/{total}  stored {got}  "
                      f"already had {skipped}  failed {failed}", flush=True)

    if rehashed:
        print(f"      checksummed {rehashed} existing file(s) for the first time")

    # Sorted, not in completion order: these land in the committed
    # _summary.json, and thread scheduling would otherwise reshuffle the same
    # failures into a fresh diff on every run.
    return {"downloaded": got, "already_present": skipped, "failed": failed,
            "sha": sha, "errors": sorted(e for e in errors if e)[:50]}


def verify_assets(assets, store, space_id, prev_sha, workers=6, quick=False):
    """Re-read what is stored and compare against the recorded checksums.

    The backup is in two halves -- git holds the index, the container holds the
    bytes -- and this is what proves they still match. Run it before relying on
    a restore: a half-finished sync or silent bit-rot looks exactly like a
    complete backup until something reads the files.

    `quick` trusts the sha256 recorded on the blob at upload time instead of
    reading 31 GB back out. That checks what was uploaded, not what is there
    now, so it catches a missing or replaced file but not corruption in place.
    """
    ok = missing = mismatched = unknown = 0
    bad, broken, lock = [], set(), threading.Lock()
    present = store.list_all()
    # In quick mode the checksums come from the same listing rather than one
    # request per blob. 16,334 sequential metadata reads is what made AKUEB's
    # audit look hung; the listing already carries them.
    meta_sha = {}
    if quick and hasattr(store, "list_all_sha256"):
        meta_sha = store.list_all_sha256()
    jobs = [(a, rel_path(a, space_id)) for a in assets]
    jobs = [(a, r) for a, r in jobs if r]

    def one(job):
        a, rel = job
        aid = str(a.get("id"))
        if rel not in present:
            return "missing", f"MISSING  {aid}  {rel}", aid
        want = prev_sha.get(aid)
        if not want:
            return "unknown", None, aid
        if quick and meta_sha:
            got_sha = meta_sha.get(rel)
            if got_sha is None:
                return "unknown", None, aid
        elif quick and hasattr(store, "stored_sha256"):
            got_sha = store.stored_sha256(rel)
            if got_sha is None:
                return "unknown", None, aid
        else:
            got_sha = store.sha256(rel)
        if got_sha == want:
            return "ok", None, aid
        return "mismatch", f"CHANGED  {aid}  {rel}", aid

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, j) for j in jobs]
        for n, fut in enumerate(as_completed(futures), 1):
            kind, msg, aid = fut.result()
            with lock:
                if kind == "ok":
                    ok += 1
                elif kind == "missing":
                    missing += 1
                    broken.add(aid)
                elif kind == "mismatch":
                    mismatched += 1
                    broken.add(aid)
                else:
                    unknown += 1
                if msg:
                    bad.append(msg)
            if n % 250 == 0 or n == len(jobs):
                print(f"      checked {n}/{len(jobs)}", flush=True)

    return {"ok": ok, "missing": missing, "mismatched": mismatched,
            "no_checksum": unknown, "problems": sorted(bad)[:50],
            "bad_ids": sorted(broken)}


# --------------------------------------------------------------------------
# stories
# --------------------------------------------------------------------------

def read_prev_stories(outdir):
    """{story id: updated_at} from the manifest the last run committed.

    What makes a repeat backup quick. The story list arrives with updated_at
    already on it, so a story whose timestamp has not moved and whose file is
    still on disk needs no request at all -- and on a weekly run that is nearly
    all of them. Without this, AKU's 7,126 stories plus 7,126 published versions
    are re-fetched in full every time, which is forty minutes to learn that
    nothing changed.
    """
    path = os.path.join(outdir, "manifest_stories.csv")
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("id") and row.get("updated_at"):
                out[row["id"]] = row["updated_at"]
    return out


def download_stories(api, token, stories, outdir, workers=5, prev=None,
                     full=False):
    """One file per story, holding the full draft content.

    The list endpoint omits `content`, so each story needs its own GET. Named
    by id, not slug: the slug is what changes when a folder tree is
    reorganised, and a slug-named file turns a rename into a delete plus an
    add, losing that story's history.
    """
    story_dir = os.path.join(outdir, "stories")
    os.makedirs(story_dir, exist_ok=True)
    keep = {str(s["id"]) for s in stories if s.get("id") is not None}
    prev = {} if full else (prev or {})

    # Untouched since the last run, and still on disk: no request needed. This is
    # also what makes an interrupted run cheap to continue -- whatever it already
    # wrote is simply skipped.
    todo, reused = [], 0
    for st in stories:
        sid = str(st.get("id"))
        was = prev.get(sid)
        if (was and st.get("updated_at") == was
                and os.path.exists(os.path.join(story_dir, f"{sid}.json"))):
            reused += 1
            continue
        todo.append(st)
    if reused:
        print(f"      {reused} unchanged since the last run, "
              f"{len(todo)} to fetch", flush=True)
    stories = todo

    ok, failed, errors, lock = 0, 0, [], threading.Lock()
    # Collected while each story is in hand. The manifest needs the component
    # and the asset references, and re-reading several thousand files afterwards
    # to get them would double the disk work for data we already had.
    meta = {}
    total = len(stories)

    def one(st):
        sid = st.get("id")
        r = get(f"{api}/stories/{sid}", token)
        if r.status_code != 200:
            return f"{sid} {st.get('full_slug')} -> {r.status_code}", None
        story = r.json().get("story")
        if not story:
            return f"{sid} -> empty body", None
        write_json(os.path.join(story_dir, f"{sid}.json"), story)
        content = story.get("content") or {}
        return None, (sid, {
            "component": content.get("component") or "",
            "assets": len(_asset_urls(content)),
            "updated_at": story.get("updated_at") or "",
            "uuid": story.get("uuid") or "",
        })

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, s) for s in stories]
        for n, fut in enumerate(as_completed(futures), 1):
            err, got = fut.result()
            with lock:
                if err:
                    failed += 1
                    errors.append(err)
                else:
                    ok += 1
                    meta[got[0]] = got[1]
            if n % 250 == 0 or n == total:
                print(f"      {n}/{total}  saved {ok}  failed {failed}",
                      flush=True)

    # A story deleted in the space has to disappear from the backup, or the
    # snapshot stops being a snapshot and becomes an accumulation. Git keeps the
    # removed file in history, which is where it belongs.
    removed = 0
    for fn in os.listdir(story_dir):
        if fn.endswith(".json") and fn[:-5] not in keep:
            os.remove(os.path.join(story_dir, fn))
            removed += 1

    # The skipped stories still need their manifest row, so their component and
    # asset count are read back off disk. Cheap: local reads, no network.
    for sid in keep - {str(k) for k in meta}:
        st = load_json(os.path.join(story_dir, f"{sid}.json"))
        if not st:
            continue
        content = st.get("content") or {}
        meta[int(sid)] = {"component": content.get("component") or "",
                          "assets": len(_asset_urls(content)),
                          "updated_at": st.get("updated_at") or "",
                          "uuid": st.get("uuid") or ""}

    return {"saved": ok, "reused": reused, "failed": failed,
            "deleted_since_last_run": removed,
            "errors": sorted(errors)[:50], "meta": meta}


def download_published(space_id, region, token, stories, outdir, workers=5,
                       prev=None, full=False):
    """The PUBLISHED version of every published story, beside the drafts.

    This is not a nicety. The Management API returns the draft, and on AKUH 231
    stories have unpublished changes -- so for those, what visitors see is not
    what stories/<id>.json holds. Restoring drafts over a live site would publish
    work in progress, which is a data-loss bug wearing the costume of a restore.

    Reached through the Content Delivery API, which is the only place the
    published version exists, using the space's own delivery token. That token is
    read from the space record and never written anywhere -- save() scrubs
    first_token, and this function does not persist it.
    """
    pub_dir = os.path.join(outdir, "stories_published")
    os.makedirs(pub_dir, exist_ok=True)
    cdn = CDN_HOSTS.get((region or "eu").lower(), CDN_HOSTS["eu"])

    live = [s for s in stories
            if s.get("published") and not s.get("is_folder") and s.get("id")]
    keep = {str(s["id"]) for s in live}
    prev = {} if full else (prev or {})
    reused = 0
    fetch = []
    for st in live:
        sid = str(st["id"])
        if (prev.get(sid) == st.get("updated_at")
                and os.path.exists(os.path.join(pub_dir, f"{sid}.json"))):
            reused += 1
            continue
        fetch.append(st)
    if reused:
        print(f"      {reused} unchanged, {len(fetch)} to fetch", flush=True)
    live = fetch
    ok, failed, errors, lock = 0, 0, [], threading.Lock()

    def one(st):
        sid = st["id"]
        r = get(f"{cdn}/stories/{sid}",
                params={"token": token, "version": "published",
                        "cv": 0, "find_by": "id"})
        if r.status_code == 404:
            # Published in the index but absent from the delivery API: usually a
            # story published then unpublished. Not an error, but recorded.
            return f"{sid} {st.get('full_slug')} -> 404 (not live)"
        if r.status_code != 200:
            return f"{sid} {st.get('full_slug')} -> {r.status_code}"
        story = (r.json() or {}).get("story")
        if not story:
            return f"{sid} -> empty body"
        write_json(os.path.join(pub_dir, f"{sid}.json"), story)
        return None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, s) for s in live]
        for n, fut in enumerate(as_completed(futures), 1):
            err = fut.result()
            with lock:
                if err:
                    failed += 1
                    errors.append(err)
                else:
                    ok += 1
            if n % 250 == 0 or n == len(live):
                print(f"      {n}/{len(live)}  saved {ok}  missing {failed}",
                      flush=True)

    removed = 0
    for fn in os.listdir(pub_dir):
        if fn.endswith(".json") and fn[:-5] not in keep:
            os.remove(os.path.join(pub_dir, fn))
            removed += 1

    return {"saved": ok, "reused": reused, "failed": failed,
            "removed": removed, "errors": sorted(errors)[:50]}


# --------------------------------------------------------------------------
# the manifests -- what a person reads
# --------------------------------------------------------------------------

# A Storyblok asset URL, recognised by its `/f/<space id>/` path segment rather
# than by its host. Hosts vary -- a.storyblok.com, the S3 form
# s3.amazonaws.com/a.storyblok.com/..., and a custom asset domain on the paid
# plans -- so matching on the word "storyblok" reports zero assets for any space
# that uses its own domain, and reports it silently.
_ASSET_URL = re.compile(r"""https?://[^\s"'<>)\]]*?/f/\d+/[^\s"'<>)\]]*""")


def _asset_urls(obj, found=None):
    """Every distinct asset URL anywhere in a content tree.

    Walks every string rather than the named fields, because the same reference
    appears three ways: an asset object's `filename`, a rich-text image node's
    `attrs.src`, and bare URLs written into prose. Counting only the tidy fields
    under-reports exactly the stories that would break in a restore.

    findall, not a substring test, so a paragraph mentioning two assets counts
    as two.
    """
    if found is None:
        found = set()
    if isinstance(obj, dict):
        for v in obj.values():
            _asset_urls(v, found)
    elif isinstance(obj, list):
        for v in obj:
            _asset_urls(v, found)
    elif isinstance(obj, str) and "/f/" in obj:
        found.update(_ASSET_URL.findall(obj))
    return found


def write_story_manifest(outdir, stories, story_meta):
    """Which story sits in which folder, as one sorted line each.

    The JSON holds all of this already, but nobody audits a 4,000-story tree by
    following parent_id chains. Sorted by full_slug and one row per story, so a
    story that moved shows up as a moved line in `git diff` instead of a changed
    integer buried in a story file.
    """
    story_folders = [s for s in stories if s.get("is_folder")]
    fpaths = folder_path_map(story_folders, name_key="slug")

    rows = []
    for s in stories:
        sid = s.get("id")
        m = story_meta.get(sid, {})
        parent = s.get("parent_id")
        rows.append([
            sid,
            m.get("uuid") or s.get("uuid") or "",
            "folder" if s.get("is_folder") else "story",
            s.get("full_slug") or "",
            fpaths.get(parent, "") if parent else "(root)",
            s.get("name") or "",
            m.get("component", ""),
            "published" if s.get("published") else "draft",
            "yes" if s.get("unpublished_changes") else "",
            m.get("assets", ""),
            "" if s.get("is_folder") else f"stories/{sid}.json",
            m.get("updated_at", ""),
        ])
    rows.sort(key=lambda r: (str(r[3]), str(r[0])))
    return write_csv(
        os.path.join(outdir, "manifest_stories.csv"),
        ["id", "uuid", "kind", "full_slug", "parent_folder", "name",
         "component", "state", "unpublished_changes", "assets_referenced",
         "backup_file", "updated_at"],
        rows)


def required_field_plugins(components):
    """Which custom field plugins the schema depends on, read from the schema.

    /field_types rejects a personal access token, so the plugins' own definitions
    cannot be captured -- but every component schema names the plugin each custom
    field uses, so the *requirement* is recoverable even when the definition is
    not. AKUH turns out to need five (sb-ai-seo, seo-metatags,
    native-color-picker, workflow-options-field-1, storyblok-colorpicker) across
    41 fields.

    This matters at restore time: field plugins are account-level and have no
    create API, so they must already exist on the target account or every
    component using one will not save correctly. Knowing the list beforehand is
    the difference between a restore that works and one that half-works quietly.
    """
    out = {}
    for c in components or []:
        for fname, f in (c.get("schema") or {}).items():
            if (f or {}).get("type") != "custom":
                continue
            plug = f.get("field_type") or "(unnamed)"
            entry = out.setdefault(plug, {"fields": 0, "components": []})
            entry["fields"] += 1
            if c.get("name") not in entry["components"]:
                entry["components"].append(c["name"])
    for entry in out.values():
        entry["components"].sort()
    return out


def read_prev_sha(outdir):
    """{asset id: sha256} from the manifest the last run committed.

    Read before anything is downloaded, because it is what lets a skipped file
    keep its checksum instead of being re-hashed.
    """
    path = os.path.join(outdir, "manifest_assets.csv")
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("sha256") and row.get("id"):
                out[row["id"].strip()] = row["sha256"].strip()
    return out


def write_asset_manifest(assets, asset_folders, space_id, outdir, store,
                         external, sha):
    """Where every asset is in the space, and where its bytes actually are.

    This file is the join between the two halves of the backup: git holds it,
    the bucket holds the files it points at. `file_present` and `sha256` are the
    columns that matter -- an asset with metadata but no bytes would be
    recreated as an empty asset by a rebuild, and every story pointing at it
    would render broken. Better to see that here than after a restore.
    """
    apaths = folder_path_map(asset_folders or [])
    # One listing, not one call per asset. Asking the container per file is
    # 5,767 sequential round-trips for AKUH and 16,334 for AKUEB, which makes a
    # finished upload look like a hung run.
    present = store.list_all()
    arows = []
    for a in assets:
        rel = rel_path(a, space_id) or ""
        arows.append([
            a.get("id"),
            os.path.basename(a.get("filename") or "") or "",
            apaths.get(a.get("asset_folder_id"), "(root)"),
            rel,
            "yes" if rel and rel in present else "NO",
            sha.get(str(a.get("id")), ""),
            a.get("content_type") or "",
            a.get("content_length") or "",
            a.get("alt") or "",
            a.get("filename") or "",
        ])
    arows.sort(key=lambda r: (str(r[2]), str(r[1]), str(r[0])))
    n = write_csv(
        os.path.join(outdir, "manifest_assets.csv"),
        ["id", "filename", "asset_folder", "backup_file", "file_present",
         "sha256", "content_type", "bytes", "alt", "url"],
        arows)

    # Where the bytes live, recorded beside the index that points at them. The
    # absolute path is deliberately NOT committed -- it is one person's drive
    # letter, it differs per machine, and it would churn the diff.
    # The kind of store, never the credentials or the machine-specific path: an
    # account name and container are fine to commit, a connection string is not.
    kind = type(store).__name__.replace("Backend", "").lower()
    where = store.label if kind == "azure" else None
    write_json(os.path.join(outdir, "assets_location.json"), {
        "external": external,
        "backend": kind,
        "location": where,
        "note": ("Binaries are stored outside this repository. Point this site's "
                 "'assets' block in config/sites.json at the location above (or "
                 "pass --assets-dir); the paths in manifest_assets.csv are "
                 "relative to it."
                 if external else
                 "Binaries are committed to this repository under "
                 "storyblok/assets/, via Git LFS."),
        "backup_file_paths_are_relative_to": (where or "<assets_dir>") if external
        else "storyblok/assets/",
        "files": n,
    })
    return n


# --------------------------------------------------------------------------
# the documents that travel with the backup
# --------------------------------------------------------------------------

def write_repo_docs(repo, site, external):
    """Write README.md, CLAUDE.md and RESTORE.md into the backup repo.

    A backup is only as good as someone's ability to use it under pressure, and
    the person opening this repo in a year will not be whoever set it up. So the
    repo explains itself: what each file is, what is missing, and the exact
    commands to put it back.

    Deliberately free of counts and timestamps. Numbers live in _summary.json
    and the manifests; putting them here would rewrite three documents on every
    run and bury the real changes.
    """
    name = site["name"]
    sub = site.get("subdir", "storyblok")
    space = site["space_id"]
    region = site.get("region", "eu")
    where = ("**outside this repo**, on the bucket or share configured as "
             "`assets_dir`" if external else
             f"in `{sub}/assets/`, committed through Git LFS")

    readme = f"""# {name} — Storyblok backup

Complete backup of the **{name}** Storyblok space (`{space}`, region `{region}`),
and everything needed to put it back. See [RESTORE.md](RESTORE.md) for that.

**Media files are {where}.**

## One command

```
python tools/sb.py doctor          is everything in place?
python tools/sb.py backup --push   THE ONE CLICK: back up, commit, push
python tools/sb.py audit           prove the backup covers the whole space
```

Or double-click `backup.cmd` (Windows) / run `./backup.sh`.

First time in a fresh clone:

```
python -m pip install -r tools/requirements.txt
python tools/sb.py setup           writes tools/sites.json, prefilled
                                   — paste the two secrets into it
python tools/sb.py doctor
```

**This repo is self-sustaining.** `tools/` holds the entire backup and restore
pipeline, so nothing outside this checkout is needed to back up, verify or
restore. It can even stand up a sibling repo for another space:

```
python tools/sb.py init ../other-backups --name AKUEB --space 123456
```

Everything else:

```
python tools/sb.py verify          checksums only
python tools/sb.py repair          re-fetch anything missing or corrupted
python tools/sb.py index           rebuild storyblok/index.sqlite
python tools/sb.py orphans         bucket files the space no longer has
python tools/sb.py restore-story <id> --apply
python tools/sb.py restore-assets --apply
python tools/sb.py rebuild <empty space id> --apply
```

Do not hand-edit anything under `{sub}/` — the next backup overwrites it. This
repo is a mirror, not a working copy.

## What is here

| Path | What it is |
|---|---|
| `{sub}/space.json` | space settings |
| `{sub}/components.json` | the content types (block schema) |
| `{sub}/component_groups.json`, `presets.json` | schema organisation |
| `{sub}/datasources.json`, `datasource_entries.json` | dropdown/key-value data |
| `{sub}/internal_tags.json` | tags used on assets and stories |
| `{sub}/asset_folders.json` | the asset folder tree |
| `{sub}/stories.json` | the story index (no content) |
| `{sub}/stories/<id>.json` | **one file per story, its DRAFT content** |
| `{sub}/stories_published/<id>.json` | the **published** content, where it differs from the draft |
| `{sub}/assets.json` | asset metadata |
| `{sub}/manifest_stories.csv` | **which story sits in which folder** |
| `{sub}/manifest_assets.csv` | **every asset: folder, file path, sha256** |
| `{sub}/index.sqlite` | **queryable view of all of the above**, incl. a row per (story, asset) reference. Committed, so you can clone and query it straight away; rebuild with `python tools/sb.py index` |
| `{sub}/assets_location.json` | where the binaries are kept |
| `{sub}/space_roles.json`, `webhook_endpoints.json`, `workflows.json`, `releases.json`, `tasks.json`, `branches.json` | settings, for reference |
| `{sub}/apps.json`, `app_provisions.json`, `extensions.json` | installed apps, for reference |
| `{sub}/required_field_plugins.json` | **custom field plugins the schema needs** — must exist on the target account before a restore |
| `{sub}/field_types_*.json` | plugin definitions, when the token can read them |
| `{sub}/_summary.json` | counts, and anything the token could not read |
| `tools/` | the backup and restore scripts, so this repo works alone |

Stories are named by **id**, not slug: a slug changes when the folder tree is
reorganised, and a slug-named file would turn a rename into a delete plus an add,
losing that story's history.

**Draft and published are two different things.** `{sub}/stories/` holds what the
editor sees; `{sub}/stories_published/` holds what visitors see. They differ for
any story with unpublished changes, so restoring from `stories/` alone would push
work-in-progress live. Check `state` and `unpublished_changes` in
`manifest_stories.csv` to see which is which.

## Reading it

Start with `{sub}/manifest_stories.csv` — one line per story with its folder,
component, published state and backup file. `{sub}/manifest_assets.csv` is the
same for media, and its `file_present` and `sha256` columns are how you check the
media half is intact.

## How it is kept

Each run replaces the snapshot and commits **only if something changed** — no
timestamp is written into any tracked file, so an unchanged space produces no
commit. The commit date is when the snapshot was taken.

A story deleted in the space disappears from the backup; git history keeps it.
"""

    claude = f"""# CLAUDE.md — {name} Storyblok backup

Guidance for Claude Code working in this repository.

## What this repo is

A **mirror** of the {name} Storyblok space (`{space}`, region `{region}`), written
by `tools/sb_backup.py`. It is not an application and has no build.

Media files are {where}.

## The rules

**Never hand-edit anything under `{sub}/`.** It is regenerated wholesale by the
next backup run, so an edit here is silently discarded. To change content, change
it in Storyblok and take a new backup.

**Never `git push --force` and never rewrite history.** This repo's value is that
the history is the only record of what the space used to be. Losing it loses the
backup's whole point. Media stored via Git LFS also cannot be un-billed by
rewriting — the objects stay.

**Restoring writes to a live CMS.** Every restore command is a dry run until
`--apply` is added. Read [RESTORE.md](RESTORE.md) before running one, and never
add `--force` without understanding which guard it disables.

**Never commit a token.** `sites.json` holds management tokens that can rewrite an
entire space. It is gitignored where the pipeline lives and must never appear
here. If you find one committed, treat it as leaked and rotate it.

## Layout

- `{sub}/` — the snapshot. Schema, settings, one JSON per story, asset metadata,
  and two CSV manifests.
- `{sub}/stories/<id>.json` — full story content, named by id.
- `{sub}/manifest_stories.csv` — story to folder mapping. Start here.
- `{sub}/manifest_assets.csv` — asset to file mapping, with sha256.
- `tools/` — `sb_backup.py`, `sb_restore.py`, `sb_common.py`. Self-contained.

## Commands

Use `tools/sb.py` — it finds the site and space from the snapshot, so no command
needs `--site`:

```bash
python tools/sb.py doctor
python tools/sb.py backup --push
python tools/sb.py audit
python tools/sb.py restore-story <id> --apply
python tools/sb.py restore-assets --apply       # deleted asset: bucket -> space
python tools/sb.py index                        # rebuild index.sqlite
```

Credentials: `tools/sites.json` (gitignored) or the environment
(`SB_TOKEN_{name}`, `AZURE_STORAGE_CONNECTION_STRING`). `python tools/sb.py setup`
writes the file prefilled. See RESTORE.md for the full procedure.

**`storyblok/index.sqlite` answers the mapping questions in SQL** — which stories
use a given asset, where its bytes are, what is in each folder. Derived, so rebuild
it rather than trusting a stale copy.

## What is NOT in here

Space settings, roles, webhooks, workflows, releases, tasks, branches, presets and
installed apps are **captured for reference but not recreated** by a rebuild.
Custom field plugins are account-level and have no create API. RESTORE.md lists
these as manual steps — do not assume a rebuild produced a complete space.
"""

    restore = f"""# RESTORE.md — how to put {name} back

Space `{space}`, region `{region}`. Media is {where}.

**Every command here is a dry run until you add `--apply`.** A dry run prints
exactly what would change and writes nothing.

---

## 0 · Before anything

You need three things:

1. **This repo**, cloned.
2. **A management token** for the space — Storyblok → My Account → Personal
   access tokens. A space-level token is not enough; several endpoints reject it.
3. **The media**, if you are restoring assets. {'It is not in this repo — mount or sync the bucket/share first, then point `assets_dir` at it. `storyblok/manifest_assets.csv` lists the exact relative path and sha256 of every file.' if external else 'It is in this repo under `storyblok/assets/`; run `git lfs pull` to fetch it.'}

Then write a `sites.json` (never commit it):

```json
{{
  "sites": [
    {{
      "name": "{name}",
      "space_id": "{space}",
      "management_token": "YOUR_PERSONAL_ACCESS_TOKEN",
      "region": "{region}",
      "repo": ".",
      "assets_dir": "{'/path/to/mounted/bucket' if external else ''}"
    }}
  ]
}}
```

```bash
python -m pip install -r tools/requirements.txt
python tools/sb.py doctor
```

`doctor` writes nothing. If it says READY, the credentials work.

There are two ways to supply them, both templated in `tools/`:
`sites.example.json` (a file, gitignored once filled in) or `env.example`
(environment variables, nothing on disk). `python tools/sb.py setup` writes the
file for you with the name, space id and region already filled in.

---

## 1 · Check the backup is intact first

```bash
# Does the backup cover the whole space? Exits non-zero if not.
python tools/sb_backup.py --config sites.json --site {name} --audit

# Deeper: read every stored file back and re-hash it. Costs egress.
python tools/sb_backup.py --config sites.json --site {name} --audit --deep

# Re-fetch anything missing or corrupted
python tools/sb_backup.py --config sites.json --site {name} \\
    --only assets --repair --no-commit
```

`--audit` re-queries the live space and proves every story and asset is present.
By default it checks media against the checksum recorded on each stored file,
which costs nothing; `--deep` reads the bytes back instead and will bill egress.

`missing` or `changed` above zero means the media half is not trustworthy — run
`--repair` before restoring, or you will publish broken images. `--repair` exists
because skipping unchanged files by size cannot see corruption that kept the
file's size.

**Every command here is safe to interrupt and re-run.** A backup skips stories
whose `updated_at` has not moved and assets already stored at the right size, so
continuing after Ctrl-C costs only what was actually left. `--full` forces a
complete re-fetch if you ever need one.

---

## 2 · Repair a live space — `--mode in-place`

Use this when the space still exists and something is wrong: a bad edit, a broken
import, a wrecked story. It finds each story **by its own id** and writes the
saved content back.

Shortest form:

```bash
python tools/sb.py restore-story 12345 --apply
```

The long form, with all the options:

```bash
# What has drifted from the backup? Writes nothing.
python tools/sb_restore.py --config sites.json --site {name} --mode in-place --all

# Put one story back
python tools/sb_restore.py --config sites.json --site {name} --mode in-place \\
    --story 12345 --apply

# Put everything back
python tools/sb_restore.py --config sites.json --site {name} --mode in-place \\
    --all --apply

# Restore as the backup stood five commits ago
python tools/sb_restore.py --config sites.json --site {name} --mode in-place \\
    --story 12345 --from-rev HEAD~5 --apply
```

**It never deletes and never re-creates.** Story ids survive, so editor review
links keep working and manual edits are not thrown away. The cost: a story that
was **hard-deleted** cannot come back this way, because its id is gone. Those are
listed and skipped — use a rebuild into a scratch space and copy it across, or
re-create that one story by hand.

Restored by default: `content`, `name`, `tag_list`, `is_startpage`, `meta_data`.
**Not** `slug`, `parent_id` or `position` — those move a story, and moving
thousands of stories to fix one broken body is a bigger accident than the one you
came to fix. Add `--with-structure` when you actually mean to move them.

Publish state is mirrored from the backup, so a draft is not pushed live just
because it was restored. `--no-publish` keeps everything as drafts.

---

## 2b · An asset was deleted — `--mode assets`

The most common repair, and the reason the media is kept separately. Someone
deletes an image in Storyblok; the bytes are still in the bucket, but the asset
row is gone and every story that used it renders a broken image.

```bash
python tools/sb.py restore-assets            # what is missing, and who used it
python tools/sb.py restore-assets --apply
```

It uploads the file from the bucket back into the space and then rewrites every
story that referenced it — a re-upload gets a new id and a new url, so uploading
alone fixes nothing. Each story is read live and only the asset reference changes,
so anything edited since the backup survives, and a story holding unpublished work
is not republished as a side effect.

To find out what a given asset is used by before touching anything:

```bash
python tools/sb.py index
sqlite3 storyblok/index.sqlite   "SELECT s.full_slug FROM story_assets sa
     JOIN stories s ON s.id = sa.story_id WHERE sa.asset_id = 12345;"
```

## 3 · Rebuild a lost space — `--mode rebuild`

Use this when the space is gone, or to clone it. **Create a new empty space
first**, then:

```bash
python tools/sb_restore.py --config sites.json --site {name} \\
    --mode rebuild --into <NEW_SPACE_ID>            # dry run: the plan
python tools/sb_restore.py --config sites.json --site {name} \\
    --mode rebuild --into <NEW_SPACE_ID> --apply
```

Order, because each step depends on the one before: component groups →
components → datasources and entries → internal tags → asset folders → assets →
story folders → stories → a relink pass.

Every id in the new space is different, so references inside story content are
rewritten as it goes — asset URLs and ids, internal story links, parent folders.
The old → new maps are written to `restore_maps/`.

**Guards.** Each refuses by default and each can be overridden with `--force`
once you have read what it said:

- refuses to rebuild into this site's own space (it would duplicate everything)
- refuses a target that already has stories (same reason)
- in-place refuses to write this backup into a different space id

### After a rebuild — the manual steps

A rebuild does **not** recreate these. Take them from the JSON by hand:

| From | Do what |
|---|---|
| `storyblok/space_roles.json` | recreate roles and permissions |
| `storyblok/webhook_endpoints.json` | recreate webhooks — **check the URLs first**, they were wired to the old space |
| `storyblok/workflows.json`, `workflow_stages.json` | recreate the workflow |
| `storyblok/releases.json`, `tasks.json`, `branches.json` | recreate if still needed |
| `storyblok/presets.json` | recreate component presets |
| `storyblok/apps.json`, `app_provisions.json`, `extensions.json` | **reinstall each app from the Storyblok marketplace.** Installing an app needs an OAuth flow a script cannot drive. |
| `storyblok/required_field_plugins.json` | **the custom field plugins this schema depends on.** Account-level, no create API — every one listed must already exist on the target account, or each component using it will not save correctly. The file names which components need which plugin. |
| — | **generate new access tokens** (Settings → Access tokens) and re-point the front end at them. The old tokens are deliberately not backed up: they are live credentials and this repo has a remote. |
| `storyblok/webhook_endpoints.json` | the signing **secret** is stripped for the same reason — set a new one on each webhook and update the receiver. |

### Draft or published?

`--mode rebuild` creates stories from `storyblok/stories/` — the **drafts** — and
publishes the ones that were published. If what you need back is exactly what
visitors last saw, use `storyblok/stories_published/` instead; `state` and
`unpublished_changes` in `manifest_stories.csv` say which stories differ.

A rebuild is also **not byte-identical**: every asset gets a new URL, so the
result is equivalent, not the same.

---

## 4 · If you only have this repo and no tooling

Everything needed is here. `tools/` holds the scripts and `requests` is the only
dependency. The snapshot is plain JSON and CSV — worst case, `storyblok/stories/`
plus `manifest_stories.csv` tell you every story's content and where it belonged,
and you can rebuild by hand through the Storyblok UI.
"""

    wrote = []
    for fn, body in (("README.md", readme), ("CLAUDE.md", claude),
                     ("RESTORE.md", restore)):
        path = os.path.join(repo, fn)
        current = ""
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                current = f.read()
        if current != body:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(body)
            wrote.append(fn)
    if wrote:
        print(f"    docs: wrote {', '.join(wrote)}")
    return wrote


# --------------------------------------------------------------------------
# git
# --------------------------------------------------------------------------

def ensure_repo(repo, outdir, want_lfs):
    """Make sure `repo` is a git repo with LFS tracking in place.

    .gitattributes goes in `outdir`, beside assets/, not at the repo root. A
    gitattributes pattern containing a slash is anchored to the directory
    holding the file, so a root-level `assets/**` never matches
    `storyblok/assets/...` -- and the result is silent: LFS reports nothing to
    do while git stores every binary raw.

    It also has to be on disk *before* the assets are staged. LFS decides what
    becomes a pointer at `git add` time, so writing the patterns afterwards
    leaves the binaries already committed in history for good.
    """
    os.makedirs(outdir, exist_ok=True)
    if not os.path.isdir(os.path.join(repo, ".git")):
        git(repo, "init", "-b", "main")
        print(f"    initialised a new repo at {repo}")

    if want_lfs:
        if not have_lfs():
            raise RuntimeError(
                "Git LFS is not installed, and this backup commits asset "
                "binaries.\n    Install from https://git-lfs.com, run "
                "'git lfs install', or pass --no-assets.")
        git(repo, "lfs", "install", "--local")
        wanted = [
            "# Storyblok asset binaries. Written by sb_backup.py - do not edit.",
            "# Anchored here rather than at the repo root: a pattern with a",
            "# slash resolves against the directory holding this file.",
            "assets/** filter=lfs diff=lfs merge=lfs -text",
            "# Formats that diff usefully stay in normal git.",
        ] + [f"assets/**/*.{e} -filter -diff -merge text"
             for e in LFS_TEXT_EXCEPTIONS]
        attrs = os.path.join(outdir, ".gitattributes")
        desired = "\n".join(wanted) + "\n"
        current = ""
        if os.path.exists(attrs):
            with open(attrs, encoding="utf-8") as f:
                current = f.read()
        if current != desired:
            with open(attrs, "w", encoding="utf-8", newline="\n") as f:
                f.write(desired)
            print("    wrote .gitattributes (LFS tracking for assets/)")

    # Appended to rather than only created, so a repo set up before a rule
    # existed still gets it. A credential rule that only lands in new repos is
    # the kind that is missing exactly where it matters.
    ignore = os.path.join(repo, ".gitignore")
    required = [
        ("*.part", "# Partial downloads from an interrupted run."),
        ("__pycache__/",
         "# Bytecode from running tools/. Changes with the Python version and\n"
         "# has no place in a backup."),
        ("*.pyc", None),
        ("restore_maps/", "# Written by sb_restore.py --mode rebuild."),
        # storyblok/index.sqlite is deliberately NOT here. It is derived, but it
        # is committed so the repo can be cloned and queried without running
        # anything first. At the weekly-or-monthly cadence these backups are
        # actually taken by hand, a few MB per run is negligible history; the
        # earlier decision to ignore it was reasoned from a nightly job that
        # does not exist.
        ("tools/sites.json",
         "# Credentials. This token can rewrite the entire space."),
        ("tools/.sites.env.json",
         "# Built from environment variables by tools/sb.py."),
    ]
    current = ""
    if os.path.exists(ignore):
        with open(ignore, encoding="utf-8") as f:
            current = f.read()
    add = [(rule, note) for rule, note in required
           if rule not in current.split()]
    if add:
        with open(ignore, "a" if current else "w", encoding="utf-8",
                  newline="\n") as f:
            if current and not current.endswith("\n"):
                f.write("\n")
            for rule, note in add:
                f.write(f"\n{note}\n{rule}\n")
        print(f"    .gitignore: added {len(add)} rule(s)")


def commit_and_push(repo, site, counts, push):
    git(repo, "add", "-A")
    if not git(repo, "status", "--porcelain").stdout.strip():
        print("    no change since the last snapshot - nothing to commit")
        return False

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    body = "\n".join(f"{k}: {v}" for k, v in sorted(counts.items()))
    msg = (f"{site['name']} Storyblok backup - {stamp}\n\n"
           f"space_id: {site['space_id']}\n{body}\n")
    git(repo, "-c", "user.name=sb_backup", "-c",
        "user.email=sb_backup@local", "commit", "-m", msg, "--no-verify")
    print(f"    committed {git(repo, 'rev-parse', '--short', 'HEAD').stdout.strip()}")

    if not push:
        print("    not pushed (pass --push)")
        return True
    if "origin" not in git(repo, "remote").stdout.split():
        print("    !! no 'origin' remote - add one, then re-run with --push")
        return True
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    print(f"    pushing {branch} -> origin", flush=True)
    r = git(repo, "push", "-u", "origin", branch, check=False)
    print("    pushed" if r.returncode == 0
          else f"    !! push failed:\n{(r.stderr or r.stdout).strip()}")
    return True


# --------------------------------------------------------------------------
# the audit -- is everything actually backed up?
# --------------------------------------------------------------------------

def audit(site, args):
    """Re-query the live space and prove the backup covers all of it.

    Deliberately not a re-read of the numbers this run just printed. A backup
    that reports its own success is worth very little; every count here comes
    from asking the space again and looking at what is on disk and in the
    container. Exits non-zero on any gap, so it can gate a nightly job.
    """
    name, space_id = site["name"], str(site["space_id"])
    repo, outdir = repo_paths(site)
    token = token_for(site)
    api = space_api(site)
    store, external = make_backend(site, outdir, args.assets_dir)

    print(f"\n{'=' * 74}\n  audit - {name}   space {space_id}\n{'=' * 74}")
    if not os.path.isdir(outdir):
        print(f"  !! no snapshot at {outdir}")
        return 1

    problems, lines = [], []

    def row(label, want, got, extra=""):
        ok = want == got
        lines.append(f"  {'ok ' if ok else 'GAP'}  {label:<28} "
                     f"space {want:>7}   backup {got:>7}   {extra}")
        if not ok:
            problems.append(f"{label}: space {want}, backup {got} {extra}")
        return ok

    # ---- schema and settings: present at all?
    for res, path, key, paginated in RESOURCES:
        live, err = fetch_list(api, path, key, paginated, token)
        saved = load_json(os.path.join(outdir, f"{res}.json"))
        if err:
            lines.append(f"  --   {res:<28} unreadable ({err[:40]})")
            continue
        n_live = len(live) if isinstance(live, list) else 1
        n_saved = len(saved) if isinstance(saved, list) else (0 if saved is None else 1)
        row(res, n_live, n_saved)

    # ---- stories: every id present, and every one holding real content
    live_stories, err = fetch_list(api, "stories", "stories", True, token)
    if err:
        problems.append(f"cannot list stories: {err}")
        live_stories = []
    live_ids = {str(s["id"]) for s in live_stories if s.get("id")}
    story_dir = os.path.join(outdir, "stories")
    have = {f[:-5] for f in os.listdir(story_dir)
            if f.endswith(".json")} if os.path.isdir(story_dir) else set()
    row("stories", len(live_ids), len(have & live_ids))

    absent = sorted(live_ids - have)
    if absent:
        problems.append(f"{len(absent)} story(ies) in the space with no backup "
                        f"file: {absent[:10]}")
    stale = sorted(have - live_ids)
    if stale:
        # Not a failure: a story deleted in the space should vanish from the
        # backup. Worth surfacing so a botched delete is visible.
        lines.append(f"  --   {'stories no longer live':<28} "
                     f"{len(stale)} file(s) will be removed next run")

    # Folders are stories too, and a folder's content is legitimately empty.
    # Counting them as missing content made a complete backup fail its own audit.
    is_folder = {str(s["id"]): bool(s.get("is_folder"))
                 for s in live_stories if s.get("id")}
    checkable = [sid for sid in sorted(have & live_ids) if not is_folder.get(sid)]
    empty = 0
    for sid in checkable:
        st = load_json(os.path.join(story_dir, f"{sid}.json")) or {}
        if not st.get("content"):
            empty += 1
    if empty:
        problems.append(f"{empty} backed-up story(ies) have no content at all")
    lines.append(f"  {'ok ' if not empty else 'GAP'}  "
                 f"{'stories with content':<28} "
                 f"{len(checkable) - empty} of {len(checkable)} "
                 f"({len(have & live_ids) - len(checkable)} folder(s) skipped)")

    # ---- published versions
    pub_dir = os.path.join(outdir, "stories_published")
    n_pub_live = sum(1 for s in live_stories
                     if s.get("published") and not s.get("is_folder"))
    n_pub_have = len([f for f in os.listdir(pub_dir)
                      if f.endswith(".json")]) if os.path.isdir(pub_dir) else 0
    drifted = sum(1 for s in live_stories if s.get("unpublished_changes"))
    row("published versions", n_pub_live, n_pub_have,
        f"({drifted} differ from their draft)")

    # ---- assets: metadata and bytes
    live_assets, err = fetch_list(api, "assets", "assets", True, token)
    if err:
        problems.append(f"cannot list assets: {err}")
        live_assets = []
    saved_assets = load_json(os.path.join(outdir, "assets.json"), []) or []
    row("asset metadata", len(live_assets), len(saved_assets))

    # Assets whose bytes are gone from Storyblok's own S3. Nothing here can fix
    # those, and an audit that fails forever on them is an audit people stop
    # reading -- which is how a real failure hides. Same idea as
    # config/tree_accepted_exceptions.csv: reviewed, recorded, and reported
    # separately rather than silently ignored.
    accepted = {str(k): v for k, v in
                (load_json(os.path.join(outdir, "accepted_gaps.json"), {})
                 or {}).items()}

    prev_sha = read_prev_sha(outdir)
    if args.no_assets:
        lines.append(f"  --   {'asset bytes':<28} not checked (--no-assets)")
    else:
        print(f"  checking {len(live_assets)} stored file(s)"
              + ("  [full re-read, billed egress]" if args.deep
                 else "  [blob metadata, no egress]"))
        v = verify_assets(live_assets, store, space_id, prev_sha,
                          args.workers, not args.deep)
        # A gap that has been reviewed and recorded is not an open gap.
        unexplained = [b for b in v["bad_ids"] if b not in accepted]
        excused = len(v["bad_ids"]) - len(unexplained)
        # Only the expected side is reduced by the accepted gaps. v["ok"] already
        # counts just the files that are actually there, so subtracting them from
        # both sides reported a one-file shortfall that did not exist.
        row("asset bytes stored", len(live_assets) - excused,
            v["ok"] + v["no_checksum"] + v["mismatched"])
        lines.append(f"  {'ok ' if not v['mismatched'] else 'GAP'}  "
                     f"{'asset checksums match':<28} "
                     f"{v['ok']} verified, {v['mismatched']} changed, "
                     f"{v['no_checksum']} unchecksummed")
        if excused:
            lines.append(f"  --   {'accepted gaps':<28} {excused} "
                         f"(gone upstream; see accepted_gaps.json)")
            for b in v["bad_ids"]:
                if b in accepted:
                    lines.append(f"       {b}: {accepted[b]}")
        if unexplained:
            problems.append(f"{len(unexplained)} asset(s) missing or corrupted "
                            f"and not in accepted_gaps.json: "
                            f"{unexplained[:8]}")
        for p in v["problems"][:15]:
            if not any(b in p for b in accepted):
                lines.append(f"       {p}")

    # ---- the mapping and the docs
    for f in ("manifest_stories.csv", "manifest_assets.csv",
              "assets_location.json", "_summary.json"):
        present = os.path.exists(os.path.join(outdir, f))
        lines.append(f"  {'ok ' if present else 'GAP'}  {f:<28} "
                     f"{'present' if present else 'MISSING'}")
        if not present:
            problems.append(f"{f} is missing")
    for f in ("README.md", "CLAUDE.md", "RESTORE.md", "tools/sb_restore.py"):
        present = os.path.exists(os.path.join(repo, f))
        lines.append(f"  {'ok ' if present else 'GAP'}  {f:<28} "
                     f"{'present' if present else 'MISSING'}")
        if not present:
            problems.append(f"{f} is missing from the repo")

    print("\n".join(lines))
    print(f"\n  media: {store.label}"
          + ("   (outside the repo)" if external else "   (in the repo)"))

    if problems:
        print(f"\n  AUDIT FAILED - {len(problems)} problem(s):")
        for p in problems:
            print(f"    - {p}")
        return 1
    print("\n  AUDIT PASSED - the backup covers the whole space")
    return 0


# --------------------------------------------------------------------------

def check(site):
    token = token_for(site)
    if not token or "YOUR_" in str(token):
        print(f"  {site['name']:<8} no token")
        return False
    r = get(space_api(site), token)
    if r.status_code != 200:
        print(f"  {site['name']:<8} {r.status_code} {r.text[:120]}")
        return False
    sp = r.json().get("space", {})
    print(f"  {site['name']:<8} ok - {sp.get('name')} "
          f"(space {site['space_id']}, plan {sp.get('plan')}, "
          f"region {site.get('region', 'eu')})")
    return True


def backup(site, only, args):
    name, space_id = site["name"], str(site["space_id"])
    repo, outdir = repo_paths(site)
    token = token_for(site)

    print(f"\n{'=' * 74}\n  {name}   space {space_id}   -> {repo}\n{'=' * 74}")
    if not token or "YOUR_" in str(token):
        print("  !! no management token - skipped")
        return None

    api = space_api(site)
    want_assets = "assets" in only and not args.no_assets
    store, external = make_backend(site, outdir, args.assets_dir)
    # LFS is only needed when binaries are committed. With the media on a bucket
    # the repo stays text-only, so requiring LFS would be a dependency for
    # nothing -- and would fail the run on a machine that does not have it.
    ensure_repo(repo, outdir, want_lfs=want_assets and not external)
    install_tools(repo)
    if want_assets:
        store.ensure()
        print(f"  media -> {store.label}"
              + ("   (outside the repo, not committed)" if external
                 else "   (committed via Git LFS)"))

    counts, errors = {}, {}

    # The space record, which doubles as the credential check: everything else
    # is pointless if this 401s, and it costs one request to find out.
    r = get(api, token)
    if r.status_code != 200:
        print(f"  !! cannot read space: {r.status_code} {r.text[:300]}")
        return None
    sp = r.json().get("space", {})
    sp.pop("owner", None)               # the account holder's name and email
    save(outdir, "space", sp)
    print(f"  space: {sp.get('name')}   plan: {sp.get('plan')}")

    if "schema" in only:
        print("\n  schema and settings")
        for res, path, key, paginated in RESOURCES:
            data, err = fetch_list(api, path, key, paginated, token)
            if err:
                # 403 here is routine, not a failure: which endpoints a token
                # can reach depends on its type and the space's plan. Recorded
                # in _summary.json so it stays visible instead of silent.
                print(f"    {res:<20} -- {err[:70]}")
                errors[res] = err
                continue
            counts[res] = save(outdir, res, data)
            print(f"    {res:<20} {counts[res]}")

        # What the schema needs from the account, derived from the schema
        # itself, because /field_types will not tell us.
        plugins = required_field_plugins(
            load_json(os.path.join(outdir, "components.json"), []) or [])
        counts["required_field_plugins"] = save(
            outdir, "required_field_plugins", plugins)
        if plugins:
            print(f"    {'field plugins needed':<20} {len(plugins)}: "
                  f"{', '.join(sorted(plugins))}")

        # Datasource entries sit behind a per-datasource query, so a
        # datasources.json on its own restores empty dropdowns.
        entries = []
        for ds in load_json(os.path.join(outdir, "datasources.json"), []) or []:
            got, err = fetch_list(
                api, f"datasource_entries?datasource_id={ds['id']}",
                "datasource_entries", True, token)
            if err:
                errors[f"datasource_entries[{ds.get('slug')}]"] = err
            else:
                entries.extend(got or [])
        counts["datasource_entries"] = save(outdir, "datasource_entries",
                                            entries)
        print(f"    {'datasource_entries':<20} {counts['datasource_entries']}")

        # Field-type plugins register per space or per account; which one
        # answers depends on the token, so both are tried.
        for label, url in (("space", f"{api}/field_types"),
                           ("account", f"{api.split('/spaces/')[0]}/field_types")):
            r = get(url, token)
            if r.status_code == 200:
                ft = r.json().get("field_types", r.json())
                if isinstance(ft, list):
                    for f_ in ft:
                        f_.pop("body", None)     # bundled plugin source, huge
                counts[f"field_types_{label}"] = save(
                    outdir, f"field_types_{label}", ft)
            else:
                errors[f"field_types_{label}"] = r.status_code

        for flag, path, key in ((args.collaborators, "collaborators",
                                 "collaborators"),
                                (args.activities, "activities", "activities")):
            if not flag:
                continue
            data, err = fetch_list(api, path, key, path == "activities", token)
            if err:
                errors[path] = err
            else:
                counts[path] = save(outdir, path, data)

    stories, story_meta, assets = [], {}, []

    if "stories" in only:
        print("\n  stories")
        stories, err = fetch_list(api, "stories", "stories", True, token)
        if err:
            print(f"    !! {err}")
            errors["stories"] = err
            stories = []
        else:
            counts["stories"] = save(outdir, "stories", stories)
            print(f"    index: {len(stories)}; fetching draft content")
            prev_stories = read_prev_stories(outdir)
            res = download_stories(api, token, stories, outdir, args.workers,
                                   prev_stories, args.full)
            counts["stories_with_content"] = res["saved"] + res["reused"]
            story_meta = res["meta"]
            if res["failed"]:
                errors["stories_content"] = res["errors"]
            if res["deleted_since_last_run"]:
                print(f"    removed {res['deleted_since_last_run']} story "
                      f"file(s) no longer in the space")

            # The published version, which is a different thing from the draft
            # for any story with unpublished changes. Without it a restore
            # publishes work in progress.
            drifted = sum(1 for s in stories if s.get("unpublished_changes"))
            delivery = sp.get("first_token")
            if args.no_published:
                print("    published versions skipped (--no-published)")
            elif not delivery:
                # Not fatal, but it must not pass silently: the backup is then
                # draft-only and cannot restore the live state.
                print("    !! no delivery token on the space record - cannot "
                      "capture published versions")
                errors["stories_published"] = "no delivery token available"
            else:
                print(f"    fetching published content "
                      f"({drifted} story(ies) differ from their draft)")
                pub = download_published(space_id, site.get("region", "eu"),
                                         delivery, stories, outdir,
                                         args.workers, prev_stories, args.full)
                counts["stories_published"] = pub["saved"] + pub["reused"]
                counts["stories_draft_differs"] = drifted
                if pub["failed"]:
                    errors["stories_published"] = pub["errors"]

    asset_sha = {}
    if "assets" in only:
        print("\n  assets")
        assets, err = fetch_list(api, "assets", "assets", True, token)
        if err:
            print(f"    !! {err}")
            errors["assets"] = err
            assets = []
        else:
            counts["assets"] = save(outdir, "assets", assets)
            print(f"    metadata: {len(assets)}")
            # Read the checksums the last run recorded BEFORE downloading, so a
            # file that is still the right size keeps its hash instead of being
            # read back off the bucket.
            prev_sha = read_prev_sha(outdir)

            # /internal_tags rejects a personal access token, but every asset
            # carries its own tags, so the list is recoverable from the metadata
            # we already have. A 403 does not have to mean a gap.
            if "internal_tags" in errors:
                derived = {}
                for a in assets:
                    for t in (a.get("internal_tags_list") or []):
                        if t.get("id") is not None:
                            derived[t["id"]] = t
                if derived:
                    counts["internal_tags_derived"] = save(
                        outdir, "internal_tags", sorted(derived.values(),
                                                        key=lambda x: x["id"]))
                    errors.pop("internal_tags", None)
                    print(f"    internal_tags        "
                          f"{counts['internal_tags_derived']} (derived from "
                          f"assets; the endpoint refuses this token type)")

            if args.verify_assets:
                print(f"    verifying {len(assets)} file(s) against "
                      f"{len(prev_sha)} recorded checksum(s)")
                v = verify_assets(assets, store, space_id, prev_sha,
                                  args.workers, not args.deep)
                counts["assets_verified_ok"] = v["ok"]
                print(f"    ok {v['ok']}   missing {v['missing']}   "
                      f"changed {v['mismatched']}   "
                      f"no checksum yet {v['no_checksum']}")
                for p in v["problems"][:20]:
                    print(f"      {p}")
                if v["missing"] or v["mismatched"]:
                    errors["assets_verify"] = v["problems"]
                asset_sha = prev_sha
            elif args.no_assets:
                print("    binaries skipped (--no-assets)")
                asset_sha = prev_sha
            else:
                force = set()
                if args.repair:
                    print("    repair: deep-verifying before download")
                    v = verify_assets(assets, store, space_id, prev_sha,
                                      args.workers, quick=False)
                    force = set(v["bad_ids"])
                    print(f"    repair: {len(force)} file(s) missing or "
                          f"corrupted, forcing re-fetch")
                res = download_assets(assets, store, space_id, prev_sha,
                                      args.workers, force)
                counts["asset_files"] = (res["downloaded"]
                                         + res["already_present"])
                asset_sha = res["sha"]
                if res["failed"]:
                    errors["asset_files"] = res["errors"]

    # The readable index: which story sits in which folder, and where every
    # asset went. Written from whatever this run fetched, so a --only run does
    # not overwrite the other manifest with an empty one.
    if stories or assets:
        print("\n  manifests")
        if stories:
            counts["manifest_stories"] = write_story_manifest(
                outdir, stories, story_meta)
            print(f"    manifest_stories.csv    "
                  f"{counts['manifest_stories']} row(s)")
        if assets:
            folders = load_json(
                os.path.join(outdir, "asset_folders.json"), []) or []
            counts["manifest_assets"] = write_asset_manifest(
                assets, folders, space_id, outdir, store, external, asset_sha)
            print(f"    manifest_assets.csv     "
                  f"{counts['manifest_assets']} row(s)")
            missing = counts.get("assets", 0) - counts.get("asset_files", 0)
            if missing > 0 and not (args.no_assets or args.verify_assets):
                print(f"    !! {missing} asset(s) have metadata but no file - "
                      f"see file_present=NO in manifest_assets.csv")

            # The visual index of the same data. One self-contained file, like
            # Blogs-Pipeline's portal, because a folder tree is the one thing
            # nobody verifies by reading JSON.
            rows_by_id = {}
            with open(os.path.join(outdir, "manifest_assets.csv"),
                      encoding="utf-8-sig", newline="") as f:
                for r_ in csv.DictReader(f):
                    rows_by_id[r_["id"]] = r_
            n = build_assets_portal(
                os.path.join(repo, "assets-portal.html"), site,
                sp.get("name"), assets, folders,
                folder_path_map(folders), rows_by_id, store.label, external)
            counts["portal_rows"] = n
            print(f"    assets-portal.html      {n} file(s) — open it to see "
                  f"the folder tree")

    save(outdir, "_summary", {"site": name, "space_id": space_id,
                              "space_name": sp.get("name"),
                              "region": site.get("region", "eu"),
                              "assets_external": external,
                              "counts": counts, "errors": errors})
    write_repo_docs(repo, site, external)
    print("\n  " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if errors:
        print(f"  not retrieved: {', '.join(sorted(errors))}")

    if args.no_commit:
        print("    not committed (--no-commit)")
    else:
        commit_and_push(repo, site, counts, args.push)
    return counts


def main():
    ap = argparse.ArgumentParser(
        description="Back up complete Storyblok spaces into per-site git repos.")
    ap.add_argument("--site", default="all",
                    help="AKUH | AKU | AKUEB | a comma list | all")
    ap.add_argument("--config", help="path to sites.json (also SB_SITES)")
    ap.add_argument("--only", default="schema,stories,assets",
                    help="comma list: schema, stories, assets")
    ap.add_argument("--check", action="store_true",
                    help="verify every configured token, then exit")
    ap.add_argument("--push", action="store_true",
                    help="push each repo to origin after committing")
    ap.add_argument("--no-commit", action="store_true",
                    help="write files but leave git alone")
    ap.add_argument("--no-assets", action="store_true",
                    help="asset metadata only, no binaries and no LFS")
    ap.add_argument("--assets-dir",
                    help="store binaries HERE instead of in the repo (bucket "
                         "mount, file share, any path). Overrides assets_dir "
                         "in sites.json. The repo then holds the index and a "
                         "sha256 per file, and needs no Git LFS.")
    ap.add_argument("--verify-assets", action="store_true",
                    help="re-hash the stored binaries against the checksums in "
                         "manifest_assets.csv and report drift. Downloads "
                         "nothing.")
    ap.add_argument("--audit", action="store_true",
                    help="re-query the live space and prove the existing backup "
                         "covers all of it. Exits non-zero on any gap.")
    ap.add_argument("--deep", action="store_true",
                    help="with --audit/--verify-assets, read every stored file "
                         "back and re-hash it. Catches corruption in place, but "
                         "downloads the whole container -- 31 GB for AKUEB -- "
                         "and Azure bills egress. The default reads the "
                         "checksum recorded on each blob instead, which costs "
                         "nothing and still catches missing or replaced files.")
    ap.add_argument("--repair", action="store_true",
                    help="deep-verify every stored file first, then re-fetch "
                         "anything missing or whose checksum no longer matches. "
                         "Needed because skipping by size cannot see corruption "
                         "that kept the file's size.")
    ap.add_argument("--no-index-db", action="store_true",
                    help="skip building index.sqlite")
    ap.add_argument("--full", action="store_true",
                    help="re-fetch every story even if its updated_at has not "
                         "moved. The default skips unchanged ones, which is what "
                         "makes a repeat or interrupted run quick.")
    ap.add_argument("--no-published", action="store_true",
                    help="skip the published versions and back up drafts only")
    ap.add_argument("--collaborators", action="store_true",
                    help="also capture members (contains real email addresses)")
    ap.add_argument("--activities", action="store_true",
                    help="also capture the activity log (large, unbounded)")
    ap.add_argument("--workers", type=int, default=6,
                    help="concurrent requests (default 6)")
    args = ap.parse_args()

    sites = pick_sites(load_sites(args.config), args.site)

    if args.check:
        print(f"\n  checking {len(sites)} site(s)\n")
        return 0 if all(check(s) for s in sites) else 1

    if args.audit:
        bad = [s["name"] for s in sites if audit(s, args) != 0]
        print(f"\n{'=' * 74}")
        if bad:
            print(f"  AUDIT FAILED for: {', '.join(bad)}")
            return 1
        print("  all audited backups cover their space")
        return 0

    only = {p.strip() for p in args.only.split(",") if p.strip()}
    unknown = only - {"schema", "stories", "assets"}
    if unknown:
        sys.exit(f"--only: unknown section(s) {', '.join(sorted(unknown))}")

    done, failed = [], []
    for s in sites:
        try:
            (done if backup(s, only, args) is not None
             else failed).append(s["name"])
        except Exception as e:
            # One site failing must not stop the others: a backup of two spaces
            # beats no backup at all. And say plainly that a re-run resumes,
            # because the natural reading of "FAILED" is that the work was lost --
            # when every story written and every file uploaded is still there and
            # a repeat run skips all of it.
            print(f"  !! {s['name']}: {type(e).__name__}: {e}")
            print("     Nothing already stored is lost - re-run to continue "
                  "from where this stopped.")
            failed.append(s["name"])

    print(f"\n{'=' * 74}\n  ok: {', '.join(done) or 'none'}")
    if failed:
        print(f"  FAILED: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
