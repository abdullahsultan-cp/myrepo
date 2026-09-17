"""build_compare_portal.py -- the old page and the new one, in one window.

Emits ONE self-contained HTML file: `out/AKU-MC-Page-Compare.html`. It opens by
double-clicking, from a bare clone, with no server and no Python -- the rule
every portal in this repo obeys (docs/PORTALS.md).

WHY THE PAGES ARE EMBEDDED RATHER THAN FRAMED
---------------------------------------------
The obvious build is two <iframe>s pointing at the live sites. It does not work:

    aku.edu                X-FRAME-OPTIONS: SAMEORIGIN
                           Content-Security-Policy: frame-ancestors 'self' ...
    app.storyblok.com      X-Frame-Options: SAMEORIGIN

Both refuse to be framed, so that version renders two blank boxes. Instead:

* the LEFT pane is the archived SharePoint HTML we already hold on disk, with
  its relative URLs rewritten to absolute so AKU's own stylesheet and images
  still load -- it looks like the real page;
* the RIGHT pane is rendered here from the story content READ BACK FROM
  STORYBLOK, so it shows what the space actually holds today, including the
  pages Rabee corrected by hand.

Both panes end up as ordinary elements in one document, which is the only way
to scroll them in lockstep -- a cross-origin iframe's scroll position cannot be
read or set, and an unsynced wipe compares two different parts of two pages.

Each pane is mounted in a SHADOW ROOT. AKU's stylesheet is 181 KB of global
rules written for a whole page; without the shadow boundary it restyles the
comparison UI around it.

`aku-dev.vercel.app` sends no frame-blocking headers, so the live front end IS
frameable and gets a third mode -- but it renders PUBLISHED stories only (12 of
75 today; a draft comes back as an empty shell), and a cross-origin frame will
not scroll with the other pane. Both limits are stated in the UI rather than
left for the reader to discover.

Run:  python Pages-Pipeline/pipeline/build_compare_portal.py
"""
import csv
import glob
import gzip
import html
import json
import os
import re
import urllib.parse

from bs4 import BeautifulSoup

HERE = os.path.dirname(os.path.abspath(__file__))
PP = os.path.dirname(HERE)
OUT = os.path.join(PP, 'out', 'AKU-MC-Page-Compare.html')
CSV_PATH = os.path.join(PP, 'out', 'rabee-pages-links-v2.csv')
LEGACY = os.path.join(PP, 'out', 'work', 'legacy_html')
AKU = 'https://www.aku.edu'
FRONTEND = 'https://aku-dev.vercel.app'

# SharePoint chrome: the ribbon, the suite bar, the dialog scaffolding. None of
# it is the page, and all of it is noise in a comparison.
CHROME_SEL = ('#s4-ribbonrow,#suiteBar,#ms-designer-ribbon,.ms-dialogHidden,'
              '#s4-titlerow,.ms-cui-ribbonTopBars,#RibbonContainer,'
              '#DeltaSPWebPartManager,.ms-core-overlay,#imgPrefetch')


# ----------------------------------------------------------------- legacy ---
def absolutise(soup, base):
    """Point every relative URL at aku.edu so the archived page still renders.

    A <base> tag would be simpler but does not cross a shadow boundary, and the
    panes have to be in shadow roots -- see the module docstring.

    Resolved against the page's OWN address, not the site root: SharePoint
    writes `../../../../_layouts/...`, which only lands in the right place if
    the depth of the original URL is taken into account. (An earlier version
    hand-rolled this with `lstrip('./')`, which ate the leading slash and
    produced `https://www.aku.edu_layouts/...` -- every stylesheet 404ed and the
    old pane rendered unstyled.)
    """
    for tag, attr in (('a', 'href'), ('link', 'href'), ('img', 'src'),
                      ('source', 'src'), ('iframe', 'src'), ('input', 'src')):
        for el in soup.find_all(tag):
            v = (el.get(attr) or '').strip()
            if not v or v.startswith(('http://', 'https://', '//', 'data:',
                                      'mailto:', 'tel:', '#', 'javascript:')):
                continue
            el[attr] = urllib.parse.urljoin(base, v)
    # inline style="background-image:url(/foo.jpg)"
    def fix_url(m):
        q, u = m.group(1), m.group(2)
        if u.startswith(('http', 'data:', '//')):
            return m.group(0)
        return f'url({q}{urllib.parse.urljoin(base, u)}{q})'
    for el in soup.find_all(style=True):
        el['style'] = re.sub(r'url\((["\']?)([^)"\']+)\1\)', fix_url, el['style'])
    return soup


def legacy_html(serial, base, widgets):
    path = os.path.join(LEGACY, f'{serial}.html')
    if not os.path.exists(path):
        return '', 0, 0
    raw = open(path, encoding='utf-8', errors='replace').read()
    styles = init_styles(raw)          # read BEFORE the scripts are stripped
    soup = BeautifulSoup(raw, 'html.parser')
    # Scripts cannot run usefully here -- the widget initialisers call a
    # SharePoint API that needs the page's own context -- and they are half the
    # file's weight. The content they would have fetched is already in the
    # story, which is the thing being compared against.
    for x in soup.find_all(['script', 'noscript', 'meta']):
        x.decompose()
    for x in soup.select(CHROME_SEL):
        x.decompose()
    base = base or AKU + '/'
    absolutise(soup, base)
    n_widgets = fill_widgets(soup, serial, base, widgets, styles)
    links = ''.join(str(l) for l in soup.find_all('link', rel='stylesheet'))
    body = soup.body or soup
    # Count the CONTENT ZONES, not the whole body. The body carries AKU's global
    # navigation, the footer and the search box, which are chrome on every page
    # and are not migrated -- counting them makes the old side look twice the
    # size of the new one on a page that lost nothing.
    cells = [d for d in soup.find_all('div')
             if (d.get('id') or '').startswith('MSOZoneCell')]
    cells = [c for c in cells if not any(p in cells for p in c.parents)]
    zones = cells or [body]
    text = len(re.sub(r'\s+', ' ',
                      ' '.join(z.get_text(' ', strip=True) for z in zones)).strip())
    return links + str(body), text, n_widgets



