# AKU → Storyblok migration portal

Vite + React + TypeScript. React Flow draws the org chart, so it pans, zooms and
drags instead of being a CSS approximation.

```bash
cd Pages-Pipeline/portal
npm install          # once
npm run dev          # http://localhost:5173
npm run build        # -> dist/, and ../AKU-Migration-Portal.html
npm run preview      # serve the build locally
```

## The deliverable is one file

`npm run build` ends by running `build_single.mjs`, which folds the script, the
stylesheet and all three datasets into **`Pages-Pipeline/AKU-Migration-Portal.html`**
— about 5 MB, opens by double-click, needs no server and no network. That is the
file to hand to anyone who is not going to run npm.

It works because `useData()` reads the baked-in `<script type="application/json">`
tags when they are present and fetches `data/*.json` when they are not. One code
path, two ways of shipping it: `dist/` for a static host, the single file for
everyone else. Rebuilding is the only way to refresh it, so the deliverable cannot
drift from the source — which is what the previous hand-written
`build/render_portal.py` did. That script still runs, but now writes
`AKU-Migration-Portal-legacy.html`, so it cannot overwrite this one.

## Where the data comes from

The app reads three JSON files at runtime from `public/data/`. All are generated —
never edit them by hand. `public/data/` is gitignored, so a fresh clone has none of
them and the portal boots on "Could not load the migration data" until you build
them. These three steps each need the four that precede them; **`build/README.md`
has the full chain**, and this is only its tail:

```bash
cd ../build
python build_migration_plan.py   # -> plan.json   (folders, pages, roles, live checks)
python probe_people.py           # -> people.json (584 named people and their roles)
python build_roles.py            # -> roles.json  (the 345 custom roles, and per person)
mkdir -p ../portal/public/data
cp plan.json people.json roles.json ../portal/public/data/
```

Reading them at runtime rather than importing them means you can regenerate the
plan and refresh the browser without rebuilding the bundle.

## Screens

| Route | What it answers |
|---|---|
| `#overview` | what is changing, and the shape of the destination |
| `#tree` | the folder hierarchy, each page's old and new slug, and who can work in it |
| `#chart` | the same hierarchy as an org chart — pan, zoom, fold, and the team on each box |
| `#pages` | all 3,306 pages, old slug → new slug, filterable by type |
| `#model` | how permissions work: the two axes, the ladder, and every SharePoint permission translated |
| `#hierarchy` | the 345 custom roles as the tree they form — indentation is inheritance |
| `#users` | every person, SharePoint groups on the left, roles to assign on the right |
| `#rights` | the 159 folders that set their own permissions, and the team on each |
| `#shared` | content belonging to an entity it cannot live under, and the hub moves |
| `#checks` | the live aku.edu pages that settled the ambiguous placements |
| `#glossary` | every label in plain English |
| `#docs` | where the data came from, how to rebuild it, and what every CSV column means |

`#roles` and `#people` still resolve, so an old link opens — they show the earlier
flat role model (280 `<unit>-editor` / `<unit>-publisher` pairs). `#hierarchy` and
`#users` supersede them.

## Folders, pages and people are one screen, not three

`#tree` and `#chart` share a detail drawer (`src/screens/Detail.tsx`). Click a
folder, a page or a person on either screen and the drawer answers the same three
questions, cross-linked so you can walk between them:

- **a folder** — which roles may create, edit, publish and delete here, how many
  named people hold each, every page it contains, and why it sits where it does;
- **a page** — its live URL and its new one, and who may edit, publish or delete
  it. A page has no permissions of its own; it takes its folder's;
- **a person** — every folder and page they can touch, and what they may do to
  each. Pick one in the person box and both screens repaint: the tree badges each
  row with that person's capability, the chart fades what they cannot reach.

Both screens export the filtered view as CSV, one row per folder, with the role
and people columns beside the path.

### How "who can edit this" is worked out

`src/lib/perm.ts` joins two halves that neither source answers alone. Every folder
names the Storyblok **roles** that may edit, publish and restructure it — inheriting
folders carry the resolved names too, so a folder always knows its own answer. Every
person carries the roles they end up in and the folders SharePoint granted them.
Role is the join.

Two things that model has to keep separate, or the numbers stop meaning anything:

**Space-wide is not folder-scoped.** The 21 `space-admin` holders can reach every
folder. Counted in with each folder's own team, all 628 folders read "21 admins"
and the three people who actually run one disappear. They are counted apart, shown
under a **Space-wide** heading, and excluded from the search and the capability
filter — otherwise searching a space admin's name "matches" all 628 folders.

**A role nobody holds is not the same as someone else's role.** 78 of the roles a
folder names hold no named person — the SharePoint group exists, but no
Unique-scope row names a member. Those render struck through, with the count at
zero, rather than being quietly dropped.

Every one of the 628 folders resolves to at least 3 named people and at least one
publisher, so no folder is unowned. Median team is 17.

## Two things to know about the model

**Permissions are hierarchical.** Whoever holds a permission on a folder manages
that folder and everything under it. A row reading *inherits · X* takes its rights
from the nearest folder above it that sets any. There is no unowned folder.

**Entity is AKU's call, not ours.** A folder is an entity only if AKU publishes it
on `aku.edu/academics` or `aku.edu/research`. Everything else is a folder at region
level. `entity_basis` on each row records which list it came from.

## Base URL

The new slugs are paths with no domain, so they work against dev, staging or live.
Prefix them with whatever base URL the environment uses.
