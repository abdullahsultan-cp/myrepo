from collections import Counter
from copy import deepcopy
from html import unescape
from json import dump, load
from os import listdir, makedirs
from os.path import abspath, dirname, join
import re

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from storyblok_embeds import embed_placeholder_tag, detect_embed_type

PRESENTATION_ATTRS = {
    "class",
    "style",
    "dir",
    "face",
    "color",
    "id",
    "width",
    "height",
    "cellspacing",
    "cellpadding",
    "border",
    "align",
    "valign",
    "bgcolor",
    "unselectable",
}

DATA_ATTR_PREFIX = "data-"
MSO_COMMENT_PATTERN = re.compile(r"\[if .*?\].*?\[endif\]", re.IGNORECASE | re.DOTALL)
EXTERNAL_CLASS_PATTERN = re.compile(r"^ExternalClass", re.IGNORECASE)


def tag_attr(tag, key, default=None):
    if not isinstance(tag, Tag):
        return default
    attrs = tag.attrs
    if not isinstance(attrs, dict):
        return default
    return attrs.get(key, default)


def load_news_data(file_path):
    with open(file_path, "r") as f:
        return load(f)


def is_external_class_div(tag):
    if not isinstance(tag, Tag) or tag.name.lower() != "div":
        return False
    class_value = tag_attr(tag, "class") or []
    if isinstance(class_value, str):
        class_value = class_value.split()
    return any(EXTERNAL_CLASS_PATTERN.match(value) for value in class_value)


def contains_embed_placeholder(tag):
    if not isinstance(tag, Tag):
        return False
    if tag_attr(tag, "data-storyblok-embed"):
        return True
    return tag.find(attrs={"data-storyblok-embed": True}) is not None


def is_spacing_div(tag):
    if not isinstance(tag, Tag) or tag.name.lower() != "div":
        return False
    meaningful_children = [
        child
        for child in tag.children
        if not (isinstance(child, NavigableString) and not str(child).strip())
    ]
    if len(meaningful_children) != 1:
        return False
    child = meaningful_children[0]
    return isinstance(child, Tag) and child.name.lower() == "br"


def is_empty_div(tag):
    if not isinstance(tag, Tag) or tag.name.lower() != "div":
        return False
    if contains_embed_placeholder(tag):
        return False
    return not tag.get_text(strip=True) and not tag.find(["img", "iframe", "table", "ul", "ol"])


def strip_presentation_attrs(tag):
    if not isinstance(tag, Tag):
        return
    if not isinstance(tag.attrs, dict):
        tag.attrs = {}
    attrs_to_remove = []
    for attr in list(tag.attrs):
        attr_lower = attr.lower()
        if attr_lower in PRESENTATION_ATTRS or attr_lower.startswith(DATA_ATTR_PREFIX):
            attrs_to_remove.append(attr)
    for attr in attrs_to_remove:
        del tag[attr]


def rename_tag(tag, new_name):
    tag.name = new_name


def unwrap_tag(tag):
    tag.unwrap()


def normalize_inline_tags(soup):
    for tag in soup.find_all(["b", "i"]):
        rename_tag(tag, "strong" if tag.name.lower() == "b" else "em")

    for tag in soup.find_all("span"):
        if tag.get_text(strip=True) or tag.find(["a", "strong", "em", "br", "sup", "sub"]):
            unwrap_tag(tag)
        else:
            tag.decompose()

    for tag in soup.find_all("font"):
        if tag.get_text(strip=True) or tag.find(["a", "strong", "em", "br"]):
            unwrap_tag(tag)
        else:
            tag.decompose()


def replace_iframe(tag):
    src = (tag_attr(tag, "src") or "").strip()
    src = unescape(src)
    embed_type = detect_embed_type(src)
    placeholder = BeautifulSoup(embed_placeholder_tag(embed_type, src), "html5lib")
    replacement = placeholder.body.find("div") if placeholder.body else None
    if replacement:
        tag.replace_with(replacement)
    else:
        tag.decompose()
    return src


def remove_style_tags(soup):
    removed = 0
    for tag in soup.find_all("style"):
        tag.decompose()
        removed += 1
    return removed


def remove_mso_comments(html):
    return MSO_COMMENT_PATTERN.sub("", html)


def hoist_embed_placeholder(tag):
    embed = tag.find(attrs={"data-storyblok-embed": True})
    if embed is None:
        return False
    embed.extract()
    tag.replace_with(embed)
    return True


def convert_div_structure(soup):
    converted = 0
    skipped_spacing = 0
    embed_wrappers_hoisted = 0

    for tag in list(soup.find_all("div")):
        if tag_attr(tag, "data-storyblok-embed"):
            continue
        if contains_embed_placeholder(tag):
            if hoist_embed_placeholder(tag):
                embed_wrappers_hoisted += 1
            continue
        if is_spacing_div(tag) or is_empty_div(tag):
            tag.decompose()
            skipped_spacing += 1
            continue

        rename_tag(tag, "p")
        converted += 1

    return converted, skipped_spacing, embed_wrappers_hoisted


def unwrap_external_class_root(soup):
    unwrapped = 0
    while True:
        root_divs = [
            child
            for child in soup.children
            if isinstance(child, Tag) and child.name.lower() == "div" and is_external_class_div(child)
        ]
        if not root_divs:
            break
        for tag in root_divs:
            tag.unwrap()
            unwrapped += 1
    return unwrapped


