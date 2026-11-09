# How an aku.edu page becomes a Storyblok page

Read off **530 pages the team built by hand** (the 5 Nov 2026 sheet, all
"Ready for testing"). For each one, the old aku.edu HTML was compared with the
story read back from Storyblok. Every number below is a count across those
530 pages, not an estimate. `build_from_sheet.py` applies the rules marked
**auto**; the rest are a person's call and are left for you.

---

## Running it for a new batch of pages

```bash
cd Pages-Pipeline/pipeline
python fetch_sheet_pages.py --csv <sheet.csv>      # old HTML + widget lists -> out/work/sheet_pages/
python fetch_reference.py   --csv <sheet.csv>      # sibling pages + live schemas (Storyblok, GET only)
python build_from_sheet.py  --csv <sheet.csv>      # -> out/work/sheet_payloads.json
python upload_page_media.py --payloads sheet_payloads.json            # dry run, then --apply
python create_pages.py      --payloads sheet_payloads.json            # dry run, then --apply --only <serials>
python score_against_reference.py                  # how close the build is to pages already built
```

The sheet is the team's export: `Serial No., Page Name, Old URL, Storyblok Path`.

**What `create_pages.py` refuses, and why:**
- **A story that already exists.** It is probably someone's hand-built page, so
  it is skipped unless you pass `--update-existing`.
- **A page that lost text.** If a page keeps under 70% of its source text, the
  build marks it `content_lost` and the page is skipped.
- **A missing folder.** It never creates a folder.

Stories are created as **drafts**. Every hand-built page is published; publishing
stays a person's decision.

## Fixing one existing page

```bash
cd Pages-Pipeline/pipeline
python fix_page.py <editor-url-or-story-id> <old-aku-url>             # dry run: shows before/after
python fix_page.py <editor-url-or-story-id> <old-aku-url> --apply     # write in place, unpublished
python fix_page.py <editor-url-or-story-id> <old-aku-url> --apply --publish
```

It keeps the story's content type, name, slug and hero, and rebuilds the body
in the house style below. It refuses to write when the story changed while it
was building, the build keeps under 70% of the old page's text, a blok does not
fit the live schema, or a picture is not uploaded. Backups before and after go
to `backup/storyblok/fixes/`.

## House style (`house_style.py`, the default)

These are Abdullah's rules, taken from his own corrections on the library pages
(5 Nov 2026). They replace the team-average layout described further down. Use
`build_from_sheet.py --style team` to get that layout back.

