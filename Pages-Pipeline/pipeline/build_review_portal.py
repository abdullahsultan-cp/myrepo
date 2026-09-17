"""build_review_portal.py -- one HTML file for reviewing the Medical College pages.

Opens by double-clicking, from a bare clone. No Python, no server, no database --
the people reviewing these pages are exactly the people who will never run the
pipeline. See docs/PORTALS.md.

**It bakes an index, not the bodies.** Per page: the title, where it went, the
blok sequence, how many images and galleries, and the three links that matter
(the old aku.edu page, the Storyblok editor, the preview). The body text is left
out -- nobody reads 43 bodies in a review tool, they filter to the ones that look
wrong and open those. That decision is `summarise()` below, and everything it
does not return costs nothing.

Flags are the point of the thing, so they have to be rare enough to mean
something: a page that is nearly empty, or has text but no pictures at all, is
what a reviewer wants to find first. "No hero image" is true of almost every one
of these pages -- SharePoint had no hero to take -- so it is a grey note, not a
red flag. The first cut flagged 39 of 40 and was useless.

Two files come out of one run:

    out/AKU-MC-Pages-Review.html      the portal -- opens from a bare clone
    out/work/review-artifact.html     the same page for publishing as an Artifact

The second exists only because the Artifact host supplies its own doctype, head
and body, so the page has to be authored without them. Everything else -- the
markup, the palette, the script -- is byte-identical between the two.

Run:  python build_review_portal.py
"""
import csv
import html as H
import json
import os

import paths

OUT = paths.out('AKU-MC-Pages-Review.html')
OUT_ARTIFACT = paths.work('review-artifact.html')


def text_len(blok):
    def txt(n):
        if isinstance(n, dict):
            if n.get('type') == 'text':
                return n.get('text', '')
            return ''.join(txt(c) for c in (n.get('content') or []))
        if isinstance(n, list):
            return ''.join(txt(c) for c in n)
        return ''
    return len(txt(blok.get('content')))


def summarise(p, links):
    """Everything the reviewer needs to FIND and JUDGE a page. Not the body."""
    bloks = p['bloks']
    seq, chars, gal_imgs = [], 0, 0
    for b in bloks:
        c = b.get('component')
        if c == 'rich_text':
            chars += text_len(b)
        if c == 'media_section':
            gal_imgs += len(b.get('gallery_images') or [])
            seq.append(f"gallery({len(b.get('gallery_images') or [])})")
        elif c == 'row':
            inner = ''
            items = b.get('items') or []
            if items and items[0].get('body'):
                inner = items[0]['body'][0].get('component', '')
            label = {'link_card': 'cards', 'profile_card': 'profiles',
                     'button': 'buttons'}.get(inner, 'row')
            seq.append(f'{label}({len(items)})')
        elif c == 'info_accordion':
            seq.append(f"accordion({len(b.get('items') or [])})")
        else:
            seq.append(c)
    hero = bloks[0] if bloks else {}
    has_hero_img = bool((hero.get('image') or {}).get('filename')
                        or (hero.get('image') or {}).get('_src_original'))
    imgs = len(p.get('images') or [])
    flags = []
    if chars < 300 and imgs == 0:
        flags.append('nearly empty')
    elif chars < 500:
        flags.append('little text')
    if imgs == 0 and chars >= 300:
        flags.append('no images')
    notes = []
    if not has_hero_img:
        notes.append('no hero image')
    lk = links.get(f"{p['folder']}/{p['slug']}", {})
    return {
        'serial': p['serial'], 'title': p['title'],
        'section': p['folder'].replace('regions/pk/entities/mc/', '') or 'mc',
        'path': f"{p['folder']}/{p['slug']}", 'slug': p['slug'],
        'seq': seq, 'bloks': len(bloks), 'chars': chars, 'images': imgs,
        'galleries': sum(1 for b in bloks if b.get('component') == 'media_section'),
        'gallery_images': gal_imgs, 'flags': flags, 'notes': notes,
        'aku': lk.get('aku_link', ''), 'edit': lk.get('sb_editorial_link', ''),
        'preview': lk.get('sb_preview_link', ''),
        'published': lk.get('published', '') == 'True', 'id': lk.get('story_id', ''),
    }


FONTS = ('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
         'family=IBM+Plex+Mono:wght@400;500&'
         'family=IBM+Plex+Sans:wght@400;500;600&'
         'family=IBM+Plex+Serif:wght@500;600&display=swap">')

