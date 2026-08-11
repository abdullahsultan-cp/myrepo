# Waiting on the dev — and exactly what to run when it lands

The 83 blogs are mapped and their payloads built. Four things are held up on the
front-end developer. **None of them needs the content re-done**: each is one
update run against the live stories, in place, keeping every story id.

| What | Blogs affected | Status here |
|---|---|---|
| `entities` field on `blog_article` | **17** | **plan finished — run it the day the field exists** |
| `category-plugin` value format | **80** | plan written, needs one filled example |
| `featured-plugin` value format | **43** | plan written, needs one filled example |
| a tags field | **83** | nothing to write until there is a field |

```bash
python pipeline/migrate/update/run_update.py --list --type blogs
python pipeline/migrate/update/run_update.py <job> --type blogs           # dry run
python pipeline/migrate/update/run_update.py <job> --type blogs --apply   # writes
```

Every run backs up what it is about to change to
`backup/updates/<job>-<n>.json.gz` first, and can only touch the fields its plan
declares. Read the dry run before applying.

---

## 1 · `entities` — ready now

`pipeline/updates/entities.py` is complete. Nothing is waiting on an example:
the field is a list of entity **folder ids as strings**, which we already know
from news. Only the field itself is missing.

**17 blogs, not 83.** It is not "the Entity column" — it is the story's own
entity folder plus every entity it is shared into:

```
12  filed under an entity   its own folder id     11 IED, 1 FAS, all pk
 5  global and shared       qtl x4, cime x1
66  entity is not a faculty legitimately empty    Global, Training, …
```

The 66 get an empty list on purpose, exactly as 1,575 news stories do.

The five shared ones get several ids each — `qtl` exists in ke, pk, tz, ug and
uk; `cime` in ke, pk and tz. That ambiguity is *why* they went to global.

## 2 · `category` — needs one filled example

80 of 83 have a category and we know which. What we do not know is what
`category-plugin` stores: nothing in the space has it set, and there are no
datasources to read it from.

**Ask for:** the demo blog with its `category` field filled in and saved. One
example is enough — the plan reads the shape and applies it to all 80.

## 3 · `isFeatured` — needs one filled example

Same problem, same fix. 43 blogs are featured, 45 carry a `FeatureSequence`
(33 are "1", 5 are "2", 4 are "3", 3 are "0"), and there is still no field for
the sequence itself.

## 4 · Tags — no field at all

47 distinct labels, 1 to 4 a blog. They are **already visible**: they render as
the demo's row of `pill` bloks, coloured by how often each tag is used so the
commonest ten are ten different colours.

That is presentation only. If the dev adds a real tags field — one that filters
and links — the pills should probably be replaced by it rather than sit
alongside. Nothing to write until that field exists and we know whether it is
free text, a datasource or a reference.

---

## Also parked, not waiting on the dev

**13 blogs have no hero image.** Closed, not pending: SharePoint holds no
banner-to-post mapping at all. See `data/banners_absent.json`.

**3 blogs have an author name but no biography** — ids 4 and 5 were deleted from
`AuthorManagement` and the live list 404s on both.

**24 links point into SharePoint** and die with it. Deliberately left as they
are, catalogued in `../News-Pipeline/data/internal_links.csv` with an empty
`new_target` column, to be replaced in one pass once the Storyblok pages exist.
Five are documents; the rest are `.aspx` pages belonging to the Pages migration.

**97 empty paragraphs and 7 squashed ones** — editor leftovers, to be cleaned by
hand against the demo blog's shape.
