"""sheet.py -- read the team's migration sheet and say where each page goes.

The sheet is the export the team works from (`aku-migration-<date>.csv`):
`Serial No., Page Name, Old URL, Storyblok Path, ...`. Imported, never run.

Two things in it are not what the space holds, measured against the 530 pages
people built by hand from the 5 Nov 2026 sheet:

* **`Storyblok Path` names the region in full; the space uses short codes.**
  `regions/global/about/officers` is `regions/gl/about/officers` in the space --
  530 of 530 rows. Asking for the long name is how a second folder gets built
  beside the real one (root CLAUDE.md §6), so it is translated here and nowhere
  else.
Translated that way, `Storyblok Path` is the story's full slug on all 530 --
`home.aspx` rows included, which already end in `/home`.
"""
import csv
import re
import urllib.parse

AKU = 'https://www.aku.edu'

# Region names in the sheet -> the short codes the backend seeded (9 Sep 2026).
REGION = {'global': 'gl', 'pakistan': 'pk', 'kenya': 'ke', 'tanzania': 'tz',
          'uganda': 'ug', 'afghanistan': 'af', 'united-kingdom': 'uk', 'uk': 'uk',
          'east-africa': 'ea'}


def read(path):
    """Every row of the sheet, as dicts. `utf-8-sig`: Excel writes a BOM."""
    with open(path, encoding='utf-8-sig', newline='') as fh:
        return list(csv.DictReader(fh))


def space_path(sheet_path):
    """`regions/global/x/y` -> `regions/gl/x/y`. Other segments untouched."""
    parts = (sheet_path or '').strip().strip('/').split('/')
    if len(parts) > 1 and parts[0] == 'regions':
        parts[1] = REGION.get(parts[1], parts[1])
    return '/'.join(parts)


def aspx_stem(old_url):
    """`.../Pages/Appendix_B.aspx` -> `appendix-b`."""
    name = urllib.parse.unquote(urllib.parse.urlsplit(old_url).path.rsplit('/', 1)[-1])
    return re.sub(r'\.aspx$', '', name, flags=re.I).lower().replace('_', '-')


def destination(row):
    """(folder, slug) the story is created at."""
    path = space_path(row.get('Storyblok Path'))
    folder, _, slug = path.rpartition('/')
    return folder, slug


def story_name(row, fallback=''):
    """The sheet's Page Name without its "(folder/...)" disambiguator.

    That is what people typed in ~165 of the 530; another 62 kept Storyblok's
    slug default ("Appendix a", "Ccreport"), which is not worth copying.
    """
    name = re.sub(r'\s*\([^()]*\)\s*$', '', (row.get('Page Name') or '').strip())
    return name or fallback


def absolute(href):
    return urllib.parse.urljoin(AKU + '/', (href or '').strip())


def norm_url(u):
    """Compare links on host+path, lowercased, no scheme/query/fragment."""
    u = (u or '').strip().lower()
    u = re.sub(r'^https?://(www\.)?', '', u)
    return u.split('?')[0].split('#')[0].rstrip('/')
