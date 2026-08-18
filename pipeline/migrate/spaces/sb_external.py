#!/usr/bin/env python3
"""
sb_external.py — bring externally-hosted files into Storyblok and repoint the
pages at them. WRITES to the live space; dry run unless --apply.

Across the three spaces, 273 references point at files that are not Storyblok
assets: 175 on AKU's own domains (www.aku.edu, hospitals.aku.edu, portal.aku.edu)
and 98 on third-party sites. The AKU domains are being switched off, so those
files and every page depending on them are on a clock.

For each reference this:

    1. downloads the file from where it lives now
    2. uploads it into Storyblok as a real asset
    3. rewrites the story content to point at the new asset URL

Uploading into STORYBLOK, not into the Azure container, and that is the whole
design. The container is private: a link into it is dead for every visitor. Once
the file is a Storyblok asset it is served by Storyblok's CDN, the links work, and
the ordinary backup copies it into Azure on the next run without being told to.

Third-party hosts are excluded unless you pass --third-party. Copying AKU's own
files off a server AKU is retiring is housekeeping; rehosting somebody else's
document on AKU's CDN and changing the link to match is republishing it, which is
a decision for a person rather than a default.

Usage (from a backup repo):
    python tools/sb.py external                     # what would happen
    python tools/sb.py external --apply
    python tools/sb.py external --third-party --apply
    python tools/sb.py external --host hospitals.aku.edu --apply
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from urllib.parse import unquote, urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sb_common import (
    OK_STATUS,
    call,
    fetch_list,
    get,
    load_sites,
    pick_sites,
    repo_paths,
    space_api,
    token_for,
    write_json,
)

# Where imported files land, so they are distinguishable from what editors put
# there. Created if missing.
FOLDER = "imported-external"

# Refused outright. A page pointing at a login page or a whole site archive is
# not a file reference worth importing, and .exe/.js/.html are not media.
SKIP_EXT = {"html", "htm", "php", "asp", "aspx", "js", "exe", "dll"}


def rows_for(outdir, hosts=None, third_party=False):
    """The references to import, from manifest_external_refs.csv."""
    path = os.path.join(outdir, "manifest_external_refs.csv")
    if not os.path.exists(path):
        sys.exit(f"  no {path}\n"
                 f"  run `python tools/sb.py backup` first - the manifest is "
                 f"what this reads.")
    out = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if (r.get("ext") or "").lower() in SKIP_EXT:
                continue
            if hosts and not any(h.lower() in r["host"] for h in hosts):
                continue
            if not hosts and not third_party and r.get("aku_owned") != "yes":
                continue
            out.append(r)
    return out


def ensure_folder(api, token, name):
    """The asset folder to import into, found or created."""
    folders, err = fetch_list(api, "asset_folders", "asset_folders", False,
                              token)
    if not err:
        for f in folders or []:
            if (f.get("name") or "").lower() == name.lower() \
                    and not f.get("parent_id"):
                return f["id"]
    r = call("POST", f"{api}/asset_folders", token,
             body={"asset_folder": {"name": name}})
    if r.status_code in OK_STATUS:
        return (r.json() or {}).get("asset_folder", {}).get("id")
    print(f"    !! could not create the '{name}' folder "
          f"({r.status_code}); importing to the root instead")
    return None


def filename_for(url):
    base = os.path.basename(unquote(urlsplit(url).path)) or "file"
    # Storyblok is strict about asset filenames; a space or a bracket in one is
    # how an upload succeeds and then 404s.
    keep = "".join(c if (c.isalnum() or c in "._-") else "-" for c in base)
    return keep.strip("-._")[:120] or "file"


def upload(api, token, url, folder_id, timeout=180):
    """Download from `url` and put it into Storyblok. Returns (asset, error)."""
    try:
        r = get(url, tries=3, stream=True)
    except Exception as e:
        return None, f"download: {type(e).__name__}"
    if r.status_code != 200:
        return None, f"download: HTTP {r.status_code}"
    body = r.content
    if not body:
        return None, "download: empty"

    name = filename_for(url)
    sign = call("POST", f"{api}/assets", token, body={
        "filename": name, "size": len(body), "validate_upload": 1,
        **({"asset_folder_id": folder_id} if folder_id else {})})
    if sign.status_code not in OK_STATUS:
        return None, f"sign: {sign.status_code} {sign.text[:90]}"
    signed = sign.json()
    post_url, fields = signed.get("post_url"), signed.get("fields") or {}
    new_id = signed.get("id")
    if not post_url:
        return None, "sign: no post_url"

    up = call("POST", post_url, None, data=fields,
              files={"file": (name, body)}, timeout=timeout)
    if up.status_code not in (200, 201, 204):
        return None, f"s3: {up.status_code}"

    fin = get(f"{api}/assets/{new_id}/finish_upload", token)
    if fin.status_code not in OK_STATUS:
        return None, f"finish: {fin.status_code}"

    got = get(f"{api}/assets/{new_id}", token)
    asset = got.json().get("asset", {}) if got.status_code == 200 else {}
    if not asset.get("filename"):
        return None, "no url came back"
    return asset, None


def run(site, args):
    api, token = space_api(site), token_for(site)
    repo, outdir = repo_paths(site)
    refs = rows_for(outdir, args.host, args.third_party)

    by_url = {}
    for r in refs:
        by_url.setdefault(r["url"], []).append(r)
    stories = {r["story_id"] for r in refs}

    print(f"\n  external import - {site['name']} space {site['space_id']}")
    print(f"  {len(by_url)} distinct file(s) across {len(stories)} story(ies)")
    hosts = {}
    for u, rs in by_url.items():
        h = rs[0]["host"]
        hosts[h] = hosts.get(h, 0) + 1
    for h, n in sorted(hosts.items(), key=lambda x: -x[1]):
        owned = next(r["aku_owned"] for r in refs if r["host"] == h)
        print(f"    {n:>5}  {h}{'' if owned == 'yes' else '   (third party)'}")

    if not by_url:
        print("\n  nothing to import"
              + ("" if args.third_party else
                 " - third-party hosts are excluded; --third-party includes them"))
        return 0

    # Already imported on an earlier run, so a repeat does not duplicate.
    map_path = os.path.join(repo, "restore_maps", "external_imported.json")
    done = {}
    if os.path.exists(map_path):
        with open(map_path, encoding="utf-8") as f:
            done = json.load(f)
    todo = [u for u in by_url if u not in done]
    if done:
        print(f"\n  {len(done)} already imported on an earlier run, "
              f"{len(todo)} left")

    if not args.apply:
        print(f"\n  DRY RUN - would download {len(todo)} file(s), upload them "
              f"into Storyblok\n  under '{FOLDER}/', and rewrite "
              f"{len(stories)} story(ies). Add --apply.")
        return 0

    folder_id = ensure_folder(api, token, FOLDER)
    url_map, failed = dict(done), []
    for i, u in enumerate(sorted(todo), 1):
        asset, err = upload(api, token, u, folder_id)
        if err:
            failed.append((u, err))
            print(f"    {i}/{len(todo)}  FAILED  {err:<28} {u[:70]}",
                  flush=True)
            continue
        url_map[u] = asset["filename"]
        print(f"    {i}/{len(todo)}  ok  {u[:64]}", flush=True)

    write_json(map_path, url_map)

    # ---- rewrite the stories, read live so nothing else is clobbered
    touched = sorted({r["story_id"] for r in refs if r["url"] in url_map})
    print(f"\n  rewriting {len(touched)} story(ies)")
    fixed, unchanged, errors = 0, 0, []
    for sid in touched:
        r = get(f"{api}/stories/{sid}", token)
        if r.status_code != 200:
            errors.append(f"story {sid}: read {r.status_code}")
            continue
        story = r.json().get("story") or {}
        before = json.dumps(story.get("content") or {}, ensure_ascii=False)
        after = before
        for old, new in url_map.items():
            if old in after:
                after = after.replace(old, new)
        if after == before:
            unchanged += 1
            continue
        body = {"story": {"content": json.loads(after)}, "force_update": "1"}
        # Only republish something already live and clean, so a page holding
        # unpublished edits is not pushed out as a side effect of a link fix.
        if story.get("published") and not story.get("unpublished_changes"):
            body["publish"] = 1
        pr = call("PUT", f"{api}/stories/{sid}", token, body=body)
        if pr.status_code in OK_STATUS:
            fixed += 1
        else:
            errors.append(f"story {sid}: write {pr.status_code} "
                          f"{pr.text[:80]}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    write_json(os.path.join(repo, "restore_maps",
                            f"external-{stamp}.json"),
               {"space": str(site["space_id"]), "url_map": url_map,
                "stories_rewritten": fixed, "failed": failed,
                "errors": errors})

    print(f"\n  imported {len(url_map) - len(done)}   "
          f"stories rewritten {fixed}   already correct {unchanged}   "
          f"failed {len(failed)}   errors {len(errors)}")
    for u, e in failed[:15]:
        print(f"      {e:<30} {u[:80]}")
    for e in errors[:10]:
        print(f"      {e}")
    print("\n  Run `python tools/sb.py backup --push` next: the new assets are "
          "real\n  Storyblok assets now, so the backup copies them into the "
          "container.")
    return 1 if (failed or errors) else 0


def main():
    ap = argparse.ArgumentParser(
        description="Import externally-hosted files into Storyblok and "
                    "repoint the pages at them.")
    ap.add_argument("--site", required=True)
    ap.add_argument("--config")
    ap.add_argument("--apply", action="store_true",
                    help="actually download, upload and rewrite")
    ap.add_argument("--third-party", action="store_true",
                    help="include hosts AKU does not own. Rehosting someone "
                         "else's document under AKU's domain is a decision, "
                         "not a default.")
    ap.add_argument("--host", action="append",
                    help="only this host (repeatable); implies --third-party "
                         "for the hosts named")
    args = ap.parse_args()

    sites = pick_sites(load_sites(args.config), args.site)
    if len(sites) != 1:
        sys.exit("--site takes exactly one site")
    return run(sites[0], args)


if __name__ == "__main__":
    sys.exit(main())
