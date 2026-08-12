# pipeline/core — the seam and the shared helpers

**Imported, never run.** Nothing here is a pipeline step; every one of these is a
module the steps depend on. If you find yourself running a file in this folder,
it is in the wrong folder.

| File | Job |
|---|---|
| `paths_root.py` | **the seam.** Resolves every path under the selected content type. Import `P` and you cannot accidentally read news data during a blogs run |
| `fields.py` | reads a source item without knowing which SharePoint list it came from — `F.get(item, "body")` is `NewsContent` or `Blog Detail` depending on the profile |
| `storyblok_richtext.py` | HTML → Storyblok rich-text document. The hardest code in the repo; see CLAUDE.md before touching it |
| `storyblok_embeds.py` | pull quotes and embeds → the right blok |
| `storyblok_utils.py` | slugs, sequence numbers, `story_uuid`. **`story_uuid` must never change** — it is the identity of every migrated story |
| `storyblok_config.py` | credentials and component names, from `config/storyblok.json` |
| `storyblok_metadata_map.py` | SharePoint field → Storyblok path registry |
| `richtext_media_utils.py` | shared media helpers for cataloguing and attaching |
| `text_clean.py` | entities, position markers, invisible characters, link hrefs. **Runs inside `convert_richtext`, so no type has to call it** |
| `link_routing.py` | where a SharePoint link should point once the site is switched off — a story, an asset, or left alone |
| `steps.py` | the step list, read from `config/steps.json` |

## `text_clean.py` — read this before writing any text handling

Three faults arrive in every SharePoint export, and blogs shipped all three to
published pages because each code path cleaned its own way: the portal decoded
entities, the payload builder did not, and nothing made them agree.

| | seen | |
|---|---|---|
| HTML entities | 88 `&#160;` in 34 published biographies | `&#123;` decodes to `{`, so decode **before** matching markers |
| Position markers | `{pullquote}` ×14, `{EmbeddedCode}` ×1 | instructions to SharePoint's renderer, not words |
| Hidden characters | 7 kinds, 8,326 occurrences | table of code points, with counts, in the module |

**`U+200C` and `U+200D` are never stripped.** They change how Urdu and Arabic
render, and filtering by Unicode category `Cf` — the obvious way to catch
zero-width spaces — sweeps both away. Hence an explicit list.

**A text node is a fragment, not a string.** `clean_text(collapse=False)` does
not trim, because the renderer concatenates adjacent nodes and the space at a
node's edge is the space between two sentences. An unconditional `.strip()` here
rewrote 2,449 of 3,606 news stories in testing, turning
*"programme. This year"* into *"programme.This year"*.

`paths_root.py` finds the repo root by looking **upward for `config/types`**
rather than counting `dirname()` calls. It has moved once already, and the
counted version silently resolved the root to `pipeline/`, sending every data
path to a directory that did not exist.
