from dataclasses import dataclass, field
from html import unescape
import json
import re

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from storyblok_config import load_config
from storyblok_embeds import embed_blok_from_src

DEFAULT_CONFIG = load_config()

BLOCK_TAGS = {
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "blockquote",
    "pre",
    "table",
    "thead",
    "tbody",
    "tr",
    "td",
    "th",
    "hr",
    "img",
    "div",
}

HEADING_LEVELS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}

MARK_TAGS = {
    "strong": "bold",
    "b": "bold",
    "em": "italic",
    "i": "italic",
    "u": "underline",
    "s": "strike",
    "del": "strike",
    "code": "code",
    "sup": "superscript",
    "sub": "subscript",
}

# SharePoint's editor never emits <u>. It underlines by setting the style
# attribute instead -- <strong style="text-decoration:underline;">, and the same
# on span and a -- so the tag map above would miss every underline in the corpus.
# The entity form appears too, because the export HTML-escapes the colon.
UNDERLINE_STYLE = re.compile(r"text-decoration[^:;]*(?::|&#58;)[^;]*underline",
                             re.IGNORECASE)


def style_marks(node):
    """Marks carried by a tag's style attribute rather than by its name."""
    style = node.get("style") or ""
    return [{"type": "underline"}] if UNDERLINE_STYLE.search(style) else []


IFRAME_COMMENT_PATTERN = re.compile(r"^\s*MIGRATION:IFRAME:(.+?)\s*$")
HTML_IFRAME_COMMENT_PATTERN = re.compile(
    r"<!--\s*MIGRATION:IFRAME:(.+?)\s*-->", re.IGNORECASE | re.DOTALL
)


@dataclass
class ConversionResult:
    document: dict
    warnings: list[str] = field(default_factory=list)


def preprocess_migration_comments(html, config=None):
    warnings = []
    blok_nodes = []

    def replacer(match):
        src = match.group(1).strip()
        warnings.append(f"iframe_embedded:{src}")
        blok_nodes.append(embed_blok_from_src(src, config=config))
        return ""

    cleaned = HTML_IFRAME_COMMENT_PATTERN.sub(replacer, html or "")
    return cleaned, warnings, blok_nodes


def html_to_storyblok_richtext(html, config=None):
    config = config or DEFAULT_CONFIG
    warnings = []
    preprocessed, comment_warnings, comment_bloks = preprocess_migration_comments(
        html, config=config
    )
    warnings.extend(comment_warnings)

    soup = BeautifulSoup(preprocessed or "", "html5lib")
    root = soup.body if soup.body else soup
    content = []

    content.extend(convert_children(list(root.children), warnings, config))

    content.extend(comment_bloks)
    content = [node for node in content if node is not None and not is_empty_paragraph(node)]
    return ConversionResult({"type": "doc", "content": content}, warnings)


def is_empty_paragraph(node):
    if not isinstance(node, dict) or node.get("type") != "paragraph":
        return False
    inline = node.get("content") or []
    if not inline:
        return True
    if len(inline) == 1 and inline[0].get("type") == "text":
        return not inline[0].get("text", "").strip()
    return False


def is_inline_tag(node):
    """A tag that belongs inside a paragraph rather than beside one."""
    return (isinstance(node, Tag)
            and node.name.lower() not in BLOCK_TAGS
            and node.name.lower() != "iframe"
            and not node.get("data-storyblok-embed"))


