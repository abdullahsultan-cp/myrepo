"""fetch_reference.py -- read the hand-built pages the builder learns from.

Two reads, both GET-only against the Management API:

  out/work/reference_stories.json  every story under each folder a sheet row
                                   targets, with full content. build_from_sheet
                                   copies section chrome (the "Explore
                                   Convocations" strip, Stay Connected banner,
                                   side navigator) from these siblings, and
                                   learns the quick-link icons from them.
  out/work/components_live.json    the live component schemas. The committed
                                   storyblok_space/component_fields.csv was 61
                                   components behind on 5 Nov 2026 and still
                                   listed `info_accordion_item.body`, a field
                                   the space no longer has.

The components endpoint ignores `?page=` and returns everything every time, so
it is fetched once (MC-PK-RULES §2).

Run:  python fetch_reference.py --csv <sheet.csv>
"""
import argparse
import json
import time

import paths
import sheet
from create_pages import SB


def get(sb, path, params=None):
    q = '&'.join(f'{k}={v}' for k, v in (params or {}).items())
    r = sb.call('GET', f'{path}?{q}' if q else path)
    r.raise_for_status()
    return r.json()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', required=True)
    a = ap.parse_args()

    sb = SB()
    comps = get(sb, 'components')['components']
    json.dump(comps, open(paths.work('components_live.json'), 'w', encoding='utf-8',
                          newline='\n'), indent=1, ensure_ascii=False)
    print(f'{len(comps)} live components -> components_live.json')

    folders = sorted({sheet.destination(r)[0] for r in sheet.read(a.csv)})
    stories = {}
    for f in folders:
        page = 1
        while True:
            d = get(sb, 'stories', {'starts_with': f + '/', 'per_page': 100,
                                    'page': page, 'story_only': 'true'})
            batch = d.get('stories') or []
            for s in batch:
                if s['id'] in stories or s.get('is_folder'):
                    continue
                full = get(sb, f"stories/{s['id']}")['story']
                stories[s['id']] = full
                time.sleep(0.1)
            if len(batch) < 100:
                break
            page += 1
        print(f'  {f}: {sum(1 for s in stories.values() if s["full_slug"].startswith(f + "/"))}')
    out = sorted(stories.values(), key=lambda s: s['full_slug'])
    json.dump(out, open(paths.work('reference_stories.json'), 'w', encoding='utf-8',
                        newline='\n'), ensure_ascii=False)
    print(f'{len(out)} reference stories -> reference_stories.json')


if __name__ == '__main__':
    main()
