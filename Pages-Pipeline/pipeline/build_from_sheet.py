"""build_from_sheet.py -- build Storyblok payloads for the rows of a migration sheet.

The rules here were measured, not guessed: 530 pages the team built BY HAND from
the 5 Nov 2026 sheet were read back from Storyblok and compared, page by page,
with the old aku.edu HTML they came from. COMPONENT-MAP.md has the numbers
behind every rule; the short reason sits beside the code that applies it.

The HTML -> rich-text conversion is build_pages.py's (Rabee's, Medical College),
reused rather than copied: nested lists, tables, images lifted out of
paragraphs, hidden webparts, the retention guard. What this file changes is what
the hand-built pages prove that builder gets wrong for the rest of the site:

* `info_accordion_item` has NO `body` or `content` field any more -- only
  `cards`. Every accordion panel build_pages.py writes is invisible. Here each
  panel is an `info_accordion_card` (variant rich_text), as people built 413.
* `split_section.description` is RICH TEXT now, and people put whole biographies
  and speeches in it. Not a 2,000-character string.
* `spacing_preset` is `section` at page level (people: section 204 vs
  subsection 169 for rich_text, 273 vs 75 for split_section); the hero is `zero`.
* The hero's title is the page's own <h1>, which is then removed from the body
  (336 / 319 of 383). A source <h2> becomes heading level 1, not 3.
* Pages carry `quick_actions` built from the left-hand side navigation and the
  "Related Links" list, at the end of the body (299 pages).
* Section chrome -- the "Explore Convocations Across Countries" strip, the Stay
  Connected banner, the side navigator -- is the same block on 57-92% of the
  pages in a folder. It is COPIED from the hand-built siblings, never invented.
* Speech and event pages are `speech_article` / `event_article` stories, with
  no hero and a body restricted to what that content type allows.

Inputs (out/work/):
    sheet_pages/html/<serial>.html, sheet_pages/widgets.json   fetch_sheet_pages.py
    reference_stories.json, components_live.json             fetch_reference.py
Writes out/work/sheet_payloads.json, read by upload_page_media.py and
create_pages.py with `--payloads sheet_payloads.json`.

Run:  python build_from_sheet.py --csv <sheet.csv> [--only 1909,1910]
"""
import argparse
import collections
import copy
import json
import os
import re

import build_pages as bp
import house_style as hs
import paths
import sheet
from bs4 import BeautifulSoup

PAGES_DIR = paths.work('sheet_pages')
OUT = paths.work('sheet_payloads.json')
PREP_DIR = paths.work('sheet_pages_prepared')

INVISIBLE = dict.fromkeys(map(ord, '​﻿­'), None)


def clean(t):
    return re.sub(r'\s+', ' ', (t or '').translate(INVISIBLE).replace('\xa0', ' ')).strip()


# ----------------------------------------------------------------- schema ---
class Schema:
    """The live component schemas: field names, option values, whitelists."""

    def __init__(self, path):
        self.c = {c['name']: c['schema'] for c in json.load(open(path, encoding='utf-8'))}

    def whitelist(self, comp, field='body'):
        f = self.c.get(comp, {}).get(field, {})
        return set(f.get('component_whitelist') or [])

    def sanitize(self, node):
        """Drop fields the live component no longer has, recursively.

        build_pages writes `pattern_opacity` on every gallery and `spacing` on
        everything; the space removed the first. A field the schema does not
        have is invisible in the editor and only confuses the next reader.
        """
        if isinstance(node, list):
            return [self.sanitize(x) for x in node]
        if not isinstance(node, dict) or 'component' not in node:
            return node
        sch = self.c.get(node['component'])
        if sch is None:
            return node
        return {k: self.sanitize(v) for k, v in node.items()
                if k in ('_uid', 'component') or k in sch}

    def problems(self, node, where='body'):
        """Every field a blok carries that its live component does not have,
        and every option value the component does not offer."""
        out = []
        if isinstance(node, list):
            for i, x in enumerate(node):
                out += self.problems(x, f'{where}[{i}]')
            return out
        if not isinstance(node, dict) or 'component' not in node:
            return out
        comp = node['component']
        sch = self.c.get(comp)
        if sch is None:
            return [f'{where}: unknown component {comp}']
        for k, v in node.items():
            if k in ('_uid', 'component'):
                continue
            f = sch.get(k)
            if f is None:
                if v not in ('', None, [], {}):
                    out.append(f'{where}.{comp}: no field `{k}`')
                continue
            if f.get('type') == 'option' and v not in ('', None):
                ok = {o.get('value') for o in f.get('options') or []}
                if ok and str(v) not in ok:
                    out.append(f'{where}.{comp}.{k}: {v!r} not in {sorted(ok)}')
            if f.get('type') == 'bloks' and isinstance(v, list):
                wl = set(f.get('component_whitelist') or [])
                for i, x in enumerate(v):
                    if wl and isinstance(x, dict) and x.get('component') not in wl:
                        out.append(f'{where}.{comp}.{k}[{i}]: {x.get("component")} '
                                   f'not allowed')
                out += self.problems(v, f'{where}.{comp}.{k}')
        return out


# ---------------------------------------------------------- root type -------
SPEECH_FILE = re.compile(r'speech|valedict|charter-acceptance|inauguration-|hh-ighd')


