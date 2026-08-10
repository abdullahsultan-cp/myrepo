import os as _os
import re
import sys as _sys
from collections import Counter
from copy import deepcopy
from html import unescape
from json import dump, load
from os import listdir, makedirs
from os.path import join

from bs4 import BeautifulSoup, NavigableString, Tag

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import _bootstrap

_bootstrap.ensure()

from fields import F

# Paths come from the shared module, so this works for any
# content type; see pipeline/paths_root.py.
from paths_root import P
from storyblok_embeds import detect_embed_type, embed_placeholder_tag

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
    with open(file_path, encoding="utf-8") as f:
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


# SharePoint's editor never writes <u>. It underlines by setting the style
# attribute -- <strong style="text-decoration:underline;"> -- so stripping style
# as presentation markup silently discards every underline in the corpus. The
# meaning is promoted to a real <u> tag first; from there the existing tag
# mapping carries it through to an underline mark. Colours and fonts genuinely
# are presentation and stay stripped.
UNDERLINE_STYLE = re.compile(r"text-decoration[^:;]*:[^;]*underline",
                             re.IGNORECASE)


def preserve_underline(tag, stats):
    """Wrap a style-underlined tag's children in <u> before the style is lost."""
    if not isinstance(tag, Tag) or tag.name.lower() == "u":
        return
    style = tag_attr(tag, "style") or ""
    if not isinstance(style, str) or not UNDERLINE_STYLE.search(style):
        return
    if not tag.get_text(strip=True):
        return                      # a zero-width spacer; nothing to underline
    # Wrap the CONTENTS, not the tag: keeping <strong> outside <u> preserves
    # both marks and leaves the tag hierarchy the rest of the pass expects.
    inner = BeautifulSoup("", "html5lib").new_tag("u")
    for child in list(tag.contents):
        inner.append(child.extract())
    tag.append(inner)
    stats["underlines_preserved"] = stats.get("underlines_preserved", 0) + 1


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


DOUBLE_BR = re.compile(r"(?:\s*<br\s*/?>\s*){2,}", re.I)


def split_on_double_breaks(html, stats):
    """Turn <br><br> inside a paragraph into real paragraph boundaries.

    Editors writing in SharePoint pressed Enter twice rather than starting a new
    block, so 179 articles arrive as ONE <p> holding the whole piece with
    <br><br> between what are plainly paragraphs. That is not cosmetic: those
    stories had a single body node, and the rule that moves paragraph 1 into
    `description` then emptied the body completely.

    Done on the serialised HTML rather than the tree. Rebuilding paragraphs by
    moving nodes around lost the text of six stories -- 2279 came out as
    <p><br/>x19</p> with all 4000 characters gone -- because extracting children
    while regrouping them is easy to get subtly wrong. A boundary is a textual
    thing here, so it is safer to cut the string and let the parser rebuild.

    Only a run of TWO OR MORE breaks splits. A single <br> is a line break
    inside a paragraph -- an address, a list of names -- and is left alone.
    """
    out, n = [], 0
    for chunk in re.split(r"(<p[^>]*>.*?</p>)", html, flags=re.S | re.I):
        if not (chunk[:2].lower() == "<p" and chunk[-4:].lower() == "</p>"):
            out.append(chunk)
            continue
        open_tag = re.match(r"<p[^>]*>", chunk, re.I).group(0)
        inner = chunk[len(open_tag):-4]
        if not DOUBLE_BR.search(inner):
            out.append(chunk)
            continue
        parts = [p for p in DOUBLE_BR.split(inner)
                 if re.sub(r"<[^>]+>", "", p).strip()
                 or re.search(r"<img", p, re.I)]
        if len(parts) < 2:
            out.append(chunk)
            continue
        out.append("".join(f"{open_tag}{p}</p>" for p in parts))
        n += len(parts)
    stats["paragraphs_split_on_double_break"] = n
    return "".join(out)


def normalize_content_html(html):
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

    # Promote style-carried underlines to <u> before ANY inline cleanup. It has
    # to run ahead of normalize_inline_tags, which unwraps <span> -- and <span
    # style="text-decoration:underline"> is where most of the corpus keeps its
    # underlines, so running after would drop them with the span. find_all is
    # materialised first because this inserts tags while iterating.
    for tag in list(body.find_all(True)):
        if tag_attr(tag, "data-storyblok-embed"):
            continue
        preserve_underline(tag, stats)

    normalize_inline_tags(body)
    stats["inline_tags_normalized"] = 1

    for tag in body.find_all(True):
        if tag_attr(tag, "data-storyblok-embed"):
            continue
        strip_presentation_attrs(tag)

    normalized_html = "".join(str(child) for child in body.children).strip()
    # Last, on the finished markup: by now every div is a <p>, so a converted
    # div gets split too.
    normalized_html = split_on_double_breaks(normalized_html, stats)
    return normalized_html, stats, warnings


def normalize_news_item(news_item):
    item = deepcopy(news_item)
    news_content = F.get(item, "body")
    if not isinstance(news_content, str) or not news_content.strip():
        return item, Counter(), []

    normalized_html, stats, warnings = normalize_content_html(news_content)
    F.set(item, "body", normalized_html)
    return item, stats, warnings


def aggregate_stats(counter, stats):
    counter.update(stats)


def export_report(summary, output_path):
    with open(output_path, "w", encoding="utf-8", newline="\n") as f:
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
        with open(output_path, "w", encoding="utf-8", newline="\n") as f:
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
    source_folder = P.CLEANED
    output_folder = P.NORMALIZED
    report_path = P.report("html_normalization_report.json")

    report = normalize_news_files(source_folder, output_folder)
    print_report(report)
    export_report(report, report_path)
    print(f"Report exported to {report_path}")
