"""Download and load the PuntersEdge monthly Australian racing closing-line datasets.

    import puntersedge_datasets as ped

    df = ped.load()                  # the latest release as a pandas DataFrame
    df = ped.load("2026-09")         # a given month
    ped.releases()                   # what is published, newest first
    path = ped.download("2026-09", "csv")   # the file itself, for any other tool

Every file is checked against the size and SHA-256 that puntersedge.online/datasets.json
publishes before it is used, and kept in a local cache while it still matches.
"""
from ._core import (CATALOGUE_URL, DatasetError, cache_dir, catalogue, download, load,
                    releases)
from ._version import __version__

__all__ = ["CATALOGUE_URL", "DatasetError", "__version__", "cache_dir", "catalogue", "download",
           "load", "releases"]
