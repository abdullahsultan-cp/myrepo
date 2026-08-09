"""Shared helpers for cataloging and downloading rich-text media references."""

from hashlib import sha1
import re
from os import listdir
from os.path import basename, isdir, isfile, join, splitext
from urllib.parse import unquote, urlparse

from storyblok_config import load_config
from storyblok_utils import absolute_sharepoint_url, generate_uid
from validate_media import classify_extension

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from paths_root import P  # noqa: E402

# Both were hardcoded to news. The public prefix is what a rich-text link is
# rewritten to; the directory is where the file actually sits on disk.
MEDIA_PUBLIC_PREFIX = f"/{P.leaf}-media"
MEDIA_RELATIVE_DIR = _os.path.relpath(P.MEDIA_DIR, P.PIPELINE)

DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".zip",
    ".eps",
}
IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".jpe",
    ".jfif",
    ".png",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
    ".svg",
    ".gif",
}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".webm", ".mkv", ".m4v", ".wmv"}
MEDIA_EXTENSIONS = DOCUMENT_EXTENSIONS | IMAGE_EXTENSIONS | VIDEO_EXTENSIONS

SKIP_SRC_SUBSTRINGS = (
    "/_layouts/",
    "icpdf.png",
    "icdoc.png",
    "icppt.png",
    "icxls.png",
)

WINDOWS_PATH_PATTERN = re.compile(r"(?:^|/)[a-z]:/", re.I)

HTML_IMG_PATTERN = re.compile(r'<img[^>]+src="([^"]+)"', re.I)
HTML_LINK_PATTERN = re.compile(r'<a[^>]+href="([^"]+)"', re.I)


def normalize_ref(value):
    return unquote((value or "").strip())


def source_key(value, base_url):
    ref = normalize_ref(value)
    if not ref:
        return None
    if ref.startswith("http://") or ref.startswith("https://"):
        parsed = urlparse(ref)
        host = (parsed.netloc or "").lower()
        base_host = urlparse(base_url).netloc.lower()
        if host and base_host and host == base_host:
            path = parsed.path or "/"
            query = f"?{parsed.query}" if parsed.query else ""
            return f"{path}{query}"
        return ref
    return ref


def is_skipped_reference(value):
    ref = normalize_ref(value).lower()
    if not ref:
        return True
    if ref.startswith(f"{MEDIA_PUBLIC_PREFIX.lower()}/"):
        return True
    if ":\\" in ref or WINDOWS_PATH_PATTERN.search(ref):
        return True
    if any(token in ref for token in SKIP_SRC_SUBSTRINGS):
        return True
    return False


def extension_from_ref(value):
    ref = normalize_ref(value)
    parsed = urlparse(ref)
    path = parsed.path if parsed.scheme else ref.split("?", 1)[0]
    return splitext(path)[1].lower()


def is_media_reference(value):
    ref = normalize_ref(value)
    if not ref or is_skipped_reference(ref):
        return False
    if ref.startswith("mailto:"):
        return False
    ext = extension_from_ref(ref)
    if ext in MEDIA_EXTENSIONS:
        return True
    if ref.startswith("/") and "PublishingImages" in ref:
        return True
    return False


def absolute_url_for_ref(value, base_url):
    ref = normalize_ref(value)
    if ref.startswith("http://") or ref.startswith("https://"):
        return ref
    return absolute_sharepoint_url(ref, base_url)


def safe_filename(name, fallback="asset"):
    stem, ext = splitext(basename(unquote(name)))
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._")
    if not stem:
        stem = fallback
    if len(stem) > 80:
        stem = stem[:80].rstrip("-._")
    return f"{stem}{ext}" if ext else stem


def generate_local_filename(source_ref, story_ids):
    story_ids = sorted({str(story_id) for story_id in story_ids if story_id})
    basename_value = safe_filename(source_ref)
    digest = sha1(source_ref.encode("utf-8")).hexdigest()[:10]
    prefix = story_ids[0] if len(story_ids) == 1 else "shared"
    return f"{prefix}-richtext-{digest}-{basename_value}"


def load_media_files(media_dir):
    if not isdir(media_dir):
        return set()
    return {
        filename
        for filename in listdir(media_dir)
        if isfile(join(media_dir, filename))
    }


