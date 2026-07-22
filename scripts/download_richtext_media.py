"""Download missing rich-text media assets and update story relationships."""

import argparse
import sys
from json import dump, load
from os import makedirs
from os.path import abspath, dirname, isfile, join

SCRIPTS_DIR = abspath(dirname(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from richtext_media_utils import (
    MEDIA_PUBLIC_PREFIX,
    attach_richtext_media_to_stories,
    build_catalog,
    generate_local_filename,
    load_media_files,
)
from storyblok_config import load_config

try:
    import requests
except ImportError:
    requests = None


def pick_download_url(asset):
    return asset.get("absolute_url") or asset.get("source_ref")


def download_asset(session, asset, media_dir, timeout=120):
    url = pick_download_url(asset)
    response = session.get(url, timeout=timeout, allow_redirects=True)
    response.raise_for_status()

    local_filename = asset["local_filename"]
    output_path = join(media_dir, local_filename)
    with open(output_path, "wb") as handle:
        handle.write(response.content)

    return {
        **asset,
        "local_filename": local_filename,
        "local_src": f"{MEDIA_PUBLIC_PREFIX}/{local_filename}",
        "exists_locally": True,
        "download_status": "downloaded",
        "bytes": len(response.content),
    }


def assign_local_filenames(assets, media_files):
    used_names = set(media_files)
    updated = []

    for asset in assets:
        if asset.get("local_filename") and asset["local_filename"] in media_files:
            asset = {
                **asset,
                "local_src": f"{MEDIA_PUBLIC_PREFIX}/{asset['local_filename']}",
                "exists_locally": True,
                "download_status": "present",
            }
            updated.append(asset)
            continue

        filename = generate_local_filename(
            asset["source_key"] or asset["source_ref"],
            asset["story_ids"],
        )
        stem, ext = filename.rsplit(".", 1) if "." in filename else (filename, "")
        candidate = filename
        counter = 2
        while candidate in used_names:
            candidate = f"{stem}-{counter}.{ext}" if ext else f"{stem}-{counter}"
            counter += 1

        used_names.add(candidate)
        updated.append(
            {
                **asset,
                "local_filename": candidate,
                "local_src": f"{MEDIA_PUBLIC_PREFIX}/{candidate}",
            }
        )

    return updated


def download_missing_assets(catalog, media_dir, dry_run=True, limit=None):
    media_files = load_media_files(media_dir)
    missing_assets = [
        asset for asset in catalog.get("missing_assets") or [] if not asset.get("exists_locally")
    ]
    if limit is not None:
        missing_assets = missing_assets[:limit]

    prepared = assign_local_filenames(missing_assets, media_files)
    if dry_run:
        return prepared, {
            "attempted": len(prepared),
            "downloaded": 0,
            "failed": 0,
            "dry_run": True,
            "failures": [],
        }

    if not requests:
        raise RuntimeError("requests is required for downloads. Install with: pip install requests")

    makedirs(media_dir, exist_ok=True)
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "aku-academy-richtext-media-downloader/1.0",
        }
    )

    downloaded = []
    failures = []
    for asset in prepared:
        try:
            downloaded.append(download_asset(session, asset, media_dir))
        except Exception as exc:
            failures.append(
                {
                    "source_key": asset.get("source_key"),
                    "absolute_url": asset.get("absolute_url"),
                    "error": str(exc),
                }
            )

    return downloaded, {
        "attempted": len(prepared),
        "downloaded": len(downloaded),
        "failed": len(failures),
        "dry_run": False,
        "failures": failures,
    }


def merge_catalog_assets(catalog, downloaded_assets):
    downloaded_by_key = {
        asset["source_key"]: asset for asset in downloaded_assets if asset.get("source_key")
    }
    merged_assets = []

    for asset in catalog.get("assets") or []:
        key = asset.get("source_key")
        if key in downloaded_by_key:
            merged = {**asset, **downloaded_by_key[key]}
            merged_assets.append(merged)
        else:
            merged_assets.append(asset)

    present = [asset for asset in merged_assets if asset.get("exists_locally")]
    missing = [asset for asset in merged_assets if not asset.get("exists_locally")]

    return {
        **catalog,
        "assets": merged_assets,
        "missing_assets": missing,
        "present_assets": present,
        "summary": {
            **catalog["summary"],
            "missing_assets": len(missing),
            "present_assets": len(present),
        },
    }


def update_stories(stories_dir, assets, base_url):
    summary = attach_richtext_media_to_stories(
        stories_dir,
        assets,
        base_url,
        add_media_bloks=True,
    )
    return summary["stories_updated"]


