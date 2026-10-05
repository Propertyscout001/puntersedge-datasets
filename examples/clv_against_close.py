"""Score bets against the closing prices in a PuntersEdge dataset release.

Closing-line value (CLV) compares the price you took with the market's last price before the
jump: CLV % = (price taken / closing price - 1) x 100. Beating the close consistently is the
standard evidence that a selection method finds value, independent of whether the bets won.

    python clv_against_close.py au-racing-closing-lines-2026-09.parquet bets.csv

bets.csv needs the columns: venue, meeting_date_aet (YYYY-MM-DD), race_number, runner_name,
price (decimal odds you took). Each bet is scored against the best close across the release's
bookmakers and against the median close.
"""
import re
import sys

import pandas as pd


def fold(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\s*\([^)]*\)\s*$", "", str(name)).lower())


def main(release_path: str, bets_path: str) -> None:
    df = pd.read_parquet(release_path)
    df["meeting_date_aet"] = df["meeting_date_aet"].astype(str)
    df["venue_l"] = df["venue"].str.lower()
    closes = (df.groupby(["venue_l", "meeting_date_aet", "race_number", "runner_key"])
                .agg(close_best=("close_win_price", "max"), close_median=("close_win_price", "median"),
                     books=("bookmaker_key", "nunique"), finish_position=("finish_position", "min"))
                .reset_index())

    bets = pd.read_csv(bets_path)
    bets["venue_l"] = bets["venue"].str.lower()
    bets["meeting_date_aet"] = bets["meeting_date_aet"].astype(str)
    bets["runner_key"] = bets["runner_name"].map(fold)
    scored = bets.merge(closes, on=["venue_l", "meeting_date_aet", "race_number", "runner_key"], how="left")
    scored["clv_vs_best_pct"] = (scored["price"] / scored["close_best"] - 1) * 100
    scored["clv_vs_median_pct"] = (scored["price"] / scored["close_median"] - 1) * 100

    found = scored["close_best"].notna()
    print(scored.loc[:, ["venue", "meeting_date_aet", "race_number", "runner_name", "price",
                         "close_best", "close_median", "clv_vs_median_pct", "finish_position"]].to_string(index=False))
    print(f"\n{found.sum()} of {len(scored)} bets matched a closing price.")
    if found.any():
        m = scored.loc[found]
        print(f"Median CLV against the median close: {m['clv_vs_median_pct'].median():+.1f}%")
        print(f"Bets that beat the median close: {(m['clv_vs_median_pct'] > 0).mean():.0%}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
