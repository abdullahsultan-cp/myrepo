# Review viewer

Faceted browser over all 3606 migrated AKU news stories. Built to answer
**"which Storyblok components do we actually need?"** without opening the AKU
site — every structural element is counted per story, so the facet counts *are*
the component inventory.

## Run

```bash
python ../scripts/migrate/build_viewer_index.py   # generate public/data/
npm install
npm run dev                                       # http://localhost:4000
```

`public/data/` is generated and gitignored. Regenerate with `npm run reindex`
after re-running the taxonomy stage or an upload.

## Filters

| Filter | Notes |
|---|---|
| **Elements / components** | video embed, hosted video, tweet, iframe, gallery, GIF, banner/medium/thumbnail, inline image, PDF, doc, table, lists, headings, blockquote, pull quote, bold/italic/superscript, link kinds, Urdu, no-media. **ALL / ANY** toggle for intersection vs union. |
| Date range | from/to on the publish date |
| Writer | 92 distinct |
| Region · Entity · Department · Placement | the migration taxonomy |
| SharePoint category | the original 12 values |
| Year · Migration status | |
| Numeric ranges | words, media files, links, share targets |
| Search | title, summary, SharePoint id, sequence number, writer, folder |

Element counts in the sidebar recompute against the **current result set**, not
the whole corpus, so they show what is left after the other filters — that is
what makes it usable for scoping components.

## Detail pane

Renders the actual Storyblok richtext — text, headings, lists, tables,
blockquotes, links, superscript — plus per-story taxonomy, the media table
(role, type, filename, caption), every link, and node/mark/blok counts.

Three outbound links per story: **SharePoint (live)**, **Storyblok editor**,
**Storyblok (live)**.

Media renders as a labelled placeholder rather than an image, because the
SharePoint asset bundle is not in the repo — every `src` points at a file that
does not exist here. The placeholder names the file that has to be uploaded,
which is more useful for review than a broken image.
