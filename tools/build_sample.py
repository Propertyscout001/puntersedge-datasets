#!/usr/bin/env python3
"""Build one public monthly release of the PuntersEdge Australian racing closing-line sample.

Input is the month file the nightly bulk generator already writes on the API host
(``/var/lib/pe-bulk/closing_lines/YYYY-MM.parquet``). This script never touches the
database or the API: it reads that file, keeps Australian races at the chosen
bookmakers, applies the same default filters as ``GET /v1/racing/closing-lines``, and
writes a self-describing release directory:

    au-racing-closing-lines-YYYY-MM.parquet    zstd Parquet
    au-racing-closing-lines-YYYY-MM.csv.gz     the same rows as gzip CSV
    summary.json                               counts and the measured figures in README.md
    README.md                                  dataset card (also the Hugging Face card)
    datapackage.json                           Frictionless Data Package with the column schema
    .zenodo.json                               Zenodo deposit metadata
    dataset-metadata.json                      Kaggle metadata (set the owner slug before upload)
    LICENSE.txt                                CC BY 4.0 notice for the data
    SHA256SUMS                                 checksums of the two data files

Filters, matching the API defaults so a Plus key reproduces the sample exactly:
    country = AU; bookmaker in --books; is_closing_line = true (last observation within
    300 s of the jump); not venue_split_suspect; not name_fragment_suspect; not scratched.

Quality gate per bookmaker, measured on that book's AU rows for the month BEFORE the
filters: the share of series whose last observation was within 300 s of the jump must be
at least --min-close-share (default 0.75). A book below the gate is left out of the release
and named in the build log (stdout), never in the published files. Fewer than
--min-books books passing, or fewer than --min-result-share of the release's races carrying
a result, makes the build fail with exit code 2 and write nothing.

Usage:
    build_sample.py --month 2026-09 --books tab,ladbrokes_au,pointsbetau,betright,tabtouch \\
        --out /var/lib/pe-public-datasets/au-racing-closing-lines
    (the release lands in <out>/<month>/; an existing release is replaced atomically)
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
import shutil
import statistics
import sys
import tempfile
from collections import Counter, defaultdict

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

SITE = "https://puntersedge.online"
DATASET_SLUG = "au-racing-closing-lines"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"

BOOK_NAMES = {
    "tab": "TAB",
    "ladbrokes_au": "Ladbrokes",
    "neds": "Neds",
    "pointsbetau": "PointsBet",
    "betright": "BetRight",
    "tabtouch": "TABtouch",
    "sportsbet": "Sportsbet",
    "palmerbet": "Palmerbet",
    "unibet": "Unibet",
    "betr_au": "Betr",
    "playup": "NextBet",
    "betgold": "BetGold",
    "boostbet": "BoostBet",
    "betdeluxe": "BetDeluxe",
}
CODE_NAMES = {"horse": "thoroughbred", "harness": "harness", "greyhound": "greyhound"}
NUMBER_WORDS = {3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}

# Public column set, in the API's own order (dropped: close_lay_price, which only an
# exchange quotes; the flag columns the filters make constant; venue_site; runner_ref,
# the third-party registry code; scratched_at).
COLUMNS = [
    ("race_id", "string", "PuntersEdge race identifier. The same id the API returns on /v1/racing/results and /v1/racing/closing-lines."),
    ("start_time", "datetime", "Advertised start time of the race, UTC."),
    ("meeting_date_aet", "date", "Racing day the meeting belongs to, in Australian Eastern time."),
    ("venue", "string", "Venue name."),
    ("race_number", "integer", "Race number at the meeting."),
    ("category", "string", "horse (thoroughbred), harness or greyhound."),
    ("country", "string", "AU for every row in this sample."),
    ("runner_key", "string", "Runner name folded to lowercase letters and digits. Joins one runner's rows across bookmakers within a race."),
    ("runner_name", "string", "Runner name as published."),
    ("runner_number", "integer", "Saddlecloth or rug number."),
    ("bookmaker_key", "string", "Bookmaker the prices were observed at: tab, ladbrokes_au, pointsbetau, betright or tabtouch, depending on the release."),
    ("open_win_price", "number", "First fixed win price observed in the series, in decimal odds."),
    ("open_secs_to_jump", "integer", "Seconds before the advertised start at which the first price was observed."),
    ("open_is_baseline", "boolean", "True when the series began when the race entered the 60-minute capture window. False when the bookmaker's market appeared later, so the first price is not a market open."),
    ("close_win_price", "number", "Last fixed win price observed before the jump, in decimal odds. Every row in this sample was last observed within 300 seconds of the advertised start."),
    ("close_secs_to_jump", "integer", "Seconds before the advertised start at which the last price was observed."),
    ("points_observed", "integer", "Number of price observations captured in the series."),
    ("finish_position", "integer", "Official finishing position where one was published. NULL does not mean the runner lost: harness results name the placegetters only, and before 14 September 2026 thoroughbred and greyhound results stored positions 1 to 4 only."),
    ("result_status", "string", "final, interim or abandoned; NULL when no result is held for the race."),
    ("venue_id", "string", "Stable PuntersEdge venue identifier."),
    ("horse_ref", "string", "Thoroughbred identity across meetings: pe: followed by the registered name folded to letters and digits. NULL on greyhound and harness rows."),
    ("open_place_price", "number", "Place price at the first observation. Captured from 29 September 2026, NULL before then and at bookmakers that price win only."),
    ("close_place_price", "number", "Place price at the last observation. Same coverage as open_place_price."),
    # Appended 2026-10-05 (API migration 061). The same value on every bookmaker row of a runner.
    ("consensus_close_prob", "number", "The market's margin-free probability for the runner at the close: each included bookmaker's implied probabilities (1 / price) raised to the exponent that makes them sum to one (the power method), the median across bookmakers, the field scaled to one. Power replaced the simple divide-by-the-sum on 6 October 2026 because it is calibrated across the price range; every archived row carries the one method. Computed over every Australian bookmaker in the archive (14), not only the five in this release. It describes what the market implied, not the outcome."),
    ("consensus_close_price", "number", "1 / consensus_close_prob."),
    ("books_in_consensus_close", "integer", "Bookmakers whose closing line entered consensus_close_prob."),
    ("consensus_open_price", "number", "The same price from series that began at the 60-minute baseline. NULL where fewer than two complete-field bookmakers did."),
    ("books_in_consensus_open", "integer", "Bookmakers behind consensus_open_price."),
]
FRICTIONLESS_TYPE = {"string": "string", "datetime": "datetime", "date": "date", "integer": "integer", "number": "number", "boolean": "boolean"}


def log(msg: str) -> None:
    print(msg, flush=True)


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def month_bounds(month: str) -> tuple[dt.date, dt.date]:
    first = dt.date.fromisoformat(month + "-01")
    nxt = (first.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return first, nxt - dt.timedelta(days=1)


def measured_figures(rows: list[dict], books: list[str]) -> dict:
    """Two descriptive figures computed on the release itself.

    best_price_share: for runners priced at the close by at least three of the release's
    books, the share of each book's priced runners on which it held the best or equal-best
    closing win price.
    median_market_pct: per race and book, the sum of 1/close_win_price over the runners,
    counted only when the book priced every runner any release book priced in that race;
    reported as the median by book and code (100% would be a market with no margin).
    """
    by_runner = defaultdict(dict)
    for r in rows:
        by_runner[(r["race_id"], r["runner_key"])][r["bookmaker_key"]] = r["close_win_price"]
    priced = Counter()
    best = Counter()
    for prices in by_runner.values():
        if len(prices) < 3:
            continue
        top = max(prices.values())
        for bk, p in prices.items():
            priced[bk] += 1
            if p >= top - 1e-9:
                best[bk] += 1
    best_share = {bk: round(best[bk] / priced[bk], 4) for bk in books if priced[bk]}

    field = defaultdict(set)          # race -> runner_keys priced by any book
    book_field = defaultdict(dict)    # (race, book) -> {runner_key: price}
    code_of = {}
    for r in rows:
        field[r["race_id"]].add(r["runner_key"])
        book_field[(r["race_id"], r["bookmaker_key"])][r["runner_key"]] = r["close_win_price"]
        code_of[r["race_id"]] = r["category"]
    market = defaultdict(list)
    for (race, bk), prices in book_field.items():
        if set(prices) != field[race] or len(prices) < 2:
            continue
        market[(bk, code_of[race])].append(sum(1.0 / p for p in prices.values() if p and p > 0))
    median_market = {}
    for (bk, code), vals in market.items():
        median_market.setdefault(bk, {})[code] = {"median_pct": round(100 * statistics.median(vals), 1), "races": len(vals)}
    return {"best_price_share": best_share, "median_market_pct": median_market,
            "runners_priced_by_3_or_more_books": sum(1 for p in by_runner.values() if len(p) >= 3)}


def build(args) -> int:
    src = os.path.join(args.bulk_dir, f"{args.month}.parquet")
    if not os.path.exists(src):
        log(f"FAIL: {src} does not exist")
        return 2
    books_req = [b.strip() for b in args.books.split(",") if b.strip()]
    table = pq.read_table(src)
    au = table.filter(pc.equal(table["country"], "AU"))

    # Quality gate per requested book, before filtering.
    passing, gate_log = [], []
    for bk in books_req:
        t = au.filter(pc.equal(au["bookmaker_key"], bk))
        n = t.num_rows
        share = (pc.sum(pc.cast(t["is_closing_line"], pa.int64())).as_py() or 0) / n if n else 0.0
        ok = n > 0 and share >= args.min_close_share
        gate_log.append((bk, n, share, ok))
        if ok:
            passing.append(bk)
    for bk, n, share, ok in gate_log:
        log(f"gate {bk:<14} rows={n:>7} close_share={share:.3f} {'PASS' if ok else 'LEFT OUT'}")
    if len(passing) < args.min_books:
        log(f"FAIL: {len(passing)} books pass the gate, need {args.min_books}")
        return 2

    mask = pc.is_in(au["bookmaker_key"], value_set=pa.array(passing))
    t = au.filter(mask)
    for col in ("venue_split_suspect", "name_fragment_suspect", "scratched"):
        t = t.filter(pc.invert(pc.fill_null(t[col], False)))
    t = t.filter(pc.fill_null(t["is_closing_line"], False))
    t = t.select([c for c, _, _ in COLUMNS])
    t = t.sort_by([("start_time", "ascending"), ("race_id", "ascending"), ("runner_number", "ascending"), ("bookmaker_key", "ascending")])
    rows = t.to_pylist()
    if not rows:
        log("FAIL: no rows after filters")
        return 2

    races = {r["race_id"] for r in rows}
    resulted = {r["race_id"] for r in rows if r["result_status"] is not None}
    result_share = len(resulted) / len(races)
    if result_share < args.min_result_share:
        log(f"FAIL: {result_share:.3f} of races carry a result, need {args.min_result_share}")
        return 2

    first, last = month_bounds(args.month)
    starts = [r["start_time"] for r in rows]
    by_code = Counter(r["category"] for r in rows)
    races_by_code = Counter()
    seen = set()
    for r in rows:
        if r["race_id"] not in seen:
            seen.add(r["race_id"])
            races_by_code[r["category"]] += 1
    close_share = {bk: round(s, 4) for bk, n, s, ok in gate_log if ok}
    figures = measured_figures(rows, passing)
    stamp = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)

    out_root = os.path.abspath(args.out)
    os.makedirs(out_root, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix=f".{args.month}.", dir=out_root)
    try:
        base = f"{DATASET_SLUG}-{args.month}"
        pq_path = os.path.join(tmp, base + ".parquet")
        csv_path = os.path.join(tmp, base + ".csv.gz")
        pq.write_table(t, pq_path, compression="zstd")
        with gzip.open(csv_path, "wb") as gz:
            pacsv.write_csv(t, gz)
        files = {
            os.path.basename(pq_path): {"bytes": os.path.getsize(pq_path), "sha256": sha256(pq_path), "format": "parquet", "mediatype": "application/vnd.apache.parquet"},
            os.path.basename(csv_path): {"bytes": os.path.getsize(csv_path), "sha256": sha256(csv_path), "format": "csv", "mediatype": "text/csv", "compression": "gz"},
        }
        summary = {
            "dataset": DATASET_SLUG,
            "release": args.month,
            "generated_at": stamp.isoformat().replace("+00:00", "Z"),
            "period": {"from": first.isoformat(), "to": last.isoformat()},
            "first_start_utc": min(starts).isoformat(), "last_start_utc": max(starts).isoformat(),
            "rows": len(rows), "races": len(races),
            "rows_by_code": dict(by_code), "races_by_code": dict(races_by_code),
            "rows_by_book": dict(Counter(r["bookmaker_key"] for r in rows)),
            "bookmakers": passing,
            "close_share_before_filter": close_share,
            "races_with_result_share": round(result_share, 4),
            "rows_with_finish_position": sum(1 for r in rows if r["finish_position"] is not None),
            "figures": figures,
            "filters": ["country = AU", "last observation within 300 s of the jump (is_closing_line)",
                        "venue-split and name-fragment suspects removed", "runners the result marked scratched removed"],
            "license": "CC-BY-4.0",
            "files": files,
            "revision": args.revision,
            "revision_note": args.note or None,
            "revision_date": stamp.date().isoformat(),
        }
        with open(os.path.join(tmp, "summary.json"), "w") as fh:
            json.dump(summary, fh, indent=1, default=str)
        with open(os.path.join(tmp, "SHA256SUMS"), "w") as fh:
            for name, meta in files.items():
                fh.write(f"{meta['sha256']}  {name}\n")
        with open(os.path.join(tmp, "LICENSE.txt"), "w") as fh:
            fh.write(license_text(args.month))
        with open(os.path.join(tmp, "README.md"), "w") as fh:
            fh.write(readme(summary))
        with open(os.path.join(tmp, "datapackage.json"), "w") as fh:
            json.dump(datapackage(summary), fh, indent=1)
        with open(os.path.join(tmp, ".zenodo.json"), "w") as fh:
            json.dump(zenodo(summary), fh, indent=1)
        with open(os.path.join(tmp, "dataset-metadata.json"), "w") as fh:
            json.dump(kaggle(summary), fh, indent=1)
        final = os.path.join(out_root, args.month)
        if os.path.exists(final):
            old = final + ".old"
            if os.path.exists(old):
                shutil.rmtree(old)
            os.rename(final, old)
            os.rename(tmp, final)
            shutil.rmtree(old)
        else:
            os.rename(tmp, final)
        os.chmod(final, 0o755)
        for name in os.listdir(final):
            os.chmod(os.path.join(final, name), 0o644)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    log(f"OK {args.month}: {len(rows)} rows, {len(races)} races, books {','.join(passing)}, "
        f"results on {pct(result_share)} of races -> {final}")
    return 0


def book_list(keys: list[str]) -> str:
    names = [BOOK_NAMES.get(k, k) for k in keys]
    return ", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else names[0]


def month_title(month: str) -> str:
    return dt.date.fromisoformat(month + "-01").strftime("%B %Y")


def license_text(month: str) -> str:
    return (
        f"Australian Racing Closing Lines, {month_title(month)} release, by PuntersEdge\n"
        f"is licensed under the Creative Commons Attribution 4.0 International licence (CC BY 4.0).\n"
        f"{LICENSE_URL}\n\n"
        "Attribution: \"PuntersEdge Australian racing closing-line sample (puntersedge.online), "
        f"{month_title(month)}, CC BY 4.0\".\n\n"
        "The licence covers PuntersEdge's compilation: the selection, capture timing, joins and\n"
        "flags. Prices are PuntersEdge's observations of prices each bookmaker displayed publicly.\n"
        "Bookmaker names are trademarks of their owners; this dataset is not affiliated with or\n"
        "endorsed by any bookmaker or racing body.\n"
    )


def readme(s: dict) -> str:
    m = s["release"]
    title = f"Australian racing closing lines, {month_title(m)}"
    books = book_list(s["bookmakers"])
    pq_name = f"{DATASET_SLUG}-{m}.parquet"
    csv_name = f"{DATASET_SLUG}-{m}.csv.gz"
    codes = ", ".join(f"{CODE_NAMES[c]} {s['races_by_code'].get(c, 0):,}" for c in ("horse", "greyhound", "harness"))
    fig = s["figures"]
    best_rows = "\n".join(
        f"| {BOOK_NAMES.get(bk, bk)} | {pct(v)} |" for bk, v in sorted(fig["best_price_share"].items(), key=lambda kv: -kv[1]))
    mk_rows = []
    for bk in s["bookmakers"]:
        cells = []
        for code in ("horse", "greyhound", "harness"):
            v = fig["median_market_pct"].get(bk, {}).get(code)
            cells.append(f"{v['median_pct']:.1f}%" if v else "n/a")
        mk_rows.append(f"| {BOOK_NAMES.get(bk, bk)} | " + " | ".join(cells) + " |")
    mk_rows = "\n".join(mk_rows)
    cols = "\n".join(f"| `{c}` | {ty} | {desc} |" for c, ty, desc in COLUMNS)
    files = s["files"]
    n_books = NUMBER_WORDS.get(len(s["bookmakers"]), str(len(s["bookmakers"])))
    front = (
        "---\n"
        "license: cc-by-4.0\n"
        f"pretty_name: Australian Racing Closing Lines ({month_title(m)})\n"
        "language:\n- en\n"
        "tags:\n- horse-racing\n- greyhound-racing\n- harness-racing\n- odds\n- betting\n- australia\n- sports-analytics\n"
        "size_categories:\n- 100K<n<1M\n"
        "configs:\n- config_name: default\n  data_files: " + pq_name + "\n"
        "---\n\n"
    )
    rev = ""
    if s.get("revision", 1) > 1:
        when = dt.date.fromisoformat(s["revision_date"]).strftime("%-d %B %Y")
        rev = (f"## Revisions\n\nRevision {s['revision']} ({when}): {s.get('revision_note') or 'rebuilt.'} "
               f"The files, checksums and `datapackage.json` version changed; cite the version `{version_of(s)}`.\n\n")
    body = front + f"""# {title}

