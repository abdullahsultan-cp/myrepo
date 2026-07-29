from collections import Counter, defaultdict
from json import dump, load
from os import listdir
from os.path import abspath, dirname, join
import re

TAG_PATTERN = re.compile(
    r"<\s*(/?)\s*([a-zA-Z][a-zA-Z0-9]*)\b([^>]*)>",
    re.IGNORECASE,
)
ATTR_PATTERN = re.compile(r"\b([a-zA-Z_:][a-zA-Z0-9_:-]*)\s*=")

TAG_CONTEXT = {
    "div": {
        "classification": "sharepoint_artifact",
        "description": (
            "Block container used by SharePoint rich-text editing. The outer "
            "ExternalClass wrapper and nested div elements structure paragraphs "
            "instead of semantic p tags."
        ),
    },
    "br": {
        "classification": "sharepoint_artifact",
        "description": (
            "Line break inserted by SharePoint/Word editors, commonly used inside "
            "empty div elements to create vertical spacing between paragraphs."
        ),
    },
    "p": {
        "classification": "structural",
        "description": "Paragraph element for body text blocks.",
    },
    "span": {
        "classification": "inline_formatting",
        "description": (
            "Inline wrapper for styled text. Often carries Word/SharePoint paste "
            "metadata such as lang, style, or data-contrast attributes."
        ),
    },
    "a": {
        "classification": "link",
        "description": (
            "Hyperlink to external pages, documents, or in-site resources. "
            "Frequently uses target=\"_blank\" for off-site links."
        ),
    },
    "strong": {
        "classification": "inline_formatting",
        "description": "Semantic emphasis for bold text.",
    },
    "em": {
        "classification": "inline_formatting",
        "description": "Semantic emphasis for italic text.",
    },
    "b": {
        "classification": "inline_formatting",
        "description": "Legacy bold formatting tag from older HTML or pasted Word content.",
    },
    "i": {
        "classification": "inline_formatting",
        "description": "Legacy italic formatting tag from older HTML or pasted Word content.",
    },
    "sup": {
        "classification": "inline_formatting",
        "description": "Superscript text, often used for footnotes or ordinal markers.",
    },
    "font": {
        "classification": "inline_formatting",
        "description": (
            "Deprecated font styling tag retained from legacy HTML or Word paste."
        ),
    },
    "ul": {
        "classification": "structural",
        "description": "Unordered (bulleted) list container.",
    },
    "ol": {
        "classification": "structural",
        "description": "Ordered (numbered) list container.",
    },
    "li": {
        "classification": "structural",
        "description": "Individual list item inside ul or ol.",
    },
    "table": {
        "classification": "structural",
        "description": "Tabular data layout for schedules, comparisons, or event details.",
    },
    "tbody": {
        "classification": "structural",
        "description": "Table body grouping rows within a table.",
    },
    "tr": {
        "classification": "structural",
        "description": "Table row containing td or th cells.",
    },
    "td": {
        "classification": "structural",
        "description": "Table data cell.",
    },
    "h1": {
        "classification": "structural",
        "description": "Top-level heading within article body content.",
    },
    "h2": {
        "classification": "structural",
        "description": "Secondary heading within article body content.",
    },
    "h3": {
        "classification": "structural",
        "description": "Tertiary heading within article body content.",
    },
    "h4": {
        "classification": "structural",
        "description": "Fourth-level heading within article body content.",
    },
    "blockquote": {
        "classification": "structural",
        "description": "Quoted passage or pull-quote block.",
    },
    "img": {
        "classification": "media",
        "description": (
            "Embedded image referenced by src, usually with alt text for captions "
            "or accessibility."
        ),
    },
    "iframe": {
        "classification": "media",
        "description": (
            "Embedded external content such as YouTube videos or other hosted media."
        ),
    },
    "style": {
        "classification": "embedded",
        "description": (
            "Inline CSS block inserted by editors or export tools. Review before "
            "stripping because it may control layout inside NewsContent."
        ),
    },
}

CLASSIFICATION_SUMMARY = {
    "sharepoint_artifact": (
        "Markup patterns introduced by SharePoint/Word rich-text editing. These are "
        "common cleanup targets when normalizing NewsContent to semantic HTML."
    ),
    "structural": (
        "Semantic or layout HTML elements that define paragraphs, headings, lists, "
        "tables, and quoted blocks."
    ),
    "inline_formatting": (
        "Inline tags used for emphasis, styling, or legacy font markup inside "
        "paragraphs."
    ),
    "link": (
        "Anchor tags linking to external websites, documents, or other AKU pages."
    ),
    "media": (
        "Embedded images, videos, or other rich media referenced inside the article."
    ),
    "embedded": (
        "Non-visible or script/style markup embedded in HTML. Review carefully "
        "before removal."
    ),
    "inferred": (
        "No explicit note exists yet for this tag. Classification was inferred "
        "from the HTML tag name."
    ),
}