def convert_children(children, warnings, config=None):
    """Convert a run of siblings, keeping consecutive inline content together.

    SharePoint leaves the opening sentence unwrapped at the top level:

        The <a href="...">College of American Pathologists</a> (CAP), an
        internationally recognised standard ...
        <p>With 3,000 CAP requirements ...</p>

    Handling each sibling on its own split that single sentence into two
    paragraphs -- "The " and " (CAP), an internationally ..." -- and dropped the
    <a> entirely, because <a> is not a block tag and nothing else claimed it. The
    link and its text vanished from the article.

    So inline siblings are buffered and flushed as ONE paragraph, and only a real
    block tag ends it.
    """
    config = config or DEFAULT_CONFIG
    out, buf = [], []

    def flush():
        nonlocal buf
        if buf:
            paragraph = paragraph_from_inline(merge_text_nodes(buf))
            if paragraph:
                out.append(paragraph)
            buf = []

    for child in children:
        # Comment subclasses NavigableString in bs4, so it is tested first.
        if isinstance(child, Comment):
            flush()
            out.extend(convert_migration_comment(child, warnings, config))
            continue
        if isinstance(child, NavigableString):
            if normalize_text(str(child)).strip():
                buf.extend(inline_from_child(child, warnings, []))
            continue
        if is_inline_tag(child):
            buf.extend(inline_from_child(child, warnings, []))
            continue
        flush()
        out.extend(convert_root_child(child, warnings, config))
    flush()
    return out


def convert_root_child(node, warnings, config=None):
    config = config or DEFAULT_CONFIG
    if isinstance(node, NavigableString):
        text = normalize_text(str(node))
        if not text.strip():
            return []
        warnings.append("orphan_text_wrapped_in_paragraph")
        return [paragraph_from_inline([text_node(text)])]

    if isinstance(node, Comment):
        return convert_migration_comment(node, warnings, config)

    if not isinstance(node, Tag):
        return []

    return block_nodes_from_tag(node, warnings, config)


def embed_blok_from_tag(tag, warnings, config=None):
    config = config or DEFAULT_CONFIG
    src = (tag.get("data-src") or tag.get("src") or "").strip()
    if not src:
        warnings.append("iframe_embed_missing_src")
        return None
    warnings.append(f"iframe_embedded:{src}")
    return embed_blok_from_src(src, config=config)


def block_nodes_from_paragraph(node, warnings, config=None):
    """Split a paragraph that carries block content, keeping document order.

    A paragraph can hold an embed, an iframe, or images. Rich text has no way to
    place an image inside a paragraph, so the paragraph is broken into the text
    around it and the images between -- in order, because their position in the
    prose is the whole point.

    This matters for the side-by-side case. SharePoint centres two photos in one
    paragraph:

        <p style="text-align:center;">
          <img src=".../Dar 1.jpeg"> <img src=".../Dar (2).jpeg">
        </p>

    Both used to be dropped, because an <img> inside a paragraph had nowhere to
    go. They now emerge as two adjacent image nodes, which is what lets the
    payload builder recognise an adjacent run and turn it into one gallery at
    that point in the article.
    """
    config = config or DEFAULT_CONFIG
    embed_divs = node.find_all("div", attrs={"data-storyblok-embed": True},
                               recursive=True)
    iframes = node.find_all("iframe", recursive=True)
    images = node.find_all("img", recursive=True)
    if not embed_divs and not iframes and not images:
        return None

    nodes, buf = [], []

    def flush():
        """Emit whatever inline content has accumulated as one paragraph."""
        nonlocal buf
        if buf:
            paragraph = paragraph_from_inline(merge_text_nodes(buf))
            if paragraph:
                nodes.append(paragraph)
            buf = []

    def walk(parent):
        """Descend so an image wrapped in <em>/<span> is still found."""
        for child in parent.children:
            if isinstance(child, Comment):
                continue
            if isinstance(child, NavigableString):
                if normalize_text(str(child)).strip():
                    buf.extend(inline_from_child(child, warnings, []))
                continue
            if not isinstance(child, Tag):
                continue

            child_name = child.name.lower()
            if child_name == "img":
                flush()
                nodes.append(convert_image_node(child, warnings))
                continue
            if child_name == "iframe" or (child_name == "div"
                                          and child.get("data-storyblok-embed")):
                flush()
                blok = embed_blok_from_tag(child, warnings, config=config)
                if blok:
                    nodes.append(blok)
                continue
            if child.find(["img", "iframe"], recursive=True):
                # an image nested inside formatting: keep going down rather than
                # collapsing the tag and losing it
                walk(child)
                continue
            buf.extend(inline_from_child(child, warnings, []))

    walk(node)
    flush()
    return nodes or None


