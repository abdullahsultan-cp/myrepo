"""build_hierarchy_map.py -- the old tree and the new one, joined row by row.

Two trees describe the same university.

  OLD  what exists today: the backend's `regions` / `region_entities` /
       `entity_departments` tables, which agree exactly with the live Storyblok
       space -- 7 regions, 60 entities, 89 departments, every id resolving --
       plus the 470 `news`/`blogs`/`events` leaves the backend seeds under each
       of those and the 6,399 stories inside them.

  NEW  what the pages migration needs: `out/aku-folder-map.csv`, 628 folders
       carrying 4,591 SharePoint pages -- the same regions and entities, but
       with sections (`about`, `academics`, `research/activities`) hanging off
       them and real SharePoint departments beside the news-derived ones.

This joins the two and gives every node ONE row saying where it goes, so the
answer to "what happens to this folder" is a line you can read rather than a
diff of two trees. Nothing is dropped: a node with no counterpart still gets a
row, with the reason in `remark`.

The decisions it encodes, all AKU's, taken 8 Sep 2026:

  * **Short codes win.** `regions/pk/entities/mc`, as the space is named now and
    as 6,399 stories are already filed. The pages plan's long slugs
    (`regions/pakistan/entities/medical-college`) are translated on the way in;
    the front end expands short -> long for the public URL.
  * **The `entities/` level stays**, and `departments/` under it.
  * **Region, entity and department folders are created by the backend**, which
    seeds `news`, `blogs` and `events` inside each one. Sections do not get
    those three -- `about` has no news of its own.
  * **No empty folders.** A pages folder holding no page anywhere beneath it is
    `skip`, not `create`: 92 of them, plus the 24 `staging/*` test folders,
    which are `ignore`.
  * **A department is renamed only where the new tree actually has it.** `fm`
    and `fam-med` are one unit under two spellings, but renaming all three `fm`
    folders would move 6 stories to satisfy a plan that only mentions the one
    under `pk/mc`. So the rename is scoped to the entity the new tree names, and
    every other occurrence keeps its name and says so in `remark`.

Actions, and what each means to whoever applies this:

  keep    exists, stays where it is                      nothing to do
  adopt   exists in Storyblok, the DB does not know it    write the id down
  create  the new tree needs it, it is not there yet      create it
  rename  same folder, new slug -- stories move with it   rename, then re-check links
  skip    in the new tree, but empty                      do not create
  ignore  exists, belongs to nobody's plan                leave alone, decide later

Inputs   data/backend/{regions,region_entities,entity_departments}.json
         ../storyblok_space/folder_tree.json          (refresh it first)
         out/aku-folder-map.csv, out/aku-page-map.csv
         ../News-Pipeline/backup/storyblok/news_*.json.gz
         ../{Events,Blogs}-Pipeline/data/taxonomy/routing.csv
Outputs  out/AKU-Hierarchy-Map.json    nested, from -> to
         out/aku-hierarchy-map.csv     one row per node, for a spreadsheet
"""
import collections
import csv
import glob
import gzip
import json
import os

import paths

SPACE_ID = '289824742951963'

# The five department pairs that are one unit under two spellings -- news on the
# left (from `Tags`, so "Psychiatry & Mental Health"), SharePoint on the right
# (a real department web, so "Department of Psychiatry"). Applied only where the
# new tree names the right-hand side under the same entity; see the docstring.
DEPT_ALIAS = {
    'fm': 'fam-med',
    'onc': 'onco',
    'psych': 'psychiatry',
    'obgyn': 'obs-gyn',
    'im': 'med',
}

# What the backend creates inside every region, entity and department.
LEAVES = ('news', 'blogs', 'events')

# Roots that are nobody's plan: the dev's own, and the test trees.
KNOWN_STRAY_ROOTS = {
    'blogs': 'the dev\'s own blogs root, predates the migration',
    'news': 'the dev\'s own news root, predates the migration',
    'development': 'the dev\'s component sandbox',
    'events-detail': 'the events detail template',
    'testing': 'component testing',
    'pakistan': 'the Migration Team\'s hand-built pages tree -- 8 pages live '
                'here at addresses the plan does not use',
    'region': 'stray singular `region` root holding region/ea/mbbs',
}


# ---------------------------------------------------------------- the inputs

