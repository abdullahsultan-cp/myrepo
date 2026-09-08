"""build_folder_json.py -- the folder tree as JSON, small enough to read.

`out/aku-folder-map.csv` is the deliverable a human reads: 628 rows and 26
columns, every value a string. That is right for a spreadsheet and too much for
a seed, so this writes the same 628 folders as a nested tree with six fields
per node and nothing else:

    title            what the folder is called
    type             region | entity | department | folder
    parent_name      the title of the folder above it
    parent_sb_id     the Storyblok id of that folder, or null if it is not made yet
    slug             the segment in the address
    shortname        the segment the space actually uses -- see below
    path             kept because every other sheet keys on it
    sb_id            this folder's own Storyblok id, or null
    children[]

Three things are worth knowing before seeding from it.

**`type` is four values, not twelve.** The CSV distinguishes `centre`,
`division`, `office`, `section`, `container` and `root` as well; each of those
is one of the four here, by the table in TYPES. The finer word is still in the
CSV, so nothing is lost -- but a tree with twelve kinds is not a tree anyone can
hold in their head, and a centre is a unit under an entity either way.

**`shortname` is not invented.** A region takes its own `region_code`, an entity
takes the short name the news migration already uses (24 of 28 match by slug),
and everything else takes its slug, which for a department is already the short
SharePoint web name -- `anaes`, `chs`. This matters because the dev renamed the
live tree to short codes: `regions/pakistan/entities/medical-college` is
`regions/pk/entities/mc` in the space. Nothing here guesses a code for a folder
that has none.

**`sb_id` is null for 590 of the 628.** These folders do not exist yet -- that
is the work. The 38 that do are matched by translating the path into short
codes and looking it up in `storyblok_space/folder_tree.json`, so the id is read
from the space rather than assumed. Refresh that file
(`migrate/review/dump_sb_tree.py`) before trusting a null.

Inputs   out/aku-folder-map.csv, ../storyblok_space/folder_tree.json,
         ../News-Pipeline/data/taxonomy/seed/regions_entities_departments.json
         (and out/aku-page-{map,assignments}.csv with --with-pages)
Outputs  out/AKU-Folder-Structure.json
"""
import argparse
import collections
import csv
import datetime
import json
import os
import re

import paths

FOLDER_CSV = 'aku-folder-map.csv'
PAGE_CSV = 'aku-page-map.csv'
ASSIGNMENT_CSV = 'aku-page-assignments.csv'
OUT_JSON = 'AKU-Folder-Structure.json'

# The CSV's twelve kinds, as the four a reader needs. A centre, a division and
# an office are all units inside an entity, which is what `department` means
# here; a section, a container and the staging root are all just folders.
TYPES = {
    'region': 'region',
    'entity': 'entity',
    'region-folder': 'entity',      # a unit hanging straight off a region
    'department': 'department',
    'centre': 'department',
    'division': 'department',
    'office': 'department',
    'folder': 'folder',
    'section': 'folder',
    'container': 'folder',
    'publication': 'folder',        # LABRAD and the digital magazine are content
    'root': 'folder',
}

# The one address where this file cannot say whether a folder already exists.
# The pages plan places the global region at `regions/global`; the news and blogs
# migrations put the same idea at the root, as `global`, and the front end strips
# the segment either way. They are not matched here, because saying `sb_id:
# 205...` for `regions/global` would assert the dev's two trees are one folder,
# which nobody has decided. So it reports null, and this note says why.
GLOBAL_NOTE = ('regions/global reports sb_id null: the space keeps the global '
               'folder at the root instead, and which address wins is AKU\'s to '
               'settle')


def rows(name):
    with open(paths.out(name), encoding='utf-8-sig') as fh:
        return list(csv.DictReader(fh))


def short_names():
    """`{slug: short}` for the entities, from the news taxonomy seed.

    Borrowed rather than restated: news already agreed a short name with AKU for
    every faculty and institute, and the live folder tree is named from it. A
    second list here would be a second opinion about the same thing.
    """
    seed = json.load(open(paths.taxonomy_seed(), encoding='utf-8'))
    return {e['slug']: e['short_name'].lower()
            for region in seed for e in region['entities']}


def live_folders():
    """`{full_slug: id}` for every folder in the space, read from the snapshot."""
    snapshot = os.path.join(paths.ROOT, 'storyblok_space', 'folder_tree.json')
    with open(snapshot, encoding='utf-8') as fh:
        return {f['full_slug']: f['id'] for f in json.load(fh)['folders']}


def shortname(row, entity_shorts):
    """The segment the space uses for this folder.

    Only two levels have a code of their own; everything else is already short.
    """
    slug = row['new_path'].rsplit('/', 1)[-1]
    if row['kind'] == 'region' and row['region_code'].isalpha():
        return row['region_code'].lower()
    if row['kind'] == 'entity':
        return entity_shorts.get(slug, slug)
    return slug


