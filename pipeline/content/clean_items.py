import os
import sys
from json import dump, load
from os import listdir, makedirs
from os.path import abspath, dirname, join

# Paths come from the shared module, so this works for any
# content type; see pipeline/paths_root.py.

import os as _os, sys as _sys  # noqa: E402
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import _bootstrap  # noqa: F401,E402  -- every pipeline folder on sys.path
from paths_root import P  # noqa: E402


def load_replacement_map(report_path):
    with open(report_path, "r", encoding="utf-8") as f:
        report = load(f)

    replacements = {}
    for item in report["characters"]:
        if not item["normalize_recommended"]:
            continue

        replacement = item["ascii_replacement"]
        if replacement is None:
            replacement = ""

        replacements[item["character"]] = parse_replacement(replacement)

    return replacements


def parse_replacement(replacement):
    return (
        replacement.replace("\\n", "\n")
        .replace("\\r", "\r")
        .replace("\\t", "\t")
    )


def clean_string(text, replacements):
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    return text


def clean_object(obj, replacements):
    if isinstance(obj, str):
        return clean_string(obj, replacements)
    if isinstance(obj, dict):
        return {key: clean_object(value, replacements) for key, value in obj.items()}
    if isinstance(obj, list):
        return [clean_object(value, replacements) for value in obj]
    return obj


def count_replacements_in_string(text, replacements):
    counts = {}
    for char in replacements:
        count = text.count(char)
        if count:
            counts[char] = count
    return counts


def count_replacements_in_object(obj, replacements):
    totals = {}
    if isinstance(obj, str):
        for char, count in count_replacements_in_string(obj, replacements).items():
            totals[char] = totals.get(char, 0) + count
    elif isinstance(obj, dict):
        for value in obj.values():
            for char, count in count_replacements_in_object(value, replacements).items():
                totals[char] = totals.get(char, 0) + count
    elif isinstance(obj, list):
        for value in obj:
            for char, count in count_replacements_in_object(value, replacements).items():
                totals[char] = totals.get(char, 0) + count
    return totals


def clean_news_files(source_folder, output_folder, replacements):
    makedirs(output_folder, exist_ok=True)

    json_files = sorted(
        filename for filename in listdir(source_folder) if filename.endswith(".json")
    )

    total_replacements = {}
    files_changed = 0

    for filename in json_files:
        source_path = join(source_folder, filename)
        with open(source_path, "r", encoding="utf-8") as f:
            news_item = load(f)

        before_counts = count_replacements_in_object(news_item, replacements)
        cleaned_item = clean_object(news_item, replacements)

        output_path = join(output_folder, filename)
        with open(output_path, "w", encoding="utf-8", newline="\n") as f:
            dump(cleaned_item, f, indent=2, ensure_ascii=False)

        if before_counts:
            files_changed += 1
            for char, count in before_counts.items():
                total_replacements[char] = total_replacements.get(char, 0) + count

    return {
        "files_processed": len(json_files),
        "files_changed": files_changed,
        "replacements_by_character": total_replacements,
    }


def char_code(char):
    return f"\\u{ord(char):04x}"


def print_summary(replacements, stats):
    print(f"Loaded {len(replacements)} replacement rule(s) from unicode report")
    print()
    print("Replacement rules:")
    for char, replacement in replacements.items():
        print(f"  {char_code(char)} -> {replacement!r}")
    print()
    print(f"Processed {stats['files_processed']} file(s)")
    print(f"Updated {stats['files_changed']} file(s) containing normalized characters")
    print()

    if stats["replacements_by_character"]:
        print("Replacements applied:")
        for char, count in sorted(
            stats["replacements_by_character"].items(),
            key=lambda item: -item[1],
        ):
            print(f"  {char_code(char)}: {count:,}")
    else:
        print("No replacements were needed.")


if __name__ == "__main__":
    base_path = abspath(join(dirname(__file__), ".."))
    report_path = P.report("unicode_report.json")
    source_folder = P.RAW
    output_folder = P.CLEANED

    replacements = load_replacement_map(report_path)
    stats = clean_news_files(source_folder, output_folder, replacements)
    print_summary(replacements, stats)
    print(f"\nCleaned files saved to {output_folder}")
