"""build_pages.py -- turn archived aku.edu HTML into Storyblok `page` payloads.

Reads the HTML saved under out/work/legacy_html/<serial>.html, the galleries
recovered by recover_galleries.py, and writes out/work/page_payloads.json.

What it decides, and why:

* **`spacing_preset` is always "subsection", and `spacing` is never written.**
  Rabee, 13 Sep 2026: "use spacing preset subsection no matter what condition i
  will change by my self if i need to". So this emits one value everywhere rather
  than a per-component default -- he tunes it by hand afterwards, and a clever
  default would only be something to undo. The legacy `spacing` custom-field
  plugin stays "" on every blok.

* **A page is not one rich_text.** The components exist, so they get used:
  `media_section` (type gallery) for the picture galleries, `row` > `row_item` >
  `profile_card` for a people grid, `hero` with the page's own heroblock image.
  A wall of text was the first version and it read like one.

* **Every content zone counts.** A SharePoint page is a set of web part zones,
  each its own `.ms-rtestate-field`. Taking only the largest dropped 44,042
  characters and 29 images across 31 pages without erroring once.

* **The galleries are not in the HTML at all.** They are fetched from a
  SharePoint list at runtime, so `HD4 Pakistan` serves one image and shows 115.
  recover_galleries.py pulls them from the REST API; this places them.

* **Images keep their source position** inside the rich text; only a recovered
  gallery becomes a separate blok, because that is what it is on the live page.

* **Text is cleaned but never trimmed inside rich text.** A text node is half a
  sentence: the space at its edge is the space between two words.

Run:  python build_pages.py [--only 848,812] [--limit N] [--skip-dupes]
"""
import argparse
import hashlib
import html
import json
import os
import re
import urllib.parse

import page_titles
import paths
from bs4 import BeautifulSoup, NavigableString, Tag

HTML_DIR = paths.work('legacy_html')
OUT = paths.work('page_payloads.json')

# One value, everywhere. See the module docstring.
PRESET = 'subsection'

CHROME = re.compile(
    r'/_layouts/|/_catalogs/|favicon|spcommon|searchresultui|nodearrow'
    r'|EntityHeaders|WebResource\.axd|AKU_logo'
    # A picture library's own form page is not a picture. `/Forms/DispForm.aspx`
    # is the "image properties" screen, it needs a login and returns 401, and it
    # arrives looking like a src because SharePoint points a thumbnail at it.
    r'|/Forms/\w+\.aspx', re.I)

HERO_IMG = re.compile(
    r'["\'(]([^"\'()<>]*?[Hh]ero[^"\'()<>]*?\.(?:jpg|jpeg|png|gif))', re.I)

BLOCK = {'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'table',
         'div', 'blockquote'}

MARKS = {'strong': 'bold', 'b': 'bold', 'em': 'italic', 'i': 'italic',
         'u': 'underline', 's': 'strike', 'strike': 'strike',
         'sub': 'subscript', 'sup': 'superscript', 'code': 'code'}


def clean_frag(text):
    """Clean a rich-text fragment. Does NOT trim -- see the module docstring."""
    if not text:
        return ''
    t = html.unescape(text).translate(page_titles.TRANSLATION)
    return re.sub(r'[ \t]+', ' ', t)


def clean_value(text):
    """Clean a whole value (a title, a card's name). Trimming is correct here."""
    return page_titles.clean(text or '')


def uid(seed):
    h = hashlib.sha1(str(seed).encode()).hexdigest()
    return f'{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}'


def asset_stub(src, alt=''):
    """An empty Storyblok asset field, carrying the source URL for the uploader."""
    return {'id': None, 'alt': alt, 'name': '', 'focus': None, 'title': None,
            'source': None, 'filename': '', 'copyright': None,
            'fieldtype': 'asset', 'meta_data': {}, '_src_original': src or ''}


def link_stub():
    return {'id': '', 'url': '', 'linktype': 'story', 'fieldtype': 'multilink',
            'cached_url': ''}


# --------------------------------------------------------------- rich text ---
def inline(node, marks, images):
    out = []
    if isinstance(node, NavigableString):
        t = clean_frag(str(node))
        if t:
            n = {'type': 'text', 'text': t}
            if marks:
                n['marks'] = [{'type': m} for m in sorted(set(marks))]
            out.append(n)
        return out
    if not isinstance(node, Tag):
        return out
    if node.name == 'br':
        return [{'type': 'hard_break'}]
    if node.name == 'img':
        src = node.get('src') or ''
        if src and not src.startswith('data:') and not CHROME.search(src):
            images.append(src)
            out.append({'type': 'image',
                        'attrs': {'id': None, 'alt': clean_value(node.get('alt') or ''),
                                  'src': src, 'title': '', 'source': '',
                                  'copyright': '', '_src_original': src}})
        return out
    if node.name == 'a':
        sub = []
        for c in node.children:
            sub += inline(c, marks, images)
        href = (node.get('href') or '').strip()
        if href:
            # An invisible inside an href is not cosmetic -- it breaks the link.
            href = html.unescape(href).translate(page_titles.TRANSLATION).strip()
            link = {'type': 'link',
                    'attrs': {'href': href, 'uuid': None, 'anchor': None,
                              'target': '_blank',
                              'linktype': 'url' if '://' in href or href.startswith('/')
                              else 'story'}}
            for n in sub:
                if n.get('type') == 'text':
                    n.setdefault('marks', []).append(link)
        return sub
    m = MARKS.get(node.name)
    nm = marks | {m} if m else marks
    for c in node.children:
        out += inline(c, nm, images)
    return out


def _has_content(nodes):
    return any(n.get('text', '').strip() or n.get('type') == 'image' for n in nodes)


def para(children):
    return {'type': 'paragraph', 'content': children} if children else None


def split_breaks(blocks):
    """Split a paragraph at a run of two or more <br>, and drop the empties.

    SharePoint's editors end a paragraph by pressing Return twice inside one, so
    a single <p> arrives holding what are plainly several paragraphs -- one here
    carries a run of ten. This splits the paragraph's own inline list; it does
    NOT regroup the HTML tree, which is how six news stories once lost all their
    text. A fragment is kept only if it has text OR an image: testing for text
    alone silently deletes a picture that sits on its own line.
    """
    out = []
    for node in blocks:
        if node.get('type') != 'paragraph':
            out.append(node)
            continue
        part, parts, run = [], [], 0
        for c in node.get('content') or []:
            if c.get('type') == 'hard_break':
                run += 1
                if run >= 2:
                    if part:
                        parts.append(part)
                    part = []
                    continue
                part.append(c)
            else:
                run = 0
                part.append(c)
        if part:
            parts.append(part)
        for p in parts:
            while p and p[-1].get('type') == 'hard_break':
                p.pop()
            while p and p[0].get('type') == 'hard_break':
                p.pop(0)
            if _has_content(p):
                out.append({'type': 'paragraph', 'content': p})
    return lift_images(out)


def lift_images(blocks):
    """Move an image out of a paragraph and make it a block in its own right.

    In Storyblok's rich text `image` is a BLOCK node, not an inline one -- the
    shared validator classifies it beside `table` and `blockquote`, and a
    paragraph's content may hold only `text` and `hard_break`. Sixty images were
    being written inside a paragraph's content array, where the renderer has no
    rule for them.

    The picture still stays exactly where the author put it, which is the rule
    (CLAUDE.md: "Images keep their source position") -- the paragraph is split
    around it rather than the image being moved to the end.
    """
    out = []
    for node in blocks:
        kind = node.get('type')
        # A heading can carry one too -- two researcher pages open with the
        # portrait sitting inside the <h2> that names them.
        if kind not in ('paragraph', 'heading'):
            out.append(node)
            continue
        run = []
        for c in node.get('content') or []:
            if c.get('type') == 'image':
                if _has_content(run):
                    out.append({**node, 'content': run})
                out.append(c)
                run = []
            else:
                run.append(c)
        if _has_content(run):
            out.append({**node, 'content': run})
    return out


def is_layout_table(table):
    """One column, or one filled cell: SharePoint using a table as a box.

    Those are unwrapped -- rendering them as a real table would draw a border
    around a paragraph. A table with two or more populated columns is a table.
    """
    rows = table.find_all('tr')
    if not rows:
        return True
    widest = max((len(r.find_all(['td', 'th'])) for r in rows), default=0)
    return widest <= 1


