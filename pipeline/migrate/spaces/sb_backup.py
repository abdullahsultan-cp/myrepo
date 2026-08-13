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
import hashlib
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sb_common import (
    asset_path,
    assets_root,
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
    sha256_file,
    space_api,
    token_for,
    write_csv,
    write_json,
)

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

def download_assets(assets, root, space_id, prev_sha=None, workers=6):
    """Fetch every binary not already on disk at the right size.

    `root` is where the files go -- inside the snapshot, or a bucket mount
    outside it. Skipping by size is what makes a second run cheap, and that is
    the difference between a backup taken nightly and one taken once.

    A sha256 is computed as the bytes stream past, so hashing costs nothing on
    top of the download. For a file that was skipped, the checksum is carried
    forward from the previous manifest when the size still matches; only when
    there is no recorded checksum is the file read back to hash it. Re-hashing
    42 GB on every run would make the nightly job unaffordable, and a checksum
    nobody can afford to compute is a checksum nobody has.
    """
    prev_sha = prev_sha or {}
    jobs = []
    for a in assets:
        rel, url = asset_path(a, space_id), a.get("filename")
        if rel and url:
            # asset_path prefixes "assets/"; root already IS that folder.
            rel = rel.split(os.sep, 1)[1] if os.sep in rel else rel
            jobs.append((a, url, os.path.join(root, rel), rel))

    got = skipped = failed = rehashed = 0
    errors, sha, lock, total = [], {}, threading.Lock(), len(jobs)

    def one(job):
        a, url, dest, rel = job
        aid = a.get("id")
        expected = a.get("content_length")
        try:
            expected = int(expected) if expected else 0
        except (TypeError, ValueError):
            expected = 0

        if os.path.exists(dest):
            on_disk = os.path.getsize(dest)
            if not expected or on_disk == expected:
                known = prev_sha.get(str(aid))
                if known:
                    return "skip", None, aid, known
                # No checksum on record: read it once, and it is in the
                # manifest from then on.
                return "rehash", None, aid, sha256_file(dest)

        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = dest + ".part"
        try:
            r = get(url, stream=True)          # no token: asset URLs are public
            if r.status_code != 200:
                return "fail", f"{aid} {url} -> {r.status_code}", aid, None
            h = hashlib.sha256()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(65536):
                    if chunk:
                        f.write(chunk)
                        h.update(chunk)
            os.replace(tmp, dest)   # never leave a half file looking complete
            return "ok", None, aid, h.hexdigest()
        except Exception as e:
            # Broad on purpose: one unreadable asset out of thousands must be
            # reported and skipped, not allowed to end the run. The type and
            # message go into _summary.json so it stays visible afterwards.
            if os.path.exists(tmp):
                os.remove(tmp)
            return "fail", f"{aid} {url} -> {type(e).__name__}: {e}", aid, None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, j) for j in jobs]
        for n, fut in enumerate(as_completed(futures), 1):
            status, err, aid, digest = fut.result()
            with lock:
                if status == "ok":
                    got += 1
                elif status == "skip":
                    skipped += 1
                elif status == "rehash":
                    skipped += 1
                    rehashed += 1
                else:
                    failed += 1
                    errors.append(err)
                if digest:
                    sha[str(aid)] = digest
            if n % 200 == 0 or n == total:
                print(f"      {n}/{total}  downloaded {got}  "
                      f"already had {skipped}  failed {failed}", flush=True)

    if rehashed:
        print(f"      checksummed {rehashed} existing file(s) for the first time")

    # Sorted, not in completion order: these land in the committed
    # _summary.json, and thread scheduling would otherwise reshuffle the same
    # failures into a fresh diff on every run.
    return {"downloaded": got, "already_present": skipped, "failed": failed,
            "sha": sha, "errors": sorted(e for e in errors if e)[:50]}


