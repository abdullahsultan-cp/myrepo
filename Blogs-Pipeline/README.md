# Blogs-Pipeline

The blogs migration. **83 posts, all analysed. Blocked on one Storyblok change
that only the dev can make.**

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

## 2 · THE BLOCKER — `blog_article.body` accepts nothing

The dev has built `blog_article` (id `205045811148991`). Its `body` field is:

```
type                 bloks
restrict_components  true
component_whitelist  []          <- empty
```

`restrict_components: true` with an **empty whitelist means no component may be
placed in the body at all.** Not rich text, not an image, not a quote. Every one
of the 83 blogs would upload with a title, a banner and an empty body.

For comparison, `news_article.body` whitelists 13 components.

**Nothing else in this document can proceed until that whitelist is filled.**

### What it needs, and why — each from the actual content

Every component below **already exists in the space**. None needs building; they
need adding to the whitelist.

| Component | Needed by | Evidence in the 83 blogs |
|---|---|---|
| `rich_text` | **all 83** | prose in every post; 598 `<p>`, 137 `<strong>`, 52 `<em>`, 70 links, 20 lists, 65 headings, 2 `<sup>` |
| `image` | 15 blogs | 37 inline `<img>` — a lone image stays inside the rich text, as agreed for news |
| `media_section` | 15 blogs + 4 | galleries for runs of 2+ images; `type=video` for YouTube |
| `quote_banner` | 17 blogs | `Pull Quotes` populated on 17, with an author on 13 |
| `split_section` | as needed | a pull quote that arrives with an image |
| `iframe` | 1 blog | blog 18 carries a Facebook post embed in `Embed Code` |
| `video` | 4 blogs | blog 18's `Embed Video`, plus YouTube links in the body of 46, 70, 71 |
| `button` | 0 so far | none found, but it is in the news whitelist and costs nothing |

Also present in the space and worth considering: **`social_embed`** may suit the
Facebook post better than a raw `iframe` — dev's call.

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

## 4 · One thing genuinely missing from the space: a table

Blog **31** contains a real 8-row schedule table — grade against teaching day, from
a COVID-19 rural-education post. It is content, not layout.

There is **no table component anywhere in the 97**. News hit this twice (stories
1335 and 3288) and the answer was to skip them and rebuild by hand. With one
occurrence, doing the same is reasonable — but it should be a decision, and the
alternative is a small `table` component the dev may want anyway.

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

**From the dev:**

1. **Fill `blog_article.body`'s component whitelist** — nothing can migrate until
   this is done. Suggested: `rich_text, image, media_section, quote_banner,
   split_section, iframe, video, button`.
2. Decide on **`entities`** and a **category** field (§3).
3. Decide on **`isGlobal`** and **`thumbnail`** (§3).
4. Decide on a **table** component, or accept rebuilding blog 31 by hand (§4).

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
