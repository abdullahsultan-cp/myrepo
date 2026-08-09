import os
import sys
from json import dump, load
from os import listdir
from os.path import abspath, basename, dirname, join, splitext
from urllib.parse import unquote
import re

from storyblok_config import load_config
from storyblok_utils import absolute_sharepoint_url

# Paths come from the shared module, so this works for any
# content type; see pipeline/paths_root.py.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths_root import P  # noqa: E402

IMAGE_PATTERN = re.compile(r'<img[^>]+src="([^"]+)"', re.I)


def scan_html_assets(folder_path):
    assets = {}
    for filename in listdir(folder_path):
        if not filename.endswith(".json"):
            continue
        with open(join(folder_path, filename), "r", encoding="utf-8") as f:
            html = load(f).get("NewsContent") or ""
        if not isinstance(html, str):
            continue
        for match in IMAGE_PATTERN.finditer(html):
            src = match.group(1).strip()
            if src:
                assets.setdefault(src, set()).add(filename)
    return assets


def scan_richtext_assets(folder_path):
    assets = {}
    for filename in listdir(folder_path):
        if not filename.endswith(".json"):
            continue
        with open(join(folder_path, filename), "r", encoding="utf-8") as f:
            payload = load(f)
        _walk_richtext_images(payload.get("NewsContent"), filename, assets)
    return assets


def _walk_richtext_images(node, filename, assets):
    if isinstance(node, dict):
        if node.get("type") == "image":
            src = (node.get("attrs") or {}).get("src")
            if src:
                assets.setdefault(src, set()).add(filename)
        for value in node.values():
            _walk_richtext_images(value, filename, assets)
    elif isinstance(node, list):
        for value in node:
            _walk_richtext_images(value, filename, assets)


def asset_entry(src, base_url, source_files):
    filename = basename(unquote(src.split("?", 1)[0])) or "asset"
    stem, ext = splitext(filename)
    if not ext:
        ext = ".bin"
        filename = f"{stem}{ext}"

    return {
        "sharepoint_src": src,
        "sharepoint_absolute_url": absolute_sharepoint_url(src, base_url),
        "filename": filename,
        "source_files": sorted(source_files),
        "storyblok_asset_id": None,
        "storyblok_filename": None,
        "storyblok_url": None,
        "upload_status": "pending",
    }


def build_asset_catalog(cleaned_folder, storyblok_folder, base_url):
    html_assets = scan_html_assets(cleaned_folder)
    richtext_assets = scan_richtext_assets(storyblok_folder)

    combined = {}
    for src, files in html_assets.items():
        combined.setdefault(src, set()).update(files)
    for src, files in richtext_assets.items():
        combined.setdefault(src, set()).update(files)

    assets = [
        asset_entry(src, base_url, files)
        for src, files in sorted(combined.items(), key=lambda item: item[0])
    ]

    sharepoint_paths = sum(1 for item in assets if item["sharepoint_src"].startswith("/"))
    return {
        "summary": {
            "unique_assets": len(assets),
            "sharepoint_relative_assets": sharepoint_paths,
            "external_assets": len(assets) - sharepoint_paths,
            "source_base_url": base_url,
        },
        "assets": assets,
    }


if __name__ == "__main__":
    base_path = abspath(join(dirname(__file__), ".."))
    cleaned_folder = P.CLEANED
    storyblok_folder = P.RICHTEXT
    output_path = P.report("storyblok_asset_catalog.json")
    asset_map_path = P.report("storyblok_asset_map.json")

    config = load_config()
    catalog = build_asset_catalog(
        cleaned_folder,
        storyblok_folder,
        config["sharepoint_base_url"],
    )

    with open(output_path, "w", encoding="utf-8", newline="\n") as f:
        dump(catalog, f, indent=2, ensure_ascii=False)

    asset_map = {
        item["sharepoint_src"]: {
            "storyblok_asset_id": item["storyblok_asset_id"],
            "storyblok_url": item["storyblok_url"],
            "upload_status": item["upload_status"],
        }
        for item in catalog["assets"]
    }
    with open(asset_map_path, "w", encoding="utf-8", newline="\n") as f:
        dump(asset_map, f, indent=2, ensure_ascii=False)

    summary = catalog["summary"]
    print("Storyblok asset catalog")
    print("=" * 72)
    print(f"Unique assets: {summary['unique_assets']:,}")
    print(f"SharePoint relative assets: {summary['sharepoint_relative_assets']:,}")
    print(f"External assets: {summary['external_assets']:,}")
    print(f"Catalog exported to {output_path}")
    print(f"Asset map exported to {asset_map_path}")
