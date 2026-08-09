import os
import sys
from json import dumps, load, dump
from os.path import abspath, dirname, join
from os import makedirs

# Paths come from the shared module, so this works for any
# content type; see pipeline/paths_root.py.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths_root import P  # noqa: E402


def load_news_data(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
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
    news_id = news_item["Id"]
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
