import os
from copy import deepcopy
from json import dump, load
from os import listdir, makedirs
from os.path import abspath, dirname, join
import sys

SCRIPTS_DIR = abspath(dirname(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from normalize_news_html import normalize_news_content_html
from storyblok_config import load_config
from storyblok_embeds import pull_quote_to_blok_or_richtext
from storyblok_richtext import html_to_storyblok_richtext
from storyblok_utils import slugify, story_uuid

# Paths come from the shared module, so this works for any
# content type; see pipeline/paths_root.py.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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
            normalized_html, _, normalize_warnings = normalize_news_content_html(str(pull_quote))
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
    sharepoint_id = item.get("Id") or item.get("ID")
    title = item.get("Title") or f"News {sharepoint_id}"
    slug = reserve_slug(
        slugify(title, fallback=f"news-{sharepoint_id}"),
        sharepoint_id,
        used_slugs,
    )

    pull_quote_payload, pull_quote_mode, pull_quote_warnings = convert_pull_quote(
        item.get("PullQuote"),
        item.get("PullQuoteAuthor"),
        config,
    )

    content = {
        "component": config["news_component"],
        "_uid": slugify(f"{sharepoint_id}-root", fallback="news-root"),
        "title": title,
        "subtitle": item.get("NewsSubTitle"),
        "summary": item.get("NewsSummary"),
        "body": item.get("NewsContent"),
        "alternate_title": item.get("AlternateNewsTitle"),
        "alternate_subtitle": item.get("AlternateNewsSubtitle"),
        "alternate_summary": item.get("AlternateNewsSummary"),
        "alternate_banner_caption": item.get("AlternateBannerCaption"),
        "pull_quote": pull_quote_payload,
        "pull_quote_author": item.get("PullQuoteAuthor"),
        "banner_caption": item.get("BannerCaption"),
        "medium_image_caption": item.get("MediumImageCaption"),
        "category": lookup_taxonomy(item.get("Category")),
        "city": lookup_taxonomy(item.get("City")),
        "entity": lookup_taxonomy(item.get("Entity")),
        "additional_entities": lookup_entity_list(item.get("AdditionalEntity")),
        "author": lookup_ref(item.get("Author")),
        "publisher": lookup_ref(item.get("Publisher")),
        "content_writer": lookup_ref(item.get("ContentWriter")),
        "content_approver": lookup_ref(item.get("ContentApprover")),
        "editor": lookup_ref(item.get("Editor")),
        "tags": lookup_tags(item.get("Tags")),
        "global_news": item.get("GlobalNews"),
        "locally_active": item.get("LocallyActive"),
        "globally_active": item.get("GloballyActive"),
        "local_approver_group": item.get("LocalApproverGroup"),
        "global_approver_group": item.get("GlobalApproverGroup"),
        "is_published": item.get("IsPulished"),
        "is_globally_approved": item.get("IsGloballyApproved"),
        "is_locally_approved": item.get("IsLocallyApproved"),
        "is_modified_by_global": item.get("IsModifiedByGlobal"),
        "news_in_urdu": normalize_news_in_urdu(item.get("NewsInUrdu")),
        "contact": item.get("Contact"),
        "secondary_language_2": item.get("SecondaryLanguage2"),
        "secondary_language_3": item.get("SecondaryLanguage3"),
        "schedule_start_date": item.get("ScheduleStartDate"),
        "schedule_end_date": item.get("ScheduleEndDate"),
        "sequence_number": item.get("SequenceNumber"),
        "sharepoint_id": sharepoint_id,
        "sharepoint_sequence_number": item.get("SequenceNumber"),
        "sharepoint_modified": item.get("Modified"),
        "sharepoint_created": item.get("Created"),
    }

    tag_labels = [tag["label"] for tag in content["tags"] if tag.get("label")]

    story = {
        "name": title,
        "slug": slug,
        "tag_list": tag_labels,
        "is_startpage": False,
        "parent_id": config.get("parent_folder_id", 0),
        "meta_data": {
            "sharepoint_id": sharepoint_id,
            "sequence_number": item.get("SequenceNumber"),
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
        sharepoint_id = item.get("Id") or item.get("ID")
        base_slug = slugify(item.get("Title") or f"News {sharepoint_id}", fallback=f"news-{sharepoint_id}")
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
