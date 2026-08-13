#!/usr/bin/env python3
"""
sb_restore.py — put a backup taken by sb_backup.py back into Storyblok.

    --mode in-place     repair a space that is still there
    --mode assets       put deleted assets back and repoint the stories
    --mode rebuild      recreate the space from scratch, in an empty one

BOTH MODES ARE A DRY RUN UNLESS YOU PASS --apply. Nothing is written without
it; a dry run prints exactly what would change and exits 0.

in-place
    Finds each backed-up story by its own id and writes the saved content back
    with a PUT. It never deletes and never re-creates, so story ids, editor
    review links and anything a person edited by hand all survive. The cost of
    that promise: a story someone hard-deleted cannot come back this way -- its
    id is gone -- so those are listed and left alone. Rebuild is the answer
    there, or re-creating the one story by hand.

    Because the backup is a git repo, --from-rev restores from any past commit
    rather than the working tree:

        python sb_restore.py --site AKU --mode in-place --story 12345 \
            --from-rev HEAD~5 --apply

assets
    Someone deleted an image in Storyblok. The bytes are still in the bucket, but
    the asset row is gone and every story that used it renders a broken image.
    Re-uploading alone does not fix that -- the file comes back with a new id and
    a new url, and the stories still point at the old one. So this uploads from
    the bucket AND rewrites every story that referenced it, reading each story
    live so nothing edited since the backup is clobbered.

        python $SB --site AKUH --mode assets                    # what is missing
        python $SB --site AKUH --mode assets --apply
        python $SB --site AKUH --mode assets --asset 1234 --apply

rebuild
    For a space that is gone or being cloned. Creates component groups,
    components, datasources, internal tags, asset folders, assets and stories
    into --into <empty space id>, in that order, because each depends on the
    one before it. Every id changes, so references inside story content are
    rewritten as it goes: asset urls and ids, story links, parent folders. The
    old -> new maps are written to restore_maps/ so the run can be audited or
    resumed.

    Story uuids are sent on create and kept when Storyblok allows it, which is
    what lets internal links keep working. Where a uuid comes back different, a
    second pass rewrites the links that pointed at it.

Usage (from the repo root; SB=pipeline/migrate/spaces/sb_restore.py)
    python $SB --site AKU --mode in-place                        # dry run
    python $SB --site AKU --mode in-place --story 12345 --apply
    python $SB --site AKU --mode in-place --all --apply
    python $SB --site AKUEB --mode rebuild --into 999888          # dry run
    python $SB --site AKUEB --mode rebuild --into 999888 --apply

This is the only script under pipeline/ that writes to a space it did not
migrate, which is why every guard below refuses by default and needs --apply.
"""

import argparse
import json
import os
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sb_common import (
    ASSET_URL_RE,
    OK_STATUS,
    api_base,
    asset_path,
    asset_url_key,
    call,
    fetch_list,
    get,
    git,
    load_json,
    load_sites,
    pick_sites,
    repo_paths,
    space_api,
    token_for,
    write_json,
)
from sb_storage import make_backend

# Written back in-place by default. Deliberately not slug, parent_id or
# position: those move a story, and moving 4,000 stories to fix one broken body
# is a bigger accident than the one being repaired. --with-structure adds them.
CONTENT_FIELDS = ["content", "name", "tag_list", "is_startpage", "meta_data"]
STRUCTURE_FIELDS = ["slug", "parent_id", "path", "position", "is_folder"]


# --------------------------------------------------------------------------
# reading the snapshot
# --------------------------------------------------------------------------