# ------------------------------------------------- the JS-rendered widgets ---
# A SharePoint webpart leaves an EMPTY div and lets JavaScript fill it from a
# list. Scripts are stripped here (AKU's REST API sends no CORS headers, so they
# could not run from a local file even if they were kept), which left those divs
# blank -- on the residency pages that is nearly the whole page.
#
# The data is not lost: `recover_widgets.py` pulled every one of those lists
# through AKU's REST API, which is why the new pages have the content at all.
# It is drawn back in here.
#
# CRUCIALLY it is rebuilt with AKU'S OWN MARKUP AND AKU'S OWN STYLESHEET, read
# out of their Accordion.js, Tabs.js and gallerywp.js. A hand-rolled
# approximation is no use for checking a migration -- you would be comparing the
# new page against something I invented. The class names, the nesting, and the
# `<link class="Style">` their script points at AKUUNIAccordion-Gray.css are all
# theirs, so the old pane renders the way aku.edu renders it.

# ReadAccordion(id, list, siteUrl, style, cssPath) -- the 5th argument is the
# stylesheet the script assigns at runtime; the tag ships with an empty href.
INIT_CALL = re.compile(
    r"\b(galleryapp|ReadAccordion|ReadTiles|ReadTabs)\s*\(\s*"
    r"'(ctl00_[^']+)'\s*,\s*'([^']*)'\s*,\s*'([^']*)'"
    r"(?:\s*,\s*'([^']*)')?(?:\s*,\s*'([^']*)')?", re.S)


def init_styles(raw):
    """div id -> the stylesheet its initialiser would have loaded."""
    return {m.group(2): (m.group(6) or '') for m in INIT_CALL.finditer(raw)}


def _body_html(raw_html, base):
    f = BeautifulSoup(raw_html or '', 'html.parser')
    for x in f.find_all(['script', 'style']):
        x.decompose()
    absolutise(f, base)
    return str(f)


def _ordered(data):
    return sorted(data, key=lambda x: x.get('order') or 0)


def accordion_markup(wid, data, base):
    """Exactly what Accordion.js appends, panel for panel.

    `arrowtoggle()` then hides the up-arrow and shows the down-arrow; that is
    reproduced inline so the closed state looks right without the script.
    """
    out = []
    for i, it in enumerate(_ordered(data)):
        pid = 'w%d%s' % (i, wid)
        out.append(
            "<div class='panel panel-default'><div class='panel-heading'>"
            "<span class='AKUAccordianHeadingGrey'>"
            "<a data-toggle='collapse' class='AKUAccordianPanelGrey' "
            "href='#" + pid + "' data-parent='#maindiv" + wid + "'>"
            "<div class='AKUAccordianIconHolderG' style='display:block'>"
            "<i class='fa fa-angle-down AKUAccordianIcon' aria-hidden='true'></i></div>"
            "<div class='AKUAccordianIconHolderG2' style='display:none'>"
            "<i class='fa fa-angle-up AKUAccordianIcon' aria-hidden='true'></i></div>"
            + html.escape(it.get('title') or '') + "</a></span></div>"
            "<div class='panel-collapse collapse' id='" + pid + "'>"
            "<div class='panel-body AKUAccordianText'><p>"
            + _body_html(it.get('body'), base) + "</p></div></div></div>")
    return ''.join(out)


def tabs_markup(wid, data, base):
    """What Tabs.js appends: the <li> list and the matching panes."""
    nav, panes = [], []
    for i, it in enumerate(_ordered(data)):
        pid = 'w%d%s' % (i, wid)
        title = html.escape(it.get('title') or '')
        if i == 0:
            nav.append("<li class='active'><a data-toggle='tab' href='#"
                       + pid + "'>" + title + "</a></li>")
            cls = 'tab-pane fade in active'
        else:
            nav.append("<li><a data-toggle='tab' href='#" + pid + "'>"
                       + title + "</a></li>")
            cls = 'tab-pane fade'
        panes.append("<div id='" + pid + "' class='" + cls + "'><p>"
                     + _body_html(it.get('body'), base) + "</p></div>")
    return ''.join(nav), ''.join(panes)


def gallery_markup(data, base):
    """gallerywp.js: one wide tile, then up to four -- the last carrying a
    "View Photos" overlay -- then the remainder as lightbox-only anchors.

    Caption is the one thing not reproduced: the recovery kept the file paths
    (`FileRef`), not the `Caption` column the script reads.
    """
    urls = [urllib.parse.urljoin(base, str(u)) for u in data]
    if not urls:
        return ''
    out, more = [], max(0, len(urls) - 5)

    def tile(u, col, inner):
        u = html.escape(u, quote=True)
        return ("<div class='col-md-" + str(col) + "'><div class='container-img'>"
                "<a data-fancybox='gallery' href='" + u + "'>"
                "<img src='" + u + "' class='img-width margin-bot' loading='lazy' />"
                + inner + "</a></div></div>")

    for u in urls[:1]:
        out.append(tile(u, 6, "<div class='text-block'>"
                              "<div class='shadow-margin-big'><h4></h4></div></div>"))
    rest = urls[1:5]
    for i, u in enumerate(rest):
        if more and i == len(rest) - 1:
            inner = ("<div class='text-block last-img'><div class='top-pad'>"
                     + str(more) + "+</div><div class='top-pad2'>"
                     "<h4>View Photos </h4></div></div>")
        else:
            inner = ("<div class='text-block'><div class='shadow-margin'>"
                     "<h4></h4></div></div>")
        out.append(tile(u, 3, inner))
    for u in urls[5:]:
        out.append("<a data-fancybox='gallery' href='"
                   + html.escape(u, quote=True) + "'></a>")
    return ''.join(out)


TILE_CSS = """
<style>
.rcv-tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));
  gap:14px;padding:6px 0}
.rcv-tiles .t{border:1px solid #e0d9d0;border-radius:6px;padding:10px;
  font:14px/1.55 'IBM Plex Sans',system-ui,sans-serif}
.rcv-tiles .t img{width:100%;height:auto;border-radius:4px;margin-bottom:6px}
.rcv-tiles .t b{display:block;margin-bottom:3px}
.rcv-approx{font:600 10px/1.4 'IBM Plex Mono',monospace;color:#8A6A2F;
  text-transform:uppercase;letter-spacing:.06em;margin:0 0 4px}
</style>
"""


