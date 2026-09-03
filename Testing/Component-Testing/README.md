# Component testing

Two deliverables, same purpose: check a component's variants without hunting
through 3,606 live stories for one that happens to use them.

1. **A local HTML mockup** — `build.py` → `index.html`. Opens by
   double-click, no network. Good for a quick field-shape reference.
2. **A real story in the live space** — `push_to_storyblok.py`, folder
   `testing/`, story `Component Testing`. The one to actually open and click
   through, because it is rendered by the real front end, not a guess at its
   CSS.

## The live story

```bash
python Testing/Component-Testing/push_to_storyblok.py           # dry run
python Testing/Component-Testing/push_to_storyblok.py --apply   # writes
python Testing/Component-Testing/push_to_storyblok.py --apply --publish
```

Content type is **`page`**, not `news_article`. That is deliberate:
`news_article.body` is whitelisted to the ~14 bloks this pipeline builds (see
`build_payload.py`) and will not accept a header, a carousel, a footer.
`page.body` carries no whitelist at all (`storyblok_space/components.json`:
`page` → `body` → `component_whitelist: null`), so it is the only root type
that can legally hold every nestable component in one story.

**All 90 embeddable components, one section per group.** Read straight from
`storyblok_space/components.json`: every field filled by its declared type
(text, asset, richtext, multilink, the spacing/colour plugins, ...), every
asset field pointing at a real, already-uploaded space asset, nested `bloks`
fields (footer → columns, header → nav_items → dropdown_columns, ...)
recursed into their first whitelisted child. A component's first `option`
field (usually `variant`, `type` or `layout`) gets one instance per value the
schema allows, so every variant is shown, not just the default. 230 bloks
total.

**Seven components are missing on purpose** — `blog_article`,
`entity_settings`, `event_article`, `global`, `news_article`, `page`,
`programme`. Those are root types: whole-page containers, not bloks a page
can nest inside itself. They're named in the story's own intro blok instead.

Left as a **draft** — visible and editable in Storyblok, not on the public
site, until `--publish` or someone publishes it by hand. Idempotent: re-run
after a schema change and it updates this same story rather than duplicating
it. `backup/component-testing-story.json` is a read-back snapshot taken right
after the write, per this repo's rule to back up *after*, not before.

The folder is `testing/` at the space root — outside `regions/` and
`global/`, so it can never be mistaken for real content and never collides
with the tree the front-end dev owns.

## The local HTML mockup

```bash
python Testing/Component-Testing/build.py    # -> index.html
```

**Part 1** — the ~14 bloks `build_payload.py` actually builds, each variant
rendered with real field names, real schema options and real asset URLs,
tagged **seen in a real payload** vs **schema only**.

**Part 2** — all 97 components in the space (the 90 above, plus the 7 root
types), auto-generated as field-schema tables. No CSS from the real site
exists in this repo, so this half documents shape rather than rendering it.

## Keeping both in sync

Regenerate after `pipeline/migrate/spaces/` refreshes
`storyblok_space/components.json`, or after a change to `build_payload.py`'s
field shapes. `index.html` is committed, `build.py` regenerates it — don't
hand-edit the HTML. The live story is regenerated the same way: re-run
`push_to_storyblok.py --apply`, don't hand-edit it in the Storyblok editor
and expect that to survive the next run.
