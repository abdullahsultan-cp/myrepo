"""Turn the two AKU exports into a migration plan: where every folder and page
goes, who manages it, and which Storyblok roles to create.

Inputs
  aku-university-visible-pages.csv   AKU's own list of pages to migrate (authoritative)
  the SharePoint permissions export  via webs.json / web_owners.json / groups.json

Outputs (all in Pages-Pipeline/)
  aku-folder-map.csv        one row per destination folder
  aku-page-map.csv          one row per page: today's URL -> tomorrow's path
  aku-permission-groups.csv the Storyblok roles to create, and who goes in them
  AKU-Migration-Plan.html   the same three tables, filterable

Path convention follows the repo's rule: slugs are lowercase-hyphenated and use
the FULL name, never the abbreviation, so region folders are `pakistan` not `pk`.
Short codes stay metadata, shown as a column and never used in a path.

A sub-folder becomes a `departments/` level only when the permissions export
proves it is a real unit -- it has its own CW/CA owner group, the way mcpk/anaes
is owned by "Anaesthesiology". Everything else keeps its own slug, so no path
segment is invented.
"""
import collections
import csv
import json
import os
import re

import page_intake
import page_owners
import paths
from classification import ENTITY_COUNTRIES, REGIONS, ROOT_PAGE_DEST, SEC, W, entity_basis

# Each event microsite's owning unit and last edition, read off its own page.
from event_owners import EVENTS as EVENT_OWNERS
from event_owners import STALE_BEFORE, stale_events

# Pages checked against the live site and found not to be migratable. Each was
# fetched, not assumed: the reason is what the server actually returned.
DO_NOT_MIGRATE = {
    'https://www.aku.edu/crm/about/Pages/executive.committee.aspx':
        'HTTP 401 — not publicly visible. The hyphenated executive-committee.aspx '
        'is the live page and carries the five committee members.',
    'https://www.aku.edu/library/pk/fhs/SitePages/Home.aspx':
        'Empty SharePoint default page — body reads "There are no items to show in '
        'this view of the Documents document library". Pages/home.aspx is the real '
        '800-word FHS library homepage.',
    'https://www.aku.edu/coe-wch/ea/Pages/home-1.aspx':
        'HTTP 404 — already gone from the live site.',

    # Found by the verify_live.py sweep of AKU's filtered export and re-fetched
    # twice each to rule out a transient failure. All five are on AKU's migrate
    # list and none of them exist; the other 252 unreachable pages returned 401,
    # which is a permissions question rather than a missing page, so they stay in
    # the plan and are raised as a decision instead.
    'https://www.aku.edu/about/officers/Pages/founding-dean-ighd.aspx':
        'HTTP 404 on two fetches — gone from the live site.',
    'https://www.aku.edu/bmi/about/Pages/waliyah-mughis.aspx':
        'HTTP 404 on two fetches — gone from the live site.',
    'https://www.aku.edu/events/rsc-conf/Pages/abstract-submission-form.aspx':
        'HTTP 404 on two fetches — gone; the conference keeps its other '
        'abstract-submission.aspx, which answers 200.',
    'https://www.aku.edu/mcpk/pathology/Pages/histopathology.aspx':
        'HTTP 404 on two fetches — gone from the live site.',
    'https://www.aku.edu/news/Pages/testNews.aspx':
        'HTTP 404 on two fetches — a test page, and gone.',
}

webs = json.load(open(paths.work('webs.json'), encoding='utf-8'))
web_owners = json.load(open(paths.work('web_owners.json'), encoding='utf-8'))
groups = json.load(open(paths.work('groups.json'), encoding='utf-8'))

GKIND = {g['group']: g['kind'] for g in groups}
GUNIT = {g['group']: g['unit'] for g in groups}
GPEOPLE = {g['group']: g['people'] for g in groups}
GROLES = {g['group']: g['roles'] for g in groups}
CENTRAL = {'CW Public Affairs', 'CA Public Affairs'}
REGION_CODE = {slug: code for slug, name, code, note in REGIONS}
REGION_NAME = {slug: name for slug, name, code, note in REGIONS}
REGION_CODE['staging'] = '--'
REGION_NAME['staging'] = 'Not content'

# ---- SharePoint role string -> what it lets you do -----------------------
# Storyblok has no "Design"; the useful distinction is publish vs draft-only,
# which is exactly what AKU already separates with its CW / CA pairs.
def capability(role_string):
    r = role_string.lower()
    if 'manage permissions' in r or r.startswith('full control'):
        return 'admin'
    if 'manage hierarchy' in r:
        return 'structure'
    if 'translation' in r:
        return 'translator'
    if 'approve' in r:
        return 'publisher'
    if 'contribute' in r or 'edit' in r:
        return 'editor'
    return 'viewer'

SCAFFOLD = {'regions', 'entities', 'departments'}

def public_url(cms_path):
    """The address a reader should see.

    The CMS path carries structure a visitor does not need -- `regions/`,
    `entities/`, `departments/` are there so editors and permissions have
    something to hang on. Strip them for the public link.

    A trailing `home` goes the same way. SharePoint serves `X/Pages/home.aspx`
    AT `X/`, so keeping the segment would publish the university homepage at
    `aku.edu/home` and every faculty front door one level below where the
    reader expects it. The page still LIVES at `<folder>/home` in Storyblok --
    this is the address only, exactly as it is for the three scaffold segments,
    so no folder and page ever share a slug. The front end strips the same
    four.
    """
    parts = cms_path.split('/')
    if len(parts) > 1 and parts[-1] == 'home':
        parts = parts[:-1]
    # A scaffold segment is invisible only while it is an INTERMEDIATE level.
    # As the last segment it is the thing being addressed, and dropping it
    # hands the address to something else: `departments` is a real AKU web with
    # its own list page, so stripping it unconditionally sent
    # `mcpk/Pages/departments.aspx` to `aku.edu/pakistan/medical-college` — the
    # faculty's front door — and pushed the Medical College's own home page to
    # `medical-college/home-2`. The reader would have found the department list
    # where the faculty homepage belongs.
    parts = [x for i, x in enumerate(parts)
             if x not in SCAFFOLD or i == len(parts) - 1]
    if parts and parts[0] == 'global':
        parts = parts[1:]
    # Nothing left means the site root. `regions/global/home` is the university
    # homepage, and it is the one page whose address is `aku.edu/` itself —
    # guarding against the empty join is what published it at `aku.edu/home`.
    return 'https://www.aku.edu/' + '/'.join(parts)

# Invisible characters have to be DELETED before the slug is built, not turned
# into a separator. Fifteen page names carry a zero-width space, three of them
# inside a word, and the generic "anything not a-z0-9 becomes a dash" rule split
# those words in the public address:
#
#     zehr<U+200B>a-nigah.aspx            -> zehr-a-nigah      (Zehra Nigah)
#     vaccinology-cou<U+200B><U+200B>rse  -> vaccinology-cou-rse
#     lung-tumo<U+200B>rs<U+200B>.aspx    -> lung-tumo-rs
#
# The same class of character is deleted in `pipeline/core/text_clean.py` for
# story text, for the same reason, and the list is written as code points rather
# than as the characters themselves so it can be reviewed — a string of
# invisibles is unreadable in a diff. U+200C and U+200D are here too: they carry
# meaning in Urdu and Arabic, but a slug is ASCII either way, and dropping them
# beats splitting a word on them.
INVISIBLE = dict.fromkeys([
    0x200B,  # zero width space
    0x200C,  # zero width non-joiner
    0x200D,  # zero width joiner
    0x00AD,  # soft hyphen
    0xFEFF,  # byte order mark
    0x2060,  # word joiner
], None)
# These are spaces, so they become the separator a space would.
AS_SPACE = {0x00A0: ' ', 0x202F: ' ', 0x2009: ' ', 0x2028: ' ', 0x2029: ' '}


def slugify(s):
    s = s.translate(INVISIBLE).translate(AS_SPACE)
    s = s.strip().lower()
    s = s.replace("'", '').replace('’', '').replace('&', 'and')
    s = re.sub(r'\.aspx$', '', s)
    s = re.sub(r'[^a-z0-9]+', '-', s)
    return re.sub(r'-{2,}', '-', s).strip('-') or 'page'

