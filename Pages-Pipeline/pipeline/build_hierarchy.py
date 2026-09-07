"""Build the region -> entity -> division -> page hierarchy for aku.edu.

Root holds the regions, global among them; global owns the news / events / blogs
hubs; every entity keeps the sub-path shape it has on the live site today.  The
emitted paths reuse the shape the news migration already proved
(global/news/... , regions/{region}/entities/{entity}/departments/{dept}/...) so
pages and stories land in one tree rather than two competing ones.

Every placement carries a provenance string naming the rule that produced it, and
`confidence` is 'witnessed' only when the CSV itself proves it -- a dedicated
CW/CA owner group, an AD-domain majority, or the section's own CSV title.  Where
the data is silent the row says so; nothing here is presented as authoritative
that the export does not actually support.
"""
import collections
import html
import json

import paths

OUT_HTML = paths.out('AKU-Folder-Hierarchy.html')
OUT_TREE = paths.out('AKU-Folder-Hierarchy.tree.txt')
OUT_JSON = paths.out('AKU-Folder-Hierarchy.json')

webs = json.load(open(paths.work('webs.json'), encoding='utf-8'))
pages = json.load(open(paths.work('pages.json'), encoding='utf-8'))

from classification import REGIONS, ROOT_PAGE_DEST, SEC, D, I, W

tops = sorted({p.split('/')[0] for p in webs if p})
missing = [t for t in tops if t not in SEC]
extra = [s for s in SEC if s not in tops]
if missing or extra:
    raise SystemExit('classification out of sync: missing=%s extra=%s' % (missing, extra))

pages_by_web = collections.defaultdict(list)
for p in pages:
    pages_by_web[p['web']].append(p)

# How many pages AKU's filtered export added over their earlier one. Stated in
# both trees rather than left for a reviewer to count off the badges.
n_new = sum(1 for p in pages if p.get('new'))

# Two webs hold pages that no permission row mentions -- library/pk/fhs/SitePages
# and mrtc-pk/research/Pages/Projects.  Dropping them would lose 14 real pages,
# so hang them on the nearest ancestor the CSV does know, and keep the note.
orphan_webs = sorted(w for w in pages_by_web if w not in webs and w)
for w in orphan_webs:
    parent = w
    while parent and parent not in webs:
        parent = parent.rsplit('/', 1)[0] if '/' in parent else ''
    if parent:
        for p in pages_by_web[w]:
            p['orphan_from'] = w
            pages_by_web[parent].append(p)

def title_of(path):
    t = webs.get(path, {}).get('title') or []
    t = [x for x in t if x]
    return t[0] if t else path.split('/')[-1]

# ---- assemble -------------------------------------------------------------
tree = collections.OrderedDict()
for slug, name, code, note in REGIONS:
    tree[slug] = {'name': name, 'code': code, 'note': note,
                  'entities': collections.OrderedDict(),
                  'functions': collections.OrderedDict()}
tree['staging'] = {'name': 'Not content (staging / duplicates)', 'code': '--',
                    'note': 'test copies and unfinished rebuilds — do not migrate',
                    'entities': collections.OrderedDict(),
                    'functions': collections.OrderedDict()}

def web_node(path):
    """A web plus everything beneath it, as it sits on the live site today."""
    kids = sorted(w for w in webs
                  if w.startswith(path + '/') and '/' not in w[len(path) + 1:])
    pgs = sorted(pages_by_web.get(path, []), key=lambda x: x['file'].lower())
    node = {'web': path, 'title': title_of(path), 'slug': path.split('/')[-1],
            'pages': pgs, 'children': [web_node(k) for k in kids]}
    # webs holding pages under a deeper folder than the CSV knows (2 cases)
    for w2 in sorted(pages_by_web):
        if w2.startswith(path + '/') and w2 not in webs and \
           '/' not in w2[len(path) + 1:].rstrip('/').replace('/Pages/', '/'):
            pass
    return node

def total_pages(node):
    return len(node['pages']) + sum(total_pages(c) for c in node['children'])

def total_webs(node):
    return 1 + sum(total_webs(c) for c in node['children'])

for sec in tops:
    region, ent_slug, ent_name, division, conf, prov = SEC[sec]
    node = web_node(sec)
    node.update({'section': sec, 'confidence': conf, 'provenance': prov,
                 'division': division})
    R = tree[region]
    if ent_slug:
        e = R['entities'].setdefault(ent_slug, {
            'name': ent_name, 'slug': ent_slug, 'sections': [],
            'confidence': conf, 'provenance': prov})
        e['sections'].append(node)
        # an entity is only as certain as its most certain section
        order = {W: 0, I: 1, D: 2}
        if order[conf] < order[e['confidence']]:
            e['confidence'], e['provenance'] = conf, prov
    else:
        R['functions'][sec] = node

# the site-collection root itself (http://aku.edu, "Home") is a web too
root_web = {'title': title_of(''), 'pages': len(pages_by_web.get('', []))} \
    if '' in webs else None

# ---- numbers -------------------------------------------------------------
stats = {}
for slug, R in tree.items():
    ep = sum(total_pages(n) for e in R['entities'].values() for n in e['sections'])
    ew = sum(total_webs(n) for e in R['entities'].values() for n in e['sections'])
    fp = sum(total_pages(n) for n in R['functions'].values())
    fw = sum(total_webs(n) for n in R['functions'].values())
    stats[slug] = {'entities': len(R['entities']), 'entity_pages': ep,
                   'entity_webs': ew, 'functions': len(R['functions']),
                   'function_pages': fp, 'function_webs': fw,
                   'pages': ep + fp, 'webs': ew + fw}

