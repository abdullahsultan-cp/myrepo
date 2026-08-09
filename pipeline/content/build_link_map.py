import os
import sys
from json import dump, load
from os import listdir
from os.path import abspath, dirname, join
from urllib.parse import parse_qs, unquote, urlparse
import re

import os as _os, sys as _sys  # noqa: E402
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import _bootstrap  # noqa: F401,E402  -- every pipeline folder on sys.path
from storyblok_utils import normalize_sequence_number, slugify, story_uuid

# Paths come from the shared module, so this works for any
# content type; see pipeline/paths_root.py.

from paths_root import P  # noqa: E402

# The SharePoint side of the link: the detail page internal links point at,
# and the id shape inside them (news_details.aspx?nid=NEWS-1234). Both are
# per type -- see source_urls in config/types/<type>.json.
DETAILS_PATTERN = re.compile(re.escape(P.source_urls["detail_page"]), re.I)
NID_PATTERN = re.compile(rf"^{re.escape(P.source_urls['id_prefix'])}-\d+$", re.I)
SOURCE_PREFIX = P.source_urls["prefix"].rstrip("/") + "/"


def load_news_items(folder_path):
    items = {}
    for filename in listdir(folder_path):
        if not filename.endswith(".json"):
            continue
        # encoding is explicit: on Windows the default is cp1252, which raises
        # on the first accented name in the corpus.
        with open(join(folder_path, filename), "r", encoding="utf-8") as f:
            item = load(f)
        items[filename] = item
    return items


def build_story_index(news_items):
    by_sequence = {}
    by_id = {}
    by_slug = {}

    for filename, item in news_items.items():
        sharepoint_id = item.get("Id") or item.get("ID")
        sequence_number = normalize_sequence_number(item.get("SequenceNumber"))
        title = item.get("Title") or f"{P.leaf}-{sharepoint_id}"
        slug = slugify(title, fallback=f"{P.leaf}-{sharepoint_id}")

        entry = {
            "file": filename,
            "sharepoint_id": sharepoint_id,
            "sequence_number": sequence_number,
            "title": title,
            "slug": slug,
            "story_uuid": story_uuid(sharepoint_id),
            "story_path": f"{P.story_prefix}/{slug}",
        }

        by_id[str(sharepoint_id)] = entry
        by_slug[slug] = entry
        if sequence_number:
            by_sequence[sequence_number] = entry

    return by_sequence, by_id, by_slug


def normalize_href(href):
    if not href:
        return href
    href = unquote(href.strip())
    parsed = urlparse(href)
    if parsed.scheme in {"http", "https"}:
        return href
    path = parsed.path or href
    if not path.startswith("/"):
        path = f"/{path}"
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{path}{query}"


def extract_nid(href):
    parsed = urlparse(href)
    query = parse_qs(parsed.query)
    for key in ("nid", "NID", "Nid"):
        values = query.get(key)
        if values:
            candidate = normalize_sequence_number(values[0])
            if candidate:
                return candidate
    return None


def resolve_href(href, by_sequence, by_slug=None, story_prefix=None):
    story_prefix = story_prefix or P.story_prefix
    normalized = normalize_href(href)
    lower = normalized.lower()

    if DETAILS_PATTERN.search(lower):
        sequence_number = extract_nid(normalized)
        if sequence_number and sequence_number in by_sequence:
            target = by_sequence[sequence_number]
            return {
                "resolved": True,
                "match_type": "sequence_number",
                "sequence_number": sequence_number,
                "target": target,
                "story_href": f"{story_prefix.rstrip('/')}/{target['slug']}",
            }
        return {
            "resolved": False,
            "match_type": "news_details_unresolved",
            "sequence_number": sequence_number,
            "original_href": normalized,
        }

    if normalized.startswith(SOURCE_PREFIX) and "Pages/" not in normalized:
        slug = normalized.split(SOURCE_PREFIX, 1)[-1].split("?", 1)[0].strip("/")
        entry = (by_slug or {}).get(slug)
        if entry:
            return {
                "resolved": True,
                "match_type": "slug_path",
                "slug": slug,
                "target": entry,
                "story_href": f"{story_prefix.rstrip('/')}/{slug}",
            }

    return {
        "resolved": False,
        "match_type": "external_or_document",
        "original_href": normalized,
    }