# ---- which webs have a real owning unit ---------------------------------
def owner_units(web):
    """The named units that administer this web, ignoring central comms."""
    out = []
    for g in web_owners.get(web, []):
        if g in CENTRAL:
            continue
        if GKIND.get(g) in ('writer', 'approver') and GUNIT.get(g):
            out.append(g)
    return out

owned = {w: owner_units(w) for w in web_owners}
owned = {w: v for w, v in owned.items() if v}

def nearest_owner(web):
    """Walk up until a web names its own unit; central comms is the fallback."""
    cur = web
    while True:
        if cur in owned:
            us = sorted({GUNIT[g] for g in owned[cur]})
            return cur, us
        if '/' not in cur:
            return None, []
        cur = cur.rsplit('/', 1)[0]

def units_at(web):
    return {GUNIT[g] for g in owned.get(web, [])}

def is_department(section, sub_web):
    """A real unit, not just a functional sub-folder.

    mcpk/anaes is owned by "Anaesthesiology" -- a unit of its own, so a
    department. mcpk/events is owned by "MC PK", the same unit that owns the
    whole section, so it is just a folder the faculty keeps its events in.
    The difference is whether the sub-folder introduces a NEW owning unit.
    """
    return bool(units_at(sub_web) - units_at(section))

# SharePoint's own library names -- "Pages", "SitePages", "Documents" -- are not
# content folders, and several webs carry one in the middle of their path.
# page_intake strips them off a page's URL; dest_web has to skip them again for
# webs the permissions export lists with one already in the path.
LIBRARY_SEGS = page_intake.CONTAINER_SEGS

# Departments are only witnessed by a group where a region bothered to create
# one. Pakistan gives every clinical department its own CW/CA pair; East Africa
# runs the same departments under one faculty-wide group, so mcea/anaes would
# read as a plain folder while mcpk/anaes reads as a department. Learn the
# department names per entity from wherever they ARE witnessed, then honour that
# name for the same entity in every other region.
DEPT_NAMES = collections.defaultdict(set)

# Read off aku.edu/mcea/departments, which publishes the list: 11 departments at
# Nairobi and 5 at Dar es Salaam. `medicine` is the Department of Internal
# Medicine and `radiology` the Department of Radiology -- East Africa runs them
# under one faculty group, so no group witnesses them.
EXTRA_DEPARTMENTS = {
    'medical-college': {'medicine', 'radiology'},
}

# The opposite correction. A programme office owning a folder made these look like
# departments; each page calls itself something else. All fetched and confirmed:
#   fellowship / residency / internship / pgme  postgraduate training programmes
#   med / mphil / phd / adv-diploma             degree programmes ("Master of
#                                               Education", "PhD in Education", …)
#   cpe / ugme / education                      teaching programmes
#   data-science                                a Centre under CITRIC
# The owners are offices -- PGME PK, Graduate Programmes, DS -- not departments.
NOT_DEPARTMENTS = {'fellowship', 'residency', 'internship', 'pgme',
                   'ugme', 'education', 'mphil', 'phd', 'adv-diploma',
                   'adv-diploma-education', 'adv-diploma-hd', 'adv-diploma-hpe',
                   'cpe'}

# And the general rule behind those: a folder carrying one of AKU's own standard
# function names is never a department, whoever happens to own it. IED's `research`
# and `alumni` are owned by the Graduate Programmes office, which made them look
# like units; /mcpk/research settled it -- research is a faculty function sitting
# parallel to Programmes, Faculty and Departments, not a department.
FUNCTION_NAMES = {
    'about', 'about-us', 'research', 'faculty', 'programmes', 'programs', 'study',
    'alumni', 'events', 'news', 'blogs', 'blog', 'resources', 'people', 'staff',
    'contact', 'partners', 'impact', 'giving', 'centres', 'library', 'media',
    'careers', 'outreach', 'publications', 'projects', 'newsletter', 'team',
    'admissions', 'support-us', 'supportus',
}
NOT_DEPARTMENTS |= FUNCTION_NAMES

# A third kind, which AKU's IED nav gives its own menu item ("CENTRES"). A centre
# is not a department and not a programme: it is a standing unit inside a faculty.
# Each of these was fetched and calls itself a centre.
# A fifth kind. AKU runs "Offices" inside faculties -- the Office of Allied Health
# was "conceptualized in 2021" -- and they are neither departments nor programmes.
# Both fetched and confirmed.
OFFICES = {
    'allied-health': 'Office of Allied Health, Medical College',
    'copyright': 'Copyright Office, University Librarian’s Office',
}

CENTRES = {
    'pdc-karachi': 'Professional Development Centre, Karachi',
    'ccbp': 'Center for Clinical Best Practices',
    'cbcb': 'Centre for Bioinformatics and Computational Biology',
    'pdc-north': 'Professional Development Centre, North (Gilgit-Baltistan)',
    'pdc-chitral': 'Professional Development Centre, Chitral',
    'cgsc': 'Centre of Global Surgical Care',
    'coors': 'Centre of Oncological Research in Surgery',
    'bioinformatics': 'Centre for Bioinformatics',
    'citric': 'Clinical and Translational Research Incubator',
    'patient-safety': 'Centre for Patient Safety',
    'data-science': 'CITRIC-Health Data Science Centre, established December 2020',
}

# A sixth kind. Some folders under a department are not units at all but the
# things a unit publishes -- LABRAD is a newsletter now in its 50th volume, issued
# by Pathology & Laboratory Medicine jointly with Radiology, so it belongs to two
# departments and is a periodical rather than a place in the org chart. Both
# fetched and confirmed.
PUBLICATIONS = {
    'labrad': 'LABRAD — newsletter of the Departments of Pathology & '
              'Laboratory Medicine and Radiology, Volume 50',
    'digital-magazine': 'Medical College Pakistan digital magazine',
}

# An office, a centre or a publication is never a department, nor are these, each
# checked on its own page: Undergraduate Programmes, the STEP project (2009-2016)
# and IED's Focus Areas.
NOT_DEPARTMENTS |= set(OFFICES) | set(CENTRES) | set(PUBLICATIONS)
NOT_DEPARTMENTS |= {'undergraduate', 'step', 'focus-areas'}
# Two more that own a CW/CA group and are not units. SIG is the Surgery Interest
# Group, "a student led body for mentoring & motivating aspiring surgeons" -- a
# student society, not a faculty department. HDP is the Human Development
# Programme, established 2003; AKU's own Departments menu lists it, but the page
# calls it a programme throughout, so decisions.py asks rather than guessing.
NOT_DEPARTMENTS |= {'sig', 'hdp'}
# And a fundraising campaign. mcpk/transform-lives invites donors to endow MBBS
# scholarships; its owner group is AF, which is Advancement, so it introduced a
# new owning unit and passed the department test on that alone. Every other
# mcpk sub-web WAS a real department -- all nine were opened to be sure.
NOT_DEPARTMENTS |= {'transform-lives'}

# Dated content is not confined to /events. A department runs an annual Research
# Day, a faculty publishes a magazine, an institute finishes a funded project --
# and each states its own latest edition on its own page. Without this, only the
# 44 event microsites could ever be flagged, and a 2021 Research Day would
# migrate as if it were current.
#
# web -> (latest edition the page names, what the page says)
DATED = {
    'mcpk/pathology/research-day': (
        2021, 'annual Research Day; the page offers abstract books for 2021 and '
              '2020 and nothing later'),
    'mcpk/digital-magazine': (
        2020, 'latest issue on the page is 2020'),
    'iedpk/step': (
        2016, 'Strengthening Teacher Education Programme, 2009-2016, funded by '
              'Global Affairs Canada and AKF Canada — a finished project'),
    'GNV': (
        None, 'four seasons of 13 episodes from 2016; the page calls the fourth '
              '"this dramatic final season", so the series has concluded'),
}

