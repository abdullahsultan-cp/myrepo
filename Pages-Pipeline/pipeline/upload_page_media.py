"""upload_page_media.py -- fetch each page image off aku.edu and put it in Storyblok.

Reads out/work/page_payloads.json, downloads every image the pages reference,
uploads it into the Migration asset tree, and writes out/work/page_asset_map.json
mapping the original SharePoint src to a real Storyblok asset object.

The rules this obeys, each of which has cost this project a day before:

* **Look up an asset folder before creating one.** Storyblok does NOT reject a
  duplicate name under one parent -- it makes a second folder. Posting first and
  searching only on failure is how the space reached 769 asset folders, 444 of
  them redundant.
* **`204 No Content` is success.** A PUT on an asset and a DELETE on a folder
  both return it; accepting only (200, 201) is how a run that moved 786 assets
  reported "0 moved, 786 failed".
* **Pool the session.** A bare requests.post() per file leaves thousands of
  sockets in TIME_WAIT until Windows runs out of ephemeral ports -- WinError
  10013. One Session, one pool.
* **Retry the connection, not just the status.** A dropped S3 connection used to
  raise straight out and end a 95-minute run.
* **Identical bytes upload once.** Keyed on sha256, so the same logo referenced
  by nine pages becomes one asset.

Run:  python upload_page_media.py            # dry run: download + report only
      python upload_page_media.py --apply    # also upload to Storyblok
"""
import argparse
import hashlib
import json
import mimetypes
import os
import re
import time
import urllib.parse

import paths
import requests

BASE = 'https://www.aku.edu'
IMG_DIR = paths.work('legacy_images')
OUT = paths.work('page_asset_map.json')
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CFG = os.path.join(REPO, 'config', 'storyblok.json')

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/124.0 Safari/537.36'}

# A page's media is filed at the SAME PATH as the page itself, so
# regions/pk/entities/mc/data-science/nyu keeps its pictures in the asset folder
# regions/pk/entities/mc/data-science.
#
# This is the rule the shared uploader already follows (`ensure_asset_folder` in
# pipeline/migrate/upload/upload.py), and why `regions/` carries 1,261 asset
# subfolders: filing each story's media beside the story is what keeps thousands
# of assets navigable instead of one flat pile. The first version of this script
# put everything under `Migration/ Medical College, Pakistan/<Section>` instead,
# copying what the Migration Team had set up by hand -- a second, parallel
# convention for the same files. Rabee, 15 Sep 2026: "the assets should be on
# same path as their story".


class SB:
    """Management API client. One pooled session for the API, one for S3."""

    def __init__(self):
        cfg = json.load(open(CFG, encoding='utf-8'))
        self.space = cfg['space_id']
        self.h = {'Authorization': cfg['management_token'],
                  'Content-Type': 'application/json'}
        self.s = requests.Session()
        self.s3 = requests.Session()

    def _call(self, method, path, **kw):
        url = f'https://mapi.storyblok.com/v1/spaces/{self.space}/{path}'
        for attempt in range(6):
            try:
                r = self.s.request(method, url, headers=self.h, timeout=60, **kw)
            except requests.exceptions.RequestException as e:
                if attempt == 5:
                    raise
                print(f'      {type(e).__name__}; retry in {3 * (attempt + 1)}s')
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(4 * (attempt + 1))
                continue
            return r
        return r

    def get(self, p):
        return self._call('GET', p)

    def post(self, p, body):
        return self._call('POST', p, data=json.dumps(body))


def asset_folders(sb):
    r = sb.get('asset_folders')
    return (r.json().get('asset_folders') or []) if r.status_code == 200 else []


def folder_path(f, by_id):
    parts, cur = [], f
    while cur:
        parts.append(cur['name'])
        cur = by_id.get(cur.get('parent_id'))
    return '/'.join(reversed(parts))


def ensure_folder(sb, path, apply_):
    """Resolve path to a folder id, creating only what is genuinely absent."""
    folders = asset_folders(sb)
    by_id = {f['id']: f for f in folders}
    existing = {folder_path(f, by_id): f['id'] for f in folders}
    parent, walked = 0, ''
    for seg in [p for p in path.split('/') if p]:
        walked = f'{walked}/{seg}' if walked else seg
        if walked in existing:
            parent = existing[walked]
            continue
        # look up by (name, parent) before creating -- see the module docstring
        match = [f['id'] for f in folders
                 if f.get('name') == seg and (f.get('parent_id') or 0) == (parent or 0)]
        if match:
            parent = min(match)
            existing[walked] = parent
            continue
        if not apply_:
            print(f'    would create asset folder: {walked}')
            return None
        r = sb.post('asset_folders',
                    {'asset_folder': {'name': seg, 'parent_id': parent or None}})
        if r.status_code not in (200, 201):
            raise SystemExit(f'cannot create asset folder {walked}: '
                             f'{r.status_code} {r.text[:200]}')
        parent = (r.json().get('asset_folder') or {}).get('id')
        print(f'    asset folder created: {walked} (id {parent})')
        folders = asset_folders(sb)
        by_id = {f['id']: f for f in folders}
        existing[walked] = parent
    return parent


def safe_name(src):
    name = urllib.parse.unquote(src.split('?')[0].split('/')[-1])
    name = re.sub(r'[^A-Za-z0-9._-]+', '-', name).strip('-')
    return name or 'image'


