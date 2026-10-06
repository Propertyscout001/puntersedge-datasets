"""Build the three notebooks in puntersedge-datasets/notebooks/ (source of truth for their cells).

    python build_notebooks.py OUT_DIR

Writes unexecuted notebooks; execute them with nbconvert afterwards.
"""
import sys
import nbformat as nbf

REPO = "Propertyscout001/puntersedge-datasets"


def colab(name):
    return (f"[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)]"
            f"(https://colab.research.google.com/github/{REPO}/blob/main/notebooks/{name})")


LOAD = '''import os

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

RELEASE = "2026-09"
URL = ("https://puntersedge.online/datasets/au-racing-closing-lines/"
       f"{RELEASE}/au-racing-closing-lines-{RELEASE}.parquet")

# Reads the release straight from puntersedge.online (about 3 MB).
# Set PUNTERSEDGE_DATASET_FILE to the path of a downloaded copy to read that instead.
df = pd.read_parquet(os.environ.get("PUNTERSEDGE_DATASET_FILE", URL))

NAMES = {"tab": "TAB", "ladbrokes_au": "Ladbrokes", "pointsbetau": "PointsBet",
         "betright": "BetRight", "tabtouch": "TABtouch"}
print(f"{len(df):,} rows, {df.race_id.nunique():,} races, "
      f"{df.meeting_date_aet.min()} to {df.meeting_date_aet.max()}")
print("Bookmakers:", ", ".join(NAMES.get(b, b) for b in sorted(df.bookmaker_key.unique())))'''

STYLE = '''GREEN, AMBER, GREY, INK = "#1B7A4B", "#E3A008", "#8A948C", "#131C16"
plt.rcParams.update({
    "figure.dpi": 110, "font.size": 10, "axes.titlesize": 11, "axes.titleweight": "bold",
    "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": "#B8C1B6",
    "axes.grid": True, "grid.color": "#E6EAE3", "grid.linewidth": 0.8, "axes.axisbelow": True,
    "text.color": INK, "axes.labelcolor": INK, "xtick.color": "#5C6961", "ytick.color": "#5C6961",
    "text.parse_math": False,                 # "$3.00 to $6.99" is a price range, not maths
})'''

RESULTS = '''# One row per runner, for races with a final result and exactly one winner.
# Harness results name the placegetters only, so an empty finish_position in a resulted
# race means the runner did not win.
winners = df[df.finish_position.eq(1)].groupby("race_id").runner_key.nunique()
resulted = df[df.result_status.eq("final")].race_id.unique()
single = winners[winners.eq(1)].index.intersection(resulted)

runners = (df[df.race_id.isin(single)]
           .groupby(["race_id", "runner_key"])
           .agg(category=("category", "first"),
                best_open=("open_win_price", "max"),
                best_close=("close_win_price", "max"),
                fair_open=("consensus_open_price", "first"),
                fair_close=("consensus_close_price", "first"),
                from_baseline=("open_is_baseline", "all"),
                won=("finish_position", lambda s: bool((s == 1).any())))
           .reset_index())
print(f"{runners.race_id.nunique():,} races with one winner, {len(runners):,} runners")'''

FOOTER = '''---
Data: [PuntersEdge Australian racing closing-line sample](https://puntersedge.online/datasets), CC BY 4.0.
Credit "PuntersEdge Australian racing closing-line sample (puntersedge.online)". Code in this notebook: MIT.
The full archive, every served bookmaker and New Zealand racing are in the [PuntersEdge API](https://puntersedge.online/api).

For research and analysis, not betting advice. 18+. Gambling Help Online: 1800 858 858.'''


def nb(cells):
    n = nbf.v4.new_notebook()
    n.metadata = {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                  "language_info": {"name": "python"}, "colab": {"provenance": []}}
    n.cells = [nbf.v4.new_markdown_cell(c[1]) if c[0] == "md" else nbf.v4.new_code_cell(c[1]) for c in cells]
    return n