def live_path(path, shorts):
    """This folder's address in the space -- the same path, in short codes.

    Every segment is translated by looking up the prefix that ends at it, since
    a short code belongs to a folder and not to a word: `medical-college` is
    `mc` under `entities` and could be something else elsewhere.
    """
    parts = path.split('/')
    return '/'.join(shorts.get('/'.join(parts[:i + 1]), part)
                    for i, part in enumerate(parts))


def build(src):
    entity_shorts = short_names()
    live = live_folders()
    shorts = {r['new_path']: shortname(r, entity_shorts) for r in src}
    titles = {r['new_path']: r['title'] for r in src}

    nodes = {}
    for r in src:
        path = r['new_path']
        nodes[path] = {
            'title': r['title'],
            'type': TYPES[r['kind']],
            'parent_name': titles.get(r['parent_path']),
            'parent_sb_id': None,          # filled below, once every id is known
            'slug': path.rsplit('/', 1)[-1],
            'shortname': shorts[path],
            'path': path,
            'sb_id': live.get(live_path(path, shorts)),
            'children': [],
        }

    roots = []
    for r in src:
        node = nodes[r['new_path']]
        parent = nodes.get(r['parent_path'])
        if parent is None:
            roots.append(node)
        else:
            node['parent_sb_id'] = parent['sb_id']
            parent['children'].append(node)
    return roots, nodes


def page_nodes(nodes):
    """The 4,591 pages, hung under the folder each one lands in.

    Only what a page needs to be seeded and then checked: its two addresses, and
    the four fields a folder node carries so the shapes match. The title comes
    from the work sheet rather than the slug, because 465 of these pages are a
    folder's front door and a tree of nodes called "home" is unreadable.
    """
    # The work sheet has to make each name unique across 4,591 rows, so 387 of
    # them end in the path they came from -- "Home (forms/home)". In a tree the
    # position is the nesting, so the parenthetical is dropped. Only one holding
    # a `/` is dropped, which is what makes it a path and not a real title.
    tail = re.compile(r' \([^()]*/[^()]*\)$')
    titles = {r['Storyblok Path']: tail.sub('', r['Page Name'])
              for r in rows(ASSIGNMENT_CSV) if r['Page Name']}
    placed = 0
    for r in rows(PAGE_CSV):
        parent = nodes.get(r['folder'])
        if parent is None:
            continue
        slug = r['new_path'].rsplit('/', 1)[-1]
        parent['children'].append({
            'title': titles.get(r['new_path'], slug),
            'type': 'page',
            'parent_name': parent['title'],
            'parent_sb_id': parent['sb_id'],
            'slug': slug,
            'path': r['new_path'],
            'source_url': r['current_url'],
            'new_url': r['new_url'],
            'do_not_migrate': bool(r['do_not_migrate'].strip()),
        })
        placed += 1
    return placed


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--with-pages', action='store_true',
                    help='hang the 4,591 pages under their folders as leaves')
    args = ap.parse_args()

    # Sorted by the path split on '/', so siblings are alphabetical and a parent
    # is always seen before its children.
    src = sorted(rows(FOLDER_CSV), key=lambda r: r['new_path'].split('/'))
    assert len({r['new_path'] for r in src}) == len(src), \
        'duplicate path in %s' % FOLDER_CSV
    roots, nodes = build(src)

    pages = page_nodes(nodes) if args.with_pages else 0
    known = sum(1 for n in nodes.values() if n['sb_id'])

    doc = {
        'meta': {
            'generated': datetime.date.today().isoformat(),
            'source': 'Pages-Pipeline/out/%s' % FOLDER_CSV,
            'space_id': '289824742951963',
            'folders': len(nodes),
            'pages': pages if args.with_pages else 4591,
            'types': dict(sorted(collections.Counter(
                n['type'] for n in nodes.values()).items(),
                key=lambda kv: (-kv[1], kv[0]))),
            'sb_id': '%d of %d folders exist in the space already and carry their '
                     'real id; the rest are null until created' % (known, len(nodes)),
            'shortname': 'region_code for a region, the news short name for an '
                         'entity, the slug for everything else -- the segment '
                         'the live space uses',
            'landing_page': 'a folder\'s own front door is the story `home` '
                            'inside it -- see out/FOR-THE-FRONTEND-DEV.md',
            'global': GLOBAL_NOTE,
        },
        'tree': roots,
    }

    with open(paths.out(OUT_JSON), 'w', encoding='utf-8', newline='\n') as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
        fh.write('\n')

    print('out/%s' % OUT_JSON)
    print('  folders    %5d   roots: %s' % (
        len(nodes), ', '.join(n['path'] for n in roots)))
    print('  with an sb_id already %d' % known)
    if args.with_pages:
        print('  pages      %5d' % pages)
    for kind, n in doc['meta']['types'].items():
        print('    %-11s %5d' % (kind, n))


if __name__ == '__main__':
    main()
