from copy import deepcopy
from json import dump, load
from os import listdir, makedirs
from os.path import abspath, dirname, join
from urllib.parse import unquote
import sys

SCRIPTS_DIR = abspath(dirname(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from build_link_map import normalize_href
from storyblok_config import load_config
from storyblok_utils import absolute_sharepoint_url


def load_json(path):
    with open(path, "r") as f:
        return load(f)


def build_lookup_tables(link_map):
    url_lookup = link_map.get("url_lookup") or {}
    normalized = {}
    for key, value in url_lookup.items():
        normalized[normalize_href(key).lower()] = value
    return normalized


def resolve_link_mark(attrs, url_lookup, base_url="/news"):
    href = (attrs or {}).get("href") or ""
    normalized = normalize_href(href)
    target = url_lookup.get(normalized.lower())

    if target:
        return {
            **attrs,
            "href": target["story_path"],
            "target": attrs.get("target") or "_self",
            "linktype": "story",
            "uuid": target["story_uuid"],
            "anchor": attrs.get("anchor"),
            "custom": attrs.get("custom") or {},
        }, "story_link_resolved"

    if normalized.startswith("/"):
        return {
            **attrs,
            "href": absolute_sharepoint_url(normalized, base_url),
            "linktype": "url",
        }, "relative_link_unresolved"

    return attrs, None


def resolve_image_attrs(attrs, asset_map, base_url):
    src = (attrs or {}).get("src") or ""
    mapped = asset_map.get(src)
    if mapped and mapped.get("storyblok_url"):
        updated = dict(attrs)
        updated["src"] = mapped["storyblok_url"]
        if mapped.get("storyblok_asset_id"):
            updated["id"] = mapped["storyblok_asset_id"]
        return updated, "asset_url_replaced"

    if src.startswith("/"):
        updated = dict(attrs)
        updated["src"] = absolute_sharepoint_url(src, base_url)
        return updated, "sharepoint_image_absolute"

    return attrs, None


def enhance_richtext_node(node, url_lookup, asset_map, base_url, story_prefix, warnings):
    if isinstance(node, dict):
        node_type = node.get("type")

        if node_type == "text" and node.get("marks"):
            updated_marks = []
            for mark in node["marks"]:
                if mark.get("type") == "link":
                    attrs, note = resolve_link_mark(
                        mark.get("attrs"),
                        url_lookup,
                        base_url=base_url,
                    )
                    if note:
                        warnings.append(note)
                    updated_marks.append({**mark, "attrs": attrs})
                else:
                    updated_marks.append(mark)
            node = {**node, "marks": updated_marks}

        if node_type == "image":
            attrs, note = resolve_image_attrs(node.get("attrs"), asset_map, base_url)
            if note:
                warnings.append(note)
            node = {**node, "attrs": attrs}

        return {
            key: enhance_richtext_node(value, url_lookup, asset_map, base_url, story_prefix, warnings)
            for key, value in node.items()
        }

    if isinstance(node, list):
        return [
            enhance_richtext_node(value, url_lookup, asset_map, base_url, story_prefix, warnings)
            for value in node
        ]

    return node


def enhance_news_item(item, url_lookup, asset_map, config):
    enhanced = deepcopy(item)
    warnings = []
    news_content = enhanced.get("NewsContent")
    if isinstance(news_content, dict):
        enhanced["NewsContent"] = enhance_richtext_node(
            news_content,
            url_lookup,
            asset_map,
            config["sharepoint_base_url"],
            config["news_story_prefix"],
            warnings,
        )
    return enhanced, warnings


def enhance_news_files(source_folder, output_folder, link_map_path, asset_map_path, config):
    makedirs(output_folder, exist_ok=True)
    link_map = load_json(link_map_path)
    asset_map = load_json(asset_map_path)
    url_lookup = build_lookup_tables(link_map)

    json_files = sorted(
        filename for filename in listdir(source_folder) if filename.endswith(".json")
    )

    files_with_warnings = []
    warning_categories = {}

    for filename in json_files:
        with open(join(source_folder, filename), "r") as f:
            item = load(f)
        enhanced, warnings = enhance_news_item(item, url_lookup, asset_map, config)
        if warnings:
            files_with_warnings.append({"file": filename, "warnings": warnings})
            for warning in warnings:
                warning_categories[warning] = warning_categories.get(warning, 0) + 1

        with open(join(output_folder, filename), "w") as f:
            dump(enhanced, f, indent=2, ensure_ascii=False)

    return {
        "summary": {
            "files_processed": len(json_files),
            "files_with_warnings": len(files_with_warnings),
            "warning_categories": warning_categories,
        },
        "files_with_warnings": files_with_warnings,
    }


if __name__ == "__main__":
    base_path = abspath(join(dirname(__file__), ".."))
    source_folder = join(base_path, "data", "storyblok_news")
    output_folder = join(base_path, "data", "storyblok_news_enhanced")
    link_map_path = join(base_path, "data", "storyblok_link_map.json")
    asset_map_path = join(base_path, "data", "storyblok_asset_map.json")
    report_path = join(base_path, "data", "storyblok_enhance_report.json")

    config = load_config()
    report = enhance_news_files(
        source_folder, output_folder, link_map_path, asset_map_path, config
    )

    with open(report_path, "w") as f:
        dump(report, f, indent=2, ensure_ascii=False)

    summary = report["summary"]
    print("Storyblok richtext enhancement")
    print("=" * 72)
    print(f"Files processed: {summary['files_processed']:,}")
    print(f"Files with warnings: {summary['files_with_warnings']:,}")
    if summary["warning_categories"]:
        print("Warning categories:")
        for key, count in sorted(summary["warning_categories"].items()):
            print(f"  {key}: {count:,}")
    print(f"Enhanced news exported to {output_folder}")
    print(f"Report exported to {report_path}")