def load_existing_map(map_path):
    if not isfile(map_path):
        return {}
    from json import load

    with open(map_path, "r", encoding="utf-8") as handle:
        payload = load(handle)

    existing = {}
    for asset in payload.get("assets") or []:
        key = asset.get("source_key") or source_key(
            asset.get("source_ref") or asset.get("absolute_url"),
            asset.get("base_url") or "https://www.aku.edu",
        )
        if key:
            existing[key] = asset
    return existing


def media_files_on_disk(media_dir):
    return load_media_files(media_dir)


def asset_exists_locally(asset, media_files, existing_map):
    local_filename = asset.get("local_filename")
    if local_filename and local_filename in media_files:
        return True
    mapped = existing_map.get(asset.get("source_key") or "")
    if mapped:
        mapped_name = mapped.get("local_filename")
        if mapped_name and mapped_name in media_files:
            return True
    return False


def walk_richtext_references(node, field_name, story_id, references):
    if isinstance(node, dict):
        node_type = node.get("type")
        if node_type == "image":
            src = (node.get("attrs") or {}).get("src")
            if is_media_reference(src):
                references.append(
                    {
                        "story_id": str(story_id),
                        "field": field_name,
                        "kind": "image",
                        "ref": normalize_ref(src),
                    }
                )
        if node_type == "text":
            for mark in node.get("marks") or []:
                if mark.get("type") != "link":
                    continue
                href = (mark.get("attrs") or {}).get("href")
                if is_media_reference(href):
                    references.append(
                        {
                            "story_id": str(story_id),
                            "field": field_name,
                            "kind": "link",
                            "ref": normalize_ref(href),
                            "text": node.get("text"),
                        }
                    )
        for value in node.values():
            walk_richtext_references(value, field_name, story_id, references)
    elif isinstance(node, list):
        for value in node:
            walk_richtext_references(value, field_name, story_id, references)


def extract_html_references(html, story_id):
    references = []
    if not isinstance(html, str) or not html.strip():
        return references

    for src in HTML_IMG_PATTERN.findall(html):
        if is_media_reference(src):
            references.append(
                {
                    "story_id": str(story_id),
                    "field": "NewsContent",
                    "kind": "image",
                    "ref": normalize_ref(src),
                }
            )

    for href in HTML_LINK_PATTERN.findall(html):
        if is_media_reference(href):
            references.append(
                {
                    "story_id": str(story_id),
                    "field": "NewsContent",
                    "kind": "link",
                    "ref": normalize_ref(href),
                }
            )

    return references


def story_sharepoint_id(story):
    meta = story.get("meta_data") or {}
    content = story.get("content") or {}
    return str(meta.get("sharepoint_id") or content.get("sharepoint_id") or "")


def collect_story_references(story, story_filename):
    story_id = story_sharepoint_id(story) or story_filename[:-5]
    content = story.get("content") or {}
    references = []

    body = content.get("body")
    if isinstance(body, dict):
        walk_richtext_references(body, "body", story_id, references)

    pull_quote = content.get("pull_quote")
    if isinstance(pull_quote, dict) and pull_quote.get("type") == "richtext":
        walk_richtext_references(pull_quote.get("content"), "pull_quote", story_id, references)

    return references


def build_asset_record(source_ref, story_refs, base_url, media_files, existing_map):
    key = source_key(source_ref, base_url)
    story_ids = sorted({ref["story_id"] for ref in story_refs})
    media_type = classify_extension(safe_filename(source_ref))
    if media_type == "unknown" and extension_from_ref(source_ref) in DOCUMENT_EXTENSIONS:
        media_type = "other"

    asset = {
        "source_key": key,
        "source_ref": source_ref,
        "absolute_url": absolute_url_for_ref(source_ref, base_url),
        "basename": basename(unquote(source_ref.split("?", 1)[0])),
        "media_type": media_type,
        "story_ids": story_ids,
        "references": story_refs,
        "local_filename": None,
        "local_src": None,
        "exists_locally": False,
        "download_status": "pending",
    }

    mapped = existing_map.get(key)
    if mapped and mapped.get("local_filename"):
        asset["local_filename"] = mapped["local_filename"]
        asset["local_src"] = f"{MEDIA_PUBLIC_PREFIX}/{mapped['local_filename']}"
        asset["download_status"] = mapped.get("download_status", "downloaded")

    asset["exists_locally"] = asset_exists_locally(asset, media_files, existing_map)
    if asset["exists_locally"] and asset.get("local_filename"):
        asset["download_status"] = "present"
    return asset


