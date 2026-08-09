"""Inject Metadata.csv media as news_media bloks into storyblok_stories."""

import sys
from collections import Counter
from csv import DictReader
from json import dump, load
from os import listdir
from os.path import abspath, dirname, isfile, join

SCRIPTS_DIR = abspath(dirname(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from storyblok_utils import generate_uid
from validate_news_media import (
    DOWNLOAD_FAILED,
    MEDIA_COLUMNS,
    classify_extension,
    normalize_cell,
)

from paths_root import P  # noqa: E402

MEDIA_PUBLIC_PREFIX = "/news-media"
MEDIA_ROLE_ORDER = (
    "Thumbnail image",
    "Banner image",
    "Alternate banner image",
    "Medium image",
    "Video1",
    "Video2",
    "Video3",
)

ROLE_SLUGS = {
    "Thumbnail image": "thumbnail",
    "Banner image": "banner",
    "Medium image": "medium",
    "Alternate banner image": "alternate_banner",
    "Video1": "video1",
    "Video2": "video2",
    "Video3": "video3",
}

CAPTION_FIELDS = {
    "Banner image": "banner_caption",
    "Medium image": "medium_image_caption",
    "Alternate banner image": "alternate_banner_caption",
}


def load_metadata_by_id(metadata_path):
    rows = {}
    with open(metadata_path, newline="", encoding="utf-8-sig") as handle:
        for row in DictReader(handle):
            news_id = normalize_cell(row.get("Id"))
            if news_id:
                rows[news_id] = row
    return rows


def caption_for_role(content, role):
    field = CAPTION_FIELDS.get(role)
    if not field:
        return None
    value = content.get(field)
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def build_media_blok(news_id, role, filename, content):
    role_slug = ROLE_SLUGS[role]
    return {
        "_uid": generate_uid(f"news-media:{news_id}:{role}:{filename}"),
        "component": "news_media",
        "role": role_slug,
        "filename": filename,
        "src": f"{MEDIA_PUBLIC_PREFIX}/{filename}",
        "media_type": classify_extension(filename),
        "caption": caption_for_role(content, role),
        "alt": normalize_cell(content.get("title")) or filename,
    }


def media_bloks_for_story(sharepoint_id, metadata_row, content):
    bloks = []
    for role in MEDIA_ROLE_ORDER:
        value = normalize_cell(metadata_row.get(role))
        if not value or value == DOWNLOAD_FAILED:
            continue
        bloks.append(build_media_blok(sharepoint_id, role, value, content))
    return bloks


def insert_media_before_body(content, media_bloks):
    updated = {}
    inserted = False

    for key, value in content.items():
        if key == "media":
            continue
        if key == "body" and not inserted:
            updated["media"] = media_bloks
            inserted = True
        updated[key] = value

    if not inserted:
        updated["media"] = media_bloks

    return updated


def inject_media_into_stories(stories_dir, metadata_path):
    metadata_by_id = load_metadata_by_id(metadata_path)
    story_files = sorted(
        filename for filename in listdir(stories_dir) if filename.endswith(".json")
    )

    updated = 0
    stories_with_media = 0
    total_media_bloks = 0
    role_counts = Counter()
    type_counts = Counter()
    missing_metadata = []

    for story_filename in story_files:
        story_path = join(stories_dir, story_filename)
        sharepoint_id = story_filename[:-5]

        with open(story_path, "r", encoding="utf-8") as handle:
            story = load(handle)

        metadata_row = metadata_by_id.get(sharepoint_id)
        if metadata_row is None:
            missing_metadata.append(sharepoint_id)
            media_bloks = []
        else:
            media_bloks = media_bloks_for_story(
                sharepoint_id,
                metadata_row,
                story.get("content") or {},
            )

        story["content"] = insert_media_before_body(story.get("content") or {}, media_bloks)

        with open(story_path, "w", encoding="utf-8", newline="\n") as handle:
            dump(story, handle, indent=2, ensure_ascii=False)

        updated += 1
        if media_bloks:
            stories_with_media += 1
            total_media_bloks += len(media_bloks)
            for blok in media_bloks:
                role_counts[blok["role"]] += 1
                type_counts[blok["media_type"]] += 1

    return {
        "summary": {
            "stories_updated": updated,
            "stories_with_media": stories_with_media,
            "stories_without_media": updated - stories_with_media,
            "total_media_bloks": total_media_bloks,
            "missing_metadata_rows": len(missing_metadata),
            "roles": dict(role_counts),
            "media_types": dict(type_counts),
        },
        "missing_metadata": missing_metadata[:20],
    }


def print_report(report):
    summary = report["summary"]
    print("Story media injection")
    print("=" * 72)
    print(f"Stories updated: {summary['stories_updated']:,}")
    print(f"Stories with media: {summary['stories_with_media']:,}")
    print(f"Stories without media: {summary['stories_without_media']:,}")
    print(f"Total media bloks injected: {summary['total_media_bloks']:,}")
    print()
    print("Media types:")
    for media_type, count in sorted(
        summary["media_types"].items(),
        key=lambda item: (-item[1], item[0]),
    ):
        print(f"  {media_type}: {count:,}")
    print()
    print("Roles:")
    for role, count in sorted(
        summary["roles"].items(),
        key=lambda item: (-item[1], item[0]),
    ):
        print(f"  {role}: {count:,}")
    print()


if __name__ == "__main__":
    base_path = abspath(join(dirname(__file__), ".."))
    stories_dir = P.STORIES
    metadata_path = P.METADATA_CSV
    output_path = P.report("storyblok_media_inject_report.json")

    if not isfile(metadata_path):
        raise SystemExit(f"Missing metadata file: {metadata_path}")

    report = inject_media_into_stories(stories_dir, metadata_path)
    print_report(report)

    with open(output_path, "w", encoding="utf-8", newline="\n") as handle:
        dump(report, handle, indent=2, ensure_ascii=False)
    print(f"Report exported to {output_path}")
