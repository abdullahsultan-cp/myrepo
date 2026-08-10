# Coding standards

Every rule here was paid for. Where one exists because something broke, the
breakage is named — that is the part that makes a rule stick.

---

## 1 · The three that matter most

### Never name a content type in shared code

No `"news"` in a condition, no SharePoint column name, no payload key. A step
asks the profile:

```python
html = F.get(item, "body")          # NewsContent, Blog Detail, whatever is next
```

**Why:** forty-five places said `item["NewsContent"]`. For a blog that returns
`None`, so `normalize-html` and `convert-richtext` ran, exited 0, and wrote
empty rich text for all 83. No error anywhere.

If you are about to type a column name, it belongs in `config/types/<type>.json`.

### Find a path, do not count `dirname()` calls

```python
def _find_root(start):
    d = os.path.dirname(os.path.abspath(start))
    while True:
        if os.path.isdir(os.path.join(d, "config", "types")):
            return d
        ...
```

**Why:** this has broken four times. `paths_root.py` moved into `core/` and
resolved the repo root to `pipeline/`, so every data path pointed at a directory
that does not exist. `storyblok_config.py` did the same and returned a config
with `space_id: None` — every API call came back 401. `join.py` reached for
`../data/taxonomy/` after the tree grew a folder per type and silently stopped
enriching. `story_media_classification.py` wrote the viewer constants into
`pipeline/storyblok-viewer/`.

Anchor on something only the target has. Use `P` and `ROOT`; never build a path
by hand.

### Fail loudly, or not at all

A step that cannot do its job must say so and exit non-zero. The failure mode to
design against is not a crash — it is a step that succeeds while producing
nothing.

```python
if not declared:
    raise SystemExit(
        f"{P.type}: no `content_fields` in config/types/{P.type}.json — "
        f"the story payload has no declared shape.")
```

**Why:** `extract_storyblok_filter_constants.py` pointed at a pre-restructure
path and failed at the end of every `all` run for weeks. Nobody noticed, because
the wall of output looked the same either way.

---

## 2 · Paths and files

**Always `encoding="utf-8"` on `open()`.** Python's Windows default is cp1252
and raises on the first accented name in the corpus. 72 call sites were missing
it; one was failing a test.

**Write with `newline="\n"`.** Otherwise a file written on Windows reads as
wholly rewritten to anyone else.

**Never hardcode a per-type path.** `P.STORIES`, `P.RAW`, `P.MEDIA_DIR`,
`P.report(name)`. If you need a new one, add a property to `paths_root.py`.

**Sanitise a filename before opening it.**
`UNCRC-vrs-ACC.pdf?sequence=1&isallowed=y` is a legal URL and an illegal Windows
path; `open()` raises `OSError` errno 22, which names nothing.

---

## 3 · Determinism

**Never let a `set` decide the order of anything written to a file.**

```python
variants = [                      # a LIST. Python randomises string hashing
    f"{src}/Pages/{page}?nid={n}",   # per process, so a set here wrote the same
    ...                              # 7,057 entries in a different order every
]                                    # run -- a 5,774-line diff meaning nothing
```

**Sort before writing** anything derived from a `set` or a `dict` you did not
build in order.

**Re-running a step must produce the same bytes.** That property is what makes
the byte-identity check in §7 possible, and it has caught more than review has.

---

## 4 · Data you did not write

**Do not edit a generated file.** Change the source and re-run. If a generated
file is wrong, the generator is wrong.

**Do not "correct" source data.** `AERR` is not a typo — it comes from the
approver group `CA AERR`. `Pakistan / Arusha Climate and Environmental Research
Centre` looks wrong and was reviewed and kept. Record an exception in
`config/tree_accepted_exceptions.csv` rather than fixing what is not broken.

**Record provenance for anything derived.** `region_source`, `entity_source`,
`department_source`. A disputed placement must be traceable to either the data
or a decision.

