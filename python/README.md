# puntersedge-datasets

Load the [PuntersEdge](https://puntersedge.online/datasets) monthly samples of the Australian racing closing-line archive into pandas. Each release holds the opening and closing fixed win prices for Australian thoroughbred, harness and greyhound races at a set of bookmakers, one row per race, runner and bookmaker, with the finishing position where one was published.

```
pip install "puntersedge-datasets @ git+https://github.com/Propertyscout001/puntersedge-datasets#subdirectory=python"
```

```python
import puntersedge_datasets as ped

df = ped.load()            # the latest release
df = ped.load("2026-09")   # a given month
print(df.attrs["version"], df.attrs["attribution"])
```

## What it does

- Reads the catalogue at [puntersedge.online/datasets.json](https://puntersedge.online/datasets.json), which lists every release with its files, sizes and SHA-256 checksums.
- Downloads the file, checks its size and SHA-256 against the catalogue, and keeps it in a local cache (`~/.cache/puntersedge-datasets`, or the folder in `PUNTERSEDGE_DATASETS_CACHE`). A cached file is reused while it still matches, so a revised release is downloaded again.
- If the site's copy can't be fetched or doesn't match, it tries the copy attached to the [GitHub release](https://github.com/Propertyscout001/puntersedge-datasets/releases) of the same name, checked the same way.
- `offline=True` uses only the saved catalogue and the cache.

## Other calls

```python
ped.releases()                         # every release, newest first: rows, races, version, files
path = ped.download("2026-09", "csv")  # the gzipped CSV in the cache, for any other tool
```

From a shell:

```
puntersedge-datasets list
puntersedge-datasets download 2026-09 --format csv --to data/
```

## Columns

The column reference and the caveats for each release are on [puntersedge.online/datasets](https://puntersedge.online/datasets?utm_source=datasets_package&utm_medium=pypi) and in each release's README in the [repository](https://github.com/Propertyscout001/puntersedge-datasets).

## Licences

- Data: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Credit "PuntersEdge Australian racing closing-line sample (puntersedge.online)"; `df.attrs["attribution"]` carries the line the catalogue publishes. The licence covers PuntersEdge's compilation; bookmaker names are trademarks of their owners and the data is not affiliated with or endorsed by any bookmaker or racing body.
- This package: MIT, see [LICENSE](LICENSE).

For research and analysis. 18+. Gambling Help Online: 1800 858 858.
