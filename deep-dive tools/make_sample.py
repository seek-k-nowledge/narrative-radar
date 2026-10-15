"""
make_sample.py - builds a practice dataset so you can learn the tool before using real news.

EVERYTHING IN IT IS MADE UP. "Harbor City" is a fictional town and the outlets are fictional.
The story built in on purpose: a water-rate increase gets covered normally, then around
day 11 a contamination scare appears on three small sites first and spreads to bigger ones.
Your job when you run analyze.py on it: see whether the report catches that pattern.
"""

import csv
import random
from datetime import datetime, timedelta

random.seed(7)
START = datetime(2026, 8, 1)
DAYS = 30

MAINSTREAM = ["harborcitytimes.example", "coastalledger.example", "wbhc-news.example", "stateherald.example", "morningpost.example"]
FRINGE = ["truthwaterwatch.example", "freeharbornews.example", "patriotpulse.example"]

# Each headline is assembled from a random opener + a random ending, so no two read exactly alike,
# but every headline in a narrative shares that narrative's core words (like real coverage does).
NARRATIVES = {
    "rates": {
        "openers": ["Harbor City water rates to rise {pct}%", "Council approves water rate increase",
                    "Water rate hike of {pct}% approved", "Residents push back on water rate increase",
                    "Utility defends water rate hike"],
        "endings": ["as utility cites aging pipes", "after heated council vote", "starting next month",
                    "- what it means for your bill", "despite resident complaints"],
        "daily": lambda d: 4 if d in (2, 3) else 1 + (d % 3 == 0),
        "sources": MAINSTREAM,
    },
    "contamination": {
        "openers": ["Leaked report claims tap water contamination", "Families fear tap water contamination",
                    "Tap water contamination rumors spread", "Is Harbor City tap water contaminated?",
                    "Health officials respond to tap water contamination claims"],
        "endings": ["as officials stay silent", "- parents switch to bottled water", "after viral post",
                    "while tests remain unreleased", "that officials call unverified"],
        "daily": lambda d: 0 if d < 11 else (2 if d == 11 else (9 if d in (13, 14) else 3)),
        "sources": None,  # fringe first, then everyone
    },
    "drought": {
        "openers": ["Drought drops reservoir to {pct}-year low", "Reservoir levels fall as drought deepens",
                    "Drought watch declared as reservoir shrinks", "Dry summer drains reservoir"],
        "endings": ["with rainfall below normal", "and no relief expected before autumn",
                    "across the county", "as heat wave continues"],
        "daily": lambda d: 2 if d < 18 else 1,
        "sources": MAINSTREAM,
    },
    "conservation": {
        "openers": ["Water conservation plan limits lawn watering", "Utility offers conservation rebates",
                    "Conservation tips to cut household water use", "New water conservation rules"],
        "endings": ["starting Monday", "for low-flow toilets and showerheads", "this summer",
                    "ask residents to skip car washes"],
        "daily": lambda d: 1 if d % 2 == 0 else 0,
        "sources": MAINSTREAM,
    },
}

rows = []
for d in range(DAYS):
    day = START + timedelta(days=d)
    for key, n in NARRATIVES.items():
        for _ in range(n["daily"](d)):
            if key == "contamination":
                src_pool = FRINGE if d <= 12 else FRINGE + MAINSTREAM
            else:
                src_pool = n["sources"]
            title = (random.choice(n["openers"]) + " " + random.choice(n["endings"])).format(pct=random.choice([8, 12, 15, 20]))
            ts = day + timedelta(hours=random.randint(6, 22), minutes=random.randint(0, 59))
            rows.append({"date": ts.strftime("%Y-%m-%d %H:%M"), "source": random.choice(src_pool),
                         "country": "US", "language": "English", "title": title, "url": ""})

rows.sort(key=lambda r: r["date"])
with open("data/sample_harbor_city.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
print(f"Wrote {len(rows)} made-up practice headlines to data/sample_harbor_city.csv")