def build_url_lookup(by_sequence, story_prefix=None):
    story_prefix = story_prefix or P.story_prefix
    src = P.source_urls["prefix"].rstrip("/")
    page = P.source_urls["detail_page"]
    lookup = {}
    for sequence_number, entry in by_sequence.items():
        slug = entry["slug"]
        # A LIST, not a set. These are written to a JSON file that is committed,
        # and set iteration order for strings is randomised per process, so a
        # set here made every regeneration produce a different key order and a
        # 5,774-line diff that meant nothing. The variants are distinct
        # literals, so there is nothing for a set to deduplicate anyway.
        variants = [
            f"{src}/Pages/{page}?nid={sequence_number}",
            f"{src}/pages/{page}?nid={sequence_number}",
            f"{src}/pages/{page.lower()}?nid={sequence_number.lower()}",
            f"{story_prefix.rstrip('/')}/{slug}",
        ]
        for href in variants:
            lookup[normalize_href(href).lower()] = entry
    return lookup


def build_link_map(news_folder, story_prefix=None):
    story_prefix = story_prefix or P.story_prefix
    news_items = load_news_items(news_folder)
    by_sequence, by_id, by_slug = build_story_index(news_items)
    url_lookup = build_url_lookup(by_sequence, story_prefix=story_prefix)

    body_field = P.fields.get("body", "NewsContent")

    unresolved = {}
    resolved_examples = []

    for filename, item in news_items.items():
        html = item.get(body_field) or ""
        for match in re.finditer(r'href="([^"]+)"', html):
            href = match.group(1)
            if not href.startswith("/") and not href.lower().startswith("http"):
                continue
            resolution = resolve_href(href, by_sequence, by_slug, story_prefix=story_prefix)
            key = normalize_href(href).lower()
            if resolution.get("resolved"):
                if len(resolved_examples) < 20:
                    resolved_examples.append({"href": href, **resolution})
            else:
                unresolved[key] = unresolved.get(key, 0) + 1

    return {
        "summary": {
            "news_items": len(news_items),
            "stories_indexed": len(by_id),
            "sequence_numbers_indexed": len(by_sequence),
            "url_lookup_entries": len(url_lookup),
            "unresolved_relative_links": len(unresolved),
        },
        "stories": sorted(
            [
                {
                    "sharepoint_id": entry["sharepoint_id"],
                    "sequence_number": entry["sequence_number"],
                    "title": entry["title"],
                    "slug": entry["slug"],
                    "story_uuid": entry["story_uuid"],
                    "story_path": entry["story_path"],
                    "file": entry["file"],
                }
                for entry in by_id.values()
            ],
            key=lambda row: row["sharepoint_id"],
        ),
        "url_lookup": {
            key: {
                "sharepoint_id": value["sharepoint_id"],
                "sequence_number": value["sequence_number"],
                "slug": value["slug"],
                "story_uuid": value["story_uuid"],
                "story_path": value["story_path"],
            }
            for key, value in url_lookup.items()
        },
        "resolved_examples": resolved_examples,
        "unresolved_hrefs": sorted(
            [{"href": href, "count": count} for href, count in unresolved.items()],
            key=lambda row: (-row["count"], row["href"]),
        ),
    }


if __name__ == "__main__":
    base_path = abspath(join(dirname(__file__), ".."))
    news_folder = P.CLEANED
    output_path = P.report("storyblok_link_map.json")

    link_map = build_link_map(news_folder)
    with open(output_path, "w", encoding="utf-8", newline="\n") as f:
        dump(link_map, f, indent=2, ensure_ascii=False)

    summary = link_map["summary"]
    print("Storyblok link map")
    print("=" * 72)
    print(f"Stories indexed: {summary['stories_indexed']:,}")
    print(f"Sequence numbers indexed: {summary['sequence_numbers_indexed']:,}")
    print(f"URL lookup entries: {summary['url_lookup_entries']:,}")
    print(f"Unresolved relative links: {summary['unresolved_relative_links']:,}")
    print(f"Report exported to {output_path}")
