"""fix_page.py -- rebuild ONE existing Storyblok page from its old aku.edu page.

    python fix_page.py <editor-url-or-story-id> <old-aku-url>              # dry run
    python fix_page.py <editor-url-or-story-id> <old-aku-url> --apply      # write, unpublished
    python fix_page.py <editor-url-or-story-id> <old-aku-url> --apply --publish

One command for what was eight manual steps per page on 5 Nov 2026: read the
story, download the old page (retrying -- aku.edu drops connections), read the
sibling pages in the same folder, build the body in the house style
(house_style.py), show what changes, and -- only with --apply -- write it in
place with a before/after backup.

What it keeps from the story as it is:
  * the content type (page / speech_article / event_article) -- never changed
  * the story's name, slug and folder
  * the hero, if the page has one (its title is cleaned of zero-width spaces)
  * its shared section blocks (country cards, contact banner) when the build
    has none of that kind

What it tidies on the way: site-relative links made absolute, 'tel:' links
made dialable, zero-width spaces out of every title. The legacy left sidebar
always becomes a library_navigator (build_from_sheet).

It refuses to write when:
  * the story changed since it was read (someone is editing it)
  * the build carries under 70% of the old page's text
  * a blok does not fit the live component schema
  * the build references a picture that is not uploaded yet -- run the media
    step first; a page with a broken image is worse than the old one

Work files: out/work/fix/<story_id>.{before,after}.json, html/, prepared/.
Backups:    backup/storyblok/fixes/fix_<story_id>_{BEFORE,AFTER}_<time>.json.gz
"""
import argparse
import copy
import gzip
import json
import os
import re
import sys
import time

import build_from_sheet as B
import build_pages as bp
import documents
import house_style as hs
import paths
import recover_widgets as rw
import requests
import sheet
from create_pages import SB

FIX = paths.work('fix')
BACKUP = os.path.join(os.path.dirname(paths.OUT), 'backup', 'storyblok', 'fixes')
COMPONENTS = paths.work('components_live.json')
# Windows consoles default to cp1252 and die on the first curly quote.
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, 'reconfigure'):
        _s.reconfigure(encoding='utf-8', errors='replace')


def ensure_components(sb, max_age_days=7):
    """The live component schemas, fetched when absent or a week old -- a new
    laptop has no out/work/ (gitignored), and the schema check needs them."""
    fresh = os.path.exists(COMPONENTS) and time.time() - os.path.getmtime(COMPONENTS) < max_age_days * 86400
    if fresh:
        return COMPONENTS
    r = sb.call('GET', 'components')
    r.raise_for_status()
    os.makedirs(os.path.dirname(COMPONENTS), exist_ok=True)
    json.dump(r.json()['components'], open(COMPONENTS, 'w', encoding='utf-8', newline='\n'),
              indent=1, ensure_ascii=False)
    print(f'fetched {len(r.json()["components"])} live component schemas -> {COMPONENTS}')
    return COMPONENTS


def story_id(arg):
    m = re.search(r'(\d{9,})\D*$', arg)
    if not m:
        raise SystemExit(f'no story id in {arg!r}')
    return m.group(1)


def fetch_old(url, dest):
    """The old page, retried: aku.edu refuses roughly one connection in five."""
    sess, last = requests.Session(), None
    for i in range(8):
        try:
            r = sess.get(url, headers={'User-Agent': rw.UA['User-Agent']}, timeout=45)
            if r.status_code == 200:
                r.encoding = 'utf-8'
                with open(dest, 'w', encoding='utf-8', newline='\n') as fh:
                    fh.write(r.text)
                return r.text, sess
            last = f'HTTP {r.status_code}'
            if r.status_code < 500:
                break
        except requests.RequestException as e:
            last = type(e).__name__
        time.sleep(min(30, 4 * (i + 1)))
    raise SystemExit(f'could not fetch {url}: {last}')


def widgets_of(raw, sess):
    out = []
    for m in rw.CALL.finditer(raw):
        fn, div, lst, web = m.group(1), m.group(2), m.group(3), m.group(4)
        if not lst or not web or f'id="{div}"' not in raw:
            continue                                # a dead initialiser (MC-PK §4)
        data = rw.fetch_list(sess, web, lst, rw.KIND[fn])
        if data:
            out.append({'kind': rw.KIND[fn], 'div': div, 'list': lst,
                        'title': (m.group(5) or '').strip(), 'offset': raw.find(f'id="{div}"'),
                        'data': data})
    return sorted(out, key=lambda w: w['offset'])