def table_node(table, images):
    """A real rich-text table: table > tableRow > tableCell > paragraph.

    The shape is copied from the tables already live in this space, attrs
    included -- `colwidth` and `backgroundColor` are present and null there, and
    a renderer that reads them should not meet a node that lacks them.

    Flattening these into paragraphs is what made the CBCB team page unreadable:
    32 of the webpart cells across these pages carry a table.
    """
    if is_layout_table(table):
        out = []
        for cell in table.find_all(['td', 'th']):
            for c in cell.children:
                out += block(c, images)
        return out
    rows = []
    for tr in table.find_all('tr'):
        cells = []
        for td in tr.find_all(['td', 'th']):
            inner = []
            for c in td.children:
                inner += block(c, images)
            if not inner:
                inner = [{'type': 'paragraph'}]
            try:
                colspan = int(td.get('colspan') or 1)
            except (TypeError, ValueError):
                colspan = 1
            try:
                rowspan = int(td.get('rowspan') or 1)
            except (TypeError, ValueError):
                rowspan = 1
            cells.append({'type': 'tableCell',
                          'attrs': {'colspan': colspan, 'rowspan': rowspan,
                                    'colwidth': None, 'backgroundColor': None},
                          'content': inner})
        if cells:
            rows.append({'type': 'tableRow', 'content': cells})
    return [{'type': 'table', 'content': rows}] if rows else []


def block(node, images):
    if isinstance(node, NavigableString):
        kids = inline(node, frozenset(), images)
        return [para(kids)] if _has_content(kids) else []
    if not isinstance(node, Tag):
        return []
    n = node.name
    if n in ('script', 'style', 'noscript'):
        return []

    if n in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
        kids = []
        for c in node.children:
            kids += inline(c, frozenset(), images)
        kids = [k for k in kids if k.get('type') != 'hard_break']
        if not _has_content(kids):
            return []
        return [{'type': 'heading', 'attrs': {'level': min(int(n[1]) + 1, 6)},
                 'content': kids}]

    if n in ('ul', 'ol'):
        # Sub-lists arrive in TWO shapes and only one of them is legal HTML.
        # SharePoint's editor indents an item by opening a new <ul> as a SIBLING
        # of the <li> it belongs under, not inside it:
        #
        #     <ul><li>Governance</li><ul><li>The Chancellor</li>...</ul></ul>
        #
        # A browser still draws that as a sub-list, so the author saw what they
        # meant. Walking only `find_all('li', recursive=False)` never visits the
        # sibling <ul> at all -- that silently dropped the whole governance list
        # from mc/home and two thirds of the equipment list from jrl.
        items = []
        for c in node.children:
            if not isinstance(c, Tag):
                continue
            if c.name in ('ul', 'ol'):
                sub = block(c, images)
                if not sub:
                    continue
                if items:                      # belongs under the item above
                    items[-1]['content'] += sub
                else:                          # no item above; keep it anyway
                    items.append({'type': 'list_item', 'content': sub})
                continue
            if c.name != 'li':
                continue
            kids, nested = [], []
            for x in c.children:               # the legal shape: <li><ul>...
                if isinstance(x, Tag) and x.name in ('ul', 'ol'):
                    nested += block(x, images)
                else:
                    kids += inline(x, frozenset(), images)
            body = ([para(kids)] if _has_content(kids) else []) + nested
            if body:
                items.append({'type': 'list_item', 'content': body})
        if not items:
            return []
        return [{'type': 'bullet_list' if n == 'ul' else 'ordered_list',
                 'content': items}]

    if n == 'blockquote':
        inner = []
        for c in node.children:
            inner += block(c, images)
        return [{'type': 'blockquote', 'content': inner}] if inner else []

    if n == 'table':
        return table_node(node, images)

    if n in ('div', 'span', 'font', 'tbody', 'tr', 'td', 'th', 'section'):
        out, buf = [], []
        for c in node.children:
            if isinstance(c, Tag) and c.name in BLOCK:
                if _has_content(buf):
                    out.append(para(buf))
                buf = []
                out += block(c, images)
            else:
                buf += inline(c, frozenset(), images)
        if _has_content(buf):
            out.append(para(buf))
        return out

    kids = []
    for c in node.children:
        kids += inline(c, frozenset(), images)
    return [para(kids)] if _has_content(kids) else []


# ------------------------------------------------------------ people grids ---
def is_people_grid(table):
    """Multi-column, and every filled cell holds exactly one image."""
    rows = table.find_all('tr')
    if max((len(r.find_all(['td', 'th'])) for r in rows), default=0) < 2:
        return False
    cells = [c for r in rows for c in r.find_all(['td', 'th'])]
    filled = [c for c in cells if c.get_text(strip=True) or c.find('img')]
    if len(filled) < 2:
        return False
    return all(len(c.find_all('img')) == 1 for c in filled)


def is_image_text_table(table):
    """A two-column table whose every filled row is one picture beside one blurb.

    SharePoint uses a table to lay an image next to its text; rendered as a real
    table the reader gets a bordered grid with a photo in one box and a sentence
    in the next. Rabee rebuilt one of these as split_sections by hand on
    ccbp/collaborations, which is the shape this recognises.
    """
    rows = [r for r in table.find_all('tr')]
    if not rows:
        return False
    good = 0
    for r in rows:
        cells = r.find_all(['td', 'th'])
        if len(cells) != 2:
            return False
        imgs = [len(c.find_all('img')) for c in cells]
        txt = [len(c.get_text(' ', strip=True)) for c in cells]
        if sum(imgs) == 0 and sum(txt) == 0:
            continue                     # a spacer row; ignore it
        # exactly one cell carries the picture, the other carries the words
        if sorted(imgs) != [0, 1] or sorted(txt)[1] < 40:
            return False
        good += 1
    return good >= 1


def table_as_splits(serial, seq, table, images):
    """One split_section per row: picture on the side it sits on in the source."""
    out = []
    for i, r in enumerate(table.find_all('tr')):
        cells = r.find_all(['td', 'th'])
        if len(cells) != 2:
            continue
        img_cell = next((c for c in cells if c.find('img')), None)
        txt_cell = next((c for c in cells if not c.find('img')), None)
        if img_cell is None or txt_cell is None:
            continue
        body = clean_value(txt_cell.get_text(' ', strip=True))
        if len(body) < 40:
            continue
        im = img_cell.find('img')
        src = (im.get('src') or '') if im else ''
        if not src or CHROME.search(src):
            src = ''
        head = txt_cell.find(['h1', 'h2', 'h3', 'h4', 'strong', 'b'])
        title = clean_value(head.get_text(' ', strip=True)) if head else ''
        if title and body.startswith(title):
            body = body[len(title):].strip()
        if src:
            images.append(src)
        # the image sat in the SECOND cell -> it renders on the right: default
        right = cells.index(img_cell) == 1
        out.append({'_uid': uid(f'{serial}-itt-{seq}-{i}'),
                    'component': 'split_section',
                    'title': title, 'highlight': '', 'description': body[:2000],
                    'image': asset_stub(src, title), 'image_fit': 'cover',
                    'image_variant': 'default',
                    'layout': 'default' if right else 'reverse',
                    'cta_label': '', 'cta_link': link_stub(),
                    'secondary_cta_label': '', 'secondary_cta_link': link_stub(),
                    'decorative_images': [], 'decorative_images_fit': 'cover',
                    'bg_color': {'_uid': uid(f'{serial}-ittbg-{seq}-{i}'),
                                 'color': '', 'plugin': 'official-colorpicker'},
                    'spacing': '', 'spacing_preset': PRESET})
    return out


def profile_from_cell(cell, images, seed):
    img = cell.find('img')
    src = img.get('src') if img else ''
    if src and not CHROME.search(src):
        images.append(src)
    else:
        src = ''
    bolds = [clean_value(b.get_text(' ', strip=True))
             for b in cell.find_all(['strong', 'b'])]
    bolds = [b for b in bolds if b]
    title = bolds[0] if bolds else ''
    subtitle = bolds[1] if len(bolds) > 1 else ''
    desc = clean_value(cell.get_text(' ', strip=True))
    for b in bolds[:2]:
        desc = desc.replace(b, '', 1)
    desc = re.sub(r'\s+', ' ', desc).strip()
    if not title:
        title, desc = desc[:60], desc[60:].strip()
    return {'_uid': uid(f'{seed}-pc'), 'component': 'profile_card',
            'image': asset_stub(src, title), 'title': title, 'subtitle': subtitle,
            'description': desc, 'image_fit': 'cover',
            'spacing': '', 'spacing_preset': PRESET}


# ------------------------------------------------------------------ build ----
AUTHOR_HINT = re.compile(r'chairsmsg|pic-circle|deansmsg|directormsg', re.I)

