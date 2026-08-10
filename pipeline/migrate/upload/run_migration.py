#!/usr/bin/env python3
"""
run_migration.py — the whole migration, in one resumable command.

    python scripts/migrate/upload/run_migration.py

Runs pre-flight checks, uploads every asset, creates every story in its own
folder, verifies the result, writes the reports and takes a backup. Then stops.

RESUMING IS THE POINT. Close the laptop, lose power, hit Ctrl-C -- run the same
command again and it continues from where it stopped without creating anything
twice. Three independent guards make that true:

  1. Postgres records sb_story_id and sb_asset_id the moment each write returns,
     so a finished item is never revisited.
  2. A payload hash means an unchanged story is skipped rather than re-PUT.
  3. If the database itself were lost, the destination slug is still looked up
     before creating, so the worst case is an update rather than a duplicate.

A lock file stops two runs racing each other. Ctrl-C finishes the item in flight
and exits cleanly rather than killing a half-written upload.

Outputs, all under data/migrate/:
    migration.log              every action, appended, with timestamps
    reports/stories.csv        one row per story: destination, ids, status
    reports/folders.csv        per folder: expected vs uploaded
    reports/taxonomy.csv       per region / entity / department
    reports/assets.csv         one row per asset: story, role, folder, status
    reports/summary.json       the run at a glance
    backup/stories_<stamp>.json  full payload of every uploaded story
"""

import argparse
import csv
import json
import os
import signal
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone

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
import _bootstrap

_bootstrap.ensure()
import db as tracking
from paths import BASE, MIGRATE

# Paths come from the shared module so this script works for any content
# type; see pipeline/paths_root.py.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from paths_root import P

OUT = P.MIGRATE
REPORTS = os.path.join(OUT, "reports")
BACKUP = os.path.join(OUT, "backup")
LOG = os.path.join(OUT, "migration.log")
LOCK = os.path.join(OUT, ".migration.lock")

_stop = {"asked": False}


def on_sigint(signum, frame):
    """Ctrl-C once: stop after the current step. Twice: give up immediately."""
    if _stop["asked"]:
        log("second interrupt — exiting now")
        sys.exit(130)
    _stop["asked"] = True
    log("interrupt received — finishing the current step, then stopping. "
        "Re-run the same command to continue.")


def log(msg, *, echo=True):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    line = f"{stamp}  {msg}"
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8", newline="\n") as f:
        f.write(line + "\n")
    if echo:
        print(msg, flush=True)


def run(label, script, args):
    """Run one stage as its own process so a crash cannot take the run down.

    Output is STREAMED, not captured. capture_output=True buffers everything
    until the process exits, so the assets stage -- an hour of uploading --
    printed nothing at all and looked hung. Reading line by line means the
    console and the log both show progress as it happens.
    """
    log(f"\n{'=' * 70}\n  {label}\n{'=' * 70}")
    t0 = time.time()
    p = subprocess.Popen([sys.executable, "-u", os.path.join(MIGRATE, script)]
                         + [str(a) for a in args],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace",
                         bufsize=1)
    for line in p.stdout:
        line = line.rstrip()
        if line:
            log(f"    {line}")
    p.wait()
    mins = (time.time() - t0) / 60
    log(f"  -- {label}: exit {p.returncode} in {mins:.1f} min")
    if p.returncode != 0:
        raise SystemExit(f"stage failed: {label}")
    return p


# --------------------------------------------------------------- pre-flight

