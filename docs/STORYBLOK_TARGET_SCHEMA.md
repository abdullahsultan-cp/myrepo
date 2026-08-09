# Target schema — live space vs. migration payload

Snapshot of the real Storyblok space, and what has to change before 3606 stories
can be created in it.

Space: **Aga Khan University** · id `289824742951963` · region `eu` · plan
`starter`
Snapshot: `storyblok_space/` — regenerate with
`python pipeline/fetch_storyblok_space.py` (read-only, GET requests only).

> The snapshot is scrubbed on save: `preview_token`, `first_token`, `api_key`,
> `real_email`, `alt_email` are stripped, and `/collaborators` is not fetched at
> all. Credentials live in `config/storyblok.json`, which is gitignored.

---

## 1. The headline problem

The migration builds a `news_article` with **45 fields and `body` as a rich-text
document**. The live `news_article` has **16 fields and `body` as a `bloks`
field**. They are not compatible.

| | Migration payload | Live space |
|---|---|---|
| fields | 45 | **16** |
| `body` | richtext doc | **`bloks`**, whitelist: `box`, `media_section`, `quote_banner`, `rich_text`, `video` |
| `author` | object `{id,title,email}` | **`text`** |
| `date` | ISO `2003-07-26T09:00:00Z` | **`text`**, formatted `"Nov 28, 2025"` |
| `media` | `news_media[]` bloks | **no such field** — `banner_image` asset + `media_section` bloks |
| taxonomy | `city` + `entity` + `additional_entities` objects | **`entities`**, a single custom-plugin string |

**The rich text cannot go in `body` directly.** It must be wrapped:

```
richtext doc  ->  { component: "rich_text", content: <doc> }  ->  body[]
```

That is exactly what the sample story does — its `body` is
`[rich_text, quote_banner, rich_text, media_section, rich_text, media_section]`.

---

## 2. Live `news_article` — the 16 fields

| Field | Type | Req | Notes |
|---|---|---|---|
| `title` | text | ✅ | |
| `date` | text | ✅ | display format, e.g. `Nov 28, 2025` |
| `author` | text | | plain name, e.g. `Bruce Marlow` |
| `read_time` | text | | e.g. `28 min read` — computed |
| `description` | text | | the summary |
| `body` | bloks | | whitelist of 5, see below |
| `banner_image` | asset | | `filetypes: images` |
| `background_pattern` | asset | | `filetypes: images` |
| `languages` | bloks | | whitelist: `article_language_link` |
| `entities` | **custom** | | plugin `entities-plugins`; value is a **slug string** — the live story has `"news-training"` |
| `isGlobal` | boolean | | |
| `show_share` | boolean | | |
| `show_similar` | boolean | | |
| `similar_show_header` | boolean | | |
| `show_social` | boolean | | |
| `social_show_header` | boolean | | |

### Field plugins in the space

Four, all discovered from component schemas (`/field_types` returns 403 to a
personal token, so the plugin source could not be fetched):

| Plugin | Used on |
|---|---|
| `spacing-field-plugin` | `media_section` · `promo_split` · `quote_banner` · `rich_text` · `row` · `row_item` |
| `entities-plugins` | **`news_article.entities`** |
| `native-color-picker` | `row.background_color` · `row_item.background_color` |
| `storyblok-colorpicker` | `split_section.bg_color` |

`entities-plugins` is the one that matters. Its stored value in the live story is
the plain string `"news-training"`, so a slug is accepted — but the plugin's
validation rules are unknown. **Confirm the accepted vocabulary with the
front-end developer before generating 3606 values.**

---

## 3. The 5 body components

### `rich_text` — carries all article prose

| Field | Type | |
|---|---|---|
| `content` | richtext | **required** — this is where the migrated body goes |
| `bg_pattern` | asset | images |
| `pattern_height` | number | |
| `pattern_mobile_height` | number | |
| `spacing` | custom | `spacing-field-plugin` |

### `media_section` — images, galleries and video

`type` is an option: **`gallery` | `video` | `image`** (default `gallery`).

| Field | Type | Used when |
|---|---|---|
| `gallery_images` | multiasset (images) | `type=gallery` |
| `media_cards` | bloks → `media_card` | |
| `video_url` | multilink | `type=video` |
| `thumbnail` | asset (images) | video poster |
| `video_title`, `video_description` | text / textarea | |
| `auto_play`, `show_controls` | boolean | defaults `false` / `true` |
| `title`, `highlight`, `description`, `cta_label`, `cta_link` | | |
| `bg_pattern`, `pattern_position`, `pattern_opacity`, `spacing` | | |

### `quote_banner` — pull quotes

`variant`: `centered` | `attributed`. **`quote` (textarea) is required.**
Plus `attribution`, `date`, `category`, `portrait`, `background_image`, `spacing`.

Maps directly from the migration's 118 pull quotes.

### `video` — standalone video

`title` · `video_url` (multilink) · `thumbnail` (asset) · `auto_play` ·
`show_controls`

### `box` — layout primitive

22 fields (`display`, `direction`, `justify`, `align`, `gap`, `wrap`, …). Layout
only; the migration has no use for it.

