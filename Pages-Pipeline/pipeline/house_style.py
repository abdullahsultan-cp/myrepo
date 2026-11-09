"""house_style.py -- how Abdullah wants a page's body laid out. Imported, never run.

Every rule here is one he gave, or corrected by hand, while fixing pages one at
a time on 5 Nov 2026 (the IED Dar es Salaam, Chitral and Gilgit library pages).
build_from_sheet.py and fix_page.py both call `layout()`, so a rule lives in
one place.

  heading + plain text        -> faculty_publications GROUPED: one group per
                                 heading, one item holding the text. A heading
                                 that is a link puts it in the group's `link`.
  linked name + description   -> faculty_publications (default): one item per
                                 entry -- name in `title`, URL in `link`, text in
                                 `description`. Online Books, Online Databases.
  a list of plain bullets     -> sub_inner_group, variant outcomes, one item each
  a list of linked bullets    -> sub_inner_group, variant links, one item each
                                 ("Free Resources")
  anything else under a head  -> its OWN rich_text: H1, centred, not bold, the
                                 last word #008F51, an empty line after it,
                                 paragraphs centred
  a short intro before a publications block goes in that block's `description`

A "heading" is a real heading, or a paragraph that opens with a bold name and a
line break -- SharePoint wrote "<strong>General Collection</strong><br>This is
the main collection..." far more often than it wrote <h2>.
"""
import copy
import re

import build_pages as bp

GREEN = '#008F51'
INVISIBLE = dict.fromkeys(map(ord, '​﻿­'), None)


def clean(t):
    return re.sub(r'\s+', ' ', (t or '').translate(INVISIBLE).replace('\xa0', ' ')).strip()


def text_of(n):
    return clean(bp.flat_text(n))


def marks(t):
    return {m.get('type') for m in t.get('marks') or []}


def href_of(t):
    return next((m['attrs'].get('href') or '' for m in t.get('marks') or []
                 if m.get('type') == 'link'), '')


def link(h):
    if not h:
        return {'id': '', 'url': '', 'linktype': 'story', 'fieldtype': 'multilink', 'cached_url': ''}
    return {'id': '', 'url': h, 'linktype': 'url', 'fieldtype': 'multilink', 'cached_url': h}


def strip_invisibles(x):
    """Zero-width characters out of every text node. Never trims: a text node
    is half a sentence (root CLAUDE.md §7)."""
    if isinstance(x, dict):
        if x.get('type') == 'text':
            x['text'] = x['text'].translate(INVISIBLE)
        for v in x.values():
            strip_invisibles(v)
    elif isinstance(x, list):
        for v in x:
            strip_invisibles(v)
        x[:] = [v for v in x if not (isinstance(v, dict) and v.get('type') == 'text' and not v['text'])]
    return x


def trim_breaks(n):
    c = n.get('content') or []
    while c and c[0].get('type') == 'hard_break':
        c.pop(0)
    while c and c[-1].get('type') == 'hard_break':
        c.pop()
    return n


# --------------------------------------------------------------- headings ---
def split_heading(t):
    """"Library Membership" -> ("Library ", "Membership"); one word -> (word, "")."""
    t = clean(t)
    head, _, last = t.rpartition(' ')
    return (head + ' ', last) if head else (t, '')


def house_heading(title):
    a, b = split_heading(title)
    content = [{'type': 'text', 'text': title}] if not b else [
        {'type': 'text', 'text': a},
        {'type': 'text', 'text': b, 'marks': [{'type': 'textStyle', 'attrs': {'color': GREEN}}]}]
    return {'type': 'heading', 'attrs': {'level': 1, 'textAlign': 'center'}, 'content': content}


def centred(nodes):
    for n in nodes:
        if n.get('type') in ('paragraph', 'heading'):
            n['attrs'] = {**(n.get('attrs') or {}), 'textAlign': 'center'}
    return nodes


