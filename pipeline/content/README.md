# pipeline/content — source export to story payload

Stage 1. Each step reads what the previous one wrote, so any one can be re-run
alone once its predecessor has. Run them through the orchestrator:

```bash
python pipeline/run_pipeline.py all [--type blogs]
```

| Step | Script | Turns |
|---|---|---|
| — | `import_source.py` | whatever the export arrived as → the type's JSON. News is OData JSON, blogs a CSV |
| `extract` | `extract_items.py` | the export → one file per item, in `data/raw/` |
| `clean` | `clean_items.py` | → `data/cleaned/`, Unicode normalised |
| `normalize-html` | `normalize_html.py` | SharePoint editor HTML → semantic HTML |
| `convert-richtext` | `convert_richtext.py` | → Storyblok rich text |
| `build-link-map` | `build_link_map.py` | SharePoint URL → story lookup |
| `enhance-richtext` | `enhance_richtext.py` | resolves internal links and asset URLs |
| `build-stories` | `build_storyblok_stories.py` | → `data/stories/`, **the payloads** |

**No step here names a SharePoint column.** They ask `F.get(item, "body")` and
the profile says which column that is. Before that, forty-five places said
`item["NewsContent"]`, which for a blog returns `None` — no error, just an empty
result.

**`build-stories` is not the last step.** It rewrites every payload and leaves
`media[]` empty; `pipeline/media/` puts the images back. Running it alone empties
the images on every story and the payload still looks valid. `run_pipeline.py`
warns when you do.
