from collections import defaultdict
from json import dump, load
from os import listdir
from os.path import abspath, dirname, join
import unicodedata

# Known characters with editorial context. Detection is not limited to this list;
# any non-ASCII or invisible/control character is still scanned and reported.
CHARACTER_CONTEXT = {
    "\u2019": {
        "name": "RIGHT SINGLE QUOTATION MARK",
        "classification": "sharepoint_artifact",
        "description": (
            "Curly apostrophe inserted by SharePoint/Word rich-text editors instead of ASCII '."
        ),
        "normalize_recommended": True,
        "ascii_replacement": "'",
    },
    "\u200b": {
        "name": "ZERO WIDTH SPACE",
        "classification": "sharepoint_artifact",
        "description": (
            "Invisible SharePoint/Word artifact. Often appears at the start of paragraphs "
            "in NewsContent and is safe to remove."
        ),
        "normalize_recommended": True,
        "ascii_replacement": "",
    },
    "\u201c": {
        "name": "LEFT DOUBLE QUOTATION MARK",
        "classification": "sharepoint_artifact",
        "description": "Curly opening double quote from SharePoint/Word instead of ASCII \".",
        "normalize_recommended": True,
        "ascii_replacement": '"',
    },
    "\u201d": {
        "name": "RIGHT DOUBLE QUOTATION MARK",
        "classification": "sharepoint_artifact",
        "description": "Curly closing double quote from SharePoint/Word instead of ASCII \".",
        "normalize_recommended": True,
        "ascii_replacement": '"',
    },
    "\u2018": {
        "name": "LEFT SINGLE QUOTATION MARK",
        "classification": "sharepoint_artifact",
        "description": "Curly opening single quote from SharePoint/Word instead of ASCII '.",
        "normalize_recommended": True,
        "ascii_replacement": "'",
    },
    "\u2013": {
        "name": "EN DASH",
        "classification": "sharepoint_artifact",
        "description": "En dash from SharePoint/Word instead of ASCII hyphen-minus.",
        "normalize_recommended": True,
        "ascii_replacement": "-",
    },
    "\u2014": {
        "name": "EM DASH",
        "classification": "sharepoint_artifact",
        "description": "Em dash from SharePoint/Word instead of ASCII hyphen-minus.",
        "normalize_recommended": True,
        "ascii_replacement": "-",
    },
    "\u00a0": {
        "name": "NO-BREAK SPACE",
        "classification": "sharepoint_artifact",
        "description": (
            "Non-breaking space from SharePoint/Word. Also commonly appears in HTML as the "
            "entity &#160; inside NewsContent."
        ),
        "normalize_recommended": True,
        "ascii_replacement": " ",
    },
    "\ufeff": {
        "name": "BYTE ORDER MARK",
        "classification": "sharepoint_artifact",
        "description": "Byte order mark copied into content during export or paste.",
        "normalize_recommended": True,
        "ascii_replacement": "",
    },
    "\u200c": {
        "name": "ZERO WIDTH NON-JOINER",
        "classification": "sharepoint_artifact",
        "description": "Invisible zero-width character sometimes introduced by rich-text editors.",
        "normalize_recommended": True,
        "ascii_replacement": "",
    },
    "\u200d": {
        "name": "ZERO WIDTH JOINER",
        "classification": "sharepoint_artifact",
        "description": "Invisible zero-width character sometimes introduced by rich-text editors.",
        "normalize_recommended": True,
        "ascii_replacement": "",
    },
    "\u2026": {
        "name": "HORIZONTAL ELLIPSIS",
        "classification": "typography",
        "description": "Ellipsis character from editors instead of three ASCII periods.",
        "normalize_recommended": True,
        "ascii_replacement": "...",
    },
    "\u2022": {
        "name": "BULLET",
        "classification": "typography",
        "description": "Bullet character pasted into HTML content by editors.",
        "normalize_recommended": True,
        "ascii_replacement": "*",
    },
    "\u202f": {
        "name": "NARROW NO-BREAK SPACE",
        "classification": "typography",
        "description": "Invisible spacing character used by editors for typographic spacing.",
        "normalize_recommended": True,
        "ascii_replacement": " ",
    },
    "\u2028": {
        "name": "LINE SEPARATOR",
        "classification": "typography",
        "description": "Unicode line break that behaves like a newline but is easy to miss visually.",
        "normalize_recommended": True,
        "ascii_replacement": "\\n",
    },
    "\u2009": {
        "name": "THIN SPACE",
        "classification": "typography",
        "description": "Thin spacing character inserted by editors.",
        "normalize_recommended": True,
        "ascii_replacement": " ",
    },
    "\u2010": {
        "name": "HYPHEN",
        "classification": "typography",
        "description": "Unicode hyphen distinct from ASCII hyphen-minus (-).",
        "normalize_recommended": True,
        "ascii_replacement": "-",
    },
    "\u2015": {
        "name": "HORIZONTAL BAR",
        "classification": "typography",
        "description": "Horizontal bar variant of dash punctuation from editors.",
        "normalize_recommended": True,
        "ascii_replacement": "-",
    },
    "\u00ad": {
        "name": "SOFT HYPHEN",
        "classification": "typography",
        "description": "Invisible hyphenation hint inserted by word processors.",
        "normalize_recommended": True,
        "ascii_replacement": "",
    },
    "\n": {
        "name": "LINE FEED",
        "classification": "control_whitespace",
        "description": "Line break in Contact, PullQuote, or pasted HTML content.",
        "normalize_recommended": False,
        "ascii_replacement": "\\n",
    },
    "\r": {
        "name": "CARRIAGE RETURN",
        "classification": "control_whitespace",
        "description": "Windows-style line ending fragment in HTML or quoted text.",
        "normalize_recommended": False,
        "ascii_replacement": "",
    },
    "\t": {
        "name": "TAB",
        "classification": "control_whitespace",
        "description": "Tab character in Contact or pasted content.",
        "normalize_recommended": False,
        "ascii_replacement": " ",
    },
    "\ufffd": {
        "name": "REPLACEMENT CHARACTER",
        "classification": "data_quality",
        "description": "Indicates corrupted or un-decodable text, often in Tags.",
        "normalize_recommended": True,
        "ascii_replacement": "",
    },
    "\uff06": {
        "name": "FULLWIDTH AMPERSAND",
        "classification": "data_quality",
        "description": "Full-width ampersand in Tags instead of ASCII &.",
        "normalize_recommended": True,
        "ascii_replacement": "&",
    },
}

