"""score_against_reference.py -- how close are built payloads to the hand-built pages?

For every payload whose destination already holds a story people built by hand,
compares the two. Reads only.

  root     same content type (page / speech_article / event_article)
  seq      similarity of the top-level blok sequence, 0-1 (difflib ratio)
  comps    Jaccard overlap of the component SETS used anywhere in the tree
  text     share of the hand page's words the payload also carries

Run:  python score_against_reference.py [--payloads sheet_payloads.json] [--worst 25]
"""
import argparse
import collections
import difflib
import json
import re

import paths


def comps(x, out=None):
    out = set() if out is None else out
    if isinstance(x, dict):
        if 'component' in x:
            out.add(x['component'])
        for v in x.values():
            comps(v, out)
    elif isinstance(x, list):
        for v in x:
            comps(v, out)
    return out


def words(x):
    out = []

    def walk(y):
        if isinstance(y, dict):
            for k, v in y.items():
                if k in ('_uid', 'component', 'filename', 'url', 'cached_url', 'href', 'src'):
                    continue
                walk(v)
        elif isinstance(y, list):
            for v in y:
                walk(v)
        elif isinstance(y, str):
            out.extend(re.findall(r'[a-z0-9]{3,}', y.lower()))
    walk(x)
    return collections.Counter(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--payloads', default='sheet_payloads.json')
    ap.add_argument('--reference', default='reference_stories.json')
    ap.add_argument('--worst', type=int, default=20)
    a = ap.parse_args()

    ref = json.load(open(paths.work(a.reference), encoding='utf-8'))
    if isinstance(ref, dict):
        ref = [v['story'] for v in ref.values() if v.get('story')]
    by_slug = {s['full_slug']: s for s in ref}
    pays = json.load(open(paths.work(a.payloads), encoding='utf-8'))

    rows = []
    for p in pays:
        hand = by_slug.get(f"{p['folder']}/{p['slug']}")
        if not hand:
            continue
        hc = hand.get('content') or {}
        hs = [b.get('component') for b in hc.get('body') or []]
        ps = [b.get('component') for b in p['content'].get('body') or []]
        hcs, pcs = comps(hc.get('body')), comps(p['content'].get('body'))
        hw, pw = words(hc), words(p['content'])
        rows.append({
            'serial': p['serial'], 'slug': f"{p['folder']}/{p['slug']}",
            'root': hc.get('component') == p['content'].get('component'),
            'seq': difflib.SequenceMatcher(None, hs, ps).ratio(),
            'comps': len(hcs & pcs) / max(1, len(hcs | pcs)),
            'text': sum((hw & pw).values()) / max(1, sum(hw.values())),
            'hand': hs, 'built': ps})
    n = len(rows)
    if not n:
        raise SystemExit('no payload lands on a hand-built story')

    def avg(k):
        return sum(r[k] for r in rows) / n
    print(f'{n} pages compared with their hand-built story')
    print(f"  root type matches      {sum(r['root'] for r in rows)}/{n}")
    print(f"  top-level sequence     {avg('seq'):.2f}   (identical: "
          f"{sum(r['hand'] == r['built'] for r in rows)})")
    print(f"  component set overlap  {avg('comps'):.2f}")
    print(f"  hand words carried     {avg('text'):.2f}")

    miss, extra = collections.Counter(), collections.Counter()
    for r in rows:
        h, b = collections.Counter(r['hand']), collections.Counter(r['built'])
        miss.update(h - b)
        extra.update(b - h)
    print('\n  top-level bloks people used that the build lacks:',
          ', '.join(f'{k} {v}' for k, v in miss.most_common(12)))
    print('  top-level bloks the build adds that people did not:',
          ', '.join(f'{k} {v}' for k, v in extra.most_common(12)))
    print(f'\n  worst {a.worst} by sequence:')
    for r in sorted(rows, key=lambda r: r['seq'])[:a.worst]:
        print(f"   {r['serial']:>5} {r['seq']:.2f} {r['slug'][-40:]:<40}\n"
              f"         hand  {' '.join(r['hand'])[:150]}\n"
              f"         built {' '.join(r['built'])[:150]}")


if __name__ == '__main__':
    main()
