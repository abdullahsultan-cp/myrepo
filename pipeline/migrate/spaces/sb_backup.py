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
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sb_common import (
    asset_path,
    fetch_list,
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

def download_assets(assets, outdir, space_id, workers=6):
    """Fetch every binary not already on disk at the right size.

    Skipping by size is what makes a second run cheap, and that is the
    difference between a backup that gets taken nightly and one taken once.
    """
    jobs = []
    for a in assets:
        rel, url = asset_path(a, space_id), a.get("filename")
        if rel and url:
            jobs.append((a, url, os.path.join(outdir, rel)))

    got = skipped = failed = 0
    errors, lock, total = [], threading.Lock(), len(jobs)

    def one(job):
        a, url, dest = job
        expected = a.get("content_length")
        if os.path.exists(dest):
            try:
                if not expected or os.path.getsize(dest) == int(expected):
                    return "skip", None
            except (TypeError, ValueError):
                return "skip", None
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = dest + ".part"
        try:
            r = get(url, stream=True)          # no token: asset URLs are public
            if r.status_code != 200:
                return "fail", f"{a.get('id')} {url} -> {r.status_code}"
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(65536):
                    if chunk:
                        f.write(chunk)
            os.replace(tmp, dest)   # never leave a half file looking complete
            return "ok", None
        except Exception as e:
            # Broad on purpose: one unreadable asset out of thousands must be
            # reported and skipped, not allowed to end the run. The type and
            # message go into _summary.json so it is still visible afterwards.
            if os.path.exists(tmp):
                os.remove(tmp)
            return "fail", f"{a.get('id')} {url} -> {type(e).__name__}: {e}"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, j) for j in jobs]
        for n, fut in enumerate(as_completed(futures), 1):
            status, err = fut.result()
            with lock:
                if status == "ok":
                    got += 1
                elif status == "skip":
                    skipped += 1
                else:
                    failed += 1
                    errors.append(err)
            if n % 200 == 0 or n == total:
                print(f"      {n}/{total}  downloaded {got}  "
                      f"already had {skipped}  failed {failed}", flush=True)

    # Sorted, not in completion order: these land in the committed
    # _summary.json, and thread scheduling would otherwise reshuffle the same
    # failures into a fresh diff on every run.
    return {"downloaded": got, "already_present": skipped, "failed": failed,
            "errors": sorted(e for e in errors if e)[:50]}


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
    total = len(stories)

    def one(st):
        sid = st.get("id")
        r = get(f"{api}/stories/{sid}", token)
        if r.status_code != 200:
            return f"{sid} {st.get('full_slug')} -> {r.status_code}"
        story = r.json().get("story")
        if not story:
            return f"{sid} -> empty body"
        write_json(os.path.join(story_dir, f"{sid}.json"), story)
        return None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, s) for s in stories]
        for n, fut in enumerate(as_completed(futures), 1):
            err = fut.result()
            with lock:
                if err:
                    failed += 1
                    errors.append(err)
                else:
                    ok += 1
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
            "errors": sorted(errors)[:50]}


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
    ensure_repo(repo, outdir, want_lfs=want_assets)
    install_tools(repo)

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

    if "stories" in only:
        print("\n  stories")
        stories, err = fetch_list(api, "stories", "stories", True, token)
        if err:
            print(f"    !! {err}")
            errors["stories"] = err
        else:
            counts["stories"] = save(outdir, "stories", stories)
            print(f"    index: {len(stories)}; fetching content")
            res = download_stories(api, token, stories, outdir, args.workers)
            counts["stories_with_content"] = res["saved"]
            if res["failed"]:
                errors["stories_content"] = res["errors"]
            if res["deleted_since_last_run"]:
                print(f"    removed {res['deleted_since_last_run']} story "
                      f"file(s) no longer in the space")

    if "assets" in only:
        print("\n  assets")
        assets, err = fetch_list(api, "assets", "assets", True, token)
        if err:
            print(f"    !! {err}")
            errors["assets"] = err
        else:
            counts["assets"] = save(outdir, "assets", assets)
            print(f"    metadata: {len(assets)}")
            if args.no_assets:
                print("    binaries skipped (--no-assets)")
            else:
                res = download_assets(assets, outdir, space_id, args.workers)
                counts["asset_files"] = (res["downloaded"]
                                         + res["already_present"])
                if res["failed"]:
                    errors["asset_files"] = res["errors"]

    save(outdir, "_summary", {"site": name, "space_id": space_id,
                              "space_name": sp.get("name"),
                              "region": site.get("region", "eu"),
                              "counts": counts, "errors": errors})
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
