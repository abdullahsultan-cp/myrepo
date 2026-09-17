# MC-PK — the conversion rules, and why each one exists

How archived aku.edu HTML becomes Storyblok bloks. **Every rule here came from
something going wrong, or from Rabee correcting a page by hand** — the reason is
written down because that is what stops it being undone.

Implemented in [pipeline/build_pages.py](pipeline/build_pages.py) unless said
otherwise. Read with [MC-PK-STATUS.md](MC-PK-STATUS.md).

> These rules also live in Claude's local memory, which is **per machine and does
> not travel with the repo**. This file is the copy that does. If you are on a
> new machine, this file is the source of truth.

---

## 1 · The two standing instructions

**`spacing_preset` is always `"subsection"`, and the legacy `spacing` field
plugin is never written.** Rabee, 13 Sep 2026: *"use spacing preset subsection no
matter what condition i will change by my self if i need to"*. One value
everywhere beats a clever per-component default he then has to undo.

The one exception is his own: a **row** owning its spacing carries
`spacing_preset: "section"` while the thing inside it carries `"zero"`. That
pairing appears in his button rows and in the footer row (§6).

**Never touch another person's pages, and do not use `last_author` to decide
which are which.** `regions/pk/entities/mc/` holds 1,300 stories and only **75**
are Rabee's: 840 are Abdullah Sultan's, 325 Jahanzaib Akhter's, 58 were last
saved by `System Administrator` and are not his, and 2 carry his name but are
`news_article` stories from the news migration.

The authoritative list is **`out/rabee-pages-links-v2.csv`** — 75 rows with
`storyblok_path` and `story_id`. An ownership test on `last_author` fails both
ways: it skips the 5 of his that read `System Administrator` because he re-saved
them in the editor, and it picks up 2 news stories that are not pages.

---

## 2 · Use the rich-text slot, never the plain field

Where a component offers both a plain field (`text`/`textarea`) and a rich-text
slot (a `richtext` field, or `bloks` whitelisted to `rich_text`), **fill the
rich-text one.** Rabee, 15 Sep: *"instead of text where ever you find rich text
use rich text variant"* — *"in any component"*.

`info_accordion_item` has both `content` (textarea) and `body` (bloks →
`rich_text`). Using `content` flattens the panel to one string: every link, list,
heading, table and picture inside it is gone. That silently dropped **39 nested
sub-lists, 61 images, 13 tables and every link from 275 accordion panels across
23 pages**, and read as "data is missing or not formatted".

Of all 157 live components, only these have a rich-text slot:

| component | slot |
|---|---|
| `rich_text` | `content` |
| `row_item` | `body` |
| `info_accordion_item` | **`body`** |
| `info_accordion_card` | `rich_text` |
| `iframe` | `description` |
| `newsletter_intro` | `body` |
| `news_article` / `blog_article` / `event_article` | `body` |

`split_section.description`, `link_card.description` and `profile_card.bio` are
textarea-only. There is no rich variant to switch to, and component schemas are
not ours to change.

**Read the live schema, not the committed CSV.** `storyblok_space/component_fields.csv`
was two dozen components out of date and did not list `info_accordion_item.body`
at all, which is exactly how it was missed. Refresh it with
`python pipeline/migrate/review/list_components.py --fields`.

**The components endpoint ignores `?page=`** and returns the whole set every
time, so a paginating loop never terminates. Fetch once, or dedupe by name.

---

## 3 · Rich text: the shapes that bite

**Nested lists arrive in two forms and only one is legal HTML.** SharePoint's
editor indents by opening a `<ul>` as a **sibling** of the `<li>` it belongs
under:

```html
<ul><li>Governance</li><ul><li>The Chancellor</li>…</ul></ul>
```

A browser still draws that as a sub-list. Walking only
`find_all('li', recursive=False)` never visits it — that dropped the whole
governance list from `mc/home` and two-thirds of the equipment list from `jrl`.
Handle both the sibling form and the legal nested form.

**`image` is a BLOCK node, not inline.** A paragraph's content may hold only
`text` and `hard_break`. Sixty images were being written inside paragraph content
where the renderer has no rule for them. Lift them out **in place** — split the
paragraph around the image so the picture stays where the author put it
(`lift_images()`). Headings can carry one too: two researcher pages open with the
portrait inside the `<h2>`.

**A text node is a fragment. Never trim one.** Inside rich text the renderer
concatenates adjacent text nodes, so the space at a node's edge is the space
between two sentences. `clean_frag` does not strip; `clean_value` does, because a
title is a whole value.

Validate with `validate_document()` from `pipeline/core/storyblok_richtext.py`
before writing. It is the same validator 3,606 published news stories passed.

---

## 4 · The JavaScript widgets — where most of the content is

SharePoint webparts ship an **empty div** and let JavaScript fill it from a list:
`ReadAccordion`, `galleryapp`, `ReadTiles`, `ReadTabs`. None of that content is
in the HTML. `recover_widgets.py` pulls it from AKU's REST API, which is
anonymously open:

```
/_api/web/lists/getbytitle('NAME')/items
```

**The div's position is the widget's position.** Place it where the div sits, not
at the end of the page — appending them put Location and Contact after an
accordion on a page where the live site shows neither there.

**A widget whose div is absent is a dead initialiser. Skip it, never append.**
Seven residency pages carry two `ReadAccordion` calls for one list with only one
target div: the webpart was deleted and its script left behind, so the live page
draws one accordion. Appending the orphan published **the whole accordion twice**
on all seven.

**`$select` naming a column the list does not have is a 400 for the whole
request** — not a missing key — and the old code returned an empty list with no
error. ccbp's `Tabs` has no `OrderBy`, so the Publications page published blank.
It now falls back to requesting every column. Four pages were hollow for this
reason:

