"""Offline tests: a local HTTP server stands in for puntersedge.online and the GitHub release."""
import hashlib
import http.server
import json
import threading
from pathlib import Path

import pandas as pd
import pytest

import puntersedge_datasets as ped
from puntersedge_datasets import __main__ as cli
from puntersedge_datasets import _core

DS = "au-racing-closing-lines"


def _frame(month, n):
    return pd.DataFrame({"race_id": [f"{month}-r{i}" for i in range(n)],
                         "bookmaker_key": ["tab"] * n,
                         "close_win_price": [2.0 + i for i in range(n)],
                         "close_observed_at": pd.to_datetime(["2026-09-01T03:00:00Z"] * n)})


class Site:
    """Files under root, served over HTTP. `fail` paths answer 500, `corrupt` paths answer junk."""

    def __init__(self, root):
        self.root, self.requests, self.fail, self.corrupt = Path(root), [], set(), set()
        site = self

        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *a, **k):
                super().__init__(*a, directory=str(site.root), **k)

            def do_GET(self):
                site.requests.append((self.path, self.headers.get("User-Agent")))
                if self.path in site.fail:
                    self.send_error(500)
                    return
                if self.path in site.corrupt:
                    body = b"not the file"
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                super().do_GET()

            def log_message(self, *a):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def publish(self, month, n, version=None):
        """Write a release's two files (and its GitHub copy) and rebuild the catalogue."""
        d = self.root / "datasets" / DS / month
        g = self.root / "gh" / month
        d.mkdir(parents=True, exist_ok=True)
        g.mkdir(parents=True, exist_ok=True)
        df = _frame(month, n)
        df.to_parquet(d / f"{DS}-{month}.parquet", index=False)
        df.to_csv(d / f"{DS}-{month}.csv.gz", index=False)
        for p in d.iterdir():
            (g / p.name).write_bytes(p.read_bytes())
        cat_path = self.root / "datasets.json"
        cat = json.loads(cat_path.read_text()) if cat_path.exists() else {
            "dataset": DS, "license": "CC-BY-4.0", "page": "https://puntersedge.online/datasets",
            "attribution": "PuntersEdge Australian racing closing-line sample (puntersedge.online)",
            "releases": []}
        cat["releases"] = [r for r in cat["releases"] if r["release"] != month]
        files = []
        for name in (f"{DS}-{month}.parquet", f"{DS}-{month}.csv.gz"):
            b = (d / name).read_bytes()
            files.append({"name": name, "url": f"{self.base}/datasets/{DS}/{month}/{name}",
                          "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()})
        cat["releases"].append({"release": month, "version": version or month, "rows": n, "races": n,
                                "bookmakers": ["tab"], "files": files})
        cat_path.write_text(json.dumps(cat))

    def hits(self, suffix):
        return sum(1 for p, _ in self.requests if p.endswith(suffix))


@pytest.fixture
def site(tmp_path, monkeypatch):
    s = Site(tmp_path / "site")
    s.publish("2026-08", 2)
    s.publish("2026-09", 3, version="2026-09.2")
    monkeypatch.setattr(_core, "CATALOGUE_URL", f"{s.base}/datasets.json")
    monkeypatch.setattr(_core, "FALLBACK_BASE", f"{s.base}/gh")
    monkeypatch.setenv("PUNTERSEDGE_DATASETS_CACHE", str(tmp_path / "cache"))
    monkeypatch.delenv("PUNTERSEDGE_DATASETS_USER_AGENT", raising=False)
    yield s
    s.server.shutdown()


def test_releases_are_newest_first(site):
    assert [r["release"] for r in ped.releases()] == ["2026-09", "2026-08"]


def test_load_reads_the_latest_release_and_labels_it(site):
    df = ped.load()
    assert len(df) == 3 and list(df.columns)[:2] == ["race_id", "bookmaker_key"]
    assert df.attrs["release"] == "2026-09" and df.attrs["version"] == "2026-09.2"
    assert df.attrs["license"] == "CC-BY-4.0" and "PuntersEdge" in df.attrs["attribution"]
    assert pd.api.types.is_datetime64_any_dtype(df["close_observed_at"])
    assert len(ped.load("2026-08", columns=["race_id"]).columns) == 1


def test_a_verified_file_is_downloaded_once(site):
    p1 = ped.download("2026-09")
    p2 = ped.download("2026-09")
    assert p1 == p2 and p1.exists() and site.hits(".parquet") == 1


def test_a_revised_release_is_downloaded_again(site):
    ped.download("2026-09")
    site.publish("2026-09", 5, version="2026-09.3")
    assert len(pd.read_parquet(ped.download("2026-09"))) == 5
    assert site.hits(".parquet") == 2


def test_a_bad_site_copy_falls_back_to_the_github_copy(site):
    site.corrupt.add(f"/datasets/{DS}/2026-09/{DS}-2026-09.parquet")
    path = ped.download("2026-09")
    assert len(pd.read_parquet(path)) == 3
    assert site.hits(f"/gh/2026-09/{DS}-2026-09.parquet") == 1
    assert not [p for p in path.parent.iterdir() if p.name.startswith(".part-")]


def test_no_verified_copy_raises_and_names_both_sources(site):
    site.corrupt.add(f"/datasets/{DS}/2026-09/{DS}-2026-09.csv.gz")
    site.fail.add(f"/gh/2026-09/{DS}-2026-09.csv.gz")
    with pytest.raises(ped.DatasetError) as e:
        ped.download("2026-09", "csv")
    assert "did not match" in str(e.value) and "500" in str(e.value)
    assert not list((ped.cache_dir() / DS / "2026-09").glob("*.csv.gz"))


def test_offline_uses_the_saved_catalogue_and_cache(site, monkeypatch):
    ped.download("2026-09")
    monkeypatch.setattr(_core, "CATALOGUE_URL", "http://127.0.0.1:9/datasets.json")
    assert ped.load(offline=True).attrs["version"] == "2026-09.2"
    with pytest.warns(UserWarning, match="could not refresh the catalogue"):
        assert ped.download("2026-09").exists()
    with pytest.raises(ped.DatasetError, match="not in the cache"):
        ped.download("2026-08", offline=True)


def test_no_catalogue_at_all_is_a_clear_error(site, monkeypatch):
    monkeypatch.setattr(_core, "CATALOGUE_URL", "http://127.0.0.1:9/datasets.json")
    with pytest.raises(ped.DatasetError, match="could not read the catalogue"):
        ped.releases()
    with pytest.raises(ped.DatasetError, match="no saved catalogue"):
        ped.releases(offline=True)


def test_release_and_format_checks(site):
    assert ped.download("2026-09.2").name.endswith(".parquet")
    with pytest.raises(ped.DatasetError, match="is not published"):
        ped.download("2026-09.1")
    with pytest.raises(ped.DatasetError, match="no release '2025-01'"):
        ped.download("2025-01")
    with pytest.raises(ped.DatasetError, match="format must be one of"):
        ped.download("2026-09", "xlsx")


def test_requests_say_who_is_asking(site, monkeypatch):
    ped.releases()
    assert site.requests[-1][1].startswith(f"puntersedge-datasets/{ped.__version__} ")
    monkeypatch.setenv("PUNTERSEDGE_DATASETS_USER_AGENT", "Mozilla/5.0 (pe-live-check)")
    ped.releases()
    assert site.requests[-1][1] == "Mozilla/5.0 (pe-live-check)"


def test_cli_list_and_download(site, tmp_path, capsys):
    assert cli.main(["list"]) == 0
    out = capsys.readouterr().out
    assert out.index("2026-09") < out.index("2026-08") and "Credit: PuntersEdge" in out
    assert cli.main(["download", "2026-08", "--format", "csv", "--to", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out" / f"{DS}-2026-08.csv.gz").exists()
    assert cli.main(["download", "1999-01"]) == 1
    assert "no release" in capsys.readouterr().err
