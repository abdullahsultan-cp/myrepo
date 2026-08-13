#!/usr/bin/env python3
"""
sb.py — the one command for a Storyblok backup repo. Run from the repo root.

    python tools/sb.py setup        write tools/sites.json, prefilled from the
                                    snapshot; you paste two secrets
    python tools/sb.py setup --name AKUEB --space 123    ...for a fresh repo
    python tools/sb.py init <other repo path> --name AKU --space 456
                                    stand up ANOTHER backup repo from this one:
                                    tools, wrappers, config, gitignore
    python tools/sb.py doctor       is everything in place to run?
    python tools/sb.py backup       THE ONE CLICK: schema, stories, published
                                    versions, assets to the bucket, manifests,
                                    portal, index, commit
    python tools/sb.py backup --push          ...and push
    python tools/sb.py audit        prove the backup covers the whole space
    python tools/sb.py audit --deep      ...re-reading every byte (costs egress)
    python tools/sb.py verify       checksums only
    python tools/sb.py repair       re-fetch anything missing or corrupted
    python tools/sb.py index        rebuild index.sqlite
    python tools/sb.py orphans      bucket files no longer in the space, and
                                    what they cost to keep
    python tools/sb.py changed [rev]     what moved, appeared, vanished or was
                                    edited since a commit (default HEAD~1).
                                    For a space being reorganised.
    python tools/sb.py restore-story <id> [--apply]
    python tools/sb.py restore-assets [--apply]
    python tools/sb.py rebuild <empty space id> [--apply]

This repo is self-contained: tools/ holds the whole pipeline, so a backup can be
taken or restored with nothing but this checkout and Python. Nothing here needs
the project the scripts were authored in.

Which site and space this is comes from storyblok/_summary.json, so no command
needs --site. Credentials come from tools/sites.json, or from the environment
(SB_TOKEN / SB_TOKEN_<SITE> and AZURE_STORAGE_CONNECTION_STRING) which is what a
scheduled job should use.
"""

import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SNAP = os.path.join(REPO, "storyblok")
CONFIG = os.path.join(HERE, "sites.json")
PY = sys.executable

DEPS = ["requests>=2.31", "azure-storage-blob>=12.19"]


def _summary():
    p = os.path.join(SNAP, "_summary.json")
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _site_from_snapshot():
    """Name, space id and region for this repo.

    From the snapshot when there is one, else from tools/sites.json, else guessed
    from the directory name. A fresh repo has no snapshot yet -- that is the
    normal state before the first backup, not an error -- and reading only the
    snapshot made it report the space as "?" while holding the answer in its own
    config.
    """
    s = _summary()
    out = {"name": s.get("site") or "",
           "space_id": str(s.get("space_id") or ""),
           "region": s.get("region") or ""}
    if not (out["name"] and out["space_id"]) and os.path.exists(CONFIG):
        try:
            with open(CONFIG, encoding="utf-8") as f:
                first = (json.load(f).get("sites") or [{}])[0]
            out["name"] = out["name"] or first.get("name") or ""
            sid = str(first.get("space_id") or "")
            if "PUT_" not in sid:
                out["space_id"] = out["space_id"] or sid
            out["region"] = out["region"] or first.get("region") or ""
        except (ValueError, OSError):
            pass
    out["name"] = out["name"] or os.path.basename(REPO).split("-")[0].upper()
    out["region"] = out["region"] or "eu"
    return out


def has_snapshot():
    return os.path.isdir(os.path.join(SNAP, "stories"))


def _env_token(name):
    key = "SB_TOKEN_" + re.sub(r"[^A-Z0-9]", "_", name.upper())
    return os.environ.get(key) or os.environ.get("SB_TOKEN")


def effective_config():
    """The config to run with: the file if present, else built from the
    environment. Returns (path, dict) — path is None when nothing usable exists."""
    if os.path.exists(CONFIG):
        with open(CONFIG, encoding="utf-8") as f:
            return CONFIG, json.load(f)

    site = _site_from_snapshot()
    token = _env_token(site["name"])
    conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if not token:
        return None, None
    site["management_token"] = token
    site["repo"] = REPO
    if conn:
        site["assets"] = {
            "backend": "azure", "connection_string": conn,
            "container": os.environ.get("SB_CONTAINER", "storyblok-backup"),
            "prefix": os.environ.get("SB_PREFIX", site["name"]),
            "tier": os.environ.get("SB_TIER", "Cool")}
    # Written beside the scripts and gitignored, because the child scripts take a
    # path rather than a dict.
    tmp = os.path.join(HERE, ".sites.env.json")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"sites": [site]}, f, indent=2)
    return tmp, {"sites": [site]}


