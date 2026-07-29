import argparse
import subprocess
import sys
from json import load
from os import listdir
from os.path import abspath, dirname, exists, isdir, isfile, join

SCRIPTS_DIR = abspath(dirname(__file__))
BASE_PATH = abspath(join(SCRIPTS_DIR, ".."))
DATA_PATH = join(BASE_PATH, "data")

NEWS_JSON_PATH = join(DATA_PATH, "news.json")
NEWS_FOLDER_PATH = join(DATA_PATH, "news")
UNICODE_REPORT_PATH = join(DATA_PATH, "unicode_report.json")
CLEANED_NEWS_FOLDER_PATH = join(DATA_PATH, "cleaned_news")
NEWSCONTENT_TAGS_REPORT_PATH = join(DATA_PATH, "newscontent_tags_report.json")
NORMALIZED_NEWS_FOLDER_PATH = join(DATA_PATH, "normalized_news")
HTML_NORMALIZATION_REPORT_PATH = join(DATA_PATH, "html_normalization_report.json")
STORYBLOK_NEWS_FOLDER_PATH = join(DATA_PATH, "storyblok_news")
RICHTEXT_CONVERSION_REPORT_PATH = join(DATA_PATH, "richtext_conversion_report.json")
STORYBLOK_LINK_MAP_PATH = join(DATA_PATH, "storyblok_link_map.json")
STORYBLOK_ASSET_CATALOG_PATH = join(DATA_PATH, "storyblok_asset_catalog.json")
STORYBLOK_ASSET_MAP_PATH = join(DATA_PATH, "storyblok_asset_map.json")
STORYBLOK_NEWS_ENHANCED_FOLDER_PATH = join(DATA_PATH, "storyblok_news_enhanced")
STORYBLOK_ENHANCE_REPORT_PATH = join(DATA_PATH, "storyblok_enhance_report.json")
STORYBLOK_STORIES_FOLDER_PATH = join(DATA_PATH, "storyblok_stories")
STORYBLOK_STORIES_REPORT_PATH = join(DATA_PATH, "storyblok_stories_report.json")
STORYBLOK_MEDIA_INJECT_REPORT_PATH = join(DATA_PATH, "storyblok_media_inject_report.json")
NEWS_MEDIA_REPORT_PATH = join(DATA_PATH, "news_media_report.json")
STORYBLOK_MEDIA_MAP_PATH = join(DATA_PATH, "storyblok_media_map.json")
RICHTEXT_MEDIA_CATALOG_PATH = join(DATA_PATH, "richtext_media_catalog.json")
RICHTEXT_MEDIA_MAP_PATH = join(DATA_PATH, "richtext_media_map.json")
RICHTEXT_MEDIA_DOWNLOAD_REPORT_PATH = join(DATA_PATH, "richtext_media_download_report.json")
RICHTEXT_MEDIA_VERIFY_REPORT_PATH = join(DATA_PATH, "richtext_media_verify_report.json")
RICHTEXT_MEDIA_ATTACH_REPORT_PATH = join(DATA_PATH, "richtext_media_attach_report.json")
STORY_MEDIA_CLASSIFICATION_REPORT_PATH = join(DATA_PATH, "story_media_classification_report.json")
STORY_MEDIA_INDEX_PATH = join(DATA_PATH, "story_media_index.json")
STORYBLOK_METADATA_REPORT_PATH = join(DATA_PATH, "storyblok_metadata_report.json")
STORYBLOK_IMPORT_REPORT_PATH = join(DATA_PATH, "storyblok_import_report.json")
STORYBLOK_VIEWER_CONSTANTS_PATH = join(BASE_PATH, "storyblok-viewer", "src", "constants")
METADATA_CSV_PATH = join(BASE_PATH, "assets", "News", "Metadata.csv")
NEWS_MEDIA_DIR = join(BASE_PATH, "assets", "News", "media")