# AKU's own maroon, lifted from the site's `color-maroon` class, on neutrals
# biased warm toward it. One accent; state colour is separate and semantic.
CSS = """
:root{
  --ground:#FBF8F7; --surface:#FFFFFF; --raise:#F6F0F0;
  --ink:#1E1819; --muted:#6E6063; --line:#E8DEDF;
  --accent:#7A1F2B; --accent-soft:#F5E6E8; --accent-ink:#7A1F2B;
  --good:#2E6B4F; --good-soft:#E4F0E9;
  --warn:#87671C; --warn-soft:#F6EDD8;
  --bad:#A32C2C; --bad-soft:#FBE7E7;
  --sans:"IBM Plex Sans",system-ui,-apple-system,Segoe UI,sans-serif;
  --serif:"IBM Plex Serif",Georgia,serif;
  --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --ground:#171314; --surface:#201A1B; --raise:#2A2223;
    --ink:#F1EAEA; --muted:#A5969A; --line:#342B2D;
    --accent:#E4808F; --accent-soft:#3A2328; --accent-ink:#F0A9B4;
    --good:#7FC3A1; --good-soft:#20322A;
    --warn:#D9B368; --warn-soft:#332A18;
    --bad:#E98A8A; --bad-soft:#3A2323;
  }
}
:root[data-theme="dark"]{
  --ground:#171314; --surface:#201A1B; --raise:#2A2223;
  --ink:#F1EAEA; --muted:#A5969A; --line:#342B2D;
  --accent:#E4808F; --accent-soft:#3A2328; --accent-ink:#F0A9B4;
  --good:#7FC3A1; --good-soft:#20322A;
  --warn:#D9B368; --warn-soft:#332A18;
  --bad:#E98A8A; --bad-soft:#3A2323;
}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);
     font:400 15px/1.55 var(--sans);-webkit-font-smoothing:antialiased}
.masthead{padding:26px 30px 20px;border-bottom:1px solid var(--line);
     background:var(--surface)}
.eyebrow{font:500 11px/1 var(--mono);letter-spacing:.14em;text-transform:uppercase;
     color:var(--accent-ink);margin:0 0 9px}
h1{margin:0;font:600 27px/1.15 var(--serif);letter-spacing:-.015em;
     text-wrap:balance}
.lede{margin:8px 0 0;max-width:62ch;color:var(--muted);font-size:14px}
.figures{display:flex;flex-wrap:wrap;gap:30px;margin-top:20px}
.fig b{display:block;font:500 25px/1.1 var(--mono);font-variant-numeric:tabular-nums}
.fig span{font:500 10.5px/1 var(--mono);letter-spacing:.1em;text-transform:uppercase;
     color:var(--muted)}
.controls{position:sticky;top:0;z-index:9;display:flex;gap:9px;flex-wrap:wrap;
     align-items:center;padding:12px 30px;background:var(--surface);
     border-bottom:1px solid var(--line)}
#q{flex:1 1 230px;min-width:200px;padding:8px 12px;border:1px solid var(--line);
     border-radius:7px;background:var(--ground);color:var(--ink);font:400 14px var(--sans)}
#q:focus-visible,.chip:focus-visible,a:focus-visible{outline:2px solid var(--accent);
     outline-offset:2px}
.chip{border:1px solid var(--line);background:var(--ground);color:var(--muted);
     border-radius:999px;padding:5px 13px;cursor:pointer;
     font:500 12px var(--mono);letter-spacing:.02em}
.chip:hover{border-color:var(--accent);color:var(--accent-ink)}
.chip[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);
     color:var(--surface)}
.tally{margin-left:auto;font:500 12px var(--mono);color:var(--muted)}
.wrap{padding:20px 30px 70px;overflow-x:auto}
table{width:100%;min-width:760px;border-collapse:collapse;background:var(--surface);
     border:1px solid var(--line);border-radius:10px;overflow:hidden}
th{text-align:left;padding:11px 14px;border-bottom:1px solid var(--line);
     background:var(--raise);cursor:pointer;white-space:nowrap;
     font:500 10.5px/1 var(--mono);letter-spacing:.1em;text-transform:uppercase;
     color:var(--muted)}
th:hover{color:var(--accent-ink)}
td{padding:13px 14px;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:0}
tr:hover td{background:var(--raise)}
.name{font-weight:600;letter-spacing:-.005em}
.path{font:400 11.5px var(--mono);color:var(--muted);word-break:break-all;
     margin-top:2px}
.seq{margin-top:7px;display:flex;flex-wrap:wrap;gap:4px}
.seq i{font-style:normal;font:500 11px var(--mono);padding:2px 7px;border-radius:5px;
     background:var(--raise);color:var(--muted);border:1px solid var(--line)}
.seq i.hi{background:var(--accent-soft);color:var(--accent-ink);border-color:transparent}
.tags{margin-top:7px;display:flex;flex-wrap:wrap;gap:5px}
.flag,.note{font:500 11px var(--mono);padding:2px 7px;border-radius:5px}
.flag{background:var(--bad-soft);color:var(--bad)}
.note{background:var(--raise);color:var(--muted)}
.num{text-align:right;font:400 13px var(--mono);font-variant-numeric:tabular-nums;
     white-space:nowrap;color:var(--muted)}
.pill{display:inline-block;font:500 11px var(--mono);padding:3px 9px;border-radius:999px}
.pill.live{background:var(--good-soft);color:var(--good)}
.pill.draft{background:var(--warn-soft);color:var(--warn)}
.acts{display:flex;flex-direction:column;gap:5px;min-width:116px}
.acts a,.acts button{text-decoration:none;text-align:center;padding:6px 11px;
     border-radius:7px;font:500 12px var(--sans);border:1px solid transparent;
     white-space:nowrap;cursor:pointer}
.all{background:var(--accent);color:var(--surface);font-weight:600!important;
     display:flex;align-items:center;justify-content:center;gap:6px}
.all::before{content:"";width:7px;height:7px;border-radius:2px;
     background:currentColor;opacity:.7;box-shadow:3px 0 0 currentColor,6px 0 0 currentColor}
.all:hover{filter:brightness(1.08)}
.go{background:var(--raise);color:var(--accent-ink);border-color:var(--line)}
.go:hover{border-color:var(--accent)}
.see{border-color:var(--accent);color:var(--accent-ink)}
.see:hover{background:var(--accent-soft)}
.old{border-color:var(--line);color:var(--muted)}
.old:hover{border-color:var(--muted);color:var(--ink)}
tr[hidden]{display:none}
.foot{padding:0 30px 50px;color:var(--muted);font-size:12.5px;max-width:70ch}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
@media (max-width:760px){.masthead,.controls,.wrap,.foot{padding-left:16px;padding-right:16px}}
"""