def build_map_payload(catalog, download_summary):
    stories_index = {}
    for asset in catalog.get("assets") or []:
        if not asset.get("local_filename"):
            continue
        for story_id in asset.get("story_ids") or []:
            stories_index.setdefault(story_id, [])
            stories_index[story_id].append(
                {
                    "source_key": asset.get("source_key"),
                    "local_filename": asset.get("local_filename"),
                    "local_src": asset.get("local_src"),
                    "media_type": asset.get("media_type"),
                    "basename": asset.get("basename"),
                }
            )

    return {
        "summary": {
            **catalog.get("summary", {}),
            **download_summary,
            "mapped_assets": sum(1 for asset in catalog.get("assets") or [] if asset.get("local_filename")),
            "stories_with_richtext_media": len(stories_index),
        },
        "assets": catalog.get("assets") or [],
        "stories": stories_index,
    }


def run(base_path, dry_run=True, limit=None, skip_story_updates=False):
    stories_dir = join(base_path, "data", "storyblok_stories")
    normalized_dir = join(base_path, "data", "normalized_news")
    media_dir = join(base_path, "assets", "News", "media")
    catalog_path = join(base_path, "data", "richtext_media_catalog.json")
    map_path = join(base_path, "data", "richtext_media_map.json")
    report_path = join(base_path, "data", "richtext_media_download_report.json")

    config = load_config()
    catalog = build_catalog(
        stories_dir=stories_dir,
        normalized_dir=normalized_dir,
        media_dir=media_dir,
        map_path=map_path,
        config=config,
    )

    downloaded_assets, download_summary = download_missing_assets(
        catalog,
        media_dir,
        dry_run=dry_run,
        limit=limit,
    )

    if dry_run:
        merged_catalog = catalog
    else:
        merged_catalog = merge_catalog_assets(catalog, downloaded_assets)

    map_payload = build_map_payload(merged_catalog, download_summary)

    if not dry_run and not skip_story_updates:
        updated_stories = update_stories(
            stories_dir,
            [asset for asset in merged_catalog.get("assets") or [] if asset.get("local_src")],
            config["sharepoint_base_url"],
        )
        download_summary["stories_updated"] = updated_stories
        map_payload["summary"]["stories_updated"] = updated_stories

    with open(catalog_path, "w") as handle:
        dump(merged_catalog, handle, indent=2, ensure_ascii=False)
    with open(map_path, "w") as handle:
        dump(map_payload, handle, indent=2, ensure_ascii=False)
    with open(report_path, "w") as handle:
        dump(
            {
                "summary": map_payload["summary"],
                "failures": download_summary.get("failures") or [],
            },
            handle,
            indent=2,
            ensure_ascii=False,
        )

    return merged_catalog, map_payload, download_summary


def print_summary(download_summary, map_payload):
    summary = map_payload["summary"]
    print("Rich text media download")
    print("=" * 72)
    print(f"Attempted downloads: {download_summary['attempted']:,}")
    print(f"Downloaded: {download_summary['downloaded']:,}")
    print(f"Failed: {download_summary['failed']:,}")
    print(f"Dry run: {download_summary['dry_run']}")
    if summary.get("stories_updated") is not None:
        print(f"Stories updated: {summary['stories_updated']:,}")
    print(f"Mapped assets: {summary.get('mapped_assets', 0):,}")
    print(f"Stories with rich-text media mappings: {summary.get('stories_with_richtext_media', 0):,}")

    failures = download_summary.get("failures") or []
    if failures:
        print()
        print("Failures:")
        for failure in failures[:10]:
            print(f"  {failure['absolute_url']}: {failure['error']}")
    print()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Download rich-text media assets missing from assets/News/media."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Perform downloads and update story files (default is dry-run).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Download at most N assets (useful for testing).",
    )
    parser.add_argument(
        "--skip-story-updates",
        action="store_true",
        help="Download files and write mapping JSON without modifying storyblok_stories.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    base_path = abspath(join(dirname(__file__), ".."))
    catalog_path = join(base_path, "data", "richtext_media_catalog.json")

    if args.execute and not isfile(catalog_path):
        print("No catalog found; building catalog first.")

    _, map_payload, download_summary = run(
        base_path,
        dry_run=not args.execute,
        limit=args.limit,
        skip_story_updates=args.skip_story_updates,
    )
    print_summary(download_summary, map_payload)

    base_path = abspath(join(dirname(__file__), ".."))
    print(f"Catalog updated at {join(base_path, 'data', 'richtext_media_catalog.json')}")
    print(f"Mapping updated at {join(base_path, 'data', 'richtext_media_map.json')}")
    print(f"Report exported to {join(base_path, 'data', 'richtext_media_download_report.json')}")
