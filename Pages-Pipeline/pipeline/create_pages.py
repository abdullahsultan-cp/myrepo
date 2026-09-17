"""create_pages.py -- create the `page` stories from the built payloads.

Reads out/work/page_payloads.json and out/work/page_asset_map.json, wires each
image reference to its uploaded Storyblok asset, and creates one story per page.

The rules this obeys:

* **Never creates a folder.** Every destination is resolved against the live
  space and a missing one is a hard stop with the path named, not something to
  invent. `regions/` belongs to the backend and the front-end developer.
* **Never creates a story that already exists.** If the slug is already present
  in the destination folder the story is UPDATED in place, because a new id
  breaks every review link already shared and loses manual edits.
* **Creates as draft.** Nothing here has been reviewed against the live page yet.
* **`spacing` is never written** -- only `spacing_preset`. See build_pages.py.

Run:  python create_pages.py            # dry run
      python create_pages.py --apply    # writes
      python create_pages.py --apply --limit 3
"""
import argparse
import copy
import json
import os
import time

import paths
import requests

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CFG = os.path.join(REPO, 'config', 'storyblok.json')


class SB:
    def __init__(self):
        cfg = json.load(open(CFG, encoding='utf-8'))
        self.space = cfg['space_id']
        self.h = {'Authorization': cfg['management_token'],
                  'Content-Type': 'application/json'}
        self.s = requests.Session()

    def call(self, method, path, body=None):
        url = f'https://mapi.storyblok.com/v1/spaces/{self.space}/{path}'
        for attempt in range(6):
            try:
                r = self.s.request(method, url, headers=self.h, timeout=60,
                                   data=json.dumps(body) if body else None)
            except requests.exceptions.RequestException:
                if attempt == 5:
                    raise
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(4 * (attempt + 1))
                continue
            return r
        return r


def wire_assets(node, amap, missing):
    """Replace every _src_original stub with the real uploaded asset."""
    if isinstance(node, dict):
        src = node.get('_src_original')
        if src is not None:
            got = amap.get(src)
            if node.get('fieldtype') == 'asset':
                out = dict(node)
                out.pop('_src_original', None)
                if got:
                    out.update({k: got.get(k) for k in ('id', 'filename')})
                elif src:
                    missing.add(src)
                return out
            # a rich-text image node
            out = dict(node)
            out.pop('_src_original', None)
            if got:
                out['id'] = got['id']
                out['src'] = got['filename']
            elif src:
                missing.add(src)
            return out
        return {k: wire_assets(v, amap, missing) for k, v in node.items()}
    if isinstance(node, list):
        return [wire_assets(v, amap, missing) for v in node]
    return node


def folder_index(sb):
    out, page = {}, 1
    while True:
        r = sb.call('GET', f'stories/?folder_only=true&per_page=100&page={page}')
        d = r.json().get('stories') or []
        if not d:
            break
        for f in d:
            out[f['full_slug'].rstrip('/')] = f['id']
        page += 1
        time.sleep(0.2)
    return out


def existing_in(sb, folder_id):
    r = sb.call('GET', f'stories/?with_parent={folder_id}&per_page=100')
    return {s['slug']: s['id'] for s in (r.json().get('stories') or [])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--limit', type=int)
    ap.add_argument('--only', help='comma-separated serials')
    ap.add_argument('--skip-dupes', action='store_true',
                    help='skip pages Abdullah already built in the old tree')
    ap.add_argument('--protect', default='',
                    help='comma-separated full_slugs never to overwrite -- pages '
                         'someone has corrected by hand since the payload was built')
    a = ap.parse_args()

    pages = json.load(open(paths.work('page_payloads.json'), encoding='utf-8'))
    amap_path = paths.work('page_asset_map.json')
    amap = json.load(open(amap_path, encoding='utf-8')) if os.path.exists(amap_path) else {}
    if a.skip_dupes:
        pages = [p for p in pages if not p.get('abdullah_dupe')]
    if a.only:
        want = set(a.only.split(','))
        pages = [p for p in pages if p['serial'] in want]
    if a.limit:
        pages = pages[:a.limit]

    sb = SB()
    folders = folder_index(sb)
    missing_folder = sorted({p['folder'] for p in pages if p['folder'] not in folders})
    if missing_folder:
        raise SystemExit('destination folder does not exist -- this script never '
                         'creates one:\n  ' + '\n  '.join(missing_folder))

    protect = {s.strip() for s in a.protect.split(',') if s.strip()}
    seen = {}
    print('APPLY - writing\n' if a.apply else 'DRY RUN - no writes\n')
    created = updated = skipped = 0
    for p in pages:
        if f"{p['folder']}/{p['slug']}" in protect:
            print(f"  PROTECTED - left alone: {p['folder']}/{p['slug']}")
            skipped += 1
            continue
        fid = folders[p['folder']]
        if fid not in seen:
            seen[fid] = existing_in(sb, fid)
        missing = set()
        bloks = wire_assets(copy.deepcopy(p['bloks']), amap, missing)
        content = {'component': 'page', 'body': bloks}
        exists = seen[fid].get(p['slug'])
        note = f"  [{len(missing)} image(s) NOT uploaded]" if missing else ''
        action = 'UPDATE' if exists else 'create'
        print(f"  {action:<6} {p['folder']}/{p['slug']}")
        print(f"         title={p['title'][:58]!r} bloks={len(bloks)}{note}")
        if not a.apply:
            continue
        body = {'story': {'name': p['title'], 'slug': p['slug'],
                          'parent_id': fid, 'content': content},
                'publish': 0}
        if exists:
            r = sb.call('PUT', f'stories/{exists}', body)
            updated += 1
        else:
            r = sb.call('POST', 'stories', body)
            created += 1
        if r.status_code not in (200, 201):
            print(f'         FAILED {r.status_code} {r.text[:200]}')
            continue
        sid = (r.json().get('story') or {}).get('id')
        seen[fid][p['slug']] = sid
        print(f'         ok id={sid}')
        time.sleep(0.4)

    if a.apply:
        print(f'\ncreated {created}, updated {updated}')
    else:
        print('\ndry run -- rerun with --apply')


if __name__ == '__main__':
    main()
