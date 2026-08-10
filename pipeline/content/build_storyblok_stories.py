import os
from copy import deepcopy
from json import dump, load
from os import listdir, makedirs
from os.path import abspath, dirname, join
import sys
import os as _os, sys as _sys  # noqa: E402
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import _bootstrap  # noqa: F401,E402  -- every pipeline folder on sys.path
from fields import F  # noqa: E402

SCRIPTS_DIR = abspath(dirname(__file__))

from normalize_html import normalize_content_html
from storyblok_config import load_config
from storyblok_embeds import pull_quote_to_blok_or_richtext
from storyblok_richtext import html_to_storyblok_richtext
from storyblok_utils import slugify, story_uuid

# Paths come from the shared module, so this works for any
# content type; see pipeline/paths_root.py.

from paths_root import P  # noqa: E402


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return load(f)


def nested_title(value):
    if isinstance(value, dict):
        return value.get("Title")
    return None


def lookup_ref(value):
    if not isinstance(value, dict):
        return None
    return {
        "id": value.get("Id"),
        "title": value.get("Title"),
        "email": value.get("EMail"),
    }


def lookup_taxonomy(value):
    if not isinstance(value, dict):
        return None
    return {
        "id": value.get("Id"),
        "title": value.get("Title"),
    }


def lookup_tags(values):
    if not isinstance(values, list):
        return []
    tags = []
    for item in values:
        if not isinstance(item, dict):
            continue
        tags.append(
            {
                "label": item.get("Label"),
                "term_guid": item.get("TermGuid"),
                "wss_id": item.get("WssId"),
            }
        )
    return tags


def lookup_entity_list(values):
    if not isinstance(values, list):
        return []
    entities = []
    for item in values:
        if isinstance(item, dict):
            entities.append({"id": item.get("Id"), "title": item.get("Title")})
    return entities


def normalize_news_in_urdu(value):
    if value is None:
        return None
    if isinstance(value, dict):
        return {
            "description": value.get("Description"),
            "url": value.get("Url") or value.get("URL"),
        }
    if isinstance(value, str) and value.strip():
        return {"description": value.strip(), "url": None}
    return None


def nested_labels(value):
    if isinstance(value, list):
        return [item.get("Label") for item in value if isinstance(item, dict) and item.get("Label")]
    return []


def convert_pull_quote(pull_quote, pull_quote_author, config):
    if not pull_quote or not str(pull_quote).strip():
        return None, None, []

    blok_or_doc, mode = pull_quote_to_blok_or_richtext(pull_quote, config=config)
    warnings = []

    if mode in {"twitter_embed", "iframe_embed"}:
        payload = {
            "type": "embed",
            "component_type": mode,
            "content": blok_or_doc,
        }
        if pull_quote_author:
            payload["author"] = pull_quote_author
        return payload, mode, warnings

    if mode == "richtext":
        if "<" in str(pull_quote):
            normalized_html, _, normalize_warnings = normalize_content_html(str(pull_quote))
            warnings.extend(normalize_warnings)
            result = html_to_storyblok_richtext(normalized_html, config=config)
            warnings.extend(result.warnings)
            doc = result.document
        else:
            doc = {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": str(pull_quote).strip()}],
                    }
                ],
            }

        payload = {"type": "richtext", "content": doc}
        if pull_quote_author:
            payload["author"] = pull_quote_author
        return payload, mode, warnings

    return None, "unsupported", warnings


def reserve_slug(base_slug, sharepoint_id, used_slugs):
    slug = base_slug
    if slug not in used_slugs:
        used_slugs.add(slug)
        return slug

    slug = f"{base_slug}-{sharepoint_id}"
    if slug not in used_slugs:
        used_slugs.add(slug)
        return slug

    counter = 2
    while True:
        candidate = f"{base_slug}-{sharepoint_id}-{counter}"
        if candidate not in used_slugs:
            used_slugs.add(candidate)
            return candidate
        counter += 1