# ── 01 ───────────────────────────────────────────────────────────────────────
NB1 = "01_which_bookmaker_is_sharpest.ipynb"
nb1 = nb([
    ("md", f'''# Which bookmaker is sharpest?

{colab(NB1)}

Two different questions hide inside "which bookmaker is best":

1. **Who pays the most?** How often each bookmaker has the best price, how far its prices sit from the typical price, and how much margin it builds into a race.
2. **Who is sharpest?** Whose prices best predict which runner wins. A sharp bookmaker's prices are accurate; a generous one's are long. They are not the same thing.

This notebook answers both from the free monthly [closing-line dataset](https://puntersedge.online/datasets), using the same method as the daily [PuntersEdge bookmaker report](https://puntersedge.online/bookmaker-report). The report compares every served bookmaker; the dataset carries five of them, so here the comparison is among those five. Runs top to bottom in Colab with nothing to install.'''),
    ("code", LOAD),
    ("code", STYLE),
    ("md", '''## 1. Who has the best price most often?

Every row is one runner at one bookmaker, with the bookmaker's last win price before the jump (`close_win_price`). For each runner we find the highest closing price across the bookmakers that priced it. A bookmaker scores when its price equals that best price; equal-best counts for everyone at that price, so the shares do not add to 100%.

Bookmakers price favourites and long shots differently, so we also split runners by their median closing price.'''),
    ("code", '''BANDS = [(1, 3, "Under $3.00"), (3, 7, "$3.00 to $6.99"), (7, 15, "$7.00 to $14.99"), (15, np.inf, "$15.00 and over")]

close_all = df[df.close_win_price > 1]                         # every closing price
close = close_all.copy()
g = close.groupby(["race_id", "runner_key"])
close["n_books"] = g.bookmaker_key.transform("nunique")
close = close[close.n_books >= 3].copy()                       # three prices before "best" means anything
g = close.groupby(["race_id", "runner_key"])
close["best"] = g.close_win_price.transform("max")
close["median"] = g.close_win_price.transform("median")
close["is_best"] = close.close_win_price >= close.best - 1e-9
close["band"] = pd.cut(close["median"], [b[0] for b in BANDS] + [np.inf], right=False,
                       labels=[b[2] for b in BANDS])

best = (close.groupby(["bookmaker_key", "band"], observed=True).is_best.mean().unstack() * 100)
best.insert(0, "All prices", close.groupby("bookmaker_key").is_best.mean() * 100)
best = best.rename(index=NAMES).sort_values("All prices", ascending=False).round(1)
print(f"{close.drop_duplicates(['race_id', 'runner_key']).shape[0]:,} runners with three or more closing prices")
best'''),
    ("code", '''fig, axes = plt.subplots(1, 4, figsize=(12, 2.9), sharex=True)
for ax, (_, _, label) in zip(axes, BANDS):
    col = best[label].sort_values()
    colors = [AMBER if v == col.max() else GREEN for v in col]
    ax.barh(col.index, col.values, color=colors, height=0.6)
    ax.set_title(label)
    ax.grid(axis="y", visible=False)
    top = col.idxmax()
    ax.annotate(f"{col.max():.0f}%", (col.max(), list(col.index).index(top)),
                xytext=(4, 0), textcoords="offset points", va="center", fontsize=9, color=INK)
axes[0].set_xlabel("Best or equal-best price (% of runners)")
fig.suptitle("Who had the best closing price, by the runner's median price", x=0.01, ha="left", fontweight="bold")
fig.tight_layout()
plt.show()'''),
    ("code", '''leaders = {label: best[label].idxmax() for _, _, label in BANDS}
for label, book in leaders.items():
    print(f"{label:>16}: {book} ({best.loc[book, label]}%)")'''),
    ("md", '''The leader changes with the price. That is the practical answer to "which bookmaker has the best odds": it depends on what you back.

## 2. How far from the typical price?

Best-price share says how often a bookmaker wins; it does not say by how much. Here each closing price is divided by the median closing price for the same runner, minus one. +2% means the bookmaker's price was 2% longer than the typical price.'''),
    ("code", '''close["rel"] = close.close_win_price / close["median"] - 1
rel = close.groupby(["bookmaker_key", "band"], observed=True).rel.mean().unstack() * 100
rel.insert(0, "All prices", close.groupby("bookmaker_key").rel.mean() * 100)
rel.rename(index=NAMES).sort_values("All prices", ascending=False).round(2)'''),
    ("md", '''## 3. Market percentage

The sum of `1 / price` over a race's runners is the bookmaker's market percentage: 100% would be a market with no margin. It is only meaningful when the bookmaker priced the whole field, so races where it missed a runner are left out.'''),
    ("code", '''per_book = close_all.groupby(["race_id", "bookmaker_key"]).runner_key.transform("nunique")
field = per_book.groupby(close_all.race_id).transform("max")
full = close_all[(per_book == field) & (field >= 4)]
book_pct = (full.assign(inv=1 / full.close_win_price)
                .groupby(["race_id", "bookmaker_key"])
                .agg(category=("category", "first"), pct=("inv", "sum")))
mkt = book_pct.groupby(["bookmaker_key", "category"]).pct.median().unstack() * 100
mkt.insert(0, "All codes", book_pct.groupby("bookmaker_key").pct.median() * 100)
mkt.rename(index=NAMES).sort_values("All codes").round(1)'''),
    ("md", r'''## 4. Who is sharpest?

Sharpness is about accuracy, not generosity. For each resulted race with one winner where a bookmaker priced the full field:

1. Remove the bookmaker's margin with the **power method**: find the exponent $k$ for which $\sum_i (1/\text{price}_i)^k = 1$, then each runner's probability is $(1/\text{price}_i)^k$. It takes more margin out of long shots than proportional scaling does, which matches how bookmakers build their markets.
2. Take the probability the bookmaker gave the **winner** and compare it with the average bookmaker in the same race, as a log score. Comparing within a race cancels out how predictable that race was.
3. Average across races. A positive figure means the bookmaker's prices gave winners more probability than the field did.

Five bookmakers are compared at once, so a difference counts only if its 95% interval clears zero after a Bonferroni correction. It is measured on the prices 60 minutes before the jump (series that began at the start of the archive's capture window) and on closing prices.'''),
    ("code", '''from statistics import NormalDist


def power_probabilities(prices, groups):
    """Margin-free probabilities by the power method, solved for every group at once."""
    p = 1.0 / np.asarray(prices, dtype=float)
    g = np.asarray(groups)
    n = g.max() + 1
    lo, hi = np.full(n, 0.05), np.full(n, 20.0)
    for _ in range(80):                                     # bisection on k, per group
        k = (lo + hi) / 2
        over = np.bincount(g, weights=p ** k[g], minlength=n) > 1
        lo, hi = np.where(over, k, lo), np.where(over, hi, k)
    q = p ** ((lo + hi) / 2)[g]
    return q / np.bincount(g, weights=q, minlength=n)[g]


# Races with a final result and exactly one winner (dead heats are left out).
winners = df[df.finish_position.eq(1)].groupby("race_id").runner_key.nunique()
single = winners[winners.eq(1)].index.intersection(df[df.result_status.eq("final")].race_id.unique())
winner = df[df.race_id.isin(single) & df.finish_position.eq(1)].groupby("race_id").runner_key.first()


def sharpness(rows, price_col):
    rows = rows[rows.race_id.isin(single) & rows[price_col].gt(1)]
    per_book = rows.groupby(["race_id", "bookmaker_key"]).runner_key.transform("nunique")
    field = per_book.groupby(rows.race_id).transform("max")
    rows = rows[(per_book == field) & (field >= 4)].sort_values(["race_id", "bookmaker_key", "runner_key"])
    gid = rows.groupby(["race_id", "bookmaker_key"], sort=False).ngroup().to_numpy()
    rows = rows.assign(prob=power_probabilities(rows[price_col].to_numpy(), gid))
    w = rows[rows.runner_key.to_numpy() == rows.race_id.map(winner).to_numpy()]
    w = w.assign(log_score=np.log(w.prob))
    w = w[w.groupby("race_id").bookmaker_key.transform("size") >= 2]
    w = w.assign(diff=w.log_score - w.groupby("race_id").log_score.transform("mean"))
    z_crit = NormalDist().inv_cdf(1 - 0.025 / w.bookmaker_key.nunique())
    out = w.groupby("bookmaker_key")["diff"].agg(["size", "mean", "std"])
    out["z"] = out["mean"] / (out["std"] / np.sqrt(out["size"]))
    out["vs field %"] = (np.exp(out["mean"]) - 1) * 100
    out["verdict"] = np.select([out.z >= z_crit, out.z <= -z_crit], ["sharper", "less sharp"], "no measurable difference")
    out = out.rename(columns={"size": "races"}).rename(index=NAMES)
    return out[["races", "vs field %", "z", "verdict"]].sort_values("vs field %", ascending=False).round(3), z_crit


at_open, z_crit = sharpness(df[df.open_is_baseline], "open_win_price")
at_close, _ = sharpness(df, "close_win_price")
print(f"Verdict threshold: |z| >= {z_crit:.2f}\\n\\n60 minutes out")
display(at_open)
print("At the close")
display(at_close)'''),
    ("code", '''spread = max(at_open["vs field %"].abs().max(), at_close["vs field %"].abs().max())
print(f"Every bookmaker gave winners within {spread:.2f}% of the field's probability, 60 minutes out and at the close.")'''),
    ("md", '''## What this shows

- **The best price depends on the price.** One bookmaker leads on favourites and another on long shots, so a punter who backs favourites and one who backs roughies should not be shopping at the same place.
- **Sharpness differences are small.** Even where a difference clears the bar, the bookmakers' closing prices give winners almost exactly the same probability. They differ on price, not on judgement, so shopping for price matters more than finding the "sharp" book.
- **Five bookmakers, one month.** "The field" here is the five bookmakers in the sample. The [bookmaker report](https://puntersedge.online/bookmaker-report) runs the same method on every served bookmaker over the last 28 days, every day.

Next: [Measure your closing-line value](02_measure_your_closing_line_value.ipynb) · [Does late money win?](03_does_late_money_win.ipynb)'''),
    ("md", FOOTER),
])