def build_catalog(stories_dir, normalized_dir, media_dir, map_path=None, config=None):
    config = config or load_config()
    base_url = config["sharepoint_base_url"]
    media_files = load_media_files(media_dir)
    existing_map = load_existing_map(map_path) if map_path else {}

    raw_refs = []

    from json import load
    from os import listdir

    if stories_dir:
        for filename in sorted(listdir(stories_dir)):
            if not filename.endswith(".json"):
                continue
            with open(join(stories_dir, filename), "r",
                      encoding="utf-8") as handle:
                story = load(handle)
            raw_refs.extend(collect_story_references(story, filename))

    if normalized_dir:
        for filename in sorted(listdir(normalized_dir)):
            if not filename.endswith(".json"):
                continue
            story_id = filename[:-5]
            with open(join(normalized_dir, filename), "r",
                      encoding="utf-8") as handle:
                item = load(handle)
            html_refs = extract_html_references(item.get("NewsContent"), story_id)
            raw_refs.extend(html_refs)

    grouped = {}
    for ref in raw_refs:
        key = source_key(ref["ref"], base_url)
        if not key:
            continue
        grouped.setdefault(key, {"source_ref": ref["ref"], "references": []})
        grouped[key]["references"].append(ref)

    assets = []
    missing_assets = []
    type_counts = {}
    for key in sorted(grouped):
        record = grouped[key]
        asset = build_asset_record(
            record["source_ref"],
            record["references"],
            base_url,
            media_files,
            existing_map,
        )
        assets.append(asset)
        type_counts[asset["media_type"]] = type_counts.get(asset["media_type"], 0) + 1
        if not asset["exists_locally"]:
            missing_assets.append(asset)

    stories_with_missing = sorted(
        {
            ref["story_id"]
            for asset in missing_assets
            for ref in asset["references"]
        }
    )

    return {
        "summary": {
            "unique_media_references": len(assets),
            "missing_assets": len(missing_assets),
            "present_assets": len(assets) - len(missing_assets),
            "story_references": len(raw_refs),
            "stories_with_missing_media": len(stories_with_missing),
            "media_files_on_disk": len(media_files),
            "media_type_counts": type_counts,
            "sharepoint_base_url": base_url,
        },
        "assets": assets,
        "missing_assets": missing_assets,
        "stories_with_missing_media": stories_with_missing,
    }


def load_download_failures(download_report_path):
    if not download_report_path or not isfile(download_report_path):
        return {}
    from json import load

    with open(download_report_path, "r", encoding="utf-8") as handle:
        payload = load(handle)

    failures = {}
    for failure in payload.get("failures") or []:
        key = failure.get("source_key")
        if key:
            failures[key] = failure.get("error")
    return failures


def summarize_asset(asset, media_dir, failure_errors=None):
    failure_errors = failure_errors or {}
    local_filename = asset.get("local_filename")
    local_path = join(media_dir, local_filename) if local_filename else None
    file_exists = bool(local_path and isfile(local_path))
    file_size = None
    if file_exists:
        from os.path import getsize

        file_size = getsize(local_path)

    source_key_value = asset.get("source_key") or ""
    download_error = failure_errors.get(source_key_value)

    if file_exists:
        verification_status = "downloaded"
    elif download_error:
        verification_status = "failed"
    elif local_filename:
        verification_status = "mapped_missing"
    else:
        verification_status = "not_downloaded"

    return {
        "source_key": source_key_value,
        "source_ref": asset.get("source_ref"),
        "absolute_url": asset.get("absolute_url"),
        "basename": asset.get("basename"),
        "media_type": asset.get("media_type"),
        "story_ids": asset.get("story_ids") or [],
        "local_filename": local_filename,
        "local_path": local_path,
        "local_src": asset.get("local_src"),
        "file_exists": file_exists,
        "file_size_bytes": file_size,
        "download_status": asset.get("download_status"),
        "verification_status": verification_status,
        "download_error": download_error,
    }