def root_type(old_url):
    """speech_article / event_article / page, from the old URL alone.

    Measured on the 530: the speech rule picks 121 of the 123 speech_articles;
    its 14 "false positives" are speeches built as `page` before the 2 Nov
    re-rooting pass and never converted. Every page under /events/ built since
    19 Oct is an event_article, conference sub-pages included.
    """
    u = old_url.lower()
    f = u.rsplit('/', 1)[-1]
    if re.search(r'/(convocation|about/chancellor)/', u) and SPEECH_FILE.search(f):
        return 'speech_article'
    if '/events/' in u:
        return 'event_article'
    return 'page'


# ------------------------------------------------------- prepare the HTML ---
RELATED = re.compile(r'^\s*related\s+links\s*:?\s*$', re.I)
COUNTRY_HOME = re.compile(r'/convocation/(ke|pk|tz|ug|uk)/pages/home\.aspx$', re.I)


def zone_cells(soup):
    cells = [d for d in soup.find_all('div') if (d.get('id') or '').startswith('MSOZoneCell')]
    return [c for c in cells if not any(p in cells for p in c.parents)]


def side_nav(soup, old_url):
    """The left-hand navigation, minus what people never kept.

    `#zz1_V4QuickLaunchMenu ul.root` holds one item -- the section root -- and
    the section's pages below it. Measured over 118 quick_actions built from it:
    order kept 118/118; the root dropped 115/118; "Contact Us" dropped 49/49 (it
    is the Stay Connected banner's button); "The Chancellor" dropped 45/45 in
    About; the country homes dropped 17/17 in Convocation (they are the
    "Explore Convocations" cards). The current page is NOT dropped (kept 12/15).
    """
    root = soup.select_one('[id$=V4QuickLaunchMenu] ul.root') or soup.select_one('ul.root.static')
    if root is None:
        return []
    top = root.find('li', recursive=False)
    sub = top.find('ul', recursive=False) if top else None
    out = []
    for li in (sub.find_all('li', recursive=False) if sub else []):
        a = li.find('a', recursive=False)
        if a is None:
            continue
        txt = a.select_one('.menu-item-text')
        label = clean((txt or a).get_text(' ', strip=True))
        href = sheet.absolute(a.get('href'))
        if not label or not a.get('href'):
            continue
        if label.lower() in ('contact us', 'contact'):
            continue
        if '/about/' in old_url.lower() and label.lower() == 'the chancellor':
            continue
        if '/convocation/' in old_url.lower() and COUNTRY_HOME.search(href):
            continue
        out.append((label, href))
    return out


def take_related_links(cells):
    """"Related Links" + the <ul> under it -> [(label, href)], removed from the page.

    104 pages carry one; 93 became quick_actions and the heading was removed
    from the prose on all 104.
    """
    out = []
    for cell in cells:
        for el in cell.find_all(['p', 'h2', 'h3', 'h4', 'h5', 'strong', 'b', 'div', 'span']):
            if el.find(['p', 'div', 'ul']) or not RELATED.match(clean(el.get_text(' '))):
                continue
            ul = el.find_next('ul')
            if ul is None or cell not in ul.parents:
                continue
            for a in ul.find_all('a'):
                label, href = clean(a.get_text(' ')), a.get('href')
                if label and href:
                    out.append((label, sheet.absolute(href)))
            block = el
            while block.parent is not None and block.parent is not cell and \
                    clean(block.parent.get_text(' ')) == clean(el.get_text(' ')):
                block = block.parent
            ul.decompose()
            block.decompose()
    return out


MARK = re.compile(r'@@EMBED@@(\S*)@@')


def mark_iframes(cells, page_video):
    """Swap every iframe in the content for a marker paragraph.

    build_pages.build() meets a webpart holding an iframe and replaces the WHOLE
    webpart with one video blok -- datafest-africa kept 67 of its 5,859
    characters that way. A marker keeps the text and the embed's position; it
    becomes a media_section (video) or an iframe blok where it sits. An empty
    src is the script-filled player, whose URL is the page's own video.
    """
    for c in cells:
        for fr in c.find_all('iframe'):
            src = (fr.get('src') or '').strip() or page_video
            p = BeautifulSoup(f'<p>@@EMBED@@{src}@@</p>', 'html.parser').p
            fr.replace_with(p)


def prepare(serial, raw, old_url):
    """Read what the body conversion must not see, and take it out.

    Returns (prepared_html, h1_text, nav_links, related_links). The prepared
    HTML is what build_pages.build() reads; scripts are kept because the widget
    wiring is read out of them. build() still finds the page video in them and
    appends it at the end -- build() below drops that copy when a marker has
    already placed the same URL.
    """
    soup = BeautifulSoup(raw, 'html.parser')
    nav = side_nav(soup, old_url)
    cells = zone_cells(soup)
    h1 = ''
    for c in cells:
        el = c.find('h1')
        if el is not None and clean(el.get_text(' ')):
            h1 = clean(el.get_text(' '))
            el.decompose()
            break
    related = take_related_links(cells)
    mark_iframes(cells, bp.video_url_of(raw))
    return str(soup), h1, nav, related


# --------------------------------------------------------- blok factories ---
PRESET = 'section'
bp.PRESET = PRESET          # every rule in build_pages reads this at call time


def doc(nodes):
    return {'type': 'doc', 'content': nodes}