class Snapshot:
    """The backup on disk, or as it was at some past commit.

    `rev` reads through `git show` instead of the working tree, which is the
    reason the backup is a git repo rather than a folder that gets overwritten:
    "put it back the way it was on Tuesday" is the actual request, and only
    history can answer it.
    """

    def __init__(self, repo, outdir, rev=None, store=None):
        self.repo, self.outdir, self.rev = repo, outdir, rev
        self.prefix = os.path.relpath(outdir, repo).replace(os.sep, "/")
        # Where the binaries actually are: a folder, a mount, or an Azure
        # container. The manifest's paths are relative to whichever it is.
        self.store = store
        self._tmp = []

    def _git_show(self, rel):
        r = git(self.repo, "show", f"{self.rev}:{self.prefix}/{rel}",
                check=False)
        return r.stdout if r.returncode == 0 else None

    def read(self, rel, default=None):
        if self.rev:
            raw = self._git_show(rel)
            return json.loads(raw) if raw else default
        return load_json(os.path.join(self.outdir, rel), default)

    def story_ids(self):
        if self.rev:
            r = git(self.repo, "ls-tree", "--name-only",
                    f"{self.rev}:{self.prefix}/stories", check=False)
            names = r.stdout.split() if r.returncode == 0 else []
        else:
            d = os.path.join(self.outdir, "stories")
            names = os.listdir(d) if os.path.isdir(d) else []
        return sorted(int(n[:-5]) for n in names
                      if n.endswith(".json") and n[:-5].isdigit())

    def story(self, sid):
        return self.read(f"stories/{sid}.json")

    def asset_rel(self, asset, space_id):
        """The asset's path relative to the storage root.

        `asset_path` yields "assets/<mirrored>"; the leading segment is dropped
        because the storage root already IS that folder -- which is what lets one
        path address a file in the repo, on a mount, or as a blob.
        """
        rel = asset_path(asset, space_id)
        if not rel:
            return None
        rel = rel.split(os.sep, 1)[1] if os.sep in rel else rel
        return rel.replace(os.sep, "/")

    def has_asset(self, asset, space_id):
        rel = self.asset_rel(asset, space_id)
        return bool(rel) and self.store.size(rel) is not None

    def asset_file(self, asset, space_id):
        """A local path to the asset's bytes, fetching from the container first.

        Never read through a git revision: under LFS `git show` returns the
        pointer text rather than the file, so a rev-based read would hand a
        rebuild a 130-byte text file named photo.jpg. To rebuild from an old
        commit, check that commit out first.
        """
        rel = self.asset_rel(asset, space_id)
        if not rel:
            return None
        local = getattr(self.store, "_p", None)
        if local:                                     # a folder: use it directly
            p = local(rel)
            return p if os.path.exists(p) else None
        # A remote container: pull it to scratch for the upload, then clean up.
        fd, tmp = tempfile.mkstemp(suffix="-" + os.path.basename(rel))
        os.close(fd)
        got = self.store.download_to(rel, tmp)
        if not got:
            os.path.exists(tmp) and os.unlink(tmp)
            return None
        self._tmp.append(tmp)
        return tmp

    def release(self, path):
        """Drop a scratch copy once it has been uploaded."""
        if path in self._tmp:
            self._tmp.remove(path)
            if os.path.exists(path):
                os.unlink(path)


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


# --------------------------------------------------------------------------
# in-place
# --------------------------------------------------------------------------

def restore_in_place(site, snap, args):
    api, token = space_api(site), token_for(site)
    fields = list(CONTENT_FIELDS) + (STRUCTURE_FIELDS
                                     if args.with_structure else [])

    saved_space = snap.read("space.json", {}) or {}
    if str(saved_space.get("id")) != str(site["space_id"]) and not args.force:
        sys.exit(f"  !! this backup is of space {saved_space.get('id')}, but "
                 f"{site['name']} points at {site['space_id']}.\n"
                 f"     in-place would write one space's content into another. "
                 f"--force to override.")

    ids = args.story or snap.story_ids()
    if not args.story and not args.all:
        sys.exit("  in-place needs --all, or --story <id> (repeatable).\n"
                 f"  the snapshot holds {len(ids)} stories.")

    print(f"\n  in-place restore - {site['name']} space {site['space_id']}")
    print(f"  source: {'commit ' + args.from_rev if args.from_rev else 'working tree'}")
    print(f"  fields: {', '.join(fields)}")
    print(f"  stories to check: {len(ids)}\n")

    differs, identical, missing, errors = [], 0, [], []
    lock = threading.Lock()

    def inspect(sid):
        want = snap.story(sid)
        if not want:
            return ("error", sid, "not in the snapshot")
        r = get(f"{api}/stories/{sid}", token)
        if r.status_code == 404:
            return ("missing", sid, want.get("full_slug"))
        if r.status_code != 200:
            return ("error", sid, f"{r.status_code} {r.text[:120]}")
        live = r.json().get("story") or {}
        changed = [f for f in fields
                   if f in want and canonical(want.get(f)) != canonical(live.get(f))]
        if not changed:
            return ("same", sid, None)
        return ("differs", sid, {"slug": want.get("full_slug"),
                                 "fields": changed, "want": want})

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(inspect, i) for i in ids]
        for n, fut in enumerate(as_completed(futures), 1):
            kind, sid, info = fut.result()
            with lock:
                if kind == "same":
                    identical += 1
                elif kind == "differs":
                    differs.append((sid, info))
                elif kind == "missing":
                    missing.append((sid, info))
                else:
                    errors.append((sid, info))
            if n % 250 == 0 or n == len(ids):
                print(f"    compared {n}/{len(ids)}", flush=True)

    differs.sort(key=lambda x: x[0])
    print(f"\n  identical {identical}   differ {len(differs)}   "
          f"hard-deleted {len(missing)}   unreadable {len(errors)}")

    for sid, info in differs[:40]:
        print(f"    {sid:<10} {info['slug'] or '':<50} "
              f"{', '.join(info['fields'])}")
    if len(differs) > 40:
        print(f"    ... and {len(differs) - 40} more")
    if missing:
        print("\n  hard-deleted, so in-place cannot restore them "
              "(use --mode rebuild, or re-create by hand):")
        for sid, slug in missing[:20]:
            print(f"    {sid:<10} {slug or ''}")
        if len(missing) > 20:
            print(f"    ... and {len(missing) - 20} more")
    if errors:
        print("\n  unreadable:")
        for sid, why in errors[:20]:
            print(f"    {sid:<10} {why}")

    if not differs:
        print("\n  nothing to write - the space matches the snapshot")
        return 0
    if not args.apply:
        print(f"\n  DRY RUN - {len(differs)} story(ies) would be written. "
              f"Add --apply to do it.")
        return 0

    print(f"\n  writing {len(differs)} story(ies)")
    ok, failed = 0, []

    def put(item):
        sid, info = item
        want = info["want"]
        payload = {f: want[f] for f in fields if f in want}
        body = {"story": payload, "force_update": "1"}
        # Mirror the snapshot's publish state rather than choosing one: a story
        # that was a draft when the backup was taken must not go live because
        # it happened to be restored.
        if want.get("published") and not args.no_publish:
            body["publish"] = 1
        r = call("PUT", f"{api}/stories/{sid}", token, body=body)
        if r.status_code in OK_STATUS:
            return sid, None
        return sid, f"{r.status_code} {r.text[:160]}"

    with ThreadPoolExecutor(max_workers=min(args.workers, 4)) as pool:
        futures = [pool.submit(put, d) for d in differs]
        for n, fut in enumerate(as_completed(futures), 1):
            sid, err = fut.result()
            if err:
                failed.append((sid, err))
            else:
                ok += 1
            if n % 100 == 0 or n == len(differs):
                print(f"    written {n}/{len(differs)}  ok {ok}  "
                      f"failed {len(failed)}", flush=True)

    print(f"\n  restored {ok}   failed {len(failed)}")
    for sid, err in failed[:20]:
        print(f"    {sid:<10} {err}")
    return 1 if failed else 0