# ── 02 ───────────────────────────────────────────────────────────────────────
NB2 = "02_measure_your_closing_line_value.ipynb"
nb2 = nb([
    ("md", f'''# Measure your closing-line value

{colab(NB2)}

**Closing-line value (CLV)** compares the price you took with the fair price at the jump:

$$\\text{{CLV}} = \\frac{{\\text{{price taken}}}}{{\\text{{fair closing price}}}} - 1$$

If the closing market is accurate, the expected return of a bet is exactly its CLV: back a runner at $6.00 whose fair closing price is $5.00 and you expect to make 20% on that bet, win or lose. That makes CLV the fastest honest scorecard for a betting method. Profit takes thousands of bets to separate skill from luck; CLV gets there in a fraction of that.

This notebook checks that claim on a month of real Australian racing, then shows how to score your own bets. It uses the free [closing-line dataset](https://puntersedge.online/datasets) and runs in Colab with nothing to install.'''),
    ("code", LOAD),
    ("code", STYLE),
    ("md", '''## The fair closing price

Each row carries `consensus_close_price`: the market's margin-free price for the runner at the close. Each bookmaker's margin is removed with the power method, the median probability across bookmakers is taken, and the field is renormalised to 100%. It is the same for every bookmaker's row of that runner.

We keep races with a final result and one winner.'''),
    ("code", RESULTS),
    ("md", '''## Does CLV predict profit?

To test it we need a lot of bets with a wide spread of CLV. Take every runner at its **best opening price** across the five bookmakers, 60 minutes before the jump, and score it against the fair closing price. This is not a betting method; it is a large, varied sample.

If the fair closing price is accurate, the average return in each CLV bucket should sit on the dashed line, where return equals CLV.'''),
    ("code", '''bets = runners[runners.from_baseline & runners.fair_close.notna() & runners.best_open.gt(1)].copy()
bets["clv"] = bets.best_open / bets.fair_close - 1
bets["profit"] = np.where(bets.won, bets.best_open - 1, -1.0)       # $1 win bets

edges = [-1, -0.3, -0.2, -0.1, 0, 0.1, 0.2, 0.4, np.inf]
bets["bucket"] = pd.cut(bets.clv, edges)
by = bets.groupby("bucket", observed=True).agg(bets=("profit", "size"), mean_clv=("clv", "mean"),
                                               roi=("profit", "mean"), sd=("profit", "std"))
by["roi_se"] = by.sd / np.sqrt(by.bets)
by[["mean_clv", "roi", "roi_se"]] = by[["mean_clv", "roi", "roi_se"]] * 100
by.drop(columns="sd").round(1)'''),
    ("code", '''fig, ax = plt.subplots(figsize=(6.4, 4.4))
lim = [min(by.mean_clv.min(), (by.roi - 2 * by.roi_se).min()) - 5, max(by.mean_clv.max(), (by.roi + 2 * by.roi_se).max()) + 5]
ax.plot(lim, lim, ls="--", lw=1.2, color=GREY)
ax.annotate("return = CLV", (lim[1], lim[1]), xytext=(-6, -14), textcoords="offset points", ha="right", color=GREY, fontsize=9)
ax.errorbar(by.mean_clv, by.roi, yerr=2 * by.roi_se, fmt="o", ms=7, color=GREEN, ecolor=GREEN, elinewidth=1.4, capsize=3)
ax.axhline(0, color="#B8C1B6", lw=1)
ax.set_xlim(lim); ax.set_ylim(lim)
ax.set_xlabel("Average CLV in the bucket (%)")
ax.set_ylabel("Average return per $1 bet (%)")
ax.set_title("Realised return tracks closing-line value\\n(bars: about 95% interval)", loc="left")
fig.tight_layout()
plt.show()'''),
    ("md", '''Every bucket's interval reaches the dashed line: on average, the return was the CLV. The intervals on the right are wide because long-priced winners are rare, which is the next point.

## Why CLV is the better scorecard

A $1 win bet returns either −$1 or a large win, so profit is noisy. CLV is known the moment the race jumps and varies far less from bet to bet. Here is how precisely each one estimates your edge after a given number of bets.'''),
    ("code", '''sd_profit = bets.profit.std()
sd_clv = bets.clv.std()
for n in (100, 500, 2000):
    print(f"after {n:>5,} bets: profit is accurate to about ±{2 * sd_profit / np.sqrt(n) * 100:4.1f}%, "
          f"CLV to about ±{2 * sd_clv / np.sqrt(n) * 100:4.1f}%")
print(f"\\nProfit needs about {(sd_profit / sd_clv) ** 2:.0f}x as many bets as CLV to reach the same precision.")'''),
    ("md", '''## Score your own bets

Put your bets in a CSV with the columns `venue`, `meeting_date_aet` (YYYY-MM-DD), `race_number`, `runner_name` and `price` (the decimal odds you took), then read it in place of the example below. The example uses three real runners from the release with made-up prices.'''),
    ("code", '''import re


def fold(name):
    """The dataset's runner_key: lowercase letters and digits, country suffix dropped."""
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\\s*\\([^)]*\\)\\s*$", "", str(name)).lower())


fair = (df.groupby(["venue", "meeting_date_aet", "race_number", "runner_key"])
          .agg(fair_close=("consensus_close_price", "first"), best_close=("close_win_price", "max"),
               finish_position=("finish_position", "min"))
          .reset_index())
fair["meeting_date_aet"] = fair.meeting_date_aet.astype(str)


def score(bets):
    b = bets.assign(runner_key=bets.runner_name.map(fold), venue_l=bets.venue.str.lower(),
                    meeting_date_aet=bets.meeting_date_aet.astype(str))
    out = b.merge(fair.assign(venue_l=fair.venue.str.lower()).drop(columns="venue"),
                  on=["venue_l", "meeting_date_aet", "race_number", "runner_key"], how="left")
    out["clv_%"] = (out.price / out.fair_close - 1) * 100
    out["vs_best_close_%"] = (out.price / out.best_close - 1) * 100
    return out[["venue", "meeting_date_aet", "race_number", "runner_name", "price", "fair_close",
                "best_close", "clv_%", "vs_best_close_%", "finish_position"]].round(2)


# Example: three runners from the release, with made-up prices taken.
sample = df[df.consensus_close_price.notna()].drop_duplicates("runner_key").sample(3, random_state=7)
my_bets = pd.DataFrame({
    "venue": sample.venue.values, "meeting_date_aet": sample.meeting_date_aet.astype(str).values,
    "race_number": sample.race_number.values, "runner_name": sample.runner_name.values,
    "price": (sample.consensus_close_price * [1.15, 0.95, 1.05]).round(2).values,
})
# my_bets = pd.read_csv("my_bets.csv")
scored = score(my_bets)
scored'''),
    ("code", '''matched = scored.fair_close.notna()
print(f"{matched.sum()} of {len(scored)} bets matched a fair closing price; "
      f"average CLV {scored.loc[matched, 'clv_%'].mean():+.1f}%")'''),
    ("md", '''A positive average CLV over a few hundred bets is far stronger evidence of an edge than a profit over the same bets. Bets the dataset can't match are usually a venue spelled differently or a race outside the release's month and bookmakers.

Next: [Does late money win?](03_does_late_money_win.ipynb) · Previous: [Which bookmaker is sharpest?](01_which_bookmaker_is_sharpest.ipynb)'''),
    ("md", FOOTER),
])