# A link is a button when AKU STYLED it as one. Counted across these pages:
# `button` 19, `buttonStyle` 15, `btn btnhpslider…` 7, `buttonStylea` 3,
# `button-hero` 2. Guessing from the text instead -- "a short ALL-CAPS link is
# probably a button" -- invented three buttons on newsevents-dsi, a page whose
# source has none. If the page has no button, we make none.
BUTTON_CLASS = re.compile(r'(?:^|\s)(button|buttonstyle\w*|btn)(?:\s|$)', re.I)


def is_button_link(a):
    classes = ' '.join(a.get('class') or [])
    if 'displaynone' in classes.lower():
        return False           # AKU hides these; they are not on the live page
    return bool(BUTTON_CLASS.search(classes))


def button_bloks(serial, seq, cell):
    """Links AKU styled as buttons -> one `row` of `button`s.

    The grouping is Rabee's own, taken off newsevents-dsi after he corrected it
    by hand: row(alignment start, on_mobile_wrap False, preset section) >
    row_item(width_mode fit) > button(variant primary, preset zero). Three loose
    button bloks stacked; one row sits them side by side.
    """
    found = []
    for i, a in enumerate(cell.find_all('a')):
        label = clean_value(a.get_text(' ', strip=True))
        href = (a.get('href') or '').strip()
        if not href or not label or '{{' in label or not is_button_link(a):
            continue
        href = html.unescape(href).translate(page_titles.TRANSLATION).strip()
        found.append({'_uid': uid(f'{serial}-btn-{seq}-{i}'), 'component': 'button',
                      'label': label, 'icon': 'none', 'variant': 'primary',
                      'link': {'id': '', 'url': href, 'linktype': 'url',
                               'fieldtype': 'multilink', 'cached_url': href,
                               'target': '_blank'},
                      'spacing': '', 'Spacing': '', 'spacing_preset': 'zero'})
    if not found:
        return []
    items = [{'_uid': uid(f'{serial}-btnri-{seq}-{i}'), 'component': 'row_item',
              'body': [b], 'alignment': 'start', 'width_mode': 'fit', 'spacing': '',
              'background_color': {'_uid': uid(f'{serial}-btnbg-{seq}-{i}'),
                                   'color': '', 'plugin': 'native-color-picker'}}
             for i, b in enumerate(found)]
    return [{'_uid': uid(f'{serial}-btnrow-{seq}'), 'component': 'row',
             'items': items, 'title': '', 'highlight': '', 'description': '',
             'alignment': 'start', 'on_mobile_wrap': 'False', 'spacing': '',
             'spacing_preset': 'section',
             'background_color': {'_uid': uid(f'{serial}-btnrowbg-{seq}'),
                                  'color': '', 'plugin': 'native-color-picker'}}]


def author_blok(serial, seq, cell, images):
    """A "Message from the Associate Dean" webpart -> split_section.

    SharePoint renders these server-side from a `chairsmsg` list: a circular
    portrait, the person's name and role, their message and a LEARN MORE link.
    It is not a testimonial and not a quote -- it is a named person speaking for
    the department, which is exactly what author_section is for.
    """
    img = cell.find('img')
    src = (img.get('src') or '') if img else ''
    if src and not CHROME.search(src):
        images.append(src)
    else:
        src = ''
    # These webparts carry no heading tags at all -- SharePoint styles the
    # heading as `div.title1`. Looking for <h*> returned nothing and left the
    # author's name and role blank.
    head = cell.find(['h1', 'h2', 'h3', 'h4']) or cell.find(class_='title1')
    title = clean_value(head.get_text(' ', strip=True)) if head else 'Message'
    lines = []
    for p in cell.find_all(['p', 'div'], recursive=True):
        if p.find(['p', 'div']):          # keep the leaves, not the wrappers
            continue
        t = clean_value(p.get_text(' ', strip=True))
        if t and t != title and t not in lines:
            lines.append(t)
    # The line under the heading -- "Dr Robyna Irshad Khan, Associate Dean
    # Allied Health" -- is its own field, not the opening of the message.
    # Rabee put it in `highlight` on BOTH pages he corrected by hand; folding it
    # into `description` ran the person's name into their first sentence.
    highlight, bio = '', ''
    if lines:
        first = lines[0]
        if len(first) < 140 and len(lines) > 1:
            highlight = first
            bio = ' '.join(lines[1:])
        else:
            bio = ' '.join(lines)
    bio = re.sub(r'\s+', ' ', bio).strip()
    for w in ('LEARN MORE', 'Learn More', 'READ MORE', 'Read More'):
        bio = bio.replace(w, '').strip()
        highlight = highlight.replace(w, '').strip()
    # SharePoint draws this portrait as a circle (`.pic-circle`), and
    # split_section has a variant for exactly that. Leaving it `default` put a
    # square crop where the old page had a round one.
    circular = bool(cell.select('.pic-circle, .pic-circle-right'))
    return {'_uid': uid(f'{serial}-author-{seq}'), 'component': 'split_section',
            'title': title, 'highlight': highlight,
            'description': bio[:2000],
            'image': asset_stub(src, highlight or title), 'image_fit': 'cover',
            'image_variant': 'circles' if circular else 'default',
            'layout': 'default',
            'cta_label': '', 'cta_link': link_stub(),
            'secondary_cta_label': '', 'secondary_cta_link': link_stub(),
            'decorative_images': [], 'decorative_images_fit': 'cover',
            'bg_color': {'_uid': uid(f'{serial}-authbg-{seq}'), 'color': '',
                         'plugin': 'official-colorpicker'},
            'spacing': '', 'spacing_preset': PRESET}


def _unused_author_section(serial, seq, title, name, role, bio, src):
    return {'_uid': uid(f'{serial}-author-{seq}'), 'component': 'author_section',
            'title': title, 'highlight': '', 'variant': 'about',
            'author_name': name, 'role': role, 'bio': bio[:2000],
            'college': '', 'college_link': link_stub(),
            'photo': asset_stub(src, name), 'profile_links': [],
            'social_links': [], 'spacing': '', 'spacing_preset': PRESET}


VIDEO_URL = re.compile(
    r'https?://(?:www\.)?(?:youtube\.com/(?:embed/|watch\?v=)|youtu\.be/|'
    r'player\.vimeo\.com/video/|vimeo\.com/\d)[^"\'\\ <>]+', re.I)

SLUGGY = re.compile(r'^[a-z0-9]+(?:[-_][a-z0-9]+)+$')


def video_url_of(raw):
    """The page's video, or ''. Channel links are not videos.

    The player is an empty `<iframe id="videouni">` filled by script, so the URL
    has to be read out of the page source rather than the iframe's src.
    """
    for u in VIDEO_URL.findall(raw):
        if '/channel/' in u or '/user/' in u:
            continue
        return u
    return ''


def video_blok(serial, seq, url):
    return {'_uid': uid(f'{serial}-vid-{seq}'), 'component': 'video',
            'video_url': {'id': '', 'url': url, 'linktype': 'url',
                          'fieldtype': 'multilink', 'cached_url': url},
            'thumbnail': asset_stub(''), 'title': '', 'auto_play': False,
            'show_controls': True, 'spacing': '', 'spacing_preset': PRESET}


def title_from_body(zones):
    """The page's real name when its own title is just the file name.

    `message-director.aspx` reports "message-director"; the page itself opens
    with an <h2> reading "Message from our Director", which is what a reader
    sees and what Rabee put in the hero by hand.
    """
    for z in zones:
        head = z.find(['h1', 'h2', 'h3'])
        if head:
            t = clean_value(head.get_text(' ', strip=True))
            if 3 < len(t) <= 90:
                return t
    return ''


def _hidden_el(e):
    return 'display:none' in (e.get('style') or '').replace(' ', '').lower()


def _cell_is_hidden(cell):
    """True when display:none covers what the cell actually says.

    Measured on text, not on tree position, because the two cases are otherwise
    identical in shape: the hidden webparts on Animal Facility hide 100% of
    their cell's text, and the profile page's validation summary hides 0% of
    its cell's 310 characters.
    """
    hidden = [e for e in [cell] + cell.find_all('div') if _hidden_el(e)]
    if not hidden:
        return False
    total = len(re.sub(r'\s+', '', cell.get_text(' ', strip=True)))
    if not total:
        return True                      # nothing to lose either way
    outer = [e for e in hidden if not any(h in e.parents for h in hidden)]
    covered = sum(len(re.sub(r'\s+', '', e.get_text(' ', strip=True))) for e in outer)
    return covered >= total * 0.8