# --------------------------------------------------------------------------
# rebuild
# --------------------------------------------------------------------------

def _walk_strings(obj, fn):
    """Rewrite every string in a nested structure, in place where possible."""
    if isinstance(obj, dict):
        return {k: _walk_strings(v, fn) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk_strings(v, fn) for v in obj]
    if isinstance(obj, str):
        return fn(obj)
    return obj


def remap_content(content, url_map, asset_id_map, uuid_map):
    """Rewrite every reference in a story's content for the new space.

    Three passes, because Storyblok stores the same reference three ways:

      * an asset field is an object holding both `id` and `filename`
      * a rich-text image node holds the url in `attrs.src`
      * and any plain string can hold a url -- a link in prose, an embed, a
        hand-written srcset

    The blanket string replacement catches the third and, incidentally, the
    first two as well; the object pass exists because `id` is a number and no
    string replacement will ever fix it. Doing only the tidy object pass is how
    a rebuilt space renders with half its images missing.
    """
    # Keyed on the stable part of each URL, never the whole thing. Storyblok
    # serves one asset under several hosts -- assets.json gives the S3 form,
    # story content carries the CDN form -- so exact-string matching replaced
    # almost nothing and left a rebuilt space pointing at the old one's images.
    by_key = {}
    for old, new in (url_map or {}).items():
        k = asset_url_key(old)
        if k:
            by_key[k] = new

    def fix_str(s):
        if "/f/" not in s:
            return s

        def swap(m):
            new = by_key.get(asset_url_key(m.group(0)))
            return new if new else m.group(0)

        return ASSET_URL_RE.sub(swap, s)

    def fix_objects(obj):
        if isinstance(obj, list):
            return [fix_objects(o) for o in obj]
        if not isinstance(obj, dict):
            return obj
        out = {k: fix_objects(v) for k, v in obj.items()}
        # asset field: id travels with filename
        if "filename" in out and isinstance(out.get("id"), int):
            if out["id"] in asset_id_map:
                out["id"] = asset_id_map[out["id"]]
        # rich-text image node
        if out.get("type") == "image" and isinstance(out.get("attrs"), dict):
            a = out["attrs"]
            if isinstance(a.get("id"), int) and a["id"] in asset_id_map:
                a["id"] = asset_id_map[a["id"]]
        # internal story link: id holds the target story's uuid
        if out.get("linktype") == "story" and isinstance(out.get("id"), str):
            out["id"] = uuid_map.get(out["id"], out["id"])
        if isinstance(out.get("uuid"), str) and out.get("linktype") == "story":
            out["uuid"] = uuid_map.get(out["uuid"], out["uuid"])
        return out

    return fix_objects(_walk_strings(content, fix_str))


def upload_asset(api, token, local_path, asset, folder_id):
    """Storyblok's three-step signed upload. Returns the new asset dict.

    1. POST /assets      -> a signed S3 form (post_url + fields)
    2. POST post_url      -> the bytes go to S3, which answers 204
    3. GET  finish_upload -> Storyblok records the asset

    Skipping step 3 leaves an asset row that exists but has no file, which
    looks like a successful upload right up until the page renders.
    """
    filename = os.path.basename(local_path)
    body = {"filename": filename, "validate_upload": 1}
    if folder_id:
        body["asset_folder_id"] = folder_id
    if asset.get("content_type"):
        body["content_type"] = asset["content_type"]

    r = call("POST", f"{api}/assets", token, body=body)
    if r.status_code not in OK_STATUS:
        return None, f"signing failed: {r.status_code} {r.text[:160]}"
    signed = r.json()
    post_url, fields = signed.get("post_url"), signed.get("fields") or {}
    new_id = signed.get("id")
    if not post_url:
        return None, f"no post_url in signing response: {str(signed)[:160]}"

    with open(local_path, "rb") as f:
        # No token here: it is a signed S3 form, and the management token has no
        # business being sent to a third-party host.
        r2 = call("POST", post_url, None,
                  data=fields, files={"file": (filename, f)}, timeout=300)
    if r2.status_code not in (200, 201, 204):
        return None, f"S3 upload failed: {r2.status_code} {r2.text[:160]}"

    r3 = get(f"{api}/assets/{new_id}/finish_upload", token)
    if r3.status_code not in OK_STATUS:
        return None, f"finish_upload failed: {r3.status_code} {r3.text[:160]}"

    r4 = get(f"{api}/assets/{new_id}", token)
    new = r4.json().get("asset", {}) if r4.status_code == 200 else {"id": new_id}

    # Carry over the metadata an editor typed. alt text is accessibility, not
    # decoration, and it is not recoverable from anywhere else.
    meta = {k: asset[k] for k in ("alt", "title", "copyright", "source",
                                  "focus", "internal_tag_ids")
            if asset.get(k) not in (None, "", [])}
    if meta:
        call("PUT", f"{api}/assets/{new_id}", token, body={"asset": meta})
    return new, None


