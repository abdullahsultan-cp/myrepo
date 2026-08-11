#!/usr/bin/env python3
"""upload.py — put blogs into Storyblok. Assets first, then the stories.

    python Blogs-Pipeline/pipeline/upload.py --demo            # dry run
    python Blogs-Pipeline/pipeline/upload.py --demo --apply    # writes
    python Blogs-Pipeline/pipeline/upload.py --only 15,18 --apply
    python Blogs-Pipeline/pipeline/upload.py --all --apply

**Nothing is written without `--apply`.** The dry run says exactly which
assets would upload, which folder each story lands in, and whether it would be
created or updated.

## The rules it will not break

**A content folder is never created.** `regions/` and `global/` belong to the
front-end developer. A story whose destination folder is missing is reported and
skipped — it is not filed somewhere convenient instead. Asset folders are a
different namespace and *are* created.

**A story is never deleted and re-made.** If a blog is already there, its id is
kept and its content updated. A new id would break every review link already
shared and lose whatever an editor has changed by hand.

**An asset is uploaded once.** `data/asset_map.json` remembers what went up, so
a second run relinks rather than duplicating. Interrupting a run is safe.

## Three kinds of image

    banner_image    70 blogs, `{id}-Banner.jpg` on disk
    author photo    inside author_section, 49 files
    inline images   31, INSIDE the rich text, still pointing at
                    /blogs/PublishingImages/... — rewritten to the asset URL

The inline ones are the easy thing to forget: they are not a field, they are
`src` attributes buried in the rich-text tree, and a story uploads perfectly
well with all of them still pointing at a SharePoint path that is about to stop
resolving.

## The demo set

`--demo` is eight blogs chosen to break different things, not to look good:

    15  the ordinary case — banner, bio, photo, category, entity-placed
    18  no banner, an inline image, a YouTube video AND a Facebook post
    26  entity-placed under IED
    31  an empty table, and 18 blank paragraphs
    45  a pull quote, four dead SharePoint links, shared to qtl
    70  h1 section headings, 20 blank paragraphs, no banner
    84  global and shared to cime
    97  an article that is one giant paragraph with 18 line breaks
"""

import argparse
import copy
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT_DIR, "pipeline"))
import _bootstrap

_bootstrap.ensure()

sys.path.insert(0, os.path.join(ROOT_DIR, "pipeline", "migrate", "upload"))

# The news uploader's client and asset helper, reused rather than rewritten:
# one retry policy, one throttle, one S3 backoff to fix if any of them is wrong.
from upload import SB, ensure_asset_folder, upload_asset

from paths_root import ROOT, P
from storyblok_config import load_config

P.use("blogs")

DEMO = ["15", "18", "26", "31", "45", "70", "84", "97"]
ASSET_FOLDER = "Blogs"