# Countries a sub-page states that its entity's own landing page does not. The
# entity-level tag in classification.py answers "where does this unit live"; this
# answers "where does this particular work happen", which is often wider.
WEB_COUNTRIES = {
    'iedea/dev-projects': (
        'Kenya, Uganda, Tanzania',
        'names 2 ongoing and 5 completed projects across all three countries'),
    'bmi/education': (
        '9 countries, 15 cities, 4 languages',
        'the page counts its own reach: "East Africa and beyond"'),
    'GNV/projects': (
        'Kenya, Uganda, Tanzania, Rwanda, Burundi, DR Congo',
        'filmmaking teams sourced from all six'),
    'coe-wch/impact': (
        'Pakistan, East Africa',
        'the impact section splits South & Central Asia from East Africa'),
    'crm/facilities': (
        'Pakistan',
        'four core facilities on the first floor of Juma Building, Karachi'),
    'careers/ovp': (
        'Pakistan, Kenya, Tanzania, Uganda, United Kingdom',
        'Overseas Volunteer Professionals places volunteers at any campus'),
    'ele-net/services': (
        'Pakistan, Kenya, Tanzania, Uganda, United Kingdom',
        'consultancy, bespoke courses and Aptis testing offered AKU-wide'),
}

# A name means different things to different faculties, so the exclusion has to be
# scoped. `med` is the Master of Education at IED and the Department of Medicine at
# the Medical College -- whose owner group is called "Dept of Medicine" outright.
# Excluding it everywhere let one faculty's degree programme suppress another
# faculty's clinical department. Listed as: this name is not a department, EXCEPT
# in these entities.
NOT_DEPARTMENTS_EXCEPT = {
    'med': {'medical-college'},
}
NOT_DEPARTMENTS |= set(NOT_DEPARTMENTS_EXCEPT)

def excluded(ent_slug, seg):
    """Is this name barred from being a department for THIS entity?"""
    s = slugify(seg)
    if s not in NOT_DEPARTMENTS:
        return False
    return ent_slug not in NOT_DEPARTMENTS_EXCEPT.get(s, set())

def learn_departments():
    for web in sorted(webs):
        if not web or '/' not in web:
            continue
        section = web.split('/')[0]
        if section not in SEC:
            continue
        region, ent_slug, ent_name, division, conf, prov = SEC[section]
        if not ent_slug or web.count('/') != 1:
            continue
        if is_department(section, web):
            DEPT_NAMES[ent_slug].add(slugify(web.split('/')[1]))

learn_departments()

def is_dept_name(ent_slug, seg):
    s = slugify(seg)
    if excluded(ent_slug, seg):
        return False
    return s in DEPT_NAMES.get(ent_slug, ()) or s in EXTRA_DEPARTMENTS.get(ent_slug, ())

# The third witness, and the plainest: AKU calls the thing a department on its
# own site. `is_department` needs the sub-web to have an owner group of its own,
# which is how a region that bothered to create one is recognised. Two units in
# the Medical College never got one and were filed as ordinary folders while
# their own SharePoint title read "Department of Oncology" and "Division of
# Woman & Child Health" -- and the breadcrumb on every page inside them says the
# same. A team that did not get its own CW/CA pair is still a department.
TITLED_DEPT = re.compile(r'^\s*(department|division|section)\b', re.I)

def titled_department(web):
    """Does this web's own title say it is one?"""
    t = (webs.get(web, {}).get('title') or [''])[0]
    return bool(TITLED_DEPT.match(t or ''))

# ---- destination path for a web -----------------------------------------
# The 17 pages at aku.edu/Pages/*.aspx -- home, contact, campuses, akdn, the
# legal set -- sit on the root web, which is not a section: SEC mirrors the
# permissions export's top-level sections and the root is not one of them. It is
# still witnessed like any other web. The export lists it as `http://aku.edu`,
# title "Home", scope Unique, owned by CW Public Affairs (13 rows) and CA Public
# Affairs (9) -- the same central-comms pair that witnesses /about. So it lands
# at the Global region folder itself, which is where content no faculty owns and
# no section contains already goes.
ROOT_DEST = 'regions/global'
ROOT_PROV = ('the aku.edu root web, which the permissions export lists as '
             'title "Home", scope Unique, owned by CW/CA Public Affairs — the '
             'central-comms pair that also witnesses /about. Not a section: '
             'these pages sit above every section, so they land at the Global '
             'region folder itself')

# Which root pages go somewhere other than Global lives in classification.py, so
# the hierarchy and the plan cannot disagree about it.


def dest_web(web):
    if web == page_intake.ROOT_WEB:
        return ROOT_DEST, 'region', 'global', '', '', W, ROOT_PROV
    segs = web.split('/')
    section = segs[0]
    region, ent_slug, ent_name, division, conf, prov = SEC[section]
    if region == 'staging':
        base = ['staging', slugify(section)]
        kind = 'section'
    elif region == 'global':
        # global is one of the regions, not a sibling of them: root > regions >
        # {global, pakistan, east-africa, ...}. It owns the content no faculty
        # owns -- including the six bodies AKU publishes as "Global Institutes &
        # Centres", which run across regions and belong to no single country.
        #
        # The entity test applies here exactly as it does to a region. It did not
        # for a while, and /vrw slipped through: "Voices from the Roof of the
        # World" is a four-country initiative with the University of Central
        # Asia, on neither /academics nor /research, and it was sitting in
        # regions/global/entities/ alongside the Brain & Mind Institute. Global
        # is a region like any other; a project inside it is a folder, not a
        # faculty.
        if ent_slug and entity_basis(ent_slug)[0]:
            base = ['regions', 'global', 'entities', ent_slug]
            kind = 'entity'
        elif ent_slug:
            base = ['regions', 'global', ent_slug]
            kind = 'region-folder'
        else:
            base = ['regions', 'global', slugify(section)]
            kind = 'section'
    else:
        base = ['regions', region]
        kind = 'region'
        if ent_slug:
            is_ent, _ = entity_basis(ent_slug)
            if is_ent:
                base += ['entities', ent_slug]
                kind = 'entity'
            else:
                # a real unit AKU does not publish as an academic unit or a global
                # institute — a region-level folder, not an entity
                base.append(ent_slug)
                kind = 'region-folder'
        if division:
            base.append(division)
            kind = 'division'
    for i, seg in enumerate(segs[1:]):
        if seg.lower() in LIBRARY_SEGS:
            continue
        sub = '/'.join(segs[:2 + i])
        if i == 0 and ent_slug and slugify(seg) in OFFICES:
            base.append(slugify(seg))
            kind = 'office'
        elif i == 0 and ent_slug and slugify(seg) in CENTRES:
            base.append(slugify(seg))
            kind = 'centre'
        elif ent_slug and slugify(seg) in PUBLICATIONS:
            # not depth-limited: LABRAD hangs off a department, the digital
            # magazine off the faculty, and both are the same kind of thing.
            base.append(slugify(seg))
            kind = 'publication'
        elif i == 0 and ent_slug and not excluded(ent_slug, seg) and (
                is_department(section, sub) or is_dept_name(ent_slug, seg)
                or titled_department(sub)):
            base += ['departments', slugify(seg)]
            kind = 'department'
        else:
            base.append(slugify(seg))
            kind = 'folder'
    # The entity column names the faculty or institute the folder sits inside.
    # A region-folder sits inside none — /cancer-centre, /ek-saath and /tele-icu
    # are real units that AKU does not publish as academic units, and their path
    # already says so. Reporting them in the entity column told a reader they
    # were faculties, and read as "Faculty / institute: ek-saath".
    ent_out = ent_slug if (ent_slug and entity_basis(ent_slug)[0]) else ''
    return '/'.join(base), kind, region, ent_out, ent_name or '', conf, prov

# ---- news, events and blogs are hubs, not folders per faculty ------------
# aku.edu/news is a top-level hub whose breadcrumb is "Home > News", and it
# filters by *Entity* and *Tag* -- AKU already runs this content in one place,
# segregated on display rather than by folder. So every faculty's own news /
# events / blog pages consolidate into the one hub and carry region, entity and
# department as tags. `moved_from` keeps it auditable.
HUB = {'news': 'news', 'events': 'events', 'event': 'events',
       'blogs': 'blogs', 'blog': 'blogs'}

def hub_of(dest):
    """The hub a folder's pages belong in, or None to leave them where they are."""
    segs = dest.split('/')
    for i, seg in enumerate(segs):
        h = HUB.get(seg)
        if not h:
            continue
        # the hub itself is regions/global/<h>; anything else is a faculty copy
        if segs[:3] == ['regions', 'global', h] and i == 2:
            return None
        return h
    return None