JS = """
(function(){
  var rows=[].slice.call(document.querySelectorAll('tbody tr'));
  var q=document.getElementById('q');
  var tally=document.getElementById('tally');
  var active={};
  function apply(){
    var s=q.value.toLowerCase().trim(), n=0;
    rows.forEach(function(r){
      var ok=!s||r.dataset.hay.indexOf(s)>-1;
      if(ok&&active.sec&&r.dataset.section!==active.sec) ok=false;
      if(ok&&active.flagged&&!r.dataset.flags) ok=false;
      if(ok&&active.draft&&r.dataset.pub==='1') ok=false;
      if(ok&&active.gallery&&r.dataset.gal==='0') ok=false;
      r.hidden=!ok; if(ok) n++;
    });
    tally.textContent=n+' of '+rows.length+' pages';
  }
  [].forEach.call(document.querySelectorAll('.chip'),function(c){
    c.addEventListener('click',function(){
      var k=c.dataset.k, v=c.dataset.v;
      if(c.getAttribute('aria-pressed')==='true'){
        c.setAttribute('aria-pressed','false'); delete active[k];
      }else{
        if(k==='sec'){
          [].forEach.call(document.querySelectorAll('.chip[data-k=sec]'),function(o){
            o.setAttribute('aria-pressed','false');});
        }
        c.setAttribute('aria-pressed','true'); active[k]=v||true;
      }
      apply();
    });
  });
  q.addEventListener('input',apply);

  // Open all three in one click. `window.open` is blocked in the Artifact's
  // sandboxed iframe, so every tab is opened the way the ordinary links already
  // work: a real anchor with target="_blank", clicked. The element's own href
  // handles the first destination, so at least one tab always opens even if the
  // host blocks the synthetic clicks.
  [].forEach.call(document.querySelectorAll('.all'),function(b){
    b.addEventListener('click',function(){
      (b.dataset.rest||'').split('|').forEach(function(u){
        if(!u) return;
        var a=document.createElement('a');
        a.href=u; a.target='_blank'; a.rel='noopener';
        a.style.display='none';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
      });
    });
  });
  [].forEach.call(document.querySelectorAll('th[data-k]'),function(th){
    var dir=1;
    th.addEventListener('click',function(){
      var k=th.dataset.k, tb=document.querySelector('tbody');
      rows.sort(function(a,b){
        var x=a.dataset[k], y=b.dataset[k];
        var nx=parseFloat(x), ny=parseFloat(y);
        if(!isNaN(nx)&&!isNaN(ny)) return (nx-ny)*dir;
        return String(x).localeCompare(String(y))*dir;
      });
      dir*=-1; rows.forEach(function(r){tb.appendChild(r);});
    });
  });
  apply();
})();
"""