def tiles_markup(data, base):
    """The one widget whose script was not recovered, so this IS an
    approximation and says so rather than passing itself off as AKU's."""
    cards = ''
    for it in _ordered(data):
        img = it.get('image')
        cards += '<div class="t">'
        if img:
            cards += ('<img src="'
                      + html.escape(urllib.parse.urljoin(base, img), quote=True)
                      + '" alt="" loading="lazy">')
        cards += '<b>' + html.escape(it.get('title') or '') + '</b>'
        cards += '<span>' + html.escape(it.get('description') or '') + '</span>'
        if it.get('cta_label'):
            cards += ('<div><a href="'
                      + html.escape(urllib.parse.urljoin(base, it.get('cta_url') or ''), quote=True)
                      + '">' + html.escape(it.get('cta_label')) + '</a></div>')
        cards += '</div>'
    return (TILE_CSS + '<p class="rcv-approx">tiles &middot; approximate layout '
            '&middot; AKU tile script not recovered</p>'
            '<div class="rcv-tiles">' + cards + '</div>')


def fill_widgets(soup, serial, base, widgets, styles):
    """Draw each recovered widget into the very container its script targets.

    A widget whose div is absent is SKIPPED, not appended -- seven residency
    pages carry a second ReadAccordion call whose target was deleted, and the
    live page draws nothing for it. Appending it is what put the accordion on
    the page twice when the new pages were built.
    """
    n = 0
    for w in widgets.get(serial, []):
        wid = w.get('div')
        host = soup.find(id=wid)
        if host is None:
            continue
        data = w.get('data') or []
        kind = w['kind']

        # give AKU's own stylesheet the href its script assigns at runtime
        css = styles.get(wid)
        if css:
            for link in host.find_all('link'):
                if 'Style' in (link.get('class') or []):
                    link['href'] = urllib.parse.urljoin(base, css)

        if kind == 'accordion':
            box = host.find(id='maindiv') or host.find(class_='mainaccordiondiv')
            if box is None:
                continue
            box['id'] = 'maindiv' + wid          # the script renames it too
            box.append(BeautifulSoup(accordion_markup(wid, data, base), 'html.parser'))
        elif kind == 'tabs':
            box = host.find(id='tabmaindiv') or host.find(class_='AKUTabs')
            if box is None:
                continue
            box['id'] = 'tabmaindiv' + wid
            nav = box.find('ul', class_='nav')
            cont = box.find(class_='tab-content')
            if nav is None or cont is None:
                continue
            nav_html, pane_html = tabs_markup(wid, data, base)
            nav.append(BeautifulSoup(nav_html, 'html.parser'))
            cont.append(BeautifulSoup(pane_html, 'html.parser'))
        elif kind == 'gallery':
            box = host.find(id='gallerywp') or host.find(class_='gallerywp')
            if box is None:
                continue
            box['id'] = 'gallerywp' + wid
            box.append(BeautifulSoup(gallery_markup(data, base), 'html.parser'))
        else:
            box = host.find(class_='ms-rtestate-field') or host
            box.append(BeautifulSoup(tiles_markup(data, base), 'html.parser'))
        n += 1
    return n


# -------------------------------------------------------------- rich text ---
MARK_TAG = {'bold': 'strong', 'italic': 'em', 'underline': 'u',
            'strike': 's', 'code': 'code', 'superscript': 'sup',
            'subscript': 'sub'}


def marks(text, ms):
    out = html.escape(text)
    for m in reversed(ms or []):
        t = m.get('type')
        if t == 'link':
            a = m.get('attrs') or {}
            href = html.escape(a.get('href') or a.get('url') or '', quote=True)
            tgt = ' target="_blank" rel="noopener"' if a.get('target') == '_blank' else ''
            out = f'<a href="{href}"{tgt}>{out}</a>'
        elif t in MARK_TAG:
            out = f'<{MARK_TAG[t]}>{out}</{MARK_TAG[t]}>'
    return out


def rt(node):
    """One Storyblok rich-text node -> HTML."""
    if isinstance(node, list):
        return ''.join(rt(n) for n in node)
    if not isinstance(node, dict):
        return ''
    t = node.get('type')
    kids = node.get('content') or []
    if t == 'text':
        return marks(node.get('text') or '', node.get('marks'))
    if t == 'hard_break':
        return '<br>'
    if t in ('doc',):
        return rt(kids)
    if t == 'paragraph':
        inner = rt(kids)
        return f'<p>{inner}</p>' if inner.strip() else ''
    if t == 'heading':
        lv = (node.get('attrs') or {}).get('level') or 2
        return f'<h{lv}>{rt(kids)}</h{lv}>'
    if t in ('bullet_list', 'ordered_list'):
        tag = 'ul' if t == 'bullet_list' else 'ol'
        return f'<{tag}>{rt(kids)}</{tag}>'
    if t == 'list_item':
        return f'<li>{rt(kids)}</li>'
    if t == 'blockquote':
        return f'<blockquote>{rt(kids)}</blockquote>'
    if t == 'horizontal_rule':
        return '<hr>'
    if t == 'code_block':
        return f'<pre>{rt(kids)}</pre>'
    if t == 'image':
        a = node.get('attrs') or {}
        src = html.escape(a.get('src') or '', quote=True)
        alt = html.escape(a.get('alt') or '', quote=True)
        return f'<img src="{src}" alt="{alt}" loading="lazy">' if src else ''
    if t == 'table':
        return f'<table>{rt(kids)}</table>'
    if t == 'tableRow':
        return f'<tr>{rt(kids)}</tr>'
    if t in ('tableCell', 'tableHeader'):
        a = node.get('attrs') or {}
        tag = 'th' if t == 'tableHeader' else 'td'
        at = ''
        if (a.get('colspan') or 1) > 1:
            at += f' colspan="{a["colspan"]}"'
        if (a.get('rowspan') or 1) > 1:
            at += f' rowspan="{a["rowspan"]}"'
        return f'<{tag}{at}>{rt(kids)}</{tag}>'
    if t == 'blok':
        return bloks((node.get('attrs') or {}).get('body') or [])
    return rt(kids)


# ------------------------------------------------------------- components ---
def img_of(field):
    if not isinstance(field, dict):
        return ''
    return field.get('filename') or ''