PIPELINE_STEPS = [
    {
        "name": "extract-news",
        "script": "analyze_news.py",
        "description": "Split data/news.json into individual files in data/news/",
        "requires": [],
        "produces": [NEWS_FOLDER_PATH],
    },
    {
        "name": "analyze-unicode",
        "script": "analyze_unicode.py",
        "description": "Scan data/news/ and write data/unicode_report.json",
        "requires": [NEWS_FOLDER_PATH],
        "produces": [UNICODE_REPORT_PATH],
    },
    {
        "name": "clean-news",
        "script": "clean_news.py",
        "description": "Normalize Unicode in data/news/ using data/unicode_report.json",
        "requires": [NEWS_FOLDER_PATH, UNICODE_REPORT_PATH],
        "produces": [CLEANED_NEWS_FOLDER_PATH],
    },
    {
        "name": "analyze-news-tags",
        "script": "analyze_news_tags.py",
        "description": "Inventory HTML tags in cleaned NewsContent fields",
        "requires": [CLEANED_NEWS_FOLDER_PATH],
        "produces": [NEWSCONTENT_TAGS_REPORT_PATH],
    },
    {
        "name": "normalize-html",
        "script": "normalize_news_html.py",
        "description": "Normalize SharePoint HTML in data/cleaned_news/ to semantic HTML",
        "requires": [CLEANED_NEWS_FOLDER_PATH],
        "produces": [NORMALIZED_NEWS_FOLDER_PATH, HTML_NORMALIZATION_REPORT_PATH],
    },
    {
        "name": "convert-richtext",
        "script": "convert_news_richtext.py",
        "description": "Convert normalized NewsContent HTML to Storyblok rich text JSON",
        "requires": [NORMALIZED_NEWS_FOLDER_PATH],
        "produces": [STORYBLOK_NEWS_FOLDER_PATH, RICHTEXT_CONVERSION_REPORT_PATH],
    },
    {
        "name": "build-link-map",
        "script": "build_link_map.py",
        "description": "Build SharePoint URL to Storyblok story lookup map",
        "requires": [CLEANED_NEWS_FOLDER_PATH],
        "produces": [STORYBLOK_LINK_MAP_PATH],
    },
    {
        "name": "catalog-assets",
        "script": "catalog_assets.py",
        "description": "Catalog SharePoint images referenced in news content",
        "requires": [CLEANED_NEWS_FOLDER_PATH, STORYBLOK_NEWS_FOLDER_PATH],
        "produces": [STORYBLOK_ASSET_CATALOG_PATH, STORYBLOK_ASSET_MAP_PATH],
    },
    {
        "name": "upload-assets",
        "script": "upload_assets.py",
        "description": "Upload cataloged assets to Storyblok (requires API credentials)",
        "requires": [STORYBLOK_ASSET_CATALOG_PATH],
        "produces": [STORYBLOK_ASSET_CATALOG_PATH, STORYBLOK_ASSET_MAP_PATH],
    },
    {
        "name": "enhance-richtext",
        "script": "enhance_storyblok_news.py",
        "description": "Resolve internal story links and asset URLs in rich text JSON",
        "requires": [
            STORYBLOK_NEWS_FOLDER_PATH,
            STORYBLOK_LINK_MAP_PATH,
            STORYBLOK_ASSET_MAP_PATH,
        ],
        "produces": [STORYBLOK_NEWS_ENHANCED_FOLDER_PATH, STORYBLOK_ENHANCE_REPORT_PATH],
    },
    {
        "name": "build-stories",
        "script": "build_storyblok_stories.py",
        "description": "Build full Storyblok story payloads including PullQuote handling",
        "requires": [STORYBLOK_NEWS_ENHANCED_FOLDER_PATH],
        "produces": [STORYBLOK_STORIES_FOLDER_PATH, STORYBLOK_STORIES_REPORT_PATH],
    },
    {
        "name": "validate-news-media",
        "script": "validate_news_media.py",
        "description": "Validate Metadata.csv references against assets/News/media",
        "requires": [METADATA_CSV_PATH, NEWS_MEDIA_DIR],
        "produces": [NEWS_MEDIA_REPORT_PATH],
    },
    {
        "name": "map-storyblok-media",
        "script": "map_storyblok_media.py",
        "description": "Map storyblok_stories to assets/News/media via Metadata.csv",
        "requires": [STORYBLOK_STORIES_FOLDER_PATH, METADATA_CSV_PATH, NEWS_MEDIA_DIR],
        "produces": [STORYBLOK_MEDIA_MAP_PATH],
    },
    {
        "name": "inject-story-media",
        "script": "inject_story_media.py",
        "description": "Inject Metadata.csv media bloks into storyblok_stories before body",
        "requires": [STORYBLOK_STORIES_FOLDER_PATH, METADATA_CSV_PATH],
        "produces": [STORYBLOK_MEDIA_INJECT_REPORT_PATH],
    },
    {
        "name": "catalog-richtext-media",
        "script": "catalog_richtext_media.py",
        "description": "Catalog PDF/image/media links in rich text missing from assets/News/media",
        "requires": [STORYBLOK_STORIES_FOLDER_PATH, NORMALIZED_NEWS_FOLDER_PATH, NEWS_MEDIA_DIR],
        "produces": [RICHTEXT_MEDIA_CATALOG_PATH],
    },
    {
        "name": "download-richtext-media",
        "script": "download_richtext_media.py",
        "description": "Download missing rich-text media into assets/News/media and update story mappings",
        "requires": [RICHTEXT_MEDIA_CATALOG_PATH, STORYBLOK_STORIES_FOLDER_PATH, NEWS_MEDIA_DIR],
        "produces": [
            RICHTEXT_MEDIA_CATALOG_PATH,
            RICHTEXT_MEDIA_MAP_PATH,
            RICHTEXT_MEDIA_DOWNLOAD_REPORT_PATH,
        ],
    },
    {
        "name": "verify-richtext-media",
        "script": "verify_richtext_media.py",
        "description": "Verify rich-text media downloads and report downloaded vs missing assets",
        "requires": [STORYBLOK_STORIES_FOLDER_PATH, NORMALIZED_NEWS_FOLDER_PATH, NEWS_MEDIA_DIR],
        "produces": [RICHTEXT_MEDIA_VERIFY_REPORT_PATH],
    },
    {
        "name": "attach-richtext-media",
        "script": "attach_richtext_media.py",
        "description": "Attach downloaded rich-text media into storyblok_stories body links and media bloks",
        "requires": [STORYBLOK_STORIES_FOLDER_PATH, NEWS_MEDIA_DIR],
        "produces": [RICHTEXT_MEDIA_ATTACH_REPORT_PATH],
    },
    {
        "name": "classify-story-media",
        "script": "story_media_classification.py",
        "description": "Classify stories by thumbnail, GIF, video file, and embedded video media",
        "requires": [STORYBLOK_STORIES_FOLDER_PATH],
        "produces": [STORY_MEDIA_CLASSIFICATION_REPORT_PATH, STORY_MEDIA_INDEX_PATH],
    },
    {
        "name": "validate-metadata",
        "script": "validate_storyblok_metadata.py",
        "description": "Validate SharePoint metadata coverage in storyblok_stories",
        "requires": [CLEANED_NEWS_FOLDER_PATH, STORYBLOK_STORIES_FOLDER_PATH],
        "produces": [STORYBLOK_METADATA_REPORT_PATH],
    },
    {
        "name": "extract-viewer-filters",
        "script": "extract_storyblok_filter_constants.py",
        "description": "Extract tags, authors, publishers, and content writers for storyblok-viewer filters",
        "requires": [STORYBLOK_STORIES_FOLDER_PATH],
        "produces": [
            join(STORYBLOK_VIEWER_CONSTANTS_PATH, "tags", "index.ts"),
            join(STORYBLOK_VIEWER_CONSTANTS_PATH, "authors", "index.ts"),
            join(STORYBLOK_VIEWER_CONSTANTS_PATH, "publishers", "index.ts"),
            join(STORYBLOK_VIEWER_CONSTANTS_PATH, "contentWriters", "index.ts"),
        ],
    },
    {
        "name": "import-storyblok",
        "script": "import_storyblok.py",
        "description": "Import built stories to Storyblok via Management API",
        "requires": [STORYBLOK_STORIES_FOLDER_PATH],
        "produces": [STORYBLOK_IMPORT_REPORT_PATH],
    },
]