def verify_assets(assets, root, space_id, prev_sha):
    """Re-hash what is on disk and compare against the recorded checksums.

    The point of splitting the backup is that git holds the index and the bucket
    holds the bytes. That only works if the halves can be proved to match, so
    this exists to be run before anyone relies on a restore -- silent bit-rot or
    a half-finished sync is exactly the failure this arrangement invites.
    """
    ok = missing = mismatched = unknown = 0
    bad = []
    for a in assets:
        rel = asset_path(a, space_id)
        if not rel:
            continue
        rel = rel.split(os.sep, 1)[1] if os.sep in rel else rel
        dest = os.path.join(root, rel)
        aid = str(a.get("id"))
        if not os.path.exists(dest):
            missing += 1
            bad.append(f"MISSING  {aid}  {rel}")
            continue
        want = prev_sha.get(aid)
        if not want:
            unknown += 1
            continue
        if sha256_file(dest) == want:
            ok += 1
        else:
            mismatched += 1
            bad.append(f"CHANGED  {aid}  {rel}")
    return {"ok": ok, "missing": missing, "mismatched": mismatched,
            "no_checksum": unknown, "problems": sorted(bad)[:50]}


# --------------------------------------------------------------------------
# stories
# --------------------------------------------------------------------------

def download_stories(api, token, stories, outdir, workers=5):
    """One file per story, holding the full draft content.

    The list endpoint omits `content`, so each story needs its own GET. Named
    by id, not slug: the slug is what changes when a folder tree is
    reorganised, and a slug-named file turns a rename into a delete plus an
    add, losing that story's history.
    """
    story_dir = os.path.join(outdir, "stories")
    os.makedirs(story_dir, exist_ok=True)
    keep = {str(s["id"]) for s in stories if s.get("id") is not None}
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

    return {"saved": ok, "failed": failed, "deleted_since_last_run": removed,
            "errors": sorted(errors)[:50], "meta": meta}


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


