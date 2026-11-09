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
    schema = B.Schema(paths.work('components_live.json'))
    p = B.build(row, B.Reference(ref_path), schema, os.path.join(FIX, 'html'), widgets)

    content = copy.deepcopy(st['content'])
    body = p['content']['body']
    old_hero = next((b for b in content.get('body') or [] if b.get('component') == 'hero'), None)
    if body and body[0].get('component') == 'hero' and old_hero:
        keep = copy.deepcopy(old_hero)
        keep['title'] = hs.clean(keep.get('title')) or body[0]['title']
        body[0] = keep
    content['body'] = body
    if root != 'page' and p['content'].get('title') and not hs.clean(content.get('title')):
        content['title'] = p['content']['title']

    soup = B.BeautifulSoup(open(os.path.join(B.PREP_DIR, f'{sid}.html'), encoding='utf-8').read(),
                           'html.parser')
    src = len(hs.clean(B.MARK.sub('', ' '.join(c.get_text(' ', strip=True) for c in bp.body_of(soup)))))
    got = len(bp.payload_text([b for b in body if b.get('component') not in
                               ('library_navigator', 'quick_actions', 'strip_banner',
                                'teaching_impact', 'carousel_section', 'hero')]))
    probs = schema.problems(body)
    missing = unresolved_images(body)

    print(f"\nnow     {outline(st['content'].get('body') or [])}")
    print(f'after   {outline(body)}')
    print(f'text    old page {src:,} chars -> built {got:,}')
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