def backend(name):
    """One of the three DB dumps. The export wraps rows in a `select ...` key."""
    with open(os.path.join(paths.DATA, 'backend', name), encoding='utf-8') as fh:
        return list(json.load(fh).values())[0]


def out_rows(name):
    with open(paths.out(name), encoding='utf-8-sig') as fh:
        return list(csv.DictReader(fh))


def live_tree():
    """`{full_slug: id}` and `{id: full_slug}` from the space snapshot."""
    snap = os.path.join(paths.ROOT, 'storyblok_space', 'folder_tree.json')
    with open(snap, encoding='utf-8') as fh:
        folders = json.load(fh)['folders']
    return ({f['full_slug']: f['id'] for f in folders},
            {f['id']: f['full_slug'] for f in folders})


def story_counts(by_id):
    """Stories per live folder path, for all three content types.

    News comes from the read-back backup, so it is where the API says the
    stories are rather than where the payload meant to put them -- and it
    survives the `global` -> `regions/gl` move, because it resolves parent ids
    against the current snapshot. Events and blogs come from their routing
    CSVs, which were written before that move, so their `global/...` paths are
    translated here.
    """
    count = collections.Counter()
    news = sorted(glob.glob(os.path.join(
        paths.ROOT, 'News-Pipeline', 'backup', 'storyblok', 'news_*.json.gz')))
    if news:
        with gzip.open(news[-1], 'rt', encoding='utf-8') as fh:
            for story in json.load(fh)['stories'].values():
                count[by_id.get(story['parent_id'], '?')] += 1

    def moved(path):
        return 'regions/gl/' + path[len('global/'):] \
            if path.startswith('global/') else path

    for type_dir, column in (('Events-Pipeline', 'folder_path'),
                             ('Blogs-Pipeline', 'target_full_slug')):
        csv_path = os.path.join(paths.ROOT, type_dir, 'data', 'taxonomy',
                                'routing.csv')
        if not os.path.exists(csv_path):
            continue
        with open(csv_path, encoding='utf-8-sig') as fh:
            for row in csv.DictReader(fh):
                count[moved(row[column])] += 1
    return count


# -------------------------------------------------- the new tree, in short codes

def short_names():
    """`{entity slug: short code}` from the news taxonomy seed."""
    with open(paths.taxonomy_seed(), encoding='utf-8') as fh:
        seed = json.load(fh)
    return {e['slug']: e['short_name'].lower().replace(' ', '-')
            for region in seed for e in region['entities']}


def translate(rows, entity_shorts):
    """`{pages path: short-code path}` for every row of aku-folder-map.csv.

    Only two levels carry a code of their own: a region takes its
    `region_code`, an entity takes the short name news agreed with AKU. A
    department and a section are already short -- `anaes`, `about`.
    """
    seg = {}
    for row in rows:
        path, slug = row['new_path'], row['new_path'].rsplit('/', 1)[-1]
        if row['kind'] == 'region' and row['region_code'].isalpha():
            seg[path] = row['region_code'].lower()
        elif row['kind'] == 'entity':
            seg[path] = entity_shorts.get(slug, slug)
        else:
            seg[path] = slug
    short = {}
    for row in rows:
        parts = row['new_path'].split('/')
        short[row['new_path']] = '/'.join(
            seg.get('/'.join(parts[:i + 1]), part)
            for i, part in enumerate(parts))
    return short


def rename_targets(pages_rows, short, live):
    """`{live department path: new slug}` for the renames the new tree implies.

    A live `fm` folder is renamed only when the new tree has `fam-med` under the
    same region and entity. That is the whole rule, and it is why 3 folders move
    and not 27.
    """
    wanted = {short[r['new_path']] for r in pages_rows
              if r['kind'] == 'department'}
    out = {}
    for path in live:
        parts = path.split('/')
        if len(parts) != 6 or parts[4] != 'departments':
            continue
        alias = DEPT_ALIAS.get(parts[5])
        if alias and '/'.join(parts[:5] + [alias]) in wanted:
            out[path] = alias
    return out


# ------------------------------------------------------------------ the rows

