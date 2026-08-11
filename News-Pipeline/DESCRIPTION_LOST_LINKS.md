# The links that cannot be in the first paragraph

**Nothing is being done about this now.** It is written down so the data is not
lost, and so the next person does not rediscover it the hard way.

Companion file: [`data/description_lost_links.csv`](data/description_lost_links.csv)
— **355 links across 274 stories**, 257 external and 98 internal.

## What the problem is

A news story's opening paragraph goes into the Storyblok field `description`.
That field is a **textarea** — plain text. It holds words and nothing else.

The same paragraph in SharePoint often carried hyperlinks. Those links have
nowhere to go: a textarea cannot hold a link, so they are dropped when the
paragraph is copied into it.

```
SharePoint     <p>AKU pledged its commitment to
               <a href="…">Every Woman Every Child</a> …</p>

description    AKU pledged its commitment to Every Woman Every Child …
               (the words survive; the link does not)
```

The reader still sees the sentence. They just cannot click it.

## Why it is not simply fixed

The field is the dev's, and its type is a decision we do not get to make. Three
things could change it and all of them are somebody else's call:

- `description` becomes a richtext field — then the links come back
- the opening paragraph is kept in `body` **as well**, and `description` becomes
  a plain summary — costs a duplicated intro unless it is written separately
- the links are accepted as lost, and the sheet is thrown away

## What already went wrong here

On 11 August a run applied the description rule to **184 live stories** and both
duplicated the intro and stripped its links. Those 184 were restored in place
from the 9 August content — same story ids, nothing moved, verified byte for
byte. See [`data/migrate/incident-20260811/`](data/migrate/incident-20260811/),
which holds the restore script, its log and the pre-revert snapshot.

**So the 355 links in the CSV are still live and still clickable today.** This
file is not a list of damage. It is a list of what would be lost if that rule is
ever applied again without the field changing first.

## The sheet

| column | |
|---|---|
| `sharepoint_id` | the story |
| `story_slug` | where it lives in Storyblok |
| `link_text` | the words the reader clicks |
| `href` | where it goes |
| `kind` | `internal` (aku.edu) or `external` |
| `where_it_belongs` | first paragraph of the story |
| `why_missing` | the plain-text field |

The 98 internal ones also appear in
[`data/internal_links.csv`](data/internal_links.csv), which is the wider sheet
of every aku.edu link and what to replace it with once the Storyblok pages
exist.

## Regenerating it

```bash
python News-Pipeline/data/migrate/incident-20260811/scan_desc_links.py
```

It uses `build_payload`'s own helpers and repeats its first-paragraph rule, so
it measures the real behaviour rather than a paraphrase of it.
