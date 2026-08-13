# How to build a portal

A portal is one HTML file that somebody opens by double-clicking it. No Python,
no server, no npm, no database, no 3.5-hour media download. The people who need
one most — the front-end developer, the content owner, whoever is reviewing —
are exactly the people who will never run the pipeline.

Two exist to copy from:

| | stories | size |
|---|---|---|
| `News-Pipeline/pipeline/build_portal.py` | 3,606 | **1.44 MB** |
| `Blogs-Pipeline/pipeline/build_portal.py` | 83 | 0.62 MB |

---

## 1 · Bake an index, not the bodies

This is the whole size question and it is decided in one function.

A first attempt at an events portal came out at **23 MB** because it put each
event's `EventDetail` into the page. Measured across the real export:

```
EventDetail, all 2,710 events        5.5 MB of raw text
  ... as Storyblok rich-text JSON     ~23 MB   (nodes, attrs, marks, nesting)

an index of the same 2,710 events    0.49 MB
```

**Half a megabyte instead of twenty-three, for the same 2,710 events.** Nobody
reads 2,710 bodies in a review tool. They filter to the twenty that look wrong
and open those — so give them what they need to *find and judge* a story, and
link out for the rest.

| Bake in | Leave out |
|---|---|
| title, date, route, author, read time | the body text |
| banner URL, a handful of image URLs | full rich text as JSON |
| the blok sequence (`rich_text`, `quote_banner x2`) | anything the editor link already shows |
| flags — no banner, iframe left, dead link | |
| the Storyblok id, so you can link to it | |

`summarise()` in either build script is that decision. **Everything it does not
return costs nothing.**

If it is still too big, trim the index — fewer image URLs per row, shorter
titles — before you consider anything structural.

## 2 · One file. Not several JSONs.

Splitting the data into `portal.html` + `data-1.json` + `data-2.json` sounds
tidy and **does not work**, for a reason that has nothing to do with size:

> A page opened from `file://` has origin `null`. `fetch()` and `XMLHttpRequest`
> against a sibling file are blocked by CORS. The page loads, the console fills
> with errors, and the portal is blank.

It works on the machine that built it only if that person happens to be running
a local server. Everyone else double-clicks it and sees nothing. That is the
same class of failure as the blogs portal shipping with 181 broken images: fine
where it was made, useless everywhere else.

So: **the data goes inside the HTML, as a JSON literal.** One file, emailable,
works from a USB stick.

If a portal genuinely cannot fit in one file, split by **content**, not by
mechanism — `news-portal-2024.html`, `news-portal-pk.html` — each still whole.

## 3 · Images must be URLs, never paths

`assets/` is gitignored. It is large and re-downloadable. A portal pointing at
`../assets/News/media/x.jpg` works for the person who built it and is broken for
everyone who clones.

Point at the uploaded asset:

```python
obj = asset_map.get(local_filename)          # data/asset_map.json is COMMITTED
src = obj["filename"] if obj else local_path # https://a.storyblok.com/...
```

Then check it, because this is invisible otherwise:

```python
local = [u for u in every_image_url if not u.startswith("http")]
print(f"images not on a URL: {len(local)}   <- must be 0")
```

Both portals print that line on every build. If it is not zero, the portal is
broken for everyone except you.

## 4 · Build from committed data

The portal must rebuild on a fresh clone, so read from something that is in git:

| Source | What it is |
|---|---|
| `<Type>-Pipeline/data/migrate/sb_snapshot/` | every story read back from the space |
| `<Type>-Pipeline/backup/storyblok/*.json.gz` | the same thing, timestamped |
| `<Type>-Pipeline/data/payloads/` | what was sent |
| `<Type>-Pipeline/data/asset_map.json` | local filename → uploaded asset |

**Refresh the snapshot after anything that writes**, or the portal reports a
state that stopped being true days ago. The news portal said `iframes left: 41`
when the space had 3, because its snapshot predated the Twitter conversion.

```bash
python pipeline/migrate/upload/sync_from_sb.py --snapshot
```

`--snapshot` is not optional. Without it that command reconciles the tracking
database, prints a summary, exits 0, and writes no story content at all.

**The build may use the network. The portal it produces never may.** The news
build refreshes slugs from the API because the snapshot predates the dev's
folder rename — but it bakes the result in, and `--offline` skips it.

## 5 · Verify that the page actually runs

A portal that ships blank looks perfect in git. The blogs one did exactly that:
a mangled quote inside an `onclick` made the whole script a `SyntaxError`.

Both builds now run their own JavaScript under Node against a stub DOM and fail
the build if nothing renders. Copy `verify()` from either.

Two traps in it, both of which made the check silently stop checking:

- **Run the script from a file, never `node -e`.** The script carries the whole
  data blob, and Windows caps a command line at about 32 KB. It fails with
  `FileNotFoundError` — indistinguishable from *node is not installed*.
- **Find node with `shutil.which`.** A bare `"node"` resolves in the shell and
  not always in `subprocess`.

## 6 · Keep the diff honest

The built HTML is committed, so every rebuild is a diff. Two rules keep that
from becoming noise:

- **Deterministic output.** Sort everything. Never let a `set` or `hash()`
  decide an order — Python randomises string hashing per process, so the same
  data produces a different file every run. That once produced a 5,774-line
  diff meaning nothing.
- **Rebuild only when the data changed**, not as a reflex before pushing.

## Checklist

```
[ ] index, not bodies — print the size on every build
[ ] one file; no fetch(); data inline
[ ] every image an https:// URL; "not on a URL" prints 0
[ ] reads only committed data
[ ] snapshot refreshed after the last write to the space
[ ] verify() passes — the page renders
[ ] output is deterministic
[ ] git stash -u, then open it. This is the only test that counts.
```

That last line is the whole document. If an image is missing there, it is
missing for everyone.