def _run(script, *args):
    cfg, _ = effective_config()
    if not cfg:
        return _no_config()
    site = _site_from_snapshot()["name"]
    # -u because these runs take minutes to hours and the only sign of progress
    # is what they print. Without it Python buffers the child's output whenever
    # stdout is not a terminal, so `sb.py backup > log` shows nothing at all
    # until the run finishes -- which looks exactly like a hang.
    cmd = [PY, "-u", os.path.join(HERE, script), "--config", cfg,
           "--site", site, *args]
    return subprocess.call(cmd)


def _no_config():
    site = _site_from_snapshot()
    print(f"""
  No credentials.

  Either run:      python tools/sb.py setup
  or set:          SB_TOKEN_{re.sub(r'[^A-Z0-9]', '_', site['name'].upper())}   (a Storyblok personal access token)
                   AZURE_STORAGE_CONNECTION_STRING                (where the media lives)

  The environment form is what a scheduled job should use, so no secret is ever
  written to disk.
""".rstrip())
    return 2


# --------------------------------------------------------------------------

def cmd_init(argv):
    """Seed another backup repo from this one: tools, wrappers, config skeleton.

    Without this a fresh repo cannot bootstrap, because tools/ only arrives when
    a backup runs — so the first backup of a new space would need the project
    these scripts were authored in. Any set-up repo can now stand up the next
    one, which is what makes the three of them independent of anything else.
    """
    if not argv:
        print("  usage: python tools/sb.py init <path to the other repo> "
              "[--name AKUEB] [--space 123]")
        return 2
    target = os.path.abspath(os.path.expanduser(argv[0]))
    opts = dict(zip(argv[1::2], argv[2::2]))
    name = opts.get("--name") or os.path.basename(target).split("-")[0].upper()
    space = opts.get("--space", "")
    region = opts.get("--region", "eu")

    tdir = os.path.join(target, "tools")
    os.makedirs(tdir, exist_ok=True)
    import shutil
    copied = 0
    for fn in sorted(os.listdir(HERE)):
        if fn.endswith(".py") or fn == "requirements.txt":
            shutil.copy2(os.path.join(HERE, fn), os.path.join(tdir, fn))
            copied += 1
    for fn in ("backup.cmd", "backup.sh"):
        src = os.path.join(REPO, fn)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(target, fn))
            copied += 1

    cfg = os.path.join(tdir, "sites.json")
    if not os.path.exists(cfg):
        with open(cfg, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"sites": [{
                "name": name,
                "space_id": space or "PUT_THE_SPACE_ID_HERE",
                "region": region,
                "repo": ".",
                "management_token": "PUT_A_STORYBLOK_PERSONAL_ACCESS_TOKEN_HERE",
                "assets": {"backend": "azure",
                           "container": "storyblok-backup",
                           "prefix": name, "tier": "Cool",
                           "connection_string":
                               "PUT_THE_AZURE_CONNECTION_STRING_HERE"},
            }]}, f, indent=2)
            f.write("\n")

    gi = os.path.join(target, ".gitignore")
    have = open(gi, encoding="utf-8").read() if os.path.exists(gi) else ""
    need = ["*.part", "restore_maps/", "storyblok/index.sqlite",
            "tools/sites.json", "tools/.sites.env.json"]
    missing = [n for n in need if n not in have.split()]
    if missing:
        with open(gi, "a" if have else "w", encoding="utf-8",
                  newline="\n") as f:
            f.write(("\n" if have and not have.endswith("\n") else "")
                    + "\n".join(missing) + "\n")

    print(f"""
  Seeded {target}

    {copied} file(s) copied, plus tools/sites.json and .gitignore

  There, do:

    python -m pip install -r tools/requirements.txt
    notepad tools\\sites.json        # space id + the two secrets
    python tools/sb.py doctor
    python tools/sb.py backup --push

  That repo now needs nothing but itself.
""".rstrip())
    return 0


def cmd_setup(argv):
    site = _site_from_snapshot()
    opts = dict(zip(argv[0::2], argv[1::2]))
    # A fresh repo has no snapshot to read the space from, so it can be given.
    name = opts.get("--name") or site["name"]
    space = opts.get("--space") or site["space_id"]
    region = opts.get("--region") or site["region"]
    if os.path.exists(CONFIG):
        print(f"  {CONFIG} already exists — edit it, or delete it and re-run.")
        return 1
    skeleton = {"sites": [{
        "name": name,
        "space_id": space or "PUT_THE_SPACE_ID_HERE",
        "region": region,
        "repo": ".",
        "management_token": "PUT_A_STORYBLOK_PERSONAL_ACCESS_TOKEN_HERE",
        "assets": {
            "backend": "azure",
            "container": "storyblok-backup",
            "prefix": name,
            "tier": "Cool",
            "connection_string": "PUT_THE_AZURE_CONNECTION_STRING_HERE",
        },
    }]}
    with open(CONFIG, "w", encoding="utf-8", newline="\n") as f:
        json.dump(skeleton, f, indent=2)
        f.write("\n")
    print(f"""
  Wrote {os.path.relpath(CONFIG, REPO)}

  Site, space id and region were filled in from the snapshot. Two secrets left:

    management_token   Storyblok -> My Account -> Personal access tokens.
                       A space-level token is not enough; several endpoints
                       reject it.
    connection_string  Azure -> Storage account -> Access keys.

  It is gitignored. Then:

    python -m pip install {' '.join(DEPS)}
    python tools/sb.py doctor
    python tools/sb.py backup
""".rstrip())
    return 0