def normalize_news_content_html(html):
    stats = Counter()
    warnings = []

    if not isinstance(html, str) or not html.strip():
        return html, stats, warnings

    html = remove_mso_comments(html)
    html = unescape(html)
    soup = BeautifulSoup(f"<body>{html}</body>", "html5lib")
    body = soup.body or soup

    stats["external_class_unwrapped"] = unwrap_external_class_root(body)

    iframe_sources = []
    for iframe in list(body.find_all("iframe")):
        iframe_sources.append(replace_iframe(iframe))
    stats["iframes_replaced"] = len(iframe_sources)
    if iframe_sources:
        warnings.extend(f"iframe_placeholder:{src}" for src in iframe_sources if src)

    stats["style_tags_removed"] = remove_style_tags(body)
    if stats["style_tags_removed"]:
        warnings.append(f"style_tags_removed:{stats['style_tags_removed']}")

    converted, skipped_spacing, embed_wrappers_hoisted = convert_div_structure(body)
    stats["divs_converted_to_p"] = converted
    stats["spacing_divs_removed"] = skipped_spacing
    stats["embed_wrappers_hoisted"] = embed_wrappers_hoisted

    normalize_inline_tags(body)
    stats["inline_tags_normalized"] = 1

    for tag in body.find_all(True):
        if tag_attr(tag, "data-storyblok-embed"):
            continue
        strip_presentation_attrs(tag)

    normalized_html = "".join(str(child) for child in body.children).strip()
    return normalized_html, stats, warnings


def normalize_news_item(news_item):
    item = deepcopy(news_item)
    news_content = item.get("NewsContent")
    if not isinstance(news_content, str) or not news_content.strip():
        return item, Counter(), []

    normalized_html, stats, warnings = normalize_news_content_html(news_content)
    item["NewsContent"] = normalized_html
    return item, stats, warnings


def aggregate_stats(counter, stats):
    counter.update(stats)


def export_report(summary, output_path):
    with open(output_path, "w") as f:
        dump(summary, f, indent=2, ensure_ascii=False)


def normalize_news_files(source_folder, output_folder):
    makedirs(output_folder, exist_ok=True)

    json_files = sorted(
        filename for filename in listdir(source_folder) if filename.endswith(".json")
    )

    totals = Counter()
    files_with_iframes = []
    files_with_styles = []
    files_with_warnings = []
    parse_failures = []

    for filename in json_files:
        source_path = join(source_folder, filename)
        try:
            news_item = load_news_data(source_path)
            normalized_item, stats, warnings = normalize_news_item(news_item)
        except Exception as exc:
            parse_failures.append({"file": filename, "error": str(exc)})
            continue

        aggregate_stats(totals, stats)
        if stats.get("iframes_replaced"):
            files_with_iframes.append(filename)
        if stats.get("style_tags_removed"):
            files_with_styles.append(filename)
        if warnings:
            files_with_warnings.append({"file": filename, "warnings": warnings})

        output_path = join(output_folder, filename)
        with open(output_path, "w") as f:
            dump(normalized_item, f, indent=2, ensure_ascii=False)

    return {
        "summary": {
            "source_folder": source_folder,
            "output_folder": output_folder,
            "files_processed": len(json_files) - len(parse_failures),
            "files_failed": len(parse_failures),
            "totals": dict(totals),
            "files_with_iframes": sorted(files_with_iframes),
            "files_with_styles": sorted(files_with_styles),
            "files_with_warnings_count": len(files_with_warnings),
        },
        "files_with_warnings": files_with_warnings,
        "parse_failures": parse_failures,
    }


def print_report(report):
    summary = report["summary"]
    print("HTML normalization summary")
    print("=" * 72)
    print(f"Files processed: {summary['files_processed']:,}")
    print(f"Files failed: {summary['files_failed']:,}")
    print(f"ExternalClass wrappers removed: {summary['totals'].get('external_class_unwrapped', 0):,}")
    print(f"Divs converted to paragraphs: {summary['totals'].get('divs_converted_to_p', 0):,}")
    print(f"Spacing divs removed: {summary['totals'].get('spacing_divs_removed', 0):,}")
    print(f"Iframes replaced with placeholders: {summary['totals'].get('iframes_replaced', 0):,}")
    print(f"Style tags removed: {summary['totals'].get('style_tags_removed', 0):,}")
    print(f"Files with iframes: {len(summary['files_with_iframes']):,}")
    print(f"Files with style tags: {len(summary['files_with_styles']):,}")
    print(f"Files with warnings: {summary['files_with_warnings_count']:,}")
    if report["parse_failures"]:
        print()
        print("Parse failures:")
        for failure in report["parse_failures"][:10]:
            print(f"  - {failure['file']}: {failure['error']}")
    print()


if __name__ == "__main__":
    base_path = abspath(join(dirname(__file__), ".."))
    source_folder = join(base_path, "data", "cleaned_news")
    output_folder = join(base_path, "data", "normalized_news")
    report_path = join(base_path, "data", "html_normalization_report.json")

    report = normalize_news_files(source_folder, output_folder)
    print_report(report)
    export_report(report, report_path)
    print(f"Report exported to {report_path}")
