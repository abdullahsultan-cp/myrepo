"""documents.py -- move a page's PDF links off aku.edu and onto Storyblok assets.

Abdullah, 6 Nov 2026: "if it is pdf then we need to upload assets in
appropriate location and then link them as storyblok asset rather than
redirecting to actual links". aku.edu is being switched off; a link to a PDF
on it is a link that will stop working.

For every link on the page whose target is a PDF on aku.edu:
  1. download it (retrying -- aku.edu drops roughly one connection in five)
     and check the bytes really are a PDF, not an HTML error page
  2. reuse it if it is already in Storyblok -- `document_asset_map.json`
     (source URL -> asset, and sha256 -> asset) or a file of the same name in
     the target folder. Storyblok does NOT reject a duplicate upload; it makes
     a second asset (root CLAUDE.md §6)
  3. otherwise upload it into the asset folder named after the story's own
     folder (`regions/gl/qtl/resources`), the rule every other asset follows
  4. point the link at the asset: `linktype: "asset"` and the a.storyblok.com
     address -- the shape the editor's own asset picker writes

Links in a field (`link`, `cta_link`, ...) and links inside rich text are both
rewritten. Anything that is not a PDF on aku.edu is left exactly as it is.

    python documents.py <editor-url-or-story-id>            # dry run: list the PDFs
    python documents.py <editor-url-or-story-id> --apply    # upload + relink + backup

fix_page.py calls relink() too, so a rebuilt page gets the same treatment.
"""
import argparse
import copy
import gzip
import hashlib
import json
import os
import re
import time
import urllib.parse

import paths
import requests
import upload_page_media as um

MAP = paths.work('document_asset_map.json')
DOC_DIR = paths.work('legacy_documents')
AKU = re.compile(r'^(https?://(www\.)?aku\.edu)?/', re.I)
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/124.0 Safari/537.36'}


def is_aku_pdf(url):
    u = (url or '').strip()
    if not u or 'a.storyblok.com' in u:
        return False
    path = urllib.parse.urlsplit(u).path.lower()
    return path.endswith('.pdf') and bool(AKU.match(u))


def absolute(url):
    return urllib.parse.urljoin('https://www.aku.edu/', url.strip())


def find_links(x, out=None):
    """Every PDF link on the page, in order, de-duplicated."""
    out = [] if out is None else out
    if isinstance(x, dict):
        if x.get('fieldtype') == 'multilink':
            u = x.get('url') or x.get('cached_url') or ''
            if is_aku_pdf(u) and absolute(u) not in out:
                out.append(absolute(u))
        if x.get('type') == 'link':
            u = (x.get('attrs') or {}).get('href') or ''
            if is_aku_pdf(u) and absolute(u) not in out:
                out.append(absolute(u))
        for v in x.values():
            find_links(v, out)
    elif isinstance(x, list):
        for v in x:
            find_links(v, out)
    return out


def download(url, sess):
    """(local path, sha256) or (None, reason)."""
    os.makedirs(DOC_DIR, exist_ok=True)
    local = os.path.join(DOC_DIR, um.cache_name(url))
    if os.path.exists(local) and os.path.getsize(local) > 0:
        return local, um.sha256_of(local)
    last = ''
    for i in range(6):
        try:
            r = sess.get(url, headers=UA, timeout=90)
            if r.status_code == 200 and r.content[:5] == b'%PDF-':
                with open(local, 'wb') as fh:
                    fh.write(r.content)
                return local, um.sha256_of(local)
            last = f'HTTP {r.status_code}' if r.status_code != 200 else \
                f"not a PDF ({r.headers.get('Content-Type', '?')})"
            if r.status_code < 500 and r.status_code != 200:
                break
            if r.status_code == 200:
                break
        except requests.RequestException as e:
            last = type(e).__name__
        time.sleep(min(30, 4 * (i + 1)))
    return None, last


def folder_assets(sb, folder_id):
    out, page = {}, 1
    while True:
        r = sb.get(f'assets?in_folder={folder_id}&per_page=100&page={page}')
        batch = r.json().get('assets') or [] if r.status_code == 200 else []
        for a in batch:
            out[a['filename'].rsplit('/', 1)[-1].lower()] = a
        if len(batch) < 100:
            return out
        page += 1


def asset_link(filename):
    return {'id': '', 'url': filename, 'linktype': 'asset', 'fieldtype': 'multilink',
            'cached_url': filename}


