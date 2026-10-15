"""
watch.py - The Narrative Radar engine. Start it with "Start Narrative Radar.bat", then use the
Radar page at http://localhost:8765 (it opens by itself).

Plain English: every 15 minutes this checks each topic on your watchlist across several free
sources (GDELT, Google News, Bing News, Hacker News, Mastodon, Reddit). It compares the last
hour to the hours before it. If the last hour is far above normal, it alerts you, shows the
newest headlines from every platform, and logs it to alerts.csv.

Standard terms: this is "real-time monitoring" with "anomaly detection". The test it uses is
a z-score: how many standard deviations the last hour sits above the average hour.
z = 3 means "about three times further from normal than usual swings" - rare by chance.

Usage (from this folder):
    python watch.py                      # watch every topic in watchlist.txt, forever
    python watch.py --once               # check once and stop (good for testing)
    python watch.py --every 10 --z 2.5   # check every 10 minutes, alert more easily

Each round also rebuilds dashboard.html (the Narrative Radar page) and opens it in your browser
the first time. Add --no-open to skip opening it.

Optional pop-up notifications on Windows:  python -m pip install plyer
"""

import argparse
import csv
import json
import math
import os
import pathlib
import re
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime

import dashboard
import feeds
import server
import mood
import sources
import trending

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
ALERT_LOG = "alerts.csv"
PAUSE = 15  # GDELT asks for at most one request every 5 seconds; 15 keeps us well under
CACHE = "radar_cache.json"  # last good reading per topic, so the dashboard always has something to show


class GdeltBusy(RuntimeError):
    """GDELT kept saying "too many requests" even after waiting."""


def open_with_retry(req, tries: int = 2) -> str:
    """Ask GDELT, and if it says "too many requests" (HTTP 429), wait 30s and try once more.
    If it still says no, give up for this round instead of hammering it (hammering keeps you blocked).
    Standard terms: retry with backoff, and a circuit breaker."""
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", errors="replace").strip()
        except urllib.error.HTTPError as exc:
            if exc.code != 429:
                raise
            if attempt == tries - 1:
                raise GdeltBusy("GDELT is busy (too many requests)")
            print("    GDELT says slow down; waiting 30s and trying once more...")
            time.sleep(30)


def gdelt(params: dict) -> dict:
    url = GDELT_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "narrative-tracker-watch/0.1 (learning project)"})
    body = open_with_retry(req)
    if not body.startswith("{"):
        raise RuntimeError(body[:200] or "empty reply")
    return json.loads(body)


def volume_series(query: str) -> list[tuple[str, float]]:
    """Article counts in 15-minute steps over the last 48 hours: [(timestamp, count), ...]."""
    data = gdelt({"query": query, "mode": "TimelineVolRaw", "format": "json", "timespan": "48h"})
    return parse_timeline(data)


def parse_timeline(data: dict) -> list[tuple[str, float]]:
    series = (data.get("timeline") or [{}])[0].get("data") or []
    return [(p.get("date", ""), float(p.get("value", 0) or 0)) for p in series]


def hourly(points: list[tuple[str, float]], per_hour: int = 4) -> list[float]:
    """Add 15-minute counts into hourly totals, newest hour last."""
    values = [v for _, v in points]
    usable = len(values) - len(values) % per_hour
    values = values[len(values) - usable:]
    return [sum(values[i:i + per_hour]) for i in range(0, usable, per_hour)]


def spike_check(hours: list[float], z_cut: float, min_articles: int) -> tuple[bool, float, float, float]:
    """Compare the newest hour with all the hours before it. Returns (is_spike, z, latest, average)."""
    if len(hours) < 8:
        return False, 0.0, hours[-1] if hours else 0.0, 0.0
    latest, history = hours[-1], hours[:-1]
    mean = statistics.mean(history)
    spread = statistics.pstdev(history) or 1.0  # avoid dividing by zero on very quiet topics
    z = (latest - mean) / spread
    return (z >= z_cut and latest >= min_articles), z, latest, mean


