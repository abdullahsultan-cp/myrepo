"""Student club page (students/clubs-societies/<country>/...) -> the agreed layout.

    hero | About the <Club|Society> | Executive Committee (publications, grouped by role)
         | Signature Events (sub_inner_group outcomes) | the country cards (unchanged)
         | library_navigator from the old sidebar

The template these pages were cloned from left flow-cytometry text in the
committee accordion's description; the committee is rebuilt from the old
page's table instead. The country cards use generic `card` bloks, which all
club pages share and the site renders, so they are kept as they are.

Usage (from Pages-Pipeline/pipeline, after fix_page.py <sid> <url> has saved
the story and the old HTML):  python club_page.py <sid>, then python apply_fix.py <sid>
"""
import copy
import json
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, '.')
import build_from_sheet as B  # noqa: E402
import build_pages as bp  # noqa: E402
import house_style as hs  # noqa: E402
import sheet  # noqa: E402
for _s in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252
    if hasattr(_s, 'reconfigure'):
        _s.reconfigure(encoding='utf-8', errors='replace')

F = '../out/work/fix/'
SID = sys.argv[1]
st = json.load(open(F + SID + '.before.json', encoding='utf-8'))
soup = BeautifulSoup(open(F + 'html/' + SID + '.html', encoding='utf-8').read(), 'html.parser')
cells = [d for d in soup.find_all('div') if (d.get('id') or '').startswith('MSOZoneCell')]
cell = max(cells, key=lambda c: len(c.get_text(' ', strip=True)))


def uid(k):
    return bp.uid(f'fix-{SID}-{k}')


body = st['content']['body']
hero = copy.deepcopy(next(b for b in body if b['component'] == 'hero'))
hero['title'] = hs.clean(hero['title'])
name = hero['title']
intro = []
h2s = cell.find_all('h2')
for p in cell.find_all('p'):
    if h2s and p.find_previous('h2') is not None:
        break
    ns = bp.split_breaks(bp.block(p, []))
    intro += [n for n in ns if hs.text_of(n)]
intro = hs.strip_invisibles(intro)
kind = 'Society' if 'society' in name.lower() else 'Club'
out = [hero, hs.section_text(uid, 'intro', f'About the {kind}', intro)]

table = cell.find('table')
if table:
    pub = hs.publications(uid, 'exco', 'grouped', 'Executive Committee')
    for i, r in enumerate(table.find_all('tr')):
        cols = [hs.clean(c.get_text(' ')) for c in r.find_all(['td', 'th'])]
        if len(cols) < 2 or not cols[0]:
            continue
        people = [n.strip() for n in cols[1].split('|') if n.strip()]
        items = []
        for k, person in enumerate(people):
            it = hs.pub_item(uid, f'g{i}-{k}', person, '', [])
            it['description'] = {'type': 'doc', 'content': []}
            items.append(it)
        pub['groups'].append({'_uid': uid(f'g{i}'), 'component': 'faculty_publication_group',
                              'title': cols[0], 'link': hs.link(''), 'items': items})
    out.append(pub)

ev_head = next((h for h in h2s if 'event' in h.get_text().lower()), None)
if ev_head:
    events = []
    for el in ev_head.find_all_next(['p', 'li', 'h2']):
        if el.name == 'h2':
            break
        if el.name == 'p' and el.find_parent('li'):
            continue
        t = hs.clean(el.get_text(' '))
        if t and t not in events:
            events.append(t)
    if events:
        out.append(hs.sub_group(uid, 'events', [(e, '') for e in events], hs.clean(ev_head.get_text(' ')) or 'Signature Events'))

for b in body:
    if b['component'] == 'teaching_impact':
        b = copy.deepcopy(b)
        b['spacing_preset'] = b.get('spacing_preset') or 'section'   # he set it by hand
        out.append(b)
nav = hs.rebuild_navigator({'_uid': uid('lib'), 'component': 'library_navigator'}, soup, uid, sheet.absolute)
if nav.get('libraries'):
    out.append(nav)
else:
    out += [copy.deepcopy(b) for b in body if b['component'] in ('quick_actions', 'library_navigator')]

for b in out:
    if b['component'] == 'faculty_publications':
        print('committee', [(g['title'], [it['title'] for it in g['items']]) for g in b['groups']])
    if b['component'] == 'sub_inner_group':
        print('events', [x['label'] for x in b['outcome_items']])
_sch = B.Schema('../out/work/components_live.json')
out = _sch.sanitize(out)
probs = [p for p in _sch.problems(out) if 'teaching_impact.cards' not in p]
print([b['component'] for b in out], '| schema (excluding the shared country cards):', probs)
if probs:
    raise SystemExit(1)
after = copy.deepcopy(st)
after['content']['body'] = out
json.dump(after, open(F + SID + '.after.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
