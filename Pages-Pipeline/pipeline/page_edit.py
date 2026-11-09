"""page_edit.py -- the pieces for a hand-shaped page fix, when fix_page.py's
generic build is not what Abdullah asked for ("put this as cards", "these two in
a parallax", a club page...).

A per-page script is then ten lines, saved in out/work/fix/ (gitignored):

    import sys; sys.path.insert(0, '.')            # run from Pages-Pipeline/pipeline
    from page_edit import Page, P, H5, hs

    pg = Page('<editor-url-or-id>', '<old-aku-url>')   # live story + old page
    body = pg.body                                     # a copy, edit freely
    body.insert(2, hs.section_text(pg.uid, 'intro', 'About the Office', [P('...')]))
    pg.save(body)                                      # checks, then <sid>.after.json

    then:  python apply_fix.py <sid>                   # write in place, unpublished

`save()` refuses (unless force=True) when a word or link of the old page's main
text is missing, or a blok does not fit the live schema -- the two checks run by
hand on every page since 5 Nov 2026.
"""
import copy
import json
import os
import re
import sys

from bs4 import BeautifulSoup

import build_from_sheet as B
import build_pages as bp
import fix_page as fp
import house_style as hs
import sheet
from create_pages import SB

__all__ = ['Page', 'P', 'H5', 'hs', 'bp', 'sheet', 'link_mark', 'story_link']


def P(text, *marks):
    """A paragraph of plain text (optionally with marks such as {'type': 'bold'})."""
    t = {'type': 'text', 'text': text}
    if marks:
        t['marks'] = list(marks)
    return {'type': 'paragraph', 'content': [t]}


def H5(text):
    """A card sub-heading: level 5, never bold (house style)."""
    return {'type': 'heading', 'attrs': {'level': 5}, 'content': [{'type': 'text', 'text': text}]}


def link_mark(href):
    return {'type': 'link', 'attrs': {'href': href, 'uuid': None, 'anchor': None,
                                      'target': '_blank', 'linktype': 'url'}}


def story_link(story):
    """A multilink to another Storyblok story (dict with uuid + full_slug)."""
    return {'id': story['uuid'], 'url': '', 'linktype': 'story', 'fieldtype': 'multilink',
            'cached_url': story['full_slug']}


def _links(x, out=None):
    out = set() if out is None else out
    if isinstance(x, dict):
        if x.get('type') == 'link' and isinstance(x.get('attrs'), dict):
            out.add(sheet.norm_url(sheet.absolute(x['attrs'].get('href') or '')))
        if x.get('fieldtype') == 'multilink':
            out.add(sheet.norm_url(sheet.absolute(x.get('url') or x.get('cached_url') or '')))
        for v in x.values():
            _links(v, out)
    elif isinstance(x, list):
        for v in x:
            _links(v, out)
    return out


def _words(s):
    return set(re.findall(r"[\w@.'’-]+", hs.clean(s).lower().replace(':', ' ')))


class Page:
    def __init__(self, story, old_url=None):
        self.sid = fp.story_id(str(story))
        self.sb = SB()
        os.makedirs(os.path.join(fp.FIX, 'html'), exist_ok=True)
        self.story = self.sb.call('GET', f'stories/{self.sid}').json()['story']
        json.dump(self.story, open(self._p('before.json'), 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        a = self.story.get('last_author') or {}
        print(f"story   {self.story['full_slug']}  last saved {self.story['updated_at']} "
              f"by {a.get('friendly_name')}")
        html = os.path.join(fp.FIX, 'html', f'{self.sid}.html')
        if old_url:
            fp.fetch_old(old_url, html)
        self.soup = BeautifulSoup(open(html, encoding='utf-8').read(), 'html.parser') \
            if os.path.exists(html) else None
        self.schema = B.Schema(fp.ensure_components(self.sb))

    def _p(self, suffix):
        return os.path.join(fp.FIX, f'{self.sid}.{suffix}')

    @property
    def body(self):
        return copy.deepcopy(self.story['content'].get('body') or [])

    def uid(self, key):
        return bp.uid(f'fix-{self.sid}-{key}')

    def blocks(self, component):
        return [b for b in self.body if b.get('component') == component]

    # ------------------------------------------------------------ old page --
    @property
    def cell(self):
        """The old page's main content zone (the longest MSOZoneCell)."""
        cells = [d for d in self.soup.find_all('div') if (d.get('id') or '').startswith('MSOZoneCell')]
        return max(cells, key=lambda c: len(c.get_text(' ', strip=True))) if cells else self.soup

    def old_text(self):
        return hs.clean(self.cell.get_text(' ', strip=True))

    def old_links(self):
        return {sheet.norm_url(sheet.absolute(a['href'])) for a in self.cell.find_all('a', href=True)
                if not a['href'].startswith(('#', 'javascript:'))}

    def nodes(self, el):
        """An old-page element -> rich-text nodes (paragraph, lists, links kept)."""
        return [n for n in bp.split_breaks(bp.block(el, [])) if hs.text_of(n)]

    def navigator(self):
        """library_navigator from the old page's own left sidebar, or None."""
        nav = hs.rebuild_navigator({'_uid': self.uid('lib'), 'component': 'library_navigator'},
                                   self.soup, self.uid, sheet.absolute)
        return nav if nav.get('libraries') else None

    # ---------------------------------------------------------------- save --
    def save(self, body, force=False, skip_words=()):
        """Check the new body against the old page, then write <sid>.after.json."""
        body = self.schema.sanitize(body)            # fields the space has since removed
        fp.tidy_links(body)
        fp.tidy_titles(body)
        probs = [p for p in self.schema.problems(body) if not fp.CARD_SCHEMA.search(p)]
        text = json.dumps(body, ensure_ascii=False).lower()
        lost_w = sorted(w for w in _words(self.old_text()) - set(skip_words)
                        if w not in text and len(w) > 1) if self.soup else []
        lost_l = sorted(u for u in self.old_links() - _links(body) if u) if self.soup else []
        # an aku.edu PDF relinked to a Storyblok asset is not lost
        known = json.load(open(fp.documents.MAP, encoding='utf-8')) if os.path.exists(fp.documents.MAP) else {}
        lost_l = [u for u in lost_l if not any(sheet.norm_url(k) == u for k in known)]
        print(f"after   {fp.outline(body)}")
        print(f'schema  {probs or "ok"}')
        print(f'words   {"all kept" if not lost_w else f"MISSING {len(lost_w)}: {lost_w[:20]}"}')
        print(f'links   {"all kept" if not lost_l else f"MISSING {len(lost_l)}: {lost_l[:10]}"}')
        if (probs or lost_w or lost_l) and not force:
            raise SystemExit('NOT SAVED -- fix the above, or save(..., force=True) if intended '
                             '(e.g. a duplicate the old page repeated)')
        after = copy.deepcopy(self.story)
        after['content']['body'] = body
        json.dump(after, open(self._p('after.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'saved   {self._p("after.json")}\nnext    python apply_fix.py {self.sid}')
        return after


if __name__ == '__main__':
    sys.exit(__doc__)