def block_nodes_from_tag(node, warnings, config=None):
    config = config or DEFAULT_CONFIG
    name = node.name.lower()
    if name == "div" and node.get("data-storyblok-embed"):
        blok = embed_blok_from_tag(node, warnings, config=config)
        return [blok] if blok else []

    if name == "iframe":
        blok = embed_blok_from_tag(node, warnings, config=config)
        return [blok] if blok else []

    if name == "div":
        # Same grouping as the root: a div is a wrapper, and running text inside
        # it must not be split sibling by sibling.
        return convert_children(list(node.children), warnings, config)

    if name == "p":
        embed_blocks = block_nodes_from_paragraph(node, warnings, config)
        if embed_blocks:
            return embed_blocks

    block = convert_block_node(node, warnings, config)
    return [block] if block else []


def paragraph_from_inline(inline):
    inline = merge_text_nodes(inline)
    if not inline:
        return None
    return {"type": "paragraph", "content": inline}


def convert_migration_comment(comment, warnings, config=None):
    config = config or DEFAULT_CONFIG
    match = IFRAME_COMMENT_PATTERN.match(str(comment).strip())
    if match:
        src = match.group(1).strip()
        warnings.append(f"iframe_embedded:{src}")
        return [embed_blok_from_src(src, config=config)]
    return []


def convert_block_node(node, warnings, config=None):
    config = config or DEFAULT_CONFIG
    name = node.name.lower()

    if name in HEADING_LEVELS:
        inline = collect_inline_content(node, warnings)
        inline = merge_text_nodes(inline)
        if not inline:
            return None
        return {
            "type": "heading",
            "attrs": {"level": HEADING_LEVELS[name]},
            "content": inline,
        }

    if name == "p":
        images = node.find_all("img", recursive=True)
        if len(images) == 1 and node.get_text(strip=True) == "" and not node.find(["a", "strong", "em"]):
            return convert_image_node(images[0], warnings)

        inline = collect_inline_content(node, warnings)
        inline = merge_text_nodes(inline)
        if not inline:
            return None
        return {"type": "paragraph", "content": inline}

    if name == "ul":
        items = [convert_list_item(child, warnings, config) for child in node.find_all("li", recursive=False)]
        items = [item for item in items if item]
        if not items:
            return None
        return {"type": "bullet_list", "content": items}

    if name == "ol":
        items = [convert_list_item(child, warnings, config) for child in node.find_all("li", recursive=False)]
        items = [item for item in items if item]
        if not items:
            return None
        return {"type": "ordered_list", "content": items}

    if name == "blockquote":
        blocks = []
        for child in node.children:
            if isinstance(child, NavigableString):
                text = normalize_text(str(child))
                if text:
                    paragraph = paragraph_from_inline([text_node(text)])
                    if paragraph:
                        blocks.append(paragraph)
                continue
            if isinstance(child, Tag):
                blocks.extend(block_nodes_from_tag(child, warnings, config))
        if not blocks:
            inline = collect_inline_content(node, warnings)
            paragraph = paragraph_from_inline(inline)
            if paragraph:
                blocks = [paragraph]
        if not blocks:
            return None
        return {"type": "blockquote", "content": blocks}

    if name == "pre":
        code_text = node.get_text()
        if not code_text:
            return None
        return {"type": "code_block", "content": [{"type": "text", "text": code_text}]}

    if name == "hr":
        return {"type": "horizontal_rule"}

    if name == "img":
        return convert_image_node(node, warnings)

    if name == "table":
        rows = []
        for row in node.find_all("tr", recursive=True):
            converted = convert_table_row(row, warnings)
            if converted:
                rows.append(converted)
        if not rows:
            return None
        return {"type": "table", "content": rows}

    if name == "div":
        warnings.append("unexpected_div_in_block_converter")
        return None

    if name in BLOCK_TAGS:
        inline = collect_inline_content(node, warnings)
        inline = merge_text_nodes(inline)
        if not inline:
            return None
        warnings.append(f"unsupported_block_wrapped_in_paragraph:{name}")
        return {"type": "paragraph", "content": inline}

    return None


