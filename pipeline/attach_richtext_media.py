"""Attach downloaded rich-text media assets into storyblok_stories."""

import os
import argparse
import sys
from json import dump
from os.path import abspath, dirname, isfile, join

SCRIPTS_DIR = abspath(dirname(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from richtext_media_utils import (
    attach_richtext_media_to_stories,
    build_catalog,
    load_attachable_assets,
)
from storyblok_config import load_config

# Paths come from the shared module, so this works for any
# content type; see pipeline/paths_root.py.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths_root import P  # noqa: E402


def print_report(report):
    summary = report["summary"]
    print("Rich text media attachment")
    print("=" * 72)
    print(f"Attachable assets on disk: {summary['attachable_assets']:,}")
    print(f"Stories updated: {summary['stories_updated']:,}")
    print(f"Stories with richtext_media metadata: {summary['stories_with_richtext_media']:,}")
    print(f"Stories with news_media bloks added: {summary['stories_with_media_bloks_added']:,}")
    print(f"news_media bloks added: {summary['media_bloks_added']:,}")
    print()


def run(base_path, add_media_bloks=True, dry_run=False):
    stories_dir = P.STORIES
    normalized_dir = P.NORMALIZED
    media_dir = P.MEDIA_DIR
    map_path = P.report("richtext_media_map.json")
    output_path = P.report("richtext_media_attach_report.json")

    config = load_config()
    assets = load_attachable_assets(map_path, media_dir)
    if not assets:
        catalog = build_catalog(
            stories_dir=stories_dir,
            normalized_dir=normalized_dir,
            media_dir=media_dir,
            map_path=map_path,
            config=config,
        )
        assets = [
            asset
            for asset in catalog.get("assets") or []
            if asset.get("local_filename") and asset.get("exists_locally")
        ]

    if dry_run:
        story_ids = sorted(
            {
                story_id
                for asset in assets
                for story_id in asset.get("story_ids") or []
            }
        )
        report = {
            "summary": {
                "dry_run": True,
                "attachable_assets": len(assets),
                "stories_updated": 0,
                "stories_with_richtext_media": len(story_ids),
                "stories_with_media_bloks_added": 0,
                "media_bloks_added": 0,
                "story_ids": story_ids,
            },
            "assets": assets,
        }
        return report

    summary = attach_richtext_media_to_stories(
        stories_dir,
        assets,
        config["sharepoint_base_url"],
        add_media_bloks=add_media_bloks,
    )
    report = {
        "summary": {
            **summary,
            "dry_run": False,
            "add_media_bloks": add_media_bloks,
        },
        "assets": assets,
    }

    with open(output_path, "w", encoding="utf-8", newline="\n") as handle:
        dump(report, handle, indent=2, ensure_ascii=False)

    return report


def parse_args():
    parser = argparse.ArgumentParser(
        description="Attach downloaded rich-text media into storyblok_stories."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Write updates to storyblok_stories (default is dry-run).",
    )
    parser.add_argument(
        "--skip-media-bloks",
        action="store_true",
        help="Only rewrite rich-text links/metadata; do not append news_media bloks.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    base_path = abspath(join(dirname(__file__), ".."))
    map_path = P.report("richtext_media_map.json")

    if not isfile(map_path):
        print("No richtext_media_map.json found; assets will be loaded from catalog.")

    report = run(
        base_path,
        add_media_bloks=not args.skip_media_bloks,
        dry_run=not args.execute,
    )
    print_report(report)

    output_path = P.report("richtext_media_attach_report.json")
    if not args.execute:
        with open(output_path, "w", encoding="utf-8", newline="\n") as handle:
            dump(report, handle, indent=2, ensure_ascii=False)
        print("Dry run only. Re-run with --execute to update story files.")
    print(f"Report exported to {output_path}")
