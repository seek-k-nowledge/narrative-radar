"""
collect.py - Step 1 of the Narrative Tracker: gather headlines.

Plain English: this asks GDELT (a free, public database that watches news sites
in 100+ languages worldwide) for every article matching your search words,
then saves the headlines to a CSV file (a spreadsheet-style text file).

Standard term: this is "data collection" / "ingestion" from an open source.
Everything here is public news, which is what OSINT (open-source intelligence) means.

Usage (run from this folder in a terminal):
    python collect.py "water rates" --days 14
    python collect.py "\"election\" AND misinformation" --days 7 --out data/election.csv

GDELT query tips:
    Put exact phrases in quotes, e.g.  "\"supply chain\""
    sourcecountry:US    only US outlets
    sourcelang:english  only English articles
"""

import argparse
import csv
import json
import os
import time
import urllib.parse
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


def open_with_retry(req, tries: int = 4) -> str:
    """Ask GDELT, and if it says "too many requests" (HTTP 429), wait longer and try again.
    Standard term: retry with exponential backoff (wait 15s, then 30s, then 60s)."""
    wait = 15
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", errors="replace").strip()
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == tries - 1:
                raise
            print(f"    GDELT says slow down; waiting {wait}s and trying again...")
            time.sleep(wait)
            wait *= 2


def fetch_window(query: str, start: datetime, end: datetime, max_records: int = 250) -> list[dict]:
    """Ask GDELT for up to 250 articles published between start and end."""
    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": str(max_records),
        "sort": "DateAsc",
        "startdatetime": start.strftime("%Y%m%d%H%M%S"),
        "enddatetime": end.strftime("%Y%m%d%H%M%S"),
    }
    url = GDELT_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "narrative-tracker/0.1 (learning project)"})
    body = open_with_retry(req)
    if not body.startswith("{"):
        # GDELT answers in plain text when the query is malformed (e.g. a word that is too short)
        raise RuntimeError(f"GDELT did not return data: {body[:200]}")
    return json.loads(body).get("articles", [])


def collect(query: str, days: int) -> list[dict]:
    """GDELT caps each request at 250 articles, so we ask one day at a time."""
    end = datetime.now(timezone.utc)
    rows, seen = [], set()
    for d in range(days, 0, -1):
        win_start = end - timedelta(days=d)
        win_end = win_start + timedelta(days=1)
        try:
            articles = fetch_window(query, win_start, win_end)
        except Exception as exc:  # keep going if one day fails
            print(f"  skipped {win_start:%Y-%m-%d}: {exc}")
            continue
        for a in articles:
            if a.get("url") in seen:
                continue  # the same story can show up twice
            seen.add(a.get("url"))
            rows.append({
                "date": datetime.strptime(a["seendate"], "%Y%m%dT%H%M%SZ").strftime("%Y-%m-%d %H:%M"),
                "source": a.get("domain", ""),
                "country": a.get("sourcecountry", ""),
                "language": a.get("language", ""),
                "title": a.get("title", "").strip(),
                "url": a.get("url", ""),
            })
        print(f"  {win_start:%Y-%m-%d}: {len(articles)} articles")
        time.sleep(10)  # GDELT asks for at most one request every 5 seconds; 10 keeps us safely under
    return rows


def main():
    parser = argparse.ArgumentParser(description="Collect news headlines from GDELT into a CSV.")
    parser.add_argument("query", help='What to search for, e.g. "water rates"')
    parser.add_argument("--days", type=int, default=7, help="How many days back to look (max about 90)")
    parser.add_argument("--out", default=None, help="Where to save the CSV (default: data/<query>.csv)")
    args = parser.parse_args()

    out = args.out or os.path.join("data", "".join(c if c.isalnum() else "_" for c in args.query).strip("_") + ".csv")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    print(f"Collecting '{args.query}' for the last {args.days} days...")
    rows = collect(args.query, args.days)
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "source", "country", "language", "title", "url"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved {len(rows)} headlines to {out}")
    print(f"Next step:  python analyze.py {out}")


if __name__ == "__main__":
    main()
