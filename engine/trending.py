"""
trending.py - "What's going viral right now", whatever the topic.

Plain English: your watchlist only catches topics you already thought of. This file grabs what is
blowing up everywhere right now, so you can spot a story nobody has put on a list yet:
  - Google Trends: what Americans are suddenly searching for, with rough search counts
  - Google News: today's top stories
  - Mastodon: the links people are sharing most on the open social web
  - Hacker News: the front page of the tech and AI crowd, with upvotes
  - Wikipedia: the pages people read most yesterday (a strong sign of public attention)

Standard terms: trend detection / attention signals from several "trending" feeds.
Anything that mentions AI is flagged so you can see where AI is in the conversation.
"""

import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from sources import UA, _clean, _get

AI_WORDS = re.compile(r"\b(ai|a\.i\.|artificial intelligence|openai|chatgpt|anthropic|claude|gemini|llm|"
                      r"deepfakes?|chatbots?|machine learning|nvidia|superintelligence|agi|grok|copilot)\b", re.I)
HT = "{https://trends.google.com/trending/rss}"


def is_ai(text: str) -> bool:
    return bool(AI_WORDS.search(text or ""))


def google_trends(n=10):
    root = ET.fromstring(_get("https://trends.google.com/trending/rss?geo=US"))
    out = []
    for it in list(root.iter("item"))[:n]:
        news = it.find(HT + "news_item")
        url = news.findtext(HT + "news_item_url", "") if news is not None else ""
        why = news.findtext(HT + "news_item_title", "") if news is not None else ""
        term = it.findtext("title", "")
        pic = it.findtext(HT + "picture", "")
        out.append({"title": term, "extra": it.findtext(HT + "approx_traffic", "") + " searches",
                    "url": url or f"https://www.google.com/search?q={term}", "note": _clean(why), "image": pic})
    return out


def google_top(n=10):
    root = ET.fromstring(_get("https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"))
    out = []
    for it in list(root.iter("item"))[:n]:
        src = it.find("source")
        source = src.text if src is not None and src.text else ""
        title = _clean(it.findtext("title", ""))
        if source and title.endswith(" - " + source):
            title = title[: -len(source) - 3]
        out.append({"title": title, "extra": source, "url": it.findtext("link", ""), "note": ""})
    return out


def mastodon_links(n=10):
    data = json.loads(_get("https://mastodon.social/api/v1/trends/links?limit=20"))
    out = []
    for d in data[:n]:
        hist = d.get("history") or [{}]
        people = hist[0].get("accounts", "")
        out.append({"title": _clean(d.get("title", "")), "extra": f"{people} people sharing today" if people else "",
                    "url": d.get("url", ""), "note": d.get("provider_name", ""), "image": d.get("image") or ""})
    return out


def hacker_news_front(n=10):
    data = json.loads(_get("https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=30"))
    hits = sorted(data.get("hits", []), key=lambda h: h.get("points") or 0, reverse=True)[:n]
    return [{"title": _clean(h.get("title", "")), "extra": f"{h.get('points', 0)} points",
             "url": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
             "note": f"{h.get('num_comments', 0)} comments"} for h in hits]


def wikipedia_top(n=10):
    day = datetime.now(timezone.utc) - timedelta(days=1)
    url = f"https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia/all-access/{day:%Y/%m/%d}"
    data = json.loads(_get(url))
    arts = data["items"][0]["articles"]
    skip = ("Main_Page", "Special:", "Wikipedia:", "Portal:", "File:", "Help:", "Talk:", "Template:", "Category:")
    out = []
    for a in arts:
        name = a["article"]
        if name.startswith(skip) or name in ("-", "Undefined", "XXX"):
            continue
        out.append({"title": name.replace("_", " "), "extra": f"{a['views']:,} views",
                    "url": f"https://en.wikipedia.org/wiki/{name}", "note": ""})
        if len(out) >= n:
            break
    return out


FEEDS = {
    "Google searches": google_trends,
    "Top news": google_top,
    "Shared on Mastodon": mastodon_links,
    "Hacker News front page": hacker_news_front,
    "Wikipedia most read": wikipedia_top,
}


def collect() -> dict:
    """Returns {feed name: list of items or an error string}. Each item gets an 'ai' flag."""
    out = {}
    for name, fetch in FEEDS.items():
        try:
            items = fetch()
            for it in items:
                it["ai"] = is_ai(it["title"] + " " + it.get("note", ""))
            out[name] = items
        except Exception as exc:
            out[name] = "blocked" if "403" in str(exc) or "429" in str(exc) else "unavailable"
    return out
