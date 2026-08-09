# Storyblok components, media and special characters

What the 3606 built story payloads actually contain — the component schemas to
define in Storyblok before uploading, every media role, and every non-ASCII
character that survives into the content.

Measured from `data/storyblok_stories/`, not from the converter source, so this
is what *will be uploaded* rather than what the code could emit.

Regenerate:

```bash
python pipeline/inventory_storyblok_components.py data/storyblok_component_inventory.json
```

---

## 1. Components — 4 to define

| Component | Instances | Nestable | Purpose |
|---|---|---|---|
| `news_article` | 3606 | content type | the story itself, 45 fields |
| `news_media` | 3621 | nestable | one image / video / file, in `media[]` and `richtext_media[]` |
| `video_embed` | 69 | nestable | embedded video, appears inside rich text |
| `twitter_embed` | 38 | nestable | embedded tweet, appears in `pull_quote` |

`iframe_embed` is configured in `config/storyblok.example.json` and used by 3
pull quotes, but no blok with that component name reaches the payloads — those
3 are stored as `pull_quote.component_type = "iframe_embed"`. Define it if you
want them as real bloks; otherwise handle them as embeds on the pull-quote field.

### `news_media` fields

`role` · `media_type` · `src` · `filename` · `alt` · `caption` · `source_key`

| `role` | Count | Meaning |
|---|---|---|
| `banner` | 3072 | primary listing / hero image |
| `medium` | 338 | secondary listing image |
| `richtext` | 200 | asset embedded in the body (in `richtext_media[]`) |
| `thumbnail` | 7 | small listing preview, separate from banner/medium |
| `video1` | 4 | hosted video from `Metadata.csv` `Video1`–`Video3` |

| `media_type` | Count |
|---|---|
| `image` | 3433 |
| `other` | 112 (PDF, DOC) |
| `gif` | 73 |
| `video` | 3 |

`role` × `media_type`, so nothing is a surprise at upload time:

```
3011  banner    image        61  banner    gif        7  thumbnail image
 326  medium    image        12  medium    gif        3  video1    video
 112  richtext  other        88  richtext  image      1  video1    image
```

### `video_embed` fields

`provider` · `video_id` · `embed_url` — **all 69 are `provider: "youtube"`.**
No Vimeo, no other provider.

### `twitter_embed` fields

`tweet_url` only.

---

## 2. Media inventory

### Files referenced from `Metadata.csv`

| | |
|---|---|
| news items | 3606 |
| with media | 3077 |
| **without any media** | **529** |
| media references | 3421 |
| unique files referenced | 3421 |
| files on disk | 3421 |
| missing references | **0** |
| orphan files | **0** |

`validation_passed: true` — every referenced file exists and every file is
referenced.

### File extensions actually present

```
.jpg  2960     .png   359     .jpeg  107     .pdf   106     .gif    73
.jfif    6     .mp4     2     .mov     1     .doc     1     .jpe     1
```

Plus 4 whose extension carries a query string
(`.pdf?sequence=1&isallowed=y`) — **strip the query before deriving a filename
or content type.**

### Media-type buckets

| Bucket | Stories | Definition |
|---|---|---|
| `video_embed` | 62 | body contains an embedded video blok (YouTube / iframe) |
| `gif` | 62 | a GIF in `content.media` or referenced in rich text |
| `thumbnail` | 7 | has a `Metadata.csv` "Thumbnail image" asset |
| `video_file` | 3 | downloadable video from `Video1`–`Video3` |

### Rich-text embedded media — the gap

| | |
|---|---|
| unique references | 257 |
| **present on disk** | **187** |
| **missing** | **70** |
| story references | 381 |
| **stories with missing media** | **51** |

These are PDFs and inline images embedded in `NewsContent` pointing at
`https://www.aku.edu`. 70 were never downloaded, so **51 stories will upload with
broken inline references** unless `download_richtext_media.py --execute` is run
first while those URLs still resolve.

Separately, `storyblok_asset_catalog.json` lists **85 inline content images**,
all SharePoint-relative, 0 external.

