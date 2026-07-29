from collections import Counter
from copy import deepcopy
from json import dump, load
from os import listdir, makedirs
from os.path import abspath, dirname, join
import sys

SCRIPTS_DIR = abspath(dirname(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from storyblok_richtext import html_to_storyblok_richtext, validate_document


def load_news_data(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        return load(f)


def convert_news_item(news_item):
    item = deepcopy(news_item)
    news_content = item.get("NewsContent")
    warnings = []

    if not isinstance(news_content, str) or not news_content.strip():
        item["NewsContent"] = {"type": "doc", "content": []}
        warnings.append("empty_news_content")
        return item, warnings, []

    try:
        result = html_to_storyblok_richtext(news_content)
        validation_errors = validate_document(result.document)
        warnings.extend(result.warnings)

        if validation_errors:
            item["NewsContent"] = None
            item["NewsContentRichtextError"] = "; ".join(validation_errors)
            return item, warnings, validation_errors

        item["NewsContent"] = result.document
        return item, warnings, []
    except Exception as exc:
        item["NewsContent"] = None
        item["NewsContentRichtextError"] = str(exc)
        return item, warnings, [str(exc)]


def categorize_warnings(warnings):
    categories = Counter()
    for warning in warnings:
        category = warning.split(":", 1)[0]
        categories[category] += 1
    return dict(categories)


def export_report(report, output_path):
    with open(output_path, "w", encoding="utf-8", newline="\n") as f:
        dump(report, f, indent=2, ensure_ascii=False)


def convert_news_files(source_folder, output_folder):
    makedirs(output_folder, exist_ok=True)

    json_files = sorted(
        filename for filename in listdir(source_folder) if filename.endswith(".json")
    )

    all_warnings = Counter()
    files_with_warnings = []
    conversion_failures = []
    empty_content_files = []
    iframe_files = []
    image_files = []
    relative_link_files = []

    for filename in json_files:
        source_path = join(source_folder, filename)
        news_item = load_news_data(source_path)
        converted_item, warnings, errors = convert_news_item(news_item)

        for warning in warnings:
            all_warnings[warning.split(":", 1)[0]] += 1

        if warnings:
            files_with_warnings.append({"file": filename, "warnings": warnings})

        if "empty_news_content" in warnings:
            empty_content_files.append(filename)

        if any(w.startswith("iframe_embedded:") for w in warnings):
            iframe_files.append(filename)

        if any(w.startswith("sharepoint_image:") for w in warnings):
            image_files.append(filename)

        if any(w.startswith("relative_link:") for w in warnings):
            relative_link_files.append(filename)

        if errors or converted_item.get("NewsContentRichtextError"):
            conversion_failures.append(
                {
                    "file": filename,
                    "error": converted_item.get("NewsContentRichtextError") or "; ".join(errors),
                    "warnings": warnings,
                }
            )

        output_path = join(output_folder, filename)
        with open(output_path, "w", encoding="utf-8", newline="\n") as f:
            dump(converted_item, f, indent=2, ensure_ascii=False)

    return {
        "summary": {
            "source_folder": source_folder,
            "output_folder": output_folder,
            "files_processed": len(json_files),
            "conversion_failures": len(conversion_failures),
            "files_with_warnings": len(files_with_warnings),
            "empty_content_files": len(empty_content_files),
            "iframe_files": len(iframe_files),
            "image_files": len(image_files),
            "relative_link_files": len(relative_link_files),
            "warning_categories": dict(all_warnings),
        },
        "conversion_failures": conversion_failures,
        "files_with_iframes": sorted(iframe_files),
        "files_with_sharepoint_images": sorted(image_files),
        "files_with_relative_links": sorted(relative_link_files),
        "files_with_warnings": files_with_warnings,
    }


def print_report(report):
    summary = report["summary"]
    print("Rich text conversion summary")
    print("=" * 72)
    print(f"Files processed: {summary['files_processed']:,}")
    print(f"Conversion failures: {summary['conversion_failures']:,}")
    print(f"Files with warnings: {summary['files_with_warnings']:,}")
    print(f"Empty content files: {summary['empty_content_files']:,}")
    print(f"Files with removed iframes: {summary['iframe_files']:,}")
    print(f"Files with SharePoint images: {summary['image_files']:,}")
    print(f"Files with relative links: {summary['relative_link_files']:,}")

    if summary["warning_categories"]:
        print()
        print("Warning categories:")
        for category, count in sorted(
            summary["warning_categories"].items(), key=lambda item: (-item[1], item[0])
        ):
            print(f"  {category}: {count:,}")

    if report["conversion_failures"]:
        print()
        print("Conversion failures:")
        for failure in report["conversion_failures"][:10]:
            print(f"  - {failure['file']}: {failure['error']}")
    print()


if __name__ == "__main__":
    base_path = abspath(join(dirname(__file__), ".."))
    source_folder = join(base_path, "data", "normalized_news")
    output_folder = join(base_path, "data", "storyblok_news")
    report_path = join(base_path, "data", "richtext_conversion_report.json")

    report = convert_news_files(source_folder, output_folder)
    print_report(report)
    export_report(report, report_path)
    print(f"Report exported to {report_path}")