def preflight():
    """Refuse to start on a problem that would only surface 2000 stories in."""
    log(f"\n{'=' * 70}\n  PRE-FLIGHT\n{'=' * 70}")
    problems = []

    tree = P.SPACE_TREE
    if not os.path.exists(tree):
        problems.append("storyblok_space/folder_tree.json missing — run "
                        "scripts/migrate/review/dump_sb_tree.py")
    else:
        with open(tree, encoding="utf-8") as f:
            live = {x["full_slug"] for x in json.load(f)["folders"]}
        log(f"  live folder snapshot: {len(live)} folders")

        with tracking.connect() as c:
            c.execute("SET search_path TO migration, public")
            want = c.execute("""SELECT DISTINCT
                                  regexp_replace(target_full_slug,'/[^/]*$','')
                                FROM story
                                WHERE target_full_slug IS NOT NULL""").fetchall()
        need = {w[0] for w in want if w[0]}
        missing = sorted(need - live)
        log(f"  destination folders needed: {len(need)}")
        if missing:
            problems.append(
                f"{len(missing)} destination folders do not exist in the "
                f"space, e.g. {missing[:3]}. This script cannot create them "
                f"under regions/ or global/ — ask the front-end developer, "
                f"then re-run dump_sb_tree.py.")

    with tracking.connect() as c:
        c.execute("SET search_path TO migration, public")
        n_story = c.execute("SELECT count(*) FROM story").fetchone()[0]
        n_asset = c.execute("SELECT count(*) FROM asset").fetchone()[0]
        no_dest = c.execute("""SELECT count(*) FROM story
                               WHERE target_full_slug IS NULL
                                  OR target_full_slug=''""").fetchone()[0]
    log(f"  tracked: {n_story} stories, {n_asset} assets")
    if no_dest:
        problems.append(f"{no_dest} stories have no target_full_slug — run "
                        f"scripts/taxonomy/run_taxonomy.py")

    cfg = os.path.join(BASE, "config", "storyblok.json")
    if not os.path.exists(cfg):
        problems.append("config/storyblok.json missing")

    if problems:
        log("\n  CANNOT START:")
        for p in problems:
            log(f"    - {p}")
        raise SystemExit(1)
    log("  pre-flight OK")


# ----------------------------------------------------------------- reports

