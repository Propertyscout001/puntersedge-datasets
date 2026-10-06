"""puntersedge-datasets list | download [RELEASE] [--format parquet|csv] [--to DIR]"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from . import _core


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="puntersedge-datasets",
                                 description="List or download PuntersEdge public racing datasets.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="the published releases, newest first")
    dl = sub.add_parser("download", help="download a release file, checked against its SHA-256")
    dl.add_argument("release", nargs="?", default="latest", help="YYYY-MM, or latest (default)")
    dl.add_argument("--format", choices=sorted(_core.FORMATS), default="parquet")
    dl.add_argument("--to", default=".", help="directory to copy the file into (default: here)")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "list":
            cat = _core.catalogue()
            for r in sorted(cat["releases"], key=lambda r: r["release"], reverse=True):
                print(f"{r['release']}  version {r.get('version') or r['release']}  "
                      f"{r.get('races', 0):,} races  {r.get('rows', 0):,} rows  "
                      f"{', '.join(r.get('bookmakers') or [])}")
            print(f"Licence {cat.get('license')}. Credit: {cat.get('attribution')}")
            return 0
        cat, rel, f, path = _core._resolve(a.release, a.format, None, False, _core.TIMEOUT)
        to = Path(a.to).expanduser()
        to.mkdir(parents=True, exist_ok=True)
        out = shutil.copy2(path, to / f["name"])
        print(f"{out}  ({rel.get('version') or rel['release']}, sha256 {f['sha256']})")
        print(f"Licence {cat.get('license')}. Credit: {cat.get('attribution')}")
        return 0
    except _core.DatasetError as exc:
        print(f"puntersedge-datasets: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