# Each faculty kept its own events landing page and its own event-detail
# template. One hub needs one of each, so 15 copies of `home` and 8 of
# `event-detail` are superseded rather than migrated -- they were plumbing, not
# content. Anything with a real title still moves.
HUB_TEMPLATES = {'home', 'default', 'index', 'detail', 'event-detail',
                 'events-detail', 'blog-detail', 'blogs-detail', 'news-detail'}

def content_type_of(dest):
    for seg in dest.split('/'):
        if seg in HUB:
            return {'news': 'news', 'events': 'event', 'event': 'event',
                    'blogs': 'blog', 'blog': 'blog'}[seg]
    return 'page'

# ---- pages from AKU's own list ------------------------------------------
# One inventory, read by page_intake: AKU's filtered export, 4,591 pages. The
# root web's pages have section None -- placed by dest_web, not by SEC -- so they
# are not held against the classification.
pages = page_intake.load()

unknown = sorted({p['section'] for p in pages
                  if p['section'] is not None and p['section'] not in SEC})
if unknown:
    raise SystemExit('pages reference unclassified sections: %s' % unknown)

# Pages AKU's earlier list carried and this one does not. Reported, never
# silently dropped -- a page leaving the corpus between two builds is the one
# loss this pipeline exists to make impossible.
DROPPED = page_intake.dropped(pages)

# The team each page names on itself. Used only where the permissions export
# names none for the web -- see page_owners for why it never overrules it.
PAGE_OWNER = page_owners.owners()

pages_by_web = collections.defaultdict(list)
for p in pages:
    pages_by_web[p['web']].append(p)

# every web that must exist: from the permissions export plus any web a page needs
all_webs = set(w for w in webs if w) | set(pages_by_web)

# ---- cross-entity: the owner names an entity the folder does not sit under --
# global/library/ea/gsmc is managed by the GSMC team but lives under the Library,
# so its entity column is empty and "everything belonging to GSMC" would miss it.
# The owning team is the evidence: whichever entity's section that team also owns
# is an entity this folder belongs to, even though it cannot live there.
UNIT_ENTITY = {}
for _sec, (_reg, _ent, _en, _div, _c, _p) in SEC.items():
    if not _ent:
        continue
    for g in owned.get(_sec, []):
        UNIT_ENTITY.setdefault(GUNIT[g], (_reg, _ent))

# The library branches are owned by library sub-teams ("EA Lib", "IED Lib"), not
# by the faculty they serve, so the owner test alone misses them. Their folder
# name carries it instead: library/ea/gsmc is GSMC's library. Only unambiguous
# abbreviations, anchored to a whole segment, so no accidental matches.
ABBREV_ENTITY = {
    'gsmc': 'graduate-school-of-media-and-communications',
    'ied': 'institute-for-educational-development',
    'fas': 'faculty-of-arts-and-sciences',
    'ismc': 'institute-for-the-study-of-muslim-civilisations',
    'sonam': 'school-of-nursing-and-midwifery',
    'bmi': 'brain-and-mind-institute',
    'cime': 'centre-for-innovation-in-medical-education',
    'crm': 'centre-for-regenerative-medicine',
    'ihd': 'institute-for-human-development',
    'ighd': 'institute-for-global-health-and-development',
}

def cross_entity(web, dest):
    out = []
    for g in owned.get(web, []):
        hit = UNIT_ENTITY.get(GUNIT[g])
        if hit and ('/entities/%s' % hit[1]) not in dest and hit[1] not in dest:
            out.append('%s (%s)' % (hit[1], hit[0]))
    for seg in dest.split('/'):
        head = seg.split('-')[0]
        ent = ABBREV_ENTITY.get(head)
        if ent and ('/entities/%s' % ent) not in dest:
            out.append('%s (named in the folder)' % ent)
    return '; '.join(sorted(set(out)))

# ---- folder rows --------------------------------------------------------
# Two source webs can legitimately land on one destination: library/pk/fhs and
# library/pk/fhs/SitePages are the same web, one of them being SharePoint's own
# page library. Merge those rather than emitting the folder twice.
folder_rows = []
dest_by_web = {}
webs_by_dest = collections.OrderedDict()
for web in sorted(all_webs):
    dest, kind, region, ent, ent_name, conf, prov = dest_web(web)
    dest_by_web[web] = dest
    webs_by_dest.setdefault(dest, []).append(web)

def dated_of(srcs):
    """(latest edition, why it is an archive candidate) for a folder, from any of
    its source webs. Events keep their own table; DATED covers everywhere else."""
    for w in srcs:
        leafseg = w.split('/')[-1]
        if w.startswith('events/') and leafseg in EVENT_OWNERS:
            yr = EVENT_OWNERS[leafseg][2]
            arch = ('yes — last ran %s' % yr) if leafseg in stale_events() else ''
            return (str(yr) if yr else ''), arch
        if w in DATED:
            yr, note = DATED[w]
            arch = ('yes — %s' % note) if yr is None or yr < STALE_BEFORE else ''
            return (str(yr) if yr else ''), arch
    return '', ''

def countries_of(srcs, section):
    """What the page itself claims, in preference to what its entity claims."""
    for w in srcs:
        if w in WEB_COUNTRIES:
            return WEB_COUNTRIES[w][0]
    return ENTITY_COUNTRIES.get(section, ('', ''))[0]

for dest, srcs in webs_by_dest.items():
    web = srcs[0]
    _, kind, region, ent, ent_name, conf, prov = dest_web(web)
    last_ran, archive = dated_of(srcs)
    src, units = nearest_owner(web)
    own_here = any(w in owned for w in srcs)
    subtree = sum(len(pages_by_web.get(w, [])) for w in all_webs
                  if any(w == s or w.startswith(s + '/') for s in srcs))
    folder_rows.append({
        'new_path': dest,
        'parent_path': dest.rsplit('/', 1)[0] if '/' in dest else '',
        'level': dest.count('/') + 1,
        'kind': kind,
        'region': region,
        'region_code': REGION_CODE[region],
        'entity': ent,
        'source_web': '; '.join(s or '(site root)' for s in srcs),
        # A region folder keeps the region's own name. The root web is the only
        # source web that lands on one, and SharePoint titles it "Home" — the
        # homepage's name, not a name for the Global region.
        'title': REGION_NAME[region] if kind == 'region' and dest == 'regions/' + region
                 else (webs.get(web, {}).get('title') or [''])[0],
        'pages_here': sum(len(pages_by_web.get(s, [])) for s in srcs),
        'pages_subtree': subtree,
        'managed_by': '; '.join(units) if units else 'Public Affairs (central)',
        'countries': countries_of(srcs, web.split('/')[0]),
        'entity_basis': (entity_basis(ent)[1] if ent else ''),
        'also_belongs_to': '; '.join(sorted({x for w in srcs
                                             for x in cross_entity(w, dest).split('; ')
                                             if x})),
        'event_owner': EVENT_OWNERS.get(web.split('/')[-1], ('', '', '', ''))[0]
                       if web.startswith('events/') else '',
        'last_ran': last_ran,
        'archive_candidate': archive,
        'permission_source': src if src is not None else 'inherited from parent',
        'own_permissions': 'yes' if own_here else 'no',
        'confidence': conf,
        'provenance': prov,
    })

# Storyblok cannot create a folder whose parent does not exist, and several
# levels in the destination shape have no source web at all -- `regions`, the
# per-region `entities` container, each `departments` container, and the region
# folders for regions whose sections are all entity-owned. Synthesise them, or
# the plan is not executable.
CONTAINER_NOTE = {
    'regions': 'container for the six regions',
    'entities': 'container for one region’s entities',
    'departments': 'container for one entity’s departments',
}
have = {r['new_path'] for r in folder_rows}
needed = set()
for r in folder_rows:
    parts = r['new_path'].split('/')
    for i in range(1, len(parts)):
        needed.add('/'.join(parts[:i]))
