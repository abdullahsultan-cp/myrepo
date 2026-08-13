# Working in parallel

Two people, two content types, one repository. These rules exist so that costs
nothing.

> **You own `<Your-Type>-Pipeline/` and `config/types/<your-type>.json`.
> Everything else is shared, and shared files need a word first.**

---

## 1 · Who owns what

| Path | Owner | Conflict risk |
|---|---|---|
| `Blogs-Pipeline/**` · `config/types/blogs.json` | **blogs** | none — nobody else writes here |
| `Events-Pipeline/**` · `config/types/events.json` | **events + pages** | none |
| `Pages-Pipeline/**` | **events + pages** (same person) | none |
| `News-Pipeline/**` · `config/types/news.json` | **news** — live, treat as read-only otherwise | none |
| `pipeline/**` | **shared** | **high** — say so before you change it |
| `config/steps.json` · `config/types/_TEMPLATE.json` | shared | high |
| `README.md` · `CLAUDE.md` · `docs/**` | shared | medium |
| `.gitignore` · `.gitattributes` · `ruff.toml` | shared | medium |
| `storyblok_space/**` | nobody — it is the front-end dev's space | resolved by re-fetching |

**Events and pages are one person.** They are separate folders because they are
separate jobs — pages is site structure, not content, and shares no code — but
they never conflict with each other either way.

**Ownership is by convention, not enforced on GitHub.** There is no CODEOWNERS
file: with three people and non-overlapping folders it would be ceremony. The
pre-push hook below is the real guard, and it runs on your machine. If the team
grows, add `.github/CODEOWNERS` mapping `/pipeline/` to whoever should review
shared changes.

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

There is deliberately no CODEOWNERS file yet — see above. The hook is the guard,
and it is honest about being local: anyone can bypass it with `--no-verify`, so
it is a reminder rather than a wall. That is the right level for three people
who talk to each other.

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
| change stories that are **already live** | an update plan | `<Type>-Pipeline/pipeline/updates/` |

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

## 3a · Starting a new type — three faults you WILL hit

Every SharePoint export carries these. They are not news quirks or blog quirks;
they are how SharePoint stores text. `pipeline/core/text_clean.py` handles all
three and you should call it wherever you turn source HTML into text.

```python
from text_clean import clean_richtext, clean_text, strip_html

strip_html(bio)        # a field holding HTML — tags out, entities decoded
clean_text(summary)    # a plain string
clean_richtext(doc)    # a Storyblok rich-text document, node by node
```

| What | Looks like | If you skip it |
|---|---|---|
| **HTML entities** | `&#160;` `&amp;` `&quot;` | the reader sees *"Dr&#160;Asad I Mian"* |
| **Position markers** | `{pullquote}` `{EmbeddedCode}` | `{pullquote}` appears mid-paragraph |
| **Blank paragraphs** | a `<p>` of only `<br>` | a gap where nothing should be |

All three shipped to published blog pages and were found by a person reading
them, not by any check. 88 entities across 34 biographies, 14 markers, 79 blank
paragraphs.

**There is a guard now.** `tests/test_text_clean.py` fails if any built payload
under `<Type>-Pipeline/data/payloads/` still contains an entity or a marker, for
every type. Build your payloads, run `pytest`, and it will tell you before
Storyblok does.

The entities are not a short list — `&#58;` alone appears 13,042 times across
the two exports, usually inside a URL. `&#123;` and `&#125;` decode to `{` and
`}`, which is why decoding must happen **before** markers are matched.

**On the third: strip a paragraph only when it has no text AND no image.**
Images live inside the rich text, so testing "has no text" alone deletes
pictures. `tests/test_blogs_payload.py` has that case.

## 3b · Portals must work from a clone. Backups are not optional.

These are the rules with the sharpest edges, because breaking either is
invisible to the person who breaks it and obvious to everybody else.

**How to build one: [docs/PORTALS.md](docs/PORTALS.md).** It has the size
budget, the reason several JSON files cannot work, and a checklist.

### A portal that needs the pipeline is a broken portal

**Someone must be able to `git clone`, double-click the portal, and see it
work.** No Python, no database, no 3.5-hour media download, no npm. The people
who most need a portal — the front-end developer, the content owner — are
exactly the people who will never run the pipeline.

That failed once and nobody noticed for weeks. `blogs-portal.html` was
committed and looked fine on the machine that built it, because it pointed at
`../assets/Blogs/media/…` — and `assets/` is gitignored, 26 MB of regenerable
media. Anyone else opened it to **181 broken images**.

| Do | Don't |
|---|---|
| bake the data into the HTML as JSON | read a JSON file at runtime |
| point images at their uploaded `a.storyblok.com` URL | point at anything under `assets/` |
| fall back to a local path only for what is *not yet uploaded* | assume the reader has the media |
| commit the built HTML | expect anyone to build it |

`Blogs-Pipeline/pipeline/build_portal.py` resolves every image through
`data/asset_map.json`, which is committed, so the portal needs nothing on disk.

**Check it the only way that means anything:**

```bash
git stash -u && start Blogs-Pipeline/out/blogs-portal.html   # or open it
```

If an image is missing there, it is missing for everyone.

### What must be committed, and why

`assets/` is gitignored on purpose — it is large and re-downloadable. Everything
that lets somebody *understand or rebuild* the migration is not.

| Committed | Why |
|---|---|
| `backup/raw/` | the SharePoint export as it arrived. **The site is being switched off — this becomes the only record it ever existed** |
| `backup/storyblok/` | every story read back from the API. Storyblok keeps no version history; this is the only way back |
| `data/asset_map.json` | local filename → uploaded asset. Without it the portal has no images and a re-run duplicates uploads |
| `data/payloads/` | what was sent, so live content can be diffed against intent |
| `data/taxonomy/routing.csv` | where each item went and **why** |
| `out/*-portal.html` | the deliverable people actually open |
| `storyblok_space/*.json` | the folder and asset trees every type reads |

`.gitignore` names `backup/` as an explicit exception. **Do not "tidy" it away
because the files are big.**

### Back up after every write, not before

```bash
python pipeline/migrate/review/backup.py --type <yours>
python pipeline/migrate/review/backup.py --type <yours> --verify   # diff, no write
```

An upload, an update run, an asset move — **the moment it finishes, snapshot it.**
Before is useless: the point is a record of what the space now holds.

Two faults found in that script by running it, both worth knowing about because
they are the shape of thing that hides:

- it could not start at all — `sys.path` was built by counting `dirname()` calls
- once running it archived **3,606 news stories into the blogs backup folder**,
  under a filename saying blogs, because it read the story list from the
  tracking database, which holds news and nothing else

**A backup nobody has restored from is a hypothesis.** `--verify` diffs the
archive against the live space and writes nothing; run it occasionally.

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
