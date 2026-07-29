#!/usr/bin/env python3
"""
run_media_all.py — resolve, download and map every asset, in one process.

Runs the stages sequentially in a single process on purpose. Two concurrent
resolver passes share media_urls.json, and the one that finishes second rewrites
the whole file from its own in-memory copy — which silently reverted corrected
entries once already. One writer, always.

Stages
    1  resolve URLs for stories that have media   (the ones worth having)
    2  resolve URLs for everything else
    3  download every resolved file to assets/News/media/
    4  export the asset map + failure report
    5  rebuild the viewer index

Every stage is resumable: fetched pages are skipped, files already on disk are
not fetched twice. Killing this and re-running continues from where it stopped.

Usage:
    python scripts/migrate/download/run_media_all.py [--workers 6] [--skip-resolve]
"""

import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from paths import LOCK, MIGRATE  # noqa: E402


def run(label, script, args):
    """Run a stage as its own process. `script` is relative to scripts/migrate/."""
    print(f"\n{'=' * 70}\n  {label}\n{'=' * 70}", flush=True)
    t0 = time.time()
    r = subprocess.run([sys.executable, "-u", os.path.join(MIGRATE, script)]
                       + [str(a) for a in args])
    mins = (time.time() - t0) / 60
    print(f"  -- {label}: exit {r.returncode} in {mins:.1f} min", flush=True)
    if r.returncode != 0:
        raise SystemExit(f"stage failed: {label}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--skip-resolve", action="store_true")
    ap.add_argument("--skip-download", action="store_true")
    a = ap.parse_args()

    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    if os.path.exists(LOCK):
        age = (time.time() - os.path.getmtime(LOCK)) / 60
        if age < 240:
            sys.exit(
                f"another media run started {age:.0f} min ago "
                f"({LOCK}).\nTwo passes corrupt the cache. Wait, or delete the "
                f"lock if that run is dead.")
        print(f"  stale lock ({age:.0f} min old), continuing")
    with open(LOCK, "w", encoding="utf-8") as f:
        f.write(f"pid {os.getpid()} started {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    started = time.time()
    try:
        run("progress before", "download/media_progress.py", [])

        if not a.skip_resolve:
            run("1/5  resolve — stories that have media",
                "download/resolve_media_urls.py",
                ["--priority", "with-media", "--workers", a.workers])
            run("2/5  resolve — everything else",
                "download/resolve_media_urls.py", ["--workers", a.workers])

        if not a.skip_download:
            run("3/5  download every resolved file", "download/download_media.py",
                ["--workers", a.workers])

        run("4/5  export the asset map", "download/export_asset_map.py", ["--csv"])
        run("4/5  failure report", "download/report_failures.py", ["--csv"])
        run("5/5  rebuild the viewer index", "review/build_viewer_index.py", [])

        run("progress after", "download/media_progress.py", [])
        print(f"\n  ALL DONE in {(time.time() - started) / 60:.0f} min",
              flush=True)
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass


if __name__ == "__main__":
    main()