def _create_tree(items, api, token, path, key, build, label):
    """Create parent-before-child, returning {old id: new id}.

    Storyblok rejects a child whose parent does not exist yet, and the export
    order is by id, which is not the same as tree order.
    """
    by_id = {i["id"]: i for i in items}
    id_map, pending, errors = {}, list(items), []
    while pending:
        progressed = False
        still = []
        for it in pending:
            parent = it.get("parent_id") or 0
            if parent and parent in by_id and parent not in id_map:
                still.append(it)          # parent not created yet
                continue
            body = build(it, id_map)
            r = call("POST", f"{api}/{path}", token, body={key: body})
            if r.status_code in OK_STATUS:
                new = (r.json() or {}).get(key, {})
                id_map[it["id"]] = new.get("id")
                progressed = True
            else:
                errors.append(f"{label} {it.get('id')} "
                              f"{it.get('name') or it.get('slug')}: "
                              f"{r.status_code} {r.text[:120]}")
                progressed = True         # do not retry forever on a hard error
        pending = still
        if not progressed and pending:
            # A cycle, or a parent that was never exported. Create the rest at
            # the root rather than dropping them: a folder in the wrong place is
            # fixable, a folder that does not exist loses its contents.
            for it in pending:
                body = build(it, id_map)
                body.pop("parent_id", None)
                r = call("POST", f"{api}/{path}", token, body={key: body})
                if r.status_code in OK_STATUS:
                    id_map[it["id"]] = (r.json() or {}).get(key, {}).get("id")
                    errors.append(f"{label} {it['id']}: parent missing, "
                                  f"created at the root")
                else:
                    errors.append(f"{label} {it['id']}: {r.status_code}")
            break
    return id_map, errors