for path in sorted(needed - have):
    last = path.split('/')[-1]
    reg = path.split('/')[1] if path.startswith('regions/') and path.count('/') >= 1 \
        else ('global' if path == 'global' else 'staging' if path == 'staging' else '')
    reg = reg if reg in REGION_CODE else ''
    folder_rows.append({
        'new_path': path,
        'parent_path': path.rsplit('/', 1)[0] if '/' in path else '',
        'level': path.count('/') + 1,
        'kind': 'container' if last in CONTAINER_NOTE else
                'root' if '/' not in path else
                'region' if path.startswith('regions/') and path.count('/') == 1
                else 'entity' if '/entities/' in path else 'folder',
        'region': reg, 'region_code': REGION_CODE.get(reg, ''),
        'entity': path.split('/entities/')[1].split('/')[0]
                  if '/entities/' in path else '',
        'title': REGION_NAME.get(last.replace('-', ' ').title().lower(), '') or
                 last.replace('-', ' ').title(),
        'source_web': '(created — no source folder)',
        'pages_here': 0, 'pages_subtree': 0,
        'managed_by': 'Public Affairs (central)',
        'countries': '',
        'entity_basis': '',
        'also_belongs_to': '',
        'event_owner': '',
        'last_ran': '',
        'archive_candidate': '',
        'permission_source': 'inherited from parent',
        'own_permissions': 'no',
        'confidence': W,
        'provenance': CONTAINER_NOTE.get(last, 'structural level with no source '
                                               'folder on aku.edu'),
    })
    have.add(path)

# ---- page rows ----------------------------------------------------------
page_rows = []
for p in sorted(pages, key=lambda x: x['url'].lower()):
    web = p['web']
    dest = dest_by_web.get(web)
    if dest is None:                       # a page under a folder no export lists
        parent = web
        while parent and parent not in dest_by_web:
            parent = parent.rsplit('/', 1)[0] if '/' in parent else ''
        dest = dest_by_web.get(parent, 'global') + '/' + slugify(web.split('/')[-1])
    section = p['section']
    leaf = slugify(p['file'])
    if section is None:                    # the root web — placed by dest_web
        region, ent_slug, ent_name, division, conf = 'global', None, None, None, W
        # A root page AKU files under a region goes there instead, under the slug
        # the override names — east-africa.aspx becomes that region's `home`, so
        # it sits where the other five regions' landing pages already do.
        override = ROOT_PAGE_DEST.get(p['file'].lower())
        if override:
            dest, region, leaf, _why = override
    else:
        region, ent_slug, ent_name, division, conf, prov = SEC[section]
    # Same test the folder uses: a page in /cancer-centre belongs to no faculty,
    # because AKU does not publish one there.
    if ent_slug and not entity_basis(ent_slug)[0]:
        ent_slug = None
    src, units = nearest_owner(web)
    mine = PAGE_OWNER.get(page_intake.key(p['url']), [])
    dept = ''
    m = re.search(r'/departments/([^/]+)', dest)
    if m:
        dept = m.group(1)
    hub = hub_of(dest)
    ctype = content_type_of(dest)
    home = dest
    moved_from = ''
    superseded = ''
    if hub:
        home = 'regions/global/' + hub
        moved_from = dest
        if slugify(p['file']) in HUB_TEMPLATES:
            superseded = ('the %s hub needs one listing page and one detail '
                          'template, not one per faculty — this copy is '
                          'superseded' % hub)
    page_rows.append({
        'current_url': p['url'],
        'action': p['action'],
        'review_status': p['status'],
        'new_in_export': 'new' if p['new'] else '',
        'new_path': home + '/' + leaf,
        'new_url': public_url(home + '/' + leaf),
        'content_type': ctype,
        'moved_from': moved_from,
        'region': region,
        'region_code': REGION_CODE[region],
        'entity': ent_slug or '',
        'department': dept,
        'folder': home,
        'page_owner': '; '.join(mine),
        # The export first. Only where it names nobody for this web does the
        # page's own CW/CA group stand in -- 523 pages that are not central
        # comms's work and were being recorded as though they were.
        'managed_by': '; '.join(units) if units
                      else ('; '.join(mine) if mine else 'Public Affairs (central)'),
        'managed_by_source': 'permissions export' if units
                             else ('page CW/CA' if mine else 'fallback — nobody named'),
        'countries': ENTITY_COUNTRIES.get(section, ('', ''))[0],
        'confidence': conf,
        'collision': '',
        'do_not_migrate': DO_NOT_MIGRATE.get(p['url'], '') or superseded,
    })

# ---- one landing page per folder ----------------------------------------
# Storyblok has no separate notion of a folder: a folder IS a story, so a folder
# and a page cannot share a slug under one parent. AKU's site breaks that in two
# ways at once, and neither was caught before, because the collision check above
# compares a page against another PAGE and never against a folder:
#
#   1. a page named for a folder that already exists — `mcpk/Pages/departments.aspx`
#      wants the exact path of the folder holding 544 department pages;
#   2. a folder with two landing pages — its own `home.aspx` and a `default.aspx`,
#      or a `home.aspx` in the sub-web plus a same-named page one level up. Both
#      want the folder's bare address once a trailing `home` is stripped.
#
# 10 folders hit the first, 17 the second. AKU's instruction is that nothing is
# dropped, so this does not choose one page and discard the other: the winner
# becomes the folder's landing page at `<folder>/home` and the loser keeps its
# content at `<folder>/<leaf>-archive`, with a remark saying which superseded it.
#
# Which one wins is MEASURED, not assumed. The obvious rule — "the page inside
# the sub-web is the canonical one" — is wrong 4 times in 10: `mcpk/bbs/Pages/
# Research.aspx` was edited in December 2025 while the sub-web's own home page
# has not been touched since June 2016. The ranking below is the evidence, in
# the order it is worth trusting.
FOLDER_PATHS = {r['new_path'] for r in folder_rows}

# SharePoint's own record of each page: when it was last edited, and which
# version it reached. A version below 1.0 has never been published — the CHS
# educational-programmes page is at 0.29 and returns 401, so it is a draft
# somebody abandoned, not the section's front door.
SP_META = {}
try:
    with open(paths.data('SPPagesAKU-Metadata.csv'), encoding='utf-8-sig') as fh:
        for _r in csv.DictReader(fh):
            _u = page_intake.key(_r.get('Original Page URL') or '')
            if not _u:
                continue
            try:
                _v = float(_r.get('Version') or 0)
            except ValueError:
                _v = 0.0
            SP_META[_u] = (_r.get('Modified Date', ''), _v)
except FileNotFoundError:
    pass

# What the live site returns. Optional on purpose: verify_live.py runs AFTER
# this step, so a first build on a fresh clone has no such file and must still
# produce a plan. Where it is missing the ranking falls back to the SharePoint
# metadata, which is a real input in data/ and always present.
LIVE_HTTP = {}
try:
    with open(paths.out('aku-live-page-verification.csv'), encoding='utf-8-sig') as fh:
        for _r in csv.DictReader(fh):
            LIVE_HTTP[page_intake.key(_r['current_url'])] = _r.get('http', '')
except FileNotFoundError:
    pass


def _mdy(s):
    """SharePoint writes 7/9/2024 1:02 PM. Sort on the date, not the string."""
    m = re.match(r'\s*(\d{1,2})/(\d{1,2})/(\d{4})', s or '')
    return (int(m.group(3)), int(m.group(1)), int(m.group(2))) if m else (0, 0, 0)


def landing_rank(row):
    """How strongly this page claims to be its folder's front door. Higher wins.

    Read top to bottom: a page the server will not serve cannot be a front
    door whatever its dates say; a draft that never reached 1.0 is not one
    either; after that the most recently edited page is the live one.
    """
    k = page_intake.key(row['current_url'])
    http = LIVE_HTTP.get(k, '')
    modified, version = SP_META.get(k, ('', 0.0))
    return (1 if http == '200' else 0,          # the server serves it
            0 if http in ('401', '404') else 1,  # ... and does not refuse it
            1 if version >= 1.0 else 0,          # published, not an abandoned draft
            _mdy(modified),                      # most recently edited
            version,
            row['current_url'].lower())          # a tie must not depend on dict order


def _archive_leaf(row, taken):
    """`research` -> `research-archive`, and `-archive-2` only if that is taken."""
    leaf = row['new_path'].rsplit('/', 1)[1]
    base = leaf + '-archive'
    cand, n = base, 2
    while cand in taken:
        cand, n = '%s-%d' % (base, n), n + 1
    return cand


