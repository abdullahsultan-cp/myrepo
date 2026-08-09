# Blogs-Pipeline

The blogs migration. **83 posts, all analysed against the live schema and the
signed-off design. Nothing blocks the upload itself.**

What is outstanding is data with nowhere to land — `Entity` above all (§2c) —
and a download pass for 46 images that exist only on aku.edu (§5).

Blogs share `pipeline/` with news and events, selected with `--type blogs`. This
folder holds only the blogs *data*.

---

## 1 · What arrived

Delivered as `Blogs-20260809T212541Z-1-001/Blogs/`, copied in verbatim and
verified byte-for-byte against the original.

| In `data/source/` | Is | Size |
|---|---|---|
| `Metadata.csv` | **the 83 blog posts** — title, body HTML, author, category, entity, tags, pull quote | 522 KB |
| `categories.json` | 36 categories, each with an `EntityId` | 19 KB |
| `entities.json` | 28 entities | 15 KB |
| `post-comments.json` | 626 reader comments | 580 KB |
| `assets/Blogs/media/` | 73 images — **banners only** | 21 MB |

83 posts against news's 3,606, so a much smaller job — but a differently shaped
one, and the shape is where the work is.

---

## 2 · `blog_article.body` — empty whitelist, but not a migration blocker

`blog_article` (id `205045811148991`) is **new** — it did not exist in the
previous space snapshot. The dev built it today, along with `author_section`,
`comment_form`, `image`, `iframe`, `social_embed` and `event_article`.

Its `body` field reads:

```
type                 bloks
restrict_components  true
component_whitelist  []          <- empty
component_group_whitelist  (absent)
```

An earlier version of this file called that a hard blocker. **It is not, for the
migration.** The reference story `blogs/beyond-the-blame-...` sits in that same
field with 11 bloks and renders correctly on the live site, and the Management
API does not enforce whitelists — it is an editor-UI restriction. Our upload path
is unaffected.

**It still needs filling**, because with an empty whitelist a human opening a
migrated blog in the editor is offered nothing to insert, and so cannot fix or
extend a post by hand. For comparison `news_article.body` whitelists 13.

### What it should list — from the reference story and from the 83 blogs

Every component below **already exists**. None needs building.

| Component | Needed by | Evidence |
|---|---|---|
| `rich_text` | **all 83** | 598 `<p>`, 137 `<strong>`, 52 `<em>`, 70 links, 20 lists, 65 headings |
| `row` | the design | the reference uses it 3× — image beside text, and the pill strip |
| `quote_banner` | 17 blogs | `Pull Quotes` populated on 17, author on 13 |
| `author_section` | the design | closes every article in the reference |
| `comment_form` | the design | closes every article in the reference |
| `image` | 15 blogs | 37 inline `<img>`; in the reference always nested in a `row_item` |
| `pill` | the design | 2 in the reference, nested in `row_item` |
| `media_section` | 4 blogs | `type=video` for YouTube |
| `iframe` / `social_embed` | 1 blog | blog 18's Facebook post embed |

`row_item.body` also has an empty whitelist and holds `image` and `pill` in the
reference, so it needs the same treatment.

---

## 2a · The reference story, blok by blok

`blogs/beyond-the-blame-rethinking-pastoralism-and-environmental-impacts`
(story `205424528709668`) is the signed-off design. Its body:

```
 0  rich_text                       intro prose
 1  row  -> row_item[image] | row_item[rich_text]     image LEFT, text right
 2  quote_banner                    variant=event
 3  rich_text
 4  row  -> row_item[rich_text] | row_item[image]     image RIGHT, text left
 5  rich_text
 6  row  -> row_item[pill] | row_item[pill]           "Research"  "Environment"
 7  rich_text                       a heading
 8  rich_text                       disclaimer
 9  author_section                  photo + bio
10  comment_form
```

So images are **not** free-standing: each sits in a `row_item` beside a
`rich_text`, and the sides alternate. The pills are also `row_item`s, with
`width_mode: fit`.

### `quote_banner` has three variants, and they use different fields