| on the old page | becomes |
|---|---|
| heading (or **bold name**) + plain text | `faculty_publications` **grouped**: one group per heading (`link` = the heading's link), each holding one item with an empty title and the text as its description |
| linked name + description (Online Books, Online Databases) | `faculty_publications` **default**: one item per entry, with the name as title, the URL as link and the text as description. A bold name with the link inside its text uses that link |
| a short line ending in ":" or an empty heading right before the entries | that block's `title`/`highlight` and `description` |
| bullet list of plain text | `sub_inner_group` **outcomes**, one item per bullet, titled with the heading |
| bullet list or table of links ("Free Resources") | `sub_inner_group` **links**, one item per link |
| any other headed section | its own `rich_text`: H1, centred, not bold, last meaningful phrase `#008F51` (see Title + highlight), then an empty line, with the paragraphs centred |
| side navigation | `library_navigator` rebuilt from the page's **own** side nav. Copied ones linked to the wrong library on most IED/Chitral/Gilgit pages |

The script writes no invented text. Where a block needs a heading or a
two-line description the old page does not have, a person writes it.

---

## The page itself

| what | rule | evidence |
|---|---|---|
| content type | URL under `/convocation/` or `/about/chancellor/` with `speech`/`valedict`/`charter-acceptance`/`inauguration-`/`hh-ighd` in the file name → `speech_article`. Under `/events/` → `event_article`. Otherwise `page`. **auto** | 121/123 speeches, 28/28 events |
| where | `Storyblok Path`, with the region translated to its short code: `regions/global/…` → `regions/gl/…` **auto** | the sheet's path is wrong on 530/530 without it |
| story name | Page Name minus its trailing `(…)` **auto** | |
| `page` root | `enable_pattern: true`, `pattern_spacing: section`, every SEO field empty **auto** | 362/378 |
| speech root | no hero; `title` = the `<h1>`. `SpeechBy: chancellor` when the h1 names His Highness the Aga Khan. Body limited to the components a speech accepts. **auto** | |
| event root | no hero; `title` = h1, `variant: single`, `isArchived: false`. Dates, city, mode and types are left blank for a person. **auto** | event details were hand-written on 7/28 |

## Top of the page

| SharePoint | Storyblok | |
|---|---|---|
| first `<h1>` in the content | `hero.title`, and the h1 is **removed** from the body | 336/383, removed 319/321 **auto** |
| — | `hero`: `variant: tertiary`, no image, `spacing_preset: zero` | 335/383, zero 383/383 **auto** |
| a real banner photo | `hero` `quaternary` with the image | 11 section home pages **auto** |
| video/slide carousel at the top | `hero` `primary` with `hero_slide`s | 9; person |

## Body

| SharePoint | Storyblok | |
|---|---|---|
| prose | **one** `rich_text` per section, not one per webpart. A new one starts only when another blok interrupts | 232/297 pages have one **auto** |
| `<h2>` | heading **level 1**; `<h3>` level 2 | 117 vs 26 **auto** |
| first text has no heading | insert H1 **"Overview"** | 70 pages, all 10 builders **auto** |
| `rich_text.spacing_preset` | `section` (`detailed_section` inside a profile panel, `zero` inside a row) | **auto** |
| speech over 5,000 characters | `collapsible: true`, `collapse_lines: 20` | **auto** |
| one picture beside its text, any length | `split_section`. **description is rich text**, every paragraph kept. `image_variant: wrap` over 1,000 characters, else `default`; never `circles` | wrap 158/160 **auto** |
| officer page: h2 role + h3 place + photo + bio | `split_section`, title = role, highlight = place | "Dean, Medical College" \| "Pakistan" **auto** |
| several split_sections in a row | alternate, **starting `reverse`** | 34/41 **auto** |
| a picture alone between paragraphs | `image` blok (`variant: hero`) — not left in the rich text | images left in rich text: 4 of 428 **auto** |
| pictures directly after each other | one `media_section` gallery at that point | **auto** |
| 3+ bold questions ending in "?" | `info_accordion`, one item per question | 24/28 **auto** |
| `ReadAccordion` / `ReadTabs` widget | `info_accordion` | 12/16 **auto** |
| accordion panel | `info_accordion_item` > **`cards`** > `info_accordion_card` (`variant: rich_text`, `color: default`), item `columns: "1"` | 413 **auto** |
| heading + plain list (no links, 2–14 items) | `sub_inner_group`, `variant: outcomes`, `columns: 2` (1 for a single item; the space removed `align`, 10 Nov 2026) | 31/45, not in speeches **auto** |
| YouTube / Vimeo / dacast iframe | `media_section` `type: video` where the iframe sat. Never a `video` blok | 22 vs 0 **auto** |
| other iframes (prezi, flipbuilder) | `iframe` blok, inline 16:9 | 7/7 **auto** |
| `galleryapp` widget | `media_section` gallery, all images | 6/7 **auto** |
| `a.buttonStyle` "Back to …" | `row` (center) > `row_item` (fit, center) > `button` (primary) | 71/73 centred **auto** |
| people table / person tiles | `row` > `row_item` > `profile_card` | person; the build makes cards |
| `div.card.profile-two` | `profile_panel_grid` > card > panel > rich_text | person |
| reference lists, chief guests, awards | `faculty_publications` | person |
| `.boringbox` numbers | `stats` > `stats_card` | person |

**Title + highlight.** A heading is cut in two, and `title` keeps its trailing
space. The hand-built pages put the last word in `highlight` (68%), but
Abdullah re-split those by hand (10 Nov 2026): the highlight is the last
meaningful PHRASE -- after a colon, after a mid-title "(NIH)", after the last
"and", else the last 2-4 words not opening on the/of/for... ("About **Our
Policies**", "Activities Since **May 2022**"); two words -> the last; a name
("Aga Khan", "Class of 2015") stays whole. `house_style.split_heading`.

## End of the page: navigation and section chrome

| what | rule | |
|---|---|---|
| `quick_actions` | Built from the **left side nav** (`#zz1_V4QuickLaunchMenu`) in its order. Drop the section root, "Contact Us", "The Chancellor" in About, and the country homes in Convocation. Then add the **"Related Links"** list, which is removed from the text. Title "Quick " + highlight "Actions", `spacing_preset: section`. | order 118/118, root dropped 115/118 **auto** |
| quick-link icons | Fixed per target URL; learnt from the hand-built pages (99 SVGs). With no learnt icon: option `graduation` in Convocation, `book` elsewhere. | 98% consistent **auto** |
| "Explore Convocations Across Countries", Stay Connected banner, side navigator | **Copied from the sibling pages** in the same folder, when at least half of them carry it. Never invented. | identical to a sibling 88% / 57% / 80% **auto** |
| right-hand QuickLinks webpart | Its links live in a SharePoint list that is not in the HTML. | person |

## What a person still decides

- Whether a page gets the "Message From His Highness" banner. It is never in
  the source; 45 pages have it, built two different ways.
- Speaker portraits for speeches. 40 of 56 had no picture in the source.
- `secondary`/`primary` heroes, `quote_banner`s, carousels, `library_navigator`
  instead of quick actions. These were each builder's choice.
- Event dates, venue, mode and types.

## Measured result

The build was run on the 530 rows and compared with what people built. A page
never copies chrome from its own story.

| | `build_pages.py` | `build_from_sheet.py` |
|---|---|---|
| content type right | 342 / 493 | **506 / 530** |
| top-level sequence similarity | 0.42 | **0.58** |
| identical top-level sequence | 4 | **30** |
| component overlap | 0.27 | **0.48** |
| pages losing >30% of their text | 10 | **2** (both inherited from build_pages, refused at upload) |

The gap that is left is mostly editorial: split sections built around a photo
the source did not have (186 of the misses), and blocks one builder used and
another did not.

## Note for MC-PK-RULES.md

§2 recommends `info_accordion_item.body`. **That field no longer exists**: the
live item has only `title`, `eyebrow`, `eyebrow_as_subtitle`, `columns` and
`cards`. Accordions written by `build_pages.py` carry their panels in a field
the editor does not show.
