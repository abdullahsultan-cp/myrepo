# Blogs-Pipeline

The blogs migration. **The export has arrived and is in `data/source/`. Nothing
has been transformed yet.**

Blogs share `pipeline/` with news and events, selected with `--type blogs`. This
folder holds only the blogs *data*, which is what keeps the migrations from
treading on each other.

---

## What arrived

Delivered as `Blogs-20260809T212541Z-1-001/Blogs/`, copied in verbatim and
verified byte-for-byte against the original.

| In `data/source/` | Is | Size |
|---|---|---|
| `Metadata.csv` | **the 83 blog posts** — title, body HTML, author, category, entity, tags, pull quote | 522 KB |
| `categories.json` | 36 categories, each with an `EntityId` | 19 KB |
| `entities.json` | 28 entities | 15 KB |
| `post-comments.json` | 626 reader comments | 580 KB |
| `assets/Blogs/media/` | 73 images — 60 jpg, 13 png | 21 MB |

**83 posts.** News was 3,606, so this is a much smaller job — but a differently
shaped one, and the shape is where the work is.

---

## Three things that differ from news, and matter

**1 · The content is a CSV, not JSON.** News arrived as `news.json`, a SharePoint
OData response. Blogs arrived as `Metadata.csv`. The pipeline's first step
(`extract`) reads `P.SOURCE_JSON`, so either the CSV becomes
`data/blogs.json`, or that step learns to read a CSV. **Converting is the
smaller change** and keeps the original untouched in `data/source/`.

**2 · `Metadata.csv` means something else here.** In news, `Metadata.csv` is the
*media manifest* — which file is a story's banner, medium, thumbnail. In blogs it
is the *content*. It must NOT be placed at `assets/Blogs/Metadata.csv`, where the
media steps would read it as a manifest and find nothing. It is deliberately in
`data/source/` instead.

Blogs carry their media inline: the `Banner` column names the file directly
(`15-Banner.jpg`), and all 73 are already on disk. So blogs need **no resolver
pass and no download stage at all** — the two slowest parts of the news
migration, and the two that depended on aku.edu still being up.

**3 · Every column is named differently.** 13 of the 15 fields in
`config/types/blogs.json` name a column this export does not have. They were
copied from news as placeholders, and a wrong name yields an **empty field, not
an error**:

| Profile expects | Real column |
|---|---|
| `NewsContent` | `Blog Detail` |
| `Title` | `Blog Title` |
| `Id` | `ID` |
| `NewsSummary` | `Summary` |
| `PullQuote` / `PullQuoteAuthor` | `Pull Quotes` / `Pull Quotes Author` |
| `ScheduleStartDate` | `Schedule Start Date` |
| `ContentWriter` | `Author Name` / `AuthorName` |
| `SequenceNumber` | `FeatureSequence` (probably — confirm) |
| `City` | *absent* — there is no city column |
| `LocalApproverGroup` | *absent* |
| `AdditionalEntity` | *absent* |
| `NewsInUrdu`, … | *absent* — no alternate languages |

`Entity` and `Tags` are the only two that match.

The full column list:

```
ID  Author Name  AuthorName  Banner  Banner Image  Blog Detail  Blog Title
Category  Close Comments  Created  Embed Code  Embed Video  Entity
FeatureSequence  IsActive  IsFeatured  Modified  Post Year  Pull Quotes
Pull Quotes Author  Schedule Start Date  Summary  Tags  Tagss
Created By  Modified By
```

Note `Tags` **and** `Tagss`, and `Author Name` **and** `AuthorName` — two pairs
of near-duplicates to reconcile before either is trusted.

---

## Open questions, for the analysis pass

- **No `City`.** News derived region from it. Blogs will have to take region from
  `Entity` via `entities.json`, or land at region level some other way.
- **`Category` vs `Tags`.** News inferred departments from tags. Blogs have a
  real `Category` field with 36 values, each carrying an `EntityId` — which looks
  more trustworthy than the tag inference ever was.
- **Comments.** 626 of them. Storyblok has no comment model here; they are
  probably out of scope, but the file is kept so that is a decision rather than
  an oversight.
- **`Embed Code` / `Embed Video`.** Blogs have dedicated embed columns where news
  had embeds buried in the body HTML.
- **The component.** `config/types/blogs.json` still says `news_article`. Read the
  live space before the first upload.

---

## Running it, once the above is settled

```bash
python pipeline/new_type.py blogs --check          # profile vs the real export
python pipeline/run_pipeline.py all --type blogs
python pipeline/taxonomy/run_taxonomy.py --type blogs
python pipeline/migrate/upload/run_migration.py --type blogs
```

No `run_media_all.py` — see point 2 above.

Every artefact lands under this folder; nothing writes into `News-Pipeline/`.

---

## Layout

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
    media/              73 files, 21 MB        gitignored -- see below
```

**The media is currently gitignored**, by the rule written for news, where
`assets/` was 1.8 GB and re-downloadable from the live site. Neither is true
here: 21 MB is small, and once SharePoint is retired this copy may be the only
one. Worth deciding deliberately rather than inheriting.