def json_files_in(folder_path):
    if not isdir(folder_path):
        return []
    return [name for name in listdir(folder_path) if name.endswith(".json")]


def validate_news_json():
    errors = []
    if not isfile(NEWS_JSON_PATH):
        errors.append(f"Missing source file: {relative_data_path(NEWS_JSON_PATH)}")
        return errors

    try:
        with open(NEWS_JSON_PATH, "r", encoding="utf-8") as f:
            data = load(f)
    except OSError as exc:
        errors.append(f"Could not read {NEWS_JSON_PATH}: {exc}")
        return errors
    except ValueError as exc:
        errors.append(f"Invalid JSON in {NEWS_JSON_PATH}: {exc}")
        return errors

    if isinstance(data, dict) and "value" in data:
        if not isinstance(data["value"], list):
            errors.append(f"{NEWS_JSON_PATH} must contain a list in the 'value' key.")
        elif not data["value"]:
            errors.append(f"{NEWS_JSON_PATH} contains an empty 'value' list.")
    elif isinstance(data, list):
        if not data:
            errors.append(f"{NEWS_JSON_PATH} contains an empty list.")
    else:
        errors.append(
            f"{NEWS_JSON_PATH} must be an OData object with 'value' or a list of news items."
        )

    return errors


def validate_news_folder():
    errors = []
    json_files = json_files_in(NEWS_FOLDER_PATH)
    if not isdir(NEWS_FOLDER_PATH):
        errors.append(f"Missing folder: {relative_data_path(NEWS_FOLDER_PATH)}")
    elif not json_files:
        errors.append(
            f"No JSON files found in {relative_data_path(NEWS_FOLDER_PATH)}. "
            "Run extract-news first."
        )
    return errors