def convert_list_item(node, warnings, config=None):
    config = config or DEFAULT_CONFIG
    blocks = []
    for child in node.children:
        if isinstance(child, NavigableString):
            text = normalize_text(str(child))
            if text:
                blocks.append({"type": "paragraph", "content": [text_node(text)]})
            continue
        if not isinstance(child, Tag):
            continue
        child_name = child.name.lower()
        if child_name in {"ul", "ol"}:
            block = convert_block_node(child, warnings, config)
            if block:
                blocks.append(block)
            continue
        blocks.extend(block_nodes_from_tag(child, warnings, config))

    if not blocks:
        inline = collect_inline_content(node, warnings)
        inline = merge_text_nodes(inline)
        if inline:
            blocks = [{"type": "paragraph", "content": inline}]

    if not blocks:
        return None

    return {"type": "list_item", "content": blocks}


def convert_table_row(node, warnings):
    cells = []
    for cell in node.find_all(["td", "th"], recursive=False):
        cell_type = "tableHeader" if cell.name.lower() == "th" else "tableCell"
        inline = collect_inline_content(cell, warnings)
        inline = merge_text_nodes(inline)
        if not inline:
            inline = [text_node("")]
        cells.append({"type": cell_type, "content": [{"type": "paragraph", "content": inline}]})

    if not cells:
        return None
    return {"type": "tableRow", "content": cells}


def convert_image_node(node, warnings):
    src = (node.get("src") or "").strip()
    alt = (node.get("alt") or "").strip()
    title = (node.get("title") or "").strip() or None

    if src.startswith("/"):
        warnings.append(f"sharepoint_image:{src}")

    attrs = {"src": src, "alt": alt}
    if title:
        attrs["title"] = title

    return {"type": "image", "attrs": attrs}


def collect_inline_content(node, warnings, active_marks=None):
    if active_marks is None:
        active_marks = []

    parts = []
    for child in node.children:
        parts.extend(inline_from_child(child, warnings, list(active_marks)))
    return parts


def inline_from_child(node, warnings, active_marks):
    if isinstance(node, Comment):
        convert_migration_comment(node, warnings)
        return []

    if isinstance(node, NavigableString):
        text = normalize_text(str(node))
        if not text:
            return []
        return [text_node(text, active_marks)]

    if not isinstance(node, Tag):
        return []

    name = node.name.lower()

    if name == "br":
        return [{"type": "hard_break"}]

    # An underline can ride on any inline tag's style attribute, so it is
    # collected before the tag's own meaning is considered.
    active_marks = active_marks + style_marks(node)

    if name == "a":
        href = (node.get("href") or "").strip()
        target = (node.get("target") or "_self").strip() or "_self"
        link_mark = {"type": "link", "attrs": link_attrs(href, target)}
        if href.startswith("/"):
            warnings.append(f"relative_link:{href}")
        marks = active_marks + [link_mark]
        return collect_inline_content(node, warnings, marks)

    if name in MARK_TAGS:
        mark = {"type": MARK_TAGS[name]}
        marks = active_marks + [mark]
        return collect_inline_content(node, warnings, marks)

    if name == "img":
        warnings.append("inline_image_promoted_to_block_unsupported_in_paragraph")
        return []

    if name == "iframe":
        warnings.append("inline_iframe_promoted_to_block")
        return []

    if name == "div" and node.get("data-storyblok-embed"):
        warnings.append("inline_embed_promoted_to_block")
        return []

    if name in {"span", "font"}:
        return collect_inline_content(node, warnings, active_marks)

    if name in BLOCK_TAGS:
        warnings.append(f"unexpected_block_inside_inline:{name}")
        return []

    warnings.append(f"unsupported_inline_tag_ignored:{name}")
    return collect_inline_content(node, warnings, active_marks)


def link_attrs(href, target):
    linktype = "url"
    if href.startswith("mailto:"):
        linktype = "email"
    return {
        "href": href,
        "target": target,
        "linktype": linktype,
        "uuid": None,
        "anchor": None,
        "custom": {},
    }


