"""fields.py — read a source item without knowing which list it came from.

The pipeline was written against the News list and says `item["NewsContent"]` in
forty-five places. Blogs call that column `Blog Detail`, so every one of those
returns None and the step writes an empty result — no error, no warning, just
eighty-three blank articles. That is the failure this module removes.

    from fields import F
    html = F.get(item, "body")            # NewsContent, or Blog Detail, or ...
    F.set(item, "body", normalised)

The mapping lives in `config/types/<type>.json` under `fields`, so adding a list
whose columns are named differently is a JSON edit rather than a search and
replace.

Why an accessor rather than renaming the columns at import: the news corpus is
already migrated, and its 21,636 per-stage files carry the SharePoint names. A
rename would invalidate all of them and force a re-run of a finished migration
to gain nothing. `F.get(item, "body")` resolves to exactly `item["NewsContent"]`
for news, so its output is unchanged byte for byte.
"""

import os
import sys


import os as _os, sys as _sys  # noqa: E402
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import _bootstrap  # noqa: F401,E402  -- every pipeline folder on sys.path
from paths_root import P  # noqa: E402


class _Fields:
    """Profile-driven access to a source item's columns."""

    def column(self, key, default=None):
        """The real column name for a logical field, e.g. 'body' -> 'NewsContent'.

        Returns `default` when the profile does not define the field at all,
        which is a legitimate answer: blogs have no `city` column, and the
        caller should skip rather than invent one.
        """
        name = (P.fields or {}).get(key, default)
        # A few fields are declared as a list of candidate columns -- the
        # language links, for instance. Callers that want them all use
        # `columns()`; `column()` gives the first, which is the primary.
        if isinstance(name, list):
            return name[0] if name else default
        return name

    def columns(self, key):
        """Every column for a field declared as a list. Always a list."""
        name = (P.fields or {}).get(key)
        if name is None:
            return []
        return list(name) if isinstance(name, list) else [name]

    def has(self, key):
        """Does this content type declare the field at all?"""
        return bool((P.fields or {}).get(key))

    def get(self, item, key, default=None):
        """Read a logical field off a source item."""
        col = self.column(key)
        if not col:
            return default
        value = item.get(col)
        return default if value is None else value

    def get_any(self, item, key, default=None):
        """First non-empty value across every column declared for the field."""
        for col in self.columns(key):
            value = item.get(col)
            if value not in (None, ""):
                return value
        return default

    def set(self, item, key, value):
        """Write a logical field back onto a source item, in place."""
        col = self.column(key)
        if not col:
            raise KeyError(
                f"{P.type}: no '{key}' column declared; add it to "
                f"config/types/{P.type}.json under fields")
        item[col] = value
        return item

    def describe(self):
        out = [f"{P.type}:"]
        for k in sorted((P.fields or {})):
            if k.startswith("_"):
                continue
            out.append(f"  {k:<20}{(P.fields or {})[k]}")
        return "\n".join(out)


F = _Fields()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        P.use(sys.argv[1])
    print(F.describe())