def lead_title(n, plain_ok=False):
    """A paragraph that is really a heading -> (title, href, remainder-or-None).

    Two shapes, both measured on the library pages:
      <strong>Name</strong><br>text...      name, then the text in the same <p>
      <a><strong>Name</strong></a>          the whole paragraph is the name
    """
    if n.get('type') != 'paragraph':
        return None
    kids = n.get('content') or []
    texts = [k for k in kids if k.get('type') == 'text' and k['text'].strip()]
    if not texts:
        return None
    lead = []
    for k in kids:
        if k.get('type') == 'hard_break':
            break
        if k.get('type') == 'text' and not k['text'].strip():
            lead.append(k)
            continue
        if k.get('type') == 'text' and ('bold' in marks(k) or href_of(k) or plain_ok):
            lead.append(k)
            continue
        return None                     # plain text before any break: prose
    title = clean(''.join(k['text'] for k in lead))
    if not title or len(title) > 120 or title.endswith(('.', ':')):
        return None
    if not any('bold' in marks(k) or href_of(k) for k in lead):
        # An unbolded name is only a name among bolded ones -- "Content Alert"
        # between "Mobile Library" and "Article Indexing" on Gilgit Services --
        # and only with the line break that marks it.
        if not (plain_ok and len(title) <= 60 and any(k.get('type') == 'hard_break' for k in kids)):
            return None
    href = next((href_of(k) for k in lead if href_of(k)), '')
    rest = kids[len(lead):]
    if rest and rest[0].get('type') != 'hard_break':
        return None
    rest = [k for k in rest]
    body = trim_breaks({**n, 'content': rest}) if rest else None
    if body is not None and not text_of(body):
        body = None
    return title, href, body


# --------------------------------------------------------------- segment ----
def segment(nodes):
    """Body nodes -> [('intro', [nodes])] + [('section', title, href, kind, [nodes])].

    kind is 'heading' for a real heading, 'name' for a bold/linked paragraph.
    """
    out, cur = [], None
    filled = [n for n in nodes if text_of(n) or n.get('type') in ('table', 'image')]
    pos = {id(n): i for i, n in enumerate(filled)}

    def described(n):
        """Is this lone name followed by a paragraph that describes it?"""
        k = pos.get(id(n))
        nx = filled[k + 1] if k is not None and k + 1 < len(filled) else None
        return bool(nx and nx.get('type') == 'paragraph' and not lead_title(nx))

    for n in nodes:
        # SharePoint editors set whole sentences as headings ("Thank you for
        # registering ... other details."). That is prose, not a title.
        if n.get('type') == 'heading' and (len(text_of(n)) > 120 or
                                           (text_of(n).endswith('.') and len(text_of(n)) > 60)):
            n = {**n, 'type': 'paragraph', 'attrs': {}}
        if n.get('type') == 'heading' and text_of(n):
            t = [k for k in n.get('content') or [] if k.get('type') == 'text']
            cur = ['section', text_of(n), next((href_of(k) for k in t if href_of(k)), ''), 'heading', []]
            out.append(cur)
            continue
        if n.get('type') == 'heading':
            continue                    # an empty heading is a spacer the editor left
        lt = lead_title(n, plain_ok=cur is not None and cur[3] == 'name')
        # Under a real heading, a lone linked line with nothing describing it
        # ("Observatory on Borderless Higher Education") is part of that
        # section. One followed by its description (Online Databases: "JSTOR",
        # then a paragraph about JSTOR) is an entry of its own.
        if lt and lt[2] is None and cur is not None and cur[3] == 'heading' and not described(n):
            lt = None
        if lt:
            title, href, body = lt
            cur = ['section', title, href, 'name', [body] if body else []]
            out.append(cur)
            continue
        if not (text_of(n) or n.get('type') in ('table', 'image')):
            continue
        if cur is None:
            if not out or out[-1][0] != 'intro':
                out.append(['intro', []])
            out[-1][1].append(n)
        else:
            cur[4].append(n)
    return out


