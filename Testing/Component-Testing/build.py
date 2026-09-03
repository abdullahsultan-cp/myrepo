#!/usr/bin/env python3
"""build.py — generate index.html: every Storyblok component, every variant.

Two halves, because this repo only builds a fraction of the space:

  Part 1  the ~14 bloks this migration pipeline actually emits (rich_text,
          image, media_section, quote_banner, split_section, button,
          brand_banner/brand_logo, social_embed, article_language_link, iframe,
          plus the three root article types). Each variant is rendered with
          real field names, real option values and real asset URLs, all pulled
          from storyblok_space/ and the reference story
          News-Pipeline/data/migrate/demo/200437344487526.json -- nothing here
          is invented.

  Part 2  all 97 components in the space, auto-generated from
          storyblok_space/components.json so it cannot drift from what the
          dev's schema actually says. This covers the site-wide components
          (header, footer, hero, carousels, programme pages, ...) that no
          pipeline in this repo touches -- CLAUDE.md is explicit that only the
          dev edits those schemas, so Part 2 is a read-only reference, not a
          rendering: there is no CSS for them in this repo to render against.

This is a mockup for visual QA of payload shape, not the live site design --
the real templates live in the dev's own front-end app, not here.

Run:
    python Testing/Component-Testing/build.py
"""
import html
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

COMPONENTS_JSON = os.path.join(ROOT, "storyblok_space", "components.json")
GROUPS_JSON = os.path.join(ROOT, "storyblok_space", "component_groups.json")
OUT_HTML = os.path.join(HERE, "index.html")

# Real asset URLs, lifted from the one demo story every field in Part 1 is
# checked against: News-Pipeline/data/migrate/demo/200437344487526.json
A = {
    "banner": "https://a.storyblok.com/f/289824742951963/2000x1324/ae04c901e5/photo_29.jpg",
    "portrait": "https://a.storyblok.com/f/289824742951963/366x427/10b4a15217/saman_barkat.png",
    "pattern": "https://a.storyblok.com/f/289824742951963/1440x811/0305b10066/web-pattern.png",
    "quote_bg": "https://a.storyblok.com/f/289824742951963/375x184/c65753b5c0/quote-backgroung.png",
    "video_thumb": "https://a.storyblok.com/f/289824742951963/2560x1707/229e9b326a/instititue.png",
    "gallery": [
        "https://a.storyblok.com/f/289824742951963/2463094/b298c53b1d/3405-richtext-25644d4383-wed_speakers.jpg",
        "https://a.storyblok.com/f/289824742951963/6926416/22a1c04449/3405-richtext-1a4c2d5e97-nakawa-1.JPG",
        "https://a.storyblok.com/f/289824742951963/731143/87e178a16c/3405-richtext-fa084ba4e8-nairobi2.jpg",
        "https://a.storyblok.com/f/289824742951963/166016/5e477b3e07/3405-richtext-483b2c4339-nairobi1.jpg",
        "https://a.storyblok.com/f/289824742951963/227240/1086c1da3b/3405-richtext-8c6e8cc738-dar-1.jpeg",
    ],
    "logo": "https://a.storyblok.com/f/289824742951963/91x113/000957a952/isqua.png",
}


def e(s):
    return html.escape(str(s), quote=True)


# ---------------------------------------------------------------- Part 1
# One render function per component this pipeline emits. `live=True` marks a
# variant seen in the reference story or in a live 3606-story payload;
# `live=False` marks one that exists in the schema but this repo has never
# produced -- shown so the page is honestly a variant CATALOG, not a claim
# that every combination has been proven in production.


def badge(live):
    return ('<span class="tag tag-live">seen in a real payload</span>' if live
            else '<span class="tag tag-schema">schema only &mdash; not yet '
                 'produced by this pipeline</span>')


def blok(name, source, variant_label, live, body):
    return f"""
    <article class="blok" id="{e(name)}-{e(variant_label)}">
      <header class="blok-head">
        <h3>{e(name)} <code>{e(variant_label)}</code></h3>
        {badge(live)}
      </header>
      <p class="src">{source}</p>
      <div class="preview">{body}</div>
    </article>"""