def validate_unicode_report():
    errors = []
    if not isfile(UNICODE_REPORT_PATH):
        errors.append(
            f"Missing report: {relative_data_path(UNICODE_REPORT_PATH)}. "
            "Run analyze-unicode first."
        )
        return errors

    try:
        with open(UNICODE_REPORT_PATH, "r", encoding="utf-8") as f:
            report = load(f)
    except OSError as exc:
        errors.append(f"Could not read {UNICODE_REPORT_PATH}: {exc}")
        return errors
    except ValueError as exc:
        errors.append(f"Invalid JSON in {UNICODE_REPORT_PATH}: {exc}")
        return errors

    if "characters" not in report or not isinstance(report["characters"], list):
        errors.append(
            f"{UNICODE_REPORT_PATH} is missing a 'characters' list. "
            "Run analyze-unicode again."
        )
    elif not report["characters"]:
        errors.append(f"{UNICODE_REPORT_PATH} contains no character entries.")

    return errors


def validate_cleaned_news_folder():
    errors = []
    json_files = json_files_in(CLEANED_NEWS_FOLDER_PATH)
    if not isdir(CLEANED_NEWS_FOLDER_PATH):
        errors.append(f"Missing folder: {relative_data_path(CLEANED_NEWS_FOLDER_PATH)}")
    elif not json_files:
        errors.append(
            f"No JSON files found in {relative_data_path(CLEANED_NEWS_FOLDER_PATH)}. "
            "Run clean-news first."
        )
    return errors