def restore_rebuild(site, snap, args):
    src_space = str(site["space_id"])
    target = str(args.into)
    token = args.into_token or os.environ.get("SB_TOKEN_TARGET") or token_for(site)
    api = f"{api_base(site)}/spaces/{target}"

    if target == src_space and not args.force:
        sys.exit(f"  !! --into {target} is the site's own space. Rebuild "
                 f"creates everything fresh, so pointing it at a live space "
                 f"duplicates the whole thing.\n     Use --mode in-place, or "
                 f"--force if you truly mean it.")

    r = get(api, token)
    if r.status_code != 200:
        sys.exit(f"  !! cannot read target space {target}: "
                 f"{r.status_code} {r.text[:200]}")
    tname = (r.json().get("space") or {}).get("name")

    existing, _ = fetch_list(api, "stories", "stories", True, token)
    if existing and not args.force:
        sys.exit(f"  !! target space {target} ({tname}) already holds "
                 f"{len(existing)} stories. Rebuild is for an empty space; "
                 f"into a populated one it creates duplicates.\n"
                 f"     Empty it first, or --force.")

    groups = snap.read("component_groups.json", []) or []
    comps = snap.read("components.json", []) or []
    dsources = snap.read("datasources.json", []) or []
    dentries = snap.read("datasource_entries.json", []) or []
    itags = snap.read("internal_tags.json", []) or []
    afolders = snap.read("asset_folders.json", []) or []
    assets = snap.read("assets.json", []) or []
    story_ids = snap.story_ids()

    stories = [snap.story(i) for i in story_ids]
    stories = [s for s in stories if s]
    folders = [s for s in stories if s.get("is_folder")]
    leaves = [s for s in stories if not s.get("is_folder")]

    # An asset row whose binary never made it to disk would be recreated as an
    # empty asset, and every story pointing at it would render a broken image.
    # Better to know before anything is written.
    have, absent = [], []
    for a in assets:
        (have if snap.has_asset(a, src_space) else absent).append(a)

    print(f"\n  rebuild - {site['name']} backup -> space {target} ({tname})")
    print(f"  {'component groups':<22} {len(groups)}")
    print(f"  {'components':<22} {len(comps)}")
    print(f"  {'datasources':<22} {len(dsources)} "
          f"({len(dentries)} entries)")
    print(f"  {'internal tags':<22} {len(itags)}")
    print(f"  {'asset folders':<22} {len(afolders)}")
    print(f"  {'assets':<22} {len(have)} to upload"
          + (f", {len(absent)} WITH NO FILE ON DISK" if absent else ""))
    print(f"  {'story folders':<22} {len(folders)}")
    print(f"  {'stories':<22} {len(leaves)}")

    if absent:
        print(f"\n  !! {len(absent)} asset(s) have metadata but no binary. "
              f"Re-run sb_backup.py to fetch them, or they will be skipped:")
        for a in absent[:10]:
            print(f"       {a.get('id')} {a.get('filename')}")

    if not args.apply:
        print("\n  DRY RUN - nothing written. Add --apply to rebuild.")
        return 0

    maps = {"source_space": src_space, "target_space": target}
    errors = []

    # ---- 1. component groups, so components can point at them
    print("\n  component groups")
    gmap = {}
    for g in groups:
        r = call("POST", f"{api}/component_groups", token,
                 body={"component_group": {"name": g["name"]}})
        if r.status_code in OK_STATUS:
            new = (r.json() or {}).get("component_group", {})
            gmap[g.get("uuid")] = new.get("uuid")
        else:
            errors.append(f"component_group {g['name']}: {r.status_code} "
                          f"{r.text[:120]}")
    print(f"    created {len(gmap)}/{len(groups)}")
    maps["component_group_uuid"] = gmap

    # ---- 2. components. Schemas reference other components by NAME, which
    #         does not change, so nothing inside a schema needs remapping.
    print("  components")
    cmap = {}
    for c in comps:
        body = {k: c[k] for k in
                ("name", "display_name", "schema", "image", "preview_field",
                 "is_root", "is_nestable", "preview_tmpl", "color_id",
                 "icon", "real_name", "component_group_uuid")
                if k in c}
        if body.get("component_group_uuid"):
            body["component_group_uuid"] = gmap.get(
                body["component_group_uuid"])
        r = call("POST", f"{api}/components", token, body={"component": body})
        if r.status_code in OK_STATUS:
            cmap[c["name"]] = (r.json() or {}).get("component", {}).get("id")
        else:
            errors.append(f"component {c['name']}: {r.status_code} "
                          f"{r.text[:160]}")
    print(f"    created {len(cmap)}/{len(comps)}")
    maps["component_name_to_id"] = cmap

    # ---- 3. datasources and their entries
    print("  datasources")
    dmap = {}
    for d in dsources:
        r = call("POST", f"{api}/datasources", token, body={"datasource": {
            "name": d["name"], "slug": d["slug"],
            "dimensions_attributes": d.get("dimensions", [])}})
        if r.status_code in OK_STATUS:
            dmap[d["id"]] = (r.json() or {}).get("datasource", {}).get("id")
        else:
            errors.append(f"datasource {d['slug']}: {r.status_code}")
    made = 0
    for e in dentries:
        new_ds = dmap.get(e.get("datasource_id"))
        if not new_ds:
            continue
        r = call("POST", f"{api}/datasource_entries", token,
                 body={"datasource_entry": {
                     "name": e["name"], "value": e.get("value"),
                     "datasource_id": new_ds}})
        if r.status_code in OK_STATUS:
            made += 1
        else:
            errors.append(f"datasource_entry {e.get('name')}: {r.status_code}")
    print(f"    created {len(dmap)} datasource(s), {made} entry(ies)")
    maps["datasource_id"] = dmap

    # ---- 4. internal tags, referenced by asset metadata
    print("  internal tags")
    tmap = {}
    for t in itags:
        r = call("POST", f"{api}/internal_tags", token, body={
            "internal_tag": {"name": t["name"],
                             "object_type": t.get("object_type", "asset")}})
        if r.status_code in OK_STATUS:
            tmap[t["id"]] = (r.json() or {}).get("internal_tag", {}).get("id")
    print(f"    created {len(tmap)}/{len(itags)}")
    maps["internal_tag_id"] = tmap

    # ---- 5. asset folders, parents first
    print("  asset folders")
    fmap, ferrs = _create_tree(
        afolders, api, token, "asset_folders", "asset_folder",
        lambda it, m: {"name": it["name"],
                       "parent_id": m.get(it.get("parent_id"))},
        "asset_folder")
    errors += ferrs
    print(f"    created {len([v for v in fmap.values() if v])}/{len(afolders)}")
    maps["asset_folder_id"] = fmap

    # ---- 6. assets. Uploads dominate the wall clock, so they run concurrently.
    print(f"  assets ({len(have)} files)")
    amap, url_map, lock = {}, {}, threading.Lock()
    done = 0

    def one_asset(a):
        path = snap.asset_file(a, src_space)
        if not path:
            return a, None, "bytes not found in storage"
        try:
            new, err = upload_asset(api, token, path, a,
                                    fmap.get(a.get("asset_folder_id")))
        finally:
            # A remote container is pulled to scratch one file at a time; without
            # this, rebuilding AKUEB would leave 31 GB in the temp directory.
            snap.release(path)
        if err:
            return a, None, err
        return a, new, None

    with ThreadPoolExecutor(max_workers=min(args.workers, 4)) as pool:
        futures = [pool.submit(one_asset, a) for a in have]
        for fut in as_completed(futures):
            a, new, err = fut.result()
            with lock:
                done += 1
                if err:
                    errors.append(f"asset {a.get('id')} "
                                  f"{a.get('filename')}: {err}")
                else:
                    amap[a["id"]] = new.get("id")
                    if a.get("filename") and new.get("filename"):
                        url_map[a["filename"]] = new["filename"]
                if done % 100 == 0 or done == len(have):
                    print(f"    uploaded {done}/{len(have)}  "
                          f"ok {len(amap)}", flush=True)
    maps["asset_id"] = amap
    maps["asset_url"] = url_map

    # ---- 7. story folders, parents first
    print("  story folders")
    def folder_body(it, m):
        b = {"name": it["name"], "slug": it["slug"], "is_folder": True,
             "parent_id": m.get(it.get("parent_id")) or 0}
        for k in ("default_root", "is_startpage", "position", "uuid"):
            if it.get(k) is not None:
                b[k] = it[k]
        return b

    smap, serrs = _create_tree(folders, api, token, "stories", "story",
                               folder_body, "story_folder")
    errors += serrs
    print(f"    created {len([v for v in smap.values() if v])}/{len(folders)}")

    # ---- 8. stories. uuid is sent so internal links survive; where Storyblok
    #         assigns a different one, pass 9 repairs the links.
    print(f"  stories ({len(leaves)})")
    uuid_map, id_map = {}, {}
    made, lock = 0, threading.Lock()

    def one_story(st):
        body = {"name": st.get("name"), "slug": st.get("slug"),
                "content": remap_content(st.get("content") or {}, url_map,
                                         amap, {}),
                "parent_id": smap.get(st.get("parent_id")) or 0}
        for k in ("is_startpage", "tag_list", "meta_data", "position",
                  "uuid", "group_id", "sort_by_slug"):
            if st.get(k) is not None:
                body[k] = st[k]
        payload = {"story": body}
        if st.get("published"):
            payload["publish"] = 1
        r = call("POST", f"{api}/stories", token, body=payload)
        if r.status_code not in OK_STATUS:
            return st, None, f"{r.status_code} {r.text[:160]}"
        return st, (r.json() or {}).get("story", {}), None

    with ThreadPoolExecutor(max_workers=min(args.workers, 4)) as pool:
        futures = [pool.submit(one_story, s) for s in leaves]
        for fut in as_completed(futures):
            st, new, err = fut.result()
            with lock:
                made += 1
                if err:
                    errors.append(f"story {st.get('id')} "
                                  f"{st.get('full_slug')}: {err}")
                else:
                    id_map[st["id"]] = new.get("id")
                    if st.get("uuid") and new.get("uuid"):
                        uuid_map[st["uuid"]] = new["uuid"]
                if made % 100 == 0 or made == len(leaves):
                    print(f"    created {made}/{len(leaves)}  "
                          f"ok {len(id_map)}", flush=True)
    maps["story_id"] = id_map
    maps["story_uuid"] = uuid_map
    maps["story_folder_id"] = smap

    # ---- 9. repair internal links whose target uuid changed
    #
    # Story A can link to story B that did not exist yet when A was created, so
    # pass 8 sent every internal link unremapped and this pass fixes them.
    #
    # The comparison is against the content as pass 8 actually sent it, not
    # against the backup: asset urls were already rewritten on create, so
    # diffing the backup would flag every story holding any image and re-PUT the
    # lot. On a space with thousands of stories that is thousands of pointless
    # writes. Diffing against what was sent isolates the uuid change alone.
    changed = {o: n for o, n in uuid_map.items() if o != n}
    print(f"  internal links: {len(changed)} story uuid(s) changed")
    relinked = 0
    if changed:
        for st in leaves:
            new_id = id_map.get(st["id"])
            if not new_id:
                continue
            original = st.get("content") or {}
            as_created = remap_content(original, url_map, amap, {})
            after = remap_content(original, url_map, amap, changed)
            if canonical(as_created) == canonical(after):
                continue
            r = call("PUT", f"{api}/stories/{new_id}", token,
                     body={"story": {"content": after}, "force_update": "1",
                           **({"publish": 1} if st.get("published") else {})})
            if r.status_code in OK_STATUS:
                relinked += 1
            else:
                errors.append(f"relink {new_id}: {r.status_code}")
        print(f"    rewrote {relinked} story(ies)")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    repo, _ = repo_paths(site)
    mpath = os.path.join(repo, "restore_maps", f"rebuild-{target}-{stamp}.json")
    maps["errors"] = errors
    write_json(mpath, maps)

    print(f"\n  rebuilt into space {target}")
    print(f"    components {len(cmap)}   assets {len(amap)}   "
          f"folders {len([v for v in smap.values() if v])}   "
          f"stories {len(id_map)}   relinked {relinked}")
    print(f"    id maps -> {mpath}")
    if errors:
        print(f"\n  {len(errors)} problem(s):")
        for e in errors[:25]:
            print(f"      {e}")
        if len(errors) > 25:
            print(f"      ... and {len(errors) - 25} more (see the map file)")
    return 1 if errors else 0