live_rows = [r for r in page_rows if not r['do_not_migrate']]
by_folder = collections.defaultdict(list)
for r in live_rows:
    by_folder[r['new_path'].rsplit('/', 1)[0]].append(r)

landings = 0
for folder in sorted(FOLDER_PATHS):
    inside = by_folder.get(folder, [])
    # Every page that wants this folder's bare address: the ones already named
    # `home` or `default` inside it, and any page whose own path IS the folder.
    rivals = [r for r in inside
              if r['new_path'].rsplit('/', 1)[1] in ('home', 'default')]
    rivals += [r for r in live_rows if r['new_path'] == folder]
    if len(rivals) < 2 and not any(r['new_path'] == folder for r in rivals):
        continue
    rivals.sort(key=landing_rank, reverse=True)
    winner, losers = rivals[0], rivals[1:]
    taken = {r['new_path'].rsplit('/', 1)[1] for r in inside} | {'home'}
    for r in losers:
        leaf = _archive_leaf(r, taken)
        taken.add(leaf)
        r['new_path'] = folder + '/' + leaf
        # The folder column has to move with the page. It was set from the page's
        # ORIGINAL destination, and leaving it behind put 10 pages a level away
        # from the folder claiming them -- which is also what the per-folder page
        # counts are rolled up from.
        r['folder'] = folder
        r['collision'] = ('superseded as the front door of %s by %s — kept, '
                          'not dropped' % (folder, winner['current_url']))
        landings += 1
    if winner['new_path'] != folder + '/home':
        winner['collision'] = ('the front door of %s, chosen over %s'
                               % (folder, '; '.join(r['current_url'] for r in losers))
                               if losers else '')
        winner['new_path'] = folder + '/home'
        winner['folder'] = folder
        landings += 1
for r in live_rows:
    r['new_url'] = public_url(r['new_path'])
print('landing pages resolved: %d rows moved' % landings)

# Two source pages can slugify to one destination -- AKU has both
# crm/about/executive-committee.aspx and executive.committee.aspx, and both a
# Pages/home.aspx and a SitePages/Home.aspx under library/pk/fhs. Suffixing the
# later one keeps both rows visible; overwriting would lose a page silently.
seen = {}
collisions = 0
# Whoever is resolved first keeps the clean address, so the order is not a
# detail. Sorted by URL, `mcea/departments/…/home.aspx` came before
# `mcea/Pages/home.aspx` because "d" precedes "p", and the faculty's own landing
# page was pushed to `home-2` by one of its sub-folders. The page nearer the top
# of the section is the more canonical one and takes the address; ties break on
# the URL so the result does not depend on dictionary order.
def _canonical_first(r):
    return (page_intake.web_of(r['current_url']).count('/'),
            r['current_url'].lower())

for r in sorted(page_rows, key=_canonical_first):
    if r['do_not_migrate']:
        # resolved against the live site: it never lands, so it takes no path and
        # cannot collide with the page that replaces it. The address goes with the
        # path -- leaving it behind published an address for a page that will not
        # exist, and put 39 of them on addresses another page is taking.
        r['new_path'] = ''
        r['new_url'] = ''
        continue
    # Uniqueness is a property of the ADDRESS, not of the CMS path. `regions/`,
    # `entities/` and `departments/` are scaffolding a reader never sees, so two
    # distinct paths can be one address — and AKU has a real web called
    # `departments`, which makes that concrete:
    #
    #   mcea/departments/Pages/message-from-the-chair.aspx
    #       -> …/medical-college/departments/message-from-the-chair
    #   mcea/Pages/message-from-the-chair.aspx
    #       -> …/medical-college/message-from-the-chair
    #
    # Different folders, different paths, and one address once the scaffold is
    # stripped. Checking the path found nothing; the reader would have found it.
    base = r['new_path']
    url = public_url(base)
    if url in seen:
        collisions += 1
        n = 2
        while public_url('%s-%d' % (base, n)) in seen:
            n += 1
        r['new_path'] = '%s-%d' % (base, n)
        r['collision'] = 'same address as %s — AKU has two source pages, pick one' \
                         % seen[url]
        # Mark the page that got there first as well, by the URL it claimed:
        # once the clash is between two DIFFERENT paths that flatten to one
        # address, matching on the path finds nobody and only one side of the
        # pair is flagged. AKU has to see both to choose between them.
        for other in page_rows:
            if other['current_url'] == seen[url]:
                other['collision'] = ('same address as %s — AKU has two source '
                                      'pages, pick one' % r['current_url'])
    r['new_url'] = public_url(r['new_path'])
    seen[r['new_url']] = r['current_url']

# No two pages may end up at one address. new_path was already unique; new_url
# was not, and nothing checked.
_urls = collections.Counter(r['new_url'] for r in page_rows if r['new_url'])
_clash = {u: n for u, n in _urls.items() if n > 1}
if _clash:
    raise SystemExit('two pages share one address: %s'
                     % '; '.join('%s (%d)' % (u, n) for u, n in list(_clash.items())[:5]))

# ---- a page with no owner inherits its FACULTY, not central comms -------
# 351 pages had nobody named: the permissions export lists no owner group for
# their web, and the page carries no CW/CA of its own. They all fell back to
# "Public Affairs (central)", which reads as a decision and is not one.
#
# Walking the folder tree for a better answer looks obvious and is a trap. Every
# ancestor of these pages is ALSO unowned, and the first named one is
# `regions/global` — owned by the Registrar, because that is what the aku.edu
# ROOT web's permission rows say. Inheriting that would have handed the
# Registrar all 2,300 global pages, including News and Blogs.
#
# So the rule stops at the faculty. 105 of the 351 sit inside a real entity
# folder — the Graduate School of Media & Communications alone has 36, and
# SONAM Uganda 50 — and a faculty owns what is published under its own name
# whether or not SharePoint ever recorded a group for it. The other 246 are
# global hubs, About AKU, event microsites and procurement, where central comms
# genuinely is the answer and stays.
FOLDER_BY_PATH = {r['new_path']: r for r in folder_rows}


def nearest_entity(path):
    parts = path.split('/')
    for i in range(len(parts), 0, -1):
        f = FOLDER_BY_PATH.get('/'.join(parts[:i]))
        if f and f['kind'] == 'entity':
            return f
    return None


adopted = 0
for r in page_rows:
    if not r['managed_by_source'].startswith('fallback'):
        continue
    f = nearest_entity(r['folder'])
    if not f:
        continue
    r['managed_by'] = f['title']
    r['managed_by_source'] = ('the faculty it sits under — the export names no '
                              'owner group for that faculty')
    adopted += 1
print('pages given their faculty as owner where nobody was named: %d' % adopted)

# ---- how many pages each folder really holds ----------------------------
# Both counts were derived from the source webs, before the pages were placed,
# and neither survived what happens after: a page consolidated into a global hub
# is counted at the faculty folder it left, and a folder this build synthesises
# — `regions`, each `entities` container, every region — has no source web at
# all and so counted nothing. `regions` reported 0 pages with 4,591 beneath it,
# and `regions/global` reported 17 against 2,389.
#
# They are recomputed here from where the pages actually landed, which is the
# only thing either column ever claimed to say, and rolled up the destination
# tree so a parent includes its children.
_here = collections.Counter(r['folder'] for r in page_rows)
_sub = collections.Counter()
for _path, _n in _here.items():
    _parts = _path.split('/')
    for _i in range(len(_parts)):
        _sub['/'.join(_parts[:_i + 1])] += _n
for r in folder_rows:
    r['pages_here'] = _here.get(r['new_path'], 0)
    r['pages_subtree'] = _sub.get(r['new_path'], 0)

_root = sum(r['pages_here'] for r in folder_rows)
if _root != len(page_rows):
    raise SystemExit('page counts do not add up: folders hold %d, there are %d pages'
                     % (_root, len(page_rows)))

# ---- Storyblok roles ----------------------------------------------------
# One role per unit per capability, scoped to the folders that unit owns. That
# mirrors the teams AKU already has, so membership needs no re-litigating.
unit_folders = collections.defaultdict(set)
for web, gs in owned.items():
    for g in gs:
        unit_folders[GUNIT[g]].add(dest_by_web.get(web, ''))

