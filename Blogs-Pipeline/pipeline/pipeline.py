"""BlogsPipeline — the blogs migration.

Blogs differ from news in ways that are real, so each override below says why.

    python Blogs-Pipeline/pipeline/run.py
"""

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "pipeline"))
from base import ContentPipeline  # noqa: E402


class BlogsPipeline(ContentPipeline):
    type = "blogs"

    def skip_steps(self):
        """Blogs need no media resolution or download.

        News had to read all 3,606 live pages to work out which file was a
        story's banner, because the export renamed everything. Blogs name the
        file directly in the `Banner` column and all 70 are already on disk, so
        these steps would do nothing but take time and hit a site that is being
        switched off.

        NOT skipped: the 37 inline body images are still SharePoint paths and do
        need fetching -- catalog/download/verify/attach-richtext-media stay.
        """
        return {"validate-media", "map-storyblok-media"}

    # TODO once the layout is signed off:
    #
    # def extract_pull_quote(self, item):
    #     """Blogs mark quotes inline with a {pullquote} marker in the body,
    #     where news has PullQuote / PullQuoteAuthor columns. 17 blogs have the
    #     column populated AND markers in the text, so the two have to be
    #     reconciled rather than one picked."""
