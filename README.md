# PuntersEdge open datasets

Free monthly samples of the [PuntersEdge](https://puntersedge.online) Australian racing closing-line archive, released under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

<!-- releases:start -->
| Release | Races | Rows | Bookmakers | Files |
|---|---|---|---|---|
| [September 2026](releases/2026-09/README.md) | 6,274 | 233,872 | TAB, Ladbrokes, PointsBet, BetRight, TABtouch | [Parquet](https://puntersedge.online/datasets/au-racing-closing-lines/2026-09/au-racing-closing-lines-2026-09.parquet) · [CSV](https://puntersedge.online/datasets/au-racing-closing-lines/2026-09/au-racing-closing-lines-2026-09.csv.gz) |

Last checked against the site on 2026-10-05.
<!-- releases:end -->

Each release holds the opening and closing fixed win prices for Australian thoroughbred, harness and greyhound races at a set of bookmakers, one row per race, runner and bookmaker, with the finishing position where one was published. Every closing price was observed within 300 seconds of the advertised start. Each release's two data files and their checksums are also attached to the matching [GitHub release](https://github.com/Propertyscout001/puntersedge-datasets/releases). The page with every release, checksums and the column reference is [puntersedge.online/datasets](https://puntersedge.online/datasets); the machine-readable catalogue is [/datasets.json](https://puntersedge.online/datasets.json).

## Load a release

With the [Python package](python/README.md), which checks each file against the SHA-256 the site publishes and keeps a local copy:

```
pip install "puntersedge-datasets @ git+https://github.com/Propertyscout001/puntersedge-datasets#subdirectory=python"
```

```python
import puntersedge_datasets as ped

df = ped.load("2026-09")
```

Or straight from the site with pandas alone:

```python
import pandas as pd

df = pd.read_parquet(
    "https://puntersedge.online/datasets/au-racing-closing-lines/2026-09/"
    "au-racing-closing-lines-2026-09.parquet")
```

[`examples/clv_against_close.py`](examples/clv_against_close.py) scores a list of bets against the closing prices in a release.

## How a release is built

[`tools/build_sample.py`](tools/build_sample.py) reads the month file of the closing-line archive, keeps Australian races at the chosen bookmakers and applies the same default filters as `GET /v1/racing/closing-lines`: the last observation within 300 seconds of the jump, no runner the result marked scratched, and no row the archive flags as a possible venue or name mismatch. A bookmaker is included when at least 75% of its series that month were last observed within 300 seconds of the jump. A release is built once, on the 3rd of the month after next. If one has to be rebuilt, it gets a new version (September 2026 is now `2026-09.2`), and its README and the catalogue say what changed and list the replaced files' checksums. A scheduled workflow copies each new release here the same day, after checking every file against the checksums the site publishes.

## Licences

- Data: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Credit "PuntersEdge Australian racing closing-line sample (puntersedge.online)". The licence covers PuntersEdge's compilation; bookmaker names are trademarks of their owners and the data is not affiliated with or endorsed by any bookmaker or racing body.
- Code in `tools/`, `examples/` and `python/`: MIT, see [LICENSE](LICENSE).

## More data

The full archive, from 4 August 2026, across 14 Australian bookmakers and New Zealand racing, with price paths, registry identifiers and a closing-line-value scorer, is in the [PuntersEdge API](https://puntersedge.online/api). A free key needs no card.

For research and analysis. 18+. Gambling Help Online: 1800 858 858.