def section_rich_text():
    body = """
      <div class="rt">
        <h2>A heading, as it comes out of SharePoint</h2>
        <p>Launched under AKU's Research Strategic Plan, the RISE Programme is
        an Early Career Research Academy designed to equip faculty with the
        essential skills needed for a successful research career &mdash;
        <a href="#">a link</a>, some <strong>bold</strong> and
        <em>italic</em>, and a superscript<sup>1</sup>.</p>
        <ul><li>Grant success</li><li>Collaboration across regions</li>
        <li>Career development</li></ul>
        <blockquote>&ldquo;Far more than writing successful grants.&rdquo;
        &mdash; Prof. Salim S. Virani</blockquote>
      </div>
      <p class="meta">spacing = SPACING_TEXT (mobile 20px / desktop
      176px &mdash; the narrow reading column) &middot; bg_pattern, pattern_height,
      pattern_mobile_height available, usually empty</p>"""
    return blok("rich_text", "pipeline/migrate/upload/build_payload.py "
                "&middot; rich_text_blok()", "default", True, body)


def section_image():
    out = []
    out.append(blok("image", "build_payload.py &middot; image_blok() "
                    "&mdash; a lone body image, kept inside the flow",
                    "variant=image", True,
                    f'<img class="img-inline" src="{A["portrait"]}" '
                    'alt="body image"><p class="meta">spacing = '
                    'SPACING_MID (20px / 80px)</p>'))
    out.append(blok("image", "schema option, not used by this pipeline "
                    "&mdash; the standalone blok renders too large for an "
                    "inline illustration (see build_payload.py comment)",
                    "variant=hero", False,
                    f'<img class="img-hero" src="{A["banner"]}" '
                    'alt="hero image">'))
    return "".join(out)


def section_iframe():
    body = f"""
      <div class="iframe-mock">
        <img src="{A['video_thumb']}" alt="">
        <div class="play">&#9658;</div>
        <span class="src-label">src: https://aku-dev.vercel.app/</span>
      </div>
      <p class="meta">display_mode=inline &middot; aspect_ratio=16:9 &middot;
      content_align=left &middot; spacing = SPACING_MID</p>
      <p class="meta">other schema options &mdash; not seen live:
      display_mode: lightbox, button &middot;
      aspect_ratio: 4:3, 1:1, 21:9, 3:2, 9:16 &middot;
      content_align: center, right</p>"""
    return blok("iframe", "build_payload.py &middot; iframe_blok() "
                "&mdash; a tweet or other embed, in place", "inline / 16:9",
                True, body)


def section_media_section():
    out = []
    out.append(blok("media_section", "build_payload.py &middot; "
                    "media_section_video()", "type=video", True, f"""
      <div class="video-card">
        <img src="{A['video_thumb']}" alt="">
        <div class="play">&#9658;</div>
      </div>
      <p class="meta">video_url = youtube.com/watch?v=9dDpy3jwn4c (or a
      hosted file) &middot; spacing = SPACING_FULL (no side padding)</p>"""))
    gal = "".join(f'<img src="{u}" alt="">' for u in A["gallery"])
    out.append(blok("media_section", "build_payload.py &middot; "
                    "media_section_gallery() &mdash; 2+ images, appended at "
                    "the point they occur, or at the end if unpositioned",
                    "type=gallery, gallery_layout=simple", True,
                    f'<div class="gallery-simple">{gal}</div>'
                    '<p class="meta">spacing = SPACING_MID</p>'))
    out.append(blok("media_section", "schema default, not emitted &mdash; "
                    "this pipeline always sets gallery_layout explicitly to "
                    "\"simple\"", "type=gallery, gallery_layout=staggered",
                    False,
                    f'<div class="gallery-staggered">{gal}</div>'))
    out.append(blok("media_section", "schema option, not used &mdash; the "
                    "pipeline uses the standalone image blok for a single "
                    "picture instead", "type=image", False,
                    f'<img class="img-hero" src="{A["banner"]}" alt="">'))
    return "".join(out)