| variant | Uses |
|---|---|
| `centered` | quote, attribution (gold), `date` + `category` as a meta line |
| `attributed` | quote, attribution, **`portrait`** |
| `event` | quote, **`pill_image`** in a decorative pill, `date`+`date_label` and `category`+`event_label` as an event card |

The reference uses **`event`** and sets `pill_image` **and** `background_image`
to the *same* asset (`203705850046717`) — that is the "image twice" you spotted.
It is one asset id referenced in two fields, not two uploads.

But the rendered page shows **none** of it: no background image, no pill photo,
no category chip — just the quote and a gold attribution. Its content is also
placeholder lifted from elsewhere (a medicine quote from President Sulaiman
Shahabuddin, `category: Convocation`) on a pastoralism blog. **So the reference
does not settle which variant blogs should use** — see the questions below.

### What our data can and cannot fill

| Field the design uses | Do we have it? |
|---|---|
| `quote` | yes — 17 blogs |
| `attribution` | yes — 13 blogs (`Pull Quotes Author`) |
| `portrait` (attributed) | **no** — no per-quote portrait anywhere |
| `pill_image` (event) | **no** |
| `date` / `category` (meta) | the blog's own date and Category, if that is wanted |
| `author_section.bio` | **no** — export has a name, never a biography |
| `author_section.photo` | **no** — no author photos in the bundle |
| `pill.label` | `Category` (21) and/or `Tags` (51) |

---

## 2b · Decisions taken

| Question | Decision |
|---|---|
| `quote_banner` variant | **Follow the reference** — `event` variant, and fill its other fields too (`date`, `category`, `date_label`, `event_label`), not just the quote |
| Blog 31's table | **Use `row`** rather than asking for a new table component |
| Image placement | **As in the source, presented as in the demo** — order comes from the article, the side-by-side `row` treatment from the reference |
| Missing values | **Ignore what we do not have** — never emit a blank field or a half-built blok |
| Pills | Deferred — the reference is only a demo |

"Ignore what we do not have" resolves several things at once: no `portrait` on
quotes, no `author_section` at all (we have neither a biography nor a photo for
any of the 52 authors — the name still rides in `blog_article.author` and shows
in the byline), and no empty `description` where `Summary` is absent.