def write_asset_manifest(assets, asset_folders, space_id, outdir, root,
                         external, sha):
    """Where every asset is in the space, and where its bytes actually are.

    This file is the join between the two halves of the backup: git holds it,
    the bucket holds the files it points at. `file_present` and `sha256` are the
    columns that matter -- an asset with metadata but no bytes would be
    recreated as an empty asset by a rebuild, and every story pointing at it
    would render broken. Better to see that here than after a restore.
    """
    apaths = folder_path_map(asset_folders or [])
    arows = []
    for a in assets:
        rel = asset_path(a, space_id)
        rel = (rel.split(os.sep, 1)[1] if rel and os.sep in rel else rel) or ""
        arows.append([
            a.get("id"),
            os.path.basename(a.get("filename") or "") or "",
            apaths.get(a.get("asset_folder_id"), "(root)"),
            rel.replace(os.sep, "/"),
            "yes" if rel and os.path.exists(os.path.join(root, rel)) else "NO",
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
    write_json(os.path.join(outdir, "assets_location.json"), {
        "external": external,
        "note": ("Binaries are stored outside this repository. Set assets_dir "
                 "for this site in config/sites.json, or pass --assets-dir, to "
                 "the location holding the paths in manifest_assets.csv."
                 if external else
                 "Binaries are committed to this repository under "
                 "storyblok/assets/, via Git LFS."),
        "backup_file_paths_are_relative_to": ("<assets_dir>" if external
                                              else "storyblok/assets/"),
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

Automated backup of the **{name}** Storyblok space (`{space}`, region `{region}`).
Written by `sb_backup.py`; see [RESTORE.md](RESTORE.md) to put it back.

**Media files are {where}.**

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
| `{sub}/stories/<id>.json` | **one file per story, with its full content** |
| `{sub}/assets.json` | asset metadata |
| `{sub}/manifest_stories.csv` | **which story sits in which folder** |
| `{sub}/manifest_assets.csv` | **every asset: folder, file path, sha256** |
| `{sub}/assets_location.json` | where the binaries are kept |
| `{sub}/space_roles.json`, `webhook_endpoints.json`, `workflows.json`, `releases.json`, `tasks.json`, `branches.json` | settings, for reference |
| `{sub}/apps.json`, `app_provisions.json`, `extensions.json` | installed apps, for reference |
| `{sub}/field_types_*.json` | custom field plugins registered |
| `{sub}/_summary.json` | counts, and anything the token could not read |
| `tools/` | the backup and restore scripts, so this repo works alone |

Stories are named by **id**, not slug: a slug changes when the folder tree is
reorganised, and a slug-named file would turn a rename into a delete plus an add,
losing that story's history.

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

```bash
python tools/sb_backup.py  --site {name} --check          # verify credentials
python tools/sb_restore.py --site {name} --mode in-place --all      # dry run
python tools/sb_restore.py --site {name} --mode in-place --story <id> --apply
```

Both need a `sites.json` with this site's `space_id`, `management_token` and
`repo` path. See RESTORE.md.

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
pip install requests
python tools/sb_backup.py --config sites.json --site {name} --check
```

`--check` writes nothing. If it prints `ok`, the credentials work.

---

## 1 · Check the backup is intact first

```bash
python tools/sb_backup.py --config sites.json --site {name} \\
    --only assets --verify-assets --no-commit
```

Re-hashes every stored file against `manifest_assets.csv`. `missing` or `changed`
above zero means the media half is not trustworthy — fix that before restoring,
or you will publish broken images.

---

## 2 · Repair a live space — `--mode in-place`

Use this when the space still exists and something is wrong: a bad edit, a broken
import, a wrecked story. It finds each story **by its own id** and writes the
saved content back.

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
| `storyblok/field_types_*.json` | custom field plugins are **account-level** and have no create API. They must already exist on the target account, or components using them will not save correctly. |

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

    ignore = os.path.join(repo, ".gitignore")
    if not os.path.exists(ignore):
        with open(ignore, "w", encoding="utf-8", newline="\n") as f:
            f.write("# Partial downloads from an interrupted run.\n*.part\n"
                    "\n# Written by sb_restore.py --mode rebuild.\n"
                    "restore_maps/\n")


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
    root, external = assets_root(site, outdir, args.assets_dir)
    # LFS is only needed when binaries are committed. With the media on a bucket
    # the repo stays text-only, so requiring LFS would be a dependency for
    # nothing -- and would fail the run on a machine that does not have it.
    ensure_repo(repo, outdir, want_lfs=want_assets and not external)
    install_tools(repo)
    if want_assets:
        print(f"  media -> {root}"
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
            print(f"    index: {len(stories)}; fetching content")
            res = download_stories(api, token, stories, outdir, args.workers)
            counts["stories_with_content"] = res["saved"]
            story_meta = res["meta"]
            if res["failed"]:
                errors["stories_content"] = res["errors"]
            if res["deleted_since_last_run"]:
                print(f"    removed {res['deleted_since_last_run']} story "
                      f"file(s) no longer in the space")

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
            if args.verify_assets:
                print(f"    verifying {len(assets)} file(s) against "
                      f"{len(prev_sha)} recorded checksum(s)")
                v = verify_assets(assets, root, space_id, prev_sha)
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
                res = download_assets(assets, root, space_id, prev_sha,
                                      args.workers)
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
                assets, folders, space_id, outdir, root, external, asset_sha)
            print(f"    manifest_assets.csv     "
                  f"{counts['manifest_assets']} row(s)")
            missing = counts.get("assets", 0) - counts.get("asset_files", 0)
            if missing > 0 and not (args.no_assets or args.verify_assets):
                print(f"    !! {missing} asset(s) have metadata but no file - "
                      f"see file_present=NO in manifest_assets.csv")

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
            # beats no backup at all.
            print(f"  !! {s['name']}: {type(e).__name__}: {e}")
            failed.append(s["name"])

    print(f"\n{'=' * 74}\n  ok: {', '.join(done) or 'none'}")
    if failed:
        print(f"  FAILED: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