# --------------------------------------------------------------------------
# assets — put a deleted file back and repoint the stories that used it
# --------------------------------------------------------------------------

def restore_assets(site, snap, args):
    """Re-upload assets that have gone from the space, then fix the references.

    The case this exists for: someone deletes an image in Storyblok. The bytes are
    still in the bucket, but the asset row is gone and every story that used it
    renders a broken image. Putting the file back gives it a NEW id and a NEW url,
    so re-uploading alone fixes nothing -- the stories still point at the old one.

    So this does both halves:

        bucket -> Storyblok        upload, into the same asset folder
        old url -> new url         rewrite every story that referenced it

    The rewrite reads each story LIVE and changes only the asset reference, rather
    than writing the backed-up copy over it. Anything edited since the backup is
    left alone, which is the same promise in-place makes: never clobber work you
    were not asked to touch.
    """
    api, token = space_api(site), token_for(site)
    src_space = str(site["space_id"])

    backup_assets = snap.read("assets.json", []) or []
    live, err = fetch_list(api, "assets", "assets", True, token)
    if err:
        sys.exit(f"  !! cannot list live assets: {err}")
    live_ids = {a["id"] for a in live if a.get("id") is not None}

    if args.asset:
        wanted = [a for a in backup_assets if a.get("id") in set(args.asset)]
        unknown = set(args.asset) - {a.get("id") for a in wanted}
        if unknown:
            sys.exit(f"  !! not in this backup: {sorted(unknown)}")
    else:
        wanted = [a for a in backup_assets if a.get("id") not in live_ids]

    print(f"\n  asset restore - {site['name']} space {src_space}")
    print(f"  media from {snap.store.label}")
    print(f"  backup holds {len(backup_assets)}, space has {len(live)}")

    if not wanted:
        print("\n  nothing to restore - every backed-up asset is still in the "
              "space")
        return 0

    # Which stories referenced each one. Scanned from the backup, because the
    # live story may already have had the reference stripped by an editor.
    refs = _reference_map(snap, src_space, {a["id"] for a in wanted})

    folders = snap.read("asset_folders.json", []) or []
    fmap = {f["id"]: f.get("name") for f in folders}

    ready, no_bytes = [], []
    for a in wanted:
        (ready if snap.has_asset(a, src_space) else no_bytes).append(a)

    already = [a for a in wanted if a.get("id") in live_ids]
    print(f"\n  {len(wanted)} asset(s) to restore"
          + (f", {len(already)} of which are still present (forced by --asset)"
             if already else ""))
    for a in wanted[:30]:
        aid = a["id"]
        n = len(refs.get(aid, []))
        state = "in bucket" if snap.has_asset(a, src_space) else "NO BYTES"
        print(f"    {aid:<18} {os.path.basename(a.get('filename') or ''):<44} "
              f"{state:<10} used by {n} story(ies)"
              f"  folder={fmap.get(a.get('asset_folder_id')) or '(root)'}")
    if len(wanted) > 30:
        print(f"    ... and {len(wanted) - 30} more")

    if no_bytes:
        print(f"\n  !! {len(no_bytes)} have no bytes in storage and cannot be "
              f"restored: {[a['id'] for a in no_bytes][:10]}")

    total_refs = sum(len(refs.get(a['id'], [])) for a in ready)
    print(f"\n  would upload {len(ready)} file(s) and rewrite {total_refs} "
          f"story reference(s)")
    if not args.apply:
        print("  DRY RUN - nothing written. Add --apply.")
        return 0

    url_map, id_map, errors = {}, {}, []
    print(f"\n  uploading {len(ready)}")
    for i, a in enumerate(ready, 1):
        path = snap.asset_file(a, src_space)
        if not path:
            errors.append(f"asset {a['id']}: bytes vanished between check and "
                          f"upload")
            continue
        try:
            new, err = upload_asset(api, token, path, a,
                                    a.get("asset_folder_id"))
        finally:
            snap.release(path)
        if err:
            errors.append(f"asset {a['id']}: {err}")
            continue
        id_map[a["id"]] = new.get("id")
        if a.get("filename") and new.get("filename"):
            url_map[a["filename"]] = new["filename"]
        print(f"    {i}/{len(ready)}  {a['id']} -> {new.get('id')}", flush=True)

    # ---- repoint the stories, reading each one live
    touched = set()
    for aid in id_map:
        touched.update(refs.get(aid, []))
    print(f"\n  rewriting {len(touched)} story(ies)")
    fixed, skipped = 0, 0
    for sid in sorted(touched):
        r = get(f"{api}/stories/{sid}", token)
        if r.status_code != 200:
            errors.append(f"story {sid}: {r.status_code} reading it back")
            continue
        story = r.json().get("story") or {}
        before = story.get("content") or {}
        after = remap_content(before, url_map, id_map, {})
        if canonical(before) == canonical(after):
            skipped += 1
            continue
        body = {"story": {"content": after}, "force_update": "1"}
        if story.get("published") and not story.get("unpublished_changes"):
            # Only republish something that was already live and clean. A story
            # holding unpublished edits must not be pushed live as a side effect
            # of fixing an image.
            body["publish"] = 1
        rr = call("PUT", f"{api}/stories/{sid}", token, body=body)
        if rr.status_code in OK_STATUS:
            fixed += 1
        else:
            errors.append(f"story {sid}: {rr.status_code} {rr.text[:120]}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    repo, _ = repo_paths(site)
    mpath = os.path.join(repo, "restore_maps", f"assets-{stamp}.json")
    write_json(mpath, {"space": src_space, "asset_id": id_map,
                       "asset_url": url_map, "stories_rewritten": fixed,
                       "errors": errors})

    print(f"\n  uploaded {len(id_map)}   stories rewritten {fixed}"
          f"   already correct {skipped}   problems {len(errors)}")
    print(f"    map -> {mpath}")
    for e in errors[:20]:
        print(f"      {e}")
    return 1 if errors else 0


def _reference_map(snap, space_id, asset_ids):
    """{asset id: [story id, ...]} by scanning the backed-up story content.

    Keyed on the path after /f/<space>/ rather than the whole url: assets.json
    returns the S3 host and story content the CDN host, so a whole-url match finds
    almost nothing.
    """
    by_key = {}
    for a in snap.read("assets.json", []) or []:
        if a.get("id") in asset_ids:
            k = asset_url_key(a.get("filename"))
            if k:
                by_key[k] = a["id"]
    out = {}
    for sid in snap.story_ids():
        st = snap.story(sid)
        blob = canonical(st.get("content") if st else None)
        if "/f/" not in blob:
            continue
        for url in set(ASSET_URL_RE.findall(blob)):
            aid = by_key.get(asset_url_key(url))
            if aid is not None:
                out.setdefault(aid, []).append(sid)
    return out


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Restore a Storyblok backup taken by sb_backup.py.")
    ap.add_argument("--site", required=True, help="AKUH | AKU | AKUEB")
    ap.add_argument("--config", help="path to sites.json (also SB_SITES)")
    ap.add_argument("--mode", required=True,
                    choices=["in-place", "rebuild", "assets"])
    ap.add_argument("--apply", action="store_true",
                    help="actually write. Without this, it is a dry run.")
    ap.add_argument("--story", type=int, action="append",
                    help="in-place: restore one story id (repeatable)")
    ap.add_argument("--all", action="store_true",
                    help="in-place: every story in the snapshot")
    ap.add_argument("--with-structure", action="store_true",
                    help="in-place: also restore slug, parent and position")
    ap.add_argument("--no-publish", action="store_true",
                    help="in-place: write drafts only, never publish")
    ap.add_argument("--from-rev",
                    help="in-place: read the snapshot at this git revision "
                         "(e.g. HEAD~3) instead of the working tree")
    ap.add_argument("--into",
                    help="rebuild: the target space id (must be empty)")
    ap.add_argument("--into-token",
                    help="rebuild: token for the target space, if it differs "
                         "(also SB_TOKEN_TARGET)")
    ap.add_argument("--asset", type=int, action="append",
                    help="assets mode: restore this asset id even if it is "
                         "still present (repeatable). Default is every asset in "
                         "the backup that is missing from the space.")
    ap.add_argument("--assets-dir",
                    help="where the binaries are kept, if outside the repo "
                         "(bucket mount, share). Overrides assets_dir in "
                         "sites.json. Needed by rebuild; in-place ignores it.")
    ap.add_argument("--force", action="store_true",
                    help="override the safety checks. Read what they said "
                         "first.")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    sites = pick_sites(load_sites(args.config), args.site)
    if len(sites) != 1:
        sys.exit("--site takes exactly one site for a restore")
    site = sites[0]

    if not token_for(site):
        sys.exit(f"  no management token for {site['name']}")

    repo, outdir = repo_paths(site)
    if not os.path.isdir(outdir):
        sys.exit(f"  no snapshot at {outdir} - run sb_backup.py first")
    store, external = make_backend(site, outdir, args.assets_dir)
    snap = Snapshot(repo, outdir, args.from_rev, store)
    if external:
        print(f"  media from {store.label}")
        root = getattr(store, "root", None)
        if root and not os.path.isdir(root):
            # Only fatal for a rebuild, which uploads them. in-place never
            # touches assets, so a missing bucket must not block a content fix.
            msg = (f"  !! the media directory does not exist: {root}\n"
                   f"     mount the bucket or share, or pass --assets-dir.")
            if args.mode == "rebuild":
                sys.exit(msg)
            print(msg.replace("!!", "--") + "\n     (in-place does not need it)")

    if args.mode == "in-place":
        return restore_in_place(site, snap, args)

    if args.mode == "assets":
        return restore_assets(site, snap, args)

    if not args.into:
        sys.exit("--mode rebuild needs --into <target space id>")
    if args.from_rev:
        sys.exit("--from-rev works with --mode in-place only: under LFS, "
                 "`git show` returns the pointer text rather than the file, so "
                 "a rebuild would upload 130-byte stubs.\n"
                 "Check the commit out into a working tree and rebuild from "
                 "there.")
    return restore_rebuild(site, snap, args)


if __name__ == "__main__":
    sys.exit(main())