Opening and closing fixed win prices for {s['races']:,} Australian thoroughbred, harness and greyhound races run in {month_title(m)}, at {books}, with the finishing position where one was published. One row per race, runner and bookmaker. Collected by [PuntersEdge]({SITE}) from each bookmaker's public prices, released under CC BY 4.0.

| | |
|---|---|
| Rows | {s['rows']:,} |
| Races | {s['races']:,} ({codes}) |
| Races with a result | {pct(s['races_with_result_share'])} |
| Period | {s['period']['from']} to {s['period']['to']} (race start, UTC) |
| Bookmakers | {books} |
| Files | `{pq_name}` ({files[pq_name]['bytes'] / 1e6:.1f} MB), `{csv_name}` ({files[csv_name]['bytes'] / 1e6:.1f} MB) |

## What is in it

Each row is one bookmaker's price series for one runner: the first price observed once the race entered the 60-minute capture window, the last price observed before the jump, when each was seen, and how many price changes were captured in between. Every row's last observation was within 300 seconds of the advertised start, so `close_win_price` is a closing price, not a last-seen price from earlier in the day.

The rows are exactly what `GET /v1/racing/closing-lines` returns with its default filters for this month, these bookmakers and `country=AU`: series that stopped being quoted more than 300 seconds before the jump are left out, as are runners the result marked scratched and the small number of rows the archive flags as possible venue or name mismatches.