unit_groups = collections.defaultdict(lambda: {'writer': [], 'approver': []})
for g, k in GKIND.items():
    if k in ('writer', 'approver') and GUNIT.get(g):
        unit_groups[GUNIT[g]][k].append(g)

role_rows = []
for u in sorted(unit_groups):
    unit_paths = sorted(x for x in unit_folders.get(u, set()) if x)
    for k, cap in (('writer', 'editor'), ('approver', 'publisher')):
        gs = unit_groups[u][k]
        if not gs:
            continue
        people = sum(GPEOPLE.get(g, 0) for g in gs)
        role_rows.append({
            'storyblok_role': '%s-%s' % (slugify(u), cap),
            'capability': cap,
            'can_publish': 'yes' if cap == 'publisher' else 'no',
            'unit': u,
            'source_sharepoint_groups': '; '.join(sorted(gs)),
            'members': people,
            'folders_scoped': len(unit_paths),
            'allowed_paths': '; '.join(unit_paths[:6]) + (' …' if len(unit_paths) > 6 else ''),
            'note': '' if unit_paths else
                    'owns no folder at unique scope — its section inherits the '
                    'site-wide roster, so scope must be set by hand',
        })

# space-wide roles, from the groups that are not unit-scoped
SPACE = [('space-admin', 'admin',
          ['AKU Owners', 'Administrators', 'IT Webteam'],
          'Full Control / Manage Permissions on the site collection'),
         ('structure-manager', 'structure', ['Hierarchy Managers'],
          'Manage Hierarchy — may create, move and delete folders'),
         ('translator', 'translator', ['Translation Managers'],
          'Restricted Interfaces for Translation — field-level translation only'),
         ('viewer', 'viewer', ['AKU Visitors', 'Viewers', 'Restricted Readers',
                               'Style Resource Readers'],
          'Read / View Only / Restricted Read'),
         ('comment-moderator', 'moderator', ['Comments Moderator'],
          'moderates comments only'),
         ('central-comms-editor', 'editor', ['CW Public Affairs'],
          'the university-wide writer group; edits anywhere it is scoped'),
         ('central-comms-publisher', 'publisher', ['CA Public Affairs'],
          'the university-wide approver group; publishes anywhere it is scoped')]
for name, cap, gs, why in SPACE:
    present = [g for g in gs if g in GPEOPLE]
    role_rows.append({
        'storyblok_role': name, 'capability': cap,
        'can_publish': 'yes' if cap in ('publisher', 'admin') else 'no',
        'unit': '(space-wide)',
        'source_sharepoint_groups': '; '.join(present),
        'members': sum(GPEOPLE.get(g, 0) for g in present),
        'folders_scoped': 0, 'allowed_paths': 'whole space', 'note': why,
    })

# ---- what the live pages settled ---------------------------------------
# Cross-entity questions the two exports could not answer were resolved by
# fetching the page and reading the breadcrumb AKU itself renders. The breadcrumb
# is the canonical parent: the site is stating where it thinks the page lives.
# The full live-site sweep lives in site_visits.py so it stays a checklist
# rather than a buried literal; REMAINING there names what is still unopened.
from site_visits import VISITED

LIVE_CHECKS = [(u.lstrip("/"), showed, settled)
               for u, showed, settled, _changed in VISITED]

live_rows = [{'page_checked': 'https://www.aku.edu/' + u,
              'what_aku_shows': b, 'what_it_settles': s}
             for u, b, s in LIVE_CHECKS]

# ---- who can do what, in each folder ------------------------------------
# Storyblok wording, from the SharePoint capability: an editor creates and edits
# but cannot publish; a publisher can also publish; only admin and the structure
# manager add or remove folders. Anyone scoped can read.
ROLES_BY_UNIT = collections.defaultdict(list)
for r in role_rows:
    ROLES_BY_UNIT[r['unit']].append(r)

for fr in folder_rows:
    units = [u.strip() for u in fr['managed_by'].split(';')]
    if 'central' in fr['managed_by']:
        units = ['(space-wide)']
    ed, pub = [], []
    for u in units:
        for r in ROLES_BY_UNIT.get(u, []):
            if r['capability'] == 'editor':
                ed.append(r['storyblok_role'])
            elif r['capability'] == 'publisher':
                pub.append(r['storyblok_role'])
    fr['can_create_and_edit'] = '; '.join(sorted(set(ed + pub))) or 'central-comms-editor'
    fr['can_publish'] = '; '.join(sorted(set(pub))) or 'central-comms-publisher'
    fr['can_add_or_delete_folders'] = 'space-admin; structure-manager'
    fr['can_read_only'] = 'viewer'