class Node(dict):
    """One row of the map. A dict so it serialises straight to JSON."""

    def __init__(self, level, to_path, **kw):
        super().__init__(level=level, from_source=None, from_path=None,
                         from_title=None, from_short=None, from_sb_id=None,
                         from_db_id=None, to_path=to_path, to_title=None,
                         to_short=None, action=None, stories=0, pages=0,
                         moves_stories=0, remark='')
        self.update(kw)


def build():
    live, by_id = live_tree()
    stories = story_counts(by_id)
    pages_rows = out_rows('aku-folder-map.csv')
    entity_shorts = short_names()
    short = translate(pages_rows, entity_shorts)
    renames = rename_targets(pages_rows, short, live)

    regions = backend('regions.json')
    entities = backend('region_entities.json')
    departments = backend('entity_departments.json')
    region_by_id = {r['id']: r for r in regions}
    entity_by_id = {e['id']: e for e in entities}

    nodes = collections.OrderedDict()
    renamed_paths = {}

    def add(node):
        nodes.setdefault(node['to_path'], node)
        return nodes[node['to_path']]

    def subtree_stories(path):
        return sum(v for k, v in stories.items()
                   if k == path or k.startswith(path + '/'))

    # --- 1 · the old tree: the backend's own three levels -------------------
    for r in regions:
        code = r['shortName'].lower()
        path = 'regions/%s' % code
        exists = path in live
        add(Node('region', path, from_source='backend.regions',
                 from_path=path if exists else None,
                 from_title=r['title'], from_short=r['shortName'],
                 from_db_id=r['id'],
                 from_sb_id=int(r['storyblokFolderId'])
                 if r['storyblokFolderId'] else None,
                 to_title=r['title'], to_short=r['shortName'],
                 action='keep' if exists else 'create',
                 stories=subtree_stories(path),
                 remark='' if r['storyblokFolderId'] else
                 'the DB row carries no storyblokFolderId; the folder exists, '
                 'so adopt its id rather than creating a second one'))
        add(Node('container', path + '/entities', from_source='backend.regions',
                 from_path=path + '/entities' if path + '/entities' in live else None,
                 from_title='Entities',
                 from_sb_id=int(r['storyblokEntitiesFolderId'])
                 if r['storyblokEntitiesFolderId'] else None,
                 to_title='Entities',
                 action='keep' if path + '/entities' in live else 'create'))

    for e in entities:
        r = region_by_id[e['regionId']]
        path = 'regions/%s/entities/%s' % (r['shortName'].lower(),
                                           e['shortName'].lower())
        add(Node('entity', path, from_source='backend.region_entities',
                 from_path=path if path in live else None,
                 from_title=e['title'], from_short=e['shortName'],
                 from_db_id=e['id'],
                 from_sb_id=int(e['storyblokFolderId'])
                 if e['storyblokFolderId'] else None,
                 to_title=e['title'], to_short=e['shortName'],
                 action='keep' if path in live else 'create',
                 stories=subtree_stories(path)))
        if e['storyblokDepartmentFolderId'] or path + '/departments' in live:
            add(Node('container', path + '/departments',
                     from_source='backend.region_entities',
                     from_path=path + '/departments',
                     from_title='Departments',
                     from_sb_id=int(e['storyblokDepartmentFolderId'])
                     if e['storyblokDepartmentFolderId'] else None,
                     to_title='Departments', action='keep'))

    for d in departments:
        e = entity_by_id[d['entityId']]
        r = region_by_id[e['regionId']]
        old = 'regions/%s/entities/%s/departments/%s' % (
            r['shortName'].lower(), e['shortName'].lower(),
            d['shortName'].lower())
        alias = renames.get(old)
        new = old.rsplit('/', 1)[0] + '/' + alias if alias else old
        if alias:
            renamed_paths[old] = new
        other = DEPT_ALIAS.get(d['shortName'].lower())
        add(Node('department', new, from_source='backend.entity_departments',
                 from_path=old, from_title=d['title'],
                 from_short=d['shortName'], from_db_id=d['id'],
                 from_sb_id=int(d['storyblokFolderId'])
                 if d['storyblokFolderId'] else None,
                 to_title=d['title'], to_short=(alias or d['shortName'].lower()).upper(),
                 action='rename' if alias else 'keep',
                 stories=subtree_stories(old),
                 moves_stories=subtree_stories(old) if alias else 0,
                 remark='the new tree calls this `%s`' % alias if alias else
                 ('same unit as the new tree\'s `%s`, which it does not place '
                  'under this entity -- kept as it is' % other) if other else ''))

    # A renamed department takes its children with it -- `fm/news` holds 3
    # stories and has to end up under `fam-med`, not beside it. Storyblok moves
    # a folder's children when the folder is renamed, so the map must say the
    # same thing or a leaf would look like a stray.
    def rewrite(path):
        for old, new in sorted(renamed_paths.items(), key=lambda kv: -len(kv[0])):
            if path == old or path.startswith(old + '/'):
                return new + path[len(old):]
        return path

    taken = {n['from_path'] for n in nodes.values() if n['from_path']}

    # --- 2 · the leaves the backend seeds ----------------------------------
    for path in sorted(p for p in live if p.split('/')[-1] in LEAVES):
        target = rewrite(path)
        if path in taken or target in nodes:
            continue
        parent = path.rsplit('/', 1)[0]
        if parent not in live:
            continue
        add(Node('leaf', target, from_source='storyblok',
                 from_path=path, from_title=path.split('/')[-1],
                 from_sb_id=live[path], to_title=path.split('/')[-1],
                 action='rename' if target != path else 'keep',
                 stories=stories.get(path, 0),
                 moves_stories=stories.get(path, 0) if target != path else 0,
                 remark='moves with its department'
                 if target != path else 'seeded by the backend with its parent'))

    # --- 3 · the new tree: the pages plan ----------------------------------
    for row in pages_rows:
        src, target = row['new_path'], short[row['new_path']]
        staging = src == 'staging' or src.startswith('staging/')
        empty = int(row['pages_subtree']) == 0
        node = nodes.get(target)
        level = {'region': 'region', 'entity': 'entity',
                 'department': 'department', 'container': 'container',
                 'root': 'stray'}.get(row['kind'], 'section')
        if node is None:
            if staging:
                action, remark = 'ignore', 'a SharePoint test site, not content'
            elif empty:
                action, remark = 'skip', 'no page lands anywhere beneath it'
            elif target in live:
                action, remark = 'adopt', ('the folder exists in Storyblok; '
                                           'write its id into the DB')
            else:
                action, remark = 'create', ''
            node = add(Node(level, target, action=action, remark=remark,
                            from_sb_id=live.get(target),
                            stories=subtree_stories(target)))
        node['from_source'] = ' + '.join(
            filter(None, [node['from_source'], 'pages-plan']))
        node['from_path'] = node['from_path'] or src
        node['to_title'] = node['to_title'] or row['title']
        node['to_short'] = node['to_short'] or target.rsplit('/', 1)[-1]
        node['pages'] = int(row['pages_here'])
        node['pages_subtree'] = int(row['pages_subtree'])
        node['pages_plan_path'] = src
        node['source_web'] = row['source_web']
        node['managed_by'] = row['managed_by']

    # --- 4 · everything else that exists ----------------------------------
    # Two kinds are left. Real structure the plans simply never mentioned -- an
    # entity folder the DB has no row for, and the `programmes` containers the
    # backend seeds -- which is kept, because AKU's instruction is that nothing
    # is deleted. And genuine strays, which are named and left alone.
    taken = {n['from_path'] for n in nodes.values() if n['from_path']}
    for path in sorted(live):
        target = rewrite(path)
        if path in taken or target in nodes:
            continue
        parts = path.split('/')
        if len(parts) == 4 and parts[2] == 'entities':
            add(Node('entity', path, from_source='storyblok', from_path=path,
                     from_title=parts[3], from_short=parts[3].upper(),
                     from_sb_id=live[path], to_title=parts[3],
                     to_short=parts[3].upper(), action='adopt',
                     stories=subtree_stories(path),
                     remark='an entity folder with no row in the backend DB -- '
                            'add one rather than leaving it unmanaged'))
            continue
        if parts[-1] == 'programmes':
            add(Node('container', path, from_source='storyblok',
                     from_path=path, from_title='Programmes',
                     from_sb_id=live[path], to_title='Programmes',
                     action='keep', stories=stories.get(path, 0),
                     remark='seeded under this entity; no plan names it'))
            continue
        remark = KNOWN_STRAY_ROOTS.get(parts[0], '')
        if path.startswith('regions/global2'):
            remark = 'a deliberate copy of global, kept for testing'
        add(Node('stray', path, from_source='storyblok', from_path=path,
                 from_title=parts[-1], from_sb_id=live[path],
                 action='ignore', stories=stories.get(path, 0),
                 remark=remark or 'exists in the space, named by no plan'))

    # --- 5 · the leaves that come with the new region/entity/department rows
    # The backend seeds news, blogs and events inside every one of those three
    # levels, so a created entity brings three folders nobody wrote down. They
    # are listed here, or the target tree is 105 folders short of what applying
    # the map actually produces.
    for path in [n['to_path'] for n in list(nodes.values())
                 if n['action'] == 'create'
                 and n['level'] in ('region', 'entity', 'department')]:
        for leaf in LEAVES:
            add(Node('leaf', '%s/%s' % (path, leaf), to_title=leaf,
                     action='create',
                     remark='seeded by the backend with its parent'))

    for node in nodes.values():
        node.setdefault('pages_subtree', node['pages'])
        node['sb_id'] = node['from_sb_id'] or live.get(node['to_path'])
    return nodes


