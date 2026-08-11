# `pipeline/migrate/update/` — changing stories that are already live

Migration is not one pass. The dev hands over a field after the stories are up;
a plugin's value format only becomes knowable once something in the space has it
filled; a component we worked around gets replaced by a real one.

Every one of those is the same job: **reach into published stories and change
one thing, without disturbing anything else.** That is what this is.

```
run_update.py     the engine. Generic — it knows no content type.
helpers.py        walk_bloks, find_bloks, spacing. Imported, never run.
_template.py      copy this to start a plan.
```

Plans live with the type that owns them, so two people never edit one file:

```
News-Pipeline/pipeline/updates/twitter_embeds.py
Blogs-Pipeline/pipeline/updates/<yours>.py
```

## Running one

```bash
python pipeline/migrate/update/run_update.py --list --type blogs
python pipeline/migrate/update/run_update.py <job> --type blogs           # dry run
python pipeline/migrate/update/run_update.py <job> --type blogs --apply   # writes
python pipeline/migrate/update/run_update.py <job> --type blogs --only 45,70
python pipeline/migrate/update/run_update.py <job> --type blogs --limit 5 --apply
```

**Nothing is written without `--apply`.** Read the diff first — it names every
story and what changes on it.

## The four rules the engine enforces

**A plan may only touch the fields it declares.** `FIELDS` is a whitelist and a
plan returning anything else is a hard error, not a warning. The live content is
read, only declared keys are replaced, everything else is written back exactly
as found — so an editor's manual fix to a field you did not declare survives.

**Stories are never created or deleted.** It PUTs existing ids. A new id would
break every review link already shared and lose manual edits.

**A backup is taken before the first write**, to
`<Type>-Pipeline/backup/updates/<job>-<n>.json.gz`. Storyblok keeps no version
history; this file is the only way back.

**Content folders are never touched.** Those belong to the front-end dev.

## Writing a plan

```python
FIELDS = ["category"]                # the only keys patch() may return
DESCRIPTION = "shown by --list"
CONTAINS = "iframe"                  # optional; narrows what gets read

def setup(source):                   # optional, runs once
    return {"by_name": {...}}

def patch(content, source, ctx):
    if content.get("category"):
        return {}                    # already set; leave it alone
    return {"category": ctx["by_name"][source["Category"]]}
```

`content` is the story **as it is live right now**, not what we uploaded.
`source` is the matching export row, or `None`. `ctx` is whatever `setup()`
returned.

### `CONTAINS` is not optional in practice

Every story must be fetched individually to see its content. News is 3,610 of
them — twenty minutes of reading to change 38. `CONTAINS = "iframe"` lets the
space do the narrowing: 43 reads instead of 3,610. Set it whenever your plan
only cares about stories holding a particular component.

### Matching to the export

Blogs put `sharepoint_id` in the payload. **News did not**, so the engine falls
back to the tracking database's `story` table. If that database is not running
you get `source=None` and a warning — which is fine for any plan that only
rewrites what is already in the story, and most do.

## The one that exists

`twitter_embeds` (news) — the 38 Twitter iframes become `social_embed` bloks.
News went live with tweets in raw iframes because nothing better existed; they
do not render, and the dev has since added `social_embed` with `twitter`,
`facebook` and `instagram` variants.

It converts **only** twitter.com hosts. The other five live iframes — three
YouTube embeds that work, and two of the dev's own test stories on
`localhost:3010` and `aku-dev.vercel.app` — are left alone. A rule that
converted every iframe would have rewritten the dev's stories.

The blok shape is copied field for field from the dev's own hand-built example
in `news/strengthening-akus-next-generation-of-researchers`, rather than
invented.