def validate_normalized_news_folder():
    errors = []
    json_files = json_files_in(NORMALIZED_NEWS_FOLDER_PATH)
    if not isdir(NORMALIZED_NEWS_FOLDER_PATH):
        errors.append(f"Missing folder: {relative_data_path(NORMALIZED_NEWS_FOLDER_PATH)}")
    elif not json_files:
        errors.append(
            f"No JSON files found in {relative_data_path(NORMALIZED_NEWS_FOLDER_PATH)}. "
            "Run normalize-html first."
        )
    return errors


def validate_storyblok_news_folder():
    errors = []
    json_files = json_files_in(STORYBLOK_NEWS_FOLDER_PATH)
    if not isdir(STORYBLOK_NEWS_FOLDER_PATH):
        errors.append(f"Missing folder: {relative_data_path(STORYBLOK_NEWS_FOLDER_PATH)}")
    elif not json_files:
        errors.append(
            f"No JSON files found in {relative_data_path(STORYBLOK_NEWS_FOLDER_PATH)}. "
            "Run convert-richtext first."
        )
    return errors


def validate_storyblok_news_enhanced_folder():
    errors = []
    json_files = json_files_in(STORYBLOK_NEWS_ENHANCED_FOLDER_PATH)
    if not isdir(STORYBLOK_NEWS_ENHANCED_FOLDER_PATH):
        errors.append(
            f"Missing folder: {relative_data_path(STORYBLOK_NEWS_ENHANCED_FOLDER_PATH)}"
        )
    elif not json_files:
        errors.append(
            f"No JSON files found in {relative_data_path(STORYBLOK_NEWS_ENHANCED_FOLDER_PATH)}. "
            "Run enhance-richtext first."
        )
    return errors


def validate_requirement(path):
    if path == NEWS_JSON_PATH:
        return validate_news_json()
    if path == NEWS_FOLDER_PATH:
        return validate_news_folder()
    if path == UNICODE_REPORT_PATH:
        return validate_unicode_report()
    if path == CLEANED_NEWS_FOLDER_PATH:
        return validate_cleaned_news_folder()
    if path == NORMALIZED_NEWS_FOLDER_PATH:
        return validate_normalized_news_folder()
    if path == STORYBLOK_NEWS_FOLDER_PATH:
        return validate_storyblok_news_folder()
    if path == STORYBLOK_NEWS_ENHANCED_FOLDER_PATH:
        return validate_storyblok_news_enhanced_folder()
    if not exists(path):
        return [f"Missing required path: {path}"]
    return []


def validate_step(step_name):
    step = get_step(step_name)
    errors = []

    for requirement in step["requires"]:
        errors.extend(validate_requirement(requirement))

    if step_name == "extract-news":
        errors.extend(validate_news_json())

    return errors


def get_step(step_name):
    for step in PIPELINE_STEPS:
        if step["name"] == step_name:
            return step
    raise ValueError(f"Unknown step: {step_name}")


def prerequisite_commands(step_name):
    step_index = next(i for i, step in enumerate(PIPELINE_STEPS) if step["name"] == step_name)
    return [
        f"python scripts/{PIPELINE_STEPS[i]['script']} "
        f"or python scripts/run_pipeline.py {PIPELINE_STEPS[i]['name']}"
        for i in range(step_index)
    ]


def relative_data_path(path):
    if path.startswith(DATA_PATH):
        return join("data", path[len(DATA_PATH) + 1 :])
    return path


def print_pipeline_overview():
    print("News processing pipeline")
    print("=" * 72)
    for index, step in enumerate(PIPELINE_STEPS, start=1):
        print(f"{index}. {step['name']}")
        print(f"   {step['description']}")
        print(f"   Script: scripts/{step['script']}")
        if step["requires"]:
            print(
                "   Requires: "
                + ", ".join(relative_data_path(path) for path in step["requires"])
            )
        print(
            "   Produces: "
            + ", ".join(relative_data_path(path) for path in step["produces"])
        )
        print()