> ⚠ **`assets/` is not in this checkout.** It is gitignored and must be supplied
> locally. Without it there are no files to upload — only the reports describing
> them. See the README for the expected layout.

---

## 3. Rich-text schema

The body is a Storyblok richtext document (`{"type": "doc", "content": [...]}`).

### Node types

| Node | Count | Attrs |
|---|---|---|
| `text` | 35,270 | — |
| `paragraph` | 30,280 | — |
| `hard_break` | 8,190 | — |
| `list_item` | 631 | — |
| `bullet_list` | 142 | — |
| `heading` | 130 | `level` |
| `blok` | 66 | `body` — nests `video_embed` / `twitter_embed` |
| `image` | 35 | `alt`, `src` |
| `ordered_list` | 21 | — |
| `tableCell` | 8 | — |
| `blockquote` | 4 | — |
| `tableRow` | 3 | — |
| `table` | 2 | — |

Note the table nodes use **camelCase** (`tableCell`, `tableRow`) while everything
else is snake_case — that is Storyblok's own convention, not an inconsistency to
"fix".

### Marks

| Mark | Count | Attrs |
|---|---|---|
| `link` | 1,991 | `href`, `linktype`, `target`, `uuid`, `anchor`, `custom` |
| `bold` | 1,022 | — |
| `italic` | 931 | — |
| `superscript` | 40 | — |

Only 4 marks. No underline, strike, code, or subscript anywhere.

### Pull quotes — 118 stories

| Mode | Count |
|---|---|
| `richtext` | 77 |
| `embed` | 41 → `twitter_embed` 38, `iframe_embed` 3 |

---

## 4. Content fields — `news_article`

45 fields. Population across 3606 stories:

**Always populated (100%)**: `title` · `summary` · `body` · `city` · `entity` ·
`author` · `content_writer` · `editor` · `tags` · `local_approver_group` ·
`global_approver_group` · `is_published` · `sequence_number` · `sharepoint_id` ·
`sharepoint_sequence_number` · `sharepoint_modified` · `sharepoint_created`

| Field | Populated | |
|---|---|---|
| `schedule_start_date` | 3601 | 99% |
| `publisher` | 3561 | 98% |
| `content_approver` | 3529 | 97% |
| `locally_active` | 3573 | 99% |
| `globally_active` | 3359 | 93% |
| `media` | 3099 | 85% |
| `is_globally_approved` | 2303 | 63% |
| `is_modified_by_global` | 2043 | 56% |
| `is_locally_approved` | 1780 | 49% |
| `category` | 1609 | 44% |
| `global_news` | 1244 | 34% |
| `additional_entities` | 946 | 26% |
| `banner_caption` | 707 | 19% |
| `subtitle` | 278 | 7% |
| `medium_image_caption` | 130 | 3% |
| `pull_quote` | 118 | 3% |
| `pull_quote_author` | 77 | 2% |
| `news_in_urdu` | 44 | 1% |
| `contact` | 30 | <1% |
| `schedule_end_date` | 26 | <1% |
| `secondary_language_2` | 8 | <1% |
| `secondary_language_3` | 3 | <1% |
| `alternate_summary` | 2 | <1% |
| `alternate_title` | 1 | <1% |
| `alternate_subtitle` | **0** | — |
| `alternate_banner_caption` | **0** | — |

`richtext_media` appears on 116 stories (present on all 116 that have it).

**Four fields are empty across all 3606 stories** — `alternate_subtitle`,
`alternate_banner_caption`, and effectively `alternate_title` (1) and
`alternate_summary` (2). Worth omitting from the schema unless AKU plans to use
them.

---

## 5. Special characters

**123 distinct non-ASCII characters, 40,410 occurrences.** 19 flagged
`normalize_recommended`, accounting for **35,616** of them.

Full detail with per-field breakdown: `data/unicode_report.json`.

### SharePoint artefacts — 9 chars, 35,290 occurrences · normalize these