A bookmaker is included in a release when at least 75% of its series that month were last observed within 300 seconds of the jump.

## Two figures from this release

Best or equal-best closing win price, on runners priced by at least three of the {n_books} bookmakers:

| Bookmaker | Share of its priced runners |
|---|---|
{best_rows}

Median market percentage at the close (the sum of 1/price across a full field; 100% would mean no margin), by code:

| Bookmaker | Thoroughbred | Greyhound | Harness |
|---|---|---|---|
{mk_rows}

Both are computed by `tools/build_sample.py` from the files in this release and are descriptive only.

## Load it

```python
import pandas as pd

df = pd.read_parquet("{pq_name}")

# Best closing price per runner across the bookmakers in this release
best = (df.groupby(["race_id", "runner_key"])["close_win_price"].max()
          .rename("best_close").reset_index())

# Winners only, from races with a final result
winners = df[(df.result_status == "final") & (df.finish_position == 1)]
```

## Columns

| Column | Type | Meaning |
|---|---|---|
{cols}

## Things to know before you model on it

- `finish_position` NULL does not mean the runner lost. Harness results name the placegetters only. Thoroughbred and greyhound results position every finisher from 14 September 2026; before that date only positions 1 to 4 were stored. Use `result_status` to tell a race with no result from a runner without a position.
- `open_is_baseline` false means the bookmaker's market appeared after the race entered the capture window, so `open_win_price` is not that market's opening price.
- Place prices start on 29 September 2026.
- Prices are decimal odds as displayed; they include each bookmaker's margin.
- Times are UTC. `meeting_date_aet` is the racing day in Australian Eastern time.