**One thing it leaves open.** The `event` variant's `pill_image` and
`background_image` are the two fields the reference sets — to the *same* asset.
We have no per-quote image. Either they stay empty (consistent with "ignore what
we do not have"), or the blog's own banner is reused for both. Worth one word
when convenient; 13 blogs have no banner to reuse either way.

---

## 2c · What still has nowhere to go

Beyond Category and Tags, these carry real data and `blog_article` has no field
for them.

| Source | Populated | Why it matters |
|---|---|---|
| **`Entity`** | **83/83**, 9 values | The biggest gap. `news_article` has `entities`; `blog_article` does not. Without it a blog cannot say which faculty owns it, and entity filtering will not work for blogs |
| **`IsFeatured`** | **43 true / 40 false** | Nearly half the blogs are flagged featured. Nothing records it |
| **`FeatureSequence`** | 45/83 — 33×`1`, 5×`2`, 4×`3`, 3×`0` | The ordering *within* featured. Useless without `IsFeatured` |
| **`Close Comments`** | **14 blogs true** | The design appends `comment_form` to every article. These 14 had comments closed in SharePoint and there is no way to suppress it |
| **`IsActive`** | 82 true, **1 false** | One blog is inactive. Probably should upload unpublished rather than live |
| **`Post Year`** | 83/83, 6 values (2021–2026) | Stored as `string;#2025`. Likely derivable from `Schedule Start Date`, so possibly redundant — but it is what SharePoint filtered archives on |
| **626 comments** | `post-comments.json` | `comment_form` is a form, not a store. There is nowhere to put existing comments |

Already accounted for: `Blog Title`→`title`, `Blog Detail`→`body`,
`Summary`→`description` (31/83), `AuthorName`→`author`,
`Schedule Start Date`→`date`, `Banner`→`banner_image`, `Pull Quotes` +
`Pull Quotes Author`→`quote_banner`, `Embed Code`→`iframe`/`social_embed`,
`Embed Video`→`media_section`, `ID`→tracking key.

Dead on all 83, ignore: **`Banner Image`**, **`Tagss`**.

Not migrating (metadata): `Created`, `Modified`, `Created By`, `Modified By`.

---

## 3 · Fields `blog_article` does not have

Not blockers in the way the whitelist is, but each loses data that exists in the
export.

| Field | news_article | blog_article | What is lost |
|---|---|---|---|
| `entities` | yes | **no** | `Entity` is populated on **83/83** blogs, 9 distinct values. News used this to drive entity filtering and cross-entity sharing. Without it, a blog cannot say which faculty it belongs to |
| *(a category field)* | — | **no** | `Category` is populated on **80/83**, 21 distinct. This is blogs' primary taxonomy and there is **nowhere to put it** |
| `isGlobal` | yes | **no** | **37 of 83** blogs are `Entity = Global` — central content that should surface globally |
| `thumbnail` | yes | **no** | news used it for listing cards; blogs would fall back to the banner |
| `background_pattern` | yes | **no** | cosmetic; may well be deliberate |

`Tags` is populated on 83/83 with 51 distinct values. Neither component has a tags
field — news turned tags into department folders, and blogs can do the same, so
this is a decision rather than a gap.

**Category needs a decision, not just a field.** 21 values with duplicates that
matter: `Education [ID: 11]` and `Education [ID: 38]` are the same label under two
ids, exactly the pattern that made news tags unreliable. Dedupe by label, never by
id.

---

## 4 · The one table — settled, use `row`

Blog **31** contains a real 8-row schedule table, grade against teaching day, from
a COVID-19 rural-education post. It is content, not layout.

There is no table component among the 97, and none is being asked for: the
decision is to build it from `row` / `row_item`, one row per line. News hit this
twice (stories 1335 and 3288) and had to rebuild by hand; here it is one post and
`row` already does the job.

---

## 5 · Media — corrected

An earlier note in this file said blogs need no download stage. **That is wrong,
and only half the picture.**

| | Count | On disk? |
|---|---|---|
| Banners | 70 blogs name a real file | **yes, all 70** |
| Banners that failed at export | 9 blogs | no — the cell literally reads `DOWNLOAD_FAILED` |
| Blogs with no banner at all | 4 | — |
| **Inline body images** | **37 across 15 blogs** | **no — none of them** |

The 73 files in `assets/Blogs/media/` are **banners only** (plus three `(1)`
duplicates: `21-Banner(1).jpg`, `25-Banner(1).jpg`, `48-Banner(1).jpg`).

Every inline image is a SharePoint path that must still be fetched:

```
22  /iedpk/...        8  /blogs/...        6  absolute URLs        1  /test/...
```

So blogs **do** need a download pass, and it is urgent: those 37 images plus the
9 failed banners live only on aku.edu, which is being retired. The `/test/` one
(blog 18) is a staging path and may 404 already.

---

## 6 · Content shape, measured

```
83 blogs, 0 with an empty body
text length   min 763   median 3,857   max 12,956 characters

div 1053   br 1011   p 598   span 258   strong 137   li 77   a 70
em 52      img 37    h2 26   h3 19      ul 19        td 14   h1 14
tr 8       h4 6      sup 2   table 1    tbody 1      th 1    ol 1
```

**1,011 `<br>` across 82 blogs** — the same single-giant-paragraph problem news
had, where `<br><br>` separates what are plainly paragraphs. The splitter written
for news (`normalize_html.py`) handles it and runs on the serialised HTML, which
is the only way that did not destroy content.

**Links**: 42 external, 26 internal/relative, 2 mailto. External hosts are
citations — `doi.org`, `ncbi.nlm.nih.gov`, `dawn.com`, `unwomen.org`. The 26
relative links point back into aku.edu and will need the same rewrite pass news
still owes.

---

## 7 · Column mapping — 13 of 15 profile fields are wrong

`config/types/blogs.json` was scaffolded from news. Every field below names a
column this export does not have; a wrong name yields an **empty field, not an
error**.

| Profile expects | Real column |
|---|---|
| `NewsContent` | `Blog Detail` |
| `Title` | `Blog Title` |
| `Id` | `ID` |
| `NewsSummary` | `Summary` (31/83 populated) |
| `PullQuote` / `PullQuoteAuthor` | `Pull Quotes` / `Pull Quotes Author` |
| `ScheduleStartDate` | `Schedule Start Date` |
| `ContentWriter` | `Author Name` / `AuthorName` |
| `SequenceNumber` | `FeatureSequence` (45/83 — confirm this is the right one) |
| `City` | **absent — there is no city column** |
| `LocalApproverGroup` | absent |
| `AdditionalEntity` | absent |
| `NewsInUrdu`, … | absent — no alternate languages |

Only `Entity` and `Tags` match.

Full column list:

```
ID  Author Name  AuthorName  Banner  Banner Image  Blog Detail  Blog Title
Category  Close Comments  Created  Embed Code  Embed Video  Entity
FeatureSequence  IsActive  IsFeatured  Modified  Post Year  Pull Quotes
Pull Quotes Author  Schedule Start Date  Summary  Tags  Tagss
Created By  Modified By
```

`Banner Image` and `Tagss` are **empty on all 83** — dead columns. `Author Name`
carries `Dr Stephen M Lyon [ID: 2]`, `AuthorName` the plain name; use the latter.

---

## 8 · Placement — no `City` means region cannot be derived as news did

News read region from a free-text `City` column. Blogs have none. Region has to
come from `Entity` via `entities.json`, and 37 of 83 are `Global` anyway.

Entity spread:

```
37  Global                                       9  Critical Creative Innovative Thinking
15  Student Affairs and Services                 4  Networks of Quality, Teaching and Learning
11  Institute for Educational Development, PK    3  Training
 2  Data Innovation Office                       1  Faculty of Arts and Sciences, Pakistan
 1  Centre for Innovation in Medical Education
```

Three of those — `Global`, `Student Affairs and Services`, `Training` — are on the
list news already treats as *not entities*, routing to `global/`. That covers 55
of 83 blogs.

---

## 9 · Comments

626 of them, in `post-comments.json`. `Close Comments` is set on the posts, and
the space has a `comment_form` component — but that is a form, not a store of
existing comments. Migrating them needs somewhere to put them, which does not
exist today. Most likely out of scope; kept so it is a decision rather than an
oversight.

---

## 10 · What is needed, in order

**From the dev** — none of these blocks our upload, but each loses data or
blocks editors:

1. **An `entities` field on `blog_article`** (§2c). The largest gap: `Entity` is
   populated on 83/83 and has nowhere to go.
2. **Fill the `body` and `row_item.body` whitelists** (§2). Not a migration
   blocker, but until then nobody can edit a blog by hand in the UI.
3. **A way to record `IsFeatured` / `FeatureSequence`**, or confirm featured
   blogs are chosen in Storyblok instead and the SharePoint flags are dropped.
4. **A way to suppress `comment_form`** on the 14 blogs with comments closed, or
   confirm the form shows on all of them regardless.

**From us, once the above is settled:**

5. Convert `Metadata.csv` to `data/blogs.json` and fix the 13 field names.
6. Run the download pass for the 37 inline images and the 9 failed banners,
   before aku.edu goes.
7. Confirm `source_urls` in the profile against a real internal blog link —
   currently a guess.

```bash
python pipeline/new_type.py blogs --check          # profile vs the real export
python pipeline/run_pipeline.py all --type blogs
python pipeline/taxonomy/run_taxonomy.py --type blogs
python pipeline/migrate/upload/run_migration.py --type blogs
```

---

## 11 · Layout

```
Blogs-Pipeline/
  data/
    source/             THE EXPORT AS DELIVERED — tracked, never edited
      Metadata.csv        the 83 posts
      categories.json  entities.json  post-comments.json
    blogs.json          converted from Metadata.csv   <- not yet made
    raw/ cleaned/ normalized/                  generated, gitignored
    richtext/ richtext_enhanced/ stories/      generated, gitignored
    taxonomy/ migrate/                         generated
  assets/Blogs/
    media/              73 banners, 21 MB      gitignored -- see below
```

**The media is gitignored**, by the rule written for news, where `assets/` was
1.8 GB and re-downloadable from the live site. Neither is true here: 21 MB is
small, and once SharePoint is retired this copy may be the only one.
