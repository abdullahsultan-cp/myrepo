"""The questions the export cannot answer, as a table AKU can work down.

Everything else in this pipeline is derived from two exports and the live site. These
are the residue: places where all three agree on what the content *is* and still
leave a choice about what to *do* with it. A 401 tells you a section is private; it
does not tell you whether AKU wants it published, migrated private, or dropped.

They lived in conversation until now, which is the wrong place for them — a decision
nobody can see is a decision nobody makes. So they are rows, with the same provenance
discipline as everything else: each one says what was observed and what the options
are, and every count is computed from the plan rather than typed, so a decision that
gets resolved upstream stops appearing here on its own.

`build()` runs at the end of build_migration_plan.py, where the rows already exist.
"""

import collections

from classification import SEC, D
from event_owners import EVENTS as EVENT_OWNERS, stale_events, STALE_BEFORE
from site_visits import NOT_PUBLIC
import paths


# Sections that read as finished on their own page but carry no year we could put
# in DATED — a programme "under review" has no last edition, only a status.
FINISHED = [
    ('iedpk/edip', 'Education Development and Improvement Programme',
     'the page states the programme ended in 2015'),
    ('iedpk/adv-diploma', 'Advanced Diploma in Education',
     'the page states the programme is under review and not currently admitting'),
]

# Two sections where ownership and presentation disagree, both fetched twice. The
# permissions say one thing and the page says another, and neither is wrong — it is
# a question about how AKU wants the site to read.
OWNERSHIP = [
    ('ccit', 'Critical, Creative and Innovative Thinking',
     'the page reads as a standalone programme, but CW/CA MC PK own the web — so the '
     'Medical College writes it while the page presents it as independent. Most of '
     'its pages are blog posts, which consolidate into the global blog hub either '
     'way, so only the section pages actually move',
     ['put it under the Medical College, matching who writes it',
      'give it its own entity folder, matching how the page reads']),
    ('mcpk/hdp', 'the Human Development Programme',
     'AKU’s own Departments menu lists it alongside Medicine and Surgery, while '
     'every mention on its own page calls it the Human Development Programme, '
     'established 2003 — the only place two AKU sources classify the same unit '
     'differently, so it is asked rather than guessed. It is currently a plain '
     'folder, matching the page',
     ['keep it a folder under the Medical College, matching its own page',
      'put it under departments/, matching AKU’s Departments menu']),
    ('mca', 'Muslim Civilisations Abstracts',
     'the page names no institute, and no owner group resolves to one either — it '
     'is the only section where both witnesses are silent',
     ['put it under ISMC, which publishes the abstracts series',
      'leave it at region level as a standalone resource']),
]

# Live, substantial, and contributing nothing — so either AKU's list is incomplete
# or the section is being retired. Only AKU knows which.
ANOMALIES = [
    ('sonamug', 'School of Nursing and Midwifery, Uganda',
     'the section is live and substantial on aku.edu, yet contributes zero pages to '
     'the 3,340 AKU asked us to migrate',
     ['add its pages to the migrate list',
      'confirm it is being retired and drop the folder']),
    ('vacancies', 'Vacancies',
     'duplicates /careers — the same job content under two sections',
     ['migrate /careers and redirect /vacancies to it',
      'keep both if they serve different audiences']),
]


def _dests(folder_rows, section):
    """Destination folders built from this source section."""
    section = section.strip('/')
    return {f['new_path'] for f in folder_rows
            if any(w.strip() == section or w.strip().startswith(section + '/')
                   for w in f['source_web'].split(';'))}


def _pages_in(page_rows, dests):
    """Pages that would actually move if these folders moved.

    Counting by source URL overstates it: /ccit is 56 pages, but 51 are blog posts
    that consolidate into the global blog hub whichever way the decision goes. Only
    the pages that still land inside the folder are at stake.
    """
    return [p for p in page_rows if p['folder'] in dests]