def rich_text(seed, nodes, preset=PRESET):
    return {'_uid': bp.uid(seed), 'component': 'rich_text', 'content': doc(nodes),
            'drop_cap': False, 'spacing_preset': preset}


def text_doc(s):
    """A plain string -> a rich-text doc, one paragraph per blank-line block."""
    paras = [p.strip() for p in re.split(r'\n\s*\n', s or '') if p.strip()]
    return doc([{'type': 'paragraph', 'content': [{'type': 'text', 'text': p}]}
                for p in paras])


KEEP_TOGETHER = re.compile(r'(?:\bAga Khan|\bClass of \d{4}|\b[A-Z][a-z]+ [A-Z]\.?)$')


def split_heading(text):
    """"Address by His Highness the Aga Khan" -> ("Address by His Highness the ", "Aga Khan").

    title + highlight is ONE heading cut in two. The hand-built pages used the
    last word (68% of 432 pairs); "Aga Khan" / "Class of 2015" stay whole.
    The title keeps its trailing space (341 of 432).
    """
    t = clean(text)
    if not t:
        return '', ''
    m = KEEP_TOGETHER.search(t)
    if m and m.start() > 0:
        return t[:m.start()], t[m.start():]
    # Otherwise the house rule: the last meaningful phrase, as Abdullah
    # re-split the last-word ones by hand (10 Nov 2026) -- one rule, in house_style.
    return hs.split_heading(t)


def split_section(seed, title, nodes, src, layout='reverse'):
    chars = len(bp.flat_text(nodes))
    t, h = split_heading(title)
    return {'_uid': bp.uid(seed), 'component': 'split_section',
            'title': t, 'highlight': h, 'description': doc(nodes),
            'image': bp.asset_stub(src, title), 'image_fit': 'cover',
            # wrap when the text runs long: 158 of 160 over 1,000 characters,
            # default for 166 of 228 at or under. `circles` was used 0 times.
            'image_variant': 'wrap' if chars > 1000 else 'default',
            'layout': layout,
            'cta_label': '', 'cta_link': bp.link_stub(),
            'secondary_cta_label': '', 'secondary_cta_link': bp.link_stub(),
            'decorative_images': [], 'decorative_images_fit': 'cover',
            'bg_color': {'_uid': bp.uid(seed + '-bg'), 'color': '',
                         'plugin': 'official-colorpicker'},
            'spacing_preset': PRESET}


def _first_image(nodes):
    for n in nodes:
        if n.get('type') == 'image':
            return n
        hit = _first_image(n.get('content') or [])
        if hit:
            return hit
    return None


def accordion(seed, items):
    """[(title, nodes)] -> info_accordion > item > info_accordion_card.

    A panel with a picture is a `split_section` card -- the picture beside the
    rest of the text -- and one without is a `rich_text` card (Abdullah, QTL
    Teaching Tips, 6 Nov 2026). The accordion's own heading is left for a
    person to write: it has to say what the items below are about.
    """
    out = []
    for i, (title, nodes) in enumerate(items):
        nodes = hs.card_text(nodes or [])           # sub-headings H5, never bold
        card = {'_uid': bp.uid(f'{seed}-{i}-c'), 'component': 'info_accordion_card',
                'variant': 'rich_text', 'color': 'default', 'title': '', 'description': '',
                'rich_text': doc(nodes or [{'type': 'paragraph'}])}
        img = _first_image(nodes)
        if img is not None:
            src = (img.get('attrs') or {}).get('_src_original') or (img.get('attrs') or {}).get('src') or ''
            text = [n for n in without_images(copy.deepcopy(nodes)) if node_text(n)
                    or n.get('type') in ('table',)]
            ss = split_section(f'{seed}-{i}-ss', '', text, src, layout='default')
            ss['spacing_preset'] = 'section_no_x'
            card.update({'variant': 'split_section', 'split_section': [ss],
                         'rich_text': doc([])})
        out.append({'_uid': bp.uid(f'{seed}-{i}'), 'component': 'info_accordion_item',
                    'title': clean(title), 'eyebrow': '', 'columns': '1', 'cards': [card]})
    return {'_uid': bp.uid(seed), 'component': 'info_accordion', 'title': '',
            'highlight': '', 'items': out, 'spacing_preset': PRESET}


def widget_accordion(serial, idx, w, images):
    """Replaces build_pages.accordion_blok, which writes the dead `body` field."""
    items = []
    for it in sorted(w['data'], key=lambda x: x.get('order') or 0):
        soup = BeautifulSoup(it.get('body') or '', 'html.parser')
        for x in soup.find_all(['script', 'style']):
            x.decompose()
        nodes = []
        for child in list(soup.children):
            nodes += bp.block(child, images)
        items.append((it.get('title') or '', bp.split_breaks(nodes)))
    return accordion(f'{serial}-acc-{idx}', items)


def video_section(serial, seq, url):
    """Replaces build_pages.video_blok: people used `video` 0 times and
    `media_section` type video 22 times."""
    return {'_uid': bp.uid(f'{serial}-vid-{seq}'), 'component': 'media_section',
            'type': 'video', 'video_layout': 'featured', 'title': '', 'highlight': '',
            'description': '',
            'video_url': {'id': '', 'url': url, 'linktype': 'url',
                          'fieldtype': 'multilink', 'cached_url': url},
            'thumbnail': bp.asset_stub(''), 'thumbnail_fit': 'cover',
            'gallery_layout': 'staggered', 'gallery_images_fit': 'cover',
            'auto_play': False, 'show_controls': True,
            'cta_label': '', 'cta_link': bp.link_stub(), 'spacing_preset': PRESET}