def section_quote_banner():
    out = []
    out.append(blok("quote_banner", "build_payload.py &middot; "
                    "quote_banner_blok() &mdash; every pull quote with no "
                    "accompanying image", "variant=centered", True, f"""
      <div class="quote-card" style="background-image:url({A['quote_bg']})">
        <p class="q">&ldquo;In the practice of medicine, knowledge and
        ethics must walk hand in hand.&rdquo;</p>
        <p class="attrib">&mdash; President Sulaiman Shahabuddin</p>
        <p class="cat">Convocation</p>
      </div>
      <p class="meta">date, category and portrait left empty unless the
      source gives them &middot; spacing = SPACING_FULL</p>"""))
    out.append(blok("quote_banner", "schema option, not produced by this "
                    "pipeline", "variant=attributed", False, f"""
      <div class="quote-card" style="background-image:url({A['quote_bg']})">
        <img class="quote-portrait" src="{A['portrait']}" alt="">
        <p class="q">Sample attributed quote text.</p>
        <p class="attrib">&mdash; Someone, Some Title</p>
      </div>"""))
    out.append(blok("quote_banner", "schema option, not produced by this "
                    "pipeline &mdash; has its own event_label / date_label "
                    "fields", "variant=event", False, f"""
      <div class="quote-card" style="background-image:url({A['quote_bg']})">
        <p class="q">Sample event quote text.</p>
        <p class="attrib">event_label &middot; date_label</p>
      </div>"""))
    return "".join(out)


def section_split_section():
    out = []
    out.append(blok("split_section", "build_payload.py &middot; "
                    "split_section_blok() &mdash; a pull quote WITH an "
                    "image: quote left, portrait right",
                    "layout=default, image_variant=default", True, f"""
      <div class="split">
        <img src="{A['portrait']}" alt="">
        <div class="split-text">
          <p>&ldquo;I am thankful to ELE_net and the team to support us at
          every step possible.&rdquo;</p>
          <p class="attrib">Saman Barkat</p>
        </div>
      </div>"""))
    out.append(blok("split_section", "schema option, not produced by this "
                    "pipeline", "layout=reverse", False, f"""
      <div class="split split-reverse">
        <div class="split-text">
          <p>Same content, image and text swap sides.</p>
        </div>
        <img src="{A['portrait']}" alt="">
      </div>"""))
    return "".join(out)


def section_button():
    out = []
    out.append(blok("button", "reference story &middot; label=\"TEST\"",
                    "variant=primary, icon=none", True,
                    '<button class="btn btn-primary">TEST</button>'
                    '<p class="meta">field is <code>Spacing</code> '
                    '(capital S) &mdash; the one blok that spells it '
                    'differently &middot; 20px / 80px</p>'))
    out.append(blok("button", "schema option, not produced by this "
                    "pipeline", "variant=secondary, icon=arrow-right", False,
                    '<button class="btn btn-secondary">Learn more '
                    '&rarr;</button>'))
    return "".join(out)


def section_brand_banner():
    logos = "".join(f'<img src="{A["logo"]}" alt="">' for _ in range(5))
    out = []
    out.append(blok("brand_banner + brand_logo", "reference story "
                    "&middot; variant=normal, 5 logos", "variant=normal",
                    True,
                    f'<div class="brand-row brand-normal">{logos}</div>'
                    '<p class="meta">spacing = SPACING_FULL (no padding)'
                    '</p>'))
    out.append(blok("brand_banner + brand_logo", "schema default, not "
                    "produced by this pipeline", "variant=hover-grayscale",
                    False, f'<div class="brand-row brand-gray">{logos}</div>'))
    return "".join(out)


def section_social_embed():
    variants = [
        ("twitter", "the shared change: iframe -> social_embed for a tweet "
         "(pipeline/migrate/update/_template.py)"),
        ("facebook", "schema option, not produced by this pipeline"),
        ("instagram", "schema option, not produced by this pipeline"),
    ]
    out = []
    for v, note in variants:
        live = v == "twitter"
        out.append(blok("social_embed", note, f"variant={v}", live, f"""
      <div class="social-card social-{e(v)}">
        <span class="platform">{e(v)}</span>
        <p>url &middot; align=center &middot; show_text=true</p>
      </div>"""))
    return "".join(out)


