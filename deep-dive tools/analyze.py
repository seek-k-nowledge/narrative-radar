"""
analyze.py - Step 2 of the Narrative Tracker: find the narratives and how they spread.

What it does, in plain English (standard term in brackets):
  1. Turns each headline into a list of numbers based on which words it uses
     and how rare those words are [TF-IDF vectorization].
  2. Finds groups of words that keep showing up together, and puts each headline
     in the group it matches best. Each group is one "narrative"
     [topic modeling with NMF, non-negative matrix factorization].
     You choose how many groups to look for (default 4). That choice is an
     analyst's judgement call: try 3, 4, 5 and see which reads most sensibly.
  3. Names each group by its strongest words [topic keywords].
  4. Counts each narrative per day and charts it [time series].
  5. Flags days where a narrative jumps far above its normal level
     [spike detection with a z-score: how many standard deviations above average].
  6. Lists which outlets carried each narrative first [early amplifiers] -
     this is where "seeding" shows up.

Usage:
    python analyze.py data/sample_harbor_city.csv
    python analyze.py data/water_rates.csv --narratives 5
    python analyze.py data/water_rates.csv --ignore "water,rates"

Tip: words that appear in almost every headline (your search words, the place name)
blur the groups together. List them with --ignore.

Your CSV needs at least these columns: date, source, title
"""

import argparse
import base64
import html
import io
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.decomposition import NMF
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer

COLORS = ["#2f6690", "#c05746", "#3a7d44", "#8e6c8a", "#d4a017", "#4a8fa0", "#7a5c3e", "#5b5f97"]