_orig_buttons = bp.button_bloks


def centred_buttons(serial, seq, cell):
    """Same buttons, centred: row 71/73 and row_item 66/73 `center` by hand."""
    rows = _orig_buttons(serial, seq, cell)
    for r in rows:
        r['alignment'] = 'center'
        for it in r.get('items') or []:
            it['alignment'] = 'center'
    return rows


def without_images(nodes):
    out = []
    for n in nodes:
        if n.get('type') == 'image':
            continue
        if n.get('content'):
            n['content'] = without_images(n['content'])
        out.append(n)
    return out


def split_of_zone(serial, seq, nodes, zone_imgs):
    """Replaces build_pages.split_section_of.

    One picture beside its text is a split_section whatever the length --
    officer biographies run to 6 paragraphs and people kept every one, in a
    rich-text description. The old 120-700 character gate and the flattening
    to one string both go. A zone with lists or tables of its own, or more than
    one heading, stays prose.
    """
    if len(zone_imgs) != 1 or '@@EMBED@@' in bp.flat_text(nodes):
        return None
    # The picture is the section's image; it must not stay in the text too. It
    # can sit inside a paragraph here -- images are lifted out only later.
    body = bp.split_breaks(without_images(copy.deepcopy(nodes)))
    if len(bp.flat_text(body)) < 120:
        return None
    if any(n.get('type') in ('table', 'bullet_list', 'ordered_list') for n in body):
        return None
    heads = [n for n in body if n.get('type') == 'heading']
    # An officer page opens with two headings -- role, then place -- and
    # people put them in title and highlight: "Dean, Medical College" |
    # "Pakistan". Any other second heading means the zone is sectioned prose.
    if len(heads) == 2 and body[:2] == heads:
        ss = split_section(f'{serial}-ss-{seq}', '', body[2:], zone_imgs[0])
        ss['title'] = clean(bp.flat_text(heads[0])) + ' '
        ss['highlight'] = clean(bp.flat_text(heads[1]))
        return ss
    if len(heads) > 1:
        return None
    title = clean(bp.flat_text(heads[0])) if heads else ''
    body = [n for n in body if n is not (heads[0] if heads else None)]
    return split_section(f'{serial}-ss-{seq}', title, body, zone_imgs[0])


bp.accordion_blok = widget_accordion
bp.video_blok = video_section
bp.button_bloks = centred_buttons
bp.split_section_of = split_of_zone


# ------------------------------------------------------- body post-passes ---
def shift_headings(node):
    """build_pages maps <hN> to level N+1; people map <h2> to level 1.

    117 source h2s became H1 against 26 H2. Shifting by two puts h2 at 1 and h3
    at 2.
    """
    if isinstance(node, dict):
        if node.get('type') == 'heading':
            lv = (node.get('attrs') or {}).get('level') or 2
            node['attrs'] = {**(node.get('attrs') or {}), 'level': max(1, lv - 2)}
        for v in node.values():
            shift_headings(v)
    elif isinstance(node, list):
        for v in node:
            shift_headings(v)


def node_text(n):
    return clean(bp.flat_text(n))


def is_question(n):
    """A bold paragraph or a heading that asks something."""
    t = node_text(n)
    if not t.endswith('?') or len(t) > 250:
        return False
    if n.get('type') == 'heading':
        return True
    if n.get('type') != 'paragraph':
        return False
    texts = [c for c in n.get('content') or [] if c.get('type') == 'text' and c.get('text', '').strip()]
    return bool(texts) and all(any(m.get('type') == 'bold' for m in c.get('marks') or [])
                               for c in texts)


def plain_list(n):
    """A list of plain-text items: no links, no sub-lists, 2-14 items."""
    if n.get('type') not in ('bullet_list', 'ordered_list'):
        return None
    items = n.get('content') or []
    if not 2 <= len(items) <= 14:
        return None
    labels = []
    for it in items:
        kids = it.get('content') or []
        if len(kids) != 1 or kids[0].get('type') != 'paragraph':
            return None
        if any(m.get('type') == 'link' for c in kids[0].get('content') or []
               for m in c.get('marks') or []):
            return None
        t = node_text(kids[0])
        if not 10 <= len(t) <= 250:
            return None
        labels.append(t)
    return labels


def outcomes(seed, heading, intro, labels):
    """A titled list of plain items -> sub_inner_group (outcomes).

    Objectives, Themes, Benefits: 31 of 45 such lists were built this way, and
    the 14 that stayed bullet lists were mostly inside speeches.
    """
    t, h = split_heading(heading)
    return {'_uid': bp.uid(seed), 'component': 'sub_inner_group', 'variant': 'outcomes',
            'title': t, 'highlight': h, 'description': intro,
            'columns': '3' if max(len(x) for x in labels) < 40 else '2',
            'spacing_preset': PRESET,
            'outcome_items': [{'_uid': bp.uid(f'{seed}-{i}'),
                               'component': 'sub_inner_group_outcome_item', 'label': lb}
                              for i, lb in enumerate(labels)]}


