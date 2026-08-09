import re

from storyblok_utils import generate_uid

YOUTUBE_PATTERNS = (
    re.compile(r"youtube\.com/embed/([^?&\"']+)", re.I),
    re.compile(r"youtu\.be/([^?&\"']+)", re.I),
    re.compile(r"youtube\.com/watch\?v=([^&\"']+)", re.I),
)

TWITTER_STATUS_PATTERN = re.compile(
    r"(?:twitter\.com|x\.com)/[^/]+/status/(\d+)", re.I
)


def embed_placeholder_tag(embed_type, src):
    return f'<div data-storyblok-embed="{embed_type}" data-src="{src}"></div>'


def detect_embed_type(src):
    src_lower = (src or "").lower()
    if any(token in src_lower for token in ("youtube.com", "youtu.be")):
        return "youtube"
    if "twitter.com" in src_lower or "x.com" in src_lower:
        return "twitter"
    return "iframe"


def extract_youtube_id(url):
    for pattern in YOUTUBE_PATTERNS:
        match = pattern.search(url or "")
        if match:
            return match.group(1)
    return None


def extract_twitter_status_url(html):
    match = TWITTER_STATUS_PATTERN.search(html or "")
    if not match:
        return None
    return f"https://twitter.com/i/status/{match.group(1)}"


def blok_node(component, payload, seed=None):
    body_item = {"_uid": generate_uid(seed), "component": component}
    body_item.update(payload)
    return {"type": "blok", "attrs": {"body": [body_item]}}


def youtube_embed_blok(embed_url, component="video_embed", seed=None):
    video_id = extract_youtube_id(embed_url)
    return blok_node(
        component,
        {
            "provider": "youtube",
            "embed_url": embed_url,
            "video_id": video_id,
        },
        seed=seed or embed_url,
    )


def twitter_embed_blok(tweet_url, component="twitter_embed", seed=None):
    return blok_node(
        component,
        {
            "tweet_url": tweet_url,
        },
        seed=seed or tweet_url,
    )


def iframe_embed_blok(embed_url, component="iframe_embed", seed=None):
    return blok_node(
        component,
        {
            "embed_url": embed_url,
        },
        seed=seed or embed_url,
    )


def embed_blok_from_src(src, config=None):
    config = config or {}
    embed_type = detect_embed_type(src)
    if embed_type == "youtube":
        return youtube_embed_blok(
            src, component=config.get("video_embed_component", "video_embed"), seed=src
        )
    if embed_type == "twitter":
        return twitter_embed_blok(
            src, component=config.get("twitter_embed_component", "twitter_embed"), seed=src
        )
    return iframe_embed_blok(
        src, component=config.get("iframe_embed_component", "iframe_embed"), seed=src
    )


def pull_quote_to_blok_or_richtext(html, config=None):
    if not html or not str(html).strip():
        return None, "empty"

    html_text = str(html)
    if "twitter-tweet" in html_text or "twitter.com" in html_text or "x.com" in html_text:
        tweet_url = extract_twitter_status_url(html_text)
        if tweet_url:
            return twitter_embed_blok(
                tweet_url,
                component=(config or {}).get("twitter_embed_component", "twitter_embed"),
                seed=tweet_url,
            ), "twitter_embed"

    if "<iframe" in html_text.lower():
        src_match = re.search(r'<iframe[^>]+src="([^"]+)"', html_text, re.I)
        if src_match:
            return embed_blok_from_src(src_match.group(1), config=config), "iframe_embed"

    return None, "richtext"
