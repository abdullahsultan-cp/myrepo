# Fields the FE dev needs to add before the migration

Answer to "what entities and fields do you need that aren't covered".

Scope follows the agreed reduction: **keep only what is in the demo, plus images,
videos, PDFs, external links, internal links, tables in rich text, and buttons.**
Everything else in the SharePoint export is dropped.

Measured against the live space (`storyblok_space/`, snapshot 2026-07-29):
`news_article` has 16 fields, `body` whitelists `box`, `media_section`,
`quote_banner`, `rich_text`, `video`.

---

## Blockers — the migration cannot run correctly without these

### 1. `sharepoint_id` — no idempotency without it

**Nothing in the story identifies its source.** A second run creates 3606
duplicates instead of updating 3606 stories. Any failure mid-run becomes
unrecoverable.

Two options, in order of preference:

| Option | Change needed |
|---|---|
| **Story-level `meta_data`** | **none** — the Management API accepts arbitrary `meta_data` on a story, and the migration already writes `meta_data.sharepoint_id`. Just confirm it survives the create call and is queryable. |
| A hidden `number` field on `news_article` | one field |

Either is fine. **Confirm which**, because everything downstream — resume,
verification, the link-rewriting pass — keys off it.

### 2. Share targets — the feature has no field at all

946 stories carry `AdditionalEntity`; 161 have real cross-entity share targets
after the owner is removed. This is the "show this news under another
entity/department, view only" dropdown, and **there is no field for it.**

```
Suggested:  share_entities
Type:       custom  (field_type: entities-plugins)
Multiple:   yes — up to 5 values (max observed is 5)
```

If `entities-plugins` cannot hold multiple values, the alternatives are a
`bloks` field of a new one-field `shared_entity` component, or a plain
multi-option field sourced from a datasource of the 19 entity slugs.

**This needs the FE dev's input on the plugin**, which is why it is a blocker
rather than something I can decide.

### 3. `button` is not allowed in the article body

You asked to keep buttons. `button` exists (`label` required, `variant`,
`icon`, `link`) but **`news_article.body` does not whitelist it**, so it cannot
be placed in an article.

```
Change:  news_article.body -> component_whitelist
Add:     button
Now:     box, media_section, quote_banner, rich_text, video
```

---

## Needed if news listing and filtering are dynamic

`news_filters` has `news_type_label`, `country_label` and `date_label`, and
`article_card` has `category`, `reading_minutes`, `pill_label`, `tag_label`.

So the design intends filtering by **news type** and **country** — but
`news_article` carries **neither**.

Note `news_grid.articles` is a `bloks` field of hand-placed `article_card`s. With
3606 stories that cannot be authored by hand, so the listing has to query the
Storyblok API — and a query can only filter on fields that exist on
`news_article`.

| Add to `news_article` | Type | Why | Data available |
|---|---|---|---|
| `category` | option or text | `news_filters.news_type_label`, `article_card.category` | **1609 stories** — Event coverage 433, other 357, Academic news 243, Achievements & awards 201, Research 134, Topical issues 132, Grants & Partnership 47, +5 more |
| `region` | option or text | `news_filters.country_label` | **3606 stories** — Pakistan 2188, Kenya 651, Tanzania 234, UK 205, Uganda 76, Afghanistan 15, Global 237 |

Region is currently encoded **only in the folder path**. Filtering on a path
prefix is possible but fragile; a field is cleaner.

If listings stay hand-authored, skip both — but then say so, because I would
otherwise generate values for fields nobody reads.

---

## Confirmations, not changes

| Item | Status |
|---|---|
| **Special characters** | **Already solved.** The pipeline normalises every SharePoint artefact to zero — 10,844 curly apostrophes, 7,201/5,823 curly quotes, 2,223 dashes, 135 ellipses, 76 bullets, 47 nbsp, 12 U+FFFD, the BOM — and **preserves legitimate content**: `é` 96→104, `ā` 72→78 (up, because HTML entities were decoded). U+200B went 7,997 → **4**. Send UTF-8; no further work. |
| **Tables in rich text** | `rich_text.content` is a `richtext` field, and the payloads contain `table` / `tableRow` / `tableCell` nodes. **Confirm the field's toolbar has tables enabled**, otherwise they are silently dropped on save. Only 2 stories have tables. |
| **PDFs** | `media_section.gallery_images` is `filetypes: images`, so a PDF cannot go there. PDFs stay as **asset uploads linked from rich text** — 106 files. Works with no schema change. |
| **GIFs** | Ride through as normal image assets. 73 files. No change. |
| **Video** | `media_section` (`type: video`, `video_url` multilink + `thumbnail`) for the 3 hosted files; `video_embed` already handles the 69 YouTube embeds. |
| **Gallery** | `media_section` (`type: gallery`, `gallery_images` multiasset). 15 stories have ≥3 images. |
| **Internal links** | No field needed. Tracked in Postgres (`migration.link`, 1893 rows) and rewritten in a second pass once every story has a Storyblok id. Exported as CSV via the `internal_links_todo` view. |
| **`banner_caption`** | 707 values, no field — write into the asset's `alt` / `title` instead. Every existing asset has both empty. |
| **`article_meta`** | Duplicates `author`/`date`/`read_time`/`languages`/`show_share`, which `news_article` already has directly. Not needed, and not in the body whitelist. |

---

## Dropped deliberately

Per the agreed reduction. Listed so nobody later reads this as data loss by
accident:

`subtitle` (278) · `city` (3606, region replaces it) · `tags` (3606 → story
`tag_list`) · `medium_image_caption` (130) · `publisher` · `content_writer` ·
`content_approver` · `editor` · `local_approver_group` · `global_approver_group`
· `is_published` · `is_globally_approved` · `is_locally_approved` ·
`is_modified_by_global` · `locally_active` · `globally_active` ·
`sequence_number` (3606, AKU's `NEWS-000958` reference) · `schedule_end_date`
(26) · `contact` (30) · `secondary_language_2/3` (11) · `alternate_*` (3)

Two are worth a second thought before dropping:

- **`sequence_number`** — AKU's own reference for every item. Cheap to keep in
  `meta_data` alongside `sharepoint_id`.
- **`is_published`** — currently the only signal of whether a story was live in
  SharePoint. Without it every story is published on arrival.

---

## Summary for the FE dev

```
news_article
  + share_entities     custom (entities-plugins), multiple   <- blocker
  + category           option | text                          <- if listings are dynamic
  + region             option | text                          <- if listings are dynamic
  ~ body               add "button" to component_whitelist     <- blocker
  ? sharepoint_id      hidden number, OR confirm story meta_data works

rich_text
  ~ content            confirm tables are enabled in the richtext toolbar
```

Nothing else. Media, links, PDFs, GIFs, galleries, video and special characters
are all handled by components that already exist.
