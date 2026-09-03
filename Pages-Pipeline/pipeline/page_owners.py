"""Who writes each page, according to the page itself.

`nearest_owner()` in build_migration_plan answers this from the permissions
export, which grants at the level of a *web*. Where a web's rows are all
inherited it finds no owner, and the page falls back to "Public Affairs
(central)" -- true of 523 pages that are plainly not central comms's work: 177
Brain & Mind Institute pages, 111 under /supportus, 98 QTL, 45 GSMC, 45 IGHD.

`SPPagesAKU-Metadata.csv` carries `CW` and `CA` on the page itself -- the content
writer and approver groups SharePoint has set there. On 97.4% of the pages it
covers, that names a team. It is a per-page witness where the export has only a
per-web one, and it fills that gap.

**It fills the gap; it never overrules the export.** Where both speak they agree
on 2,580 of 2,656 pages, and the 76 exceptions are not ownership disputes:

    CW SONAM-PK Faculty   26 pages   8 sections   4 filenames
                          faspk, iedea, iedpk, ismc, mcea, mcpk, sonamea, sonampk
                          admin.aspx, create-profile.aspx, home.aspx, profile.aspx

That is one faculty-profile app copied into seven faculties, every copy carrying
whoever built it -- not the School of Nursing owning ISMC's pages. The same holds
for the blog and event templates that carry `CW FAS PK` into /cime and /deib. In
every one of those cases the folder already has a named owner from the export,
which is the right answer, so preferring the export settles them all without a
rule about which groups to believe.

An earlier draft tried to decide that per group, by asking which section a group
mostly appears in. It got `CW SONAM-PK Faculty` wrong -- 4 pages in /faspk and 4
in /sonampk is a tie broken arbitrarily -- and it threw away `CW GSMC` on the GNV
pages, which really are GSMC's. Preferring the export needs no such judgement.

`conflicts()` lists the disagreements rather than resolving them, because a
handful are worth a human's attention: /mcpk/Pages/animal-facility.aspx and
jrl.aspx are filed under the Medical College but written by Research and Graduate
Studies, which may be the better home for a shared research facility.
"""
import collections
import csv
import json
import os
import re

import page_intake
import paths

csv.field_size_limit(10 ** 9)

METADATA_CSV = paths.data('SPPagesAKU-Metadata.csv')


def _rows():
    if not os.path.exists(METADATA_CSV):
        return
    with open(METADATA_CSV, encoding='utf-8-sig', newline='') as fh:
        for r in csv.DictReader(fh):
            u = (r.get('Original Page URL') or '').strip()
            if u:
                yield page_intake.key(u), r


def _unit_map():
    """group name -> unit, as probe_roles.py already resolved it.

    AKU names these groups three ways -- `CW CRM`, `CRM Writer`,
    `FacultyOwners-mcpk` -- and only the first yields its unit by dropping a
    prefix. Doing that by hand read `CRM Writer` and `CRM Approver` as two teams
    neither of which was the folder's `CRM`, and reported 73 of /crm's own pages
    as owned by somebody else. groups.json has already done this properly, so
    ask it and only fall back to the prefix for a group it does not carry.
    """
    path = paths.work('groups.json')
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as fh:
        return {g['group']: g['unit'] for g in json.load(fh) if g.get('unit')}


_UNITS = None


def _units(row):
    """The teams a page's CW/CA groups name, spelled as `managed_by` spells them."""
    global _UNITS
    if _UNITS is None:
        _UNITS = _unit_map()
    out = set()
    for col in ('CW', 'CA'):
        for g in re.split(r'[;,]', row.get(col) or ''):
            g = g.strip()
            if not g:
                continue
            u = _UNITS.get(g)
            out.add(u if u else (g[3:].strip() if g[:3] in ('CW ', 'CA ') else g))
    return sorted(u for u in out if u)


def owners():
    """page key -> the units the page names for itself. Empty where it names none."""
    return {key: u for key, row in _rows() if (u := _units(row))}


def titles():
    """page key -> (page title, the SharePoint title of the web holding it).

    Not used for placement -- it is what a reviewer reads to tell whether a
    placement looks right, and the verification CSV carries it for that.
    """
    return {key: ((row.get('Title') or '').strip(),
                  (row.get('Web Title') or '').strip())
            for key, row in _rows()}


def conflicts(page_rows):
    """Pages whose own CW/CA names a team the folder's owner does not include.

    Reported, never resolved: the export wins in the plan, and these are the
    rows worth a second opinion.
    """
    own = owners()
    out = []
    for r in page_rows:
        key = page_intake.key(r['current_url'])
        mine = set(own.get(key, ()))
        if not mine:
            continue
        theirs = {u.strip() for u in r['managed_by'].split(';') if u.strip()}
        if theirs and theirs != {'Public Affairs (central)'} and not (mine & theirs):
            out.append((r['current_url'], sorted(mine), sorted(theirs), r['folder']))
    return sorted(out)


if __name__ == '__main__':
    own = owners()
    print('metadata rows ................ %d' % sum(1 for _ in _rows()))
    print('pages naming their own team .. %d' % len(own))
    print()
    u = collections.Counter(x for units in own.values() for x in units)
    print('most common page-level teams (%d distinct):' % len(u))
    for k, n in u.most_common(14):
        print('   %-38s %d' % (k[:38], n))