| Char | Codepoint | Count | Files | → ASCII |
|---|---|---|---|---|
| `’` | U+2019 | 10,844 | 2185 | `'` |
| *(zero width space)* | U+200B | 7,997 | 3004 | *(remove)* |
| `“` | U+201C | 7,201 | 2110 | `"` |
| `”` | U+201D | 5,823 | 1737 | `"` |
| `–` | U+2013 | 1,779 | 839 | `-` |
| `‘` | U+2018 | 1,154 | 612 | `'` |
| `—` | U+2014 | 444 | 203 | `-` |
| *(no-break space)* | U+00A0 | 47 | 23 | space |
| *(BOM)* | U+FEFF | 1 | 1 | *(remove)* |

U+200B appears in **3004 of 3606 files** — the single most widespread artefact,
and invisible, so it will not show up in a visual review.

### Typography — 8 chars, 308 occurrences · safe to normalize

`…` U+2026 (135) → `...` · *(narrow no-break space)* U+202F (77) → space ·
`•` U+2022 (76) → `*` · `‐` U+2010 (7) → `-` · *(line separator)* U+2028 (6) →
`\n` · *(soft hyphen)* U+00AD (5) → remove · *(thin space)* U+2009 (1) ·
`―` U+2015 (1) → `-`

### Legitimate content — 98 chars, 711 occurrences · **do NOT strip**

Valid multilingual content. Stripping these corrupts names and quotations.

- **Accented Latin** — `é` (96), `ö` (19), `è` (17), `ü` (16), `ç` (14)
- **Transliteration** — `ā` (72), `ī` (41), `ū` (22), `ʿ` U+02BF (29), `ḥ`, `ṣ`, `ṭ`
- **Ligatures** — `ﬁ` U+FB01 (25), `ﬂ` U+FB02
- **Arabic / Urdu** — full script present (`ے ی ہ ں گ ک ڈ چ پ` …) for the 44
  `news_in_urdu` stories. **Requires RTL handling.**
- **CJK** — `宋` `体` (font names leaking from Word markup)
- **Symbols** — `£` (16), `€` (14), `°` (13), `™`, `®`
- **Greek** — `π`, `β`
- **Emoji** — `👇`, and the regional indicators `🇦 🇰 🇺`

### Data-quality problems — 2 chars, 18 occurrences · fix at source

| Char | Codepoint | Count | Meaning |
|---|---|---|---|
| `�` | U+FFFD | 12 | **replacement character — original byte already lost** |
| `＆` | U+FF06 | 6 | fullwidth ampersand → `&` |

The 12 U+FFFD cannot be recovered by any transform — the information is gone.
They need a manual look at those 12 stories.

### Control whitespace — 3 chars, 4,076 occurrences

`\n` (2875), `\r` (1099), `\t` (102). Intentional in `Contact` fields; review
before collapsing inside HTML fields.

### Upload rules

1. Send everything as **UTF-8**. Do not transliterate to ASCII — that destroys
   the 711 legitimate-content occurrences.
2. Strip U+200B, U+FEFF and U+00AD **before** upload; they are invisible and
   inflate every text field.
3. Normalize the curly quotes and dashes only if AKU wants ASCII typography. They
   are valid UTF-8 and safe to keep.
4. Slugs are already ASCII-safe — `build_folder_tree.py` reduces to
   `[a-z0-9-]`, so no character in this table can reach a URL.
5. RTL is a rendering concern for the 44 Urdu stories, not an encoding one.

---

## 6. Source HTML (context)

What the converter had to handle, from `data/newscontent_tags_report.json`:

| Class | Tags | Occurrences |
|---|---|---|
| sharepoint_artifact | `div` (34,785) · `br` (23,055) | 57,840 |
| structural | `p` (13,712) · `li` · `ul` · `h1`–`h4` · `table` / `tr` / `td` / `tbody` · `ol` · `blockquote` | 14,765 |
| inline_formatting | `span` (2757) · `strong` (1121) · `em` (1030) · `b` · `sup` · `font` · `i` | 5,003 |
| link | `a` (2,056) | 2,056 |
| media | `img` · `iframe` | — |
| ignored | `style` | — |

`div` appears in all 3606 files and `br` in 3330 — hence 8,190 `hard_break`
nodes surviving into the rich text.
