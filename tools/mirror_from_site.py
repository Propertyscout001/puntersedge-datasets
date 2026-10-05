#!/usr/bin/env python3
"""Mirror new dataset releases from puntersedge.online into this repository.

The website is the source of truth: a server job builds each monthly release on the 3rd and
publishes it at https://puntersedge.online/datasets, listing every release, file URL and
SHA-256 in https://puntersedge.online/datasets.json. This script, run by
.github/workflows/mirror-releases.yml, makes the repository follow it:

  1. reads the catalogue;
  2. for every release with no GitHub release yet, downloads the data files and checks each
     against the catalogue's size and SHA-256, downloads README.md, LICENSE.txt, SHA256SUMS,
     datapackage.json and summary.json, and checks SHA256SUMS agrees with the catalogue;
  3. writes those documents to releases/<YYYY-MM>/ and regenerates the release table in
     README.md (between the releases:start/end markers);
  4. with --apply: commits and pushes, then creates the GitHub release with the two data
     files and SHA256SUMS attached and notes generated from summary.json.

Any mismatch stops the run before anything is committed. A release that already has a GitHub
release is never touched again, so a published file never changes under its checksum.

    python3 tools/mirror_from_site.py                # report only
    python3 tools/mirror_from_site.py --apply        # commit, push and release (CI)
    python3 tools/mirror_from_site.py --apply --stamp  # also record the check date
    python3 tools/mirror_from_site.py --no-github    # offline test: assume no GitHub releases, never push
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

SITE = "https://puntersedge.online"
CATALOGUE = SITE + "/datasets.json"
DOCS = ["README.md", "LICENSE.txt", "SHA256SUMS", "datapackage.json", "summary.json"]
START, END = "<!-- releases:start -->", "<!-- releases:end -->"
BOOK_NAMES = {
    "tab": "TAB", "ladbrokes_au": "Ladbrokes", "neds": "Neds", "pointsbetau": "PointsBet",
    "betright": "BetRight", "tabtouch": "TABtouch", "sportsbet": "Sportsbet", "palmerbet": "Palmerbet",
    "unibet": "Unibet", "betr_au": "Betr", "playup": "NextBet", "betgold": "BetGold",
    "boostbet": "BoostBet", "betdeluxe": "BetDeluxe",
}
UA = "puntersedge-datasets-mirror/1.0 (+https://github.com/Propertyscout001/puntersedge-datasets)"


def fetch(url: str, attempts: int = 3) -> bytes:
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(5 * (i + 1))
    raise SystemExit(f"FAIL fetching {url}: {last}")


def month_label(release: str) -> str:
    return dt.date.fromisoformat(release + "-01").strftime("%B %Y")


def books(keys: list[str]) -> str:
    return ", ".join(BOOK_NAMES.get(k, k) for k in keys)


def run(cmd: list[str], cwd: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=check, text=True, capture_output=True)


def github_release_exists(tag: str, cwd: str) -> bool:
    return run(["gh", "release", "view", tag], cwd, check=False).returncode == 0


def readme_table(cat: dict) -> str:
    rows = ["| Release | Races | Rows | Bookmakers | Files |", "|---|---|---|---|---|"]
    for r in cat["releases"]:
        links = []
        for f in r["files"]:
            kind = "Parquet" if f["name"].endswith(".parquet") else "CSV" if f["name"].endswith(".csv.gz") else f["name"]
            links.append(f"[{kind}]({f['url']})")
        rows.append(f"| [{month_label(r['release'])}](releases/{r['release']}/README.md) | {r['races']:,} | {r['rows']:,} | "
                    f"{books(r['bookmakers'])} | {' · '.join(links)} |")
    return "\n".join(rows)


def release_notes(summary: dict, sums: dict, release: str) -> str:
    files = summary["files"]
    table = "\n".join(f"| `{n}` | {m['bytes'] / 1e6:.1f} MB | `{sums[n]}` |" for n, m in files.items())
    label = month_label(release)
    return (
        f"Opening and closing fixed win prices for **{summary['races']:,} Australian thoroughbred, harness and greyhound "
        f"races** run in {label}, at {books(summary['bookmakers'])}, with the finishing position where one was published. "
        f"One row per race, runner and bookmaker: **{summary['rows']:,} rows**. Every closing price was observed within "
        f"300 seconds of the advertised start. {round(summary['races_with_result_share'] * 100)}% of races carry a result.\n\n"
        f"| File | Size | SHA-256 |\n|---|---|---|\n{table}\n\n"
        f"Column reference, caveats and the two measured figures: [releases/{release}/README.md]"
        f"(https://github.com/Propertyscout001/puntersedge-datasets/blob/main/releases/{release}/README.md). "
        f"Also served at [puntersedge.online/datasets]({SITE}/datasets).\n\n"
        f"Licence: CC BY 4.0. Credit \"PuntersEdge Australian racing closing-line sample (puntersedge.online), {label}\". "
        f"For research and analysis. 18+. Gambling Help Online: 1800 858 858.\n"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-dir", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--apply", action="store_true", help="commit, push and create GitHub releases")
    ap.add_argument("--stamp", action="store_true", help="record today's check date in README.md")
    ap.add_argument("--no-github", action="store_true", help="offline test: treat every release as unmirrored, never push")
    a = ap.parse_args()
    if a.apply and a.no_github:
        raise SystemExit("--apply and --no-github are exclusive")
    repo = os.path.abspath(a.repo_dir)
    cat = json.loads(fetch(CATALOGUE))
    if cat.get("dataset") != "au-racing-closing-lines" or not cat.get("releases"):
        raise SystemExit("FAIL: unexpected catalogue shape")
    print(f"catalogue: {len(cat['releases'])} release(s): {', '.join(r['release'] for r in cat['releases'])}")

    added, staged = [], {}
    for r in sorted(cat["releases"], key=lambda x: x["release"]):
        rel = r["release"]
        if not re.fullmatch(r"\d{4}-\d{2}", rel):
            raise SystemExit(f"FAIL: bad release id {rel!r}")
        if not a.no_github and github_release_exists(rel, repo):
            print(f"{rel}: GitHub release exists, nothing to do")
            continue
        tmp = tempfile.mkdtemp(prefix=f"mirror-{rel}-")
        base = r["datapackage"].rsplit("/", 1)[0] + "/"
        for f in r["files"]:
            body = fetch(f["url"])
            digest = hashlib.sha256(body).hexdigest()
            if digest != f["sha256"] or len(body) != f["bytes"]:
                raise SystemExit(f"FAIL {rel}/{f['name']}: sha256 {digest} size {len(body)}, catalogue says {f['sha256']} {f['bytes']}")
            open(os.path.join(tmp, f["name"]), "wb").write(body)
        for name in DOCS:
            open(os.path.join(tmp, name), "wb").write(fetch(base + name))
        sums = dict(reversed(line.split()) for line in open(os.path.join(tmp, "SHA256SUMS")) if line.strip())
        for f in r["files"]:
            if sums.get(f["name"]) != f["sha256"]:
                raise SystemExit(f"FAIL {rel}: SHA256SUMS disagrees with the catalogue on {f['name']}")
        summary = json.load(open(os.path.join(tmp, "summary.json")))
        dest = os.path.join(repo, "releases", rel)
        os.makedirs(dest, exist_ok=True)
        for name in DOCS:
            shutil.copyfile(os.path.join(tmp, name), os.path.join(dest, name))
        staged[rel] = (tmp, summary, sums, [f["name"] for f in r["files"]])
        added.append(rel)
        print(f"{rel}: downloaded and verified {len(r['files'])} data files and {len(DOCS)} documents")

    readme_path = os.path.join(repo, "README.md")
    readme = open(readme_path).read()
    if START not in readme or END not in readme:
        raise SystemExit("FAIL: README.md lacks the releases markers")
    head, rest = readme.split(START, 1)
    _, tail = rest.split(END, 1)
    checked = re.search(r"Last checked against the site on (\d{4}-\d{2}-\d{2})", rest)
    day = dt.date.today().isoformat() if (a.stamp or added) else (checked.group(1) if checked else dt.date.today().isoformat())
    block = f"{START}\n{readme_table(cat)}\n\nLast checked against the site on {day}.\n{END}"
    new_readme = head + block + tail
    if new_readme != readme:
        open(readme_path, "w").write(new_readme)
        print("README.md release table updated")

    if not a.apply:
        print("report only: nothing committed" if not a.no_github else "offline test: nothing pushed")
        return 0

    run(["git", "add", "README.md", "releases"], repo)
    if run(["git", "diff", "--cached", "--quiet"], repo, check=False).returncode != 0:
        msg = f"Mirror {', '.join(month_label(x) for x in added)} release from puntersedge.online" if added \
            else f"Mirror check against puntersedge.online: no new release ({day})"
        run(["git", "commit", "-m", msg], repo)
        run(["git", "push"], repo)
        print(f"committed and pushed: {msg}")
    for rel in added:
        tmp, summary, sums, names = staged[rel]
        notes = os.path.join(tmp, "NOTES.md")
        open(notes, "w").write(release_notes(summary, sums, rel))
        assets = [os.path.join(tmp, n) for n in names] + [os.path.join(tmp, "SHA256SUMS")]
        run(["gh", "release", "create", rel, *assets, "--title", month_label(rel), "--notes-file", notes, "--latest"], repo)
        print(f"{rel}: GitHub release created")
    return 0


if __name__ == "__main__":
    sys.exit(main())