def body_of(soup):
    """Every content zone on the page, in document order.

    A SharePoint page is not one rich-text field -- it is a set of web part
    zones. "Allied Health Events" has sixteen; taking only the biggest looks
    right on a simple page and silently truncates a complex one. Nested zones are
    skipped, not added twice.
    """
    for x in soup.find_all(['script', 'style', 'noscript']):
        x.decompose()
    # A webpart CELL, not a rich-text field. Some webparts are rendered by
    # SharePoint on the server and carry no .ms-rtestate-field at all -- the
    # "Message from the Associate Dean" block is one, and selecting on the field
    # dropped it silently along with 3,493 characters across five pages.
    cells = [d for d in soup.find_all('div')
             if (d.get('id') or '').startswith('MSOZoneCell')]
    cells = [c for c in cells
             if not any(p in cells for p in c.parents)]
    # A webpart wrapped in display:none is not on the live page. Animal Facility
    # carries Location and Contact twice this way -- once inside the accordion,
    # once in a hidden cell -- and both were being published.
    #
    # But "contains a hidden div" is far too broad a test. A faculty profile's
    # contact form carries a `ValidationSummary` div that is display:none until
    # the reader submits something invalid, and treating that as a hidden webpart
    # threw the whole cell away. Ask instead whether the hidden part accounts for
    # the cell's CONTENT: a hidden webpart hides all of its own text, while an
    # incidental hidden element holds none of it.
    cells = [c for c in cells if not _cell_is_hidden(c)]
    # A form's field labels are not content. The faculty profile's "Email
    # Contact Form" webpart reads as "Your Name * Your email * Subject *
    # Message *", which is a form the reader fills in, not prose to migrate.
    cells = [c for c in cells if len(c.find_all(['input', 'textarea', 'select'])) < 3]
    if cells:
        return cells
    fields = soup.select('.ms-rtestate-field')
    zones = [e for e in fields if not any(p in fields for p in e.parents)]
    if zones:
        return zones
    ph = soup.select_one('[id*=PlaceHolderMain]')
    return [ph] if ph else []


IMG_CACHE = paths.work('legacy_images')
MIN_HERO_WIDTH = 900


def _cache_path(src):
    import hashlib as _h
    name = urllib.parse.unquote(src.split('?')[0].split('/')[-1])
    name = re.sub(r'[^A-Za-z0-9._-]+', '-', name).strip('-') or 'image'
    stem, dot, ext = name.rpartition('.')
    digest = _h.sha1(src.encode()).hexdigest()[:10]
    return os.path.join(IMG_CACHE,
                        f'{stem or "image"}-{digest}{dot}{ext}' if dot
                        else f'{name}-{digest}')


def image_size(src):
    """(width, height) read from the file header, or (0, 0).

    No Pillow in this environment and the pages declare no width/height, so the
    JPEG/PNG/GIF headers are read directly. This exists because AKU reuses small
    side-column pictures (ccit/what-we-do) that turn to mush when a hero
    stretches them across the page.
    """
    p = _cache_path(src)
    try:
        with open(p, 'rb') as f:
            head = f.read(32)
            if head[:8] == b'\x89PNG\r\n\x1a\n':
                return (int.from_bytes(head[16:20], 'big'),
                        int.from_bytes(head[20:24], 'big'))
            if head[:3] == b'GIF':
                return (int.from_bytes(head[6:8], 'little'),
                        int.from_bytes(head[8:10], 'little'))
            if head[:2] == b'\xff\xd8':
                f.seek(2)
                while True:
                    b = f.read(1)
                    while b and b != b'\xff':
                        b = f.read(1)
                    marker = f.read(1)
                    while marker == b'\xff':
                        marker = f.read(1)
                    if not marker:
                        return (0, 0)
                    if marker[0] in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6,
                                     0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                        f.read(3)
                        h = int.from_bytes(f.read(2), 'big')
                        w = int.from_bytes(f.read(2), 'big')
                        return (w, h)
                    seg = int.from_bytes(f.read(2), 'big')
                    if seg < 2:
                        return (0, 0)
                    f.seek(seg - 2, 1)
    except (OSError, ValueError, IndexError):
        return (0, 0)
    return (0, 0)


def wide_enough_for_hero(src):
    w, _ = image_size(src)
    return w == 0 or w >= MIN_HERO_WIDTH   # unknown size: let it through


def hero_image_of(raw):
    """The page's own heroblock picture, or ''.

    Matched on the word "hero" in the path -- SharePoint files these under
    PublishingImages/Lists/<x>heroblock/. Anything else is left empty rather
    than guessed at: a wrong image on a published page is worse than none.
    """
    for cand in HERO_IMG.findall(raw):
        if ('PublishingImages' in cand or 'SiteAssets' in cand) and not CHROME.search(cand):
            return cand
    return ''


def gallery_blok(serial, idx, name, srcs, images):
    images.extend(srcs)
    return {
        '_uid': uid(f'{serial}-gal-{idx}'), 'component': 'media_section',
        'type': 'gallery', 'title': clean_value(name), 'highlight': '',
        'description': '', 'gallery_layout': 'staggered',
        'gallery_images': [asset_stub(s) for s in srcs],
        'gallery_categories': [], 'media_cards': [], 'video_items': [],
        'video_title': '', 'video_description': '', 'video_layout': 'stacked',
        'video_url': link_stub(), 'thumbnail': asset_stub(''),
        'bg_pattern': asset_stub(''), 'pattern_opacity': False,
        'pattern_position': '', 'auto_play': False, 'show_controls': True,
        'cta_label': '', 'cta_link': link_stub(),
        'spacing': '', 'spacing_preset': PRESET,
    }


def accordion_blok(serial, idx, w, images):
    """An accordion list -> info_accordion, each panel a real rich_text.

    `info_accordion_item` has BOTH a `content` textarea and a `body` bloks field
    whitelisted to `rich_text`. The first version used `content`, which flattens
    the panel to a single string -- every link, list, heading and picture inside
    it gone. These panels are the whole body of the residency and research
    pages, so that was most of their content arriving as grey prose.

    The `body` slot is not in the committed component catalog; the catalog was
    snapshotted before the field existed, which is why it was missed. Read the
    live schema, not the CSV.
    """
    items = []
    for i, it in enumerate(sorted(w['data'], key=lambda x: x.get('order') or 0)):
        soup = BeautifulSoup(it['body'] or '', 'html.parser')
        for x in soup.find_all(['script', 'style']):
            x.decompose()
        nodes = []
        for child in list(soup.children):
            nodes += block(child, images)
        nodes = split_breaks(nodes)
        panel = []
        if nodes:
            panel = [{'_uid': uid(f'{serial}-accrt-{idx}-{i}'), 'component': 'rich_text',
                      'content': {'type': 'doc', 'content': nodes},
                      'drop_cap': False, 'spacing': '', 'spacing_preset': PRESET}]
        items.append({'_uid': uid(f'{serial}-acc-{idx}-{i}'),
                      'component': 'info_accordion_item',
                      'title': clean_value(it['title']),
                      'eyebrow': '', 'columns': '',
                      'body': panel, 'content': '', 'cards': []})
    return {'_uid': uid(f'{serial}-acc-{idx}'), 'component': 'info_accordion',
            'items': items, 'columns': '', 'spacing': '', 'spacing_preset': PRESET}


def tiles_blok(serial, idx, w, images):
    """A tile row -> a link_card per tile: picture, blurb, and where it goes.

    These are what the live page shows as clickable cards -- Publications is
    eight of them. Rendering them as prose loses both the picture and the link,
    which is the entire point of a tile.
    """
    items = []
    for i, t in enumerate(sorted(w['data'], key=lambda x: x.get('order') or 0)):
        if t.get('image'):
            images.append(t['image'])
        url = t.get('cta_url') or ''
        items.append({
            '_uid': uid(f'{serial}-tile-{idx}-{i}'), 'component': 'row_item',
            'body': [{
                '_uid': uid(f'{serial}-lc-{idx}-{i}'), 'component': 'link_card',
                'title': clean_value(t.get('title')),
                'description': clean_value(t.get('description')),
                'image': asset_stub(t.get('image') or '', clean_value(t.get('title'))),
                'cta_label': clean_value(t.get('cta_label')) or 'See More',
                'link': {'id': '', 'url': url, 'linktype': 'url',
                         'fieldtype': 'multilink', 'cached_url': url,
                         'target': '_blank'},
                'spacing': '', 'spacing_preset': PRESET}],
            'alignment': 'start', 'width_mode': 'fit', 'spacing': '',
            'background_color': {'_uid': uid(f'{serial}-tbg-{idx}-{i}'),
                                 'color': '#ffffff',
                                 'plugin': 'native-color-picker'}})
    # ReadTiles' fourth argument is a column-count hint ('Three', 'Four'), NOT a
    # heading -- using it put the word "Three" above eight card rows on the
    # Publications page. Only galleryapp's fourth argument is a real title.
    return {'_uid': uid(f'{serial}-tiles-{idx}'), 'component': 'row',
            'items': items, 'title': '', 'highlight': '',
            'description': '', 'alignment': 'center', 'on_mobile_wrap': 'True',
            'spacing': '', 'spacing_preset': PRESET,
            'background_color': {'_uid': uid(f'{serial}-tilesbg-{idx}'),
                                 'color': '', 'plugin': 'native-color-picker'}}