def image_blok(seed, node):
    a = node.get('attrs') or {}
    src = a.get('_src_original') or a.get('src') or ''
    return {'_uid': bp.uid(seed), 'component': 'image', 'variant': 'hero',
            'image': bp.asset_stub(src, a.get('alt') or ''), 'image_fit': 'cover',
            'title': '', 'description': '', 'spacing_preset': 'subsection'}


# dacast does NOT play in media_section's video player -- only in an iframe blok
# (Research Magazine, 9 Nov 2026). YouTube and Vimeo go to media_section.
VIDEO_HOST = re.compile(r'youtube\.com|youtu\.be|vimeo\.com', re.I)


def embed_blok(seed, src):
    """A marked iframe -> media_section (video) or an iframe blok.

    Video players became media_section type video (22); prezi, flipbuilder and
    vzaar embeds became `iframe` bloks with these settings (7 of 7).
    """
    if VIDEO_HOST.search(src):
        return video_section(seed, 0, src)
    return {'_uid': bp.uid(seed), 'component': 'iframe', 'src': src, 'title': '',
            'display_mode': 'inline', 'layout': 'full', 'aspect_ratio': '16:9',
            'rounded': True, 'loading': 'lazy', 'allow_fullscreen': True,
            'show_play_overlay': True, 'content_align': 'left',
            'spacing_preset': PRESET}


def take_markers(node):
    """Remove every iframe marker from a node's text; return their srcs in order."""
    found = []

    def walk(x):
        if isinstance(x, dict):
            if x.get('type') == 'text' and '@@EMBED@@' in x.get('text', ''):
                found.extend(MARK.findall(x['text']))
                x['text'] = MARK.sub('', x['text'])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
            x[:] = [v for v in x if not (isinstance(v, dict) and v.get('type') == 'text'
                                         and not v.get('text'))]
    walk(node)
    return found


def explode_rich_text(serial, n, b, allowed, root, house=True):
    """One rich_text -> the bloks people made of the same content.

    * A picture standing between paragraphs is an `image` blok: people kept an
      image inside rich text 4 times in 428.
    * Three or more questions -> an accordion, one item per question (24/28).
    * A heading + optional intro + a plain list -> sub_inner_group (outcomes).
    * An iframe marker -> the embed, in place.

    Only components the story's content type accepts are made. A speech that
    asks three questions became an accordion, the speech whitelist then removed
    the accordion, and 7,100 characters went with it.
    """
    def ok(comp):
        return not allowed or comp in allowed

    nodes = b['content'].get('content') or []
    out, run = [], []

    def flush():
        if any(node_text(x) or x.get('type') in ('table', 'image') for x in run):
            if house and root != 'speech_article':
                seed = f'{serial}-hs-{n}-{len(out)}'
                out.extend(hs.layout(list(run), lambda k: bp.uid(f'{seed}-{k}'), allowed))
            else:
                out.append(rich_text(f'{serial}-rt-{n}-{len(out)}', list(run), b['spacing_preset']))
        run.clear()

    qs = [i for i, x in enumerate(nodes) if is_question(x)] if ok('info_accordion') else []
    if len(qs) >= 3:
        head, items = nodes[:qs[0]], []
        for k, qi in enumerate(qs):
            end = qs[k + 1] if k + 1 < len(qs) else len(nodes)
            items.append((node_text(nodes[qi]), nodes[qi + 1:end]))
        run.extend(head)
        flush()
        out.append(accordion(f'{serial}-qa-{n}', items))
        return out

    i = 0
    while i < len(nodes):
        x = nodes[i]
        srcs = take_markers(x)
        if srcs:
            if node_text(x):
                run.append(x)
            flush()
            for k, src in enumerate(srcs):
                blk = embed_blok(f'{serial}-emb-{n}-{i}-{k}', src) if src else None
                if blk and ok(blk['component']):
                    out.append(blk)
            i += 1
            continue
        if x.get('type') == 'image' and ok('image'):
            # A run of pictures is a grid, and becomes ONE gallery at that point.
            # Emitting one `image` blok per picture put 47 full-width images on
            # one page. Only directly consecutive pictures: a caption between
            # two has nowhere to go in a gallery, and text is never dropped.
            j, pics = i, []
            while j < len(nodes) and nodes[j].get('type') == 'image':
                pics.append(nodes[j])
                j += 1
            flush()
            if len(pics) >= 2 and ok('media_section'):
                srcs = [(p.get('attrs') or {}).get('_src_original') or '' for p in pics]
                out.append(bp.gallery_blok(serial, f'{n}-{i}', '', [s for s in srcs if s], []))
                i = j
            else:
                out.append(image_blok(f'{serial}-img-{n}-{i}', x))
                i += 1
            continue
        if not house and root != 'speech_article' and ok('sub_inner_group') and x.get('type') == 'heading':
            j, intro = i + 1, ''
            if j < len(nodes) and nodes[j].get('type') == 'paragraph' and \
                    j + 1 < len(nodes) and plain_list(nodes[j + 1]):
                intro, j = node_text(nodes[j]), j + 1
            labels = plain_list(nodes[j]) if j < len(nodes) else None
            if labels:
                flush()
                out.append(outcomes(f'{serial}-out-{n}-{i}', node_text(x), intro, labels))
                i = j + 1
                continue
        run.append(x)
        i += 1
    flush()
    return out


