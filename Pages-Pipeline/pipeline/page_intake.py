"""The page inventory: what AKU wants migrated, and which web holds each page.

Until now two files answered this and both said 3,340: `AKU-EN_1.HTM`, scraped
by join.py, and `aku-university-visible-pages.csv`, read by
build_migration_plan.py.  AKU's second export, `aku-university-filtered.csv`,
carries 4,591 pages -- 1,323 the earlier pair never listed -- and drops 72 they
did.  Two inventories that disagree by a third of the corpus cannot both be
consulted, so the new export is the inventory and the old pair becomes a
cross-check: `dropped()` names what AKU has taken off the list, rather than
letting those pages vanish between two builds.

Three things in the new export the old rule could not resolve:

**The site root.**  17 pages sit at `aku.edu/Pages/*.aspx` with no section above
them -- home, contact, campuses, the AKDN page, the legal set.  The old list had
none, so `web` came out `''` and the section lookup had nothing to find.  They
are not an unclassified section: they are the root web itself, which the
permissions export lists as `http://aku.edu`, title "Home", scope Unique, owned
by CW/CA Public Affairs -- the same central-comms team that witnesses /about.
`ROOT_WEB` names that web so dest_web can place it without inventing a SEC entry
(SEC has to match the export's sections exactly, and the root is not one).

**SharePoint's own containers.**  `SitePages` and `Documents` are library names,
not folders anyone authored.  `pages`/`sitepages` were already skipped when they
appear mid-path; `Documents` was not, so `events/aasc/Documents` would have
become a folder.  Stripping them here means the four pages behind them merge
into the web that owns them, which is what library/pk/fhs/SitePages already does.

**The columns changed.**  `FileName` is gone -- derived from the URL -- and
`FinalStatus` and `References` are new.  FinalStatus is AKU's own review state:
MIGRATE 3,386, NOT_REVIEWED 1,084, UNCLEAR 121.  It is carried through to the
page map rather than filtered on, because "not reviewed" is a fact about AKU's
process, not about where the page belongs.
"""
import csv
import os
from urllib.parse import urlsplit

import paths

csv.field_size_limit(10 ** 9)

# The aku.edu root web. Not a section -- `SEC` mirrors the permissions export's
# top-level sections and the root is not one of them -- so it is named here and
# placed by dest_web directly.
ROOT_WEB = ''

# SharePoint's own library names. A page inside one belongs to the web that
# holds the library, not to a folder named after it.
CONTAINER_SEGS = {'pages', 'sitepages', 'documents'}

HOSTS = ('https://www.aku.edu/', 'http://www.aku.edu/',
         'https://aku.edu/', 'http://aku.edu/')


def relative(url):
    """The aku.edu-relative path, host and scheme stripped."""
    u = url.strip()
    for h in HOSTS:
        if u.lower().startswith(h):
            return u[len(h):]
    return urlsplit(u).path.lstrip('/')


def key(url):
    """A URL reduced to what identifies the page, for comparing two exports.

    The exports differ in case and trailing slash on the same page, so both are
    normalised away. Query strings never appear on these URLs.
    """
    return relative(url).rstrip('/').lower()


def web_of(url):
    """The web that owns this page: its path with the library container removed.

    `events/aasc/Documents/jpma_supplement.aspx` -> `events/aasc`
    `about/environment/Pages/about-us.aspx`      -> `about/environment`
    `Pages/home.aspx`                            -> `''`  (the root web)
    """
    segs = [s for s in relative(url).split('/') if s][:-1]
    while segs and segs[-1].lower() in CONTAINER_SEGS:
        segs.pop()
    return '/'.join(segs)


def file_of(url):
    """The page file name. The new export dropped the column; the URL has it."""
    segs = [s for s in relative(url).split('/') if s]
    return segs[-1] if segs else ''


def section_of(web):
    """The top-level section, or None for the root web."""
    return web.split('/')[0] if web else None


def previous_keys():
    """Every page the earlier export listed, as comparison keys.

    Empty if that file has gone, and `load()` then marks nothing new rather than
    marking everything new -- a review screen claiming 4,591 new pages would be
    worse than one claiming none.
    """
    old = paths.VISIBLE_PAGES_CSV
    if not os.path.exists(old):
        return set()
    with open(old, encoding='utf-8-sig', newline='') as fh:
        return {key(r['PageUrl']) for r in csv.DictReader(fh)
                if (r.get('PageUrl') or '').strip()}


def load(path=None):
    """Every page AKU's list names, in file order.

    Each row: file, url, web, section (None at the root), action, status,
    references, new. `status` is AKU's FinalStatus; `action` their disposition;
    `new` is True when the earlier export did not list the page, which is what
    the tree marks up so a reviewer can see this export's 1,323 additions
    without diffing two builds by hand.
    """
    path = path or paths.FILTERED_PAGES_CSV
    before = previous_keys()
    pages, seen = [], set()
    with open(path, encoding='utf-8-sig', newline='') as fh:
        for r in csv.DictReader(fh):
            url = (r.get('PageUrl') or '').strip()
            if not url:
                continue
            k = key(url)
            if k in seen:          # the export has none today; a re-export might
                continue
            seen.add(k)
            web = web_of(url)
            pages.append({
                'file': file_of(url),
                'url': url,
                'key': k,
                'web': web,
                'section': section_of(web),
                'action': (r.get('Action') or '').strip(),
                'status': (r.get('FinalStatus') or '').strip(),
                'references': (r.get('References') or '').strip(),
                'new': bool(before) and k not in before,
            })
    return pages


def dropped(pages=None):
    """Pages the previous export listed that AKU's new list no longer does.

    The old list is authoritative for nothing now, but a page silently leaving
    the corpus between two builds is exactly the kind of loss this pipeline is
    supposed to make impossible. Returns (url, action) in URL order.
    """
    old = paths.VISIBLE_PAGES_CSV
    if not os.path.exists(old):
        return []
    now = {p['key'] for p in (pages if pages is not None else load())}
    out = []
    with open(old, encoding='utf-8-sig', newline='') as fh:
        for r in csv.DictReader(fh):
            url = (r.get('PageUrl') or '').strip()
            if url and key(url) not in now:
                out.append((url, (r.get('Action') or '').strip()))
    return sorted(set(out))


if __name__ == '__main__':
    import collections

    pages = load()
    gone = dropped(pages)
    print('pages in AKU\'s list ....... %d' % len(pages))
    print('  new in this export ...... %d' % sum(1 for p in pages if p['new']))
    print('  carried over ............ %d' % sum(1 for p in pages if not p['new']))
    print('distinct webs ............. %d' % len({p['web'] for p in pages}))
    print('at the site root .......... %d' % sum(1 for p in pages if p['web'] == ROOT_WEB))
    print('dropped since the old list  %d' % len(gone))
    print()
    for col in ('status', 'action'):
        print('%s:' % col)
        for k, n in collections.Counter(p[col] for p in pages).most_common():
            print('   %-16s %d' % (k, n))
    print()
    print('sections ................. %d' % len({p['section'] for p in pages if p['section']}))