| page | before | after |
|---|---|---|
| `ccbp/publications` | 12 chars | 2,578 |
| `mchrtc/fayaz-umrani` | 111 | 8,324 |
| `mchrtc/amnat` | 88 | 2,074 |
| `mchrtc/imran-memon` | 77 | 943 |

`recover_widgets.py` **merges, never replaces** its output file. An earlier
`--only` run overwrote it and discarded 781 recovered images.

---

## 5 · AKU's page patterns → components

**The full-width message banner → `split_section`.**
AKU's `FullWidthRowNews3` strip — photograph, heading, sub-line, LEARN MORE:

| legacy | Storyblok |
|---|---|
| `div.div-pad-bot.title1` | `title` |
| `div.div-pad-bot` (only when another block follows) | `highlight` — **the name only** |
| `div.div-pad-bot2` | `description` |
| `img.pic-circle` / `.pic-circle-right` | `image_variant: "circles"` |
| otherwise | `image_variant: "default"` |
| `a.button-hero` | `cta_label` (lowercased) + `cta_link` |

The sub-line is a person's name and role, or a kicker. Folding it into
`description` runs the name into their first sentence. **Drop the role** —
"Dr Robyna Irshad Khan, Associate Dean Allied Health" became
"Dr Robyna Irshad Khan", because the heading already says "Associate Dean's
Message". Trim only that shape: a comma, a short lead-in, no sentence
punctuation before it. A kicker with no comma ("Every Gift Matters") stays whole.

**Match on `.title1`**, which every variant carries. Matching on
`chairsmsg|pic-circle` catches only the circular version — CITRIC has two square
ones and both were flattened into prose.

**The CTA resolves to the migrated page** where one exists: `cta_link` becomes a
`story` link on `cached_url`, not an aku.edu URL, because the old site is being
switched off. Where the target is not built yet, keep the aku.edu URL so it can
be found and replaced later (`migrated_dest()` reads
`out/rabee-pages-links-v2.csv`).

**The three footer columns → one `row`.**

```
footer.noindex > div.BottomMain > div.container > div.row
    > div.col-md-4.col-sm-4.BottomPane1  > webpart cell
    > div.col-md-4.col-sm-4.BottomPane2
    > div.col-md-4.col-sm-4.BottomPane3
```

One `row_item` per column in column order, each wrapping its `rich_text`
unchanged. Row: `alignment: start`, `on_mobile_wrap: false`,
`spacing_preset: "section"`, `background_color: #ffffff`. Item:
`width_mode: "auto"`. Inner rich_text: `spacing_preset: "zero"`.

Match `^BottomPane[1-9]$` **anchored at both ends** — `ContentBottomPane` is the
main content pane, and matching it loosely sweeps the page body into the footer
row. Fewer than two filled columns is not a row.

**Other shapes already handled:** `div.containerimg1` overlay tiles → `link_card`
in a row; a narrow image column beside a wide text column → `split_section`;
`div.AKUTabs` rendered into the page (no init call) → its panes; a people grid →
`row` > `row_item` > `profile_card`; a picture-beside-text table →
`split_section` rather than a bordered grid.

**Split sections alternate down the page** — picture left, right, left. A
post-pass sets it, so the zig-zag is a property of the page rather than of
whichever rule produced each one.

---

## 6 · What is not content

**A hidden webpart is not on the live page.** Skip a cell when `display:none`
covers what it actually says — measured on text, because the two cases are
otherwise identical in shape. Animal Facility's hidden webparts hide 100% of
their cell's text; a faculty profile's `ValidationSummary` div hides 0% of its
310 characters. Testing for "contains a hidden div" threw whole pages away.
CITRIC's anniversary banner is hidden this way and correctly does not migrate.

**A form is not content.** A cell with three or more `input`/`textarea`/`select`
elements is a form the reader fills in, not prose. The faculty profile's reads
"Your Name * Your email * Subject * Message *".

**A picture library's form page is not a picture.** `/Forms/DispForm.aspx` is the
image-properties screen, needs a login, returns 401, and arrives looking like a
`src` because SharePoint points a thumbnail at it.

**Do not invent buttons.** Only links carrying `buttonStyle`/`button`/`btn`, and
never one marked `displaynone`.

---

## 7 · The guards, and why they are there

**The retention guard refuses to write a page that keeps under 70% of its source
text.** A picture-then-bio rule once took the Certification page from 2,548
characters to 153 and nothing said a word. Counting is cheap; finding that by eye
was not.

**Prove the shape before touching the tree.** The same incident happened because
a rule extracted elements and then discarded groups under 80 characters, firing
on an article with three inline images.

**Never delete and re-upload a story.** Update in place. A new id breaks every
review link already shared and loses manual edits.

**Never create a content folder.** `regions/` belongs to the front-end developer;
`create_pages.py` hard-stops on a missing one.

**Back up immediately after anything that writes** — after, not before. Storyblok
keeps no version history, so the read-back archive is the only record.

**`204 No Content` is success** on an asset PUT and a folder DELETE.

**Look up an asset folder before creating one.** Storyblok does not reject a
duplicate name under one parent; it makes a second folder. The space once reached
769 asset folders, 444 of them redundant.

**Assets go at the story's own path**, not in a separate `Migration/` tree —
`regions/pk/entities/mc/<section>`. Rabee, 15 Sep: *"the assets should be on same
path as their story"*.

**Cache downloads on the whole source path, not the basename.** Every recovered
gallery numbers its pictures from 1, so two galleries both have `1.jpg` and the
second would silently get the first one's photograph.