def load_map():
    path = os.path.join(P.DATA, "asset_map.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_map(table):
    path = os.path.join(P.DATA, "asset_map.json")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(table, f, ensure_ascii=False, indent=2, sort_keys=True)


def folder_ids():
    """{full_slug: id} for every folder in the space."""
    with open(P.SPACE_TREE, encoding="utf-8") as f:
        tree = json.load(f)
    folders = tree["folders"] if isinstance(tree, dict) else tree
    return {f["full_slug"].strip("/"): f["id"] for f in folders}


def collect_inline(node, found):
    """Every image src inside a rich-text tree, with the node holding it."""
    if isinstance(node, dict):
        if node.get("type") == "image":
            attrs = node.get("attrs") or {}
            if attrs.get("src"):
                found.append(node)
        for value in node.values():
            if isinstance(value, (list, dict)):
                collect_inline(value, found)
    elif isinstance(node, list):
        for child in node:
            collect_inline(child, found)


def local_name(src):
    return re.sub(r'[<>:"/\\|?*]', "_",
                  os.path.basename(src.split("?")[0])) or ""


def need_assets(payload):
    """Every local file this payload refers to, by its name on disk."""
    wanted = []
    banner = (payload["content"]["banner_image"] or {}).get("_local")
    if banner:
        wanted.append(banner)
    for blok in payload["content"]["body"]:
        if blok.get("component") == "author_section":
            photo = (blok.get("photo") or {}).get("_local")
            if photo:
                wanted.append(photo)
        if blok.get("component") == "rich_text":
            found = []
            collect_inline(blok.get("content"), found)
            for node in found:
                name = local_name((node.get("attrs") or {}).get("src") or "")
                if name:
                    wanted.append(name)
    return wanted


def attach(payload, table):
    """Replace every `_local` marker and inline src with the uploaded asset."""
    content = payload["content"]
    banner = (content["banner_image"] or {}).get("_local")
    if banner and banner in table:
        content["banner_image"] = copy.deepcopy(table[banner])
    elif banner:
        content["banner_image"] = {"fieldtype": "asset"}
    for blok in content["body"]:
        if blok.get("component") == "author_section":
            photo = (blok.get("photo") or {}).get("_local")
            blok["photo"] = (copy.deepcopy(table[photo]) if photo in table
                             else {"fieldtype": "asset"})
        if blok.get("component") == "rich_text":
            found = []
            collect_inline(blok.get("content"), found)
            for node in found:
                attrs = node.get("attrs") or {}
                name = local_name(attrs.get("src") or "")
                if name in table:
                    attrs["src"] = table[name]["filename"]
                    node["attrs"] = attrs
    return payload


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--demo", action="store_true", help="the eight below")
    ap.add_argument("--only", help="comma-separated blog ids")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    if a.demo:
        wanted = set(DEMO)
    elif a.only:
        wanted = {x.strip() for x in a.only.split(",") if x.strip()}
    elif a.all:
        wanted = None
    else:
        sys.exit("  pick --demo, --only or --all")

    payload_dir = os.path.join(P.DATA, "payloads")
    if not os.path.isdir(payload_dir):
        sys.exit("  no payloads — run Blogs-Pipeline/pipeline/build_payload.py")

    import csv
    routing = {}
    with open(os.path.join(P.DATA, "taxonomy", "routing.csv"),
              encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            routing[str(row["id"])] = row

    payloads = {}
    for name in sorted(os.listdir(payload_dir)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(payload_dir, name), encoding="utf-8") as f:
            story = json.load(f)["story"]
        sid = str(story["content"].get("sharepoint_id") or name[:-5])
        if wanted is None or sid in wanted:
            payloads[sid] = story

    missing = (wanted or set()) - set(payloads)
    if missing:
        print(f"  no payload for {sorted(missing)}")
    print(f"  {len(payloads)} blog(s) selected"
          + ("  [DRY RUN]" if not a.apply else "  [WRITING]"))

    folders = folder_ids()
    table = load_map()
    media = P.MEDIA_DIR

    # ---- what has to go up, and what is missing from disk ----------------
    needed, absent = [], []
    for sid, story in payloads.items():
        for name in need_assets(story):
            if name in table:
                continue
            if os.path.exists(os.path.join(media, name)):
                if name not in needed:
                    needed.append(name)
            else:
                absent.append((sid, name))
    line = (f"  assets: {len(table)} already uploaded, "
            f"{len(needed)} to upload")
    if absent:
        line += f", {len(absent)} referenced but NOT ON DISK"
    print(line)
    for sid, name in absent[:8]:
        print(f"    blog {sid:<5}missing file {name[:56]}")

    # ---- destinations, before anything is written ------------------------
    plan = []
    for sid, story in sorted(payloads.items(), key=lambda kv: int(kv[0])):
        route = routing.get(sid, {})
        target = (route.get("target_full_slug") or "").strip("/")
        parent = folders.get(target)
        plan.append((sid, story, target, parent))
        state = f"folder id {parent}" if parent else "FOLDER MISSING — skipped"
        print(f"    blog {sid:<5}{target:<44}{state}")
    if any(p is None for _, _, _, p in plan):
        print("  a missing folder is never created here — ask the dev for it")

    if not a.apply:
        print("\n  nothing written. Re-run with --apply when this looks right.")
        return 0

    cfg = load_config()
    sb = SB(cfg)
    folder_cache = {}
    asset_folder = ensure_asset_folder(sb, ASSET_FOLDER, folder_cache)

    for i, name in enumerate(needed, 1):
        obj, err = upload_asset(sb, os.path.join(media, name), name,
                                asset_folder)
        if err:
            print(f"    {i}/{len(needed)} FAILED {name[:44]}: {err[:60]}")
            continue
        table[name] = obj
        save_map(table)
        print(f"    {i}/{len(needed)} {name[:52]}")

    created = updated = skipped = failed = 0
    report = []
    for sid, story, target, parent in plan:
        if parent is None:
            skipped += 1
            continue
        ready = attach(copy.deepcopy(story), table)
        slug = ready.get("slug") or ready["content"]["title"]
        body = {"story": {"name": ready["content"]["title"][:255],
                          "slug": slug,
                          "parent_id": parent,
                          "content": ready["content"]},
                "publish": 1}
        found = sb.get("stories", params={"with_slug": f"{target}/{slug}"})
        existing = (found.json().get("stories") or []) if found is not None \
            and found.status_code == 200 else []
        if existing:
            sb_id = existing[0]["id"]
            r = sb.put(f"stories/{sb_id}", body)
            action = "updated"
        else:
            r = sb.post("stories", body)
            action = "created"
        ok = r is not None and r.status_code in (200, 201)
        if ok:
            sb_id = r.json()["story"]["id"]
            created += action == "created"
            updated += action == "updated"
        else:
            failed += 1
            sb_id = None
        report.append({"blog": sid, "action": action if ok else "failed",
                       "slug": f"{target}/{slug}", "storyblok_id": sb_id,
                       "status": getattr(r, "status_code", None)})
        print(f"    blog {sid:<5}{action if ok else 'FAILED':<9}"
              f"{target}/{slug}"[:66])

    out = os.path.join(P.DATA, "upload_report.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"created": created, "updated": updated, "skipped": skipped,
                   "failed": failed, "rows": report}, f,
                  ensure_ascii=False, indent=2)
    print(f"\n  created {created}, updated {updated}, "
          f"skipped {skipped}, failed {failed}")
    print(f"  -> {os.path.relpath(out, ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
