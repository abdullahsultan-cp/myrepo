# pipeline/analyze — look, report, never change

Everything here **reads**. Nothing in this folder edits a payload or writes to
Storyblok, so any of it is safe to run at any time.

| Script | Answers |
|---|---|
| `analyze_unicode.py` | which odd characters exist, and where. **Read its report before running `clean`** — that is the review step |
| `analyze_tags.py` | which HTML tags the bodies actually contain |
| `validate_media.py` | does every file `Metadata.csv` names exist on disk? |
| `validate_storyblok_metadata.py` | is every SharePoint field represented in the payloads? |
| `fetch_storyblok_space.py` | snapshot the live space — components, assets, folders |
| `inventory_storyblok_components.py` | what components exist and what fields they have |
| `analyze_storyblok_space.py` | summarise that snapshot |
| `extract_storyblok_filter_constants.py` | the review viewer's filter lists → TypeScript |
| `import_storyblok.py` | the old direct importer, superseded by `pipeline/migrate/upload/` |

`validate_media.py` and `verify_richtext_media.py` print **`Validation: FAILED`
by design** — they are reporting the 206 media that cannot be recovered. Both
return zero. Watch the count, not the word: if it grows, something broke.
