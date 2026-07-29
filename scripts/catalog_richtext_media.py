"""Catalog PDF/image/media links in rich text that are missing from assets/News/media."""

import sys
from json import dump
from os.path import abspath, dirname, join

SCRIPTS_DIR = abspath(dirname(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from richtext_media_utils import build_catalog
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
    base_path = abspath(join(dirname(__file__), ".."))
    stories_dir = join(base_path, "data", "storyblok_stories")
    normalized_dir = join(base_path, "data", "normalized_news")
    media_dir = join(base_path, "assets", "News", "media")
    map_path = join(base_path, "data", "richtext_media_map.json")
    output_path = join(base_path, "data", "richtext_media_catalog.json")

    config = load_config()
    report = build_catalog(
        stories_dir=stories_dir,
        normalized_dir=normalized_dir,
        media_dir=media_dir,
        map_path=map_path,
        config=config,
    )
    print_report(report)

    with open(output_path, "w", encoding="utf-8") as handle:
        dump(report, handle, indent=2, ensure_ascii=False)
    print(f"Catalog exported to {output_path}")
