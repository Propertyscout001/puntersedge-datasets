"""The catalogue, the download and the checks. Standard library only; load() needs pandas and
pyarrow, which the package installs."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.request
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ._version import __version__

CATALOGUE_URL = "https://puntersedge.online/datasets.json"
# Each release's files are also attached to the GitHub release of the same name, copied there
# only after they matched the site's checksums. Used when the site's copy can't be fetched.
FALLBACK_BASE = "https://github.com/Propertyscout001/puntersedge-datasets/releases/download"
DEFAULT_DATASET = "au-racing-closing-lines"
FORMATS = {"parquet": ".parquet", "csv": ".csv.gz"}
TIMEOUT = 60


class DatasetError(Exception):
    """A release, file or checksum problem: the message says which, and what was tried."""


def cache_dir(path: Optional[os.PathLike] = None) -> Path:
    """Where files are kept: `path`, else $PUNTERSEDGE_DATASETS_CACHE, else
    $XDG_CACHE_HOME/puntersedge-datasets, else ~/.cache/puntersedge-datasets."""
    if path:
        return Path(path).expanduser()
    if os.environ.get("PUNTERSEDGE_DATASETS_CACHE"):
        return Path(os.environ["PUNTERSEDGE_DATASETS_CACHE"]).expanduser()
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "puntersedge-datasets"


def _user_agent() -> str:
    return os.environ.get("PUNTERSEDGE_DATASETS_USER_AGENT") or (
        f"puntersedge-datasets/{__version__} (+https://github.com/Propertyscout001/puntersedge-datasets)")


def _open(url: str, timeout: float):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": _user_agent()}),
                                  timeout=timeout)


def _check_catalogue(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict) or not isinstance(data.get("releases"), list):
        raise DatasetError("the catalogue has no list of releases")
    for r in data["releases"]:
        if not r.get("release") or not r.get("files"):
            raise DatasetError("a catalogue entry has no release name or no files")
        for f in r["files"]:
            if not all(f.get(k) for k in ("name", "url", "bytes", "sha256")):
                raise DatasetError(f"a file in release {r['release']} lacks its name, url, size or SHA-256")
    return data


def _saved(cache: Optional[os.PathLike]) -> Path:
    return cache_dir(cache) / "datasets.json"


def catalogue(*, cache: Optional[os.PathLike] = None, offline: bool = False,
              timeout: float = 30) -> Dict[str, Any]:
    """The site's catalogue of releases (/datasets.json). The last good copy is saved in the cache;
    when the site can't be reached that copy is used, with a warning. offline=True never asks
    the site."""
    saved = _saved(cache)
    if not offline:
        try:
            with _open(CATALOGUE_URL, timeout) as resp:
                data = _check_catalogue(json.loads(resp.read().decode("utf-8")))
            saved.parent.mkdir(parents=True, exist_ok=True)
            tmp = saved.with_name(saved.name + ".tmp")
            tmp.write_text(json.dumps(data))
            os.replace(tmp, saved)
            return data
        except (OSError, ValueError, DatasetError) as exc:     # URLError is an OSError
            if not saved.exists():
                raise DatasetError(f"could not read the catalogue at {CATALOGUE_URL}: {exc}") from exc
            warnings.warn(f"could not refresh the catalogue from {CATALOGUE_URL} ({exc}); "
                          f"using the copy saved in {saved.parent}", stacklevel=2)
    elif not saved.exists():
        raise DatasetError(f"no saved catalogue in {saved.parent}; run once with a network")
    return _check_catalogue(json.loads(saved.read_text()))


def releases(*, cache: Optional[os.PathLike] = None, offline: bool = False,
             timeout: float = 30) -> List[Dict[str, Any]]:
    """Every published release, newest first. Each has release ("2026-09"), version ("2026-09.2"
    after a revision), rows, races, period, bookmakers and files (name, url, bytes, sha256)."""
    cat = catalogue(cache=cache, offline=offline, timeout=timeout)
    return sorted(cat["releases"], key=lambda r: r["release"], reverse=True)


def _pick(cat: Dict[str, Any], release: Optional[str]) -> Dict[str, Any]:
    rels = sorted(cat["releases"], key=lambda r: r["release"])
    if not rels:
        raise DatasetError("the catalogue lists no releases")
    if release in (None, "latest"):
        return rels[-1]
    month, _, rev = str(release).partition(".")
    for r in rels:
        if r["release"] == month:
            if rev and str(r.get("version") or month) != str(release):
                raise DatasetError(f"{release} is not published: {month} is now version {r.get('version')}, "
                                   "and a revision replaces the files rather than adding to them")
            return r
    raise DatasetError(f"no release {release!r}; published: {', '.join(r['release'] for r in rels)}")


def _file(rel: Dict[str, Any], fmt: str) -> Dict[str, Any]:
    suffix = FORMATS.get(fmt)
    if suffix is None:
        raise DatasetError(f"format must be one of: {', '.join(FORMATS)}")
    for f in rel["files"]:
        if f["name"].endswith(suffix):
            return f
    raise DatasetError(f"release {rel['release']} has no {fmt} file")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _matches(path: Path, f: Dict[str, Any]) -> bool:
    return path.exists() and path.stat().st_size == int(f["bytes"]) and _sha256(path) == f["sha256"]


def _fetch(url: str, dest: Path, f: Dict[str, Any], timeout: float) -> bool:
    """Download into a temporary file beside dest; keep it only if size and SHA-256 match."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(dest.parent), prefix=".part-")
    try:
        with os.fdopen(fd, "wb") as out, _open(url, timeout) as resp:
            for chunk in iter(lambda: resp.read(1 << 16), b""):
                out.write(chunk)
        if not _matches(Path(tmp), f):
            return False
        os.replace(tmp, dest)
        return True
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _resolve(release: Optional[str], fmt: str, cache: Optional[os.PathLike], offline: bool,
             timeout: float) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Path]:
    cat = catalogue(cache=cache, offline=offline, timeout=min(timeout, 30))
    rel = _pick(cat, release)
    f = _file(rel, fmt)
    dest = cache_dir(cache) / str(cat.get("dataset") or DEFAULT_DATASET) / rel["release"] / f["name"]
    if _matches(dest, f):
        return cat, rel, f, dest
    if offline:
        raise DatasetError(f"{f['name']} (version {rel.get('version')}) is not in the cache at "
                           f"{dest.parent}; run once with a network")
    tried = []
    for url in (f["url"], f"{FALLBACK_BASE}/{rel['release']}/{f['name']}"):
        try:
            if _fetch(url, dest, f, timeout):
                return cat, rel, f, dest
            tried.append(f"{url}: the size or SHA-256 did not match the catalogue")
        except OSError as exc:
            tried.append(f"{url}: {exc}")
    raise DatasetError(f"no verified copy of {f['name']} could be downloaded:\n  " + "\n  ".join(tried))