def inline_link(li):
    """True when a list item has a link INSIDE a longer sentence -- not a list
    item that IS a link (those are a link list: sub_inner_group links)."""
    for c in li.get('content') or []:
        texts = [k for k in c.get('content') or [] if k.get('type') == 'text' and k['text'].strip()]
        linked = ''.join(k['text'] for k in texts if href_of(k)).strip()
        if linked and len(linked) < len(text_of(c)) * 0.8:
            return True
    return False


def list_items(n):
    """[(label, href)] for a bullet/ordered list, flattening nested lists."""
    out = []
    for li in n.get('content') or []:
        for c in li.get('content') or []:
            if c.get('type') in ('bullet_list', 'ordered_list'):
                out += list_items(c)
            elif text_of(c):
                ts = [k for k in c.get('content') or [] if k.get('type') == 'text']
                out.append((text_of(c), next((href_of(k) for k in ts if href_of(k)), '')))
    return out


def table_links(n):
    """A layout table of links (the "Free Resources" grid) -> [(label, href)]."""
    out = []

    def walk(x):
        if isinstance(x, dict):
            if x.get('type') in ('paragraph', 'list_item') and text_of(x):
                ts = [k for k in (x.get('content') or []) if k.get('type') == 'text']
                h = next((href_of(k) for k in ts if href_of(k)), '')
                if h and x.get('type') == 'paragraph':
                    out.append((text_of(x), h))
                    return
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(n)
    return out


# --------------------------------------------------------------- bloks ------
def publications(uid, key, variant, title=''):
    t, h = split_heading(title) if title else ('', '')
    return {'_uid': uid(key), 'component': 'faculty_publications', 'variant': variant,
            'title': t, 'highlight': h, 'heading': '', 'description': '',
            'cta_label': '', 'cta_link': link(''), 'profile_label': '', 'profile_link': link(''),
            'nav_label': '', 'paginate': False, 'per_page': '6', 'collapsible': False,
            'spacing_preset': 'section', 'items': [], 'groups': []}


def pub_item(uid, key, title, href, nodes):
    nodes = [trim_breaks(copy.deepcopy(n)) for n in nodes]
    for n in nodes:
        if n.get('type') in ('paragraph', 'heading'):
            n['attrs'] = {'textAlign': None}
    return {'_uid': uid(key), 'component': 'faculty_publication_item', 'title': title,
            'link': link(href), 'description': {'type': 'doc', 'content': nodes},
            'group_title': '', 'group_link': link('')}


def sub_group(uid, key, pairs, title=''):
    t, h = split_heading(title) if title else ('', '')
    linked = pairs and all(h_ for _, h_ in pairs)
    base = {'_uid': uid(key), 'component': 'sub_inner_group', 'title': t, 'highlight': h,
            'description': '', 'align': 'center', 'columns': '2', 'spacing_preset': 'section'}
    if linked:
        return {**base, 'variant': 'links',
                'items': [{'_uid': uid(f'{key}-{i}'), 'component': 'sub_inner_group_item',
                           'label': lab, 'link': link(u)} for i, (lab, u) in enumerate(pairs)]}
    return {**base, 'variant': 'outcomes',
            'outcome_items': [{'_uid': uid(f'{key}-{i}'), 'component': 'sub_inner_group_outcome_item',
                               'label': lab} for i, (lab, _) in enumerate(pairs)]}


def section_text(uid, key, title, nodes, preset='section'):
    body = [house_heading(title), {'type': 'paragraph', 'attrs': {'textAlign': 'center'}}] if title else []
    return {'_uid': uid(key), 'component': 'rich_text', 'drop_cap': False, 'spacing_preset': preset,
            'content': {'type': 'doc', 'content': body + centred([copy.deepcopy(n) for n in nodes])}}


# --------------------------------------------------------------- layout -----
def plain_only(nodes):
    return all(n.get('type') in ('paragraph', 'blockquote') for n in nodes)