# ---- write the CSVs ----------------------------------------------------
def write_csv(name, rows, cols):
    p = paths.out(name)
    with open(p, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    return p

FOLD_COLS = ['new_path', 'parent_path', 'level', 'kind', 'region', 'region_code',
             'entity', 'title', 'source_web', 'pages_here', 'pages_subtree',
             'managed_by', 'can_create_and_edit', 'can_publish',
             'can_add_or_delete_folders', 'can_read_only', 'countries',
             'entity_basis', 'also_belongs_to', 'event_owner', 'last_ran',
             'archive_candidate', 'own_permissions', 'permission_source',
             'confidence', 'provenance']
PAGE_COLS = ['current_url', 'new_url', 'new_path', 'content_type', 'action',
             'review_status', 'new_in_export', 'region', 'region_code', 'entity',
             'department', 'folder', 'moved_from', 'managed_by',
             'managed_by_source', 'page_owner', 'countries', 'confidence',
             'collision', 'do_not_migrate']
ROLE_COLS = ['storyblok_role', 'capability', 'can_publish', 'unit', 'members',
             'folders_scoped', 'source_sharepoint_groups', 'allowed_paths', 'note']

# What every column means, in the words a reviewer needs rather than the words the
# code uses. It lives here because this file decides the columns, and it ships in
# plan.json so the single-file portal and the React app describe the CSVs from one
# source instead of two hand-kept copies that drift apart. The check below is the
# point of putting it here: add a column above without describing it, or describe
# one that no longer exists, and the build stops.
COL_DOCS = {
    'folders': {
        'new_path': 'Where the folder goes in Storyblok. Lowercase-hyphenated, full '
                    'names, never abbreviations.',
        'parent_path': 'The folder directly above it. Empty for the two roots.',
        'level': 'Depth, counting the root as 1.',
        'kind': 'region, entity, department, region-folder, centre, division, section, '
                'folder or container. Only entity, department and region change the '
                'shape of the path.',
        'region': 'Which of the regions owns it. "global" means no faculty does.',
        'region_code': 'AKU’s two-letter code. Metadata for display — never a path '
                       'segment.',
        'entity': 'The faculty, school or institute it sits under, if any.',
        'title': 'The human name SharePoint already carries for the slug, shown beside '
                 'it everywhere so nothing needs renaming.',
        'source_web': 'The SharePoint web the row came from, or "(created — no source '
                      'folder)" for a level that is new.',
        'pages_here': 'Pages landing directly in this folder.',
        'pages_subtree': 'Pages in it and everything under it — what you judge a '
                         'folder’s weight by.',
        'managed_by': 'The unit that manages it, resolved through inheritance.',
        'can_create_and_edit': 'Storyblok roles that may write drafts here.',
        'can_publish': 'Roles that may publish. The CA half of AKU’s CW/CA pair.',
        'can_add_or_delete_folders': 'Roles that may change the structure — space-admin '
                                     'and structure-manager only.',
        'can_read_only': 'Roles with view access and nothing more.',
        'countries': 'For an East-Africa-wide or global unit, the countries its own page '
                     'names. A tag, because one folder cannot sit in three countries.',
        'entity_basis': 'Which AKU list made it an entity — aku.edu/academics, '
                        'aku.edu/research, or neither.',
        'also_belongs_to': 'The entity it belongs to but cannot live under: a library '
                           'branch owned by a faculty, a conference owned by an institute.',
        'event_owner': 'For an event microsite, the owning unit as the event’s own page '
                       'names it — its SharePoint group is named after the event, so it '
                       'cannot say.',
        'last_ran': 'The most recent edition an event page names.',
        'archive_candidate': 'Set when that edition is old enough that the folder is '
                             'probably archive, not content to carry forward.',
        'own_permissions': 'yes when the folder sets its own rights; no when it inherits '
                           'them from above.',
        'permission_source': 'The folder the rights actually come from — itself, or the '
                             'nearest ancestor that sets any.',
        'confidence': 'witnessed when the export or the live page proves the placement, '
                      'inferred when only a naming convention supports it, decide when '
                      'AKU has to answer.',
        'provenance': 'The rule that produced the row, in words. This is the column to '
                      'argue with.',
    },
    'pages': {
        'current_url': 'The live SharePoint URL today, including /Pages/….aspx.',
        'new_url': 'The public address after migration.',
        'new_path': 'The Storyblok path, CMS scaffolding included. Empty means the page '
                    'does not migrate.',
        'content_type': 'page, news, event or blog. The last three live in the global '
                        'hubs and carry their unit as tags.',
        'action': 'AKU’s own call from their CSV: "Move as is" or "Update and move".',
        'review_status': 'AKU’s FinalStatus from the same export — MIGRATE, NOT_REVIEWED '
                         'or UNCLEAR. Where the page belongs is settled either way; this '
                         'says whether AKU has finished looking at it.',
        'new_in_export': '"new" when AKU’s filtered export lists the page and their '
                         'earlier one did not — the 1,323 additions. Filter on it to '
                         'review only what changed; blank means the page was in both.',
        'region': 'Region of the folder it lands in.',
        'region_code': 'Two-letter code, metadata only.',
        'entity': 'Entity of the folder it lands in, if any.',
        'department': 'Department, when the permissions export proves one owns it.',
        'folder': 'new_path of its destination folder — the join key back to the folder '
                  'map.',
        'moved_from': 'Set when the page was pulled out of a faculty’s own folder into a '
                      'global hub. Its old home, for the redirect.',
        'managed_by': 'The unit that will manage it once moved.',
        'managed_by_source': 'Which witness named that unit — the permissions export '
                             '(a grant on its web), or the page’s own CW/CA group where '
                             'the export names nobody. "fallback" means neither did.',
        'page_owner': 'The content writer / approver groups set on the page itself, from '
                      'AKU’s metadata export. Shown for every page that has them, even '
                      'where managed_by came from the export, so the two can be compared.',
        'countries': 'Inherited from the folder, for a unit that works across several.',
        'confidence': 'Same three values as the folder map.',
        'collision': 'Two source pages want the same slug. Surfaced, not silently '
                     'resolved — AKU picks one.',
        'do_not_migrate': 'Why it does not move, in the words of what the server '
                          'actually returned when the page was fetched.',
    },
    'roles': {
        'storyblok_role': 'The role to create. Named for the unit, then the capability.',
        'capability': 'editor or publisher, plus the space-wide roles.',
        'can_publish': 'The one line that separates a CW group from a CA group.',
        'unit': 'The unit it belongs to, or "(space-wide)".',
        'members': 'How many named people are in the source group today.',
        'folders_scoped': 'How many folders the role reaches.',
        'source_sharepoint_groups': 'The SharePoint group or groups it was derived from. '
                                    'This is where you spot-check a role.',
        'allowed_paths': 'The paths it may write to. Permissions are hierarchical, so '
                         'everything below a path is included.',
        'note': 'Anything about the role a reviewer would otherwise have to ask about.',
    },
}
for _which, _cols in (('folders', FOLD_COLS), ('pages', PAGE_COLS),
                      ('roles', ROLE_COLS)):
    _undescribed = [c for c in _cols if c not in COL_DOCS[_which]]
    _unknown = [c for c in COL_DOCS[_which] if c not in _cols]
    if _undescribed or _unknown:
        raise SystemExit('COL_DOCS[%r] is out of step with the CSV — undescribed: %s; '
                         'no such column: %s'
                         % (_which, _undescribed or 'none', _unknown or 'none'))
# Emitted as ordered pairs, not a dict, so the portal lists the columns in the
# order the file writes them.
COLUMNS = {w: [[c, COL_DOCS[w][c]] for c in cols]
           for w, cols in (('folders', FOLD_COLS), ('pages', PAGE_COLS),
                           ('roles', ROLE_COLS))}

folder_rows.sort(key=lambda r: r['new_path'])
role_rows.sort(key=lambda r: (r['unit'] == '(space-wide)', r['storyblok_role']))
write_csv('aku-folder-map.csv', folder_rows, FOLD_COLS)
write_csv('aku-page-map.csv', page_rows, PAGE_COLS)
write_csv('aku-permission-groups.csv', role_rows, ROLE_COLS)
write_csv('aku-live-page-checks.csv', live_rows,
          ['page_checked', 'what_aku_shows', 'what_it_settles'])

print('folders %d | pages %d | roles %d' % (len(folder_rows), len(page_rows),
                                           len(role_rows)))
print('slug collisions surfaced:', collisions)
_mv = [r for r in page_rows if r['moved_from']]
print('pages consolidated into the global hubs:', len(_mv))
print('  by type:', dict(collections.Counter(r['content_type'] for r in _mv)))
print('event microsites with a witnessed owner:',
      sum(1 for r in folder_rows if r['event_owner']))
print('event microsites that are archive candidates:',
      sum(1 for r in folder_rows if r['archive_candidate']))
print('folders that belong to an entity they cannot live under:',
      sum(1 for r in folder_rows if r['also_belongs_to']))
print('pages resolved as do-not-migrate:',
      sum(1 for r in page_rows if r['do_not_migrate']))
print('pages with a named managing unit: %d of %d'
      % (sum(1 for r in page_rows if 'central' not in r['managed_by']),
         len(page_rows)))

# Pages AKU's earlier export listed and the current one does not. Written out
# rather than printed alone: 72 pages leaving the corpus is a question for AKU,
# and the answer has to survive the next build.
with open(paths.work('dropped_pages.txt'), 'w', encoding='utf-8') as _f:
    _f.write('Pages in %s that %s no longer lists.\n'
             % (os.path.basename(paths.VISIBLE_PAGES_CSV),
                os.path.basename(paths.FILTERED_PAGES_CSV)))
    _f.write('%d pages. AKU to confirm each was retired deliberately.\n\n' % len(DROPPED))
    for _u, _a in DROPPED:
        _f.write('%-96s %s\n' % (_u, _a))
print('pages the previous export listed and this one drops:', len(DROPPED))

# Where the page's own CW/CA names a team the folder's owner does not include.
# The export wins in the plan; these are written out because a few are worth a
# second opinion rather than a rule.
_conf = page_owners.conflicts(page_rows)
with open(paths.work('owner_conflicts.txt'), 'w', encoding='utf-8') as _f:
    _f.write('Pages whose own CW/CA group names a team the permissions export does '
             'not give the folder.\n')
    _f.write('%d pages. The export wins in the plan — these are for review, not a '
             'blocked build.\n\n' % len(_conf))
    for _u, _mine, _theirs, _fold in _conf:
        _f.write('%s\n    page says   %s\n    folder says %s\n    folder      %s\n'
                 % (_u, ', '.join(_mine), ', '.join(_theirs), _fold))
print('pages whose own CW/CA disagrees with the folder owner:', len(_conf))
print('pages given an owner by their own CW/CA where the export named none:',
      sum(1 for r in page_rows if r['managed_by_source'] == 'page CW/CA'))

by_kind = collections.Counter(r['kind'] for r in folder_rows)
print('folder kinds:', dict(by_kind))
dept = sum(1 for r in folder_rows if r['kind'] == 'department')
print('witnessed departments:', dept)

# The questions no export answers. Computed from the rows above rather than
# authored as a list, so a decision that gets resolved upstream stops appearing
# without anyone remembering to delete it.
from decisions import build as build_decisions

decision_rows = build_decisions(folder_rows, page_rows)
print('open decisions: %d (%d pages at stake)'
      % (len(decision_rows), sum(r['pages'] for r in decision_rows)))

json.dump({'folders': folder_rows, 'pages': page_rows, 'roles': role_rows,
           'live': live_rows, 'decisions': decision_rows, 'columns': COLUMNS},
          open(paths.work('plan.json'), 'w', encoding='utf-8'),
          ensure_ascii=False)