def download(release: Optional[str] = "latest", fmt: str = "parquet", *,
             cache: Optional[os.PathLike] = None, offline: bool = False,
             timeout: float = TIMEOUT) -> Path:
    """One release file in the local cache, checked against the size and SHA-256 the catalogue
    publishes; returns its path. A cached copy is reused while it still matches, so a revised
    release is fetched again. If the site's copy can't be fetched or doesn't match, the copy
    attached to the GitHub release is tried. fmt is "parquet" or "csv" (gzipped CSV)."""
    return _resolve(release, fmt, cache, offline, timeout)[3]


def load(release: Optional[str] = "latest", *, columns: Optional[Sequence[str]] = None,
         cache: Optional[os.PathLike] = None, offline: bool = False, timeout: float = TIMEOUT):
    """The release as a pandas DataFrame, read from its checked Parquet file. df.attrs carries the
    release, version, file checksum, licence and the credit line the licence asks for."""
    import pandas as pd

    cat, rel, f, path = _resolve(release, "parquet", cache, offline, timeout)
    df = pd.read_parquet(path, columns=list(columns) if columns is not None else None)
    df.attrs.update({"dataset": cat.get("dataset") or DEFAULT_DATASET, "release": rel["release"],
                     "version": rel.get("version") or rel["release"], "sha256": f["sha256"],
                     "source": f["url"], "license": cat.get("license"),
                     "attribution": cat.get("attribution"), "page": cat.get("page")})
    return df