def sweep_markers(x):
    """Remove markers that ended up in a string field (a split_section title,
    a card). Returns how many; a marker must never reach the page."""
    n = 0
    if isinstance(x, dict):
        for k, v in x.items():
            if isinstance(v, str) and '@@EMBED@@' in v:
                n += len(MARK.findall(v))
                x[k] = MARK.sub('', v)
            else:
                n += sweep_markers(v)
    elif isinstance(x, list):
        for v in x:
            n += sweep_markers(v)
    return n


def merge_adjacent_rich_text(bloks):
    """build_pages starts a rich_text per webpart cell; people start one only
    when another blok interrupts the text -- 232 of 297 pages have one."""
    out = []
    for b in bloks:
        if out and b.get('component') == 'rich_text' and out[-1].get('component') == 'rich_text':
            out[-1]['content']['content'] += b['content']['content']
            continue
        out.append(b)
    return out


def fix_split_sections(bloks):
    """String descriptions from build_pages' other split rules -> rich text;
    variant by length; runs alternate starting with `reverse` (34 of 41)."""
    flip = 0
    for b in bloks:
        if b.get('component') != 'split_section':
            flip = 0
            continue
        if isinstance(b.get('description'), str):
            b['description'] = text_doc(b['description'])
        chars = len(bp.flat_text(b['description']))
        b['image_variant'] = 'wrap' if chars > 1000 else 'default'
        if b.get('title') and not b.get('highlight'):
            b['title'], b['highlight'] = split_heading(b['title'])
        b['layout'] = 'reverse' if flip % 2 == 0 else 'default'
        b['spacing_preset'] = PRESET
        flip += 1
    return bloks


# -------------------------------------------------------------- chrome ------
def canon(x):
    if isinstance(x, dict):
        return {k: canon(v) for k, v in sorted(x.items()) if k not in ('_uid', '_editable')}
    if isinstance(x, list):
        return [canon(v) for v in x]
    return x


def fresh_uids(x, seed):
    n = [0]

    def walk(y):
        if isinstance(y, dict):
            if '_uid' in y:
                n[0] += 1
                y['_uid'] = bp.uid(f'{seed}-{n[0]}')
            for v in y.values():
                walk(v)
        elif isinstance(y, list):
            for v in y:
                walk(v)
    x = copy.deepcopy(x)
    walk(x)
    return x


class Reference:
    """The hand-built stories: siblings to copy chrome from, icons to reuse."""

    COPY = ('library_navigator', 'teaching_impact', 'carousel_section', 'strip_banner')

    def __init__(self, path):
        data = json.load(open(path, encoding='utf-8')) if os.path.exists(path) else []
        if isinstance(data, dict):           # the older {serial: {story}} shape
            data = [v['story'] for v in data.values() if v.get('story')]
        self.stories = data
        self.by_folder = collections.defaultdict(list)
        for s in data:
            self.by_folder[s['full_slug'].rsplit('/', 1)[0]].append(s)
        self.icons = self._icons()

    def _icons(self):
        """Quick-link icon per target URL, by majority. 99 SVGs, each always
        the same asset; the majority icon covers 98% of side-nav links."""
        seen = collections.defaultdict(collections.Counter)
        keep = {}

        def walk(x):
            if isinstance(x, dict):
                if x.get('component') == 'quick_action':
                    link = x.get('link') or {}
                    key = sheet.norm_url(link.get('cached_url') or link.get('url'))
                    img = x.get('icon_image') or {}
                    sig = json.dumps([img.get('id'), x.get('icon') or ''])
                    if key:
                        seen[key][sig] += 1
                        if img.get('filename'):
                            keep[sig] = img
                for v in x.values():
                    walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)
        walk([s.get('content') for s in self.stories])
        out = {}
        for key, cnt in seen.items():
            sig = cnt.most_common(1)[0][0]
            iid, icon = json.loads(sig)
            out[key] = (keep.get(sig), icon)
        return out

    def chrome(self, folder, exclude_slug=None):
        """{component: blok} copied from siblings, where at least half carry it.

        Byte-identical (ignoring ids) to a sibling: teaching_impact 88%,
        institutes carousel 92%, library_navigator 80%, strip_banner 57%.
        Below half, the block is a builder's choice, so it is left out.
        """
        sibs = [s for s in self.by_folder.get(folder, [])
                if s['full_slug'] != exclude_slug]
        if not sibs:
            return {}
        out = {}
        for comp in self.COPY:
            versions = collections.Counter()
            sample = {}
            have = 0
            for s in sibs:
                found = [b for b in (s.get('content') or {}).get('body') or []
                         if b.get('component') == comp]
                if comp == 'carousel_section':
                    found = [b for b in found if any(
                        x.get('component') == 'carousel_institute_slide'
                        for x in b.get('slides') or b.get('items') or [])]
                if not found:
                    continue
                have += 1
                key = json.dumps(canon(found[0]), sort_keys=True)
                versions[key] += 1
                sample[key] = found[0]
            if have * 2 >= len(sibs) and versions:
                out[comp] = sample[versions.most_common(1)[0][0]]
        return out