# ── 03 ───────────────────────────────────────────────────────────────────────
NB3 = "03_does_late_money_win.ipynb"
nb3 = nb([
    ("md", f'''# Does late money win?

{colab(NB3)}

A runner that **firms** (its price shortens) in the last hour is said to carry "the money". A **drifter** goes the other way. Two questions:

1. Do runners that firm win more often than their **opening** price said they would?
2. Do they win more often than their **closing** price says?

If the answer to the first is yes and the second is no, the closing market has already absorbed whatever the late money knew. This notebook checks both on a month of Australian racing from the free [closing-line dataset](https://puntersedge.online/datasets), in Colab with nothing to install.'''),
    ("code", LOAD),
    ("code", STYLE),
    ("md", '''We use the market's margin-free consensus price for each runner: `consensus_open_price` from series that began 60 minutes before the jump, and `consensus_close_price` at the close. Races with a final result and one winner only.'''),
    ("code", RESULTS),
    ("md", '''## Is the closing price right?

First, a check on the yardstick. Group runners by the probability the closing price gave them and compare it with how often they actually won. A well-calibrated market sits on the diagonal.'''),
    ("code", '''cal = runners[runners.fair_close.notna()].assign(p=lambda x: 1 / x.fair_close)
cal["bin"] = pd.qcut(cal.p, 10)
c = cal.groupby("bin", observed=True).agg(runners=("won", "size"), implied=("p", "mean"), won=("won", "mean"))
c[["implied", "won"]] *= 100

fig, ax = plt.subplots(figsize=(5.2, 5))
ax.plot([0, c.implied.max() * 1.08], [0, c.implied.max() * 1.08], ls="--", lw=1.2, color=GREY)
ax.plot(c.implied, c.won, "o", ms=8, color=GREEN)
ax.set_xlabel("Probability from the closing price (%)")
ax.set_ylabel("Actual win rate (%)")
ax.set_title("The closing price is well calibrated\\n(each dot: a tenth of all runners)", loc="left")
fig.tight_layout()
plt.show()
c.round(1)'''),
    ("md", '''## Late money

Now group runners by how far the consensus price moved between 60 minutes out and the jump, and compare the actual win rate with what the opening price and the closing price implied.'''),
    ("code", '''mv = runners[runners.fair_open.notna() & runners.fair_close.notna()].copy()
mv["move"] = mv.fair_close / mv.fair_open - 1
labels = ["Firmed 30%+", "Firmed 15–30%", "Firmed 5–15%", "Steady", "Drifted 5–20%", "Drifted 20–50%", "Drifted 50%+"]
mv["group"] = pd.cut(mv.move, [-1, -0.3, -0.15, -0.05, 0.05, 0.2, 0.5, np.inf], labels=labels)
late = mv.groupby("group", observed=True).agg(runners=("won", "size"),
                                              opening_implied=("fair_open", lambda s: (1 / s).mean()),
                                              closing_implied=("fair_close", lambda s: (1 / s).mean()),
                                              won=("won", "mean"))
late[["opening_implied", "closing_implied", "won"]] *= 100
late.round(1)'''),
    ("code", '''fig, ax = plt.subplots(figsize=(8.6, 4.2))
x = np.arange(len(late))
ax.plot(x, late.opening_implied, "o", ms=8, color=AMBER, label="Opening price implied")
ax.plot(x, late.closing_implied, "o", ms=11, mfc="none", mec=INK, mew=1.4, label="Closing price implied")
ax.plot(x, late.won, "o", ms=6, color=GREEN, label="Actually won")
ax.set_xticks(x, late.index, rotation=0, fontsize=8.5)
ax.set_ylabel("Win rate (%)")
ax.set_title("Firmers win more than their opening price said, and about what the close said", loc="left")
ax.legend(frameon=False, loc="upper right")
fig.tight_layout()
plt.show()'''),
    ("code", '''f = late.loc["Firmed 30%+"]
print(f"Runners that firmed 30% or more won {f.won:.1f}% of the time: their opening price implied "
      f"{f.opening_implied:.1f}% and their closing price {f.closing_implied:.1f}%.")
d = late.loc["Drifted 50%+"]
print(f"Runners that drifted 50% or more won {d.won:.1f}%: opening price {d.opening_implied:.1f}%, "
      f"closing price {d.closing_implied:.1f}%.")'''),
    ("md", '''The late money was right about which runners would improve their chances, and the closing price already knew it. Backing a runner *because* it has firmed buys a price that has already moved.

## What being early is worth

The flip side: if you can get on **before** the move, at the best price available 60 minutes out, the return is very different from backing the same runners at the best closing price. This is hindsight (nobody knows in advance which runners will firm), but it shows where the value in a price move sits.'''),
    ("code", '''mv["ret_open"] = np.where(mv.won, mv.best_open - 1, -1.0)
mv["ret_close"] = np.where(mv.won, mv.best_close - 1, -1.0)
worth = mv.groupby("group", observed=True)[["ret_open", "ret_close"]].mean() * 100
worth.columns = ["Return at best opening price (%)", "Return at best closing price (%)"]
worth.round(1)'''),
    ("md", '''## By code'''),
    ("code", '''firmers = mv[mv.move <= -0.15]
(firmers.groupby("category")
        .agg(runners=("won", "size"),
             opening_implied=("fair_open", lambda s: (1 / s).mean() * 100),
             closing_implied=("fair_close", lambda s: (1 / s).mean() * 100),
             won=("won", lambda s: s.mean() * 100))
        .round(1))'''),
    ("md", '''## What this shows

- The closing price is a good estimate of a runner's chance, which is why [closing-line value](02_measure_your_closing_line_value.ipynb) works as a scorecard.
- Runners that firm in the last hour win far more often than their opening price implied and about as often as their closing price implies. The information arrives before the jump and the market prices it.
- The value in a move belongs to whoever bet before it. Following the move at the close gains nothing over the close itself.

Previous: [Measure your closing-line value](02_measure_your_closing_line_value.ipynb) · [Which bookmaker is sharpest?](01_which_bookmaker_is_sharpest.ipynb)'''),
    ("md", FOOTER),
])

if __name__ == "__main__":
    out = sys.argv[1]
    for name, book in ((NB1, nb1), (NB2, nb2), (NB3, nb3)):
        nbf.write(book, f"{out}/{name}")
        print("wrote", name)
