---
license: cc-by-4.0
pretty_name: Australian Racing Closing Lines (September 2026)
language:
- en
tags:
- horse-racing
- greyhound-racing
- harness-racing
- odds
- betting
- australia
- sports-analytics
size_categories:
- 100K<n<1M
configs:
- config_name: default
  data_files: au-racing-closing-lines-2026-09.parquet
---

# Australian racing closing lines, September 2026

Opening and closing fixed win prices for 6,310 Australian thoroughbred, harness and greyhound races run in September 2026, at TAB, Ladbrokes, PointsBet, BetRight and TABtouch, with the finishing position where one was published. One row per race, runner and bookmaker. Collected by [PuntersEdge](https://puntersedge.online) from each bookmaker's public prices, released under CC BY 4.0.

| | |
|---|---|
| Rows | 234,451 |
| Races | 6,310 (thoroughbred 1,286, greyhound 3,866, harness 1,158) |
| Races with a result | 98% |
| Period | 2026-09-01 to 2026-09-30 (race start, UTC) |
| Bookmakers | TAB, Ladbrokes, PointsBet, BetRight and TABtouch |
| Files | `au-racing-closing-lines-2026-09.parquet` (2.7 MB), `au-racing-closing-lines-2026-09.csv.gz` (4.2 MB) |

## What is in it

Each row is one bookmaker's price series for one runner: the first price observed once the race entered the 60-minute capture window, the last price observed before the jump, when each was seen, and how many price changes were captured in between. Every row's last observation was within 300 seconds of the advertised start, so `close_win_price` is a closing price, not a last-seen price from earlier in the day.

The rows are exactly what `GET /v1/racing/closing-lines` returns with its default filters for this month, these bookmakers and `country=AU`: series that stopped being quoted more than 300 seconds before the jump are left out, as are runners the result marked scratched and the small number of rows the archive flags as possible venue or name mismatches.

A bookmaker is included in a release when at least 75% of its series that month were last observed within 300 seconds of the jump.

## Two figures from this release

Best or equal-best closing win price, on runners priced by at least three of the five bookmakers:

| Bookmaker | Share of its priced runners |
|---|---|
| PointsBet | 50% |
| BetRight | 45% |
| TAB | 40% |
| TABtouch | 28% |
| Ladbrokes | 19% |

Median market percentage at the close (the sum of 1/price across a full field; 100% would mean no margin), by code:

| Bookmaker | Thoroughbred | Greyhound | Harness |
|---|---|---|---|
| TAB | 121.9% | 123.3% | 126.1% |
| Ladbrokes | 121.4% | 126.1% | 126.8% |
| PointsBet | 119.6% | 122.9% | 124.9% |
| BetRight | 119.9% | 123.1% | 123.7% |
| TABtouch | 120.4% | 123.1% | 125.2% |

Both are computed by `tools/build_sample.py` from the files in this release and are descriptive only.

## Load it

```python
import pandas as pd

df = pd.read_parquet("au-racing-closing-lines-2026-09.parquet")

# Best closing price per runner across the bookmakers in this release
best = (df.groupby(["race_id", "runner_key"])["close_win_price"].max()
          .rename("best_close").reset_index())

# Winners only, from races with a final result
winners = df[(df.result_status == "final") & (df.finish_position == 1)]
```

## Columns

| Column | Type | Meaning |
|---|---|---|
| `race_id` | string | PuntersEdge race identifier. The same id the API returns on /v1/racing/results and /v1/racing/closing-lines. |
| `start_time` | datetime | Advertised start time of the race, UTC. |
| `meeting_date_aet` | date | Racing day the meeting belongs to, in Australian Eastern time. |
| `venue` | string | Venue name. |
| `race_number` | integer | Race number at the meeting. |
| `category` | string | horse (thoroughbred), harness or greyhound. |
| `country` | string | AU for every row in this sample. |
| `runner_key` | string | Runner name folded to lowercase letters and digits. Joins one runner's rows across bookmakers within a race. |
| `runner_name` | string | Runner name as published. |
| `runner_number` | integer | Saddlecloth or rug number. |
| `bookmaker_key` | string | Bookmaker the prices were observed at: tab, ladbrokes_au, pointsbetau, betright or tabtouch, depending on the release. |
| `open_win_price` | number | First fixed win price observed in the series, in decimal odds. |
| `open_secs_to_jump` | integer | Seconds before the advertised start at which the first price was observed. |
| `open_is_baseline` | boolean | True when the series began when the race entered the 60-minute capture window. False when the bookmaker's market appeared later, so the first price is not a market open. |
| `close_win_price` | number | Last fixed win price observed before the jump, in decimal odds. Every row in this sample was last observed within 300 seconds of the advertised start. |
| `close_secs_to_jump` | integer | Seconds before the advertised start at which the last price was observed. |
| `points_observed` | integer | Number of price observations captured in the series. |
| `finish_position` | integer | Official finishing position where one was published. NULL does not mean the runner lost: harness results name the placegetters only, and before 14 September 2026 thoroughbred and greyhound results stored positions 1 to 4 only. |
| `result_status` | string | final, interim or abandoned; NULL when no result is held for the race. |
| `venue_id` | string | Stable PuntersEdge venue identifier. |
| `horse_ref` | string | Thoroughbred identity across meetings: pe: followed by the registered name folded to letters and digits. NULL on greyhound and harness rows. |
| `open_place_price` | number | Place price at the first observation. Captured from 29 September 2026, NULL before then and at bookmakers that price win only. |
| `close_place_price` | number | Place price at the last observation. Same coverage as open_place_price. |

## Things to know before you model on it

- `finish_position` NULL does not mean the runner lost. Harness results name the placegetters only. Thoroughbred and greyhound results position every finisher from 14 September 2026; before that date only positions 1 to 4 were stored. Use `result_status` to tell a race with no result from a runner without a position.
- `open_is_baseline` false means the bookmaker's market appeared after the race entered the capture window, so `open_win_price` is not that market's opening price.
- Place prices start on 29 September 2026.
- Prices are decimal odds as displayed; they include each bookmaker's margin.
- Times are UTC. `meeting_date_aet` is the racing day in Australian Eastern time.

## More data

This is a monthly sample. The same archive is available through the [PuntersEdge API](https://puntersedge.online/api) from 4 August 2026 for 14 Australian bookmakers and New Zealand racing, with full price paths, registry identifiers and a closing-line-value scorer. A free key needs no card. Coverage and freshness are measured on the [data quality page](https://puntersedge.online/data-quality).

## Licence and citation

Data: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Credit "PuntersEdge Australian racing closing-line sample (puntersedge.online), September 2026". The licence covers PuntersEdge's compilation; bookmaker names are trademarks of their owners and this dataset is not affiliated with or endorsed by any bookmaker or racing body.

```bibtex
@misc{puntersedge_closing_lines_2026_09,
  author = {{PuntersEdge}},
  title  = {Australian racing closing lines, September 2026},
  year   = {2026},
  url    = {https://puntersedge.online/datasets},
  note   = {CC BY 4.0}
}
```

Checksums are in `SHA256SUMS`. Generated 2026-10-05T08:08:23Z.

For research and analysis. 18+. Gambling Help Online: 1800 858 858.