def build(folder_rows, page_rows):
    rows = []

    def add(group, question, evidence, options, folders=(), pages=0, blocks=''):
        rows.append({
            'id': '%s-%d' % (group, sum(1 for r in rows if r['group'] == group) + 1),
            'group': group,
            'question': question,
            'evidence': evidence,
            'options': ' | '.join(options),
            'folders': len(folders),
            'pages': pages,
            'example_paths': '; '.join(sorted(folders)[:4]),
            'blocks': blocks,
        })

    # 1. Sections AKU's own list says to migrate, which do not answer to the public.
    #    /cancer-centre/information-hub sits inside /cancer-centre and both returned
    #    401, so asking twice would double-count 8 pages and imply two decisions where
    #    there is one -- a private parent takes its whole subtree with it.
    covered = {p.strip('/') for p, _, _, _ in NOT_PUBLIC}
    for path, code, listed, label in sorted(NOT_PUBLIC, key=lambda x: -x[2]):
        section = path.strip('/')
        if any(section.startswith(o + '/') for o in covered if o != section):
            continue
        dests = _dests(folder_rows, section)
        hits = len(_pages_in(page_rows, dests))
        # The count in site_visits.py was read off AKU's list by hand. The plan
        # derives it. If they ever disagree, one of them is stale -- say so rather
        # than quietly preferring either.
        if hits != listed and not any(o.startswith(section + '/') for o in covered
                                      if o != section):
            raise SystemExit(
                'decisions.py: %s is recorded as %d pages in site_visits.py but the '
                'plan places %d. Reconcile before shipping.' % (path, listed, hits))
        add('not public',
            'HTTP %d — %s. Publish it, migrate it private, or drop it?' % (code, label),
            'fetched and returned %d; %d of its pages are in AKU’s migrate list'
            % (code, hits),
            ['publish it before the migration',
             'migrate it as a private Storyblok folder',
             'drop it and let the pages go'],
            folders=dests, pages=hits,
            blocks='these pages cannot be reviewed before migration' if hits else '')

    # 2. Dated content with no recent edition. Derived, so resolving a date upstream
    #    removes the row without anyone editing this file.
    stale = stale_events()
    for f in sorted(folder_rows, key=lambda r: r['new_path']):
        if not f['archive_candidate']:
            continue
        add('stale',
            'Carry %s forward, or archive it?' % (f['title'] or f['new_path'].split('/')[-1]),
            f['archive_candidate'].replace('yes — ', ''),
            ['migrate it as live content',
             'migrate it into an archive folder, out of the main tree',
             'do not migrate it'],
            folders=[f['new_path']], pages=int(f['pages_subtree'] or 0))

    # 3. Programmes their own page reports as over.
    for web, label, why in FINISHED:
        dests = _dests(folder_rows, web)
        pages = len(_pages_in(page_rows, dests))
        add('finished', 'Does %s still need a page?' % label, why,
            ['keep it as a record of a completed programme',
             'archive it', 'do not migrate it'],
            folders=dests, pages=pages)

    # 4. Ownership disagreeing with presentation.
    for section, label, why, opts in OWNERSHIP:
        dests = _dests(folder_rows, section)
        pages = len(_pages_in(page_rows, dests))
        add('ownership', 'Where should %s sit?' % label, why, opts,
            folders=dests, pages=pages,
            blocks='its folder path, and therefore every slug beneath it')

    # 5. Live-but-absent, and duplicated.
    for section, label, why, opts in ANOMALIES:
        dests = _dests(folder_rows, section)
        add('anomaly', '%s — %s' % (label, why.split(' — ')[0][:60]), why, opts,
            folders=dests, pages=len(_pages_in(page_rows, dests)))

    # 6. The same entity in two regions, one of them empty. AKU keeps per-country
    #    SharePoint stubs (/mcke, /mctz, /iedtz, /sonamke, /sonamtz) that all return
    #    401 and hold no pages, while the real content sits in the East Africa folder
    #    -- mcea/about says so outright: "134 faculty on two campuses (Kenya and
    #    Tanzania)". Left in, Storyblok gets ten folders holding nothing and a reader
    #    sees three Medical Colleges. Derived, so it disappears if the stubs ever
    #    gain content.
    by_ent = collections.defaultdict(list)
    for f in folder_rows:
        if f['kind'] == 'entity':
            by_ent[f['new_path'].split('/entities/')[1]].append(f)
    empty_dupes = []
    for ent, fs in sorted(by_ent.items()):
        if len(fs) < 2 or not any(int(f['pages_subtree'] or 0) for f in fs):
            continue
        for f in fs:
            if not int(f['pages_subtree'] or 0) and 'no source folder' in f['source_web']:
                empty_dupes.append(f['new_path'])
    if empty_dupes:
        kids = [f['new_path'] for f in folder_rows
                if any(f['parent_path'] == e for e in empty_dupes)]
        add('anomaly',
            'Create %d empty entity folders for entities that already exist '
            'elsewhere?' % len(empty_dupes),
            'each is a per-country SharePoint stub that returns 401 and holds no '
            'pages, while the entity’s real content sits in its East Africa folder; '
            'aku.edu/mcea/about calls it one college on "two campuses (Kenya and '
            'Tanzania)". With their %d empty children that is %d folders holding '
            'nothing' % (len(kids), len(empty_dupes) + len(kids)),
            ['drop them — one entity folder per entity, tagged by country',
             'keep them as placeholders for content AKU plans to add'],
            folders=empty_dupes, pages=0)

    # 7. Placements the export could not settle, marked needs-decision upstream.
    for section, (region, ent, ent_name, div, conf, prov) in sorted(SEC.items()):
        if conf != D:
            continue
        if any(section == o[0] for o in OWNERSHIP):
            continue          # already asked above, with better wording
        dests = _dests(folder_rows, section)
        add('placement', 'Which region owns /%s?' % section, prov,
            ['confirm the inferred placement', 'move it'],
            folders=dests, pages=len(_pages_in(page_rows, dests)))

    # 7. Pages the plan already refuses to move, listed so the refusal is visible
    #    rather than silent.
    dnm = [p for p in page_rows if p['do_not_migrate']]
    if dnm:
        why = collections.Counter(p['do_not_migrate'] for p in dnm)
        # First sentence, not first 60 characters -- a character cut lands
        # mid-word and reads as a bug ("one detail templat").
        add('do not migrate',
            'Confirm %d pages should not move?' % len(dnm),
            '; '.join('%s (%d)' % (k.split('. ')[0].rstrip('.'), v)
                      for k, v in why.most_common()),
            ['confirm', 'migrate some of them after all'],
            folders=[], pages=len(dnm),
            blocks='')

    return rows


if __name__ == '__main__':
    import io, json, os
    HERE = os.path.dirname(os.path.abspath(__file__))
    plan = json.load(io.open(paths.work('plan.json'), encoding='utf-8'))
    rows = build(plan['folders'], plan['pages'])
    by = collections.Counter(r['group'] for r in rows)
    print('open decisions %d' % len(rows))
    for g, n in by.most_common():
        pages = sum(r['pages'] for r in rows if r['group'] == g)
        print('  %-16s %3d   %5d pages behind them' % (g, n, pages))
    print()
    print('biggest ten by pages at stake:')
    for r in sorted(rows, key=lambda x: -x['pages'])[:10]:
        print('  %5d  %-14s %s' % (r['pages'], r['group'], r['question'][:74]))
