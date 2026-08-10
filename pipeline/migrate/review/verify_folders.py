#!/usr/bin/env python3
"""
verify_folders.py — is every folder the migration needs actually in Storyblok?

Read-only. GET requests only; this never creates, moves or deletes anything.

The upload computes each story's parent from folders.json. A folder that is
missing, or whose slug differs by one character, means the upload either fails or
silently creates a duplicate alongside the dev's. So this compares the 346
folders we expect against what the space really contains, and reports:

    MISSING     we need it, the space has no such folder -> stories cannot land
    EXTRA       the space has a folder inside our subtree that we never asked for
    CASE/NAME   right slug, different display name

The dev may have created the tree under a parent rather than at the space root
(e.g. everything inside `news/`). Pass --prefix, or let it auto-detect by looking
for where our root slugs appear.

Usage:
    python scripts/migrate/review/verify_folders.py
    python scripts/migrate/review/verify_folders.py --prefix news
    python scripts/migrate/review/verify_folders.py --csv out.csv
"""

import argparse
import csv
import json
import os
import sys

try:
    import requests
except ImportError:
    sys.exit("pip install -r requirements.txt")

# Walk up to the pipeline/ root rather than counting dirname() calls: the
# scripts using this sit at two different depths (migrate/ and
# migrate/review/), and a fixed count is right for one and wrong for the
# other -- which is exactly how this broke.
# Two things have to be importable: this flow's own helpers (migrate/paths.py,
# migrate/db.py) and the shared pipeline modules. The scripts using this sit at
# two different depths -- migrate/ and migrate/review/ -- so the pipeline root is
# found by walking up for _bootstrap.py rather than by counting dirname() calls,
# which is right for one depth and silently wrong for the other.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_d = os.path.dirname(os.path.abspath(__file__))
while _d != os.path.dirname(_d):
    if os.path.exists(os.path.join(_d, "_bootstrap.py")):
        sys.path.insert(0, _d)
        break
    _d = os.path.dirname(_d)
import _bootstrap  # noqa: F401,E402
from paths import BASE  # noqa: E402

from storyblok_config import load_config, management_api_base  # noqa: E402

# Paths come from the shared module so this script works for any content
# type; see pipeline/paths_root.py.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from paths_root import P  # noqa: E402

SEED = os.path.join(P.TAXONOMY, "seed", "folders.json")
OUT = os.path.join(P.MIGRATE, "folder_verification.csv")

# The two roots our tree starts from. Used to auto-detect the dev's prefix.
ROOTS = ("global", "regions")


def all_folders(cfg):
    """Every folder in the space, paged. Folders only — stories are ignored."""
    api = f"{management_api_base(cfg)}/spaces/{cfg['space_id']}"
    s = requests.Session()
    s.headers.update({"Authorization": cfg["management_token"]})
    out, page = [], 1
    while True:
        r = s.get(f"{api}/stories",
                  params={"per_page": 100, "page": page, "folder_only": 1},
                  timeout=120)
        if r.status_code != 200:
            sys.exit(f"list failed: {r.status_code} {r.text[:300]}")
        chunk = r.json().get("stories") or []
        out.extend(chunk)
        total = int(r.headers.get("Total", len(out)))
        print(f"    fetched {len(out)}/{total} folders", end="\r", flush=True)
        if len(out) >= total or not chunk:
            break
        page += 1
    print(" " * 60, end="\r")
    return [f for f in out if f.get("is_folder")]


