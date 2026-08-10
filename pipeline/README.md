# pipeline — the base every content type inherits from

```
pipeline/                    THE BASE. Shared machinery, knows no content type.
  base.py                      class ContentPipeline  <- inherit from this
  run_pipeline.py              stage 1 orchestrator
  new_type.py                  scaffold / check a type
  core/                        the seam and shared helpers (imported, never run)
  content/                     source export -> story payload
  media/                       assets: catalogue, download, attach, inject
  analyze/                     inventories and validation (reads, never writes)
  taxonomy/                    Region / Entity / Department
  migrate/                     disk <-> Storyblok, the only network code

News-Pipeline/pipeline/      class NewsPipeline(ContentPipeline)
Blogs-Pipeline/pipeline/     class BlogsPipeline(ContentPipeline)
Events-Pipeline/pipeline/    class EventsPipeline(ContentPipeline)
Pages-Pipeline/pipeline/     a different job — inherits nothing, shares nothing
```

**Every content type has its own pipeline folder.** The one here is the parent:
it holds the machinery and the base class, and each type's folder holds a
subclass that says what is different about it.

---

## The class

```python
class BlogsPipeline(ContentPipeline):
    type = "blogs"

    def skip_steps(self):
        """Blogs name their banner file directly in the Banner column, so the
        stages that resolve which file belongs to which story have nothing to
        do."""
        return {"validate-media", "map-storyblok-media"}
```

That is the whole file. Everything not overridden comes from the base, so adding
a type is a small file rather than a fork of 80 scripts.

### What a subclass can change

| Hook | For |
|---|---|
| `skip_steps()` | steps this type does not need |
| `extra_steps()` | steps only this type has |
| `import_source()` | a delivered export in an unusual shape |
| `clean_item(item)` | per-item fixes after Unicode cleaning |
| `normalize_html(html, item)` | list-specific HTML quirks |
| `extract_pull_quote(item)` | news uses columns; blogs mark quotes inline |
| `story_name(item, id)` | how the story is named in Storyblok |
| `after_payload(payload, item)` | a last look before it is written |

**Overriding a script wholesale:** drop a file with the same name into
`<Type>-Pipeline/pipeline/` and it wins — `resolve_script()` looks in the type's
own folder before the base. No table edit, no base change.

### Two rules that keep it honest

**The base knows no content type.** No `"news"` in a condition, no SharePoint
column name, no payload key. Anything type-shaped comes from
`config/types/<type>.json` or from a subclass. Before this, forty-five places
said `item["NewsContent"]`, which for a blog returns `None` — no error, just an
empty result on all 83.

**A subclass overrides behaviour, not paths.** Paths already resolve per type
through `core/paths_root.py`. If a subclass is building a path, something has
gone wrong.

---

## Running it

Three ways, all equivalent:

```bash
python pipeline/run_pipeline.py all --type blogs   # the orchestrator
python Blogs-Pipeline/pipeline/run.py              # the type's own entry point
python Blogs-Pipeline/pipeline/run.py build-stories
python Blogs-Pipeline/pipeline/run.py --describe   # what this type overrides
```

`--describe` is the quickest way to see what a type actually does:

```
BlogsPipeline  (type=blogs)
  data      Blogs-Pipeline\data
  leaf      blogs
  steps     20 of 22
  skipped   map-storyblok-media, validate-media
  overrides skip_steps
```

---

## The folders

| Folder | Job | Runs? |
|---|---|---|
| `core/` | the seam and shared helpers — `paths_root`, `fields`, the rich-text converter | **imported, never run** |
| `content/` | source export → story payload | via `run_pipeline.py` |
| `media/` | assets: catalogue, download, verify, attach, inject | via `run_pipeline.py` |
| `analyze/` | inventories and validation | **reads, never writes** |
| `taxonomy/` | Region → Entity → Department | `taxonomy/run_taxonomy.py` |
| `migrate/` | disk ↔ Storyblok, the only network code | `migrate/upload/run_migration.py` |

Each has its own README.

`_bootstrap.py` puts every folder on `sys.path`, because the steps are run as
scripts rather than imported as a package — Python would otherwise show a step in
`content/` nothing from `core/`.

---

## Why Pages inherits nothing

`Pages-Pipeline/pipeline/` is not a `ContentPipeline`. Pages is not a list of
items becoming stories: it reconciles two exports into a folder tree and a
permission model, and shares no step with the other three. Bending it into this
class would mean overriding every hook to do something unrelated, which teaches
the reader nothing.

---

## Finding the repo root

`core/paths_root.py` and `pages/paths.py` both walk **upward** looking for
`config/types` rather than counting `dirname()` calls. Both have moved folders
more than once, and each time the counted version resolved to somewhere
plausible and wrong, with no error at all.