# ----------------------------------------------------------------- the output

COLUMNS = ['level', 'action', 'from_source', 'from_path', 'from_title',
           'from_short', 'from_db_id', 'from_sb_id', 'to_path', 'to_title',
           'to_short', 'sb_id', 'stories', 'pages', 'pages_subtree',
           'moves_stories', 'source_web', 'managed_by', 'remark']


def nest(nodes):
    """The new tree, nested, for anything that walks it rather than filters it."""
    kids = collections.defaultdict(list)
    roots = []
    for path, node in nodes.items():
        parent = path.rsplit('/', 1)[0] if '/' in path else None
        (kids[parent] if parent in nodes else roots).append(node)

    def attach(node):
        node['children'] = [attach(k) for k in kids.get(node['to_path'], [])]
        return node
    return [attach(n) for n in roots]


def main():
    nodes = build()
    rows = list(nodes.values())
    by_action = collections.Counter(n['action'] for n in rows)
    by_level = collections.Counter(n['level'] for n in rows)

    with open(paths.out('aku-hierarchy-map.csv'), 'w', encoding='utf-8',
              newline='') as fh:
        w = csv.DictWriter(fh, COLUMNS, extrasaction='ignore')
        w.writeheader()
        for row in sorted(rows, key=lambda n: n['to_path'].split('/')):
            w.writerow(row)

    doc = {
        'meta': {
            'space_id': SPACE_ID,
            'naming': 'short codes, as the space is named; the front end '
                      'expands short -> long for the public URL',
            'decided': '2026-09-08',
            'nodes': len(rows),
            'by_action': dict(by_action.most_common()),
            'by_level': dict(by_level.most_common()),
            # Counted at the leaves only. A renamed department reports its
            # whole subtree so the row reads honestly, and its `news` folder
            # reports the same stories -- adding both would count them twice.
            'stories_moved': sum(n['moves_stories'] for n in rows
                                 if n['level'] == 'leaf'),
            'sources': {
                'old': 'Pages-Pipeline/data/backend/*.json + '
                       'storyblok_space/folder_tree.json',
                'new': 'Pages-Pipeline/out/aku-folder-map.csv',
            },
        },
        'tree': nest({k: dict(v) for k, v in nodes.items()}),
    }
    with open(paths.out('AKU-Hierarchy-Map.json'), 'w', encoding='utf-8',
              newline='\n') as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)
        fh.write('\n')

    print('out/aku-hierarchy-map.csv   %d rows' % len(rows))
    print('out/AKU-Hierarchy-Map.json')
    print()
    for action, n in by_action.most_common():
        print('  %-8s %5d' % (action, n))
    print()
    for level, n in by_level.most_common():
        print('  %-11s %5d' % (level, n))
    print()
    print('  stories that move %d' % sum(n['moves_stories'] for n in rows
                                        if n['level'] == 'leaf'))
    print('  pages placed      %d' % sum(n['pages'] for n in rows))
    print('  stories accounted %d' % sum(n['stories'] for n in rows
                                         if n['level'] == 'leaf'))


if __name__ == '__main__':
    main()
