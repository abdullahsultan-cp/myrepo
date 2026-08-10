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

`paths_root.py` finds the repo root by looking **upward for `config/types`**
rather than counting `dirname()` calls. It has moved once already, and the
counted version silently resolved the root to `pipeline/`, sending every data
path to a directory that did not exist.