## More data

This is a monthly sample. The same archive is available through the [PuntersEdge API]({SITE}/api) from 4 August 2026 for 14 Australian bookmakers and New Zealand racing, with full price paths, registry identifiers and a closing-line-value scorer. A free key needs no card. Coverage and freshness are measured on the [data quality page]({SITE}/data-quality).

## Licence and citation

Data: [CC BY 4.0]({LICENSE_URL}). Credit "PuntersEdge Australian racing closing-line sample (puntersedge.online), {month_title(m)}". The licence covers PuntersEdge's compilation; bookmaker names are trademarks of their owners and this dataset is not affiliated with or endorsed by any bookmaker or racing body.

```bibtex
@misc{{puntersedge_closing_lines_{m.replace('-', '_')},
  author = {{{{PuntersEdge}}}},
  title  = {{Australian racing closing lines, {month_title(m)}}},
  year   = {{{m[:4]}}},
  url    = {{{SITE}/datasets}},
  note   = {{CC BY 4.0}}
}}
```

Checksums are in `SHA256SUMS`. Generated {s['generated_at']}.

For research and analysis. 18+. Gambling Help Online: 1800 858 858.
"""
    return body.replace("## Licence and citation", rev + "## Licence and citation", 1)


def version_of(s: dict) -> str:
    """'2026-09' for a first build, '2026-09.2' for its second revision — so a citation names the files."""
    return s["release"] if s.get("revision", 1) == 1 else f"{s['release']}.{s['revision']}"


def datapackage(s: dict) -> dict:
    m = s["release"]
    res = []
    for name, meta in s["files"].items():
        r = {"name": name.replace(".", "-").lower(), "path": name, "format": meta["format"], "mediatype": meta["mediatype"],
             "bytes": meta["bytes"], "hash": "sha256:" + meta["sha256"],
             "schema": {"fields": [{"name": c, "type": FRICTIONLESS_TYPE[ty], "description": d} for c, ty, d in COLUMNS]}}
        if meta.get("compression"):
            r["compression"] = meta["compression"]
        res.append(r)
    return {
        "name": f"{DATASET_SLUG}-{m}",
        "title": f"Australian racing closing lines, {month_title(m)}",
        "description": f"Opening and closing fixed win prices for Australian racing at {book_list(s['bookmakers'])}, with results. One row per race, runner and bookmaker.",
        "homepage": f"{SITE}/datasets",
        "version": version_of(s),
        "created": s["generated_at"],
        "licenses": [{"name": "CC-BY-4.0", "path": LICENSE_URL, "title": "Creative Commons Attribution 4.0"}],
        "sources": [{"title": "PuntersEdge closing-line archive", "path": f"{SITE}/data-quality"}],
        "keywords": ["horse racing", "greyhound racing", "harness racing", "odds", "closing line", "Australia"],
        "resources": res,
    }


def zenodo(s: dict) -> dict:
    m = s["release"]
    return {
        "title": f"Australian racing closing lines, {month_title(m)} (PuntersEdge sample)",
        "upload_type": "dataset",
        "description": (f"<p>Opening and closing fixed win prices for {s['races']:,} Australian thoroughbred, harness and greyhound races "
                        f"in {month_title(m)} at {book_list(s['bookmakers'])}, with finishing positions where published. "
                        f"{s['rows']:,} rows, one per race, runner and bookmaker. Every closing price was observed within 300 seconds "
                        f"of the advertised start. Collected by PuntersEdge from each bookmaker's public prices.</p>"),
        "creators": [{"name": "Carter, Hamish", "affiliation": "PuntersEdge"}],
        "license": "cc-by-4.0",
        "access_right": "open",
        "version": version_of(s),
        "keywords": ["horse racing", "greyhound racing", "harness racing", "betting odds", "closing line value", "Australia"],
        "related_identifiers": [{"identifier": f"{SITE}/datasets", "relation": "isDocumentedBy", "resource_type": "other"}],
    }


def kaggle(s: dict) -> dict:
    m = s["release"]
    return {
        "title": f"Australian Racing Closing Lines {m}",
        "subtitle": f"Opening and closing win prices with results, {NUMBER_WORDS.get(len(s['bookmakers']), len(s['bookmakers']))} bookmakers",
        "id": "KAGGLE_USERNAME/australian-racing-closing-lines",
        "licenses": [{"name": "CC-BY-4.0"}],
        "keywords": ["horse racing", "sports", "betting", "australia"],
        "description": readme(s).split("---\n\n", 1)[1],
        "resources": [{"path": name, "description": f"{month_title(m)} release, {meta['format']}"} for name, meta in s["files"].items()],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--month", required=True, help="YYYY-MM")
    ap.add_argument("--books", default="tab,ladbrokes_au,pointsbetau,betright,tabtouch")
    ap.add_argument("--bulk-dir", default="/var/lib/pe-bulk/closing_lines")
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-close-share", type=float, default=0.75)
    ap.add_argument("--min-result-share", type=float, default=0.90)
    ap.add_argument("--min-books", type=int, default=3)
    ap.add_argument("--revision", type=int, default=1,
                    help="Revision number when a published month is rebuilt on purpose (default 1)")
    ap.add_argument("--note", default="",
                    help="What changed in this revision; written to README.md, summary.json and the metadata")
    return build(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
