"""Verify rich-text media downloads and report downloaded vs missing assets."""

import sys
from json import dump
from os.path import abspath, dirname, join

SCRIPTS_DIR = abspath(dirname(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from richtext_media_utils import build_verification_report
from storyblok_config import load_config


def print_report(report):
    summary = report["summary"]
    print("Rich text media verification")
    print("=" * 72)
    print(f"Total assets referenced: {summary['unique_media_references']:,}")
    print(f"Downloaded (file on disk): {summary['downloaded_assets']:,}")
    print(f"Missing: {summary['missing_assets']:,}")
    print(f"  Failed downloads: {summary['failed_downloads']:,}")
    print(f"  Mapped but file missing: {summary['mapped_missing_files']:,}")
    print(f"  Not yet downloaded: {summary['not_downloaded']:,}")
    print()
    print(f"Stories with downloaded media: {summary['stories_with_downloaded_media']:,}")
    print(f"Stories with missing media: {summary['stories_with_missing_media']:,}")
    print()
    print(
        "Validation: "
        + ("PASSED" if summary["validation_passed"] else "FAILED")
    )

    downloaded = report.get("downloaded_assets") or []
    if downloaded:
        print()
        print(f"Downloaded assets ({len(downloaded):,}):")
        for asset in downloaded[:15]:
            size_kb = (asset.get("file_size_bytes") or 0) / 1024
            stories = ", ".join(asset["story_ids"][:4])
            suffix = "..." if len(asset["story_ids"]) > 4 else ""
            print(
                f"  {asset['local_filename']} "
                f"({size_kb:.1f} KB) [{asset['media_type']}] stories: {stories}{suffix}"
            )
        if len(downloaded) > 15:
            print(f"  ... and {len(downloaded) - 15:,} more in report")

    missing = report.get("missing_assets") or []
    if missing:
        print()
        print(f"Missing assets ({len(missing):,}):")
        for asset in missing[:15]:
            status = asset["verification_status"]
            error = asset.get("download_error")
            error_suffix = f" — {error[:70]}" if error else ""
            print(
                f"  [{status}] {asset['basename']} "
                f"-> {asset['absolute_url'][:70]}{error_suffix}"
            )
        if len(missing) > 15:
            print(f"  ... and {len(missing) - 15:,} more in report")
    print()


if __name__ == "__main__":
    base_path = abspath(join(dirname(__file__), ".."))
    stories_dir = join(base_path, "data", "storyblok_stories")
    normalized_dir = join(base_path, "data", "normalized_news")
    media_dir = join(base_path, "assets", "News", "media")
    map_path = join(base_path, "data", "richtext_media_map.json")
    download_report_path = join(base_path, "data", "richtext_media_download_report.json")
    output_path = join(base_path, "data", "richtext_media_verify_report.json")

    config = load_config()
    report = build_verification_report(
        stories_dir=stories_dir,
        normalized_dir=normalized_dir,
        media_dir=media_dir,
        map_path=map_path,
        download_report_path=download_report_path,
        config=config,
    )
    print_report(report)

    with open(output_path, "w", encoding="utf-8") as handle:
        dump(report, handle, indent=2, ensure_ascii=False)
    print(f"Report exported to {output_path}")