def print_status():
    print_pipeline_overview()
    print("Current status")
    print("=" * 72)

    checks = [
        ("news.json", validate_news_json()),
        ("news/", validate_news_folder()),
        ("unicode_report.json", validate_unicode_report()),
        (
            "cleaned_news/",
            validate_cleaned_news_folder(),
        ),
        (
            "newscontent_tags_report.json",
            [] if isfile(NEWSCONTENT_TAGS_REPORT_PATH) else [
                f"Missing report: {relative_data_path(NEWSCONTENT_TAGS_REPORT_PATH)}"
            ],
        ),
        (
            "normalized_news/",
            validate_normalized_news_folder(),
        ),
        (
            "storyblok_news/",
            validate_storyblok_news_folder(),
        ),
        (
            "storyblok_link_map.json",
            [] if isfile(STORYBLOK_LINK_MAP_PATH) else [
                f"Missing report: {relative_data_path(STORYBLOK_LINK_MAP_PATH)}"
            ],
        ),
        (
            "storyblok_asset_catalog.json",
            [] if isfile(STORYBLOK_ASSET_CATALOG_PATH) else [
                f"Missing report: {relative_data_path(STORYBLOK_ASSET_CATALOG_PATH)}"
            ],
        ),
        (
            "storyblok_news_enhanced/",
            validate_storyblok_news_enhanced_folder(),
        ),
        (
            "storyblok_stories/",
            [] if isdir(STORYBLOK_STORIES_FOLDER_PATH) and json_files_in(STORYBLOK_STORIES_FOLDER_PATH) else [
                f"Missing or empty folder: {relative_data_path(STORYBLOK_STORIES_FOLDER_PATH)}"
            ],
        ),
        (
            "news_media_report.json",
            [] if isfile(NEWS_MEDIA_REPORT_PATH) else [
                f"Missing report: {relative_data_path(NEWS_MEDIA_REPORT_PATH)}"
            ],
        ),
        (
            "storyblok_media_map.json",
            [] if isfile(STORYBLOK_MEDIA_MAP_PATH) else [
                f"Missing report: {relative_data_path(STORYBLOK_MEDIA_MAP_PATH)}"
            ],
        ),
        (
            "storyblok_media_inject_report.json",
            [] if isfile(STORYBLOK_MEDIA_INJECT_REPORT_PATH) else [
                f"Missing report: {relative_data_path(STORYBLOK_MEDIA_INJECT_REPORT_PATH)}"
            ],
        ),
        (
            "richtext_media_catalog.json",
            [] if isfile(RICHTEXT_MEDIA_CATALOG_PATH) else [
                f"Missing report: {relative_data_path(RICHTEXT_MEDIA_CATALOG_PATH)}"
            ],
        ),
        (
            "richtext_media_map.json",
            [] if isfile(RICHTEXT_MEDIA_MAP_PATH) else [
                f"Missing report: {relative_data_path(RICHTEXT_MEDIA_MAP_PATH)}"
            ],
        ),
        (
            "richtext_media_verify_report.json",
            [] if isfile(RICHTEXT_MEDIA_VERIFY_REPORT_PATH) else [
                f"Missing report: {relative_data_path(RICHTEXT_MEDIA_VERIFY_REPORT_PATH)}"
            ],
        ),
        (
            "richtext_media_attach_report.json",
            [] if isfile(RICHTEXT_MEDIA_ATTACH_REPORT_PATH) else [
                f"Missing report: {relative_data_path(RICHTEXT_MEDIA_ATTACH_REPORT_PATH)}"
            ],
        ),
        (
            "storyblok_metadata_report.json",
            [] if isfile(STORYBLOK_METADATA_REPORT_PATH) else [
                f"Missing report: {relative_data_path(STORYBLOK_METADATA_REPORT_PATH)}"
            ],
        ),
        (
            "storyblok-viewer filter constants",
            [] if all(
                isfile(join(STORYBLOK_VIEWER_CONSTANTS_PATH, folder, "index.ts"))
                for folder in ("tags", "authors", "publishers", "contentWriters")
            ) else [
                "Missing one or more files in storyblok-viewer/src/constants/"
            ],
        ),
    ]

    for label, errors in checks:
        if errors:
            print(f"[missing] {label}")
            for error in errors:
                print(f"  - {error}")
        else:
            if label.endswith("/"):
                folder_path = {
                    "news/": NEWS_FOLDER_PATH,
                    "cleaned_news/": CLEANED_NEWS_FOLDER_PATH,
                    "normalized_news/": NORMALIZED_NEWS_FOLDER_PATH,
                    "storyblok_news/": STORYBLOK_NEWS_FOLDER_PATH,
                    "storyblok_news_enhanced/": STORYBLOK_NEWS_ENHANCED_FOLDER_PATH,
                    "storyblok_stories/": STORYBLOK_STORIES_FOLDER_PATH,
                }[label]
                print(f"[ready]   {label} ({len(json_files_in(folder_path))} JSON files)")
            else:
                print(f"[ready]   {label}")

    print()
    print("Runnable steps")
    print("-" * 72)
    for step in PIPELINE_STEPS:
        errors = validate_step(step["name"])
        if errors:
            print(f"[blocked] {step['name']}")
            for error in errors:
                print(f"  - {error}")
            if prerequisite_commands(step["name"]):
                print("  Run these first:")
                for command in prerequisite_commands(step["name"]):
                    print(f"    {command}")
        else:
            print(f"[ready]   {step['name']}")
    print()


