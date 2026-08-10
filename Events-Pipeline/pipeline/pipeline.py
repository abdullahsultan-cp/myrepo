"""EventsPipeline — the events migration.

Awaiting the export. This file exists so there is somewhere obvious to put the
first override, and so `--type events` resolves to a real class rather than the
generic fallback.

    python Events-Pipeline/pipeline/run.py
"""

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "pipeline"))
from base import ContentPipeline  # noqa: E402


class EventsPipeline(ContentPipeline):
    type = "events"

    # Nothing overridden yet, because nothing is known yet. Before the first run:
    #
    #   1. config/types/events.json — every column name in it is copied from
    #      news and is a guess. `python pipeline/new_type.py events --check`
    #   2. storyblok.component — the space already has `event_article`, which is
    #      NOT news_article: it has show_events / show_events_header and lacks
    #      author, date, read_time, languages, entities and isGlobal.
    #   3. If the export is a CSV, set source_format/source_file in the profile;
    #      the base importer handles the rest.
