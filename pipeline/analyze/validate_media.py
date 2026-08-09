"""Validate Metadata.csv references against assets/News/media and summarize file types."""

from collections import Counter, defaultdict
from csv import DictReader
from json import dump
from os import listdir
from os.path import abspath, dirname, isfile, join, splitext

import sys as _s, os as _o
_s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))
import os as _os, sys as _sys  # noqa: E402
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import _bootstrap  # noqa: F401,E402  -- every pipeline folder on sys.path
from paths_root import P  # noqa: E402

MEDIA_COLUMNS = (
    "Video1",
    "Video2",
    "Video3",
    "Thumbnail image",
    "Medium image",
    "Banner image",
    "Alternate banner image",
)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".webp", ".bmp", ".tif", ".tiff", ".svg"}
GIF_EXTENSIONS = {".gif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".webm", ".mkv", ".m4v", ".wmv"}

DOWNLOAD_FAILED = "DOWNLOAD_FAILED"


def classify_extension(filename):
    ext = splitext(filename)[1].lower()
    if ext in GIF_EXTENSIONS:
        return "gif"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext:
        return "other"
    return "unknown"


def normalize_cell(value):
    return (value or "").strip()


def build_mapping(metadata_path, media_dir):
    media_files = {
        filename
        for filename in listdir(media_dir)
        if isfile(join(media_dir, filename))
    }

    news_items = []
    referenced_files = []
    missing_files = []
    download_failed = Counter()
    empty_cells = Counter()
    role_counts = Counter()
    type_counts = Counter()
    type_by_role = defaultdict(Counter)
    issues = []

    with open(metadata_path, newline="", encoding="utf-8-sig") as handle:
        reader = DictReader(handle)
        for row in reader:
            news_id = normalize_cell(row.get("Id"))
            title = normalize_cell(row.get("Title"))
            assets = []

            for role in MEDIA_COLUMNS:
                value = normalize_cell(row.get(role))
                if not value:
                    empty_cells[role] += 1
                    continue
                if value == DOWNLOAD_FAILED:
                    download_failed[role] += 1
                    continue

                role_counts[role] += 1
                referenced_files.append(value)

                file_type = classify_extension(value)
                type_counts[file_type] += 1
                type_by_role[role][file_type] += 1

                exists = value in media_files
                if not exists:
                    missing_files.append(
                        {
                            "news_id": news_id,
                            "title": title,
                            "role": role,
                            "filename": value,
                        }
                    )

                assets.append(
                    {
                        "role": role,
                        "filename": value,
                        "type": file_type,
                        "exists": exists,
                    }
                )

            news_items.append(
                {
                    "news_id": news_id,
                    "title": title,
                    "assets": assets,
                    "asset_count": len(assets),
                }
            )

    referenced_set = set(referenced_files)
    orphan_files = sorted(media_files - referenced_set)

    news_without_media = [
        item for item in news_items if item["asset_count"] == 0
    ]
    news_with_media = [
        item for item in news_items if item["asset_count"] > 0
    ]

    if missing_files:
        issues.append(
            {
                "type": "missing_file",
                "count": len(missing_files),
                "examples": missing_files[:20],
            }
        )
    if orphan_files:
        issues.append(
            {
                "type": "orphan_file",
                "count": len(orphan_files),
                "examples": orphan_files[:20],
            }
        )
    if news_without_media:
        issues.append(
            {
                "type": "news_without_media",
                "count": len(news_without_media),
                "examples": news_without_media[:20],
            }
        )

    return {
        "summary": {
            "news_items": len(news_items),
            "news_with_media": len(news_with_media),
            "news_without_media": len(news_without_media),
            "media_references": len(referenced_files),
            "unique_media_files_referenced": len(referenced_set),
            "media_files_on_disk": len(media_files),
            "missing_references": len(missing_files),
            "orphan_files": len(orphan_files),
            "download_failed_cells": sum(download_failed.values()),
            "empty_cells": sum(empty_cells.values()),
            "file_type_counts": dict(type_counts),
            "references_by_role": dict(role_counts),
            "file_types_by_role": {
                role: dict(counts) for role, counts in sorted(type_by_role.items())
            },
            "download_failed_by_role": dict(download_failed),
            "empty_cells_by_role": dict(empty_cells),
            "validation_passed": not missing_files and not orphan_files,
        },
        "issues": issues,
        "mapping": news_items,
    }


def print_report(report):
    summary = report["summary"]
    print("News media mapping validation")
    print("=" * 72)
    print(f"News items in CSV: {summary['news_items']:,}")
    print(f"News with media: {summary['news_with_media']:,}")
    print(f"News without media: {summary['news_without_media']:,}")
    print()
    print(f"Media references in CSV: {summary['media_references']:,}")
    print(f"Unique files referenced: {summary['unique_media_files_referenced']:,}")
    print(f"Files on disk: {summary['media_files_on_disk']:,}")
    print(f"Missing references: {summary['missing_references']:,}")
    print(f"Orphan files on disk: {summary['orphan_files']:,}")
    print(f"DOWNLOAD_FAILED cells: {summary['download_failed_cells']:,}")
    print(f"Empty cells: {summary['empty_cells']:,}")
    print()
    print("File types (by extension):")
    for file_type, count in sorted(
        summary["file_type_counts"].items(),
        key=lambda item: (-item[1], item[0]),
    ):
        print(f"  {file_type}: {count:,}")
    print()
    print("References by CSV column:")
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
            examples = issue.get("examples") or []
            for example in examples[:5]:
                print(f"    - {example}")
    print()


if __name__ == "__main__":
    base_path = abspath(join(dirname(__file__), ".."))
    metadata_path = P.METADATA_CSV
    media_dir = P.MEDIA_DIR
    output_path = P.report("news_media_report.json")

    report = build_mapping(metadata_path, media_dir)
    print_report(report)

    with open(output_path, "w", encoding="utf-8", newline="\n") as handle:
        dump(report, handle, indent=2, ensure_ascii=False)
    print(f"Report exported to {output_path}")