def cache_name(src):
    """The on-disk name. MUST be keyed on the whole path, not the basename.

    Every recovered gallery numbers its pictures from 1, so `NYU Gallery/1.jpg`
    and `BDMIS Image Gallery/1.jpg` share a basename. Caching on the basename
    alone would hand the second gallery the first one's photograph -- a wrong
    image on a published page, silently.
    """
    stem, dot, ext = safe_name(src).rpartition('.')
    digest = hashlib.sha1(src.encode()).hexdigest()[:10]
    return f'{stem or "image"}-{digest}{dot}{ext}' if dot else f'{safe_name(src)}-{digest}'


def download(src, sess):
    """Fetch one image; returns (local_path, sha256) or (None, reason)."""
    url = src if src.startswith('http') else urllib.parse.urljoin(BASE, src)
    local = os.path.join(IMG_DIR, cache_name(src))
    if os.path.exists(local) and os.path.getsize(local) > 0:
        return local, sha256_of(local)
    try:
        r = sess.get(url, headers=UA, timeout=60)
    except requests.exceptions.RequestException as e:
        return None, f'{type(e).__name__}: {e}'
    if r.status_code != 200:
        return None, f'HTTP {r.status_code}'
    if not r.content or 'image' not in r.headers.get('Content-Type', ''):
        return None, f"not an image ({r.headers.get('Content-Type', '?')})"
    os.makedirs(IMG_DIR, exist_ok=True)
    with open(local, 'wb') as f:
        f.write(r.content)
    return local, sha256_of(local)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def upload(sb, path, filename, folder_id):
    size = os.path.getsize(path)
    ctype = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
    body = {'filename': filename, 'size': str(size), 'content_type': ctype}
    if folder_id:
        body['asset_folder_id'] = folder_id
    r = sb.post('assets', body)
    if r.status_code not in (200, 201):
        return None, f'sign failed {r.status_code} {r.text[:200]}'
    sig = r.json()
    up = None
    for attempt in range(5):
        try:
            with open(path, 'rb') as fh:
                files = {**{k: (None, v) for k, v in (sig.get('fields') or {}).items()},
                         'file': (filename, fh, ctype)}
                up = sb.s3.post(sig['post_url'], files=files, timeout=300)
            break
        except requests.exceptions.RequestException as e:
            if attempt == 4:
                return None, f's3 unreachable: {e}'
            time.sleep(3 * (attempt + 1))
    # 204 is success.
    if up is None or up.status_code not in (200, 201, 204):
        return None, f"s3 failed {getattr(up, 'status_code', '?')}"
    fin = sb.get(f"assets/{sig['id']}/finish_upload")
    if fin.status_code not in (200, 204):
        return None, f'finish failed {fin.status_code}'
    meta = sb.get(f"assets/{sig['id']}")
    obj = meta.json().get('asset', meta.json()) if meta.status_code == 200 else {}
    return {'id': sig['id'],
            'filename': obj.get('filename') or sig.get('pretty_url') or '',
            'alt': '', 'name': '', 'focus': None, 'title': None, 'source': None,
            'copyright': None, 'fieldtype': 'asset', 'meta_data': {}}, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='actually upload')
    a = ap.parse_args()

    pages = json.load(open(paths.work('page_payloads.json'), encoding='utf-8'))
    os.makedirs(IMG_DIR, exist_ok=True)

    # src -> the section it belongs to (first page that references it wins)
    owner = {}
    for p in pages:
        for src in p['images']:
            owner.setdefault(src, p['folder'])

    print(f'{len(owner)} distinct images referenced by {len(pages)} pages\n')
    sess = requests.Session()
    got, failed = {}, {}
    for src in owner:
        local, info = download(src, sess)
        if local:
            got[src] = (local, info)
        else:
            failed[src] = info
        time.sleep(0.1)
    print(f'downloaded {len(got)} | failed {len(failed)}')
    for s, why in list(failed.items())[:12]:
        print(f'    FAIL {why:<28} {s[:70]}')

    if not a.apply:
        by_sec = {}
        for src, sec in owner.items():
            if src in got:
                by_sec[sec] = by_sec.get(sec, 0) + 1
        print('\nwould upload, by asset folder:')
        for sec, n in sorted(by_sec.items()):
            print(f'    {n:>3}  {sec}')
        print('\ndry run -- rerun with --apply')
        return

    sb = SB()
    # Resume: anything already in the map is already in Storyblok. Re-running
    # must not upload it a second time -- a duplicate asset is invisible in the
    # editor and permanent in the space.
    amap = json.load(open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {}
    fid_cache, by_hash = {}, {}
    if amap:
        print(f'resuming: {len(amap)} images already uploaded, skipping those')
    for src, (local, digest) in got.items():
        if src in amap:
            by_hash.setdefault(digest, amap[src])
            continue
        fpath = owner[src]
        if fpath not in fid_cache:
            fid_cache[fpath] = ensure_folder(sb, fpath, True)
        if digest in by_hash:
            amap[src] = by_hash[digest]
            continue
        obj, err = upload(sb, local, safe_name(src), fid_cache[fpath])
        if err:
            print(f'    FAILED {safe_name(src)[:44]}: {err}')
            continue
        by_hash[digest] = obj
        amap[src] = obj
        print(f"    ok {obj['id']}  {fpath}/{safe_name(src)[:46]}")
        time.sleep(0.3)

    json.dump(amap, open(OUT, 'w', encoding='utf-8', newline='\n'),
              indent=1, ensure_ascii=False)
    print(f'\n{len(amap)} of {len(owner)} images mapped -> {OUT}')


if __name__ == '__main__':
    main()