def pic(field, cls='c-img'):
    src = img_of(field)
    if not src:
        return ''
    alt = html.escape((field.get('alt') or ''), quote=True)
    return (f'<img class="{cls}" src="{html.escape(src, quote=True)}" '
            f'alt="{alt}" loading="lazy">')


def link_of(field):
    if not isinstance(field, dict):
        return ''
    return field.get('url') or field.get('cached_url') or ''


def esc(v):
    return html.escape(str(v or ''))


def cta(label, link, cls='c-btn'):
    href = link_of(link)
    if not label:
        return ''
    if not href:
        return f'<span class="{cls}">{esc(label)}</span>'
    return (f'<a class="{cls}" href="{html.escape(href, quote=True)}" '
            f'target="_blank" rel="noopener">{esc(label)}</a>')


def blok(b):
    """One Storyblok blok -> HTML. Unknown components are named, not dropped."""
    if not isinstance(b, dict):
        return ''
    c = b.get('component')

    if c == 'rich_text':
        return f'<div class="c-rt">{rt(b.get("content"))}</div>'

    if c == 'hero':
        img = pic(b.get('image'), 'c-hero-img')
        sub = b.get('description') or b.get('subtitle') or ''
        return (f'<header class="c-hero">{img}'
                f'<div class="c-hero-t"><h1>{esc(b.get("title"))}</h1>'
                f'{f"<p>{esc(sub)}</p>" if sub else ""}</div></header>')

    if c == 'split_section':
        rev = ' rev' if b.get('layout') == 'reverse' else ''
        head = f'<h2>{esc(b.get("title"))}</h2>' if b.get('title') else ''
        body = f'<p>{esc(b.get("description"))}</p>' if b.get('description') else ''
        return (f'<section class="c-split{rev}">'
                f'<div class="c-split-i">{pic(b.get("image"))}</div>'
                f'<div class="c-split-b">{head}{body}'
                f'{cta(b.get("cta_label"), b.get("cta_link"))}</div></section>')

    if c == 'info_accordion':
        items = ''.join(blok(i) for i in (b.get('items') or []))
        return f'<section class="c-acc">{items}</section>'

    if c == 'info_accordion_item':
        inner = bloks(b.get('body') or [])
        if not inner and (b.get('content') or '').strip():
            # the old flat shape -- shown as-is so a page still on it is obvious
            inner = f'<p class="c-flat">{esc(b.get("content"))}</p>'
        cards = ''.join(blok(x) for x in (b.get('cards') or []))
        eyebrow = (f'<span class="c-eyebrow">{esc(b.get("eyebrow"))}</span>'
                   if b.get('eyebrow') else '')
        return (f'<details class="c-acc-i" open><summary>{eyebrow}'
                f'{esc(b.get("title"))}</summary>'
                f'<div class="c-acc-b">{inner}{cards}</div></details>')

    if c == 'info_accordion_card':
        body = rt(b.get('rich_text')) if b.get('rich_text') else esc(b.get('description'))
        return (f'<div class="c-card"><h4>{esc(b.get("title"))}</h4>'
                f'<div>{body}</div></div>')

    if c == 'row':
        items = ''.join(blok(i) for i in (b.get('items') or []))
        head = f'<h2>{esc(b.get("title"))}</h2>' if b.get('title') else ''
        return f'<section class="c-row">{head}<div class="c-row-g">{items}</div></section>'

    if c == 'row_item':
        return f'<div class="c-row-i">{bloks(b.get("body") or [])}</div>'

    if c == 'link_card':
        return (f'<div class="c-card">{pic(b.get("image"))}'
                f'<h4>{esc(b.get("title"))}</h4>'
                f'<p>{esc(b.get("description"))}</p>'
                f'{cta(b.get("cta_label"), b.get("link"))}</div>')

    if c == 'profile_card':
        return (f'<div class="c-prof">{pic(b.get("image"), "c-prof-img")}'
                f'<h4>{esc(b.get("name") or b.get("title"))}</h4>'
                f'<p class="c-role">{esc(b.get("role") or b.get("designation"))}</p>'
                f'<p>{esc(b.get("bio") or b.get("description"))}</p></div>')

    if c == 'button':
        return f'<p class="c-btn-row">{cta(b.get("label") or b.get("title"), b.get("link"))}</p>'

    if c == 'video':
        u = link_of(b.get('video_link') or b.get('link')) or b.get('url') or ''
        return (f'<p class="c-video">▶ video: '
                f'<a href="{html.escape(u, quote=True)}" target="_blank" '
                f'rel="noopener">{esc(u)}</a></p>' if u else '')

    if c == 'media_section':
        items = b.get('media') or b.get('items') or b.get('images') or []
        cells = ''.join(f'<div class="c-g-i">{pic(x if isinstance(x, dict) and x.get("filename") else (x.get("image") if isinstance(x, dict) else None))}</div>'
                        for x in items)
        return f'<section class="c-gal">{cells}</section>'

    if c == 'author_section':
        return (f'<aside class="c-author">{pic(b.get("image"), "c-prof-img")}'
                f'<div><h4>{esc(b.get("name") or b.get("author_name"))}</h4>'
                f'<p>{esc(b.get("description") or b.get("bio"))}</p></div></aside>')

    inner = ''
    for v in b.values():
        if isinstance(v, list) and v and isinstance(v[0], dict) and v[0].get('component'):
            inner += bloks(v)
    return f'<div class="c-unknown"><span>{esc(c)}</span>{inner}</div>'


def bloks(lst):
    return ''.join(blok(b) for b in (lst or []))


# ------------------------------------------------------------------ build ---
def newest_backup():
    """The most recent snapshot BY MODIFICATION TIME, not by name.

    Sorting the names picks `mc-pages_20260913` over `mc-pages-AFTER-...`,
    because `_` sorts after `-` -- so the portal was built from the oldest
    backup in the folder and every page came out with zero bloks.
    """
    files = glob.glob(os.path.join(PP, 'backup', 'storyblok', 'mc-pages*.json.gz'))
    if not files:
        raise SystemExit('no Storyblok backup found -- run a backup first')
    return max(files, key=os.path.getmtime)


