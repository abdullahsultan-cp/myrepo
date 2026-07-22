from json import dumps, load, dump
from os.path import abspath, dirname, join
from os import makedirs


def load_news_data(file_path):
    with open(file_path, "r") as f:
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
    print(news_item)
    news_id = news_item["Id"]
    with open(join(abspath(dirname(__file__)), "..", "data", "news",f"{news_id}.json"), "w") as f:
        dump(news_item, f, indent=2, default=str)


def create_news_items_json(news_items, news_folder_path):
    # Create the directory if it doesn't exist
    makedirs(news_folder_path, exist_ok=True)
    for news_item in news_items:
        create_news_item_json(news_item, news_folder_path)

if __name__ == "__main__":
    file_path = join(abspath(dirname(__file__)), "..", "data", "news.json")
    news_folder_path = join(abspath(dirname(__file__)), "..", "data", "news")
    news_data = load_news_data(file_path)
    news_items = extract_news_items(news_data)
    create_news_items_json(news_items, news_folder_path)