def drop_echoed_title(nodes, title):
    """Remove a leading heading that just repeats the page title.

    The hero already shows it. SharePoint pages open with their own <h1>, so
    every page was printing its name twice, once large and once again directly
    underneath.
    """
    want = re.sub(r'[^a-z0-9]+', '', (title or '').lower())
    if not want:
        return nodes
    for i, n in enumerate(nodes[:2]):
        if n.get('type') != 'heading':
            continue
        got = re.sub(r'[^a-z0-9]+', '', flat_text(n).lower())
        if got and (got == want or got in want or want in got):
            return nodes[:i] + nodes[i + 1:]
    return nodes


def people_as_split(serial, seq, cells_html, images):
    """A person with a long biography is a split_section, not a card.

    A profile_card shows a name, a role and a line -- give it six hundred words
    and it is unreadable. Measured per grid: when the average cell runs past 400
    characters these become picture-beside-text sections instead.
    """
    out = []
    for i, cell in enumerate(cells_html):
        img = cell.find('img')
        src = (img.get('src') or '') if img else ''
        if src and not CHROME.search(src):
            images.append(src)
        else:
            src = ''
        bolds = [clean_value(b.get_text(' ', strip=True))
                 for b in cell.find_all(['strong', 'b', 'h3', 'h4'])]
        bolds = [b for b in bolds if b]
        name = bolds[0] if bolds else ''
        body = clean_value(cell.get_text(' ', strip=True))
        for b in bolds[:1]:
            body = body.replace(b, '', 1)
        out.append({'_uid': uid(f'{serial}-pss-{seq}-{i}'),
                    'component': 'split_section',
                    'title': name, 'highlight': '',
                    'description': re.sub(r'\s+', ' ', body).strip()[:2000],
                    'image': asset_stub(src, name), 'image_fit': 'cover',
                    'image_variant': 'default',
                    'layout': 'default' if i % 2 == 0 else 'reverse',
                    'cta_label': '', 'cta_link': link_stub(),
                    'secondary_cta_label': '', 'secondary_cta_link': link_stub(),
                    'decorative_images': [], 'decorative_images_fit': 'cover',
                    'bg_color': {'_uid': uid(f'{serial}-pssbg-{seq}-{i}'),
                                 'color': '', 'plugin': 'official-colorpicker'},
                    'spacing': '', 'spacing_preset': PRESET})
    return out


def overlay_cards(serial, seq, cell, images):
    """AKU's overlay tile -> link_card.

        div.containerimg1 > img.image1
                          + div.text2      (the tile's name)
                          + div.overlay1 > a.button  (the blurb, and where it goes)

    Rendered as prose this collapses into a stray caption and a sentence that
    looks like a link; it is a card, so it becomes one.
    """
    tiles = cell.select('div.containerimg1')
    if not tiles:
        return None
    items = []
    for i, t in enumerate(tiles):
        img = t.find('img')
        src = (img.get('src') or '') if img else ''
        if src and not CHROME.search(src):
            images.append(src)
        else:
            src = ''
        cap = t.select_one('div.text2')
        title = clean_value(cap.get_text(' ', strip=True)) if cap else ''
        a = t.select_one('a')
        desc = clean_value(a.get_text(' ', strip=True)) if a else ''
        href = (a.get('href') or '').strip() if a else ''
        if href:
            href = html.unescape(href).translate(page_titles.TRANSLATION).strip()
        if not (title or desc or src):
            continue
        items.append({
            '_uid': uid(f'{serial}-ov-{seq}-{i}'), 'component': 'row_item',
            'body': [{'_uid': uid(f'{serial}-ovc-{seq}-{i}'), 'component': 'link_card',
                      'title': title or desc[:60],
                      'description': desc if title else '',
                      'image': asset_stub(src, title),
                      'cta_label': 'Read More' if href else '',
                      'link': {'id': '', 'url': href, 'linktype': 'url',
                               'fieldtype': 'multilink', 'cached_url': href,
                               'target': '_blank'},
                      'spacing': '', 'spacing_preset': PRESET}],
            'alignment': 'start', 'width_mode': 'fit', 'spacing': '',
            'background_color': {'_uid': uid(f'{serial}-ovbg-{seq}-{i}'),
                                 'color': '', 'plugin': 'native-color-picker'}})
        t.decompose()
    if not items:
        return None
    return {'_uid': uid(f'{serial}-ovrow-{seq}'), 'component': 'row',
            'items': items, 'title': '', 'highlight': '', 'description': '',
            'alignment': 'center', 'on_mobile_wrap': 'True', 'spacing': '',
            'spacing_preset': PRESET,
            'background_color': {'_uid': uid(f'{serial}-ovrowbg-{seq}'),
                                 'color': '', 'plugin': 'native-color-picker'}}


def image_beside_text(serial, seq, cell, images):
    """`div.row > col-md-3 (picture) + col-md-9 (heading and blurb)`.

    A narrow image column beside a wide text column is a split_section by any
    other name. Six of these sit on the News & Views page, one per story.
    """
    out = []
    rows = [d for d in cell.select('div.row')
            if d.select_one('div[class*=col-md-3] img')
            and d.select_one('div[class*=col-md-9]')]
    for i, r in enumerate(rows):
        img = r.select_one('div[class*=col-md-3] img')
        src = (img.get('src') or '') if img else ''
        if not src or CHROME.search(src):
            src = ''
        # NOTE: the image is recorded only once this row is known to produce a
        # section (below). Appending first and skipping afterwards uploaded two
        # pictures that appear on no page -- the same append-before-deciding
        # mistake that cost the Certification page its text.
        body = r.select_one('div[class*=col-md-9]')
        head = body.find(['h1', 'h2', 'h3', 'h4', 'h5']) if body else None
        title = clean_value(head.get_text(' ', strip=True)) if head else ''
        if head:
            head.extract()
        text = clean_value(body.get_text(' ', strip=True)) if body else ''
        link = body.find('a') if body else None
        href = (link.get('href') or '').strip() if link else ''
        if href:
            href = html.unescape(href).translate(page_titles.TRANSLATION).strip()
        if not (title or text):
            continue
        if src:
            images.append(src)
        out.append({'_uid': uid(f'{serial}-ibt-{seq}-{i}'),
                    'component': 'split_section',
                    'title': title, 'highlight': '', 'description': text[:2000],
                    'image': asset_stub(src, title), 'image_fit': 'cover',
                    'image_variant': 'default',
                    'layout': 'default' if i % 2 == 0 else 'reverse',
                    'cta_label': 'Read More' if href else '',
                    'cta_link': {'id': '', 'url': href, 'linktype': 'url',
                                 'fieldtype': 'multilink', 'cached_url': href,
                                 'target': '_blank'} if href else link_stub(),
                    'secondary_cta_label': '', 'secondary_cta_link': link_stub(),
                    'decorative_images': [], 'decorative_images_fit': 'cover',
                    'bg_color': {'_uid': uid(f'{serial}-ibtbg-{seq}-{i}'),
                                 'color': '', 'plugin': 'official-colorpicker'},
                    'spacing': '', 'spacing_preset': PRESET})
        r.decompose()
    return out


# aku.edu URL -> the Storyblok path we migrated it to. Built from the tracking
# CSV, so it only ever claims a page that actually exists in the space.
_DEST_CACHE = {}


def _norm_url(u):
    """Compare on host+path, lowercased. Query strings and the scheme differ
    between how a link is written and how the sheet records it."""
    u = (u or '').strip().lower()
    u = re.sub(r'^https?://(www\.)?', '', u)
    return u.split('?')[0].split('#')[0].rstrip('/')


def migrated_dest(href):
    """The Storyblok path for an aku.edu link, or '' if it is not migrated yet."""
    if not _DEST_CACHE:
        _DEST_CACHE['__loaded__'] = ''
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), 'out', 'rabee-pages-links-v2.csv')
        if os.path.exists(path):
            import csv as _csv
            with open(path, encoding='utf-8') as fh:
                for row in _csv.DictReader(fh):
                    k = _norm_url(row.get('aku_link'))
                    if k and row.get('storyblok_path'):
                        _DEST_CACHE[k] = row['storyblok_path']
    return _DEST_CACHE.get(_norm_url(href), '')


