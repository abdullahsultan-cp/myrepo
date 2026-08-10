
# Paths come from the shared module, so this works for any
# content type; see pipeline/paths_root.py.
import os as _os
import sys as _sys
from json import dump, dumps, load
from os import makedirs
from os.path import join

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import _bootstrap

_bootstrap.ensure()

from fields import F
from paths_root import P


def load_news_data(file_path):
    with open(file_path, encoding="utf-8") as f:
        return load(f)


def extract_news_items(json_data):
    if isinstance(json_data, dict) and "value" in json_data:
        return json_data["value"]
    if isinstance(json_data, list):
        return json_data
    raise ValueError("Unexpected JSON structure: expected OData object or list of news items")


def print_news_items(news_items):
    for index, item in enumerate(news_items, start=1):
        print(f"--- News item {index} ---")
        print(dumps(item, indent=2, default=str))
        print()

def create_news_item_json(news_item, folder_path):
    # The id column is "Id" in the News list and "ID" in Blogs. Asking the
    # profile costs nothing and stops the whole run dying on a KeyError.
    news_id = F.get(news_item, "id") or news_item.get("Id") or news_item.get("ID")
    if news_id in (None, ""):
        raise SystemExit(
            f"an item has no {F.column('id')!r}; every later stage keys on it. "
            f"Check fields.id in config/types/{P.type}.json")
    out_path = join(P.RAW, f"{news_id}.json")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        dump(news_item, f, indent=2, default=str)


def create_news_items_json(news_items, news_folder_path):
    # Create the directory if it doesn't exist
    makedirs(news_folder_path, exist_ok=True)
    for news_item in news_items:
        create_news_item_json(news_item, news_folder_path)

if __name__ == "__main__":
    file_path = P.SOURCE_JSON
    news_folder_path = P.RAW
    news_data = load_news_data(file_path)
    news_items = extract_news_items(news_data)
    create_news_items_json(news_items, news_folder_path)