**Report what you cannot resolve; never guess.** Blog 84 is owned by an entity
with folders under three regions and nothing to say which. It is reported as
`unresolved`, not assigned to the most likely one.

---

## 5 · Comments

**Comment the why, never the what.** The diff already says what.

```python
# A LIST, not a set. These are written to a JSON file that is committed, and
# set iteration order for strings is randomised per process, so a set here made
# every regeneration produce a different key order and a 5,774-line diff that
# meant nothing.
```

That comment stops someone "tidying" it back into a set. This does not:

```python
# build the list of variants
```

**A docstring says what the module is for and what will bite you.** Look at
`pipeline/core/fields.py` or `pipeline/base.py` for the shape.

**Leave the landmine marked.** If you find something surprising and true, write
it down where the next person will hit it — in the code if it is local, in
`CLAUDE.md` if it is general.

---

## 6 · Structure

**One script per step**, independently re-runnable. Do not merge steps.

**Each folder has one job**, stated in its README:

| | |
|---|---|
| `pipeline/core/` | imported, never run |
| `pipeline/content/` | source export → payload |
| `pipeline/media/` | assets |
| `pipeline/analyze/` | reads, never writes |
| `pipeline/migrate/` | the only network code |

A file in the wrong folder is a bug in the structure, not a detail.

**Type-specific behaviour goes in the type**, never in a branch:

```python
if P.type == "blogs":     # NO
```

Use the profile, `skip_steps`, `extra_steps`, a hook, or a same-named file in
`<Type>-Pipeline/pipeline/`. See [CONTRIBUTING.md](CONTRIBUTING.md) §3.

**Prefer data over code.** The step list is `config/steps.json`. The payload
shape is `content_fields`. Column names are `fields`. Each was once a Python
literal, and each was a file two people had to edit at the same time.

---

## 7 · Before you claim it works

**Run it. Reading is not checking.** Every bug in this repo's history was found
by looking at a result: a banner that was a logo, a counter that went backwards,
a read time implying 16 wpm, a description that was the word "The", a JSON diff
of 5,774 lines of nothing.

**For any change to shared code, prove news is unchanged.** Its 3,606 payloads
are known-good:

```bash
find News-Pipeline/data/stories -name '*.json' | sort | xargs md5sum > /tmp/before
python pipeline/run_pipeline.py all
find News-Pipeline/data/stories -name '*.json' | sort | xargs md5sum > /tmp/after
diff /tmp/before /tmp/after && echo unchanged
```

That check caught `_uid` vanishing from all 3,606 payloads, which no amount of
reading the diff would have.

**Know what your baseline is.** The same check once showed all 3,606 changed
after a clean rename. The *before* state had been left by a lone `build-stories`
run, which empties `media[]`. The refactor was fine; the baseline was not.

**Read the exit code, not the last line.** `all` ends with a wall of output, and
two steps print `Validation: FAILED` **by design** — they report the 206
unrecoverable media and return zero.

---

## 8 · Git

**Commit messages say why.** Prefix type-specific work:

```
blogs: resolve taxonomy against the live tree
pipeline: accept tags as text as well as SharePoint objects
```

**Never commit** `config/storyblok.json`, `config/database.json`, `assets/`, or
a regenerated file you did not mean to change.

**Do not commit a large regenerable snapshot.**
`storyblok_space/stories_full.json` is 44 MB and produced a single
1.3-million-line diff that swamped everything real in the same commit.

```bash
python pipeline/check_before_push.py --type <yours>
```

---

## 9 · Style

Mechanical, so nobody argues about it: `ruff.toml` in the repo root, 4-space
indent, 100 columns, double quotes.

```bash
ruff check . && ruff format --check .
```

Naming: `snake_case` for functions and variables, `UPPER_SNAKE` for module
constants, `PascalCase` for classes. Say what a thing is —
`unresolved_relative_links`, not `urls2`.

Standard library where it will do. The dependencies are `bs4`, `html5lib`,
`requests`, `psycopg`; adding another needs a reason in the commit message.