def w_csv(path, cols, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.DictWriter(f, lineterminator="\n", fieldnames=cols,
                            extrasaction="ignore")
        wr.writeheader()
        wr.writerows(rows)
    log(f"    {len(rows):>6}  {os.path.relpath(path, BASE)}")


def reports(space_id):
    log(f"\n{'=' * 70}\n  REPORTS\n{'=' * 70}")
    os.makedirs(REPORTS, exist_ok=True)
    editor = ("https://app.storyblok.com/#/me/spaces/"
              f"{space_id}/stories/0/0/{{id}}")

    with tracking.connect() as c:
        c.execute("SET search_path TO migration, public")
        stories = c.execute("""
            SELECT sharepoint_id, sequence_number, title, region, entity,
                   department, placement, surface_global, target_full_slug,
                   upload_full_slug, sb_story_id, sb_uuid, status, error,
                   uploaded_at
            FROM story ORDER BY sharepoint_id""").fetchall()
        assets = c.execute("""
            SELECT a.sharepoint_id, a.role, a.source_filename, a.status,
                   a.sb_asset_id, a.sb_filename,
                   coalesce(s.target_full_slug,'')
            FROM asset a LEFT JOIN story s USING (sharepoint_id)
            ORDER BY a.sharepoint_id, a.role""").fetchall()

    # ---- per story
    srows = []
    for (sid, seq, title, region, entity, dept, placement, glob, target,
         uploaded, sb_id, uuid, status, err, at) in stories:
        srows.append({
            "sharepoint_id": sid, "sequence_number": seq or "", "title": title,
            "region": region or "", "entity": entity or "",
            "department": dept or "", "placement": placement or "",
            "is_global": bool(glob),
            "target_full_slug": target or "",
            "uploaded_full_slug": uploaded or "",
            "in_expected_place": bool(uploaded) and uploaded == target,
            "sb_story_id": sb_id or "", "sb_uuid": uuid or "",
            "status": status,
            "sharepoint_url": (f"https://www.aku.edu/news/Pages/"
                               f"news_details.aspx?nid={(seq or '').upper()}"
                               if seq else ""),
            "storyblok_editor": editor.format(id=sb_id) if sb_id else "",
            "error": (err or "")[:300],
            "uploaded_at": at.isoformat() if at else "",
        })
    w_csv(os.path.join(REPORTS, "stories.csv"), list(srows[0]), srows)

    # ---- the review sheet: five columns, one row per story, nothing else.
    # Ordered by sr_no so it can be worked through top to bottom, and every
    # uploaded story comes first so the unfinished ones are not interleaved.
    domain = "https://aku-dev.vercel.app"
    cfg_path = os.path.join(BASE, "config", "storyblok.json")
    if os.path.exists(cfg_path):
        with open(cfg_path, encoding="utf-8") as f:
            domain = (json.load(f).get("frontend_domain") or domain).rstrip("/")
    links = []
    for i, r in enumerate(
            sorted(srows, key=lambda x: (not x["sb_story_id"],
                                         x["sharepoint_id"])), 1):
        links.append({
            "sr_no": i,
            "sharepoint_id": r["sharepoint_id"],
            "sharepoint_link": r["sharepoint_url"],
            "sb_editorial_link": r["storyblok_editor"],
            "sb_live_link": (f"{domain}/{r['uploaded_full_slug']}"
                             if r["uploaded_full_slug"] else ""),
        })
    w_csv(os.path.join(REPORTS, "links.csv"),
          ["sr_no", "sharepoint_id", "sharepoint_link", "sb_editorial_link",
           "sb_live_link"], links)

    # ---- per folder
    by_folder = defaultdict(lambda: {"expected": 0, "uploaded": 0,
                                     "failed": 0, "misplaced": 0})
    for r in srows:
        f = r["target_full_slug"].rsplit("/", 1)[0] if r["target_full_slug"] else "(none)"
        b = by_folder[f]
        b["expected"] += 1
        if r["sb_story_id"]:
            b["uploaded"] += 1
            if not r["in_expected_place"]:
                b["misplaced"] += 1
        if r["status"] == "failed":
            b["failed"] += 1
    frows = [{"folder": k, **v, "remaining": v["expected"] - v["uploaded"]}
             for k, v in sorted(by_folder.items())]
    w_csv(os.path.join(REPORTS, "folders.csv"),
          ["folder", "expected", "uploaded", "remaining", "failed",
           "misplaced"], frows)

    # ---- per region / entity / department
    by_tax = defaultdict(lambda: {"expected": 0, "uploaded": 0, "failed": 0})
    for r in srows:
        key = (r["region"] or "(none)", r["entity"] or "(none)",
               r["department"] or "(none)")
        b = by_tax[key]
        b["expected"] += 1
        if r["sb_story_id"]:
            b["uploaded"] += 1
        if r["status"] == "failed":
            b["failed"] += 1
    trows = [{"region": k[0], "entity": k[1], "department": k[2], **v,
              "remaining": v["expected"] - v["uploaded"]}
             for k, v in sorted(by_tax.items())]
    w_csv(os.path.join(REPORTS, "taxonomy.csv"),
          ["region", "entity", "department", "expected", "uploaded",
           "remaining", "failed"], trows)

    # ---- per asset
    arows = [{"sharepoint_id": sid, "role": role, "filename": fn,
              "status": st, "sb_asset_id": aid or "",
              "sb_url": sbfn or "",
              "asset_folder": (tgt.rsplit("/", 1)[0] if "/" in tgt else "")}
             for sid, role, fn, st, aid, sbfn, tgt in assets]
    w_csv(os.path.join(REPORTS, "assets.csv"),
          ["sharepoint_id", "role", "filename", "status", "asset_folder",
           "sb_asset_id", "sb_url"], arows)

    # ---- summary
    st_counts = Counter(r["status"] for r in srows)
    a_counts = Counter(r["status"] for r in arows)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "space_id": space_id,
        "stories": {
            "total": len(srows),
            "uploaded": sum(1 for r in srows if r["sb_story_id"]),
            "remaining": sum(1 for r in srows if not r["sb_story_id"]),
            "misplaced": sum(1 for r in srows
                             if r["sb_story_id"] and not r["in_expected_place"]),
            "by_status": dict(st_counts),
        },
        "assets": {"total": len(arows), "by_status": dict(a_counts)},
        "folders": {"destinations": len(frows),
                    "complete": sum(1 for f in frows if not f["remaining"])},
        "taxonomy_rows": len(trows),
    }
    p = os.path.join(REPORTS, "summary.json")
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    log(f"         -  {os.path.relpath(p, BASE)}")
    return summary