def notify(title: str, message: str) -> None:
    print("\a", end="")  # terminal beep
    try:
        from plyer import notification  # optional
        notification.notify(title=title, message=message[:250], timeout=15)
    except Exception:
        pass


def log_alert(row: dict) -> None:
    new = not os.path.exists(ALERT_LOG)
    with open(ALERT_LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["time", "query", "z", "last_hour", "normal_hour", "top_headline", "url"])
        if new:
            w.writeheader()
        w.writerow(row)


def load_watchlist(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


def load_cache() -> dict:
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_cache(cache: dict) -> None:
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f)


def last_hour_mix(items: list[dict], now: float) -> tuple[list[float], float]:
    """Hourly counts over 48h (for the chart) and how many items across all sources landed in the last hour."""
    bins = [0.0] * 48
    for it in items:
        age_h = (now - it["ts"]) / 3600
        if 0 <= age_h < 48:
            bins[47 - int(age_h)] += 1
    return bins, bins[-1]


def history_signal(hist: list, latest: float, now: float) -> tuple[float, float, bool]:
    """Search feeds don't give a fair sample over time (they favour fresh stories), so the radar
    compares each reading with its OWN earlier readings of the same thing, taken every round.
    Needs about 2.5 hours of running (6 readings older than an hour) before it will call a spike from this signal.
    Standard term: a rolling baseline built from the tool's own measurements.
    Returns (normal, z, enough_history)."""
    past = [c for t, c in hist if now - t > 3600]
    if len(past) < 6:
        return (statistics.mean(past) if past else 0.0), 0.0, False
    mean = statistics.mean(past)
    spread = max(statistics.pstdev(past), math.sqrt(max(mean, 1.0)))
    return mean, (latest - mean) / spread, True


def summarize(items: list[dict], now: float) -> dict:
    """Per-platform counts for the last 24h, who had it first, mood, and a mixed headline list."""
    day = [it for it in items if now - it["ts"] <= 86400]
    counts, first = {}, {}
    for it in day:
        p = it["platform"]
        counts[p] = counts.get(p, 0) + 1
        if p not in first or it["ts"] < first[p]:
            first[p] = it["ts"]
    heads, per = [], {}
    for it in items:
        if per.get(it["platform"], 0) < 2:
            heads.append({"title": it["title"], "url": it["url"], "domain": it["source"],
                          "platform": it["platform"], "ts": it["ts"], "image": it.get("image", "")})
            per[it["platform"]] = per.get(it["platform"], 0) + 1
        if len(heads) >= 6:
            break
    return {"counts": counts, "first": sorted(first.items(), key=lambda kv: kv[1]),
            "tone": mood.average([it["title"] for it in day]), "headlines": heads}


