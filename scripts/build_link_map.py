from json import dump, load
from os import listdir
from os.path import abspath, dirname, join
from urllib.parse import parse_qs, unquote, urlparse
import re

from storyblok_utils import normalize_sequence_number, slugify, story_uuid

NEWS_DETAILS_PATTERN = re.compile(r"news_details\.aspx", re.I)
NID_PATTERN = re.compile(r"^NEWS-\d+$", re.I)


def load_news_items(folder_path):
    items = {}
    for filename in listdir(folder_path):
        if not filename.endswith(".json"):
            continue
        with open(join(folder_path, filename), "r") as f:
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
        title = item.get("Title") or f"news-{sharepoint_id}"
        slug = slugify(title, fallback=f"news-{sharepoint_id}")

        entry = {
            "file": filename,
            "sharepoint_id": sharepoint_id,
            "sequence_number": sequence_number,
            "title": title,
            "slug": slug,
            "story_uuid": story_uuid(sharepoint_id),
            "story_path": f"/news/{slug}",
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


def resolve_href(href, by_sequence, by_slug=None, story_prefix="/news"):
    normalized = normalize_href(href)
    lower = normalized.lower()

    if NEWS_DETAILS_PATTERN.search(lower):
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

    if normalized.startswith("/news/") and "Pages/" not in normalized:
        slug = normalized.split("/news/", 1)[-1].split("?", 1)[0].strip("/")
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


def build_url_lookup(by_sequence, story_prefix="/news"):
    lookup = {}
    for sequence_number, entry in by_sequence.items():
        slug = entry["slug"]
        variants = {
            f"/news/Pages/News_Details.aspx?nid={sequence_number}",
            f"/news/pages/News_Details.aspx?nid={sequence_number}",
            f"/news/pages/news_details.aspx?nid={sequence_number.lower()}",
            f"{story_prefix.rstrip('/')}/{slug}",
        }
        for href in variants:
            lookup[normalize_href(href).lower()] = entry
    return lookup


def build_link_map(news_folder, story_prefix="/news"):
    news_items = load_news_items(news_folder)
    by_sequence, by_id, by_slug = build_story_index(news_items)
    url_lookup = build_url_lookup(by_sequence, story_prefix=story_prefix)

    unresolved = {}
    resolved_examples = []

    for filename, item in news_items.items():
        html = item.get("NewsContent") or ""
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
    news_folder = join(base_path, "data", "cleaned_news")
    output_path = join(base_path, "data", "storyblok_link_map.json")

    link_map = build_link_map(news_folder)
    with open(output_path, "w") as f:
        dump(link_map, f, indent=2, ensure_ascii=False)

    summary = link_map["summary"]
    print("Storyblok link map")
    print("=" * 72)
    print(f"Stories indexed: {summary['stories_indexed']:,}")
    print(f"Sequence numbers indexed: {summary['sequence_numbers_indexed']:,}")
    print(f"URL lookup entries: {summary['url_lookup_entries']:,}")
    print(f"Unresolved relative links: {summary['unresolved_relative_links']:,}")
    print(f"Report exported to {output_path}")