def main():
    rows = list(csv.DictReader(open(CSV_PATH, encoding='utf-8')))
    wpath = os.path.join(PP, 'out', 'work', 'page_widgets.json')
    widgets = json.load(open(wpath, encoding='utf-8')) if os.path.exists(wpath) else {}
    print(f'recovered widget sets: {sum(len(v) for v in widgets.values())} '
          f'across {len(widgets)} pages')
    bk = newest_backup()
    live = {s['full_slug']: s for s in json.load(gzip.open(bk, 'rt', encoding='utf-8'))}
    print(f'live stories from {os.path.basename(bk)}: {len(live)}')

    pages = []
    for r in rows:
        story = live.get(r['storyblok_path'])
        body = ((story or {}).get('content') or {}).get('body') or []
        old, old_len, n_w = legacy_html(r['serial'], r['aku_link'], widgets)
        new = bloks(body)
        new_len = len(re.sub(r'\s+', ' ',
                             re.sub(r'<[^>]+>', ' ', new)).strip())
        pages.append({
            'sr': int(r['sr_no']), 'serial': r['serial'], 'title': r['title'],
            'path': r['storyblok_path'], 'aku': r['aku_link'],
            'edit': r['sb_editorial_link'],
            'live': f"{FRONTEND}/{r['storyblok_path']}",
            # From the story itself, not the CSV column -- the sheet was written
            # before several pages were published and says 3 where the space
            # says 12.
            'pub': bool((story or {}).get('published')),
            'bloks': len(body), 'oldLen': old_len, 'newLen': new_len,
            'old': old, 'new': new,
        })
        print(f"  {r['sr_no']:>3}  {r['title'][:38]:<40} "
              f"old={old_len:>6} new={new_len:>6} bloks={len(body)} "
              f"widgets={n_w}")

    # The payload rides in a <script type="application/json"> block, so the one
    # sequence that can break out of it is a literal `</script`. Escaping the
    # slash is invisible to JSON.parse and cannot end the element early.
    data = json.dumps(pages, ensure_ascii=False, separators=(',', ':'))
    data = re.sub(r'</(script)', r'<\\/\1', data, flags=re.I)
    doc = TEMPLATE.replace('/*__DATA__*/', data)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, 'w', encoding='utf-8', newline='\n').write(doc)
    mb = os.path.getsize(OUT) / 1024 / 1024
    print(f'\n{len(pages)} pages -> {OUT}  ({mb:.1f} MB)')
    print(f'published (live front end will render): '
          f'{sum(1 for p in pages if p["pub"])} of {len(pages)}')


TEMPLATE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AKU MC — Page Compare</title>
<style>
:root{
  --maroon:#7A1F2B; --maroon-d:#5E1721;
  --bg:#F5F2EE; --panel:#FFFFFF; --ink:#1C1917; --mut:#6B6560;
  --line:#E2DBD3; --old:#8A6A2F; --new:#1F5E4A;
  --sans:'IBM Plex Sans',system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
  --mono:'IBM Plex Mono',ui-monospace,Consolas,monospace;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme=light]){
    --bg:#17150F; --panel:#211E18; --ink:#F2EDE6; --mut:#A9A199;
    --line:#3A342C; --maroon:#C77A86; --maroon-d:#E0A3AC;
  }
}
:root[data-theme=dark]{
  --bg:#17150F; --panel:#211E18; --ink:#F2EDE6; --mut:#A9A199;
  --line:#3A342C; --maroon:#C77A86; --maroon-d:#E0A3AC;
}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
  font-size:14px;display:flex;flex-direction:column;overflow:hidden}

header.bar{display:flex;align-items:center;gap:10px;padding:8px 14px;
  background:var(--panel);border-bottom:1px solid var(--line);flex:0 0 auto;
  flex-wrap:nowrap;overflow-x:auto;overflow-y:hidden;white-space:nowrap}
header.bar::-webkit-scrollbar{height:6px}
header.bar>*{flex:0 0 auto}
/* the page picker is the one thing allowed to give up width */
header.bar #pick{flex:1 1 200px;min-width:110px}
.brand{font-weight:700;color:var(--maroon);letter-spacing:.2px;white-space:nowrap}
.brand small{display:block;font-weight:400;color:var(--mut);font-size:11px}
select,button,input{font:inherit;color:inherit}
select,input[type=search]{background:var(--bg);border:1px solid var(--line);
  border-radius:7px;padding:6px 9px;max-width:38vw;text-overflow:ellipsis}
button{background:var(--bg);border:1px solid var(--line);border-radius:7px;
  padding:6px 11px;cursor:pointer}