def fail_with_prerequisite_message(step_name, errors):
    print(f"Cannot run '{step_name}'.", file=sys.stderr)
    print(file=sys.stderr)
    print("Missing prerequisites:", file=sys.stderr)
    for error in errors:
        print(f"  - {error}", file=sys.stderr)

    previous = prerequisite_commands(step_name)
    if previous:
        print(file=sys.stderr)
        print("Required pipeline order:", file=sys.stderr)
        for index, step in enumerate(PIPELINE_STEPS, start=1):
            print(f"  {index}. {step['name']}", file=sys.stderr)
        print(file=sys.stderr)
        print("Run these commands first:", file=sys.stderr)
        for command in previous:
            print(f"  {command}", file=sys.stderr)

    sys.exit(1)


def run_script(script_name):
    script_path = join(SCRIPTS_DIR, script_name)
    python_executable = sys.executable
    venv_python = join(BASE_PATH, ".venv", "bin", "python")
    if exists(venv_python):
        python_executable = venv_python

    print(f"Running {script_name}")
    print("-" * 72)
    result = subprocess.run([python_executable, script_path], cwd=BASE_PATH)
    print("-" * 72)
    if result.returncode != 0:
        print(f"{script_name} failed with exit code {result.returncode}", file=sys.stderr)
        sys.exit(result.returncode)
    print()


def run_step(step_name):
    errors = validate_step(step_name)
    if errors:
        fail_with_prerequisite_message(step_name, errors)

    step = get_step(step_name)
    run_script(step["script"])


def run_all():
    for step in PIPELINE_STEPS:
        run_step(step["name"])
    print("Pipeline completed successfully.")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Run the AKU news processing pipeline in the required order."
    )
    parser.add_argument(
        "command",
        choices=[step["name"] for step in PIPELINE_STEPS] + ["all", "status"],
        help=(
            "Pipeline command. Use 'status' to inspect prerequisites, or 'all' "
            "to run every step in order."
        ),
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "status":
        print_status()
        return

    if args.command == "all":
        run_all()
        return

    run_step(args.command)


if __name__ == "__main__":
    main()