def check_all(queries: list[str], z_cut: float, min_articles: int, cooldown: dict, cooldown_min: int,
              use_gdelt: bool = True, cache: dict | None = None, pool: list | None = None) -> list[dict]:
    cache = {} if cache is None else cache
    stamp = datetime.now().strftime("%I:%M %p")
    print(f"\n[{stamp}] checking {len(queries)} topics across {len(sources.SOURCES) + 1} sources...")
    results, gdelt_busy = [], not use_gdelt
    for q in queries:
        now = time.time()
        old = cache.get(q, {})
        r = {"query": q, "label": sources.label(q), "z_cut": z_cut, "spike": False, "stale": False, "error": "",
             "as_of": datetime.now().strftime("%I:%M %p"), "signal": "", "status": {}}
        results.append(r)

        items, r["status"] = sources.collect_all(q, pool=pool)
        r["items"] = [{k: it.get(k, "") for k in ("title", "url", "source", "platform", "kind", "image", "ts")}
                      for it in items[:40]]
        z_m = latest_m = mean_m = 0.0
        bins, ok_m = [], False
        hist = [h for h in old.get("hist", []) if now - h[0] < 48 * 3600]
        if items:
            bins, latest_m = last_hour_mix(items, now)
            mean_m, z_m, ok_m = history_signal(hist, latest_m, now)
            hist.append([now, latest_m])
            r.update(summarize(items, now))
        r["hist"] = hist
        r["hist_hours"] = round((now - hist[0][0]) / 3600, 1) if hist else 0

        hours_g, z_g, latest_g, mean_g, ok_g = [], 0.0, 0.0, 0.0, False
        if not gdelt_busy:
            try:
                hours_g = hourly(volume_series(q))
                _, z_g, latest_g, mean_g = spike_check(hours_g, z_cut, min_articles)
                ok_g = len(hours_g) >= 8
                r["status"]["GDELT"] = "ok"
            except GdeltBusy:
                gdelt_busy = True
                r["status"]["GDELT"] = "busy"
                print("    GDELT is busy; using the other sources for the rest of this round.")
            except Exception:
                r["status"]["GDELT"] = "error"
            time.sleep(PAUSE)
        else:
            r["status"]["GDELT"] = "busy" if use_gdelt else "off"

        # Use whichever signal is more alarmed: GDELT counts worldwide news; the mix catches social-first stories.
        if ok_g and (z_g >= z_m or not ok_m):
            r.update(hours=hours_g, latest=latest_g, mean=mean_g, z=z_g, signal="worldwide news count (GDELT)")
            floor = min_articles
        elif ok_m or items:
            r.update(hours=bins, latest=latest_m, mean=mean_m, z=z_m if ok_m else 0.0,
                     signal="all sources vs its own history" if ok_m
                     else f"all sources (learning normal: {r['hist_hours']}h of 2.5h)")
            floor = max(3, min_articles // 2)
        else:
            r.update({k: old.get(k) for k in ("hours", "latest", "mean", "z", "counts", "first", "tone",
                                              "headlines", "as_of", "signal")})
            cache[q] = dict(old, hist=hist)
            r["stale"] = True
            for k, v in (("hours", []), ("latest", 0.0), ("mean", 0.0), ("z", 0.0)):
                r[k] = r[k] if r.get(k) is not None else v
            print(f"  {q}: no source answered; showing the saved reading")
            continue
        r["spike"] = r["z"] >= z_cut and r["latest"] >= floor
        cache[q] = {k: r.get(k) for k in ("hours", "latest", "mean", "z", "counts", "first", "tone",
                                           "headlines", "as_of", "signal", "hist")}
        live = ", ".join(f"{k} {v}" for k, v in r["status"].items())
        marker = "SPIKE" if r["spike"] else "ok"
        print(f"  {q}: last hour {r['latest']:.0f}, normal {r['mean']:.1f}, z={r['z']:.1f}  {marker}   [{live}]")
        time.sleep(2)

        if not r["spike"] or time.time() - cooldown.get(q, 0) < cooldown_min * 60:
            continue
        cooldown[q] = time.time()
        heads = r.get("headlines", [])
        print("\n" + "=" * 70)
        print(f"  SPIKE: '{q}' is {r['latest']:.0f} this hour vs about {r['mean']:.0f} normally (z={r['z']:.1f}, {r['signal']})")
        for h in heads:
            print(f"   - {h.get('title', '').strip()}  [{h.get('platform', '')}: {h.get('domain', '')}]")
            print(f"     {h.get('url', '')}")
        print("  Next: confirm with 2 sources, then run your First Look prompt.")
        print("=" * 70 + "\n")
        top = heads[0] if heads else {}
        notify(f"Spike: {q}", top.get("title", f"{r['latest']:.0f} this hour"))
        log_alert({"time": datetime.now().isoformat(timespec="minutes"), "query": q, "z": round(r["z"], 1),
                   "last_hour": int(r["latest"]), "normal_hour": round(r["mean"], 1),
                   "top_headline": top.get("title", ""), "url": top.get("url", "")})
    save_cache(cache)
    if gdelt_busy and use_gdelt:
        print("GDELT was busy this round. The other sources still worked.")
    return results


def breaking_list(arts: list[dict], vids: list[dict], now: float, minutes: int = 90) -> list[dict]:
    """Newest stories from news outlets and news video channels in the last 90 minutes."""
    news_vids = [v for v in vids if v["source"] not in ("Two Minute Papers", "AI Explained", "Matt Wolfe")]
    fresh = [i for i in arts + news_vids if 0 <= now - i["ts"] <= minutes * 60]
    fresh.sort(key=lambda i: i["ts"], reverse=True)
    for i in fresh:
        i["hot"] = bool(re.search(r"\b(breaking|live|just in|developing)\b", i["title"], re.I)) or now - i["ts"] < 1800
        i["ai"] = trending.is_ai(i["title"])
    return fresh[:40]


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))  # so the server finds its files wherever you start it
    p = argparse.ArgumentParser(description="Narrative Radar: watch topics, breaking news and what is going viral.")
    p.add_argument("--watchlist", default=os.path.join("..", "watchlist.txt"))
    p.add_argument("--every", type=int, default=15, help="Minutes between checks (default 15)")
    p.add_argument("--z", type=float, default=3.0, help="How unusual a spike must be (default 3)")
    p.add_argument("--min", type=int, default=10, help="Minimum articles in the last hour to count (default 10)")
    p.add_argument("--cooldown", type=int, default=120, help="Minutes before the same topic can alert again")
    p.add_argument("--once", action="store_true", help="Check once and stop")
    p.add_argument("--no-open", action="store_true", help="Don't open the Radar in the browser")
    p.add_argument("--no-gdelt", action="store_true", help="Skip GDELT and use only the other sources")
    p.add_argument("--port", type=int, default=8765, help="Port for the Radar page (default 8765)")
    a = p.parse_args()

    url = server.start(a.port) if not a.once else ""
    print("Narrative Radar - Listening Between the Lies")
    print(f"Mood engine: {mood.engine()}.  Open the Radar at: {url or '(server off in --once mode)'}")
    print("Leave this window open. Close it to stop.")
    cooldown: dict = {}
    cache = load_cache()
    opened = False
    if url and not a.no_open:  # open the page right away; it shows the last saved round while the new one runs
        webbrowser.open(url)
        opened = True
    while True:
        started = time.time()
        queries = load_watchlist(a.watchlist)  # re-read every round, so topics added from the page count
        print(f"\n[{datetime.now():%I:%M %p}] reading outlets and video channels...")
        arts, vids, health = feeds.collect()
        print(f"  {len(arts)} outlet stories, {len(vids)} videos")
        print("Checking what's going viral everywhere...")
        trends = trending.collect()
        for name, items in trends.items():
            shown = items if isinstance(items, str) else ", ".join(i["title"][:40] for i in items[:3])
            print(f"  {name}: {shown}")
        results = check_all(queries, a.z, a.min, cooldown, a.cooldown, use_gdelt=not a.no_gdelt,
                            cache=cache, pool=arts + vids)
        now = time.time()
        for r in results:
            for k, v in (r.get("status") or {}).items():
                if k not in ("Outlets", "YouTube"):
                    prev = health.get(k)
                    health[k] = v if not isinstance(prev, int) else prev + (v if isinstance(v, int) else 0)
        alerts = dashboard.read_alerts(ALERT_LOG, limit=50)
        data = {"generated": now, "generated_text": datetime.now().strftime("%I:%M %p"), "every_min": a.every,
                "next_at": now + a.every * 60, "round_secs": round(now - started),
                "topics": results, "trends": trends, "breaking": breaking_list(arts, vids, now),
                "videos": [dict(v, ai=trending.is_ai(v["title"])) for v in vids[:80]],
                "outlets": arts[:120], "health": health, "alerts": alerts, "mood_engine": mood.engine()}
        server.write_data(data)
        page = dashboard.build(results, ALERT_LOG, a.every, trends=trends)
        print(f"Round done in {round(now - started)}s. Radar: {url or page}")
        if not opened and not a.no_open:
            webbrowser.open(url or pathlib.Path(page).as_uri())
            opened = True
        if a.once:
            break
        server.check_now.clear()
        server.check_now.wait(timeout=max(1, a.every) * 60)  # sleep until the next round, or until "Check now"


if __name__ == "__main__":
    main()