def cta_from(cell):
    """The banner's own call-to-action: (label, link field).

    Rabee added this to allied-health/home after first leaving it empty, so the
    button IS carried over -- lowercased, the way he typed it.

    An internal target becomes a `story` link to the migrated page. Leaving it
    as an aku.edu URL would publish a link that stops working the day the old
    site is switched off, and this one -- chairs-message -- is a page we are
    migrating ourselves.
    """
    a = cell.select_one('a.button-hero') or cell.select_one('.button-position a, '
                                                            '.button-position-circle a, '
                                                            '.button-position-circle-right a')
    if a is None:
        return '', link_stub()
    label = clean_value(a.get_text(' ', strip=True))
    if not label:
        return '', link_stub()
    href = html.unescape((a.get('href') or '').strip()).translate(
        page_titles.TRANSLATION).strip()
    if not href:
        return label.lower(), link_stub()
    dest = migrated_dest(href)
    if dest:
        return label.lower(), {'id': '', 'url': '', 'linktype': 'story',
                               'fieldtype': 'multilink', 'cached_url': dest}
    return label.lower(), {'id': '', 'url': href, 'linktype': 'url',
                           'fieldtype': 'multilink', 'cached_url': href,
                           'target': '_blank'}


# `BottomPane1`, `BottomPane2`, `BottomPane3` -- AKU's three footer columns.
# Anchored at both ends: `ContentBottomPane` is the MAIN content pane and is a
# different thing entirely, and matching it would sweep the body of the page
# into the footer row.
BOTTOM_PANE = re.compile(r'^BottomPane([1-9])$')


def pane_index(cell):
    """Which footer column this webpart cell sits in, or None."""
    node = cell
    while node is not None and getattr(node, 'get', None):
        for c in (node.get('class') or []):
            m = BOTTOM_PANE.match(c)
            if m:
                return int(m.group(1))
        node = node.parent
    return None


def pane_row(serial, seq, panes, images):
    """The footer columns -> one row of row_items, in column order.

    Shape copied field for field from Rabee's own edit of allied-health/home:
    the row carries `spacing_preset: section` and the rich_text inside each item
    carries `zero`, which is the same pairing he uses for a row of buttons -- the
    row owns the spacing, the thing inside it adds none.
    """
    items = []
    for n, (idx, cell) in enumerate(sorted(panes, key=lambda p: p[0])):
        nodes = []
        for child in list(cell.children):
            nodes += block(child, images)
        nodes = split_breaks(nodes)
        nodes = [x for x in nodes if x]
        if not nodes:
            continue
        items.append({
            '_uid': uid(f'{serial}-pane-{seq}-{n}'), 'component': 'row_item',
            'body': [{'_uid': uid(f'{serial}-panert-{seq}-{n}'),
                      'component': 'rich_text',
                      'content': {'type': 'doc', 'content': nodes},
                      'drop_cap': False, 'spacing': '', 'spacing_preset': 'zero'}],
            'alignment': 'start', 'width_mode': 'auto', 'spacing': '',
            'background_color': {'_uid': uid(f'{serial}-panebg-{seq}-{n}'),
                                 'color': '#ffffff',
                                 'plugin': 'native-color-picker'}})
    if len(items) < 2:
        return None              # one column is not a row; leave it as prose
    return {'_uid': uid(f'{serial}-panerow-{seq}'), 'component': 'row',
            'items': items, 'title': '', 'highlight': '', 'description': '',
            'alignment': 'start', 'on_mobile_wrap': False, 'spacing': '',
            'spacing_preset': 'section',
            'background_color': {'_uid': uid(f'{serial}-panerowbg-{seq}'),
                                 'color': '#ffffff',
                                 'plugin': 'native-color-picker'}}


def name_only(line):
    """"Dr Robyna Irshad Khan, Associate Dean Allied Health" -> the name.

    The banner's heading already carries the role ("Associate Dean's Message"),
    so keeping the whole line printed it twice -- Rabee trimmed it by hand.

    Trimmed only when the line is plainly "Name, Role": a comma, with a short
    lead-in and no sentence punctuation before it. A kicker without a comma
    ("Every Gift Matters") is left exactly as it is.
    """
    if ',' not in line:
        return line
    head = line.split(',', 1)[0].strip()
    if not head or len(head) > 60 or re.search(r'[.:;!?]', head):
        return line
    if not (1 < len(head.split()) <= 6):
        return line
    return head


def banner_splits(serial, seq, cell, images):
    """AKU's full-width picture-and-message banner -> split_section.

    Keyed on `.title1`, which is the one part every variant of this webpart has
    -- the circular portrait, the square photograph and the plain text variant all
    carry it. The earlier rule keyed on `chairsmsg|pic-circle`, which is the
    CIRCULAR variant only, so CITRIC's two square banners never reached it and
    were flattened into paragraphs.

    Field mapping is read off the two pages Rabee corrected by hand:
      .title1     -> title
      .div-pad-bot  -> highlight   (only when a further block follows it)
      .div-pad-bot2 -> description
    and `image_variant` is `circles` exactly when the picture is round.

    The LEARN MORE / READ MORE in `.button-position` IS carried over, into the
    split_section's own CTA -- Rabee added it to allied-health/home on 16 Sep
    after first leaving it out. Where it points at a page we have migrated, it
    is wired to that story instead of to aku.edu.
    """
    out = []
    for i, head in enumerate(cell.select('.title1')):
        row = head
        for _ in range(6):                    # climb to the row holding the image
            if row.parent is None:
                break
            row = row.parent
            if row.find('img') is not None and 'row' in (row.get('class') or []):
                break
        else:
            continue
        if row is None or row.find('img') is None:
            continue

        title = clean_value(head.get_text(' ', strip=True))
        blocks = []
        for d in row.select('.div-pad-bot, .div-pad-bot2'):
            if d is head or 'title1' in (d.get('class') or []):
                continue
            if 'displaynone' in (d.get('class') or []):
                continue          # SharePoint's own way of switching a line off
            t = clean_value(d.get_text(' ', strip=True))
            if t and t not in blocks:
                blocks.append(t)
        if not (title or blocks):
            continue

        # One block is the message. Two means the first is a name and role, or
        # a kicker -- that is the line that belongs in `highlight`.
        highlight = name_only(blocks[0]) if len(blocks) > 1 else ''
        body = ' '.join(blocks[1:]) if len(blocks) > 1 else (blocks[0] if blocks else '')

        img = row.find('img')
        src = (img.get('src') or '') if img else ''
        if src and not CHROME.search(src):
            images.append(src)
        else:
            src = ''
        circular = bool(row.select('.pic-circle, .pic-circle-right'))
        cta_label, cta_link = cta_from(row)

        out.append({'_uid': uid(f'{serial}-ban-{seq}-{i}'),
                    'component': 'split_section',
                    'title': title, 'highlight': highlight,
                    'description': body[:2000],
                    'image': asset_stub(src, title), 'image_fit': 'cover',
                    'image_variant': 'circles' if circular else 'default',
                    'layout': 'default',
                    'cta_label': cta_label, 'cta_link': cta_link,
                    'secondary_cta_label': '', 'secondary_cta_link': link_stub(),
                    'decorative_images': [], 'decorative_images_fit': 'cover',
                    'bg_color': {'_uid': uid(f'{serial}-banbg-{seq}-{i}'),
                                 'color': '', 'plugin': 'official-colorpicker'},
                    'spacing': '', 'spacing_preset': PRESET})
        row.decompose()
    return out


def aku_tabs(cell):
    """`div.AKUTabs` -> [(label, pane)] in tab order, or [].

    This tab strip is rendered into the page itself, unlike the ReadTabs webpart,
    so nothing in the widget recovery sees it. Three pages are built almost
    entirely out of one -- Publications, CGSC and Our Mentors and Team all looked
    empty because their whole body lives inside the panes.
    """
    out = []
    for wrap in cell.select('div.AKUTabs'):
        labels = {}
        for a in wrap.select('ul.nav-tabs a[href^="#"]'):
            labels[a.get('href')[1:]] = clean_value(a.get_text(' ', strip=True))
        for pane in wrap.select('div.tab-content > div.tab-pane'):
            pid = pane.get('id') or ''
            out.append((labels.get(pid, ''), pane))
        wrap.extract()
    return out


def flat_text(n):
    if isinstance(n, dict):
        if n.get('type') == 'text':
            return n.get('text', '')
        return ' '.join(flat_text(c) for c in (n.get('content') or []))
    if isinstance(n, list):
        return ' '.join(flat_text(c) for c in n)
    return ''