def cmd_doctor(argv):
    site = _site_from_snapshot()
    print(f"\n  {site['name']}  space {site['space_id'] or '?'}  "
          f"region {site['region']}")
    ok = True

    print(f"\n  {'python':<22} {sys.version.split()[0]}")
    for dep, mod in (("requests", "requests"),
                     ("azure-storage-blob", "azure.storage.blob")):
        try:
            __import__(mod)
            print(f"  {dep:<22} installed")
        except ImportError:
            print(f"  {dep:<22} MISSING   python -m pip install {dep}")
            ok = False

    # A repo with no snapshot is not broken, it is new. Reporting NOT READY for
    # that told people their fresh repo could not take its first backup, which
    # was both wrong and discouraging.
    fresh = not has_snapshot()
    if fresh:
        print(f"\n  {'snapshot':<22} none yet - this will be the first backup")
    else:
        for name, path in (("snapshot", SNAP),
                           ("stories", os.path.join(SNAP, "stories")),
                           ("manifests", os.path.join(SNAP,
                                                     "manifest_assets.csv")),
                           ("restore docs", os.path.join(REPO, "RESTORE.md"))):
            there = os.path.exists(path)
            print(f"  {name:<22} {'present' if there else 'MISSING'}")
            ok &= there

    cfg, data = effective_config()
    if not cfg:
        print(f"  {'credentials':<22} MISSING")
        _no_config()
        return 1
    src = "tools/sites.json" if cfg == CONFIG else "the environment"
    print(f"  {'credentials':<22} from {src}")
    placeholder = "PUT_" in json.dumps(data)
    if placeholder:
        print(f"  {'':<22} !! still has PUT_..._HERE placeholders")
        ok = False

    if not placeholder:
        print()
        rc = _run("sb_backup.py", "--check")
        ok &= rc == 0
    if ok:
        print("\n  READY" + ("  -  run:  python tools/sb.py backup --push"
                             if fresh else ""))
    else:
        print("\n  NOT READY")
    print()
    return 0 if ok else 1


def cmd_backup(argv):
    return _run("sb_backup.py", *argv)


def cmd_audit(argv):
    return _run("sb_backup.py", "--audit", *argv)


def cmd_verify(argv):
    return _run("sb_backup.py", "--only", "assets", "--verify-assets",
                "--no-commit", *argv)


def cmd_repair(argv):
    return _run("sb_backup.py", "--only", "assets", "--repair", "--no-commit",
                *argv)


def cmd_index(argv):
    return subprocess.call([PY, os.path.join(HERE, "sb_indexdb.py"), SNAP])


def cmd_restore_story(argv):
    if not argv or not argv[0].isdigit():
        print("  usage: python tools/sb.py restore-story <story id> [--apply]")
        return 2
    return _run("sb_restore.py", "--mode", "in-place", "--story", argv[0],
                *argv[1:])


def cmd_restore_assets(argv):
    return _run("sb_restore.py", "--mode", "assets", *argv)


def cmd_rebuild(argv):
    if not argv or not argv[0].isdigit():
        print("  usage: python tools/sb.py rebuild <empty space id> [--apply]")
        return 2
    return _run("sb_restore.py", "--mode", "rebuild", "--into", argv[0],
                *argv[1:])