def build_story_payload(item, config, used_slugs=None):
    used_slugs = used_slugs if used_slugs is not None else set()
    sharepoint_id = F.get(item, "id") or item.get("Id") or item.get("ID")
    title = F.get(item, "title") or f"{P.leaf.title()} {sharepoint_id}"
    slug = reserve_slug(
        slugify(title, fallback=f"{P.leaf}-{sharepoint_id}"),
        sharepoint_id,
        used_slugs,
    )

    pull_quote_payload, pull_quote_mode, pull_quote_warnings = convert_pull_quote(
        F.get(item, "pull_quote"),
        F.get(item, "pull_quote_author"),
        config,
    )

    # The payload shape is declared in config/types/<type>.json under
    # `content_fields`, not written out here. It used to be 44 hardcoded lines,
    # 27 of them naming News-list columns that no other list has -- which is
    # precisely why a blog built with this produced a payload full of nulls.
    # Walking the declaration keeps pipeline/ generic and puts each list's
    # peculiarities in its own profile. Order matters: it is the emitted key
    # order, so the declaration preserves the order this code had.
    DECODERS = {
        "taxonomy": lookup_taxonomy,
        "ref": lookup_ref,
        "tags": lookup_tags,
        "entity_list": lookup_entity_list,
        "urdu_link": normalize_news_in_urdu,
    }
    COMPUTED = {
        "component": config["news_component"],
        "uid": slugify(f"{sharepoint_id}-root", fallback=f"{P.leaf}-root"),
        "title": title,
        "pull_quote": pull_quote_payload,
        "sharepoint_id": sharepoint_id,
    }

    declared = P.spec.get("content_fields")
    if not declared:
        raise SystemExit(
            f"{P.type}: no `content_fields` in config/types/{P.type}.json — "
            f"the story payload has no declared shape. Copy the block from "
            f"news.json and change what differs.")

    content = {}
    for entry in declared:
        key = entry.get("key")
        # Skip only documentation entries. NOT every underscore key: `_uid` is
        # a real Storyblok field, and filtering on the prefix silently dropped
        # it from all 3,606 payloads.
        if not key or key == "_comment":
            continue
        if "computed" in entry:
            value = COMPUTED.get(entry["computed"])
        elif "field" in entry:
            value = F.get(item, entry["field"])
        else:
            value = item.get(entry.get("column"))
        decode = entry.get("decode")
        if decode:
            value = DECODERS[decode](value)
        content[key] = value

    tag_labels = [tag["label"] for tag in content["tags"] if tag.get("label")]

    story = {
        "name": title,
        "slug": slug,
        "tag_list": tag_labels,
        "is_startpage": False,
        "parent_id": config.get("parent_folder_id", 0),
        "meta_data": {
            "sharepoint_id": sharepoint_id,
            "sequence_number": F.get(item, "sequence_number"),
            "story_uuid": story_uuid(sharepoint_id),
        },
        "content": content,
    }

    return story, {
        "pull_quote_mode": pull_quote_mode,
        "pull_quote_warnings": pull_quote_warnings,
    }


def build_story_files(source_folder, output_folder, config):
    makedirs(output_folder, exist_ok=True)
    json_files = sorted(
        filename for filename in listdir(source_folder) if filename.endswith(".json")
    )

    pull_quote_modes = {}
    files_with_warnings = []
    slug_collisions = []
    used_slugs = set()

    for filename in json_files:
        with open(join(source_folder, filename), "r", encoding="utf-8") as f:
            item = load(f)
        sharepoint_id = F.get(item, "id") or item.get("Id") or item.get("ID")
        base_slug = slugify(F.get(item, "title") or f"{P.leaf.title()} {sharepoint_id}",
                        fallback=f"{P.leaf}-{sharepoint_id}")
        story, notes = build_story_payload(item, config, used_slugs=used_slugs)
        if story["slug"] != base_slug:
            slug_collisions.append(
                {
                    "file": filename,
                    "sharepoint_id": sharepoint_id,
                    "base_slug": base_slug,
                    "slug": story["slug"],
                }
            )
        pull_quote_modes[notes["pull_quote_mode"]] = (
            pull_quote_modes.get(notes["pull_quote_mode"], 0) + 1
        )
        if notes["pull_quote_warnings"]:
            files_with_warnings.append(
                {"file": filename, "warnings": notes["pull_quote_warnings"]}
            )

        with open(join(output_folder, filename), "w", encoding="utf-8") as f:
            dump(story, f, indent=2, ensure_ascii=False)

    return {
        "summary": {
            "files_processed": len(json_files),
            "pull_quote_modes": pull_quote_modes,
            "files_with_pull_quote_warnings": len(files_with_warnings),
            "slug_collisions_resolved": len(slug_collisions),
        },
        "slug_collisions": slug_collisions,
        "files_with_warnings": files_with_warnings,
    }


if __name__ == "__main__":
    base_path = abspath(join(dirname(__file__), ".."))
    source_folder = P.RICHTEXT_ENHANCED
    output_folder = P.STORIES
    report_path = P.report("storyblok_stories_report.json")

    config = load_config()
    report = build_story_files(source_folder, output_folder, config)

    with open(report_path, "w", encoding="utf-8", newline="\n") as f:
        dump(report, f, indent=2, ensure_ascii=False)

    summary = report["summary"]
    print("Storyblok story builder")
    print("=" * 72)
    print(f"Stories built: {summary['files_processed']:,}")
    print(f"Pull quote modes: {summary['pull_quote_modes']}")
    print(f"Stories exported to {output_folder}")
    print(f"Report exported to {report_path}")