def lift_title(nodes, title, body):
    """Promote a bolded opening run to the section's title.

    A split_section has a title field and a description field; running the two
    together as one paragraph wastes the first and buries the second. The source
    marks the heading with <strong> as often as with <h3>, and only the <h3> case
    was being caught -- so "MBBS Class of 1998 We extend our sincere thanks to
    the MBBS Class of 1998 for their generous contribution..." arrived as a
    single blob. Rabee split exactly that by hand on ccbp/home.
    """
    if title:
        return title, body
    for n in nodes:
        for frag in (n.get('content') or []):
            if frag.get('type') != 'text':
                continue
            marks = {m.get('type') for m in (frag.get('marks') or [])}
            lead = (frag.get('text') or '').strip()
            if 'bold' in marks and 2 < len(lead) <= 70:
                if body.startswith(lead):
                    body = body[len(lead):].strip()
                return clean_value(lead), body
            return title, body          # first fragment is not a heading
    return title, body


def split_section_of(serial, seq, nodes, zone_imgs):
    """One picture beside one blurb reads as a split_section. Longer stays prose.

    `split_section.description` is a plain textarea, so pushing a long body
    through it would drop every link, list and heading inside it. The length gate
    is the whole safety of this.
    """
    chars = len(flat_text(nodes))
    heads = [n for n in nodes if n.get('type') == 'heading']
    if len(zone_imgs) != 1 or not (120 <= chars <= 700) or len(heads) > 1:
        return None
    head_node = heads[0] if heads else None
    title = clean_value(flat_text(head_node)) if head_node else ''
    body = clean_value(' '.join(flat_text(n) for n in nodes if n is not head_node))
    title, body = lift_title(nodes, title, body)
    if not body:
        return None
    return {'_uid': uid(f'{serial}-ss-{seq}'), 'component': 'split_section',
            'title': title, 'highlight': '', 'description': body,
            'image': asset_stub(zone_imgs[0]), 'image_fit': 'cover',
            'image_variant': 'default',
            'layout': 'default' if seq % 2 == 0 else 'reverse',
            'cta_label': '', 'cta_link': link_stub(),
            'secondary_cta_label': '', 'secondary_cta_link': link_stub(),
            'decorative_images': [], 'decorative_images_fit': 'cover',
            'bg_color': {'_uid': uid(f'{serial}-ssbg-{seq}'), 'color': '',
                         'plugin': 'official-colorpicker'},
            'spacing': '', 'spacing_preset': PRESET}


def build(serial, title, widgets):
    raw = open(os.path.join(HTML_DIR, f'{serial}.html'), encoding='utf-8').read()
    soup = BeautifulSoup(raw, 'html.parser')
    own = page_titles.short(soup.title.get_text(strip=True) if soup.title else '')
    title = own or clean_value(title)
    # A slug-shaped title is the file name, not the page's name.
    if SLUGGY.match(title or ''):
        better = title_from_body(body_of(soup))
        if better:
            title = better

    images = []
    hero_src = hero_image_of(raw)
    if not hero_src:
        # A page whose first webpart is nothing but a picture is showing its
        # banner -- hdsc-alumni is one, and its hero was coming out blank.
        for c in body_of(soup):
            if c.get_text(' ', strip=True):
                break
            im = c.find('img')
            cand = (im.get('src') or '') if im else ''
            if cand and not CHROME.search(cand):
                hero_src = cand
                break
    if hero_src and not wide_enough_for_hero(hero_src):
        hero_src = ''          # too small; a stretched thumbnail looks broken
    if hero_src:
        images.append(hero_src)
    bloks = [{'_uid': uid(f'{serial}-hero'), 'component': 'hero',
              'image': asset_stub(hero_src, title), 'title': clean_value(title),
              'slides': [], 'variant': 'tertiary', 'subtitle': '',
              'cta_label': '', 'image_fit': 'cover', 'cta_link': link_stub()}]

    page_video = video_url_of(raw)
    cells = body_of(soup)
    by_div = {w['div']: w for w in widgets}
    # A cell that HOLDS a widget must be walked into, not treated as one section,
    # or the widget inside it is never reached.
    zones = [c for c in cells
             if not any((d.get('id') or '') in by_div for d in c.find_all('div'))]
    zone_ids = {id(z) for z in zones}

    # Walk the document ONCE, stopping at a text zone or a widget div, so the two
    # interleave exactly as the reader sees them. Appending widgets at the end --
    # what the first version did -- put every gallery in the wrong place: the
    # live Allied Health Events page is text, gallery, text, gallery.
    ordered = []

    def collect(node):
        if not isinstance(node, Tag):
            return
        if id(node) in zone_ids:
            ordered.append(('zone', node))
            return
        nid = node.get('id')
        if nid and nid in by_div:
            ordered.append(('widget', by_div[nid]))
            return
        for c in node.children:
            collect(c)

    collect(soup.body or soup)
    placed = {w['div'] for k, w in ordered if k == 'widget'}

    doc, seq = [], 0

    def flush():
        nonlocal doc, seq
        if not doc:
            return
        body_nodes = split_breaks(doc)
        if not any(b['component'] == 'rich_text' for b in bloks):
            body_nodes = drop_echoed_title(body_nodes, title)
        bloks.append({'_uid': uid(f'{serial}-rt-{seq}'), 'component': 'rich_text',
                      'content': {'type': 'doc', 'content': body_nodes},
                      'drop_cap': False, 'spacing': '', 'spacing_preset': PRESET})
        doc, seq = [], seq + 1

    def widget_blok(w, n):
        if w['kind'] == 'gallery':
            return gallery_blok(serial, n, w.get('title') or w['list'], w['data'], images)
        if w['kind'] in ('accordion', 'tabs'):
            return accordion_blok(serial, n, w, images)
        return tiles_blok(serial, n, w, images)

    # The footer columns are held back and emitted together at the end, which
    # is where they sit on the page anyway -- three separate full-width blocks
    # is not what the reader sees.
    footer_panes = []
    for kind, thing in ordered:
        if kind == 'zone':
            pi = pane_index(thing)
            if pi is not None:
                footer_panes.append((pi, thing))
                continue

        if kind == 'widget':
            flush()
            bloks.append(widget_blok(thing, len(bloks)))
            continue

        if thing.find('iframe') and page_video:
            flush()
            bloks.append(video_blok(serial, seq, page_video))
            seq += 1
            page_video = ''          # one player per page, placed where it sits
            continue

        bans = banner_splits(serial, seq, thing, images)
        if bans:
            flush()
            bloks.extend(bans)
            seq += 1

        if AUTHOR_HINT.search(str(thing)) and thing.find('img') is not None:
            flush()
            bloks.append(author_blok(serial, seq, thing, images))
            seq += 1
            # No trailing button. The webpart's LEARN MORE belongs to the
            # banner, and Rabee left the CTA empty on both pages he corrected;
            # emitting it produced a stray button under the message.
            continue

        # Pull the call-to-action links OUT before converting the prose, so a
        # LEARN MORE becomes a button instead of appearing twice -- once as a
        # button and once as a sentence fragment in the paragraph above it.
        btns = button_bloks(serial, seq, thing)
        if btns:
            for a in list(thing.find_all('a')):
                if is_button_link(a):
                    a.decompose()

        # A people grid can sit several divs deep inside a webpart cell, so it is
        # searched for rather than expected as a direct child -- looking only at
        # the cell's own children silently turned every team page back into a
        # plain table.
        # picture-beside-text tables become split_sections, not a bordered grid
        for tbl in [t for t in thing.find_all('table')
                    if not is_people_grid(t) and is_image_text_table(t)]:
            made = table_as_splits(serial, seq, tbl, images)
            if made:
                flush()
                bloks.extend(made)
                seq += 1
                tbl.decompose()

        for grid in [t for t in thing.find_all('table') if is_people_grid(t)]:
            flush()
            gcells = [c for r in grid.find_all('tr')
                      for c in r.find_all(['td', 'th']) if c.find('img')]
            avg = (sum(len(c.get_text(' ', strip=True)) for c in gcells)
                   / max(1, len(gcells)))
            if avg > 400:
                bloks.extend(people_as_split(serial, seq, gcells, images))
                seq += 1
                grid.decompose()
                continue
            items = [{'_uid': uid(f'{serial}-ri-{seq}-{i}'), 'component': 'row_item',
                      'body': [profile_from_cell(c, images, f'{serial}-{seq}-{i}')],
                      'alignment': 'start', 'width_mode': 'fit', 'spacing': '',
                      'background_color': {'_uid': uid(f'{serial}-bg-{seq}-{i}'),
                                           'color': '#ffffff',
                                           'plugin': 'native-color-picker'}}
                     for i, c in enumerate(gcells)]
            bloks.append({'_uid': uid(f'{serial}-row-{seq}'), 'component': 'row',
                          'items': items, 'title': '', 'highlight': '',
                          'description': '', 'alignment': 'center',
                          'on_mobile_wrap': 'True', 'spacing': '',
                          'spacing_preset': PRESET,
                          'background_color': {'_uid': uid(f'{serial}-rowbg-{seq}'),
                                               'color': '',
                                               'plugin': 'native-color-picker'}})
            seq += 1
            grid.decompose()

        # AKU's own section shapes, taken off the markup Rabee pointed at.
        for label, pane in aku_tabs(thing):
            flush()
            if label:
                doc.append({'type': 'heading', 'attrs': {'level': 2},
                            'content': [{'type': 'text', 'text': label}]})
            for ch in list(pane.children):
                doc += block(ch, images)
            flush()

        ov = overlay_cards(serial, seq, thing, images)
        if ov:
            flush()
            bloks.append(ov)
            seq += 1

        for ss in image_beside_text(serial, seq, thing, images):
            flush()
            bloks.append(ss)
            seq += 1

        # Picture-then-biography: faculty and alumni pages lay people out with
        # no table at all, so the people-grid rule never sees them.
        #
        # This decides BEFORE it touches the tree. The first version extracted
        # each group and then dropped any under 80 characters -- on the
        # Certification page, which is one article with three inline pictures and
        # no people at all, that destroyed 2,395 of its 2,548 characters. A rule
        # that rearranges content must prove the shape first and keep every part.
        cell_imgs = [i for i in thing.find_all('img')
                     if (i.get('src') or '') and not CHROME.search(i.get('src') or '')]
        if len(cell_imgs) >= 3 and not thing.find('table'):
            groups, cur = [], None
            for el in thing.find_all(['p', 'div', 'h3', 'h4']):
                if el.find(['p', 'div']):
                    continue
                if el.find('img'):
                    if cur is not None:
                        groups.append(cur)
                    cur = [el]
                elif cur is not None:
                    cur.append(el)
            if cur is not None:
                groups.append(cur)

            def looks_like_person(g):
                txt = ' '.join(e.get_text(' ', strip=True) for e in g)
                named = any(e.find(['strong', 'b', 'h3', 'h4']) for e in g)
                return named and len(txt) >= 80

            named = [g for g in groups if looks_like_person(g)]
            # Most groups must look like a person -- a name in bold beside a
            # picture. An article that merely contains pictures (the
            # Certification page) has none, and must not be cut up. Every group
            # is then emitted, person-shaped or not, so nothing is discarded.
            if len(groups) >= 3 and len(named) >= max(3, int(len(groups) * 0.7)):
                flush()
                for gi, g in enumerate(groups):
                    wrap = BeautifulSoup('<div></div>', 'html.parser').div
                    for el in g:
                        wrap.append(el.extract())
                    bloks.extend(people_as_split(serial, f'{seq}-{gi}', [wrap], images))
                seq += 1
                continue

        zone_imgs = []
        for child in thing.children:
            before = len(images)
            doc += block(child, images)
            zone_imgs += images[before:]

        ss = split_section_of(serial, seq, doc, zone_imgs) if doc else None
        if ss:
            bloks.append(ss)
            doc, seq = [], seq + 1
        else:
            flush()
        if btns:
            bloks.extend(btns)
    flush()

    if footer_panes:
        prow = pane_row(serial, seq, footer_panes, images)
        if prow:
            bloks.append(prow)
            seq += 1
        else:
            # A single filled column stays what it was rather than becoming a
            # one-item row.
            for _, cell in sorted(footer_panes, key=lambda p: p[0]):
                for child in list(cell.children):
                    doc += block(child, images)
            flush()

    # Anything the walk could not place -- a div outside <body>, or a list the
    # page names but never renders -- is appended rather than dropped.
    #
    # EXCEPT when the same list is already on the page. Seven residency pages
    # carry two ReadAccordion() calls for one list and only ONE target div: the
    # webpart was deleted and its initialiser left behind, so the second call
    # finds no element and the live page draws one accordion. Appending it
    # published the whole accordion twice. An unplaced widget is only content if
    # nothing else already rendered that list.
    shown = {(w['kind'], w['list']) for w in widgets if w['div'] in placed}
    for i, w in enumerate(widgets):
        if w['div'] in placed:
            continue
        if (w['kind'], w['list']) in shown:
            continue                        # dead initialiser, not a webpart
        bloks.append(widget_blok(w, 900 + i))

    if page_video:
        bloks.append(video_blok(serial, 900, page_video))

    # Split sections alternate down the page: picture left, right, left. Each
    # rule was choosing its own side in isolation, so two neighbours produced by
    # different rules could both land the same way. Rabee flipped one by hand on
    # ccbp/home; this makes the zig-zag a property of the page, not of the rule.
    flip = 0
    for b in bloks:
        if b.get('component') == 'split_section':
            b['layout'] = 'default' if flip % 2 == 0 else 'reverse'
            flip += 1

    return bloks, [i for i in images if i], title