def text_node(text, marks=None):
    node = {"type": "text", "text": text}
    if marks:
        node["marks"] = normalize_marks(marks)
    return node


def normalize_marks(marks):
    deduped = []
    seen = set()
    for mark in marks:
        key = mark_key(mark)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(mark)
    return deduped


def mark_key(mark):
    attrs = mark.get("attrs") or {}
    return (mark["type"], json.dumps(attrs, sort_keys=True))


def marks_list_key(marks):
    return tuple(mark_key(mark) for mark in normalize_marks(marks or []))


def merge_text_nodes(nodes):
    merged = []
    for node in nodes:
        if node.get("type") == "hard_break":
            merged.append(node)
            continue
        if node.get("type") != "text":
            merged.append(node)
            continue

        key = marks_list_key(node.get("marks"))
        if merged and merged[-1].get("type") == "text":
            if marks_list_key(merged[-1].get("marks")) == key:
                merged[-1]["text"] += node["text"]
                continue
        merged.append(node)
    return merged


def normalize_text(text):
    return unescape(text).replace("\xa0", " ")


def validate_document(document):
    errors = []
    if not isinstance(document, dict):
        return ["document must be an object"]
    if document.get("type") != "doc":
        errors.append("root type must be doc")
    content = document.get("content")
    if not isinstance(content, list):
        errors.append("doc.content must be a list")
        return errors

    for index, node in enumerate(content):
        errors.extend(validate_block_node(node, f"content[{index}]"))

    return errors


def validate_block_node(node, path):
    errors = []
    if not isinstance(node, dict):
        return [f"{path} must be an object"]

    node_type = node.get("type")
    if node_type == "paragraph":
        errors.extend(validate_inline_nodes(node.get("content"), path))
    elif node_type == "heading":
        level = (node.get("attrs") or {}).get("level")
        if level not in {1, 2, 3, 4, 5, 6}:
            errors.append(f"{path}.attrs.level must be 1-6")
        errors.extend(validate_inline_nodes(node.get("content"), path))
    elif node_type in {"bullet_list", "ordered_list"}:
        for index, item in enumerate(node.get("content") or []):
            errors.extend(validate_block_node(item, f"{path}.content[{index}]"))
    elif node_type == "list_item":
        blocks = node.get("content") or []
        if not blocks:
            errors.append(f"{path} list_item must contain block nodes")
        for index, block in enumerate(blocks):
            errors.extend(validate_block_node(block, f"{path}.content[{index}]"))
    elif node_type == "blockquote":
        for index, block in enumerate(node.get("content") or []):
            errors.extend(validate_block_node(block, f"{path}.content[{index}]"))
    elif node_type == "table":
        for index, row in enumerate(node.get("content") or []):
            if row.get("type") != "tableRow":
                errors.append(f"{path}.content[{index}] must be tableRow")
    elif node_type == "image":
        if not (node.get("attrs") or {}).get("src"):
            errors.append(f"{path}.attrs.src is required")
    elif node_type == "blok":
        body = (node.get("attrs") or {}).get("body")
        if not isinstance(body, list) or not body:
            errors.append(f"{path}.attrs.body must be a non-empty list")
    elif node_type in {"horizontal_rule", "code_block"}:
        pass
    else:
        errors.append(f"{path} has unsupported block type {node_type!r}")

    return errors


def validate_inline_nodes(nodes, path):
    errors = []
    if nodes is None:
        errors.append(f"{path}.content must be a list")
        return errors
    if not isinstance(nodes, list):
        errors.append(f"{path}.content must be a list")
        return errors
    for index, node in enumerate(nodes):
        node_type = node.get("type")
        if node_type == "text":
            if not isinstance(node.get("text"), str):
                errors.append(f"{path}.content[{index}].text must be a string")
        elif node_type == "hard_break":
            continue
        else:
            errors.append(f"{path}.content[{index}] has unsupported inline type {node_type!r}")
    return errors