def detect_prefix(live_slugs):
    """Where did the dev put our tree? '' means at the space root."""
    for root in ROOTS:
        if root in live_slugs:
            return ""
    # look for any folder whose path ENDS at one of our roots
    for slug in sorted(live_slugs, key=len):
        for root in ROOTS:
            if slug.endswith("/" + root):
                return slug[: -len(root) - 1]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", help="parent path the tree lives under")
    ap.add_argument("--csv", nargs="?", const=OUT,
                    help="write the differences to a CSV")
    a = ap.parse_args()

    with open(SEED, encoding="utf-8") as f:
        seed = json.load(f)
    expected = {f["full_slug"]: f for f in seed["folders"]}
    print(f"  expecting {len(expected)} folders from folders.json")

    cfg = load_config()
    print(f"  reading space {cfg['space_id']} (read-only)...")
    live = all_folders(cfg)
    live_by_slug = {f["full_slug"]: f for f in live}
    print(f"  space contains {len(live)} folders\n")

    prefix = a.prefix if a.prefix is not None else detect_prefix(live_by_slug)
    if prefix is None:
        print("  Could not find our root folders ('global', 'regions') anywhere")
        print("  in the space. Either the tree has not been created yet, or it")
        print("  sits under a parent whose name differs. Folders at the root:")
        for s in sorted(x for x in live_by_slug if "/" not in x)[:25]:
            print(f"      {s}")
        return 1
    prefix = prefix.strip("/")
    print(f"  tree prefix: {prefix + '/' if prefix else '(space root)'}")

    def full(slug):
        return f"{prefix}/{slug}" if prefix else slug

    # ------------------------------------------------------------- compare
    rows = []
    missing, present, renamed = [], [], []
    for slug, f in sorted(expected.items()):
        target = full(slug)
        got = live_by_slug.get(target)
        if got is None:
            missing.append((slug, f))
            rows.append({"status": "MISSING", "level": f["level"],
                         "expected_full_slug": target, "name": f["name"],
                         "live_name": "", "sb_id": ""})
        else:
            present.append(slug)
            if (got.get("name") or "").strip() != (f["name"] or "").strip():
                renamed.append((target, f["name"], got.get("name")))
                rows.append({"status": "NAME", "level": f["level"],
                             "expected_full_slug": target, "name": f["name"],
                             "live_name": got.get("name"), "sb_id": got["id"]})

    # extras: live folders inside our subtree that we never asked for
    ours = {full(s) for s in expected}
    scope = tuple(full(r) for r in ROOTS)
    extra = sorted(s for s in live_by_slug
                   if s not in ours
                   and (s.startswith(scope)
                        or any(s.startswith(x + "/") for x in scope)))
    for s in extra:
        rows.append({"status": "EXTRA", "level": "", "expected_full_slug": s,
                     "name": "", "live_name": live_by_slug[s].get("name"),
                     "sb_id": live_by_slug[s]["id"]})

    # ------------------------------------------------------------- report
    print(f"\n{'=' * 74}")
    print(f"  PRESENT  {len(present)} / {len(expected)}")
    print(f"  MISSING  {len(missing)}")
    print(f"  EXTRA    {len(extra)}   (inside our subtree, not in our tree)")
    print(f"  NAME     {len(renamed)}  (right slug, different display name)")
    print("=" * 74)

    if missing:
        by_level = {}
        for slug, f in missing:
            by_level.setdefault(f["level"], []).append((slug, f))
        print(f"\n  MISSING, by level — stories routed here cannot be created:")
        for lvl in ("root", "region", "entities-root", "entity",
                    "departments-root", "department", "news"):
            sel = by_level.get(lvl) or []
            if not sel:
                continue
            print(f"\n    {lvl}  ({len(sel)})")
            for slug, f in sel[:20]:
                print(f"      {full(slug)}")
                print(f"          expected name: {f['name']}"
                      f"   stories: {f.get('expected_news_count', 0)}")
            if len(sel) > 20:
                print(f"      ... and {len(sel) - 20} more")

    if renamed:
        print(f"\n  NAME differences — slug matches so the upload still works,")
        print(f"  but the label a reader sees is not what we recorded:")
        for target, ours_name, theirs in renamed[:25]:
            print(f"    {target}")
            print(f"        ours   {ours_name!r}")
            print(f"        live   {theirs!r}")

    if extra:
        print(f"\n  EXTRA — in the space but not in our tree. Harmless unless a")
        print(f"  story was meant to go here:")
        for s in extra[:25]:
            print(f"    {s}")
        if len(extra) > 25:
            print(f"    ... and {len(extra) - 25} more")

    # how many stories are blocked by the missing folders
    if missing:
        blocked = sum(f.get("expected_news_count", 0) for _, f in missing)
        print(f"\n  {blocked} stories are routed into a folder that does not exist.")

    if a.csv and rows:
        os.makedirs(os.path.dirname(os.path.abspath(a.csv)), exist_ok=True)
        with open(a.csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, lineterminator="\n",
                               fieldnames=["status", "level",
                                           "expected_full_slug", "name",
                                           "live_name", "sb_id"])
            w.writeheader()
            w.writerows(rows)
        print(f"\n  -> {a.csv}  ({len(rows)} rows)")

    ok = not missing
    print(f"\n  VERDICT: {'ALL FOLDERS PRESENT' if ok else 'FOLDERS MISSING'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
