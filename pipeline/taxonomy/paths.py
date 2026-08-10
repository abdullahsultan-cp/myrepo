"""Canonical locations for the taxonomy stage.

One place defines where things live, so moving a directory means editing this
file and nothing else. All paths are absolute and derived from this file's own
location, so the scripts work from any working directory.

Layout:
    <repo>/
      config/region_overrides.csv        hand corrections (versioned)
      config/department_abbrev.csv       department short names (hand-authored)
      data/cleaned_news/                 INPUT: 3606 unicode-normalised items
      data/taxonomy/
        intermediate/                    one file per stage, each auditable
        lookups/                         city / entity / tag inventories
        routing/                         per-item destination + folder list
        seed/                            deliverables for the backend
      scripts/taxonomy/                  this stage's scripts
"""

import os
import sys

TAXONOMY_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.dirname(TAXONOMY_DIR)
REPO = os.path.dirname(SCRIPTS_DIR)

CONFIG = os.path.join(REPO, "config")
# Delegated to the shared module so a --type switch reaches here too.
sys.path.insert(0, SCRIPTS_DIR)
from paths_root import P

DATA = P.DATA

# INPUT — the pipeline's unicode-normalised export. Byte-identical to the raw
# SharePoint dump the taxonomy work was originally developed against.
NEWS_DIR = P.CLEANED

TAXONOMY_DATA = P.TAXONOMY
INTERMEDIATE = os.path.join(TAXONOMY_DATA, "intermediate")
LOOKUPS = os.path.join(TAXONOMY_DATA, "lookups")
ROUTING = os.path.join(TAXONOMY_DATA, "routing")
SEED = os.path.join(TAXONOMY_DATA, "seed")

# Named inputs consumed by build_folder_tree.py
REGION_OVERRIDES = os.path.join(CONFIG, "region_overrides.csv")
# Entity short names are derived from AKU's own approver-group names, so they
# live in intermediate/. Departments come from Tags and have no such source, so
# their short names are hand-authored and versioned in config/ instead.
DEPARTMENT_ABBREV = os.path.join(CONFIG, "department_abbrev.csv")
# Regions have no abbreviation anywhere in the export either; ISO 3166-1 alpha-2.
REGION_ABBREV = os.path.join(CONFIG, "region_abbrev.csv")
# Applied on top of the derived entity_abbrev.csv, for entities whose approver
# group yields no usable short form.
ENTITY_ABBREV_OVERRIDES = os.path.join(CONFIG, "entity_abbrev_overrides.csv")
NEWS_STRUCTURE = os.path.join(INTERMEDIATE, "news_structure.csv")
RECOVERED_ENTITIES = os.path.join(INTERMEDIATE, "recovered_entities.csv")
ITEMS_DEPARTMENTS = os.path.join(INTERMEDIATE, "_items_departments.csv")
ENTITY_ABBREV = os.path.join(INTERMEDIATE, "entity_abbrev.csv")
CONNECTIONS = os.path.join(INTERMEDIATE, "connections.csv")


def ensure_dirs():
    for d in (INTERMEDIATE, LOOKUPS, ROUTING, SEED):
        os.makedirs(d, exist_ok=True)