def layout(nodes, uid, allowed=None):
    """One rich_text's nodes -> the bloks of the house style, in source order."""
    def ok(c):
        return not allowed or c in allowed

    nodes = strip_invisibles(copy.deepcopy(nodes))
    segs = segment(nodes)
    out = []
    pubs = None                          # the publications block being filled

    def close():
        nonlocal pubs
        if pubs is not None and not pubs['items'] and not pubs['groups']:
            # titled and described, then nothing followed: keep the words as text
            words = [{'type': 'paragraph', 'content': [{'type': 'text', 'text': pubs['description']}]}]                 if pubs['description'] else []
            out[out.index(pubs)] = section_text(uid, pubs['_uid'] + '-0',
                                                (pubs['title'] + pubs['highlight']).strip(), words)
            pubs = None
        if pubs is not None and pubs['variant'] == 'default' and len(pubs['items']) == 1 \
                and not pubs['title']:
            # one linked line is a sentence with a link in it, not a directory
            # ("Do you find the Teaching Tips useful? ... by emailing:")
            it = pubs['items'][0]
            words = [{'type': 'paragraph', 'content': [
                {'type': 'text', 'text': it['title'],
                 'marks': [{'type': 'link', 'attrs': {'href': it['link']['url'], 'uuid': None,
                                                      'anchor': None, 'target': '_blank',
                                                      'linktype': 'url'}}] if it['link']['url'] else []}]}]
            out[out.index(pubs)] = section_text(uid, pubs['_uid'] + '-1', '',
                                                words + it['description']['content'])
            pubs = None
        if pubs is not None:
            if pubs['variant'] == 'grouped' and len(pubs['groups']) == 1 and not pubs['description']:
                g = pubs['groups'][0]          # one group alone is just a section
                out[out.index(pubs)] = section_text(uid, pubs['_uid'] + '-1', g['title'],
                                                    g['items'][0]['description']['content'])
            pubs = None

    for i, s in enumerate(segs):
        if s[0] == 'intro':
            close()
            nxt = segs[i + 1] if i + 1 < len(segs) else None
            intro = s[1]
            # a short intro right before the entries is the block's description
            if (nxt and nxt[0] == 'section' and len(intro) == 1 and plain_only(intro)
                    and len(text_of(intro[0])) <= 400 and ok('faculty_publications')
                    and plain_only(nxt[4])):
                out.append({'_intro': text_of(intro[0])})
                continue
            lists = [n for n in intro if n.get('type') in ('bullet_list', 'ordered_list')]
            if lists and len(lists) == len(intro) and ok('sub_inner_group'):
                for k, n in enumerate(lists):
                    out.append(sub_group(uid, f'intro-list-{i}-{k}', list_items(n)))
                continue
            out.append(section_text(uid, f'intro-{i}', '', intro))
            continue

        _, title, href, kind, body = s
        if kind == 'name' and not href:
            href = next((href_of(t) for n in body for t in (n.get('content') or [])
                         if t.get('type') == 'text' and href_of(t)), '')
        # "Membership -- The library offers membership to the following:" is
        # not an entry: it names and introduces the entries under it.
        nxt = segs[i + 1] if i + 1 < len(segs) else None
        if (nxt and nxt[0] == 'section' and plain_only(nxt[4])
                and (not body and kind == 'heading'
                     or len(body) == 1 and len(text_of(body[0])) <= 300
                     and text_of(body[0]).endswith(':'))
                and ok('faculty_publications')):
            close()
            pubs = publications(uid, f'pubs-{i}', 'default' if nxt[3] == 'name' and nxt[2] else 'grouped',
                                title)
            pubs['description'] = text_of(body[0]) if body else ''
            out.append(pubs)
            continue
        lists = [n for n in body if n.get('type') in ('bullet_list', 'ordered_list')]
        # A table is a link list only when its words ARE the links ("Free
        # Resources"). Chief-guest and best-graduate tables are data, and
        # reading only their linked cells dropped 2,000 characters a page.
        tables = [n for n in body if n.get('type') == 'table'
                  and len(''.join(lab for lab, _ in table_links(n)).replace(' ', '')) >= 0.8 * len(text_of(n).replace(' ', ''))]
        if any(n.get('type') == 'table' for n in body) and len(tables) < len(
                [n for n in body if n.get('type') == 'table']):
            lists = []                  # a data table: keep the section as text
            tables = []
        # Bullets with a link INSIDE their sentence ("...through its support to
        # the University Research Council, the apex...") cannot go in a
        # sub_inner_group: its items are plain labels and the links are lost.
        # They become a grouped publications block -- one group named after the
        # heading, one item per bullet, the bullet's rich text (links and all)
        # as the description (Abdullah, ORIC, 9 Nov 2026).
        if lists and not tables and ok('faculty_publications') and \
                len(lists) == len([n for n in body if n.get('type') != 'paragraph']) and \
                any(inline_link(li) for n in lists for li in n.get('content') or []):
            close()
            p = publications(uid, f'pubs-list-{i}', 'grouped', title)
            intro = [n for n in body if n.get('type') == 'paragraph']
            if intro and len(intro) == 1 and len(text_of(intro[0])) <= 400:
                p['description'] = text_of(intro[0])
            elif intro:
                out.append(section_text(uid, f'pubs-list-intro-{i}', title, intro))
            p['groups'] = [{'_uid': uid(f'pubs-list-g-{i}'), 'component': 'faculty_publication_group',
                            'title': title, 'link': link(''),
                            'items': [pub_item(uid, f'pubs-list-{i}-{k}', '', '',
                                               [c for c in li.get('content') or []
                                                if c.get('type') == 'paragraph'] or li.get('content') or [])
                                      for n in lists for k, li in enumerate(n.get('content') or [])]}]
            out.append(p)
            continue
        if (lists or tables) and ok('sub_inner_group') and \
                len(lists) + len(tables) == len([n for n in body if n.get('type') != 'paragraph']):
            close()
            pairs = []
            for n in body:
                if n.get('type') in ('bullet_list', 'ordered_list'):
                    pairs += list_items(n)
                elif n.get('type') == 'table':
                    pairs += table_links(n)
            intro = [n for n in body if n.get('type') == 'paragraph']
            sg = sub_group(uid, f'sig-{i}', pairs, title)
            if intro and len(intro) == 1 and len(text_of(intro[0])) <= 400:
                sg['description'] = text_of(intro[0])
            elif intro:
                out.append(section_text(uid, f'sig-intro-{i}', title, intro))
                sg['title'], sg['highlight'] = '', ''
            out.append(sg)
            continue
        if plain_only(body) and ok('faculty_publications'):
            variant = 'default' if kind == 'name' and href else 'grouped'
            # an unlinked name inside a run of linked names is still an item
            # (Pennsylvania State University Electronic Classics Site)
            if pubs is not None and pubs['variant'] == 'default' and (kind == 'name' or href):
                variant = 'default'
            if pubs is None or pubs['variant'] != variant:
                close()
                pubs = publications(uid, f'pubs-{i}', variant)
                if out and '_intro' in out[-1]:
                    pubs['description'] = out.pop()['_intro']
                out.append(pubs)
            if variant == 'default':
                pubs['items'].append(pub_item(uid, f'pub-{i}', title, href, body))
            else:
                pubs['groups'].append({'_uid': uid(f'grp-{i}'), 'component': 'faculty_publication_group',
                                       'title': title, 'link': link(href),
                                       'items': [pub_item(uid, f'grp-{i}-0', '', '', body)]})
            continue
        close()
        out.append(section_text(uid, f'sec-{i}', title, body))
    close()
    # an intro that found no block to describe stays as text
    return [section_text(uid, f'intro-left-{k}', '', [{'type': 'paragraph', 'content': [
        {'type': 'text', 'text': b['_intro']}]}]) if '_intro' in b else b for k, b in enumerate(out)]


