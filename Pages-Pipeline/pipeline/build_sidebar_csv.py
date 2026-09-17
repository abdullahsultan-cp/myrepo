"""build_sidebar_csv.py -- which built pages carry a sidebar, with both links.

Writes out/rabee-pages-with-sidebar.csv: one row per built page whose legacy
aku.edu page has a side navigation column, with the Storyblok links beside the
legacy one.

HOW A SIDEBAR IS DETECTED
-------------------------
AKU's section navigation is SharePoint's quick launch, rendered into a column
beside the content:

    div.row
      div.col-md-3.col-sm-3.hidden-xs.LeftNav-zone-padding   <- the sidebar
        div#zz3_V4QuickLaunchMenu.ms-core-listMenu-verticalBox
      div.col-md-9.col-sm-9                                  <- the content

Side is read from the column's POSITION among its siblings rather than from its
name -- first child is a left sidebar, last is a right one. Every built page
that has one has it on the left; the scan also looks for a narrow column placed
AFTER a wide one anywhere in the content area, and finds none.

`sidebar_items` is what the sidebar actually lists, so the row says what would
have to be reproduced, not merely that something was there.

Run:  python Pages-Pipeline/pipeline/build_sidebar_csv.py
"""
import csv
import os
import re

from bs4 import BeautifulSoup

HERE = os.path.dirname(os.path.abspath(__file__))
PP = os.path.dirname(HERE)
SRC = os.path.join(PP, 'out', 'rabee-pages-links-v2.csv')
LEGACY = os.path.join(PP, 'out', 'work', 'legacy_html')
OUT = os.path.join(PP, 'out', 'rabee-pages-with-sidebar.csv')

NARROW = re.compile(r'^col-(?:md|lg|sm)-[1-4]$')
WIDE = re.compile(r'^col-(?:md|lg|sm)-(?:[7-9]|1[0-2])$')


def squash(text):
    return re.sub(r'[\s​]+', ' ', text or '').strip()


def sidebar_of(soup):
    """(side, column) for the page's side navigation, or (None, None)."""
    nav = soup.find(id=re.compile('QuickLaunchMenu'))
    col = None
    if nav is not None:
        col = nav
        while col is not None and not any(
                str(c).startswith('col-') for c in (col.get('class') or [])):
            col = col.parent
    if col is None:
        col = soup.select_one('[class*=LeftNav-zone-padding]')
    if col is None or col.parent is None:
        return None, None
    sibs = col.parent.find_all('div', recursive=False)
    if col not in sibs:
        return 'left', col
    return ('left' if sibs.index(col) == 0 else 'right'), col


def right_aside(soup):
    """A narrow column sitting AFTER a wide one -- a right-hand sidebar."""
    for row in soup.select('div.row'):
        kids = row.find_all('div', recursive=False)
        if len(kids) != 2:
            continue
        left_cls = (kids[0].get('class') or [])
        right_cls = (kids[1].get('class') or [])
        if not any(WIDE.match(c) for c in left_cls):
            continue
        if not any(NARROW.match(c) for c in right_cls):
            continue
        if any('LeftNav' in c for c in right_cls):
            continue
        if len(squash(kids[1].get_text(' ', strip=True))) > 40:
            return kids[1]
    return None


def main():
    rows = list(csv.DictReader(open(SRC, encoding='utf-8')))
    out = []
    for r in rows:
        path = os.path.join(LEGACY, f"{r['serial']}.html")
        if not os.path.exists(path):
            continue
        soup = BeautifulSoup(open(path, encoding='utf-8', errors='replace').read(),
                             'html.parser')
        for x in soup.find_all(['style', 'script']):
            x.decompose()

        side, col = sidebar_of(soup)
        if col is None:
            # the left nav is the common case; a right-hand aside is checked
            # separately so a page with only that is not missed
            body = BeautifulSoup(open(path, encoding='utf-8', errors='replace').read(),
                                 'html.parser')
            for x in body.find_all(['style', 'script', 'footer', 'nav']):
                x.decompose()
            col = right_aside(body)
            side = 'right' if col is not None else None
        if col is None:
            continue

        links = col.find_all('a')
        labels = []
        for a in links:
            t = squash(a.get_text(' ', strip=True))
            if t and t not in labels:
                labels.append(t)
        if not labels:
            continue          # an empty nav column is not a sidebar

        out.append({
            'sr_no': r['sr_no'],
            'serial': r['serial'],
            'title': r['title'],
            'sidebar_side': side,
            'sidebar_link_count': len(labels),
            'sidebar_items': ' | '.join(labels),
            'legacy_link': r['aku_link'],
            'sb_editorial_link': r['sb_editorial_link'],
            'sb_preview_link': r['sb_preview_link'],
            'storyblok_path': r['storyblok_path'],
            'published': r['published'],
            'story_id': r['story_id'],
        })

    out.sort(key=lambda x: int(x['sr_no']))
    cols = ['sr_no', 'serial', 'title', 'sidebar_side', 'sidebar_link_count',
            'sidebar_items', 'legacy_link', 'sb_editorial_link',
            'sb_preview_link', 'storyblok_path', 'published', 'story_id']
    with open(OUT, 'w', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(out)

    sides = {}
    for o in out:
        sides[o['sidebar_side']] = sides.get(o['sidebar_side'], 0) + 1
    print(f'{len(out)} of {len(rows)} built pages have a sidebar  {sides}')
    print(f'-> {OUT}')
    for o in out[:10]:
        print(f"   sr {o['sr_no']:>3}  {o['title'][:34]:<36} {o['sidebar_side']:<6} "
              f"{o['sidebar_link_count']:>2} links")


if __name__ == '__main__':
    main()
