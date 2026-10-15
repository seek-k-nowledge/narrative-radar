# Narrative Tracker (v0)

Your first OSINT tool. It collects public news headlines on any topic, groups them into
narratives (the different "stories" being told about that topic), charts how each one
spreads day by day, flags sudden spikes, and shows which outlets carried each story first.

Author: Paul Edward Harris IV

## Set up (Windows, one time)

1. Install Python 3.11 or newer from python.org (tick "Add Python to PATH").
2. Open this folder in VS Code, then open a terminal (Terminal > New Terminal).
3. Install the libraries:

   ```
   python -m pip install -r requirements.txt
   ```

## Practice run (made-up data)

`data/sample_harbor_city.csv` is fictional practice data. Harbor City and every outlet in it are invented.

```
python analyze.py data/sample_harbor_city.csv --ignore "harbor,city"
```

Open `reports/sample_harbor_city_report.html` in your browser.
Exercise: find the narrative that started on small sites and then spread to bigger ones.
Which day did it spike? Which outlets carried it first?

## Real run (live news)

```
python collect.py "water rates" --days 14
python analyze.py data/water_rates.csv --ignore "water,rates"
```

`collect.py` pulls from GDELT, a free public database that monitors news worldwide.
It waits 5 seconds between requests to respect GDELT's limits, so 14 days takes about a minute.

## Spike mode (breaking news alerts)

```
python watch.py
```

Every 15 minutes it checks each topic in `watchlist.txt` and compares the last hour of news
to the previous two days. When a topic jumps far above normal, it beeps, shows the newest
headlines with links, and logs the alert in `alerts.csv`. Leave the window open while you work.

- Edit `watchlist.txt` to watch your own topics (one per line).
- `python watch.py --once` checks once, which is handy for testing.
- `python watch.py --z 2.5` alerts on smaller spikes; `--z 4` only on huge ones.
- For pop-up notifications: `python -m pip install plyer`

When it alerts: confirm with two sources, then use the First Look prompt in your launch plan.

## How it works

| Step | Plain English | Standard term |
|---|---|---|
| 1 | Pull every headline matching your search | Data collection / ingestion |
| 2 | Turn each headline into numbers based on its words | TF-IDF vectorization |
| 3 | Find word groups that travel together; each is a narrative | Topic modeling (NMF) |
| 4 | Count each narrative per day | Time series |
| 5 | Flag days far above normal | Spike detection (z-score) |
| 6 | List who carried it first | Early amplifier analysis |

## What it can't tell you

It shows what was said, when, and by whom first. It does not show why. A spike can come
from a real event, one wire story copied by many sites, or a coordinated push. Your job as
the analyst is to test those explanations against each other before concluding anything.

## Roadmap

- v1: better grouping with AI sentence embeddings (understands meaning, not just shared words)
- v2: add Reddit / Bluesky posts as sources
- v3: network map of which outlets echo which
- v4: compare narrative spikes against real-world event timelines