---

## 4. Field mapping

### Maps cleanly

| Live field | From |
|---|---|
| `title` | `content.title` |
| `description` | `content.summary` |
| `author` | `content.author.title` — object → string |
| `date` | `ScheduleStartDate` → `"%b %d, %Y"` |
| `read_time` | computed from body word count |
| `isGlobal` | `surface_global` (1244 true) |
| `entities` | taxonomy entity → slug |
| `body` | richtext doc → `rich_text` blok |
| `body` | 118 pull quotes → `quote_banner` blok |
| `banner_image` | `media[]` role `banner` (3072) → uploaded asset |
| `languages` | 44 `news_in_urdu` → `article_language_link` bloks |
| `show_*` | defaults `true` |

### Has nowhere to go — 24 fields

Everything below exists in the migration payload and has **no field in the live
`news_article`**:

| Migration field | Populated | Consequence |
|---|---|---|
| **`sharepoint_id`** | **3606** | **no way to trace a story back to source, and no idempotent re-run** |
| `sequence_number` | 3606 | AKU's own reference (`NEWS-000958`) lost |
| `sharepoint_created` / `sharepoint_modified` | 3606 | original timestamps lost |
| `city` | 3606 | region survives only in the folder path |
| `additional_entities` | 946 | **the share / cross-reference feature has no field** |
| `tags` | 3606 | → story-level `tag_list`, not content |
| `category` | 1609 | Event coverage / Research / … lost |
| `banner_caption` | 707 | asset `alt`/`title` is the only home |
| `subtitle` | 278 | lost |
| `medium_image_caption` | 130 | lost |
| `richtext_media` | 116 | inline PDFs and images |
| `pull_quote_author` | 77 | → `quote_banner.attribution` |
| `contact` | 30 | lost |
| `publisher`, `content_writer`, `content_approver`, `editor` | 3529–3606 | editorial provenance lost |
| `local_approver_group`, `global_approver_group` | 3606 | **the permission signal** |
| `is_published`, `is_globally_approved`, `is_locally_approved`, `is_modified_by_global`, `locally_active`, `globally_active` | 1780–3606 | publication state lost |
| `schedule_end_date` | 26 | lost |
| `secondary_language_2` / `_3` | 8 / 3 | lost |

Three of these are worth a decision rather than silent loss:

1. **`sharepoint_id`** — without it there is no idempotency. A re-run creates
   duplicates instead of updating. Storyblok's story-level `meta_data` is a
   natural home and needs no schema change; the migration already writes
   `meta_data.sharepoint_id`. **Verify it survives the create call.**
2. **`additional_entities`** (946 items, 161 with real share targets) — the
   share-to-another-entity feature has no field at all. It needs one.
3. **`category`** (1609 items) — `quote_banner` has a `category` text field but
   `news_article` does not.

---

## 5. Schema drift already in the space

Two `news_article` stories exist and they disagree:

| Story | Updated | State |
|---|---|---|
| `news/strengthening-akus-next-generation-of-researchers` | 2026-07-28 | **matches the schema exactly** — 16/16 fields |
| `news/test/strengthening-akus-next-generation-of-researchers` | 2026-07-24 | **stale** — has a `thumbnail` field not in the schema, and `description` is a `bloks` array where the schema says `text` |

Build against the **first** one. The second is a pre-schema-change draft; Storyblok
keeps orphaned field values after a schema edit, so it is misleading.

---

## 6. Asset object shape

An `asset` field expects the full object returned by the upload, not a URL:

```json
{
  "id": 193045184543116,
  "filename": "https://a.storyblok.com/f/289824742951963/2000x1324/ae04c901e5/photo_29.jpg",
  "alt": "", "name": "", "focus": "", "title": "", "source": "", "copyright": "",
  "fieldtype": "asset",
  "meta_data": {},
  "is_external_url": false
}
```

`multiasset` (`gallery_images`) is an array of the same objects.

**`alt` and `title` are empty on every existing asset** — a chance to populate
them from the 707 `banner_caption` and 130 `medium_image_caption` values that
otherwise have no home.

---

## 7. Space contents today

| | |
|---|---|
| components | **84** in 7 groups |
| content types | `news_article`, `page`, `global` |
| stories | 22 (16 `page`, 2 `news_article`, 1 `global`, 3 folders) |
| assets | 30 (27 `.png`, 3 `.jpg`) |
| presets / datasources / asset folders | **0** |
| plan | `starter` |

Component groups: `Hero` (2) · `accordian` (7) · `banner` (5) · `cards` (14) ·
`carousel` (5) · `common` (32) · `sections` (16) · ungrouped (3).

**Nothing to be careful of yet** — only 22 stories and 30 assets exist, and the
`news/` folder holds just the two samples. Two things to note before a bulk run:

- **Asset folders: 0.** All 3421 media files would land in one flat asset root.
  Worth creating asset folders that mirror the story tree first.
- **Plan is `starter`.** Check the asset-count and API rate limits on that tier
  before uploading 3421 files and 3606 stories.
