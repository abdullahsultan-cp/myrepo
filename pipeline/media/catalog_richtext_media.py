"""Catalog PDF/image/media links in rich text that are missing from assets/News/media."""

from json import dump
from os.path import abspath, dirname

SCRIPTS_DIR = abspath(dirname(__file__))

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import _bootstrap

_bootstrap.ensure()
from richtext_media_utils import build_catalog

# Paths come from the shared module, so this works for any
# content type; see pipeline/paths_root.py.
from paths_root import P
from storyblok_config import load_config


def print_report(report):
    summary = report["summary"]
    print("Rich text media catalog")
    print("=" * 72)
    print(f"Unique media references: {summary['unique_media_references']:,}")
    print(f"Missing from assets/News/media: {summary['missing_assets']:,}")
    print(f"Already present locally: {summary['present_assets']:,}")
    print(f"Story references scanned: {summary['story_references']:,}")
    print(f"Stories with missing media: {summary['stories_with_missing_media']:,}")
    print(f"Files on disk in media folder: {summary['media_files_on_disk']:,}")
    print()
    print("Media types:")
    for media_type, count in sorted(
        summary["media_type_counts"].items(),
        key=lambda item: (-item[1], item[0]),
    ):
        print(f"  {media_type}: {count:,}")

    missing_assets = report.get("missing_assets") or []
    if missing_assets:
        print()
        print("Missing assets (first 20):")
        for asset in missing_assets[:20]:
            stories = ", ".join(asset["story_ids"][:5])
            suffix = "..." if len(asset["story_ids"]) > 5 else ""
            print(
                f"  [{asset['media_type']}] {asset['basename']} "
                f"-> {asset['absolute_url'][:90]}"
            )
            print(f"    stories: {stories}{suffix}")
    print()


if __name__ == "__main__":
    stories_dir = P.STORIES
    normalized_dir = P.NORMALIZED
    media_dir = P.MEDIA_DIR
    map_path = P.report("richtext_media_map.json")
    output_path = P.report("richtext_media_catalog.json")

    config = load_config()
    report = build_catalog(
        stories_dir=stories_dir,
        normalized_dir=normalized_dir,
        media_dir=media_dir,
        map_path=map_path,
        config=config,
    )
    print_report(report)

    with open(output_path, "w", encoding="utf-8", newline="\n") as handle:
        dump(report, handle, indent=2, ensure_ascii=False)
    print(f"Catalog exported to {output_path}")