def section_article_language_link():
    body = ('<span class="pill">urdu &rarr; PDF, uploaded to Storyblok'
            '</span><p class="meta">one per real alternate language; '
            '"Photo gallery" and similar labels are dropped, not '
            'mislabelled as a translation</p>')
    return blok("article_language_link", "build_payload.py &mdash; one per "
                "real alternate language", "default", True, body)


def section_roots():
    roots = [
        ("news_article", "3,606 live", "News-Pipeline"),
        ("blog_article", "83 live", "Blogs-Pipeline"),
        ("event_article", "2,710 live", "Events-Pipeline"),
    ]
    cards = "".join(f"""
      <div class="root-card">
        <h4>{e(name)}</h4>
        <p>{e(count)} &middot; {e(pipe)}</p>
      </div>""" for name, count, pipe in roots)
    return f"""
    <article class="blok">
      <header class="blok-head"><h3>the three root article types</h3></header>
      <p class="src">each is a component in its own right (is_root=true) that
      assembles the bloks above into `body` &mdash; see
      pipeline/migrate/upload/build_payload.py</p>
      <div class="root-cards">{cards}</div>
    </article>"""


PART1_SECTIONS = [
    ("rich_text", section_rich_text),
    ("image", section_image),
    ("iframe", section_iframe),
    ("media_section", section_media_section),
    ("quote_banner", section_quote_banner),
    ("split_section", section_split_section),
    ("button", section_button),
    ("brand_banner", section_brand_banner),
    ("social_embed", section_social_embed),
    ("article_language_link", section_article_language_link),
    ("root types", section_roots),
]


# ---------------------------------------------------------------- Part 2

def load_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def field_row(fname, f):
    t = f.get("type")
    opts = f.get("options")
    optvals = ", ".join(str(o.get("value")) for o in opts) if opts else ""
    default = f.get("default_value")
    default = "" if default in (None, "") else e(default)
    return f"""<tr><td><code>{e(fname)}</code></td><td>{e(t)}</td>
      <td>{e(optvals)}</td><td>{default}</td></tr>"""


def component_card(c):
    name = c["name"]
    disp = c.get("display_name") or name
    schema = c.get("schema") or {}
    rows = "".join(field_row(fn, f) for fn, f in schema.items())
    flags = []
    if c.get("is_root"):
        flags.append('<span class="tag tag-root">root</span>')
    if c.get("is_nestable"):
        flags.append('<span class="tag tag-nestable">nestable</span>')
    table = (f"""<table class="field-table"><thead><tr><th>field</th>
      <th>type</th><th>options</th><th>default</th></tr></thead>
      <tbody>{rows}</tbody></table>""" if rows else
             '<p class="meta">no fields</p>')
    return f"""
      <details class="component-card" id="c-{e(name)}">
        <summary><span class="cname">{e(disp)}</span>
        <code>{e(name)}</code> {''.join(flags)}
        <span class="field-count">{len(schema)} field
        {'s' if len(schema) != 1 else ''}</span></summary>
        {table}
      </details>"""


def build_part2():
    data = load_json(COMPONENTS_JSON)
    comps = sorted(data["components"], key=lambda c: c["name"])
    groups = load_json(GROUPS_JSON)
    group_name = {g["uuid"]: g["name"] for g in groups}

    by_group = {}
    for c in comps:
        gname = group_name.get(c.get("component_group_uuid"), "ungrouped")
        by_group.setdefault(gname, []).append(c)

    out = []
    for gname in sorted(by_group):
        cards = "".join(component_card(c) for c in by_group[gname])
        out.append(f"""
        <section class="group">
          <h3 class="group-title">{e(gname)}
          <span class="group-count">{len(by_group[gname])}</span></h3>
          {cards}
        </section>""")
    return "".join(out), len(comps)