CLASSIFICATION_SUMMARY = {
    "sharepoint_artifact": (
        "Characters commonly introduced by SharePoint/Word rich-text editing. "
        "These are the main cleanup targets alongside zero-width spaces."
    ),
    "typography": (
        "Editor typography and invisible spacing characters. Often safe to normalize "
        "when converting content to plain ASCII text."
    ),
    "control_whitespace": (
        "Line breaks and tabs. Usually intentional in Contact fields, but worth "
        "reviewing in HTML fields."
    ),
    "data_quality": (
        "Characters that indicate encoding or data-entry problems rather than "
        "normal editorial styling."
    ),
    "legitimate_content": (
        "Valid multilingual content such as accented Latin names, transliteration "
        "marks, Arabic/Urdu poetry, and intentional symbols like £ or °. "
        "Do not strip these during routine SharePoint cleanup."
    ),
    "inferred": (
        "No explicit note exists yet for this character. Classification was inferred "
        "from Unicode category and script."
    ),
}

INVISIBLE_CATEGORIES = {"Cf", "Cc", "Cs"}


def load_news_data(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        return load(f)


def iter_strings(obj, path=""):
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for key, value in obj.items():
            child_path = f"{path}.{key}" if path else key
            yield from iter_strings(value, child_path)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from iter_strings(value, f"{path}[{index}]")


def char_code(char):
    return f"\\u{ord(char):04x}"


def unicode_name(char):
    if char in CHARACTER_CONTEXT:
        return CHARACTER_CONTEXT[char]["name"]
    return unicodedata.name(char, "UNKNOWN")


def is_arabic_script(char):
    code = ord(char)
    return (
        0x0600 <= code <= 0x06FF
        or 0x0750 <= code <= 0x077F
        or 0x08A0 <= code <= 0x08FF
        or 0xFB50 <= code <= 0xFDFF
        or 0xFE70 <= code <= 0xFEFF
    )


def infer_character_context(char):
    category = unicodedata.category(char)
    name = unicode_name(char)

    if category in {"Ll", "Lu", "Lm"} and not char.isascii():
        if is_arabic_script(char):
            description = "Arabic-script character used in PullQuote poetry or transliteration."
        else:
            description = (
                "Latin extended or accented letter used in names, places, or transliteration."
            )
        return {
            "name": name,
            "classification": "legitimate_content",
            "description": description,
            "normalize_recommended": False,
            "ascii_replacement": None,
        }

    if category == "Lo":
        if is_arabic_script(char):
            description = "Arabic-script character used in PullQuote poetry or transliteration."
        else:
            description = "Non-Latin letter used as legitimate editorial content."
        return {
            "name": name,
            "classification": "legitimate_content",
            "description": description,
            "normalize_recommended": False,
            "ascii_replacement": None,
        }

    if category in {"Sc", "Sm", "Sk", "No"}:
        return {
            "name": name,
            "classification": "legitimate_content",
            "description": "Symbol or numeric character used intentionally in content.",
            "normalize_recommended": False,
            "ascii_replacement": None,
        }

    if category == "So" and char not in {"\ufffd", "\uff06"}:
        return {
            "name": name,
            "classification": "legitimate_content",
            "description": "Special symbol used intentionally in content.",
            "normalize_recommended": False,
            "ascii_replacement": None,
        }

    if category in {"Po", "Pd", "Pe", "Pi", "Pf", "Ps"}:
        return {
            "name": name,
            "classification": "inferred",
            "description": (
                "Punctuation character inferred from Unicode category. Review before "
                "normalizing in case it is intentional editorial content."
            ),
            "normalize_recommended": False,
            "ascii_replacement": None,
        }

    if category in INVISIBLE_CATEGORIES:
        return {
            "name": name,
            "classification": "inferred",
            "description": (
                "Invisible or control character inferred from Unicode category. "
                "Review before removing."
            ),
            "normalize_recommended": False,
            "ascii_replacement": None,
        }

    return {
        "name": name,
        "classification": "inferred",
        "description": (
            "Character context inferred automatically. Add an explicit entry to "
            "CHARACTER_CONTEXT if this character needs a fixed editorial note."
        ),
        "normalize_recommended": False,
        "ascii_replacement": None,
    }


def get_character_context(char):
    if char in CHARACTER_CONTEXT:
        return CHARACTER_CONTEXT[char]
    return infer_character_context(char)


def is_special_char(char):
    if char in CHARACTER_CONTEXT:
        return True
    if not char.isascii():
        return True
    if unicodedata.category(char) in INVISIBLE_CATEGORIES:
        return True
    return False


def snippet(text, char, radius=40):
    index = text.find(char)
    if index == -1:
        return ""
    start = max(0, index - radius)
    end = min(len(text), index + radius + 1)
    return text[start:end]


def extract_special_chars(text):
    found = {}
    for char in text:
        if not is_special_char(char):
            continue
        if char not in found:
            context = get_character_context(char)
            found[char] = {
                "code": char_code(char),
                "name": context["name"],
                "unicode_category": unicodedata.category(char),
                "classification": context["classification"],
                "description": context["description"],
                "normalize_recommended": context["normalize_recommended"],
                "ascii_replacement": context["ascii_replacement"],
                "count": 0,
            }
        found[char]["count"] += 1
    return found


def analyze_news_item(news_item_data, filename, findings):
    for field_path, text in iter_strings(news_item_data):
        for char, info in extract_special_chars(text).items():
            entry = findings[char]
            entry.update(
                {
                    "code": info["code"],
                    "name": info["name"],
                    "unicode_category": info["unicode_category"],
                    "classification": info["classification"],
                    "description": info["description"],
                    "normalize_recommended": info["normalize_recommended"],
                    "ascii_replacement": info["ascii_replacement"],
                }
            )
            entry["total_count"] += info["count"]
            entry["fields"].add(field_path)
            entry["files"].add(filename)

            if len(entry["examples"]) < 3:
                entry["examples"].append(
                    {
                        "file": filename,
                        "field": field_path,
                        "snippet": snippet(text, char),
                    }
                )


def new_findings_store():
    return defaultdict(
        lambda: {
            "code": "",
            "name": "",
            "unicode_category": "",
            "classification": "",
            "description": "",
            "normalize_recommended": False,
            "ascii_replacement": None,
            "total_count": 0,
            "fields": set(),
            "files": set(),
            "examples": [],
        }
    )


def iterate_news_items(folder_path):
    findings = new_findings_store()
    json_files = sorted(
        filename for filename in listdir(folder_path) if filename.endswith(".json")
    )

    for filename in json_files:
        news_item_data = load_news_data(join(folder_path, filename))
        analyze_news_item(news_item_data, filename, findings)

    return findings


def sorted_findings(findings):
    return sorted(
        findings.items(),
        key=lambda item: (-item[1]["total_count"], item[1]["code"]),
    )


def print_classification_summary(findings):
    grouped = defaultdict(list)
    for char, info in sorted_findings(findings):
        grouped[info["classification"]].append((char, info))

    print("Classification guide")
    print("=" * 80)
    for classification, description in CLASSIFICATION_SUMMARY.items():
        count = len(grouped.get(classification, []))
        print(f"[{classification}] ({count} characters)")
        print(f"  {description}")
        print()


def print_complete_inventory(findings):
    items = sorted_findings(findings)
    print(f"Complete inventory: {len(items)} unique special characters")
    print("=" * 80)
    print(
        f"{'#':>3}  {'Code':<8}  {'Count':>7}  {'Class':<22}  {'Unicode':<6}  Name"
    )
    print("-" * 80)

    for index, (_, info) in enumerate(items, start=1):
        print(
            f"{index:>3}  {info['code']:<8}  {info['total_count']:>7,}  "
            f"{info['classification']:<22}  {info['unicode_category']:<6}  {info['name']}"
        )

    print()


def print_character_details(findings):
    print("Character details")
    print("=" * 80)

    for index, (char, info) in enumerate(sorted_findings(findings), start=1):
        print(f"{index}. {info['code']} ({info['name']})")
        print(f"   Occurrences: {info['total_count']:,}")
        print(f"   Files: {len(info['files'])}")
        print(f"   Unicode category: {info['unicode_category']}")
        print(f"   Classification: {info['classification']}")
        print(f"   Normalize recommended: {info['normalize_recommended']}")
        if info["ascii_replacement"] is not None:
            print(f"   Suggested replacement: {info['ascii_replacement']!r}")
        print(f"   Context: {info['description']}")
        print(f"   Fields: {', '.join(sorted(info['fields']))}")

        for example in info["examples"]:
            print(f"   Example in {example['file']} [{example['field']}]:")
            print(f"     {example['snippet']!r}")
        print()


def print_report(findings):
    if not findings:
        print("No special Unicode characters found.")
        return

    print_classification_summary(findings)
    print_complete_inventory(findings)
    print_character_details(findings)


def export_report(findings, output_path):
    items = []
    for char, info in sorted_findings(findings):
        items.append(
            {
                "rank": len(items) + 1,
                "character": char,
                "code": info["code"],
                "name": info["name"],
                "unicode_category": info["unicode_category"],
                "classification": info["classification"],
                "description": info["description"],
                "normalize_recommended": info["normalize_recommended"],
                "ascii_replacement": info["ascii_replacement"],
                "total_count": info["total_count"],
                "file_count": len(info["files"]),
                "fields": sorted(info["fields"]),
                "files": sorted(info["files"]),
                "examples": info["examples"],
            }
        )

    payload = {
        "summary": {
            "unique_character_count": len(items),
            "classification_guide": CLASSIFICATION_SUMMARY,
            "by_classification": {
                classification: len(
                    [item for item in items if item["classification"] == classification]
                )
                for classification in CLASSIFICATION_SUMMARY
            },
        },
        "characters": items,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        dump(payload, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    folder_path = join(abspath(dirname(__file__)), "..", "data", "news")
    output_path = join(abspath(dirname(__file__)), "..", "data", "unicode_report.json")

    findings = iterate_news_items(folder_path)
    print_report(findings)
    export_report(findings, output_path)
    print(f"Report exported to {output_path}")