HILITE = ('gallery', 'cards', 'profiles', 'buttons', 'accordion',
          'split_section', 'author_section')


def build_rows(items):
    out = []
    for n, i in enumerate(items, 1):
        seq = ''.join(
            f'<i class="{"hi" if any(h in s for h in HILITE) else ""}">'
            f'{H.escape(s)}</i>' for s in i['seq'])
        tags = ''.join(f'<span class="flag">{H.escape(f)}</span>' for f in i['flags'])
        tags += ''.join(f'<span class="note">{H.escape(f)}</span>'
                        for f in i.get('notes', []))
        hay = H.escape(
            f"{i['title']} {i['path']} {i['serial']} {' '.join(i['flags'])}".lower(),
            quote=True)
        # One button opens all three at once -- comparing a page means having the
        # editor, the rendered page and the original side by side, and clicking
        # three links per row for 43 rows is the actual work.
        # The master control is an ANCHOR, not a button. Inside the Artifact
        # host the page runs in a sandboxed iframe where `window.open` is
        # blocked outright -- the first version used it and opened nothing,
        # while the plain target="_blank" links beside it worked fine. So the
        # first destination opens natively through the href, and the click
        # handler opens the rest the same way, by clicking real anchors.
        trio = [u for u in (i['edit'], i['preview'], i['aku']) if u]
        acts = []
        if len(trio) > 1:
            acts.append(
                f'<a class="all" href="{H.escape(trio[0])}" target="_blank" '
                f'rel="noopener" data-rest="{H.escape("|".join(trio[1:]), quote=True)}">'
                f'Open all {len(trio)}</a>')
        if i['edit']:
            acts.append(f'<a class="go" href="{H.escape(i["edit"])}" '
                        f'target="_blank" rel="noopener">Edit</a>')
        if i['preview']:
            acts.append(f'<a class="see" href="{H.escape(i["preview"])}" '
                        f'target="_blank" rel="noopener">Preview</a>')
        if i['aku']:
            acts.append(f'<a class="old" href="{H.escape(i["aku"])}" '
                        f'target="_blank" rel="noopener">Old page</a>')
        state = ('<span class="pill live">live</span>' if i['published']
                 else '<span class="pill draft">draft</span>')
        out.append(
            f'<tr data-hay="{hay}" data-section="{H.escape(i["section"])}" '
            f'data-flags="{"x" if i["flags"] else ""}" '
            f'data-pub="{1 if i["published"] else 0}" data-gal="{i["galleries"]}" '
            f'data-title="{H.escape(i["title"])}" data-images="{i["images"]}" '
            f'data-chars="{i["chars"]}" data-serial="{i["serial"]}">'
            f'<td class="num">{n}</td>'
            f'<td><div class="name">{H.escape(i["title"])}</div>'
            f'<div class="path">{H.escape(i["path"])}</div>'
            f'<div class="seq">{seq}</div>'
            f'<div class="tags">{tags}</div></td>'
            f'<td class="num">{i["chars"]:,}</td>'
            f'<td class="num">{i["images"]}</td>'
            f'<td>{state}</td>'
            f'<td><div class="acts">{"".join(acts)}</div></td></tr>')
    return ''.join(out)