CSS = """
:root{
  --bg:#f7f7f5; --panel:#fff; --ink:#1c1c1a; --sub:#6b6b64; --line:#e4e3de;
  --accent:#0f6b5c; --accent-soft:#e4f2ef;
  --warn:#8a5a00; --warn-soft:#fbeed4;
}
@media (prefers-color-scheme: dark){
  :root{ --bg:#15161a; --panel:#1c1e24; --ink:#eceef0; --sub:#9a9ea6;
    --line:#2b2e36; --accent:#5fd6b8; --accent-soft:#173330;
    --warn:#e0b04a; --warn-soft:#3a2f12; }
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
header.page{padding:32px 40px 20px;border-bottom:1px solid var(--line)}
header.page h1{margin:0 0 6px;font-size:22px}
header.page p{margin:0;color:var(--sub);max-width:70ch}
nav.toc{display:flex;flex-wrap:wrap;gap:8px;padding:16px 40px;
  border-bottom:1px solid var(--line);position:sticky;top:0;
  background:var(--bg);z-index:5}
nav.toc a{font-size:12px;color:var(--sub);text-decoration:none;
  padding:4px 9px;border:1px solid var(--line);border-radius:100px;
  background:var(--panel)}
nav.toc a:hover{color:var(--ink);border-color:var(--accent)}
main{padding:8px 40px 80px;max-width:1100px;margin:0 auto}
h2.part{margin:40px 0 4px;font-size:18px}
p.part-note{color:var(--sub);margin:0 0 20px;max-width:80ch}
.blok{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  padding:18px 20px;margin:0 0 16px}
.blok-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.blok-head h3{margin:0;font-size:15px}
.blok-head code{font-size:12px;color:var(--accent);font-weight:600}
.src{color:var(--sub);font-size:12px;margin:6px 0 14px}
.tag{font-size:10.5px;text-transform:uppercase;letter-spacing:.03em;
  padding:2px 8px;border-radius:100px;white-space:nowrap}
.tag-live{background:var(--accent-soft);color:var(--accent)}
.tag-schema{background:var(--warn-soft);color:var(--warn)}
.tag-root{background:var(--accent-soft);color:var(--accent)}
.tag-nestable{background:var(--line);color:var(--sub)}
.preview{border-top:1px dashed var(--line);padding-top:14px}
.meta{color:var(--sub);font-size:12px;margin:10px 0 0}
.rt h2{font-size:16px;margin:0 0 8px}
.rt p{margin:0 0 10px}
.rt blockquote{margin:0;padding:10px 16px;border-left:3px solid var(--accent);
  color:var(--sub)}
img{max-width:100%;display:block;border-radius:6px}
.img-inline{max-width:320px}
.img-hero{width:100%;max-height:280px;object-fit:cover}
.iframe-mock{position:relative;max-width:480px}
.iframe-mock img{max-height:260px;object-fit:cover;width:100%}
.play{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
  width:52px;height:52px;border-radius:50%;background:rgba(0,0,0,.55);
  color:#fff;display:flex;align-items:center;justify-content:center;
  font-size:18px}
.src-label{position:absolute;bottom:8px;left:8px;background:rgba(0,0,0,.6);
  color:#fff;font-size:11px;padding:2px 8px;border-radius:4px}
.video-card{position:relative;max-width:420px}
.video-card img{max-height:220px;object-fit:cover;width:100%}
.gallery-simple{display:grid;grid-template-columns:repeat(5,1fr);gap:6px}
.gallery-staggered{display:grid;grid-template-columns:2fr 1fr 1fr;gap:6px}
.gallery-staggered img:first-child{grid-row:span 2}
.gallery-simple img,.gallery-staggered img{height:110px;
  object-fit:cover;width:100%}
.quote-card{background-size:cover;background-position:center;padding:24px;
  border-radius:8px;max-width:520px;color:#1c1c1a}
.quote-card .q{font-size:15px;font-style:italic;margin:0 0 8px}
.quote-card .attrib{font-weight:600;margin:0}
.quote-card .cat{color:var(--sub);font-size:12px;margin:4px 0 0}
.quote-portrait{width:56px;height:56px;border-radius:50%;
  object-fit:cover;margin-bottom:10px}
.split{display:flex;gap:18px;align-items:center;max-width:560px}
.split img{width:160px;border-radius:8px;flex:none}
.split-reverse{flex-direction:row-reverse}
.split-text p{margin:0 0 8px}
.split-text .attrib{font-weight:600;color:var(--accent)}
.btn{border:none;border-radius:6px;padding:11px 22px;font-size:13px;
  font-weight:600;cursor:default}
.btn-primary{background:var(--accent);color:#fff}
.btn-secondary{background:transparent;color:var(--accent);
  border:1.5px solid var(--accent)}
.brand-row{display:flex;gap:24px;align-items:center;padding:12px 0}
.brand-row img{width:60px;height:auto}
.brand-gray img{filter:grayscale(1);opacity:.6}
.social-card{border:1px solid var(--line);border-radius:8px;padding:14px 16px;
  max-width:340px}
.social-card .platform{font-weight:700;text-transform:capitalize;
  color:var(--accent)}
.pill{display:inline-block;background:var(--accent-soft);color:var(--accent);
  padding:4px 12px;border-radius:100px;font-size:12px;font-weight:600}
.root-cards{display:flex;gap:12px;flex-wrap:wrap}
.root-card{border:1px solid var(--line);border-radius:8px;padding:12px 16px;
  min-width:160px}
.root-card h4{margin:0 0 4px;font-size:13px}
.root-card p{margin:0;color:var(--sub);font-size:12px}

/* Part 2 */
.group{margin:0 0 28px}
.group-title{font-size:13px;text-transform:uppercase;letter-spacing:.04em;
  color:var(--sub);border-bottom:1px solid var(--line);padding-bottom:6px;
  margin:0 0 10px}
.group-count{font-weight:400;color:var(--sub)}
.component-card{background:var(--panel);border:1px solid var(--line);
  border-radius:8px;margin:0 0 8px;padding:0}
.component-card summary{cursor:pointer;padding:10px 14px;font-size:13px;
  display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.component-card summary .cname{font-weight:600}
.component-card summary code{color:var(--accent);font-size:11.5px}
.field-count{margin-left:auto;color:var(--sub);font-size:11.5px}
.field-table{width:100%;border-collapse:collapse;font-size:12px;
  margin:0 14px 14px;width:calc(100% - 28px)}
.field-table th{text-align:left;color:var(--sub);font-weight:500;
  border-bottom:1px solid var(--line);padding:5px 8px}
.field-table td{padding:5px 8px;border-bottom:1px solid var(--line)}
.field-table code{color:var(--accent)}
"""