def rebuild_navigator(nav, soup, uid, absolute):
    """A library_navigator's libraries rebuilt from the page's own side nav.

    Copied navigators were wrong on 6 of 7 IED Dar es Salaam pages and most of
    Chitral and Gilgit: the sub-pages pointed at another library (FHS, FAS).
    """
    # the left menu is zz1_ on library pages, zz3_ on QTL -- any V4QuickLaunchMenu
    root = soup.select_one('[id$=V4QuickLaunchMenu] ul.root')
    if root is None:
        return nav

    def items(ul):
        out = []
        for li in ul.find_all('li', recursive=False):
            a = li.find('a', recursive=False)
            if not a or not a.get('href'):
                continue
            lab = re.sub(r'\s*Currently selected$', '',
                         clean((a.select_one('.menu-item-text') or a).get_text(' ', strip=True)))
            sub = li.find('ul', recursive=False)
            out.append((lab, absolute(a.get('href')), items(sub) if sub else []))
        return out
    tree = items(root)
    if not tree:
        return nav
    top = tree[0]
    nav = copy.deepcopy(nav)
    nav['eyebrow'] = nav.get('eyebrow') or top[0]

    def flat(kids):
        # library_nav_page has no children: a third level follows its parent
        # in order, so no sidebar link is dropped (Wellness UG, 9 Nov 2026)
        for kl, kh, sub in kids:
            yield kl, kh
            yield from flat(sub)
    nav['libraries'] = [{
        '_uid': uid(f'lib-{i}'), 'component': 'library_nav_item', 'name': lab, 'short_name': lab,
        'link': link(h),
        'pages': [{'_uid': uid(f'lib-{i}-{j}'), 'component': 'library_nav_page', 'label': kl,
                   'link': link(kh)} for j, (kl, kh) in enumerate(flat(kids))]}
        for i, (lab, h, kids) in enumerate(top[2])]
    return nav