def siblings(sb, folder):
    out, page = [], 1
    while True:
        r = sb.call('GET', f'stories?starts_with={folder}/&per_page=100&page={page}&story_only=1')
        batch = r.json().get('stories') or []
        for s in batch:
            if s['full_slug'].rsplit('/', 1)[0] == folder:
                out.append(sb.call('GET', f"stories/{s['id']}").json()['story'])
        if len(batch) < 100:
            return out
        page += 1


def outline(body):
    return ' | '.join(b.get('component', '?') for b in body)


def unresolved_images(x, out=None):
    out = [] if out is None else out
    if isinstance(x, dict):
        if x.get('_src_original') and not x.get('filename'):
            out.append(x['_src_original'])
        for v in x.values():
            unresolved_images(v, out)
    elif isinstance(x, list):
        for v in x:
            unresolved_images(v, out)
    return out


# The shared country cards (teaching_impact) are NOT carried: Abdullah deleted
# them from every page fixed with them (Wellness UG, Experience KE, Mission &
# Vision, 9 Nov 2026). club_page.py keeps them on the club pages.
SHARED = ('carousel_section', 'strip_banner')
CARD_SCHEMA = re.compile(r'teaching_impact\.cards\[\d+\]: card not allowed')


def carry_shared(body, story_body):
    """The story's own shared section blocks (institutes carousel, contact
    banner), when the build has none of that kind -- they were dropped on pages
    whose siblings do not carry them (Counselling and Wellness Uganda lost its
    contact banner). They go after the content, before the navigator."""
    have = {b.get('component') for b in body}
    add = [copy.deepcopy(b) for b in story_body if b.get('component') in SHARED
           and b.get('component') not in have]
    if not add:
        return body, []
    k = next((i for i, b in enumerate(body) if b.get('component') in
              ('library_navigator', 'quick_actions')), len(body))
    return body[:k] + add + body[k:], [b['component'] for b in add]


def words(x):
    return set(re.findall(r'[a-z0-9@.]+', bp.flat_text(x).lower() if isinstance(x, dict) and 'type' in x
                          else json.dumps(x, ensure_ascii=False).lower()))


def drop_contact_text(body):
    """A 'Contact Us' text section whose every word is already in the page's
    contact banner (strip_banner) says it twice. Returns the body, and whether
    one went."""
    banner = next((b for b in body if b.get('component') == 'strip_banner'), None)
    if not banner:
        return body, False
    have = words(banner)
    have |= {re.sub(r'\D', '', w) for w in have}            # phone numbers, digits only
    for b in body:
        if b.get('component') != 'rich_text':
            continue
        ns = b['content'].get('content') or []
        heads = [hs.text_of(n) for n in ns if n.get('type') == 'heading']
        if not heads or not heads[0].lower().startswith('contact'):
            continue
        rest = [n for n in ns if n.get('type') != 'heading']
        ws = set().union(*[words(n) for n in rest]) if rest else set()
        ws = {w.strip('.') for w in ws} - {'', 'phone', 'number', 'email', 'address', 'e', 't', 'tel'}
        if all(w in have or re.sub(r'\D', '', w) in have and re.sub(r'\D', '', w) for w in ws):
            return [x for x in body if x is not b], True
    return body, False


def tidy_links(x):
    """Every link the page writes: site-relative hrefs made absolute (a bare
    '/about/...' resolves against the NEW site and 404s), 'tel: +256 77...'
    made a dialable 'tel:+25677...'. Returns how many were changed."""
    n = 0

    def fix(u):
        u2 = u
        if u.startswith('/') and not u.startswith('//'):
            u2 = sheet.absolute(u)
        elif u.lower().startswith('tel:'):
            u2 = 'tel:' + re.sub(r'[^\d+]', '', u[4:])
        return u2

    def walk(v):
        nonlocal n
        if isinstance(v, dict):
            if v.get('type') == 'link' and isinstance(v.get('attrs'), dict) and v['attrs'].get('href'):
                new = fix(v['attrs']['href'])
                if new != v['attrs']['href']:
                    v['attrs']['href'], n = new, n + 1
            if v.get('fieldtype') == 'multilink' and v.get('linktype') == 'url' and v.get('url'):
                new = fix(v['url'])
                if new != v['url']:
                    v['url'] = v['cached_url'] = new
                    n += 1
            for w in v.values():
                walk(w)
        elif isinstance(v, list):
            for w in v:
                walk(w)
    walk(x)
    return n