def quick_actions(serial, links, ref, convocation):
    items, seen = [], set()
    for i, (label, href) in enumerate(links):
        key = sheet.norm_url(href)
        if key in seen:
            continue
        seen.add(key)
        img, icon = ref.icons.get(key, (None, ''))
        item = {'_uid': bp.uid(f'{serial}-qa-{i}'), 'component': 'quick_action',
                'label': label,
                'link': {'id': '', 'url': href, 'linktype': 'url',
                         'fieldtype': 'multilink', 'cached_url': href},
                'spacing_preset': 'zero'}
        if img:
            item['icon_image'] = img
        else:
            # no icon learnt for this link: the option people fell back on
            item['icon'] = icon or ('graduation' if convocation else 'book')
        items.append(item)
    if not items:
        return None
    return {'_uid': bp.uid(f'{serial}-qas'), 'component': 'quick_actions',
            'title': 'Quick ', 'highlight': 'Actions', 'actions': items,
            'spacing_preset': PRESET}


# ---------------------------------------------------------------- build -----
def build(row, ref, schema, html_dir, widgets, house=True):
    serial, url = row['Serial No.'], row['Old URL']
    folder, slug = sheet.destination(row)
    root = row.get('_root') or root_type(url)
    raw = open(os.path.join(html_dir, f'{serial}.html'), encoding='utf-8').read()
    prepared, h1, nav, related = prepare(serial, raw, url)
    with open(os.path.join(PREP_DIR, f'{serial}.html'), 'w', encoding='utf-8',
              newline='\n') as fh:
        fh.write(prepared)

    name = sheet.story_name(row)
    bloks, _images, script_title = bp.build(serial, h1 or name, widgets)
    title = h1 or name or script_title
    shift_headings(bloks)

    hero, body = bloks[0], bloks[1:]
    # The hero: the page's own h1, tertiary, no picture unless the page had a
    # real banner (quaternary: 11 of 11 hand heroes with a photo).
    has_img = bool((hero.get('image') or {}).get('_src_original'))
    hero.update({'title': title, 'variant': 'quaternary' if has_img else 'tertiary',
                 'spacing_preset': 'zero'})
    if not has_img:
        hero['image'] = bp.asset_stub('')

    allowed = schema.whitelist(root) if root != 'page' else set()
    out = []
    for n, b in enumerate(merge_adjacent_rich_text(body)):
        if b.get('component') == 'rich_text':
            out += explode_rich_text(serial, n, b, allowed, root, house)
        else:
            out.append(b)
    # build() appends the page's video at the end; a marker placed it already.
    placed = {sheet.norm_url((b.get('video_url') or {}).get('url'))
              for b in out if b.get('component') == 'media_section'
              and b['_uid'] != bp.uid(f'{serial}-vid-900')}
    out = [b for b in out if not (b['_uid'] == bp.uid(f'{serial}-vid-900')
                                  and sheet.norm_url(b['video_url']['url']) in placed)]
    body = fix_split_sections(out if house else merge_adjacent_rich_text(out))
    leaked = sweep_markers(body)
    if leaked:
        print(f'    {serial}: {leaked} embed marker(s) sat inside a component '
              f'that cannot hold an embed; removed')

    # The first text after the hero always opens with a heading (180/185); when
    # the source has none, every owner wrote "Overview" (70 pages).
    if not house and root == 'page' and body and body[0].get('component') == 'rich_text':
        first = body[0]['content']['content']
        if first and first[0].get('type') != 'heading':
            first.insert(0, {'type': 'heading', 'attrs': {'level': 1},
                             'content': [{'type': 'text', 'text': 'Overview'}]})

    # Speeches over 5,000 characters fold (22 of 47), at 20 lines.
    if root == 'speech_article':
        for b in body:
            if b.get('component') == 'rich_text' and len(bp.flat_text(b['content'])) > 5000:
                b.update({'collapsible': True, 'collapse_lines': 20})

    # Chrome at the end: quick_actions, then the copied section blocks.
    chrome = ref.chrome(folder, exclude_slug=f'{folder}/{slug}')
    # House style: the legacy left sidebar is ALWAYS a library_navigator built
    # from this page's own sidebar, never quick_actions (Abdullah, QTL Teaching
    # Tips, 6 Nov 2026) -- whether or not the siblings carry one. Copied
    # navigators pointed at the WRONG library on most IED/Chitral/Gilgit pages;
    # a sibling's is used for its settings only, the links come from this page.
    lib = None
    if house or 'library_navigator' in chrome:
        tmpl = (fresh_uids(chrome['library_navigator'], f'{serial}-lib')
                if 'library_navigator' in chrome
                else {'_uid': bp.uid(f'{serial}-lib'), 'component': 'library_navigator'})
        lib = hs.rebuild_navigator(tmpl, BeautifulSoup(raw, 'html.parser'),
                                   lambda k: bp.uid(f'{serial}-lib-{k}'), sheet.absolute)
        if not lib.get('libraries'):
            lib = None                   # no sidebar on this page
    links = ([] if lib else nav) + related
    qa = quick_actions(serial, links, ref, '/convocation/' in url.lower())
    tail = []
    if qa:
        tail.append(qa)
    for comp in ('teaching_impact', 'carousel_section', 'strip_banner'):
        # House style: no copied country cards. Abdullah deleted the shared
        # teaching_impact from every page fixed with it (Wellness UG,
        # Experience KE, Mission & Vision, 9 Nov 2026).
        if comp == 'teaching_impact' and house:
            continue
        if comp in chrome:
            tail.append(fresh_uids(chrome[comp], f'{serial}-{comp}'))
    if lib:
        tail.append(lib)
    body += tail

    common = {'enable_pattern': True, 'pattern_spacing': 'section',
              'meta_title': '', 'meta_description': '', 'meta_keywords': '',
              'og_title': '', 'og_description': '', 'canonical_url': '',
              'noindex': False}
    body = [schema.sanitize(b) for b in body]
    if root == 'page':
        content = {'component': 'page', 'body': [schema.sanitize(hero)] + body, **common}
    else:
        dropped = [b['component'] for b in body if allowed and b['component'] not in allowed]
        body = [b for b in body if not allowed or b['component'] in allowed]
        content = {'component': root, 'title': title, 'description': '',
                   'body': body, **common}
        if root == 'speech_article':
            low = title.lower()
            content.update({'date': '', 'SpeechBy': 'chancellor'
                            if 'aga khan' in low and 'highness' in low else ''})
        else:
            content.update({'variant': 'single', 'register_action': 'modal',
                            'isArchived': False, 'banner_image_fit': 'cover',
                            'show_share': True, 'show_calendar': True,
                            'show_events': False, 'show_events_header': False})
        if dropped:
            print(f'    {serial}: not allowed in {root}, dropped: {dropped}')

    images = []

    def collect(x):
        if isinstance(x, dict):
            src = x.get('_src_original')
            if src:
                images.append(src)
            for v in x.values():
                collect(v)
        elif isinstance(x, list):
            for v in x:
                collect(v)
    collect(content['body'])
    return {'serial': serial, 'aku_url': url, 'folder': folder, 'slug': slug,
            'title': name or title, 'root': root, 'content': content,
            'bloks': content['body'], 'images': list(dict.fromkeys(images))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', required=True)
    ap.add_argument('--only', help='comma-separated serials')
    ap.add_argument('--pages', default=PAGES_DIR, help='fetch_sheet_pages.py output')
    ap.add_argument('--reference', default=paths.work('reference_stories.json'))
    ap.add_argument('--out', default=OUT)
    ap.add_argument('--style', choices=('house', 'team'), default='house',
                    help="house: Abdullah's layout (house_style.py). team: what the 530 "
                         "hand-built pages do on average, as scored by score_against_reference")
    a = ap.parse_args()

    rows = sheet.read(a.csv)
    if a.only:
        want = set(a.only.split(','))
        rows = [r for r in rows if r['Serial No.'] in want]
    html_dir = os.path.join(a.pages, 'html')
    wpath = os.path.join(a.pages, 'widgets.json')
    widgets = json.load(open(wpath, encoding='utf-8')) if os.path.exists(wpath) else {}
    # Widgets whose div is not on the page are dead initialisers (MC-PK §4).
    widgets = {k: [w for w in v if w.get('div_present', True)] for k, v in widgets.items()}
    ref = Reference(a.reference)
    schema = Schema(paths.work('components_live.json'))
    os.makedirs(PREP_DIR, exist_ok=True)
    bp.HTML_DIR = PREP_DIR

    out, missing, invalid = [], [], {}
    for row in rows:
        sn = row['Serial No.']
        if not os.path.exists(os.path.join(html_dir, f'{sn}.html')):
            missing.append(sn)
            continue
        p = build(row, ref, schema, html_dir, widgets.get(sn, []), house=a.style == 'house')
        probs = schema.problems(p['content']['body'])
        if probs:
            invalid[sn] = probs
        out.append(p)
        shape = collections.Counter(b['component'] for b in p['content']['body'])
        print(f"  {sn:>5} {p['root'][:6]:<6} {p['folder'][-28:]:>28}/{p['slug'][:22]:<22} "
              + ' '.join(f'{v}x{k}' for k, v in shape.items()))

    json.dump(out, open(a.out, 'w', encoding='utf-8', newline='\n'),
              indent=1, ensure_ascii=False)
    print(f'\n{len(out)} payloads -> {a.out}')
    if missing:
        print(f'  {len(missing)} row(s) have no downloaded HTML -- run '
              f'fetch_sheet_pages.py: {missing[:20]}')

    # The retention guard, as build_pages: a page must keep 70% of its text.
    losses = []
    for p in out:
        # measured on the prepared page, without the embed markers' URLs
        soup = BeautifulSoup(open(os.path.join(PREP_DIR, f"{p['serial']}.html"),
                                  encoding='utf-8').read(), 'html.parser')
        src = len(clean(MARK.sub('', ' '.join(c.get_text(' ', strip=True)
                                              for c in bp.body_of(soup)))))
        got = len(bp.payload_text(p['content']))
        if src > 300 and got < src * 0.7:
            losses.append(f"{p['serial']} {p['slug']}: {got} of {src} chars")
            p['content_lost'] = f'{got} of {src} chars'   # create_pages refuses it
    json.dump(out, open(a.out, 'w', encoding='utf-8', newline='\n'),
              indent=1, ensure_ascii=False)
    if losses:
        print('\n*** CONTENT LOST -- read these before uploading:\n  ' + '\n  '.join(losses))
    if invalid:
        print(f'\n*** {len(invalid)} payload(s) do not fit the live schema:')
        for sn, probs in list(invalid.items())[:15]:
            print(f'  {sn}: ' + '; '.join(probs[:4]))
    if losses or invalid:
        raise SystemExit(1)
    print('  every page keeps 70% of its source text and fits the live schema')


if __name__ == '__main__':
    main()