# --------------------------------------------------------- inside cards -----
def card_text(nodes):
    """Tidy the text inside an accordion card or a split_section beside a picture.

    Abdullah, QTL Teaching Tips (6 Nov 2026): "inside accordions headings are
    bold and look bad, if sub heading then h5 and do not make headings bold".
      * a short paragraph that is ALL bold is a sub-heading -> heading level 5,
        bold removed (links and other marks kept)
      * a real heading of any level -> level 5, bold removed; "1.Silent" -> "1. Silent"
      * empty spacer paragraphs go, and line breaks at a paragraph's edges
    A bold phrase that opens a sentence ("**Direct students' attention** Consider
    using...") is emphasis, not a heading, and is left alone.
    """
    out = []
    for n in strip_invisibles(copy.deepcopy(nodes)):
        kind = n.get('type')
        texts = [k for k in n.get('content') or [] if k.get('type') == 'text' and k['text'].strip()]
        all_bold = bool(texts) and all('bold' in marks(k) for k in texts)
        # A bold line that links somewhere or states a fact is emphasis, not a
        # sub-heading: "Application form: https://forms.gle/..." and
        # "Application fee is PKR 1,500 (non-refundable)" (AKU Challenge, 6 Nov 2026).
        fact = any(href_of(k) for k in texts) or bool(
            re.search(r'\b(is|are|was|were|will|must|can|should)\b|\d[\d,]{2,}', text_of(n)))
        if kind == 'heading' or (kind == 'paragraph' and all_bold and len(text_of(n)) <= 120
                                 and not fact):
            kids = []
            for k in n.get('content') or []:
                if k.get('type') == 'hard_break':
                    continue
                k = dict(k)
                ms = [m for m in k.get('marks') or [] if m.get('type') != 'bold']
                if ms:
                    k['marks'] = ms
                else:
                    k.pop('marks', None)
                kids.append(k)
            if kids:
                kids[0]['text'] = re.sub(r'^(\d+)\.(?=\S)', r'\1. ', kids[0]['text'].lstrip())
                kids[-1]['text'] = kids[-1]['text'].rstrip()
            kids = [k for k in kids if k.get('type') != 'text' or k['text']]
            if kids:
                out.append({'type': 'heading', 'attrs': {'level': 5}, 'content': kids})
            continue
        if kind == 'paragraph':
            n = trim_breaks(n)
            if not text_of(n) and not any(k.get('type') == 'image' for k in n.get('content') or []):
                continue
        out.append(n)
    return out