def load(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = {"date", "source", "title"} - set(df.columns)
    if missing:
        sys.exit(f"Your CSV is missing these columns: {', '.join(sorted(missing))}")
    df = df.dropna(subset=["title"]).copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    df["day"] = df["date"].dt.normalize()
    return df


def find_narratives(df: pd.DataFrame, k: int, ignore: list[str]):
    stop = list(ENGLISH_STOP_WORDS | {w.strip().lower() for w in ignore if w.strip()})
    vec = TfidfVectorizer(stop_words=stop, ngram_range=(1, 2), min_df=2, max_df=0.5, sublinear_tf=True)
    X = vec.fit_transform(df["title"])
    terms = np.array(vec.get_feature_names_out())

    model = NMF(n_components=k, init="nndsvd", random_state=0, max_iter=800)
    weights = model.fit_transform(X)          # how strongly each headline matches each narrative
    labels = weights.argmax(axis=1)           # each headline goes to its best match
    names = [" / ".join(terms[np.argsort(row)[::-1][:3]]) for row in model.components_]
    return labels, names


def spikes(counts: pd.Series, z_cut: float = 2.0) -> list[tuple[pd.Timestamp, int, float]]:
    mean, std = counts.mean(), counts.std()
    if not std or np.isnan(std):
        return []
    z = (counts - mean) / std
    return [(d, int(counts[d]), float(z[d])) for d in counts.index if z[d] >= z_cut and counts[d] >= 3]


def chart(daily: pd.DataFrame, names: list[str]) -> str:
    fig, ax = plt.subplots(figsize=(10, 4.2), dpi=130)
    for i, col in enumerate(daily.columns):
        ax.plot(daily.index, daily[col], color=COLORS[i % len(COLORS)], lw=2, label=f"N{col + 1}: {names[col]}")
    ax.set_ylabel("Articles per day")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25)
    ax.legend(loc="upper left", fontsize=7.5, frameon=False)
    fig.autofmt_xdate()
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def build_report(df: pd.DataFrame, names: list[str], title: str) -> str:
    all_days = pd.date_range(df["day"].min(), df["day"].max(), freq="D")
    daily = df.groupby(["day", "narrative"]).size().unstack(fill_value=0).reindex(all_days, fill_value=0)
    img = chart(daily, names)

    sections = []
    order = df["narrative"].value_counts().index
    for n in order:
        sub = df[df["narrative"] == n]
        first = sub.iloc[: max(3, len(sub) // 10)]  # earliest 10% of coverage
        early = first["source"].value_counts().head(4)
        sp = spikes(daily[n])
        spike_txt = ", ".join(f"{d:%b %d} ({c} articles, z={z:.1f})" for d, c, z in sp) or "none"
        examples = "".join(
            f"<li><span class='d'>{r.date:%b %d}</span> {html.escape(str(r.title))} "
            f"<span class='s'>{html.escape(str(r.source))}</span></li>"
            for r in sub.head(3).itertuples()
        )
        sections.append(f"""
        <section>
          <h3><span class='sw' style='background:{COLORS[n % len(COLORS)]}'></span>N{n + 1}: {html.escape(names[n])}</h3>
          <p class='meta'>{len(sub)} articles &middot; first seen {sub['date'].min():%b %d} &middot; peak day {daily[n].idxmax():%b %d}</p>
          <p><b>Spikes</b> (days far above normal): {spike_txt}</p>
          <p><b>Early amplifiers</b> (outlets carrying it first): {', '.join(f'{html.escape(s)} ({c})' for s, c in early.items())}</p>
          <ul>{examples}</ul>
        </section>""")

    return f"""<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;max-width:900px;margin:32px auto;padding:0 16px;color:#1d2530;line-height:1.5}}
h1{{margin-bottom:4px}} .sub{{color:#5a6472;margin-top:0}}
img{{max-width:100%;border:1px solid #dde2e8;border-radius:6px}}
section{{border-top:1px solid #dde2e8;padding:12px 0}}
.sw{{display:inline-block;width:12px;height:12px;border-radius:2px;margin-right:8px}}
.meta,.s,.d{{color:#5a6472;font-size:.9em}} .d{{display:inline-block;width:52px}}
.note{{background:#f3f5f8;border-left:3px solid #2f6690;padding:10px 14px;margin:18px 0}}
</style></head><body>
<h1>{html.escape(title)}</h1>
<p class='sub'>{len(df)} articles from {df['source'].nunique()} sources &middot; {df['day'].min():%b %d, %Y} to {df['day'].max():%b %d, %Y} &middot; {len(names)} narratives found</p>
<img src='data:image/png;base64,{img}' alt='Articles per day for each narrative'>
<div class='note'><b>Read this before drawing conclusions.</b> This report shows <i>what</i> was said, <i>when</i>, and <i>who said it first</i>.
It does not show <i>why</i>. Two narratives rising together is a correlation, not proof one caused the other.
Before you call something a coordinated campaign, list the other explanations (a real event, one wire story copied by many sites,
a news cycle) and check which ones the evidence rules out.</div>
{''.join(sections)}
</body></html>"""


def main():
    parser = argparse.ArgumentParser(description="Group headlines into narratives and chart their spread.")
    parser.add_argument("csv", help="CSV from collect.py (or any CSV with date, source, title)")
    parser.add_argument("--narratives", type=int, default=4, help="How many narratives to look for (default 4)")
    parser.add_argument("--ignore", default="", help='Comma-separated words to skip, e.g. "harbor,city"')
    args = parser.parse_args()

    df = load(args.csv)
    if len(df) < 30:
        sys.exit(f"Only {len(df)} headlines. Collect at least 30 for the grouping to mean anything.")
    df["narrative"], names = find_narratives(df, args.narratives, args.ignore.split(","))

    base = os.path.splitext(os.path.basename(args.csv))[0]
    os.makedirs("reports", exist_ok=True)
    out = os.path.join("reports", f"{base}_report.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(build_report(df, names, f"Narrative report: {base.replace('_', ' ')}"))

    print(f"Found {len(names)} narratives in {len(df)} headlines:")
    for i, name in enumerate(names):
        print(f"  N{i + 1}: {name}  ({(df['narrative'] == i).sum()} articles)")
    print(f"Report saved to {out}  (open it in your browser)")


if __name__ == "__main__":
    main()