def main():
    part1 = "".join(fn() for _name, fn in PART1_SECTIONS)
    part1_toc = "".join(
        f'<a href="#{e(name)}">{e(name)}</a>' for name, _fn in PART1_SECTIONS)
    part2, n_all = build_part2()

    html_out = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AKU &middot; Storyblok component testing</title>
<style>{CSS}</style>
</head>
<body>
<header class="page">
  <h1>Component testing</h1>
  <p>Every blok this migration pipeline builds, every variant its schema
  allows, and the full 97-component space schema for reference &mdash;
  generated by <code>Testing/Component-Testing/build.py</code> from
  <code>storyblok_space/components.json</code> and the reference story
  <code>News-Pipeline/data/migrate/demo/200437344487526.json</code>. This is a
  payload-shape mockup for visual QA, not the live site design &mdash; the real
  templates live in the dev's own front-end app.</p>
</header>
<nav class="toc">{part1_toc}<a href="#part2">full space schema</a></nav>
<main>
  <h2 class="part">Part 1 &middot; what this pipeline builds</h2>
  <p class="part-note">Green tag = seen in a real, live payload (the
  reference story or a published run). Amber tag = a variant the schema
  allows but this pipeline has never produced &mdash; shown so this is a
  complete catalog, not a claim of production coverage.</p>
  {part1}

  <h2 class="part" id="part2">Part 2 &middot; every component in the space
  ({n_all})</h2>
  <p class="part-note">Auto-generated from storyblok_space/components.json,
  grouped the way the dev grouped them in Storyblok. Field tables only &mdash;
  most of these (header, footer, hero, carousels, programme pages, ...) are
  page-builder components no pipeline in this repo touches, and there is no
  CSS here to render them against. Re-run build.py after
  pipeline/migrate/spaces/dump refreshes components.json to keep this in
  sync.</p>
  {part2}
</main>
</body>
</html>"""

    with open(OUT_HTML, "w", encoding="utf-8", newline="\n") as f:
        f.write(html_out)
    print(f"-> {OUT_HTML}  ({len(html_out) / 1024:.0f} KB, "
          f"{len(PART1_SECTIONS)} rendered blok types, {n_all} in the full "
          f"schema)")


if __name__ == "__main__":
    main()
