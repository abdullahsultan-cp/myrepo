"""NewsPipeline — the news migration.

News is the type the base was written against, so this subclass overrides almost
nothing. That is the point: what makes news *news* lives in
`config/types/news.json`, not in code.

Kept as a real file rather than left to the generic fallback so that when news
does need to diverge -- a re-export with a renamed column, a second list merged
in -- there is an obvious place to put it, and a reader can see at a glance that
news currently has no special cases.

    python News-Pipeline/pipeline/run.py           # everything
    python News-Pipeline/pipeline/run.py build-stories
"""

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "pipeline"))
from base import ContentPipeline


class NewsPipeline(ContentPipeline):
    type = "news"

    # No overrides. Every difference is declared in config/types/news.json:
    # the column names under `fields`, the payload shape under `content_fields`,
    # where a story lands under `hierarchy`, and where it came from under
    # `source_urls`.
    #
    # 3,606 stories were migrated through exactly this path.