json.dump({'regions': [{'slug': s, **{k: v for k, v in tree[s].items()
                                      if k not in ('entities', 'functions')},
                        'stats': stats[s],
                        'entities': [{'slug': es, 'name': e['name'],
                                      'confidence': e['confidence'],
                                      'provenance': e['provenance'],
                                      'sections': e['sections']}
                                     for es, e in tree[s]['entities'].items()],
                        'functions': list(tree[s]['functions'].values())}
                       for s in tree],
           'orphan_webs': orphan_webs,
           'totals': {'webs': len(webs), 'pages': len(pages),
                      'sections': len(tops)}},
          open(OUT_JSON, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

# ---- ASCII tree ----------------------------------------------------------
def ascii_web(node, pre, out, last, show_pages):
    out.append('%s%s %s  (%s)%s' % (
        pre, '└─' if last else '├─', node['slug'], node['title'],
        '  ·  %d pages' % len(node['pages']) if node['pages'] else ''))
    pre2 = pre + ('   ' if last else '│  ')
    kids = node['children']
    for i, c in enumerate(kids):
        ascii_web(c, pre2, out, i == len(kids) - 1 and not (show_pages and node['pages']), show_pages)
    if show_pages:
        for j, p in enumerate(node['pages']):
            out.append('%s%s %s%s' % (pre2, '└─' if j == len(node['pages']) - 1 else '├─',
                                      p['file'], '   [NEW]' if p.get('new') else ''))

def build_tree_text(show_pages):
    out = ['AKU.EDU — folder hierarchy (%d webs · %d pages · %d sections)'
           % (len(webs), len(pages), len(tops)),
           '%d pages marked [NEW] are in AKU\'s filtered export and were not in '
           'their earlier one.' % n_new if n_new else '', '']
    out.append('/   (site root — http://aku.edu, "%s"%s)'
               % (root_web['title'] if root_web else '?',
                  ', %d pages' % root_web['pages'] if root_web and root_web['pages'] else ''))
    if show_pages:
        for p in sorted(pages_by_web.get('', []), key=lambda x: x['file'].lower()):
            _g = ROOT_PAGE_DEST.get(p['file'].lower())
            out.append('│   %s%s%s' % (p['file'], '   [NEW]' if p.get('new') else '',
                                       '   -> %s' % _g[0] if _g else ''))
    keys = list(tree)
    for ri, slug in enumerate(keys):
        R = tree[slug]
        rlast = ri == len(keys) - 1
        st = stats[slug]
        out.append('%s %s/  [%s]  %d entities · %d sections · %d pages'
                   % ('└──' if rlast else '├──', slug, R['code'],
                      st['entities'], st['functions'] + sum(len(e['sections'])
                      for e in R['entities'].values()), st['pages']))
        rp = '    ' if rlast else '│   '
        blocks = []
        if R['functions']:
            landing = slug in R['functions']
            blocks.append((
                '(region landing page)' if landing and len(R['functions']) == 1
                else '(section folders)', list(R['functions'].values()), None))
        for es, e in R['entities'].items():
            blocks.append(('entities/%s' % es, e['sections'], e))
        for bi, (label, nodes, e) in enumerate(blocks):
            blast = bi == len(blocks) - 1
            mark = {'witnessed': '', 'inferred': '  ~inferred', 'decide': '  !needs-decision'}
            tag = mark[e['confidence']] if e else ''
            out.append('%s%s %s%s' % (rp, '└──' if blast else '├──', label, tag))
            bp = rp + ('    ' if blast else '│   ')
            for ni, n in enumerate(nodes):
                ascii_web(n, bp, out, ni == len(nodes) - 1, show_pages)
    if orphan_webs:
        out += ['', 'webs that hold pages but appear in no permission row:']
        out += ['   %s (%d pages)' % (w, len(pages_by_web[w])) for w in orphan_webs]
    return '\n'.join(out)

open(OUT_TREE, 'w', encoding='utf-8').write(build_tree_text(True))
print('tree written')

# ---- HTML ---------------------------------------------------------------
e = html.escape
CONF_LABEL = {W: ('witnessed', 'ok'), I: ('inferred', 'inf'), D: ('needs decision', 'dec')}

# ---- cross-region and cross-entity content ------------------------------
# A folder tree gives every page exactly one parent, but the live site does not
# respect that: the same entity runs in several regions, one entity splits its own
# content by region, and global functions carry content that belongs to a named
# entity.  Each case below is counted from the export, with the handling that
# keeps a single folder home and expresses the rest as references.
# An entity slug can appear under several regions.  Counting placements (32) and
# counting distinct entities (24) are different questions -- comparing one to the
# other would overstate how unusual a multi-region entity is.
ent_names = {}
multi_region = collections.defaultdict(list)
for slug in tree:
    for es, ent in tree[slug]['entities'].items():
        multi_region[es].append((slug, [n['section'] for n in ent['sections']]))
        ent_names[es] = ent['name']
distinct_entities = len(multi_region)
multi_region = {k: v for k, v in multi_region.items() if len(v) > 1}

def sub_pages(prefix):
    return sum(v['pages'] for q, v in webs.items()
               if q == prefix or q.startswith(prefix + '/'))

CROSS = [
    ('Same entity, several regions',
     '<b>%d of the %d distinct entities</b> run in more than one region — %s — '
     'which is how %d entities become %d folder placements. Each region owns its '
     'own SharePoint section, so each becomes its own folder: '
     '<span class="mono">regions/kenya/entities/medical-college</span> is not the '
     'same folder as <span class="mono">regions/pakistan/entities/medical-college'
     '</span>.'
     % (len(multi_region), distinct_entities,
        ', '.join('%s in %d' % (e(ent_names[k]), len(v))
                  for k, v in sorted(multi_region.items(),
                                     key=lambda x: -len(x[1]))),
        distinct_entities, sum(len(tree[s]['entities']) for s in tree)),
     'Keep one folder per region instance. Give every story and page an '
     '<b>entity</b> reference that points at a single shared entity record, so '
     '"all Medical College content" is a query on that reference and not a path '
     'match. Without it, the four Medical College folders look like four entities.'),
    ('One entity, its own region split',
     'Centre of Excellence in Women and Child Health carries coe-wch/pk, '
     'coe-wch/ea (%d pages) and coe-wch/ca — <b>Central Asia</b>, a region that '
     'appears nowhere in the news taxonomy. Its other 36 pages (about, impact, '
     'programmes, research, events) are shared across all three.'
     % sub_pages('coe-wch/ea'),
     'Canonical home in Pakistan, where the owner group and domain majority point. '
     'The shared pages take all three regions as references rather than being '
     'copied. Central Asia has to be added to the region list or explicitly '
     'declined — it cannot stay undeclared.'),
    ('Global function, entity-specific content',
     'Library holds 11 branch libraries that belong to named entities — '
     'library/ea/gsmc (%d pages), library/pk/ied (%d), library/pk/fas (%d), '
     'library/ea/ied-daressalaam (%d) and the FHS libraries in Karachi, Nairobi, '
     'Dar es Salaam and Kampala. library/pk totals %d pages and library/ea %d.'
     % (sub_pages('library/ea/gsmc'), sub_pages('library/pk/ied'),
        sub_pages('library/pk/fas'), sub_pages('library/ea/ied-daressalaam'),
        sub_pages('library/pk'), sub_pages('library/ea')),
     'The Library is one global function, so it keeps one folder tree under '
     'global/library. Each branch page references its region and its entity, '
     'which is what lets the IED page list its own library without the file '
     'moving out of global/library.'),
    ('Global function, region split',
     'Students splits four ways under five different subsections — '
     'clubs-societies (%d pages), health (%d), wellness (%d), experience (%d) and '
     'pelfp — and Convocation splits six ways, into global, ke, pk, tz, ug and uk. '
     'Admissions carries per-country programme webs such as '
     'admissions/bns-de-uganda.'
     % (sub_pages('students/clubs-societies'), sub_pages('students/health'),
        sub_pages('students/wellness'), sub_pages('students/experience')),
     'Keep the folder shape the site already uses, because editors know it and it '
     'is stable. Add the region as a reference on each leaf so a region landing '
     'page can pull its own student and convocation content without duplicating '
     'the parent structure.'),
    ('Events, owned by entities but living in global',
     'All 48 event microsites sit under /events, yet their owner groups name the '
     'entity behind each one: CW MC EA on breast-cancer and wpsd, CW IHD on icehd, '
     'CA BMI on bmi-conf, CRM Approver on rsc-conf, CW CIME on simpact, '
     'CW IED PK Research on iedpk-intl-conf, CW SONAM PK on inmd, CW Library on '
     'pls, CA DTEA on dtea, CA Neuroscience Conference on neuro-conf.',
     'This is the pattern to copy for news, blogs and events: one folder under '
     'global, with the owning entity and region carried as tags. The owner group '
     'is the evidence for the tag, so it can be assigned rather than guessed.'),
]


# One row per uncertain *section*, not per entity: a witnessed entity can still
# hold a section whose placement is a guess (GSMC is inferred, but /GNV and
# /govprogramme landing under it is a separate open question), and rolling those
# up into the entity badge would hide them.
decisions = []
for s in tree:
    for es, ent in tree[s]['entities'].items():
        for n in ent['sections']:
            if n['confidence'] != W:
                label = ent['name'] + (' → %s' % n['division'] if n['division'] else '')
                decisions.append((s, label, '/' + n['section'],
                                  n['confidence'], n['provenance']))
    for k, n in tree[s]['functions'].items():
        if n['confidence'] != W:
            decisions.append((s, n['title'], '/' + k, n['confidence'], n['provenance']))
cross_html = ''.join(
    '<div class="cross"><div class="ch"><span class="cn">%d</span>'
    '<span class="ct">%s</span></div><p class="cf">%s</p>'
    '<p class="cw"><b>How it is handled</b> — %s</p></div>'
    % (i + 1, e(title), finding, handling)
    for i, (title, finding, handling) in enumerate(CROSS))

dec_rows = ''.join(
    '<tr class="%s"><td>%s</td><td>%s</td><td class="mono">%s</td><td>%s</td></tr>'
    % ('dec' if c == D else 'inf', e(r), e(nm), e(sc), e(pv))
    for r, nm, sc, c, pv in sorted(decisions, key=lambda x: (x[3] != D, x[0])))
# ---- how much of the tagging is derivable -------------------------------
# A page can be tagged automatically when some folder at or above it names a
# real owner. Webs carrying the whole 47-93 group roster name no owner, so their
# pages have to be tagged by hand -- that is the number worth planning around.
ROOT_DUMP = 30
CENTRAL = {'CW Public Affairs', 'CA Public Affairs'}

def owner_of(web):
    cur = web
    while True:
        g = webs.get(cur, {}).get('uniq_groups', {})
        if 0 < len(g) <= ROOT_DUMP:
            real = sorted(x for x in g if x not in CENTRAL)
            if real:
                return cur, real
        if '/' not in cur:
            return None, None
        cur = cur.rsplit('/', 1)[0]

auto_tag, manual_tag = 0, 0
manual_by_section = collections.Counter()
for pg in pages:
    _, real = owner_of(pg['web'])
    if real:
        auto_tag += 1
    else:
        manual_tag += 1
        manual_by_section[pg['section']] += 1

# ---- chart helpers -------------------------------------------------------
# One measure, nominal categories, so every bar takes the same validated hue --
# a darker-where-bigger ramp would double-encode the length the bar already
# shows. Values ride the bar tips, so no number is reachable only by hover.

def bar_rows(rows, unit='pages'):
    top = max([v for _, v, _ in rows] + [1])
    out = []
    for label, val, note in rows:
        pct = 100.0 * val / top
        zero = ' zero' if not val else ''
        out.append(
            '<div class="brow' + zero + '" tabindex="0" data-tip="'
            + e('%s — %s %s%s' % (label, f'{val:,}', unit,
                                  ' · ' + note if note else '')) + '">'
            '<span class="blab">' + e(label) + '</span>'
            '<span class="btrack"><span class="bfill" style="width:'
            + ('%.2f' % pct) + '%"></span></span>'
            '<span class="bval">' + f'{val:,}' + '</span>'
            '<span class="bnote">' + e(note) + '</span></div>')
    return '<div class="bars">' + ''.join(out) + '</div>'

def prop_bar(segments):
    """Part-to-whole across a handful of classes, separated by a 2px surface gap."""
    tot = sum(v for _, v, _ in segments) or 1
    seg, leg = [], []
    for label, val, cls in segments:
        seg.append('<span class="pseg ' + cls + '" style="flex:' + str(val)
                   + '" data-tip="' + e('%s — %s of %s' % (label, f'{val:,}',
                                                           f'{tot:,}'))
                   + '"></span>')
        leg.append('<span class="plegi"><i class="sw ' + cls + '"></i>'
                   + e(label) + ' <b>' + f'{val:,}' + '</b>'
                   + '<em>' + ('%.0f%%' % (100.0 * val / tot)) + '</em></span>')
    return ('<div class="prop">' + ''.join(seg) + '</div>'
            '<div class="pleg">' + ''.join(leg) + '</div>')

# ---- the tree ------------------------------------------------------------
def n_of(n, word):
    return '%s %s%s' % (f'{n:,}', word, '' if n == 1 else 's')

def n_ent_of(n):
    return '%d %s' % (n, 'entity' if n == 1 else 'entities')

def t_row(cls, label, meta, data, extra='', kids='', open_=False):
    caret = '<span class="tw"></span>' if kids else '<span class="tw leafmark"></span>'
    return ('<li class="' + cls + ('' if open_ or not kids else ' collapsed')
            + '"><div class="row" data-n="' + data + '">' + caret + extra
            + '<span class="lbl">' + label + '</span>'
            + '<span class="meta">' + meta + '</span></div>'
            + ('<ul>' + kids + '</ul>' if kids else '') + '</li>')

# AKU's four dispositions. The newer export added the last two: a page nobody
# has looked at yet is a different thing from one they have decided to move, and
# the tree should not colour it as though the call had been made.
ACTION_TITLE = {'asis': 'Move as is', 'upd': 'Update, then move',
                'unrev': 'Not reviewed by AKU yet', 'unclear': 'AKU marked it unclear'}

def t_page(p):
    # `new` marks a page AKU's filtered export added and the earlier one never
    # listed. It goes in data-n as the word "new" too, so the existing search box
    # finds them without a second mechanism.
    isnew = p.get('new')
    # A root page the plan sends somewhere other than Global says so here, or the
    # tree would show it staying put.
    goes = ROOT_PAGE_DEST.get(p['file'].lower()) if not p.get('web') else None
    # Searchable text: the file name, the web that holds it, and the word "new"
    # for the ones this export added. The box is a free-text search, so a broad
    # match is what it is for — unlike a dropdown labelled with one region,
    # which has to mean that region exactly.
    return ('<li class="t-page' + (' is-new' if isnew else '')
            + '"><div class="row" data-n="' + e(p['file'].lower())
            + ' ' + e((p.get('web') or 'site-root').lower())
            + (' new' if isnew else '')
            + '"><span class="tw leafmark"></span><span class="dot ' + p['action']
            + '" title="' + ACTION_TITLE.get(p['action'], p['action'])
            + '"></span><span class="lbl mono">' + e(p['file']) + '</span>'
            + ('<span class="tag-new" title="not in AKU’s earlier export">new</span>'
               if isnew else '')
            + ('<span class="tag-moves" title="' + e(goes[3]) + '">&rarr; '
               + e(goes[0]) + '</span>' if goes else '')
            + '<span class="meta">' + e(p['cat']) + '</span>'
            '<a class="go" href="' + e(p['url']) + '" target="_blank" '
            'rel="noopener">open ↗</a></div></li>')

def t_web(node):
    kids = ''.join(t_web(c) for c in node['children']) + \
           ''.join(t_page(p) for p in node['pages'])
    tp, tw = total_pages(node), total_webs(node)
    bits = ([n_of(tw, 'folder')] if tw > 1 else []) + \
           [n_of(tp, 'page') if tp else 'no pages']
    return t_row('t-web',
                 '<span class="mono sl">' + e(node['slug']) + '</span> '
                 '<span class="tt">' + e(node['title']) + '</span>',
                 ' · '.join(bits),
                 e((node['slug'] + ' ' + node['title']).lower()), '', kids)

tree_items = []
for slug in tree:
    R, st = tree[slug], stats[slug]
    groups = ''
    if R['functions']:
        landing = slug in R['functions'] and len(R['functions']) == 1
        label = ('Region landing page' if landing else
                 'Content hubs and section folders' if slug == 'global'
                 else 'Section folders')
        hub = [k for k in ('news', 'events', 'blogs') if k in R['functions']]
        order = hub + [k for k in R['functions'] if k not in hub]
        groups += t_row('t-group', e(label),
                        '%s · %s' % (n_of(len(R['functions']), 'folder'),
                                     n_of(st['function_pages'], 'page')),
                        e(label.lower()), '',
                        ''.join(t_web(R['functions'][k]) for k in order), open_=True)
    if R['entities']:
        ents_html = ''
        for es, ent in R['entities'].items():
            lbl, cls = CONF_LABEL[ent['confidence']]
            ep = sum(total_pages(n) for n in ent['sections'])
            ew = sum(total_webs(n) for n in ent['sections'])
            ents_html += t_row(
                't-ent',
                '<span class="en">' + e(ent['name']) + '</span>',
                '%s · %s' % (n_of(ew, 'folder'), n_of(ep, 'page')),
                e((ent['name'] + ' ' + es).lower()),
                '<span class="badge ' + cls + '">' + lbl + '</span>',
                '<li class="t-prov"><div class="row" data-n="' + e(es) + '">'
                '<span class="tw leafmark"></span><span class="lbl">'
                '<b>' + e('%s/entities/%s' % (slug, es)) + '</b> — '
                + e(ent['provenance']) + '</span></div></li>'
                + ''.join(t_web(n) for n in ent['sections']))
        groups += t_row('t-group', 'Entities',
                        '%s · %s' % (n_ent_of(len(R['entities'])),
                                     n_of(st['entity_pages'], 'page')),
                        'entities', '', ents_html, open_=True)
    if not groups:
        groups = ('<li class="t-none"><div class="row" data-n="afghanistan">'
                  '<span class="tw leafmark"></span><span class="lbl">No section on '
                  'aku.edu — this region exists only in the news data</span>'
                  '</div></li>')
    nsec = st['functions'] + sum(len(x['sections']) for x in R['entities'].values())
    tree_items.append(t_row(
        't-region', '<span class="rn">' + e(R['name']) + '</span>',
        '%s · %s · %s · %s'
        % (n_ent_of(st['entities']), n_of(nsec, 'section'),
           n_of(st['webs'], 'folder'), n_of(st['pages'], 'page')),
        e((slug + ' ' + R['name']).lower()),
        '<span class="code">' + e(R['code']) + '</span>'
        '<span class="path">' + e(slug) + '/</span>', groups, open_=True))

# The root web's own pages -- home, contact, campuses, the legal set -- hang off
# the root itself. They sit above every section, so there is no region node they
# could belong to, and leaving them out would drop 17 pages from the tree.
root_pages = sorted(pages_by_web.get('', []), key=lambda x: x['file'].lower())

tree_view = ('<ul class="tree"><li class="t-root"><div class="row" '
             'data-n="root aku.edu home"><span class="tw"></span>'
             '<span class="lbl mono">aku.edu</span><span class="meta">site root · '
             + n_of(len(webs), 'folder') + ' · ' + n_of(len(pages), 'page')
             + '</span></div><ul>'
             + ''.join(t_page(p) for p in root_pages)
             + ''.join(tree_items) + '</ul></li></ul>')

# ---- charts ---------------------------------------------------------------
region_rows = [(tree[s]['name'], stats[s]['pages'],
                '%d entities · %d folders' % (stats[s]['entities'], stats[s]['webs']))
               for s in tree if s != 'staging']
region_rows.sort(key=lambda r: -r[1])
chart_regions = bar_rows(region_rows)

sec_pages = collections.Counter()
for pg in pages:
    sec_pages[pg['section']] += 1
sec_rows = []
for s, n in sec_pages.most_common(12):
    reg, ent, _, _, _, _ = SEC[s]
    where = tree[reg]['name'] if reg != 'staging' else 'staging'
    sec_rows.append(('/' + s, n, where))
chart_sections = bar_rows(sec_rows)

conf_count = collections.Counter(SEC[s][4] for s in tops)
chart_conf = prop_bar([
    ('Witnessed', conf_count[W], 'ok'),
    ('Inferred', conf_count[I], 'inf'),
    ('Needs decision', conf_count[D], 'dec')])
chart_tag = prop_bar([
    ('Owner group found automatically', auto_tag, 'ok'),
    ('Needs manual tagging', manual_tag, 'inf')])

manual_rows = ''.join(
    '<li><span class="mono">/' + e(s) + '</span><b>' + str(n) + '</b></li>'
    for s, n in manual_by_section.most_common())

# ---- inline SVG diagrams -------------------------------------------------
DIAG_SPLIT = '''
<figure class="fig"><svg viewBox="0 0 880 300" role="img" xmlns="http://www.w3.org/2000/svg"
 aria-label="The flat slug mcpk forks into two folder levels, a region and an entity, each needing its own witness; the deeper path segments below it copy across unchanged.">
<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7"
 markerHeight="7" orient="auto-start-reverse">
<path d="M0,0 L10,5 L0,10 z" fill="currentColor"/></marker></defs>
<text x="8" y="14" class="dh">TODAY — ONE FLAT LIST OF 82 SECTIONS</text>
<text x="520" y="14" class="dh">PROPOSED — REGIONS AT THE ROOT</text>
<rect x="8" y="36" width="230" height="34" rx="6" class="dbox hi"/>
<text x="20" y="58" class="dm hi">/mcpk</text>
<text x="160" y="58" class="ds">892 pages</text>
<path d="M238 53 H340 V37 H508" class="dl" fill="none" marker-end="url(#ar)"/>
<path d="M340 53 V85 H508" class="dl" fill="none" marker-end="url(#ar)"/>
<text x="350" y="30" class="dt">slug suffix “pk”</text>
<text x="350" y="78" class="dt">owner group CW MC PK</text>
<rect x="520" y="20" width="348" height="34" rx="6" class="dbox hi"/>
<text x="532" y="42" class="dm hi">regions/pakistan/</text>
<rect x="520" y="68" width="348" height="34" rx="6" class="dbox hi"/>
<text x="532" y="90" class="dm hi">entities/medical-college/</text>
<line x1="8" y1="126" x2="868" y2="126" class="dl dashed"/>
<text x="8" y="118" class="dh">BELOW THE SPLIT — NOTHING IS INFERRED</text>
<rect x="8" y="150" width="230" height="30" rx="6" class="dbox dim"/>
<text x="20" y="170" class="dm">/anaes</text>
<rect x="8" y="196" width="230" height="30" rx="6" class="dbox dim"/>
<text x="20" y="216" class="dm">Pages/home.aspx</text>
<line x1="238" y1="165" x2="508" y2="165" class="dl dashed" marker-end="url(#ar)"/>
<line x1="238" y1="211" x2="508" y2="211" class="dl dashed" marker-end="url(#ar)"/>
<text x="350" y="158" class="dt dim">copied across unchanged</text>
<rect x="520" y="150" width="348" height="30" rx="6" class="dbox dim"/>
<text x="532" y="170" class="dm">departments/anaes/</text>
<rect x="520" y="196" width="348" height="30" rx="6" class="dbox dim"/>
<text x="532" y="216" class="dm">home</text>
<text x="8" y="266" class="ds">One segment becomes two folder levels, and each half needs
its own witness.</text>
<text x="8" y="284" class="ds">Everything deeper than the split is a straight copy — which
is why the risk sits entirely in that first hop.</text>
</svg><figcaption>One slug, two facts. <b>mcpk</b> means Medical College
<i>and</i> Pakistan, so it forks into two folder levels — evidenced by the
<span class="mono">pk</span> suffix and the <span class="mono">CW MC PK</span>
owner group. The 19 open questions in section 6 are all failures of exactly this
fork.</figcaption></figure>'''

DIAG_TAG = '''
<figure class="fig"><svg viewBox="0 0 880 258" role="img" xmlns="http://www.w3.org/2000/svg"
 aria-label="A page has exactly one folder home but can belong to a region and an entity at the same time, which only tags can express.">
<defs><marker id="ar2" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7"
 markerHeight="7" orient="auto-start-reverse">
<path d="M0,0 L10,5 L0,10 z" fill="currentColor"/></marker></defs>
<rect x="286" y="16" width="308" height="38" rx="6" class="dbox hi"/>
<text x="300" y="40" class="dm hi">library/ea/gsmc</text>
<text x="524" y="40" class="ds">6 pages</text>
<path d="M400 58 V80 H195 V104" class="dl" fill="none" marker-end="url(#ar2)"/>
<path d="M480 58 V80 H685 V104" class="dl dashed" fill="none" marker-end="url(#ar2)"/>
<text x="298" y="72" class="dt" text-anchor="middle">lives in — one folder only</text>
<text x="582" y="72" class="dt" text-anchor="middle">belongs to — any number</text>
<rect x="30" y="112" width="330" height="34" rx="6" class="dbox"/>
<text x="42" y="134" class="dm">global/library/ea/gsmc</text>
<text x="30" y="172" class="ds">Folders answer <tspan class="dstrong">where does it
live.</tspan></text>
<rect x="520" y="112" width="330" height="34" rx="6" class="dbox tag"/>
<text x="532" y="134" class="dm">region: kenya</text>
<rect x="520" y="156" width="330" height="34" rx="6" class="dbox tag"/>
<text x="532" y="178" class="dm">entity: graduate-school-of-media…</text>
<text x="520" y="216" class="ds">Tags answer <tspan class="dstrong">who does it belong
to.</tspan></text>
<text x="30" y="240" class="ds">Copying the page into a second folder would fork it. A tag
adds the second owner without moving anything.</text>
</svg><figcaption>Why tagging is not optional. This library branch belongs to the
Library <i>and</i> to GSMC in Kenya — a single-parent folder tree can only say one
of those.</figcaption></figure>'''

# ---- stylesheet ----------------------------------------------------------
# Data marks use the validated blue: AKU's green fails the categorical gate on
# this surface (L 0.416, outside the 0.43-0.77 band; chroma 0.075, below the 0.1
# floor -- it reads gray as a fill). Green stays on page chrome, which encodes
# nothing. Dark steps come from the same ramp and were validated against #1a1a19.
CSS = """
*{box-sizing:border-box}
:root{
 --plane:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --mut:#898781;
 --grid:#e1e0d9; --base:#c3c2b7; --ring:rgba(11,11,11,.10);
 --series:#2a78d6;
 --ok:#0ca30c; --inf:#fab219; --dec:#d03b3b;
 --brand:#00594f; --brand2:#0b7f6f;
 color-scheme:light}
@media(prefers-color-scheme:dark){:root{
 --plane:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7; --mut:#898781;
 --grid:#2c2c2a; --base:#383835; --ring:rgba(255,255,255,.10);
 --series:#3987e5; --brand:#0b7f6f; --brand2:#12a08c;
 color-scheme:dark}}
html{scroll-behavior:smooth}
body{margin:0;background:var(--plane);color:var(--ink);
 font:15px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif;
 -webkit-font-smoothing:antialiased}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.86em}
.wrap{max-width:1080px;margin:0 auto;padding:0 24px}

/* header + hero figure */
header.top{background:var(--brand);color:#fff;padding:38px 0 30px}
h1{margin:0 0 8px;font-size:25px;font-weight:640;letter-spacing:-.3px}
header.top p{margin:0;max-width:64ch;font-size:14.5px;color:rgba(255,255,255,.88)}
.hero{display:flex;align-items:flex-end;gap:28px;flex-wrap:wrap;margin-top:26px}
.hnum{font-size:52px;font-weight:680;line-height:.95;letter-spacing:-1.5px}
.hnum span{font-size:15px;font-weight:500;letter-spacing:0;
 display:block;color:rgba(255,255,255,.8);margin-top:5px}
.tiles{display:flex;gap:26px;flex-wrap:wrap;padding-bottom:5px}
.tile b{display:block;font-size:22px;font-weight:660;line-height:1.1}
.tile span{font-size:11.5px;color:rgba(255,255,255,.78);text-transform:uppercase;
 letter-spacing:.6px}

/* section nav */
nav.jump{position:sticky;top:0;z-index:40;background:var(--plane);
 border-bottom:1px solid var(--grid)}
nav.jump .wrap{display:flex;gap:2px;overflow-x:auto;padding:0 24px}
nav.jump a{padding:13px 12px;font-size:13px;color:var(--ink2);text-decoration:none;
 white-space:nowrap;border-bottom:2px solid transparent}
nav.jump a:hover{color:var(--brand2);border-bottom-color:var(--grid)}

/* sections */
section{padding:44px 0 8px}
.snum{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.8px;
 color:var(--brand2);text-transform:uppercase;margin-bottom:7px}
h2{margin:0 0 8px;font-size:22px;font-weight:640;letter-spacing:-.2px}
.lede{margin:0 0 22px;font-size:15px;color:var(--ink2);max-width:74ch}
.lede b{color:var(--ink)}
h3.sub{margin:26px 0 12px;font-size:14px;font-weight:640}

/* cards + figures */
.card{background:var(--surface);border:1px solid var(--ring);border-radius:12px;
 padding:20px 22px;margin-bottom:14px}
.fig{margin:0 0 14px;background:var(--surface);border:1px solid var(--ring);
 border-radius:12px;padding:20px 22px;overflow-x:auto}
.fig svg{max-width:100%;height:auto;color:var(--ink2);display:block}
figcaption{margin-top:14px;font-size:13px;color:var(--ink2);line-height:1.6;
 border-top:1px solid var(--grid);padding-top:12px}
figcaption b{color:var(--ink)}
.dh{font:600 10.5px system-ui;letter-spacing:.8px;fill:var(--mut)}
.dm{font:600 13px ui-monospace,Menlo,Consolas,monospace;fill:var(--ink)}
.dm.hi{fill:var(--series)}
.ds{font:12px system-ui;fill:var(--mut)}
.dstrong{font-weight:650;fill:var(--ink2)}
.dt{font:11.5px system-ui;fill:var(--mut)}
.dt.dim{opacity:.7}
.dbox{fill:none;stroke:var(--base);stroke-width:1}
.dbox.dim{stroke:var(--grid)}
.dbox.hi{stroke:var(--series);stroke-width:1.5}
.dbox.tag{stroke:var(--base);stroke-dasharray:4 3}
.dl{stroke:currentColor;stroke-width:1.5;fill:none;opacity:.65}
.dl.dashed{stroke-dasharray:4 4;opacity:.4}

/* bar charts */
.bars{display:flex;flex-direction:column;gap:9px}
.brow{display:grid;grid-template-columns:132px 1fr 62px 150px;align-items:center;
 gap:12px;position:relative;outline:none}
.btrack{height:18px;border-left:1px solid var(--base);display:flex;align-items:center}
.bfill{height:18px;background:var(--series);border-radius:0 4px 4px 0;
 min-width:2px;transition:opacity .12s}
.brow.zero .bfill{background:var(--grid);border-radius:0 2px 2px 0}
.blab{font-size:13px;text-align:right;color:var(--ink)}
.bval{font-size:13px;font-weight:620;font-variant-numeric:tabular-nums}
.bnote{font-size:11.5px;color:var(--mut)}
.brow:hover .bfill,.brow:focus .bfill{opacity:.78}
.brow[data-tip]:hover::after,.brow[data-tip]:focus::after{content:attr(data-tip);
 position:absolute;left:144px;bottom:100%;margin-bottom:5px;background:var(--ink);
 color:var(--plane);font-size:11.5px;padding:5px 9px;border-radius:6px;
 white-space:nowrap;z-index:5;pointer-events:none}

/* proportion bar */
.prop{display:flex;height:26px;border-radius:5px;overflow:hidden;gap:2px;
 background:var(--surface)}
.pseg{position:relative;min-width:3px}
.pseg.ok{background:var(--ok)}.pseg.inf{background:var(--inf)}
.pseg.dec{background:var(--dec)}
.pseg[data-tip]:hover::after{content:attr(data-tip);position:absolute;left:0;
 top:100%;margin-top:6px;background:var(--ink);color:var(--plane);font-size:11.5px;
 padding:5px 9px;border-radius:6px;white-space:nowrap;z-index:5}
.pleg{display:flex;gap:22px;flex-wrap:wrap;margin-top:13px;font-size:12.5px;
 color:var(--ink2)}
.plegi{display:flex;align-items:center;gap:6px}
.plegi b{font-variant-numeric:tabular-nums}
.plegi em{font-style:normal;color:var(--mut);font-size:11.5px}
.sw{width:10px;height:10px;border-radius:3px;flex:none}
.sw.ok{background:var(--ok)}.sw.inf{background:var(--inf)}.sw.dec{background:var(--dec)}
.mlist{list-style:none;margin:13px 0 0;padding:0;display:flex;flex-wrap:wrap;gap:7px}
.mlist li{display:flex;gap:7px;align-items:center;background:var(--plane);
 border:1px solid var(--grid);border-radius:6px;padding:4px 9px;font-size:12px}
.mlist b{font-variant-numeric:tabular-nums;color:var(--ink2)}

/* two-up */
.duo{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:860px){.duo{grid-template-columns:1fr}
 .brow{grid-template-columns:104px 1fr 54px;}.bnote{display:none}}

/* tree */
.tbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:13px}
#q{flex:1;min-width:210px;padding:10px 13px;border:1px solid var(--ring);
 border-radius:9px;font-size:14px;background:var(--surface);color:var(--ink)}
#q:focus{outline:2px solid var(--brand2);outline-offset:-1px}
.btn{padding:9px 12px;border:1px solid var(--ring);background:var(--surface);
 border-radius:9px;cursor:pointer;font-size:13px;color:var(--ink2)}
.btn:hover{border-color:var(--brand2);color:var(--brand2)}
#hits{font-size:12.5px;color:var(--mut);min-width:104px}
#treeview{background:var(--surface);border:1px solid var(--ring);border-radius:12px;
 padding:16px 18px;overflow-x:auto}
.tree,.tree ul{list-style:none;margin:0;padding:0}
.tree ul{padding-left:22px}
.tree li{position:relative;padding-left:22px}
.tree li::before{content:"";position:absolute;left:0;top:16px;width:15px;height:1px;
 background:var(--base)}
.tree li::after{content:"";position:absolute;left:0;top:0;bottom:0;width:1px;
 background:var(--base)}
.tree li:last-child::after{height:16px}
.tree>li{padding-left:0}
.tree>li::before,.tree>li::after{display:none}
.tree li.collapsed>ul{display:none}
.tree .row{display:flex;align-items:center;gap:8px;padding:5px 8px;border-radius:7px;
 min-height:32px;white-space:nowrap}
.tree .row:hover{background:var(--plane)}
.tw{width:13px;height:13px;flex:none;position:relative;cursor:pointer}
.tw::before{content:"";position:absolute;left:3px;top:1px;width:5px;height:5px;
 border-right:1.6px solid var(--mut);border-bottom:1.6px solid var(--mut);
 transform:rotate(45deg);transition:transform .14s}
li.collapsed>.row>.tw::before{transform:rotate(-45deg);left:2px;top:2px}
.tw.leafmark{cursor:default}
.tw.leafmark::before{border:0;background:var(--base);width:4px;height:4px;
 border-radius:50%;left:4px;top:4px;transform:none}
.tree .lbl{font-size:13.5px}
.tree .meta{font-size:11.5px;color:var(--mut);margin-left:6px}
.tree .go{font-size:11px;color:var(--brand2);text-decoration:none;margin-left:8px}
.tree .dot{width:7px;height:7px;border-radius:50%;flex:none;background:var(--base)}
.tree .dot.upd{background:var(--inf)}
.tree .dot.unrev{background:transparent;box-shadow:inset 0 0 0 1.5px var(--mut)}
.tree .dot.unclear{background:var(--mut)}
/* Pages this export added, and a rollup on every folder above them, so a
   reviewer can find the additions without opening 628 folders. */
.tree .tag-new{margin-left:7px;padding:1px 6px;border-radius:9px;font-size:10px;
  font-weight:700;letter-spacing:.03em;text-transform:uppercase;
  background:var(--ok,#0a7d4b);color:#fff;flex:none}
.tree .cnt-new{margin-left:7px;padding:1px 6px;border-radius:9px;font-size:10.5px;
  font-weight:660;background:rgba(10,125,75,.12);color:var(--ok,#0a7d4b);
  border:1px solid rgba(10,125,75,.3);flex:none}
.tree .tag-moves{margin-left:7px;padding:1px 6px;border-radius:9px;font-size:10.5px;
  font-weight:660;background:rgba(0,0,0,.05);color:var(--brand2);
  border:1px solid var(--ring);flex:none}
.tree.newonly li:not(.has-new):not(.is-new){display:none}
.btn.on{border-color:var(--brand2);color:var(--brand2);font-weight:660}
.t-root>.row{background:var(--brand);color:#fff;margin-bottom:4px}
.t-root>.row .lbl{font-weight:660;font-size:15px}
.t-root>.row .meta{color:rgba(255,255,255,.8)}
.t-root>.row .tw::before{border-color:#fff}
.t-region>.row{background:var(--plane);margin:3px 0}
.t-region .rn{font-weight:640;font-size:14.5px}
.t-group>.row .lbl{font-size:10.5px;text-transform:uppercase;letter-spacing:.7px;
 color:var(--mut);font-weight:700}
.t-ent>.row .en{font-weight:600}
.t-web>.row .sl{color:var(--series);font-weight:600;font-size:12px}
.t-web>.row .tt{font-size:12.5px;color:var(--ink2)}
.t-page>.row .lbl{font-size:11.5px}
.t-prov .lbl,.t-none .lbl{font-size:12px;color:var(--mut);white-space:normal;
 line-height:1.55}
.t-prov .lbl b{color:var(--ink2);font-family:ui-monospace,Menlo,Consolas,monospace}
.t-prov .row,.t-none .row{white-space:normal;align-items:flex-start;padding-top:3px}
.tree .path{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11px;
 color:var(--ink2);background:var(--surface);padding:2px 6px;border-radius:5px}
.code{background:var(--brand2);color:#fff;border-radius:5px;padding:2px 7px;
 font-size:11px;font-weight:700;letter-spacing:.4px;flex:none}
.badge{font-size:10px;text-transform:uppercase;letter-spacing:.4px;font-weight:700;
 padding:3px 7px;border-radius:5px;flex:none;display:inline-flex;gap:4px;
 align-items:center}
.badge::before{font-size:9px}
.badge.ok{background:rgba(12,163,12,.13);color:var(--ok)}
.badge.ok::before{content:"✓"}
.badge.inf{background:rgba(250,178,25,.16);color:#8a6000}
.badge.inf::before{content:"~"}
.badge.dec{background:rgba(208,59,59,.13);color:var(--dec)}
.badge.dec::before{content:"!"}
@media(prefers-color-scheme:dark){.badge.inf{color:var(--inf)}}

/* cross cards */
.cross{background:var(--surface);border:1px solid var(--ring);
 border-left:3px solid var(--brand2);border-radius:0 12px 12px 0;
 padding:16px 20px;margin-bottom:10px}
.ch{display:flex;align-items:center;gap:10px;margin-bottom:8px}
.cn{background:var(--brand);color:#fff;width:22px;height:22px;border-radius:50%;
 display:flex;align-items:center;justify-content:center;font-size:11.5px;
 font-weight:700;flex:none}
.ct{font-weight:640;font-size:15px}
.cf{margin:0 0 10px;font-size:13.5px;line-height:1.65;color:var(--ink2)}
.cf b{color:var(--ink)}
.cw{margin:0;font-size:13px;color:var(--ink2);line-height:1.65;background:var(--plane);
 padding:10px 13px;border-radius:8px}
.cw b{color:var(--brand2)}

/* table */
table{width:100%;border-collapse:collapse;background:var(--surface);
 border:1px solid var(--ring);border-radius:12px;overflow:hidden;font-size:13px}
th{text-align:left;padding:10px 13px;background:var(--plane);color:var(--mut);
 font-size:10.5px;text-transform:uppercase;letter-spacing:.5px;
 border-bottom:1px solid var(--grid);font-weight:700}
td{padding:10px 13px;border-bottom:1px solid var(--grid);vertical-align:top}
tr:last-child td{border-bottom:0}
tr.dec td:first-child{box-shadow:inset 3px 0 0 var(--dec)}
tr.inf td:first-child{box-shadow:inset 3px 0 0 var(--inf)}

/* glossary */
dl.gl{margin:0;display:grid;grid-template-columns:auto 1fr;gap:9px 18px;font-size:13.5px}
dl.gl dt{font-weight:640;color:var(--ink)}
dl.gl dd{margin:0;color:var(--ink2)}
.hide{display:none!important}
footer{border-top:1px solid var(--grid);margin-top:44px;padding:24px 0 40px;
 color:var(--mut);font-size:12.5px}
"""

JS = """
const q=document.getElementById('q'),hits=document.getElementById('hits');
const nodes=[...document.querySelectorAll('.tree li')];
function kids(li){return [...li.querySelectorAll(':scope > ul > li')];}
function openUp(li){let p=li.parentElement;while(p){if(p.tagName==='LI')
  p.classList.remove('collapsed');p=p.parentElement;}}
document.querySelectorAll('.tree .row').forEach(r=>{
  r.addEventListener('click',ev=>{
    if(ev.target.tagName==='A')return;
    const li=r.closest('li');
    if(li.querySelector(':scope > ul'))li.classList.toggle('collapsed');
  });
});
/* Depth 0 root, 1 region, 2 group heading, 3 entity or top-level section,
   4+ the folders and pages inside it. */
function depth(li){let d=0,p=li.parentElement;
  while(p){if(p.tagName==='LI')d++;p=p.parentElement;}return d;}
function setDepth(n){nodes.forEach(li=>{if(li.querySelector(':scope > ul'))
  li.classList.toggle('collapsed',depth(li)>=n);});}
function level(n){q.value='';hits.textContent='';clearNewOnly();
  nodes.forEach(li=>li.classList.remove('hide'));setDepth(n);}
/* The depth buttons and the search box each show the whole tree again, so the
   new-only filter has to come off with them -- left on, it silently hides most
   of what the reviewer just asked to see. Defined before the button exists so
   level() and search() can both call it. */
function clearNewOnly(){const t=document.querySelector('.tree');
  if(!t||!t.classList.contains('newonly'))return;
  t.classList.remove('newonly');
  document.getElementById('LN').classList.remove('on');}
function search(t){
  t=t.trim().toLowerCase();
  if(!t){level(3);return;}
  clearNewOnly();
  [...nodes].reverse().forEach(li=>{           // deepest first
    const self=li.querySelector(':scope > .row').dataset.n.includes(t);
    const kid=kids(li).some(c=>!c.classList.contains('hide'));
    const show=self||kid;
    li.classList.toggle('hide',!show);
    if(show){
      if(self)[...li.querySelectorAll('li')].forEach(c=>c.classList.remove('hide'));
      li.classList.remove('collapsed');openUp(li);
    }
  });
  const p=nodes.filter(li=>li.classList.contains('t-page')
                        &&!li.classList.contains('hide')).length;
  const f=nodes.filter(li=>(li.classList.contains('t-ent')
                        ||li.classList.contains('t-web'))
                        &&!li.classList.contains('hide')).length;
  hits.textContent=f+' folders · '+p+' pages';
}
let tm;q.addEventListener('input',()=>{clearTimeout(tm);tm=setTimeout(()=>search(q.value),110);});
document.getElementById('L1').onclick=()=>level(1);
document.getElementById('L2').onclick=()=>level(3);
document.getElementById('L3').onclick=()=>level(4);
document.getElementById('L9').onclick=()=>{q.value='';hits.textContent='';clearNewOnly();
  nodes.forEach(li=>{li.classList.remove('hide');li.classList.remove('collapsed');});};

/* Pages this export added carry .is-new from the builder. Every folder above one
   gets a count badge and .has-new, computed here rather than in Python: the
   rollup then cannot disagree with the tree it is describing, and the three node
   builders stay as they were. */
const tree=document.querySelector('.tree');
nodes.forEach(li=>{
  if(li.classList.contains('t-page'))return;
  const n=li.querySelectorAll('li.is-new').length;
  if(!n)return;
  li.classList.add('has-new');
  const b=document.createElement('span');
  b.className='cnt-new';
  b.textContent='+'+n+' new';
  b.title=n+' page'+(n===1?'':'s')+' here that AKU\\u2019s earlier export did not list';
  li.querySelector(':scope > .row').appendChild(b);
});
const bN=document.getElementById('LN');
bN.onclick=()=>{
  const on=tree.classList.toggle('newonly');
  bN.classList.toggle('on',on);
  q.value='';
  nodes.forEach(li=>li.classList.remove('hide'));
  if(on){nodes.forEach(li=>li.classList.remove('collapsed'));
         hits.textContent=document.querySelectorAll('.tree li.is-new').length+' new pages';}
  else{hits.textContent='';setDepth(3);}
};
setDepth(3);
"""

# ---- assemble the page ---------------------------------------------------
def sec(idx, sid, title, lede, body):
    return ('<section id="' + sid + '"><div class="wrap">'
            '<span class="snum">' + idx + '</span>'
            '<h2>' + title + '</h2><p class="lede">' + lede + '</p>'
            + body + '</div></section>')

n_ent = sum(stats[s]['entities'] for s in tree)
tiles = [(f'{len(webs):,}', 'folders'),
         (str(len(tops)), 'site sections'),
         ('6 + global', 'regions'),
         (str(n_ent), 'entity placements'),
         (str(len(decisions)), 'open questions')]

head = ('<header class="top"><div class="wrap">'
        '<h1>aku.edu — the folder and page hierarchy</h1>'
        '<p>Where every page on the university site goes when it moves to '
        'Storyblok: regions at the root, global among them, entities inside their '
        'region. Built by joining the SharePoint permissions export with the page '
        'inventory. Only aku.edu — hospitals.aku.edu and examinationboard.aku.edu '
        'are excluded.</p>'
        '<div class="hero"><div class="hnum">' + f'{len(pages):,}'
        + '<span>pages to move</span></div><div class="tiles">'
        + ''.join('<div class="tile"><b>' + v + '</b><span>' + l + '</span></div>'
                  for v, l in tiles)
        + '</div></div></div></header>')

nav = ('<nav class="jump"><div class="wrap">'
       '<a href="#shape">1 · The shape</a>'
       '<a href="#where">2 · Where the pages are</a>'
       '<a href="#confidence">3 · How certain</a>'
       '<a href="#tree">4 · Browse the tree</a>'
       '<a href="#cross">5 · Cross-region content</a>'
       '<a href="#open">6 · Open questions</a>'
       '<a href="#sources">7 · Sources</a></div></nav>')

s1 = sec('Section 1', 'shape', 'The shape, and the one thing it turns on',
         'Today aku.edu is <b>one flat list of 82 sections</b>. Nothing in it names '
         'a region — the region is hidden inside the slug, the owner group and the '
         'staff directory a page’s editors belong to. The migration’s real '
         'work is pulling those apart, and it is only safe where the export proves '
         'both halves.',
         DIAG_SPLIT + DIAG_TAG)

s2 = sec('Section 2', 'where', 'Where the pages actually are',
         'Two regions hold almost everything. <b>Pakistan has '
         + '{:,}'.format(stats['pakistan']['pages']) + ' pages</b> and global '
         + '{:,}'.format(stats['global']['pages']) + '; Uganda has a full folder '
         'structure but not one page in it yet, and Afghanistan has no section on '
         'aku.edu at all. Plan effort against these bars, not against the '
         'section count.',
         '<div class="card"><h3 class="sub">Pages by region</h3>' + chart_regions
         + '</div><div class="card"><h3 class="sub">The twelve largest sections'
           '</h3>' + chart_sections + '</div>')

s3 = sec('Section 3', 'confidence',
         'How certain each placement is, and what must be tagged by hand',
         'Every placement records the rule that produced it. <b>Witnessed</b> means '
         'the export proves it — a dedicated CW/CA owner group, a majority of staff '
         'logins from one campus directory, or the section’s own title. '
         '<b>Inferred</b> rests only on a naming convention. <b>Needs decision</b> '
         'has no witness at all and is AKU’s call.',
         '<div class="card"><h3 class="sub">The 82 sections by strength of '
         'evidence</h3>' + chart_conf + '</div>'
         '<div class="card"><h3 class="sub">Can the owning entity be derived '
         'automatically?</h3>' + chart_tag
         + '<p class="lede" style="margin:14px 0 0;font-size:13px">'
         + f'{manual_tag:,}' + ' pages sit under a folder that names no '
         'owner — it carries the site’s whole 47-to-93 group roster instead of '
         'an owner group. They fall in these sections, and someone at AKU has to '
         'tag them:</p><ul class="mlist">' + manual_rows + '</ul></div>')

s4 = sec('Section 4', 'tree', 'Browse the full tree',
         'Every one of the ' + f'{len(webs):,}' + ' folders and '
         + f'{len(pages):,}' + ' pages, in the shape they will take. '
         'It opens at entity level — click a row to go deeper, or search for any '
         'region, entity, folder or page. A dot beside a page means <b>move as '
         'is</b>; an amber dot means <b>update, then move</b>; a hollow dot means '
         'AKU has <b>not reviewed it yet</b>, and a grey one that they marked it '
         '<b>unclear</b>. '
         + ('<b>' + f'{n_new:,}' + ' pages</b> carry a green <b>new</b> tag: AKU’s '
            'filtered export lists them and their earlier one did not. Every folder '
            'above one shows how many it holds, and <b>New pages only</b> narrows the '
            'tree to just those. The other ' + f'{len(pages) - n_new:,}' + ' were in '
            'both exports and have not moved.' if n_new else ''),
         '<div class="tbar"><input id="q" type="search" placeholder="Search a '
         'region, entity, folder or page…" autocomplete="off"><span id="hits">'
         '</span><button class="btn" id="L1">Regions</button>'
         '<button class="btn" id="L2">Entities</button>'
         '<button class="btn" id="L3">Folders</button>'
         '<button class="btn" id="LN">New pages only</button>'
         '<button class="btn" id="L9">Expand all</button></div>'
         '<div id="treeview">' + tree_view + '</div>')

s5 = sec('Section 5', 'cross', 'Cross-region and cross-entity content',
         'A folder tree gives each page exactly one parent. The live site does not '
         'honour that, so these five cases are where <b>tagging has to carry what '
         'folders cannot</b>. Every count comes from the export.',
         cross_html)

s6 = sec('Section 6', 'open',
         'Open questions — ' + str(len(decisions)) + ' placements the export does '
         'not settle',
         'These rest on weaker evidence than the rest of the tree. The '
         + str(sum(1 for d in decisions if d[3] == D)) + ' marked <b>needs '
         'decision</b> have no supporting witness at all and should be confirmed '
         'before migration.',
         '<table><tr><th>Placed in</th><th>Entity or section</th><th>Site path</th>'
         '<th>Why it is not certain</th></tr>' + dec_rows + '</table>')

orphan_txt = ', '.join('<span class="mono">' + e(w) + '</span> ('
                       + str(len(pages_by_web[w])) + ' pages)'
                       for w in orphan_webs) or 'none'
s7 = sec('Section 7', 'sources', 'What the two source files cover',
         'Neither file is a superset of the other, which is why both were needed.',
         '<div class="duo"><div class="card"><h3 class="sub" style="margin-top:0">'
         'The permissions export</h3><p class="lede" style="font-size:13.5px">'
         'Lists every folder — <b>' + f'{len(webs):,}' + '</b> under '
         'aku.edu across <b>' + str(len(tops)) + '</b> sections, with the groups '
         'that administer each one. It is the only evidence for sections holding no '
         'page: <span class="mono">/events</span> alone has 48 event microsites and '
         '<span class="mono">/research</span> 18 folders.</p></div>'
         '<div class="card"><h3 class="sub" style="margin-top:0">The page inventory'
         '</h3><p class="lede" style="font-size:13.5px">Covers <b>'
         + f'{len(pages):,}' + '</b> pages but reaches only <b>40</b> of the '
         + str(len(tops)) + ' sections. The other 42 appear as folders with no page '
         '— a real finding, not a gap: their content lives in SharePoint lists '
         '(news, events, blogs), not a Pages library.</p></div></div>'
         '<div class="card"><h3 class="sub" style="margin-top:0">Two loose ends'
         '</h3><p class="lede" style="font-size:13.5px">' + orphan_txt + ' hold '
         'pages that appear in no permission row; they are attached to the nearest '
         'folder the export does know. And <b>Afghanistan</b> has no aku.edu section '
         'whatsoever — it exists only in the news data, where it holds one story.'
         '</p></div>'
         '<div class="card"><h3 class="sub" style="margin-top:0">The words used here'
         '</h3><dl class="gl">'
         '<dt>Folder</dt><dd>A SharePoint <i>web</i> — a folder with its own '
         'permissions. 611 of them under aku.edu.</dd>'
         '<dt>Section</dt><dd>A top-level folder, the first thing after the domain: '
         '<span class="mono">aku.edu/mcpk</span>.</dd>'
         '<dt>CW / CA group</dt><dd>Content Writer and Content Approver. '
         '<span class="mono">CW MC PK</span> is who may edit Medical College '
         'Pakistan, which is how the owning entity is known.</dd>'
         '<dt>Unique scope</dt><dd>A folder with its own permissions rather than its '
         'parent’s. Only these rows name an owner; inherited rows repeat the '
         'AKU-wide groups and prove nothing.</dd>'
         '<dt>Campus directory</dt><dd>The staff login domain — '
         '<span class="mono">aku\\</span> Karachi, <span class="mono">nbi\\</span> '
         'Nairobi, <span class="mono">dar\\</span> Dar es Salaam, '
         '<span class="mono">ismc\\</span> London. A region witness no other column '
         'carries.</dd></dl></div>')

doc = ('<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">\n'
       '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
       '<title>aku.edu — folder and page hierarchy</title>\n<style>' + CSS
       + '</style></head><body>\n' + head + nav
       + s1 + s2 + s3 + s4 + s5 + s6 + s7
       + '<footer><div class="wrap">Built from AKU-EN_1.HTM and the SharePoint 2016 '
         'user-roles mapping · aku.edu only · every folder and page in the export is '
         'accounted for in the tree above</div></footer>\n<script>' + JS
       + '</script></body></html>\n')

# AKU-Folder-Hierarchy.html is RETIRED as of 7 Sep 2026 and is no longer
# written. Two deliverables already showed this same tree: AKU-Tree.html, built
# from plan.json and so unable to disagree with it, and the Hierarchy tab of
# AKU-Migration-Plan.html. This page was built BEFORE the plan, from the source
# webs, so its numbers were a different basis -- 611 source webs against the
# plan's 628 destination folders -- and its prose had drifted out of step with
# its own tables, claiming 19 open questions above a section listing 2. Being
# gitignored, a stale copy could only ever mislead whoever built it, which is
# what happened.
#
# The page is still ASSEMBLED, and deliberately: `decisions`, `stats`, `tree`
# and the tag counts are computed by that code and are what the accounting check
# at the bottom of this file tests. Deleting the 900 lines would take the check
# with them, and the check is the reason this step exists -- it fails the build
# if any web or page would land nowhere. Read the tree in AKU-Tree.html and the
# numbers in out/aku-master-pages.csv.
print('html assembled, %.0f KB — not written, this page is retired'
      % (len(doc.encode('utf-8')) / 1024))
for s in tree:
    print('%-16s ent=%-3d fn=%-3d webs=%-4d pages=%-5d'
          % (s, stats[s]['entities'], stats[s]['functions'],
             stats[s]['webs'], stats[s]['pages']))
# The site root is a web with pages of its own, and both sides of the accounting
# have to say so: its 17 pages belong to no region, so summing the regions alone
# would report them lost.
placed_p = sum(stats[s]['pages'] for s in tree) + (root_web['pages'] if root_web else 0)
placed_w = sum(stats[s]['webs'] for s in tree) + (1 if root_web else 0)
print('TOTAL pages placed', placed_p, 'of', len(pages))
print('TOTAL webs placed', placed_w, 'of', len(webs), '(incl. site root)')
print('auto-taggable', auto_tag, '| manual', manual_tag)
print('decisions', len(decisions))
if placed_p != len(pages) or placed_w != len(webs):
    raise SystemExit('accounting mismatch — every folder and page must land somewhere')