def payload_text(node):
    """Every word a reader will see, from anywhere in the payload."""
    out = []

    def walk(x):
        if isinstance(x, dict):
            if x.get('type') == 'text' and x.get('text'):
                out.append(x['text'])
            for k in ('title', 'description', 'subtitle', 'content', 'label',
                      'bio', 'role', 'author_name', 'highlight', 'quote'):
                v = x.get(k)
                if isinstance(v, str) and v.strip():
                    out.append(v)
            for v in x.values():
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(node)
    return re.sub(r'\s+', ' ', ' '.join(out)).strip()


def source_text_len(serial):
    """Characters in the page's own visible webpart cells."""
    soup = BeautifulSoup(
        open(os.path.join(HTML_DIR, f'{serial}.html'), encoding='utf-8').read(),
        'html.parser')
    cells = body_of(soup)
    return len(re.sub(r'\s+', ' ',
                      ' '.join(c.get_text(' ', strip=True) for c in cells)).strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', help='comma-separated serials')
    ap.add_argument('--limit', type=int)
    ap.add_argument('--skip-dupes', action='store_true',
                    help="skip pages Abdullah already built in the old tree")
    a = ap.parse_args()

    plan = json.load(open(paths.work('build_list_v2.json'), encoding='utf-8'))
    wpath = paths.work('page_widgets.json')
    widgets = json.load(open(wpath, encoding='utf-8')) if os.path.exists(wpath) else {}
    if a.skip_dupes:
        plan = [p for p in plan if not p.get('abdullah_dupe')]
    if a.only:
        want = set(a.only.split(','))
        plan = [p for p in plan if p['serial'] in want]
    if a.limit:
        plan = plan[:a.limit]

    out = []
    for p in plan:
        bloks, images, title = build(p['serial'], p['title'], widgets.get(p['serial'], []))
        out.append({**p, 'title': title, 'sheet_title': p['title'],
                    'bloks': bloks, 'images': images})
        kinds = {}
        for b in bloks:
            kinds[b['component']] = kinds.get(b['component'], 0) + 1
        shape = '+'.join(f'{v}x{k}' for k, v in kinds.items())
        print(f"  {p['serial']:>4}  {p['slug'][:32]:<34} {shape:<46} imgs={len(images)}")

    json.dump(out, open(OUT, 'w', encoding='utf-8', newline='\n'),
              indent=1, ensure_ascii=False)
    print(f'\n{len(out)} payloads -> {OUT}')
    print('images referenced:', sum(len(o['images']) for o in out),
          '| distinct:', len({i for o in out for i in o['images']}))

    # A page must carry its source text out the other side. Every rule here
    # rearranges the tree, and a rule that rearranges can silently delete: one
    # of them took the Certification page from 2,548 characters to 153 and
    # nothing said a word. Counting is cheap; finding it by eye was not.
    print('\nretention check (built text vs source text):')
    losses = []
    for o in out:
        src = source_text_len(o['serial'])
        got = len(payload_text(o['bloks']))
        if src > 300 and got < src * 0.7:
            losses.append((o['serial'], o['slug'], src, got))
    if losses:
        for sn, slug, src, got in losses:
            print(f'  *** {sn} {slug}: {got} of {src} chars kept '
                  f'({100 * got // src}%) -- CONTENT LOST')
        raise SystemExit(f'{len(losses)} page(s) lost content; not shipping these')
    print(f'  all {len(out)} pages keep at least 70% of their source text')


if __name__ == '__main__':
    main()