def load_news_data(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        return load(f)


def get_tag_context(tag_name):
    if tag_name in TAG_CONTEXT:
        return TAG_CONTEXT[tag_name]

    if tag_name.startswith("h") and tag_name[1:].isdigit():
        level = tag_name[1:]
        return {
            "classification": "structural",
            "description": f"Heading level {level} within article body content.",
        }

    return {
        "classification": "inferred",
        "description": (
            "Tag context inferred automatically. Add an explicit entry to "
            "TAG_CONTEXT if this tag needs a fixed editorial note."
        ),
    }


def snippet(text, match, radius=50):
    start = max(0, match.start() - radius)
    end = min(len(text), match.end() + radius)
    return text[start:end]


def extract_tags(text):
    found = {}
    for match in TAG_PATTERN.finditer(text):
        closing, raw_name, attr_text = match.groups()
        if closing:
            continue

        tag_name = raw_name.lower()
        attributes = [attr.lower() for attr in ATTR_PATTERN.findall(attr_text)]

        if tag_name not in found:
            found[tag_name] = {
                "count": 0,
                "attributes": Counter(),
                "example_match": match,
            }

        found[tag_name]["count"] += 1
        found[tag_name]["attributes"].update(attributes)

    return found


def new_findings_store():
    return defaultdict(
        lambda: {
            "classification": "",
            "description": "",
            "total_count": 0,
            "attributes": Counter(),
            "files": set(),
            "examples": [],
        }
    )


def analyze_news_content(news_content, filename, findings):
    if not isinstance(news_content, str) or not news_content.strip():
        return False

    for tag_name, info in extract_tags(news_content).items():
        context = get_tag_context(tag_name)
        entry = findings[tag_name]
        entry["classification"] = context["classification"]
        entry["description"] = context["description"]
        entry["total_count"] += info["count"]
        entry["attributes"].update(info["attributes"])
        entry["files"].add(filename)

        if len(entry["examples"]) < 3:
            entry["examples"].append(
                {
                    "file": filename,
                    "field": "NewsContent",
                    "snippet": snippet(news_content, info["example_match"]),
                }
            )

    return True


def iterate_cleaned_news(folder_path):
    findings = new_findings_store()
    json_files = sorted(
        filename for filename in listdir(folder_path) if filename.endswith(".json")
    )

    files_with_newscontent = 0
    for filename in json_files:
        news_item_data = load_news_data(join(folder_path, filename))
        news_content = news_item_data.get("NewsContent")
        if analyze_news_content(news_content, filename, findings):
            files_with_newscontent += 1

    return findings, len(json_files), files_with_newscontent


def sorted_findings(findings):
    return sorted(
        findings.items(),
        key=lambda item: (-item[1]["total_count"], item[0]),
    )


def print_classification_summary(findings):
    grouped = defaultdict(list)
    for tag_name, info in sorted_findings(findings):
        grouped[info["classification"]].append((tag_name, info))

    print("Classification guide")
    print("=" * 80)
    for classification, description in CLASSIFICATION_SUMMARY.items():
        count = len(grouped.get(classification, []))
        print(f"[{classification}] ({count} tags)")
        print(f"  {description}")
        print()


def print_complete_inventory(findings):
    items = sorted_findings(findings)
    print(f"Complete inventory: {len(items)} unique HTML tags")
    print("=" * 80)
    print(f"{'#':>3}  {'Tag':<12}  {'Count':>8}  {'Files':>7}  {'Class':<22}  Description")
    print("-" * 80)

    for index, (tag_name, info) in enumerate(items, start=1):
        print(
            f"{index:>3}  {tag_name:<12}  {info['total_count']:>8,}  "
            f"{len(info['files']):>7,}  {info['classification']:<22}  "
            f"{info['description'][:40]}"
        )

    print()


def print_tag_details(findings):
    print("Tag details")
    print("=" * 80)

    for index, (tag_name, info) in enumerate(sorted_findings(findings), start=1):
        top_attributes = info["attributes"].most_common(8)
        print(f"{index}. <{tag_name}>")
        print(f"   Occurrences: {info['total_count']:,}")
        print(f"   Files: {len(info['files'])}")
        print(f"   Classification: {info['classification']}")
        print(f"   Context: {info['description']}")
        if top_attributes:
            attrs = ", ".join(f"{name} ({count:,})" for name, count in top_attributes)
            print(f"   Attributes: {attrs}")

        for example in info["examples"]:
            print(f"   Example in {example['file']} [{example['field']}]:")
            print(f"     {example['snippet']!r}")
        print()


def print_report(findings, files_scanned, files_with_newscontent):
    print(f"Files scanned: {files_scanned:,}")
    print(f"Files with NewsContent HTML: {files_with_newscontent:,}")
    print()

    if not findings:
        print("No HTML tags found in NewsContent.")
        return

    print_classification_summary(findings)
    print_complete_inventory(findings)
    print_tag_details(findings)


def export_report(findings, output_path, files_scanned, files_with_newscontent):
    items = []
    for tag_name, info in sorted_findings(findings):
        items.append(
            {
                "rank": len(items) + 1,
                "tag": tag_name,
                "classification": info["classification"],
                "description": info["description"],
                "total_count": info["total_count"],
                "file_count": len(info["files"]),
                "attributes": sorted(info["attributes"]),
                "attribute_usage": dict(info["attributes"]),
                "files": sorted(info["files"]),
                "examples": info["examples"],
            }
        )

    payload = {
        "summary": {
            "field": "NewsContent",
            "files_scanned": files_scanned,
            "files_with_newscontent": files_with_newscontent,
            "unique_tag_count": len(items),
            "classification_guide": CLASSIFICATION_SUMMARY,
            "by_classification": {
                classification: len(
                    [item for item in items if item["classification"] == classification]
                )
                for classification in CLASSIFICATION_SUMMARY
            },
        },
        "tags": items,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        dump(payload, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    folder_path = join(abspath(dirname(__file__)), "..", "data", "cleaned_news")
    output_path = join(
        abspath(dirname(__file__)), "..", "data", "newscontent_tags_report.json"
    )

    findings, files_scanned, files_with_newscontent = iterate_cleaned_news(folder_path)
    print_report(findings, files_scanned, files_with_newscontent)
    export_report(findings, output_path, files_scanned, files_with_newscontent)
    print(f"Report exported to {output_path}")