def page_body(items, sections, stats):
    chips = ''.join(
        f'<button class="chip" data-k="sec" data-v="{H.escape(s)}" '
        f'aria-pressed="false">{H.escape(s)}</button>' for s in sections)
    figures = ''.join(f'<div class="fig"><b>{v}</b><span>{k}</span></div>'
                      for k, v in stats)
    return f"""<div class="masthead">
  <p class="eyebrow">Medical College, Pakistan &middot; migration review</p>
  <h1>Pages rebuilt from aku.edu</h1>
  <p class="lede">Every page now living under
    <code>regions/pk/entities/mc/</code>. Open <strong>Edit</strong> for Storyblok,
    <strong>Preview</strong> for the rendered page, <strong>Old page</strong> for
    the original on aku.edu &mdash; the three you need side by side to check one.</p>
  <p class="lede">To check the old page against the new one without switching
    tabs, open <a href="AKU-MC-Page-Compare.html"><strong>AKU-MC-Page-Compare.html</strong></a>
    &mdash; both pages in one window with a divider you drag across them.</p>
  <div class="figures">{figures}</div>
</div>
<div class="controls">
  <input id="q" type="search" placeholder="Search title, path or flag&hellip;"
         aria-label="Search pages">
  {chips}
  <button class="chip" data-k="flagged" aria-pressed="false">flagged</button>
  <button class="chip" data-k="draft" aria-pressed="false">drafts</button>
  <button class="chip" data-k="gallery" aria-pressed="false">has gallery</button>
  <span class="tally" id="tally"></span>
</div>
<div class="wrap">
  <table>
    <thead><tr>
      <th>#</th><th data-k="title">Page &amp; blok sequence</th>
      <th class="num" data-k="chars">Text</th><th class="num" data-k="images">Images</th>
      <th data-k="pub">State</th><th>Open</th>
    </tr></thead>
    <tbody>{build_rows(items)}</tbody>
  </table>
</div>
<p class="foot">Chips in maroon are the components that replaced plain prose:
galleries recovered from SharePoint lists, card rows, profile splits and
accordions. A red flag means content may be missing; a grey note is expected
&mdash; almost none of these pages had a hero image to take.</p>"""


def main():
    pay = json.load(open(paths.work('page_payloads.json'), encoding='utf-8'))
    # ONE links file, the current one. Merging an older copy in as a fallback
    # put 25 deleted pages back on the board -- a review tool that lists stories
    # which no longer exist is worse than one that lists too few.
    links = {}
    for name in ('rabee-pages-links-v2.csv', 'rabee-pages-links.csv'):
        p = paths.out(name)
        if os.path.exists(p):
            for r in csv.DictReader(open(p, encoding='utf-8')):
                links[r['storyblok_path']] = r
            break
    items = [summarise(p, links) for p in pay
             if f"{p['folder']}/{p['slug']}" in links]
    have = {i['path'] for i in items}
    for path, r in links.items():
        if path in have:
            continue
        items.append({'serial': r['serial'], 'title': r['title'],
                      'section': path.replace('regions/pk/entities/mc/', '').rsplit('/', 1)[0],
                      'path': path, 'slug': path.rsplit('/', 1)[-1],
                      'seq': ['built by hand'], 'bloks': 0, 'chars': 0, 'images': 0,
                      'galleries': 0, 'gallery_images': 0, 'flags': [], 'notes': [],
                      'aku': r.get('aku_link', ''), 'edit': r.get('sb_editorial_link', ''),
                      'preview': r.get('sb_preview_link', ''),
                      'published': r.get('published') == 'True',
                      'id': r.get('story_id', '')})
    items.sort(key=lambda x: (x['section'], x['slug']))

    sections = sorted({i['section'] for i in items})
    stats = [('pages', len(items)),
             ('images', sum(i['images'] for i in items)),
             ('galleries', sum(i['galleries'] for i in items)),
             ('flagged', sum(1 for i in items if i['flags'])),
             ('sections', len(sections))]
    body = page_body(items, sections, stats)
    title = 'AKU Medical College Page Review'

    standalone = (f'<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
                  f'<meta name="viewport" content="width=device-width,initial-scale=1">\n'
                  f'<title>{title}</title>\n{FONTS}\n<style>{CSS}</style>\n</head>\n'
                  f'<body>\n{body}\n<script>{JS}</script>\n</body>\n</html>\n')
    open(OUT, 'w', encoding='utf-8', newline='\n').write(standalone)

    # The Artifact host wraps the file in its own doctype/head/body, so this
    # variant carries only the title, styles, markup and script.
    artifact = (f'<title>{title}</title>\n{FONTS}\n<style>{CSS}</style>\n'
                f'{body}\n<script>{JS}</script>\n')
    os.makedirs(os.path.dirname(OUT_ARTIFACT), exist_ok=True)
    open(OUT_ARTIFACT, 'w', encoding='utf-8', newline='\n').write(artifact)

    print(f'{len(items)} pages')
    print(f'  portal   -> {OUT}  ({os.path.getsize(OUT) / 1024:.0f} KB)')
    print(f'  artifact -> {OUT_ARTIFACT}  ({os.path.getsize(OUT_ARTIFACT) / 1024:.0f} KB)')
    print(f'  {stats[3][1]} flagged, {stats[2][1]} galleries, {stats[1][1]} images')


if __name__ == '__main__':
    main()
