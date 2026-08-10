# Working in parallel

Two people, two content types, one repository. These rules exist so that costs
nothing.

> **You own `<Your-Type>-Pipeline/` and `config/types/<your-type>.json`.
> Everything else is shared, and shared files need a word first.**

---

## 1 · Who owns what

| Path | Owner | Conflict risk |
|---|---|---|
| `Blogs-Pipeline/**` | whoever has blogs | none — nobody else writes here |
| `Events-Pipeline/**` | whoever has events | none |
| `config/types/blogs.json` · `events.json` | that type's owner | none |
| `pipeline/**` | **shared** | **high** — say so before you change it |
| `config/types/_TEMPLATE.json` | shared | high |
| `README.md` · `CLAUDE.md` · `docs/**` | shared | medium |
| `.gitignore` · `.gitattributes` | shared | medium |
| `storyblok_space/**` | nobody — it is the front-end dev's space | resolved by re-fetching |
| `News-Pipeline/**` | done and live; treat as read-only unless news is your job | — |

**The rule of thumb:** if the change is about *your* content type, there is a
place for it inside your own folder. If you find yourself editing `pipeline/`
to make your type work, that is the signal to stop and read §3.

---

## 1a · Turn the rules on

Once per clone:

```bash
python pipeline/install_hooks.py --type blogs     # or events
export AKU_CONTENT_TYPE=blogs                     # $env:... in PowerShell
```

That points git at `.githooks/`, where the pre-push hook **refuses** a push that
touches a file outside your folder, and runs the tests. When a shared change is
deliberate — and sometimes it is — say so once:

```bash
AKU_ALLOW_SHARED=1 git push
```

`.github/CODEOWNERS` does the same job on GitHub's side: a PR touching
`pipeline/` needs the shared owner's review. Replace the placeholder usernames
and enable "Require review from Code Owners" in branch protection.

---

## 2 · Branches

```bash
git switch -c blogs/<what>       # or events/<what>
```

Prefix with your content type. Push the branch, open a PR, and merge it
yourself once it is green — you do not need the other person's review for work
entirely inside your own folder.

**Rebase rather than merge** when main has moved:

```bash
git fetch origin && git rebase origin/main
```

A merge commit between two type branches makes the history unreadable for
nobody's benefit; the branches touch different files.

---

## 3 · Changing shared code without breaking the other person

`pipeline/` is the parent every type inherits from. It is shared on purpose:
one copy means one bug fixed once. That only works if it stays free of any one
type's peculiarities.

**Before editing `pipeline/`, check whether the change belongs to your type:**

| You want to | Do this instead | Where |
|---|---|---|
| skip a step your type does not need | `"skip_steps": [...]` | your profile |
| add a step only your type has | `"extra_steps": [{..., "after": "<step>"}]` | your profile |
| map a differently-named column | `"fields"` | your profile |
| change the payload shape | `"content_fields"` | your profile |
| route items somewhere else | `"hierarchy"` | your profile |
| say where items came from on aku.edu | `"source_urls"` | your profile |
| change how one step behaves | override a hook — `normalize_html`, `extract_pull_quote`, `clean_item`, `after_payload` | your subclass |
| replace a step wholesale | a file of the same name; `resolve_script()` prefers it | `<Type>-Pipeline/pipeline/` |

**Prefer the profile.** JSON keeps the decision beside the rest of the type's
configuration, and two people editing two profiles can never conflict. Reach for
the subclass only when the answer has to be computed.

That list covers almost everything. Blogs needed **one** shared change to run
end to end — tags arriving as `"Label|GUID"` rather than SharePoint objects —
and that was a genuine gap in the base, not a blogs quirk.

**If it really is a base change:** say so in chat first, keep it in its own
commit, and make sure the other type still runs. `pipeline/` changes are the
only ones that can break someone else's work.

---

## 4 · The one thing that will bite you

**Never commit a regenerated file just because it changed.**

Running the pipeline rewrites files, and `git status` will show them. Most are
gitignored, but a few are tracked because they are deliverables. Ask: *did I
change this, or did I just re-run something?*

| If this changed | And you did not intend it | Then |
|---|---|---|
| `storyblok_space/**` | you ran `fetch_storyblok_space` or `dump_sb_tree` | `git checkout -- storyblok_space` |
| `storyblok-viewer/src/constants/**` | you ran the full pipeline | leave it, or check out |
| the other type's `data/taxonomy/*.csv` | you ran with the wrong `--type` | check out, and re-run with yours |
| `News-Pipeline/**` | you ran without `--type` | **check out.** News is live |

`--type` defaults to **news**. A command without it runs against the finished
migration. Set it once per shell and stop thinking about it:

```bash
export AKU_CONTENT_TYPE=blogs      # PowerShell: $env:AKU_CONTENT_TYPE = "blogs"
```

or use your own entry point, which cannot be wrong:

```bash
python Blogs-Pipeline/pipeline/run.py
```

---

## 5 · Snapshots of the space are nobody's to merge

`storyblok_space/` holds what the front-end developer's space looked like at a
moment. Two people's snapshots differ because they were taken at different
times, not because either is wrong, so merging them is meaningless.
`.gitattributes` marks them `merge=ours`; the real resolution is a fresh copy:

```bash
python pipeline/migrate/review/dump_sb_tree.py       # the folder tree
python pipeline/analyze/fetch_storyblok_space.py     # components and the rest
```

The folder tree lives at `storyblok_space/folder_tree.json` — **space level, not
per type**, because every type reads the same one. It used to sit under
`News-Pipeline/`, which meant blogs reached across into news's folder for it and
two people refreshed it in two places.

That tree changes under you. The developer renamed every folder to a short code
mid-project — `regions/pakistan/entities/medical-college` became
`regions/pk/entities/mc` — and the first sign was blogs resolving nothing.
**Refresh it before you trust a routing result.**

---

## 6 · Before you push

```bash
python -m pytest tests/                        # 33 tests, seconds
python <Your>-Pipeline/pipeline/run.py --describe
git status                                     # anything here you did not mean?
```

If you touched `pipeline/`, also run the other types far enough to prove they
still work:

```bash
python pipeline/run_pipeline.py build-stories --type events
python pipeline/run_pipeline.py build-stories --type blogs
```

News has a stronger check available, because its output is known-good: rebuild
it and confirm every payload is byte-identical.

```bash
find News-Pipeline/data/stories -name '*.json' | sort | xargs md5sum > /tmp/before
python pipeline/run_pipeline.py all
find News-Pipeline/data/stories -name '*.json' | sort | xargs md5sum > /tmp/after
diff /tmp/before /tmp/after && echo "unchanged"
```

Every refactor in this repo has been checked that way, and it has caught things
reading the code did not — `_uid` vanishing from all 3,606 payloads, for one.

---

## 7 · Commits

Say what changed and why it was needed. The reason is the part nobody can
recover later; the diff already says what.

Prefix with the type when the change is type-specific:

```
blogs: resolve taxonomy against the live tree
events: map the export columns
pipeline: accept tags as text as well as SharePoint objects
```

Never commit `config/storyblok.json` or `config/database.json`. Both are
gitignored; if either appears in `git status`, something has gone wrong with the
ignore rules rather than with you.