def cmd_changed(argv):
    """What moved, appeared, vanished or was edited since an earlier commit.

    Built for a space under active reorganisation: AKU is mid-development and
    whole sections -- news, events, blogs -- are being moved to their proper
    places. A move changes a story's slug and parent but not its id, so the
    backup handles it without losing history; this is how you SEE it happen.

    Diffs manifest_stories.csv between a revision and the working tree, which is
    the whole reason that file is one sorted line per story.
    """
    rev = argv[0] if argv and not argv[0].startswith("-") else "HEAD~1"
    rel = "storyblok/manifest_stories.csv"

    old = subprocess.run(["git", "-C", REPO, "show", f"{rev}:{rel}"],
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace")
    if old.returncode != 0:
        print(f"  cannot read {rel} at {rev}:\n  "
              f"{(old.stderr or '').strip()[:200]}")
        return 1

    import csv
    import io

    def rows(text):
        out = {}
        for r in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
            if r.get("id"):
                out[r["id"]] = r
        return out

    before = rows(old.stdout)
    with open(os.path.join(REPO, rel), encoding="utf-8-sig", newline="") as f:
        after = rows(f.read())

    added = [after[i] for i in after.keys() - before.keys()]
    gone = [before[i] for i in before.keys() - after.keys()]
    moved, edited, republished = [], [], []
    for i in before.keys() & after.keys():
        b, a = before[i], after[i]
        if b.get("full_slug") != a.get("full_slug"):
            moved.append((b, a))
        elif b.get("updated_at") != a.get("updated_at"):
            edited.append(a)
        if b.get("state") != a.get("state"):
            republished.append((b, a))

    print(f"\n  {rev} -> now\n")
    print(f"  moved        {len(moved):>5}")
    print(f"  added        {len(added):>5}")
    print(f"  removed      {len(gone):>5}")
    print(f"  edited       {len(edited):>5}")
    print(f"  state change {len(republished):>5}")

    if moved:
        print("\n  moved:")
        for b, a in sorted(moved, key=lambda x: x[1]["full_slug"])[:40]:
            print(f"    {b['id']:<18} {b['full_slug']}")
            print(f"    {'':<18}   -> {a['full_slug']}")
        if len(moved) > 40:
            print(f"    ... and {len(moved) - 40} more")
        print("\n  Ids are unchanged, so each of those kept its history and is "
              "still\n  restorable by id. Nothing was re-created.")
    for label, items in (("added", added), ("removed", gone)):
        if items:
            print(f"\n  {label}:")
            for r in sorted(items, key=lambda x: x.get("full_slug") or "")[:20]:
                print(f"    {r['id']:<18} {r.get('full_slug')}")
            if len(items) > 20:
                print(f"    ... and {len(items) - 20} more")
    if gone:
        print("\n  Removed stories are still in git history, and their assets "
              "are still\n  in the bucket - see `sb.py restore-assets`.")
    return 0


def cmd_orphans(argv):
    """Bucket files the space no longer has an asset row for.

    Keeping them is the point -- that is what makes a deleted asset recoverable.
    But they are also the part of the bill nobody is watching, so the size is
    worth seeing. Reports only; nothing here deletes.
    """
    sys.path.insert(0, HERE)
    from sb_backup import rel_path
    from sb_storage import make_backend

    cfg, data = effective_config()
    if not cfg:
        return _no_config()
    site = data["sites"][0]
    store, external = make_backend(site, SNAP)
    if not external:
        print("  media is inside this repo, not a bucket - nothing to report")
        return 0

    with open(os.path.join(SNAP, "assets.json"), encoding="utf-8") as f:
        assets = json.load(f)
    live = {rel_path(a, str(site["space_id"])) for a in assets}
    live.discard(None)

    print(f"\n  {store.label}\n  listing…")
    stored = store.list_all()
    orphan = {k: v for k, v in stored.items() if k not in live}
    total = sum(stored.values())
    orph_bytes = sum(orphan.values())

    def gb(n):
        return f"{n / 1e9:.2f} GB"

    print(f"\n  in the bucket        {len(stored):>7} files   {gb(total)}")
    print(f"  still in the space   {len(stored) - len(orphan):>7} files   "
          f"{gb(total - orph_bytes)}")
    print(f"  no longer in space   {len(orphan):>7} files   {gb(orph_bytes)}")
    if orphan:
        print(f"\n  Those {len(orphan)} are recoverable with "
              f"`sb.py restore-assets`, which is why they are kept.")
        print(f"  At Cool-tier rates {gb(orph_bytes)} is roughly "
              f"${orph_bytes / 1e9 * 0.01:.2f}/month.")
        for k in sorted(orphan)[:15]:
            print(f"      {k}")
        if len(orphan) > 15:
            print(f"      ... and {len(orphan) - 15} more")
    return 0


COMMANDS = {
    "init": cmd_init, "setup": cmd_setup, "doctor": cmd_doctor, "backup": cmd_backup,
    "audit": cmd_audit, "verify": cmd_verify, "repair": cmd_repair,
    "index": cmd_index, "orphans": cmd_orphans,
    "changed": cmd_changed,
    "restore-story": cmd_restore_story, "restore-assets": cmd_restore_assets,
    "rebuild": cmd_rebuild,
}


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0
    cmd = argv[0]
    if cmd not in COMMANDS:
        print(f"  unknown command {cmd!r}\n")
        print(f"  one of: {', '.join(sorted(COMMANDS))}")
        return 2
    return COMMANDS[cmd](argv[1:])


if __name__ == "__main__":
    sys.exit(main())
