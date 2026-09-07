"""build_master_sheet.py -- one sheet with every page, and nothing hidden.

AKU's instruction (7 Sep 2026) is that no page is ever removed from the
deliverable. A row taken out of the sheet is a page nobody can look up again
once SharePoint is switched off, so anything wrong with a page is written
BESIDE it in the remark column instead of being a reason to drop it.

That makes this sheet the union of three populations that used to live in three
separate files, each of which someone had to know to open:

  4,591  the pages in aku-university-filtered.csv -- AKU's own list, priority 1
    367  live pages found by crawling that appear in no AKU export -- priority 2
    275  crawled URLs that are dead, login-only or unscanned -- recorded, not built

Nothing here decides anything. Every destination comes from plan.json and every
remark from a source named in the remark itself, so a reviewer can check any row
against the file it came from.

Inputs   out/work/plan.json, data/SPPagesAKU-Metadata.csv,
         out/aku-live-page-verification.csv, out/aku-pages-not-in-the-list.csv
Outputs  out/aku-master-pages.csv     one row per page
         out/aku-master-folders.csv   one row per folder
"""
import collections
import csv
import json

import page_intake
import page_titles
import paths

PLAN = json.load(open(paths.work('plan.json'), encoding='utf-8'))
PAGES, FOLDERS, DECISIONS = PLAN['pages'], PLAN['folders'], PLAN['decisions']

# ---- what we know about each page from somewhere other than the plan -------
TITLE, HTTP, CRUMB = {}, {}, {}
with open(paths.data('SPPagesAKU-Metadata.csv'), encoding='utf-8-sig') as fh:
    for r in csv.DictReader(fh):
        k = page_intake.key(r.get('Original Page URL') or '')
        if k and r.get('Title'):
            # Cleaned here rather than in each consumer: 135 of AKU's titles
            # carry a zero-width space, which reads identically to the same
            # title without one and sorts apart from it. Nine copies of "Dean's
            # Communiqué" came out as three groups nobody could reconcile.
            TITLE[k] = page_titles.clean(r['Title'])
try:
    with open(paths.out('aku-live-page-verification.csv'), encoding='utf-8-sig') as fh:
        for r in csv.DictReader(fh):
            k = page_intake.key(r['current_url'])
            HTTP[k] = r.get('http', '')
            CRUMB[k] = r.get('breadcrumb', '')
            TITLE.setdefault(k, page_titles.clean(r.get('live_title', '')))
except FileNotFoundError:
    pass

# A decision names the folders it covers, not the pages, so a page inherits the
# decision of the deepest folder it sits under. Prefix-matched -- stated here
# because it is an inference and a reviewer should be able to see that it is.
DEC_AT = {}
for d in DECISIONS:
    for path in (d.get('example_paths') or '').split(';'):
        path = path.strip()
        if path:
            DEC_AT[path] = '%s: %s' % (d['group'], d['question'])


def decision_for(dest):
    parts = dest.split('/')
    for i in range(len(parts), 0, -1):
        hit = DEC_AT.get('/'.join(parts[:i]))
        if hit:
            return hit
    return ''


# The four pages under global/vacancies that are the job board's own plumbing
# rather than anything a visitor reads. Named individually: guessing from the
# slug would also catch apply-online, which IS a public page.
VACANCIES_INTERNAL = {'admin', 'create-job', 'vacancies-test',
                      'career-opportunities-working-file'}

HTTP_SAYS = {
    '401': 'HTTP 401 - login only, could not verify',
    '404': 'HTTP 404 - gone from the live site',
    '403': 'HTTP 403 - refused by the server',
    '500': 'HTTP 500 - the server errored',
}


def remarks(p, dest):
    """Everything wrong with this page, in the order it matters. Never a drop."""
    out = []
    if p.get('do_not_migrate'):
        out.append(p['do_not_migrate'])
    if p.get('collision'):
        out.append(p['collision'])
    said = HTTP_SAYS.get(HTTP.get(page_intake.key(p['current_url']), ''))
    if said:
        out.append(said)
    if p.get('action') in ('Not Reviewed', 'Unclear'):
        out.append('AKU: %s' % p['action'])
    if dest.startswith('staging/'):
        out.append('AKU test site - kept for the record, hide with the filter')
    if (dest.startswith('regions/global/vacancies/')
            and dest.rsplit('/', 1)[-1] in VACANCIES_INTERNAL):
        out.append('admin/test page - the job board plumbing, not a visitor page')
    if not dest:
        out.append('no destination - superseded, see the reason above')
    return ' | '.join(out)


# ---- place it, but do you BUILD it? ---------------------------------------
# AKU's decision of 7 Sep 2026, and the distinction the sheet was missing: a
# page can have a correct place in the hierarchy and still not be built. The
# two are separate columns because they are separate facts, and collapsing them
# is how a page ends up either silently absent or silently empty.
#
#   yes    build it
#   no     it has a place, but there is nothing to build from -- either the
#          server will not serve it to us, or another page supersedes it
#   later  real, and AKU wants it, but after the 4,591. Found by crawling.
def buildable(http, dest, priority):
    if priority == '2':
        return 'later', 'AKU list comes first; build this if there is time'
    if not dest:
        return 'no', 'superseded -- another page carries this content'
    if http == '401':
        return 'no', ('login only -- AKU has not made it public, so nobody can '
                      'read the content. Its place in the hierarchy is RESERVED: '
                      'hand over the page and it goes straight here, no '
                      'replanning. AKU to unblock')
    if http in ('404', '403', '500'):
        return 'no', 'the live site will not serve it, so there is nothing to copy'
    return 'yes', ''