def build_verification_report(
    stories_dir,
    normalized_dir,
    media_dir,
    map_path=None,
    download_report_path=None,
    config=None,
):
    catalog = build_catalog(
        stories_dir=stories_dir,
        normalized_dir=normalized_dir,
        media_dir=media_dir,
        map_path=map_path,
        config=config,
    )
    failure_errors = load_download_failures(download_report_path)

    downloaded_assets = []
    missing_assets = []
    failed_assets = []
    mapped_missing_assets = []

    for asset in catalog.get("assets") or []:
        entry = summarize_asset(asset, media_dir, failure_errors)
        if entry["verification_status"] == "downloaded":
            downloaded_assets.append(entry)
        elif entry["verification_status"] == "failed":
            failed_assets.append(entry)
            missing_assets.append(entry)
        elif entry["verification_status"] == "mapped_missing":
            mapped_missing_assets.append(entry)
            missing_assets.append(entry)
        else:
            missing_assets.append(entry)

    stories_downloaded = sorted(
        {
            story_id
            for asset in downloaded_assets
            for story_id in asset["story_ids"]
        }
    )
    stories_missing = sorted(
        {
            story_id
            for asset in missing_assets
            for story_id in asset["story_ids"]
        }
    )

    validation_passed = not missing_assets

    return {
        "summary": {
            **catalog["summary"],
            "downloaded_assets": len(downloaded_assets),
            "missing_assets": len(missing_assets),
            "failed_downloads": len(failed_assets),
            "mapped_missing_files": len(mapped_missing_assets),
            "not_downloaded": len(missing_assets) - len(failed_assets) - len(mapped_missing_assets),
            "stories_fully_downloaded": len(set(stories_downloaded) - set(stories_missing)),
            "stories_with_downloaded_media": len(stories_downloaded),
            "stories_with_missing_media": len(stories_missing),
            "validation_passed": validation_passed,
        },
        "downloaded_assets": downloaded_assets,
        "missing_assets": missing_assets,
        "failed_downloads": failed_assets,
        "mapped_missing_files": mapped_missing_assets,
        "stories_with_downloaded_media": stories_downloaded,
        "stories_with_missing_media": stories_missing,
    }


def replace_richtext_reference(node, replacements):
    changed = False

    if isinstance(node, dict):
        node_type = node.get("type")
        if node_type == "image":
            attrs = dict(node.get("attrs") or {})
            src = normalize_ref(attrs.get("src"))
            replacement = replacements.get(src)
            if replacement:
                attrs["src"] = replacement
                node = {**node, "attrs": attrs}
                changed = True
        if node_type == "text" and node.get("marks"):
            marks = []
            for mark in node["marks"]:
                if mark.get("type") == "link":
                    attrs = dict(mark.get("attrs") or {})
                    href = normalize_ref(attrs.get("href"))
                    replacement = replacements.get(href)
                    if replacement:
                        attrs["href"] = replacement
                        mark = {**mark, "attrs": attrs}
                        changed = True
                marks.append(mark)
            node = {**node, "marks": marks}

        updated = {}
        for key, value in node.items():
            new_value, child_changed = replace_richtext_reference(value, replacements)
            updated[key] = new_value
            changed = changed or child_changed
        return updated, changed

    if isinstance(node, list):
        updated = []
        for value in node:
            new_value, child_changed = replace_richtext_reference(value, replacements)
            updated.append(new_value)
            changed = changed or child_changed
        return updated, changed

    return node, False


def build_replacement_map(asset):
    local_src = asset.get("local_src")
    if not local_src:
        return {}

    replacements = {}
    candidates = [
        asset.get("source_ref"),
        asset.get("absolute_url"),
        asset.get("source_key"),
    ]
    for ref in asset.get("references") or []:
        candidates.append(ref.get("ref"))

    for candidate in candidates:
        normalized = normalize_ref(candidate)
        if normalized:
            replacements[normalized] = local_src
    return replacements


def build_richtext_media_blok(story_id, asset, content):
    filename = asset["local_filename"]
    title = (content.get("title") or "").strip()
    return {
        "_uid": generate_uid(f"{P.leaf}-media:{story_id}:richtext:{filename}"),
        "component": "news_media",
        "role": "richtext",
        "filename": filename,
        "src": asset["local_src"],
        "media_type": asset.get("media_type") or classify_extension(filename),
        "caption": asset.get("basename"),
        "alt": title or asset.get("basename") or filename,
        "source_key": asset.get("source_key"),
    }


def merge_richtext_media_bloks(existing_media, new_bloks):
    existing = list(existing_media or [])
    known_filenames = {blok.get("filename") for blok in existing if blok.get("filename")}
    merged = existing[:]
    for blok in new_bloks:
        filename = blok.get("filename")
        if filename and filename not in known_filenames:
            merged.append(blok)
            known_filenames.add(filename)
    return merged