def backup():
    """Snapshot every uploaded story's payload, so a bad edit is recoverable."""
    log(f"\n{'=' * 70}\n  BACKUP\n{'=' * 70}")
    os.makedirs(BACKUP, exist_ok=True)
    snap_dir = os.path.join(OUT, "sb_snapshot")
    out = {}
    if os.path.isdir(snap_dir):
        for n in sorted(os.listdir(snap_dir)):
            if n.endswith(".json"):
                with open(os.path.join(snap_dir, n), encoding="utf-8") as f:
                    out[n[:-5]] = json.load(f)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    p = os.path.join(BACKUP, f"stories_{stamp}.json")
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"taken_at": stamp, "count": len(out), "stories": out},
                  f, indent=2, ensure_ascii=False)
    mb = os.path.getsize(p) / 1e6
    log(f"  {len(out)} stories -> {os.path.relpath(p, BASE)}  ({mb:.1f} MB)")


# -------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true",
                    help="only the 20-story review sample")
    ap.add_argument("--skip-assets", action="store_true")
    ap.add_argument("--skip-stories", action="store_true")
    ap.add_argument("--reports-only", action="store_true")
    ap.add_argument("--draft", action="store_true",
                    help="upload without publishing")
    a = ap.parse_args()

    signal.signal(signal.SIGINT, on_sigint)
    os.makedirs(OUT, exist_ok=True)

    cfg_path = os.path.join(BASE, "config", "storyblok.json")
    space = ""
    if os.path.exists(cfg_path):
        with open(cfg_path, encoding="utf-8") as f:
            space = json.load(f).get("space_id", "")

    if a.reports_only:
        reports(space)
        backup()
        return

    if os.path.exists(LOCK):
        age = (time.time() - os.path.getmtime(LOCK)) / 60
        if age < 240:
            sys.exit(f"another migration started {age:.0f} min ago ({LOCK}).\n"
                     f"Two runs would fight over the same stories. Wait, or "
                     f"delete the lock if that run is dead.")
        log(f"  stale lock ({age:.0f} min old), continuing")
    with open(LOCK, "w", encoding="utf-8", newline="\n") as f:
        f.write(f"pid {os.getpid()} started "
                f"{datetime.now(timezone.utc).isoformat()}\n")

    started = time.time()
    scope = [] if a.sample else ["--all-stories"]
    try:
        log(f"\n{'#' * 70}\n#  AKU NEWS MIGRATION"
            f"{'  (sample)' if a.sample else ''}\n{'#' * 70}")
        preflight()

        before = reports(space)
        log(f"\n  starting from: {before['stories']['uploaded']} stories "
            f"already uploaded, {before['stories']['remaining']} to go")

        if not a.skip_assets and not _stop["asked"]:
            run("1/4  assets", "upload/upload.py", ["assets"] + scope)

        if not a.skip_stories and not _stop["asked"]:
            args = ["stories"] + scope + (["--draft"] if a.draft else [])
            run("2/4  stories", "upload/upload.py", args)

        if not _stop["asked"]:
            run("3/4  read back from Storyblok", "upload/sync_from_sb.py",
                ["--snapshot"])

        log(f"\n{'=' * 70}\n  4/4  REPORTS AND BACKUP\n{'=' * 70}")
        after = reports(space)
        backup()

        mins = (time.time() - started) / 60
        s = after["stories"]
        log(f"\n{'#' * 70}")
        log(f"#  {'STOPPED EARLY' if _stop['asked'] else 'DONE'} in "
            f"{mins:.0f} min")
        log(f"#  stories  {s['uploaded']}/{s['total']} uploaded, "
            f"{s['remaining']} remaining, {s['misplaced']} misplaced")
        log(f"#  assets   {after['assets']['by_status']}")
        log(f"#  folders  {after['folders']['complete']}/"
            f"{after['folders']['destinations']} complete")
        log("#  reports  data/migrate/reports/")
        if s["remaining"]:
            log("#\n#  Not finished. Run the same command again to continue "
                "where it stopped.")
        log(f"{'#' * 70}")
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass


if __name__ == "__main__":
    main()