rows = []
for p in PAGES:
    k = page_intake.key(p['current_url'])
    dest = p['new_path']
    build, why = buildable(HTTP.get(k, ''), dest, '1')
    rows.append({
        'priority': '1',
        'in_aku_list': 'yes',
        'build': build,
        'build_reason': why,
        'source_url': p['current_url'],
        'title': TITLE.get(k, ''),
        'http': HTTP.get(k, ''),
        'region': p['region'],
        'entity': p['entity'],
        'department': p['department'],
        'destination_path': dest,
        'destination_url': p['new_url'],
        'content_type': p['content_type'],
        'managed_by': p['managed_by'],
        'managed_by_source': p['managed_by_source'],
        'aku_action': p['action'],
        'confidence': p['confidence'],
        'breadcrumb': CRUMB.get(k, ''),
        'open_decision': decision_for(dest),
        'remark': remarks(p, dest),
    })

# ---- the pages AKU never listed -------------------------------------------
# Found by following links on the live site. AKU's decision is that these are
# real and should be built, but SECOND -- the 4,591 come first, and if these do
# not fit the schedule they do not ship. They carry no destination path because
# nothing has classified them; 51 belong to a section the structure does not
# have at all, and those need a human before a path could be honest.
crawl = 0
try:
    fh = open(paths.out('aku-pages-not-in-the-list.csv'), encoding='utf-8-sig')
except FileNotFoundError:
    fh = None
if fh:
    with fh:
        for r in csv.DictReader(fh):
            said = HTTP_SAYS.get(r['http'], '')
            note = ['optional - found by crawl, in no AKU export']
            if said:
                note.append(said)
            elif r['http'] != '200':
                note.append('not scanned')
            if r['section_known'] != 'yes':
                note.append('section not in the structure - needs placing by AKU')
            rows.append({
                'priority': '2',
                'in_aku_list': 'no',
                'build': 'later',
                'build_reason': 'AKU list comes first; build this if there is time',
                'source_url': r['url'],
                'title': page_titles.clean(r['title']),
                'http': r['http'],
                'region': r['would_be_region'],
                'entity': r['would_be_entity'],
                'department': '',
                'destination_path': '',
                'destination_url': '',
                'content_type': '',
                'managed_by': '',
                'managed_by_source': '',
                'aku_action': '',
                'confidence': 'decide',
                'breadcrumb': r['breadcrumb'],
                'open_decision': '',
                'remark': ' | '.join(note),
            })
            crawl += 1

rows.sort(key=lambda r: (r['priority'], r['source_url'].lower()))

PAGE_COLS = ['priority', 'build', 'build_reason', 'in_aku_list', 'source_url',
             'title', 'http', 'region',
             'entity', 'department', 'destination_path', 'destination_url',
             'content_type', 'managed_by', 'managed_by_source', 'aku_action',
             'confidence', 'breadcrumb', 'open_decision', 'remark']

# ---- folders, with the empty ones said out loud ---------------------------
frows = []
for f in FOLDERS:
    note = []
    if not f['pages_subtree']:
        note.append('empty - AKU has this folder but listed no page in it; '
                    'created anyway so the structure is complete')
    if f['new_path'].startswith('staging'):
        note.append('AKU test site - kept for the record, hide with the filter')
    frows.append({
        'destination_path': f['new_path'],
        'title': f['title'],
        'kind': f['kind'],
        'level': f['level'],
        'region': f['region'],
        'entity': f['entity'],
        'source_web': f['source_web'],
        'pages_here': f['pages_here'],
        'pages_subtree': f['pages_subtree'],
        'managed_by': f['managed_by'],
        'confidence': f['confidence'],
        'open_decision': decision_for(f['new_path']),
        'remark': ' | '.join(note),
    })
frows.sort(key=lambda r: r['destination_path'])

FOLDER_COLS = ['destination_path', 'title', 'kind', 'level', 'region', 'entity',
               'source_web', 'pages_here', 'pages_subtree', 'managed_by',
               'confidence', 'open_decision', 'remark']


def write(name, data, cols):
    with open(paths.out(name), 'w', encoding='utf-8-sig', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction='ignore')
        w.writeheader()
        w.writerows(data)
    print('%-30s %5d rows' % (name, len(data)))


write('aku-master-pages.csv', rows, PAGE_COLS)
write('aku-master-folders.csv', frows, FOLDER_COLS)

print()
print('priority 1 (AKU list)       %5d' % sum(1 for r in rows if r['priority'] == '1'))
print('priority 2 (crawl only)     %5d' % crawl)
print('rows carrying a remark      %5d' % sum(1 for r in rows if r['remark']))
print('rows with no destination    %5d' % sum(1 for r in rows if not r['destination_path']))
for verdict in ('yes', 'no', 'later'):
    print('build = %-6s            %5d' % (verdict, sum(1 for r in rows if r['build'] == verdict)))
print('folders that would be empty %5d' % sum(1 for r in frows if 'empty' in r['remark']))
print()
top = collections.Counter(part.split(' - ')[0][:56]
                          for r in rows if r['remark']
                          for part in r['remark'].split(' | '))
print('the remarks, most common first:')
for text, n in top.most_common(14):
    print('  %5d  %s' % (n, text))