button:hover{border-color:var(--maroon)}
button.on{background:var(--maroon);border-color:var(--maroon);color:#fff}
.spacer{flex:1 1 0;min-width:0}
@media (max-width:1500px){ #stat{display:none} }
@media (max-width:1180px){ .brand small{display:none} }
.pill{font:600 11px/1 var(--mono);padding:4px 7px;border-radius:999px;
  border:1px solid var(--line);color:var(--mut);white-space:nowrap}
.pill.ok{color:var(--new);border-color:var(--new)}
.pill.draft{color:var(--old);border-color:var(--old)}
a.lnk{color:var(--maroon);text-decoration:none;font-weight:600;white-space:nowrap}
a.lnk:hover{text-decoration:underline}

.note{padding:6px 14px;background:var(--panel);border-bottom:1px solid var(--line);
  color:var(--mut);font-size:12px;flex:0 0 auto}
.note b{color:var(--ink)}

#stage{position:relative;flex:1 1 auto;overflow:hidden;background:var(--bg)}
.pane{position:absolute;inset:0;overflow:auto;background:#fff}
.pane.new{background:#fff}
:root[data-theme=dark] .pane,:root:not([data-theme=light]) .pane{background:#fff}
.inner{transform-origin:top left}
.pane{scroll-behavior:auto}
.tag{position:absolute;top:8px;z-index:6;font:700 11px/1 var(--mono);
  padding:5px 9px;border-radius:999px;color:#fff;pointer-events:none;
  box-shadow:0 2px 8px rgba(0,0,0,.28)}
.tag.l{left:10px;background:var(--old)}
.tag.r{right:10px;background:var(--new)}

/* wipe */
#stage.wipe .pane.new{clip-path:inset(0 0 0 var(--x));}
#handle{position:absolute;top:0;bottom:0;width:3px;background:var(--maroon);
  z-index:8;cursor:ew-resize;left:var(--x);display:none;
  box-shadow:0 0 0 1px rgba(255,255,255,.55)}
#stage.wipe #handle{display:block}
#handle::before{content:'';position:absolute;left:-11px;right:-11px;top:0;bottom:0}
#handle i{position:absolute;top:50%;left:50%;cursor:ew-resize;transform:translate(-50%,-50%);
  width:34px;height:34px;border-radius:50%;background:var(--maroon);color:#fff;
  display:grid;place-items:center;font-style:normal;font-size:13px;
  box-shadow:0 2px 10px rgba(0,0,0,.35)}

/* split */
#stage.split .pane.old{right:50%}
#stage.split .pane.new{left:50%;border-left:2px solid var(--maroon);clip-path:none}

/* An <iframe> is a REPLACED element: with width:auto it takes its intrinsic
   300x150, so left+right alone never stretch it. Without an explicit width the
   live pane rendered 305px wide and the front end served its MOBILE layout. */
/* An <iframe> is a REPLACED element: with width:auto it takes its intrinsic
   300x150, so left+right alone never stretch it. It is given an explicit
   desktop width in applyZoom() and scaled from the top-left corner. */
#frame{position:absolute;top:0;left:50%;border:0;background:#fff;display:none;
  border-left:2px solid var(--maroon);transform-origin:top left}
#stage.livemode #frame{display:block}
#stage.livemode .pane.new{display:none}
#stage.livemode .pane.old{right:50%}

.empty{padding:40px;color:#666;font-family:var(--sans)}
kbd{font:600 11px/1 var(--mono);border:1px solid var(--line);border-bottom-width:2px;
  border-radius:4px;padding:2px 5px;color:var(--mut)}
@media (max-width:900px){ .brand small{display:none} select,input[type=search]{max-width:44vw} }
</style>
</head>
<body>

<header class="bar">
  <div class="brand">AKU MC — Page Compare<small>old SharePoint page vs what Storyblok holds now</small></div>
  <input type="search" id="q" placeholder="filter pages…" style="width:150px">
  <select id="pick"></select>
  <button id="prev" title="previous page">◀</button>
  <button id="next" title="next page">▶</button>
  <span class="spacer"></span>
  <span id="stat" class="pill"></span>
  <span id="pubpill" class="pill"></span>
  <button id="mWipe" class="on">Wipe</button>
  <button id="mSplit">Side by side</button>
  <button id="mLive" title="the real front end — published pages only">Live</button>
  <select id="zoom" title="desktop width the pages are rendered at — pick a narrower one in Side by side to keep small text crisp">
    <option value="1440">1440px</option>
    <option value="1280">1280px</option>
    <option value="1152">1152px</option>
    <option value="1024">1024px</option>
    <option value="1600">1600px</option>
    <option value="1920">1920px</option>
  </select>
  <a class="lnk" id="aAku" target="_blank" rel="noopener" title="open the old page on aku.edu">aku.edu ↗</a>
  <a class="lnk" id="aEdit" target="_blank" rel="noopener" title="open this story in Storyblok">Storyblok ↗</a>
  <button id="expand" class="on" title="expand every panel in the OLD pane — AKU ships them collapsed">Panels open</button>
  <button id="theme" title="light / dark">◐</button>
</header>

<div class="note" id="note"></div>

<div id="stage" class="wipe">
  <div class="tag l">OLD — aku.edu</div>
  <div class="tag r">NEW — Storyblok</div>
  <div class="pane old" id="paneOld"><div class="inner" id="innerOld"></div></div>
  <div class="pane new" id="paneNew"><div class="inner" id="innerNew"></div></div>
  <div id="handle"><i>⇔</i></div>
  <iframe id="frame" referrerpolicy="no-referrer"></iframe>
</div>

<script id="data" type="application/json">/*__DATA__*/</script>
<script>
const PAGES = JSON.parse(document.getElementById('data').textContent);
const $ = s => document.querySelector(s);
const stage=$('#stage'), paneOld=$('#paneOld'), paneNew=$('#paneNew'),
      innerOld=$('#innerOld'), innerNew=$('#innerNew'), handle=$('#handle'),
      pick=$('#pick'), frame=$('#frame');
let idx = 0, mode='wipe', width=1440, x=0.5;

/* The new page is rendered with this stylesheet. It is deliberately plain:
   the real front end is still being built, so this shows STRUCTURE AND
   CONTENT, not final design. Saying so in the UI beats implying otherwise. */
const NEWCSS = `
:host,*{box-sizing:border-box}
body{margin:0}
.wrap{font:15px/1.7 'IBM Plex Sans',system-ui,sans-serif;color:#1C1917;
  max-width:none;margin:0;padding:24px 40px 90px}
h1{font-size:34px;line-height:1.2;margin:.2em 0 .4em}
h2{font-size:24px;margin:1.6em 0 .5em;color:#7A1F2B}
h3{font-size:19px;margin:1.4em 0 .4em}
h4{font-size:16px;margin:1.1em 0 .3em}
p{margin:0 0 1em}
a{color:#7A1F2B}
img{max-width:100%;height:auto;border-radius:6px;margin:.6em 0}
ul,ol{margin:0 0 1em;padding-left:1.35em}
li{margin:.3em 0}
li>ul,li>ol{margin:.3em 0}
blockquote{margin:1em 0;padding:.4em 0 .4em 1em;border-left:3px solid #7A1F2B;color:#5a534d}
table{border-collapse:collapse;width:100%;margin:1em 0;font-size:14px}
td,th{border:1px solid #E2DBD3;padding:7px 9px;vertical-align:top}
th{background:#F5F2EE;text-align:left}
hr{border:0;border-top:1px solid #E2DBD3;margin:1.6em 0}
.c-hero{margin:0 0 1.4em}
.c-hero-img{width:100%;border-radius:10px}
.c-hero-t h1{margin:.3em 0 0}
.c-hero-t p{color:#6B6560}
.c-rt{margin:0 0 1.2em}
.c-split{display:grid;grid-template-columns:1fr 1fr;gap:22px;align-items:center;
  margin:1.6em 0;padding:16px;border:1px solid #E2DBD3;border-radius:10px}
.c-split.rev .c-split-i{order:2}
.c-split-b h2{margin-top:0}
.c-acc{margin:1.4em 0;border:1px solid #E2DBD3;border-radius:10px;overflow:hidden}
.c-acc-i{border-bottom:1px solid #E2DBD3}
.c-acc-i:last-child{border-bottom:0}
.c-acc-i>summary{cursor:pointer;padding:12px 15px;font-weight:600;background:#F5F2EE;
  list-style:none}
.c-acc-i>summary::-webkit-details-marker{display:none}
.c-acc-i>summary::before{content:'▸';display:inline-block;margin-right:8px;
  transition:transform .15s;color:#7A1F2B}
.c-acc-i[open]>summary::before{transform:rotate(90deg)}
.c-acc-b{padding:14px 16px}
.c-eyebrow{display:block;font:600 11px/1 'IBM Plex Mono',monospace;
  text-transform:uppercase;letter-spacing:.08em;color:#8A6A2F;margin-bottom:3px}
.c-flat{background:#FDF3D7;border-left:3px solid #8A6A2F;padding:8px 11px}
.c-row{margin:1.6em 0}
.c-row-g{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));gap:16px}
.c-card,.c-prof{border:1px solid #E2DBD3;border-radius:10px;padding:14px}
.c-card h4,.c-prof h4{margin-top:.2em}
.c-prof-img{width:76px;height:76px;object-fit:cover;border-radius:50%}
.c-role{color:#6B6560;font-size:14px;margin:.1em 0 .5em}
.c-btn,.c-btn-row .c-btn{display:inline-block;background:#7A1F2B;color:#fff;
  text-decoration:none;padding:8px 15px;border-radius:7px;font-weight:600;font-size:14px}
.c-video{background:#F5F2EE;padding:10px 13px;border-radius:8px;font-size:14px}
.c-gal{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:1.2em 0}
.c-author{display:flex;gap:14px;align-items:flex-start;border-top:1px solid #E2DBD3;
  margin-top:1.6em;padding-top:1.2em}
.c-unknown{border:1px dashed #b9b2aa;border-radius:8px;padding:10px;margin:1em 0}
.c-unknown>span{font:600 11px/1 'IBM Plex Mono',monospace;color:#8A6A2F}
`;

function shadow(host){
  if(!host._sr){
    host._sr = host.attachShadow({mode:'open'});
    if(host === innerOld) wireLegacy(host._sr);
  }
  return host._sr;
}

/* AKU's accordions and tabs are Bootstrap: the panels carry `.collapse` and
   their jQuery adds `.in` on click. That jQuery cannot run here, so without
   this the panels are rendered exactly right and never open. This reproduces
   only the toggling -- the markup and the stylesheet are still AKU's. */
function wireLegacy(root){
  root.addEventListener('click', e => {
    const a = e.target.closest && e.target.closest('a[data-toggle]');
    if(!a) return;
    const sel = a.getAttribute('href') || '';
    if(!sel.startsWith('#')) return;
    e.preventDefault();
    const target = root.querySelector('[id="' + sel.slice(1) + '"]');
    if(!target) return;
    if(a.getAttribute('data-toggle') === 'collapse'){
      setPanel(a, target, !target.classList.contains('in'));
    } else {
      const wrap = a.closest('.AKUTabs') || root;
      wrap.querySelectorAll('li').forEach(li => li.classList.remove('active'));
      if(a.parentElement) a.parentElement.classList.add('active');
      wrap.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('in','active'));
      target.classList.add('in','active');
    }
  });
}

function setPanel(a, panel, open){
  panel.classList.toggle('in', open);
  panel.style.display = open ? 'block' : '';
  const g  = a && a.querySelector('.AKUAccordianIconHolderG');
  const g2 = a && a.querySelector('.AKUAccordianIconHolderG2');
  if(g)  g.style.display  = open ? 'none'  : 'block';
  if(g2) g2.style.display = open ? 'block' : 'none';
}

let panelsOpen = true;
function applyPanels(){
  const root = innerOld._sr;
  if(!root) return;
  root.querySelectorAll('.panel-collapse').forEach(panel => {
    const head = panel.parentElement &&
                 panel.parentElement.querySelector('a.AKUAccordianPanelGrey');
    setPanel(head, panel, panelsOpen);
  });
}

function render(){
  const p = PAGES[idx]; if(!p) return;
  document.title = `${p.title} — AKU MC Compare`;
  $('#aAku').href = p.aku; $('#aEdit').href = p.edit;
  $('#stat').textContent = `${p.oldLen.toLocaleString()} → ${p.newLen.toLocaleString()} ch · ${p.bloks} bloks`;
  const pub = $('#pubpill');
  pub.textContent = p.pub ? 'published' : 'draft';
  pub.className = 'pill ' + (p.pub ? 'ok' : 'draft');

  shadow(innerOld).innerHTML = p.old || '<div class="empty">no archived copy of this page</div>';
  shadow(innerNew).innerHTML = `<style>${NEWCSS}</style><div class="wrap">${p.new || '<p style="padding:40px;color:#8A6A2F;font:600 15px/1.5 sans-serif">This story has no bloks in Storyblok yet.</p>'}</div>`;

  frame.src = (mode==='live') ? p.live : 'about:blank';
  $('#note').innerHTML = mode==='live'
    ? (p.pub ? `<b>Live front end.</b> This is the real rendered page. A cross-origin frame cannot be scrolled in step with the left pane, so scroll each separately.`
             : `<b>This page is a draft</b>, so the live front end renders an empty shell. Switch to Wipe or Side by side to see its content.`)
    : `<b>Left</b> is the archived SharePoint page with aku.edu's own stylesheet; its JavaScript-loaded accordions, tabs and galleries are rebuilt from the recovered SharePoint lists using AKU's own markup and CSS. <b>Right</b> is what Storyblok holds now, drawn with a plain stylesheet — the front end is still being built, so this shows content and structure, not final design. Drag the divider, or use <kbd>←</kbd> <kbd>→</kbd>.`;

  applyPanels();
  pick.value = String(idx);
  writeHash();
  applyZoom();
  paneOld.scrollTop = paneNew.scrollTop = 0;
}

function applyZoom(){
  const halfWidth = (mode==='split' || mode==='live');
  const avail = halfWidth ? stage.clientWidth/2 : stage.clientWidth;
  if(mode==='live'){
    // Lay the frame out at the full desktop width so the site picks its
    // DESKTOP breakpoint, then scale the whole frame down to fit the half
    // pane. Sizing the frame to 960px instead just asks for the tablet layout.
    const fs = avail / width;
    frame.style.width  = width + 'px';
    frame.style.height = (stage.clientHeight / fs) + 'px';
    frame.style.transform = `scale(${fs})`;
  }
  // No `Math.min(1, ...)` cap. Capping at 1 renders a 1440px page inside a
  // 1900px pane and leaves 460px of blank white on the right of BOTH panes --
  // which is the strip the wipe divider uncovers first, so the new page looked
  // like it had failed to load. Scale up as well as down so the pane is filled.
  const s = Math.max(0.25, Math.min(2.5, avail / width));
  for(const el of [innerOld, innerNew]){
    // `zoom`, not `transform:scale()`. A transform scales what you SEE and
    // leaves the layout box at full size, so the pane keeps scrolling long
    // after the content ends and the two sides never line up. zoom scales the
    // layout, which is what the scroll sync measures.
    el.style.zoom = s;
    el.style.width = width+'px';
  }
}

/* Scroll in lockstep. Both panes are elements in THIS document, which is the
   whole reason they are not iframes -- a cross-origin frame's scrollTop is
   unreadable, and an unsynced wipe compares two different places. */
let lock = false;
function sync(from, to){
  from.addEventListener('scroll', () => {
    if(lock) return; lock = true;
    const r = from.scrollTop / Math.max(1, from.scrollHeight - from.clientHeight);
    to.scrollTop = r * Math.max(0, to.scrollHeight - to.clientHeight);
    requestAnimationFrame(()=>{ lock = false; });
  }, {passive:true});
}
sync(paneOld, paneNew); sync(paneNew, paneOld);

function setX(px){
  x = Math.min(1, Math.max(0, px / stage.clientWidth));
  stage.style.setProperty('--x', (x*100).toFixed(2)+'%');
  handle.style.left = (x*100).toFixed(2)+'%';
}
setX(stage.clientWidth/2);

let drag = false;
handle.addEventListener('pointerdown', e => { drag = true; handle.setPointerCapture(e.pointerId); });
handle.addEventListener('pointermove', e => { if(drag) setX(e.clientX - stage.getBoundingClientRect().left); });
handle.addEventListener('pointerup',   e => { drag = false; handle.releasePointerCapture(e.pointerId); });
stage.addEventListener('dblclick', e => { if(mode==='wipe') setX(e.clientX - stage.getBoundingClientRect().left); });

function setMode(m){
  mode = m;
  stage.className = m==='live' ? 'livemode' : m;
  for(const [b,k] of [['#mWipe','wipe'],['#mSplit','split'],['#mLive','live']])
    $(b).classList.toggle('on', k===m);
  render();
}
$('#mWipe').onclick  = ()=>setMode('wipe');
$('#mSplit').onclick = ()=>setMode('split');
$('#mLive').onclick  = ()=>setMode('live');
$('#zoom').onchange  = e => { width = +e.target.value; applyZoom(); };
$('#prev').onclick   = ()=>{ idx = (idx-1+PAGES.length)%PAGES.length; render(); };
$('#next').onclick   = ()=>{ idx = (idx+1)%PAGES.length; render(); };
pick.onchange = e => { idx = +e.target.value; render(); };

function fillPicker(filter){
  const f = (filter||'').toLowerCase();
  pick.innerHTML = '';
  PAGES.forEach((p,i)=>{
    if(f && !(p.title+' '+p.path).toLowerCase().includes(f)) return;
    const o = document.createElement('option');
    o.value = i; o.textContent = `${String(p.sr).padStart(2,'0')} · ${p.title}`;
    pick.appendChild(o);
  });
  if(!pick.querySelector(`option[value="${idx}"]`) && pick.options.length){
    idx = +pick.options[0].value; render();
  }
}
$('#q').oninput = e => fillPicker(e.target.value);

$('#expand').onclick = ()=>{
  panelsOpen = !panelsOpen;
  $('#expand').classList.toggle('on', panelsOpen);
  $('#expand').textContent = panelsOpen ? 'Panels open' : 'Panels closed';
  applyPanels();
};
$('#theme').onclick = ()=>{
  const cur = document.documentElement.getAttribute('data-theme');
  const next = cur==='dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  try{ localStorage.setItem('akuCmpTheme', next); }catch(e){}
};
try{ const t = localStorage.getItem('akuCmpTheme');
     if(t) document.documentElement.setAttribute('data-theme', t); }catch(e){}

addEventListener('keydown', e=>{
  if(e.target.tagName==='INPUT'||e.target.tagName==='SELECT') return;
  const step = e.shiftKey ? 80 : 24;
  if(e.key==='ArrowLeft'){ setX(x*stage.clientWidth - step); e.preventDefault(); }
  if(e.key==='ArrowRight'){ setX(x*stage.clientWidth + step); e.preventDefault(); }
  if(e.key===']'){ $('#next').click(); }
  if(e.key==='['){ $('#prev').click(); }
  if(e.key==='w'){ setMode('wipe'); }
  if(e.key==='s'){ setMode('split'); }
});
addEventListener('resize', ()=>{ applyZoom(); setX(x*stage.clientWidth); });

function readHash(){
  const m = (location.hash||'').replace('#','').split('/');
  const sr = parseInt(m[0],10);
  if(!isNaN(sr)){
    const i = PAGES.findIndex(p=>p.sr===sr);
    if(i>=0) idx = i;
  }
  if(['wipe','split','live'].includes(m[1])) mode = m[1];
}
function writeHash(){
  try{ history.replaceState(null,'',`#${PAGES[idx].sr}/${mode}`); }catch(e){}
}
addEventListener('hashchange', ()=>{ readHash(); setMode(mode); });

readHash();
stage.className = mode==='live' ? 'livemode' : mode;
for(const [b,k] of [['#mWipe','wipe'],['#mSplit','split'],['#mLive','live']])
  $(b).classList.toggle('on', k===mode);
fillPicker(''); render();
</script>
</body>
</html>
'''

if __name__ == '__main__':
    main()
