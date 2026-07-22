from collections import Counter
from json import dump, load
from os import listdir
from os.path import abspath, dirname, join
import sys

SCRIPTS_DIR = abspath(dirname(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from storyblok_config import load_config
from storyblok_metadata_map import MAPPED_FIELDS, STRUCTURED_FIELDS, editorial_keys


def is_present(value):
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return True


def get_story_value(story, target_path):
    current = story
    for part in target_path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def source_has_rich_data(field, value):
    if field == "Tags":
        return isinstance(value, list) and any(
            isinstance(item, dict) and (item.get("TermGuid") or item.get("WssId"))
            for item in value
        )
    if field in {
        "Category",
        "City",
        "Entity",
        "Author",
        "Publisher",
        "ContentWriter",
        "ContentApprover",
        "Editor",
    }:
        return isinstance(value, dict) and value.get("Id") is not None
    if field == "AdditionalEntity":
        return isinstance(value, list) and len(value) > 0
    return False


def story_preserves_rich_data(field, story_value):
    if field == "Tags":
        if not isinstance(story_value, list):
            return False
        return any(
            isinstance(item, dict) and (item.get("term_guid") or item.get("wss_id"))
            for item in story_value
        )
    if field in STRUCTURED_FIELDS and field not in {"Tags", "AdditionalEntity"}:
        return isinstance(story_value, dict) and story_value.get("id") is not None
    if field == "AdditionalEntity":
        return isinstance(story_value, list) and len(story_value) > 0
    return True


def validate_item(item, story):
    missing_mappings = []
    null_in_story = []
    partial_loss = []

    for field in editorial_keys(item):
        source_value = item.get(field)
        if field in MAPPED_FIELDS:
            target = MAPPED_FIELDS[field]
            story_value = get_story_value(story, target)
            if is_present(source_value) and not is_present(story_value):
                null_in_story.append(
                    {
                        "field": field,
                        "target": target,
                        "source_preview": preview(source_value),
                    }
                )
        elif field in STRUCTURED_FIELDS:
            target = STRUCTURED_FIELDS[field]
            story_value = get_story_value(story, target)
            if is_present(source_value) and not is_present(story_value):
                null_in_story.append(
                    {
                        "field": field,
                        "target": target,
                        "source_preview": preview(source_value),
                    }
                )
            elif source_has_rich_data(field, source_value) and not story_preserves_rich_data(
                field, story_value
            ):
                partial_loss.append(
                    {
                        "field": field,
                        "target": target,
                        "issue": "nested ids/guids not preserved",
                        "source_preview": preview(source_value),
                        "story_preview": preview(story_value),
                    }
                )
        else:
            if is_present(source_value):
                missing_mappings.append(
                    {
                        "field": field,
                        "source_preview": preview(source_value),
                    }
                )

    return {
        "missing_mappings": missing_mappings,
        "null_in_story": null_in_story,
        "partial_loss": partial_loss,
    }


def preview(value, limit=120):
    text = str(value)
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def validate_metadata(source_folder, stories_folder):
    json_files = sorted(
        filename for filename in listdir(source_folder) if filename.endswith(".json")
    )

    files_with_issues = []
    issue_counts = Counter()
    field_issue_counts = Counter()

    for filename in json_files:
        with open(join(source_folder, filename), "r") as f:
            item = load(f)
        story_path = join(stories_folder, filename)
        try:
            with open(story_path, "r") as f:
                story = load(f)
        except FileNotFoundError:
            files_with_issues.append(
                {
                    "file": filename,
                    "issues": [{"type": "missing_story_file"}],
                }
            )
            issue_counts["missing_story_file"] += 1
            continue

        result = validate_item(item, story)
        issues = []
        for entry in result["missing_mappings"]:
            issues.append({"type": "unmapped_field", **entry})
            issue_counts["unmapped_field"] += 1
            field_issue_counts[entry["field"]] += 1
        for entry in result["null_in_story"]:
            issues.append({"type": "mapped_but_null", **entry})
            issue_counts["mapped_but_null"] += 1
            field_issue_counts[entry["field"]] += 1
        for entry in result["partial_loss"]:
            issues.append({"type": "partial_nested_loss", **entry})
            issue_counts["partial_nested_loss"] += 1
            field_issue_counts[entry["field"]] += 1

        if issues:
            files_with_issues.append({"file": filename, "issues": issues})

    mapped_count = len(MAPPED_FIELDS) + len(STRUCTURED_FIELDS)
    return {
        "summary": {
            "files_checked": len(json_files),
            "files_with_issues": len(files_with_issues),
            "mapped_field_definitions": mapped_count,
            "issue_counts": dict(issue_counts),
            "top_fields_with_issues": field_issue_counts.most_common(20),
            "mapping_registry": {
                "mapped_fields": MAPPED_FIELDS,
                "structured_fields": STRUCTURED_FIELDS,
            },
        },
        "files_with_issues": files_with_issues,
    }


def print_report(report):
    summary = report["summary"]
    print("Storyblok metadata validation")
    print("=" * 72)
    print(f"Files checked: {summary['files_checked']:,}")
    print(f"Files with issues: {summary['files_with_issues']:,}")
    print(f"Mapped field definitions: {summary['mapped_field_definitions']}")
    if summary["issue_counts"]:
        print()
        print("Issue counts:")
        for key, count in sorted(summary["issue_counts"].items()):
            print(f"  {key}: {count:,}")
    if summary["top_fields_with_issues"]:
        print()
        print("Top fields with issues:")
        for field, count in summary["top_fields_with_issues"][:15]:
            print(f"  {field}: {count:,}")
    print()


if __name__ == "__main__":
    base_path = abspath(join(dirname(__file__), ".."))
    source_folder = join(base_path, "data", "cleaned_news")
    stories_folder = join(base_path, "data", "storyblok_stories")
    output_path = join(base_path, "data", "storyblok_metadata_report.json")

    report = validate_metadata(source_folder, stories_folder)
    print_report(report)

    with open(output_path, "w") as f:
        dump(report, f, indent=2, ensure_ascii=False)
    print(f"Report exported to {output_path}")
