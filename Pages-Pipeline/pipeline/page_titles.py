"""page_titles.py -- a readable page name out of a SharePoint title.

Three faults arrive in every title SharePoint exports, and a name is where they
are least forgivable: a title is what a person reads in a work sheet, sorts by,
and searches for.

  1. HTML ENTITIES are not decoded.  `Dean&#39;s Communiqu&eacute;`
  2. INVISIBLE CHARACTERS are present. `Dean's Communiqu` + U+200B + `e`
     reads identically to the same name without it and sorts apart from it, so
     nine copies of one title became three groups nobody could reconcile.
  3. The title is a CHAIN, not a name: "Academic Content | Anaesthesiology |
     MC, PK | The Aga Khan University". Everything after the first bar is
     already its own column in the sheet.

`pipeline/core/text_clean.py` fixes exactly (1) and (2) for news, blogs and
events. This is a separate 40 lines rather than an import because Pages shares
no code with `pipeline/` by design -- it is a different job, a folder tree and a
permission model rather than a list of items -- and reaching across would put
this stage behind the shared-code push guard for a string function. The code
point list is the same list, and is written as code points for the same reason:
a string of invisibles cannot be reviewed in a diff.

U+200C and U+200D are deliberately absent. They are the zero-width non-joiner
and joiner, and they change how Urdu and Arabic render -- filtering by Unicode
category Cf, the obvious way to catch a zero-width space, sweeps both away.
"""
import html
import re

# Deleted outright: they carry no meaning and are invisible either way.
DELETE = dict.fromkeys([
    0x200B,  # zero width space          -- 8,187 across the news export
    0x200E,  # left-to-right mark
    0x200F,  # right-to-left mark
    0x00AD,  # soft hyphen
    0xFEFF,  # byte-order mark
    0x2060,  # word joiner
    0x061C,  # arabic letter mark
])

# Become an ordinary space: they ARE a space, just one that breaks alignment
# and defeats an exact-match search.
AS_SPACE = {
    0x00A0: ' ',  # no-break space
    0x202F: ' ',  # narrow no-break space
    0x2009: ' ',  # thin space
    0x2028: ' ',  # line separator
    0x2029: ' ',  # paragraph separator
    0x0009: ' ',
}

TRANSLATION = {**DELETE, **AS_SPACE}


def clean(title):
    """Decode, strip the invisibles, collapse the whitespace. Nothing else.

    Decoding runs ONCE, deliberately. Looping until the string stops changing
    would destroy a title that legitimately shows markup, and no AKU export
    contains a double-encoded entity -- `looks_encoded` reports a survivor
    rather than guessing at it.

    Letters are left exactly as authored: a curly apostrophe stays curly, an
    accent stays. Two titles differing only in apostrophe style are a real
    difference in the source and not this function's to hide.
    """
    if not title:
        return ''
    return re.sub(r'\s+', ' ', html.unescape(title).translate(TRANSLATION)).strip()


def short(title):
    """The page's own name: the first segment of the title chain."""
    return clean(title).split('|')[0].strip()


def looks_encoded(text):
    """An entity that survived one decode -- report it, do not decode again."""
    return bool(re.search(r'&(?:#\d{2,5}|#x[0-9a-fA-F]{2,4}|[a-zA-Z]{2,10});', text))


def invisibles_in(text):
    """Which of the listed code points are still present. For a test to assert."""
    return sorted({'U+%04X' % ord(c) for c in text if ord(c) in TRANSLATION})
