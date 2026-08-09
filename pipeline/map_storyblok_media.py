"""Map data/storyblok_stories JSON files to assets/News/media via Metadata.csv."""

import sys
from collections import Counter
from csv import DictReader
from json import dump, load
from os import listdir
from os.path import abspath, dirname, isfile, join

SCRIPTS_DIR = abspath(dirname(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from validate_news_media import (
    DOWNLOAD_FAILED,
    MEDIA_COLUMNS,
    classify_extension,
    normalize_cell,
)

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from paths_root import P, ROOT as _ROOT  # noqa: E402

# A display path recorded in the report, not one that is opened. Derived from
# the shared module so a blogs run does not describe its media as living under
# assets/News.
MEDIA_RELATIVE_DIR = _os.path.relpath(P.MEDIA_DIR, _ROOT).replace("\\", "/")


def load_metadata_by_id(metadata_path):
    rows = {}
    with open(metadata_path, newline="", encoding="utf-8-sig") as handle:
        for row in DictReader(handle):
            news_id = normalize_cell(row.get("Id"))
            if news_id:
                rows[news_id] = row
    return rows


def media_assets_for_row(row, media_files):
    assets = []
    for role in MEDIA_COLUMNS:
        value = normalize_cell(row.get(role))
        if not value or value == DOWNLOAD_FAILED:
            continue
        assets.append(
            {
                "role": role,
                "filename": value,
                "relative_path": join(MEDIA_RELATIVE_DIR, value),
                "type": classify_extension(value),
                "exists": value in media_files,
            }
        )
    return assets


def story_sharepoint_id(story):
    meta = story.get("meta_data") or {}
    content = story.get("content") or {}
    return str(meta.get("sharepoint_id") or content.get("sharepoint_id") or "")


def build_storyblok_media_map(stories_dir, metadata_path, media_dir):
    media_files = {
        filename
        for filename in listdir(media_dir)
        if isfile(join(media_dir, filename))
    }
    metadata_by_id = load_metadata_by_id(metadata_path)

    story_files = sorted(
        filename
        for filename in listdir(stories_dir)
        if filename.endswith(".json")
    )

    mappings = []
    file_to_story = {}
    issues = []
    type_counts = Counter()
    role_counts = Counter()
    stories_with_media = 0
    stories_without_media = 0
    missing_story_files = []
    id_mismatches = []
    missing_metadata_rows = []

    for story_filename in story_files:
        story_path = join(stories_dir, story_filename)
        file_id = story_filename[:-5]

        with open(story_path, "r", encoding="utf-8") as handle:
            story = load(handle)

        sharepoint_id = story_sharepoint_id(story)
        if sharepoint_id != file_id:
            id_mismatches.append(
                {
                    "story_file": story_filename,
                    "file_id": file_id,
                    "sharepoint_id": sharepoint_id,
                }
            )

        metadata_row = metadata_by_id.get(file_id)
        if metadata_row is None:
            missing_metadata_rows.append(file_id)
            assets = []
        else:
            assets = media_assets_for_row(metadata_row, media_files)

        if assets:
            stories_with_media += 1
        else:
            stories_without_media += 1

        for asset in assets:
            type_counts[asset["type"]] += 1
            role_counts[asset["role"]] += 1
            if asset["filename"] in file_to_story:
                file_to_story[asset["filename"]].append(file_id)
            else:
                file_to_story[asset["filename"]] = [file_id]
            if not asset["exists"]:
                missing_story_files.append(
                    {
                        "story_file": story_filename,
                        "sharepoint_id": file_id,
                        "role": asset["role"],
                        "filename": asset["filename"],
                    }
                )

        mappings.append(
            {
                "story_file": join(_os.path.relpath(P.STORIES, _ROOT)
                                   .replace("\\", "/"),
                                   story_filename),
                "sharepoint_id": file_id,
                "story_uuid": (story.get("meta_data") or {}).get("story_uuid"),
                "slug": story.get("slug"),
                "title": story.get("name") or (story.get("content") or {}).get("title"),
                "asset_count": len(assets),
                "assets": assets,
            }
        )

    metadata_ids = set(metadata_by_id)
    story_ids = {entry["sharepoint_id"] for entry in mappings}
    stories_without_metadata = sorted(metadata_ids - story_ids)
    metadata_without_story = sorted(story_ids - metadata_ids)

    duplicate_media_refs = {
        filename: story_ids
        for filename, story_ids in file_to_story.items()
        if len(story_ids) > 1
    }

    mapped_media_files = set(file_to_story)
    orphan_media_files = sorted(media_files - mapped_media_files)
    unmapped_stories = [
        entry
        for entry in mappings
        if entry["asset_count"] == 0
    ]

    if id_mismatches:
        issues.append(
            {
                "type": "sharepoint_id_mismatch",
                "count": len(id_mismatches),
                "examples": id_mismatches[:20],
            }
        )
    if missing_metadata_rows:
        issues.append(
            {
                "type": "missing_metadata_row",
                "count": len(missing_metadata_rows),
                "examples": missing_metadata_rows[:20],
            }
        )
    if missing_story_files:
        issues.append(
            {
                "type": "missing_media_file",
                "count": len(missing_story_files),
                "examples": missing_story_files[:20],
            }
        )
    if orphan_media_files:
        issues.append(
            {
                "type": "orphan_media_file",
                "count": len(orphan_media_files),
                "examples": orphan_media_files[:20],
            }
        )
    if duplicate_media_refs:
        issues.append(
            {
                "type": "duplicate_media_reference",
                "count": len(duplicate_media_refs),
                "examples": [
                    {"filename": filename, "story_ids": story_ids}
                    for filename, story_ids in list(duplicate_media_refs.items())[:20]
                ],
            }
        )
    if unmapped_stories:
        issues.append(
            {
                "type": "story_without_media",
                "count": len(unmapped_stories),
                "examples": unmapped_stories[:20],
            }
        )

    validation_passed = not any(
        issue["type"]
        in {
            "sharepoint_id_mismatch",
            "missing_metadata_row",
            "missing_media_file",
            "orphan_media_file",
            "duplicate_media_reference",
        }
        for issue in issues
    )

    return {
        "summary": {
            "story_files": len(mappings),
            "metadata_rows": len(metadata_by_id),
            "stories_with_media": stories_with_media,
            "stories_without_media": stories_without_media,
            "media_files_on_disk": len(media_files),
            "mapped_media_files": len(mapped_media_files),
            "orphan_media_files": len(orphan_media_files),
            "missing_media_files": len(missing_story_files),
            "metadata_without_story": len(metadata_without_story),
            "stories_without_metadata": len(stories_without_metadata),
            "file_type_counts": dict(type_counts),
            "references_by_role": dict(role_counts),
            "validation_passed": validation_passed,
        },
        "media_to_stories": {
            filename: story_ids for filename, story_ids in sorted(file_to_story.items())
        },
        "issues": issues,
        "mapping": mappings,
    }


def print_report(report):
    summary = report["summary"]
    print("Storyblok stories to News media mapping")
    print("=" * 72)
    print(f"Story files: {summary['story_files']:,}")
    print(f"Metadata rows: {summary['metadata_rows']:,}")
    print(f"Stories with media: {summary['stories_with_media']:,}")
    print(f"Stories without media: {summary['stories_without_media']:,}")
    print()
    print(f"Media files on disk: {summary['media_files_on_disk']:,}")
    print(f"Mapped media files: {summary['mapped_media_files']:,}")
    print(f"Orphan media files: {summary['orphan_media_files']:,}")
    print(f"Missing media files: {summary['missing_media_files']:,}")
    print()
    print("Mapped file types:")
    for file_type, count in sorted(
        summary["file_type_counts"].items(),
        key=lambda item: (-item[1], item[0]),
    ):
        print(f"  {file_type}: {count:,}")
    print()
    print("References by role:")
    for role, count in sorted(
        summary["references_by_role"].items(),
        key=lambda item: (-item[1], item[0]),
    ):
        print(f"  {role}: {count:,}")
    print()
    print(
        "Validation: "
        + ("PASSED" if summary["validation_passed"] else "FAILED")
    )

    if report["issues"]:
        print()
        print("Issues:")
        for issue in report["issues"]:
            print(f"  {issue['type']}: {issue['count']:,}")
            for example in (issue.get("examples") or [])[:3]:
                print(f"    - {example}")
    print()


if __name__ == "__main__":
    base_path = abspath(join(dirname(__file__), ".."))
    stories_dir = P.STORIES
    metadata_path = P.METADATA_CSV
    media_dir = P.MEDIA_DIR
    output_path = P.report("storyblok_media_map.json")

    report = build_storyblok_media_map(stories_dir, metadata_path, media_dir)
    print_report(report)

    with open(output_path, "w", encoding="utf-8", newline="\n") as handle:
        dump(report, handle, indent=2, ensure_ascii=False)
    print(f"Mapping exported to {output_path}")