def apply_story_media_updates(
    story,
    asset_by_source_key,
    base_url,
    add_media_bloks=False,
):
    content = story.get("content") or {}
    story_id = story_sharepoint_id(story)
    replacements = {}
    embedded_bloks = []
    media_bloks = []

    for key, asset in asset_by_source_key.items():
        if story_id not in asset.get("story_ids", []):
            continue
        local_src = asset.get("local_src")
        if not local_src:
            continue

        for ref, target in build_replacement_map(asset).items():
            replacements[ref] = target

        story_refs = [
            ref for ref in asset.get("references", []) if ref["story_id"] == story_id
        ]
        embedded_bloks.append(
            {
                "source_key": key,
                "local_filename": asset["local_filename"],
                "local_src": local_src,
                "media_type": asset["media_type"],
                "basename": asset["basename"],
                "references": story_refs,
            }
        )
        if add_media_bloks:
            media_bloks.append(build_richtext_media_blok(story_id, asset, content))

    if not replacements and not embedded_bloks and not media_bloks:
        return story, False

    updated_content = dict(content)
    changed = False

    body = updated_content.get("body")
    if isinstance(body, dict) and replacements:
        new_body, body_changed = replace_richtext_reference(body, replacements)
        if body_changed:
            updated_content["body"] = new_body
            changed = True

    pull_quote = updated_content.get("pull_quote")
    if isinstance(pull_quote, dict) and pull_quote.get("type") == "richtext" and replacements:
        new_content, pq_changed = replace_richtext_reference(
            pull_quote.get("content"),
            replacements,
        )
        if pq_changed:
            pull_quote = {**pull_quote, "content": new_content}
            updated_content["pull_quote"] = pull_quote
            changed = True

    if embedded_bloks:
        updated_content["richtext_media"] = embedded_bloks
        changed = True

    if media_bloks:
        merged_media = merge_richtext_media_bloks(updated_content.get("media"), media_bloks)
        if merged_media != (updated_content.get("media") or []):
            updated_content["media"] = merged_media
            changed = True

    if changed:
        story = {**story, "content": updated_content}
    return story, changed


def load_attachable_assets(map_path, media_dir):
    from json import load

    if isfile(map_path):
        with open(map_path, "r", encoding="utf-8") as handle:
            payload = load(handle)
        assets = payload.get("assets") or []
    else:
        assets = []

    media_files = load_media_files(media_dir)
    attachable = []
    for asset in assets:
        filename = asset.get("local_filename")
        if not filename or filename not in media_files:
            continue
        attachable.append(
            {
                **asset,
                "local_src": asset.get("local_src") or f"{MEDIA_PUBLIC_PREFIX}/{filename}",
                "exists_locally": True,
            }
        )
    return attachable


def attach_richtext_media_to_stories(
    stories_dir,
    assets,
    base_url,
    add_media_bloks=True,
):
    asset_by_source_key = {
        asset["source_key"]: asset
        for asset in assets
        if asset.get("source_key") and asset.get("local_src")
    }

    from json import dump, load
    from os import listdir

    updated_stories = 0
    stories_with_links = 0
    stories_with_media_bloks = 0
    total_media_bloks_added = 0

    for filename in sorted(listdir(stories_dir)):
        if not filename.endswith(".json"):
            continue
        story_path = join(stories_dir, filename)
        with open(story_path, "r", encoding="utf-8") as handle:
            story = load(handle)

        before_media_count = len((story.get("content") or {}).get("media") or [])
        updated_story, changed = apply_story_media_updates(
            story,
            asset_by_source_key,
            base_url,
            add_media_bloks=add_media_bloks,
        )
        if not changed:
            continue

        after_media_count = len((updated_story.get("content") or {}).get("media") or [])
        if (updated_story.get("content") or {}).get("richtext_media"):
            stories_with_links += 1
        if after_media_count > before_media_count:
            stories_with_media_bloks += 1
            total_media_bloks_added += after_media_count - before_media_count

        with open(story_path, "w", encoding="utf-8", newline="\n") as handle:
            dump(updated_story, handle, indent=2, ensure_ascii=False)
        updated_stories += 1

    return {
        "stories_updated": updated_stories,
        "stories_with_richtext_media": stories_with_links,
        "stories_with_media_bloks_added": stories_with_media_bloks,
        "media_bloks_added": total_media_bloks_added,
        "attachable_assets": len(assets),
    }