def tidy_titles(x):
    """Zero-width spaces out of every title/highlight/label/name ('About
    Counselling a​nd Wellness'). Spacing is left alone: a highlight's
    leading space is how the title and highlight join."""
    if isinstance(x, dict):
        for k in ('title', 'highlight', 'label', 'name', 'short_name', 'eyebrow'):
            if isinstance(x.get(k), str):
                x[k] = x[k].translate(hs.INVISIBLE)
        if x.get('component') == 'strip_banner' and hs.clean(x.get('title')) == 'Contact':
            x['title'] = 'Contact Us'                # he renamed it by hand (TISC)
        for v in x.values():
            tidy_titles(v)
    elif isinstance(x, list):
        for v in x:
            tidy_titles(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('story')
    ap.add_argument('old_url')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--publish', action='store_true')
    a = ap.parse_args()

    sid = story_id(a.story)
    for d in ('html', 'prepared'):
        os.makedirs(os.path.join(FIX, d), exist_ok=True)
    sb = SB()
    st = sb.call('GET', f'stories/{sid}').json()['story']
    before_path = os.path.join(FIX, f'{sid}.before.json')
    json.dump(st, open(before_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    folder = st['full_slug'].rsplit('/', 1)[0]
    root = (st.get('content') or {}).get('component') or 'page'
    print(f"story   {st['full_slug']}  ({root}, last saved by "
          f"{(st.get('last_author') or {}).get('friendly_name')}, published={st['published']})")

    raw, sess = fetch_old(a.old_url, os.path.join(FIX, 'html', f'{sid}.html'))
    widgets = widgets_of(raw, sess)
    sibs = [s for s in siblings(sb, folder) if s['id'] != st['id']]
    ref_path = os.path.join(FIX, f'{sid}.siblings.json')
    json.dump(sibs, open(ref_path, 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'old     {a.old_url}  ({len(raw):,} bytes, {len(widgets)} widget list(s)); '
          f'{len(sibs)} sibling page(s)')

    B.PREP_DIR = os.path.join(FIX, 'prepared')
    bp.HTML_DIR = B.PREP_DIR
    row = {'Serial No.': sid, 'Old URL': a.old_url, 'Storyblok Path': st['full_slug'],
           'Page Name': st['name'], '_root': root}
    schema = B.Schema(ensure_components(sb))
    p = B.build(row, B.Reference(ref_path), schema, os.path.join(FIX, 'html'), widgets)

    content = copy.deepcopy(st['content'])
    body = p['content']['body']
    old_hero = next((b for b in content.get('body') or [] if b.get('component') == 'hero'), None)
    if body and body[0].get('component') == 'hero' and old_hero:
        keep = copy.deepcopy(old_hero)
        keep['title'] = hs.clean(keep.get('title')) or body[0]['title']
        body[0] = keep
    body, carried = carry_shared(body, content.get('body') or [])
    body = [b for b in body if b.get('component') != 'teaching_impact']
    body, contact_dup = drop_contact_text(body)
    relinked = tidy_links(body)
    tidy_titles(body)
    content['body'] = body
    if root != 'page' and p['content'].get('title') and not hs.clean(content.get('title')):
        content['title'] = p['content']['title']

    soup = B.BeautifulSoup(open(os.path.join(B.PREP_DIR, f'{sid}.html'), encoding='utf-8').read(),
                           'html.parser')
    src = len(hs.clean(B.MARK.sub('', ' '.join(c.get_text(' ', strip=True) for c in bp.body_of(soup)))))
    got = len(bp.payload_text([b for b in body if b.get('component') not in
                               ('library_navigator', 'quick_actions', 'strip_banner',
                                'teaching_impact', 'carousel_section', 'hero')]))
    # Country cards are generic `card` bloks inside teaching_impact on every
    # students/* page: a team-wide design the site renders. Not a problem.
    # fields the space has since removed (sub_inner_group.align, 10 Nov 2026)
    # are dropped, not reported: the editor cannot show them anyway
    body = content['body'] = schema.sanitize(body)
    probs = [p for p in schema.problems(body) if not CARD_SCHEMA.search(p)]
    missing = unresolved_images(body)

    print(f"\nnow     {outline(st['content'].get('body') or [])}")
    print(f'after   {outline(body)}')
    print(f'text    old page {src:,} chars -> built {got:,}')
    if carried:
        print(f"kept    from the story: {', '.join(carried)}")
    if any(b.get('component') == 'teaching_impact' for b in st['content'].get('body') or []):
        print('dropped the shared country cards (teaching_impact) -- house style')
    if contact_dup:
        print('dropped a "Contact Us" text section -- every word is in the contact banner')
    if relinked:
        print(f'links   {relinked} made absolute / dialable')
    nav = next((b for b in body if b.get('component') == 'library_navigator'), None)
    if nav:
        print(f"        library_navigator: {len(nav.get('libraries') or [])} entries, "
              f"{sum(len(x.get('pages') or []) for x in nav.get('libraries') or [])} sub-pages")
    for b in body:
        if b.get('component') == 'faculty_publications':
            n = len(b.get('groups') or b.get('items') or [])
            print(f"        faculty_publications ({b['variant']}): {n} "
                  f"{'groups' if b.get('groups') else 'items'}")
        if b.get('component') == 'sub_inner_group':
            n = len(b.get('items') or b.get('outcome_items') or [])
            print(f"        sub_inner_group ({b['variant']}) {b.get('title', '')}{b.get('highlight', '')}: {n} items")
    after = copy.deepcopy(st)
    after['content'] = content
    json.dump(after, open(os.path.join(FIX, f'{sid}.after.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)

    stop = []
    if src > 300 and got < src * 0.7:
        stop.append(f'content lost: {got} of {src} chars')
    if probs:
        stop.append('schema: ' + '; '.join(probs[:5]))
    if missing:
        stop.append(f'{len(missing)} picture(s) not uploaded: {missing[:3]}')
    if stop:
        print('\nNOT WRITING:\n  ' + '\n  '.join(stop))
        raise SystemExit(1)
    # PDFs on aku.edu -> uploaded Storyblok assets in the story's own folder,
    # linked as assets (Abdullah, 6 Nov 2026). Listed on a dry run, done on --apply.
    print('\nPDF links:')
    content, pdfs, pdf_problems = documents.relink(content, folder, a.apply, log=print)
    if not pdfs and not pdf_problems and not documents.find_links(content):
        print('    none')
    if not a.apply:
        print('\ndry run -- add --apply to write' + (' and publish' if a.publish else ''))
        return
    if pdf_problems:
        print(f'  {len(pdf_problems)} PDF(s) could not be fetched; their links are left as they were')

    cur = sb.call('GET', f'stories/{sid}').json()['story']
    if cur['updated_at'] != st['updated_at']:
        raise SystemExit(f"story changed while building ({cur['updated_at']}); run again")
    r = sb.call('PUT', f'stories/{sid}', {'story': {'name': cur['name'], 'slug': cur['slug'],
                                                    'parent_id': cur['parent_id'],
                                                    'content': content},
                                          'publish': 1 if a.publish else 0})
    if r.status_code not in (200, 201, 204):
        raise SystemExit(f'PUT failed {r.status_code}: {r.text[:300]}')
    time.sleep(1)
    back = sb.call('GET', f'stories/{sid}').json()['story']
    ts = time.strftime('%Y%m%d-%H%M%S')
    os.makedirs(BACKUP, exist_ok=True)
    for tag, obj in (('BEFORE', st), ('AFTER', back)):
        with gzip.open(os.path.join(BACKUP, f'fix_{sid}_{tag}_{ts}.json.gz'), 'wt',
                       encoding='utf-8') as fh:
            json.dump(obj, fh, ensure_ascii=False)
    print(f"\nwritten: {outline(back['content']['body'])}")
    print(f"published={back['published']} unpublished_changes={back.get('unpublished_changes')}"
          f'  backups -> {BACKUP}')


if __name__ == '__main__':
    main()