def relink(content, folder, apply_, sb=None, log=print):
    """Upload the page's aku.edu PDFs and point its links at them.

    Returns (new_content, {source_url: asset_filename}, {source_url: problem}).
    Without apply_, nothing is uploaded or written; links already known in the
    map are still rewritten so the dry run shows the result.
    """
    sb = sb or um.SB()
    urls = find_links(content)
    amap = json.load(open(MAP, encoding='utf-8')) if os.path.exists(MAP) else {}
    by_hash = {v['sha256']: v for v in amap.values() if v.get('sha256')}
    resolved, problems = {}, {}
    if not urls:
        return content, resolved, problems
    sess = requests.Session()
    fid = um.ensure_folder(sb, folder, apply_)
    existing = folder_assets(sb, fid) if fid else {}
    for u in urls:
        if u in amap:
            resolved[u] = amap[u]['filename']
            log(f'    known      {u.rsplit("/", 1)[-1]}')
            continue
        local, digest = download(u, sess)
        if not local:
            problems[u] = digest
            log(f'    NOT FOUND  {u}  ({digest})')
            continue
        name = um.safe_name(u)
        hit = by_hash.get(digest) or existing.get(name.lower())
        if hit:
            rec = {'id': hit['id'], 'filename': hit['filename'], 'sha256': digest}
            log(f'    reuse      {name}  (already in Storyblok)')
        elif not apply_:
            log(f'    upload     {name}  -> {folder}  ({os.path.getsize(local) // 1024} KB)')
            continue
        else:
            obj, err = um.upload(sb, local, name, fid)
            if not obj:
                problems[u] = err
                log(f'    FAILED     {name}: {err}')
                continue
            rec = {'id': obj['id'], 'filename': obj['filename'], 'sha256': digest}
            by_hash[digest] = rec
            log(f'    uploaded   {name}  -> {obj["filename"]}')
        amap[u] = rec
        resolved[u] = rec['filename']
        if apply_:   # after every one, so a crash part-way loses nothing
            json.dump(amap, open(MAP, 'w', encoding='utf-8', newline='\n'), indent=1,
                      ensure_ascii=False)

    def walk(x):
        if isinstance(x, dict):
            if x.get('fieldtype') == 'multilink':
                u = absolute(x.get('url') or x.get('cached_url') or '')
                if u in resolved:
                    return asset_link(resolved[u])
            if x.get('type') == 'link':
                a = dict(x.get('attrs') or {})
                u = absolute(a.get('href') or '')
                if u in resolved:
                    a.update({'href': resolved[u], 'linktype': 'asset', 'target': '_blank'})
                    return {**x, 'attrs': a}
            return {k: walk(v) for k, v in x.items()}
        if isinstance(x, list):
            return [walk(v) for v in x]
        return x
    return walk(copy.deepcopy(content)), resolved, problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('story')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--publish', action='store_true')
    a = ap.parse_args()
    sid = re.search(r'(\d{9,})\D*$', a.story).group(1)
    sb = um.SB()
    st = sb.get(f'stories/{sid}').json()['story']
    folder = st['full_slug'].rsplit('/', 1)[0]
    print(f"story  {st['full_slug']}  -> asset folder {folder}")
    new, resolved, problems = relink(st['content'], folder, a.apply, sb)
    print(f'\n{len(resolved)} PDF link(s) on Storyblok assets, {len(problems)} problem(s)')
    if not a.apply:
        print('dry run -- add --apply to upload and relink')
        return
    if not resolved:
        return
    cur = sb.get(f'stories/{sid}').json()['story']
    if cur['updated_at'] != st['updated_at']:
        raise SystemExit('story changed while uploading; run again (uploads are kept)')
    r = sb._call('PUT', f'stories/{sid}', data=json.dumps(
        {'story': {'name': cur['name'], 'slug': cur['slug'], 'parent_id': cur['parent_id'],
                   'content': new}, 'publish': 1 if a.publish else 0}))
    if r.status_code not in (200, 201, 204):
        raise SystemExit(f'PUT failed {r.status_code}: {r.text[:300]}')
    back = sb.get(f'stories/{sid}').json()['story']
    bk = os.path.join(os.path.dirname(paths.OUT), 'backup', 'storyblok', 'fixes')
    os.makedirs(bk, exist_ok=True)
    ts = time.strftime('%Y%m%d-%H%M%S')
    for tag, obj in (('BEFORE', st), ('AFTER', back)):
        with gzip.open(os.path.join(bk, f'pdf_{sid}_{tag}_{ts}.json.gz'), 'wt', encoding='utf-8') as fh:
            json.dump(obj, fh, ensure_ascii=False)
    left = find_links(back['content'])
    print(f'written; aku.edu PDF links left on the page: {len(left)}  (backups -> {bk})')


if __name__ == '__main__':
    main()
