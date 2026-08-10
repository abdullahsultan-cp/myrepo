# pipeline/media — the assets

Everything to do with images, video and documents: finding them, fetching what is
missing, and putting them into the payloads `pipeline/content/` built.

| Step | Script | Job |
|---|---|---|
| `catalog-assets` | `catalog_assets.py` | inventory the images referenced in item bodies |
| `map-storyblok-media` | `map_storyblok_media.py` | match each story to its files via `Metadata.csv` |
| `inject-story-media` | `inject_story_media.py` | banner / medium / thumbnail / video **into** the payloads |
| `catalog-richtext-media` | `catalog_richtext_media.py` | inline media inventory |
| `download-richtext-media` | `download_richtext_media.py` | fetch anything still missing |
| `verify-richtext-media` | `verify_richtext_media.py` | confirm each file is on disk |
| `attach-richtext-media` | `attach_richtext_media.py` | inline media **into** the payloads |
| `classify-story-media` | `story_media_classification.py` | tag each story by media type |
| `upload-assets` | `upload_assets.py` | push catalogued assets to Storyblok |

These run **after** `build-stories` and are not optional: that step writes the
payload, these fill `media[]` and `richtext_media[]`. Skip them and every story
uploads without pictures.

Bulk downloading from aku.edu is a different job and lives in
`pipeline/migrate/download/`, behind a lock, because it is slow, interruptible
and must never run twice at once.
