#!/usr/bin/env python
"""
tools/fixtures/capture.py
-------------------------

Capture RAW + “golden” EXP fixtures for *any* scraper that supports the
`group=capture` exporters.

The scraper must write:

    /tmp/raw_<runId>.html        (or .json/.txt - extension doesn't matter)
    /tmp/exp_<runId>.json        (pretty-printed decoded data)

Both files are optionally gzipped (if > SIZE_CAP) and moved to

    tests/samples/<package>/<scraper>/

Usage
-----
    # single scraper
    python tools/fixtures/capture.py balldontlie.bdl_teams

    # batch (matrix defined in scrapers/balldontlie/__init__.py)
    python tools/fixtures/capture.py --all
"""

from __future__ import annotations

import argparse
import gzip
import importlib
import pathlib
import shutil
import subprocess
import sys
import uuid
from typing import List

# --------------------------------------------------------------------------- #
# Project‑level constants
# --------------------------------------------------------------------------- #
ROOT = pathlib.Path(__file__).resolve().parents[2]          # repo root
sys.path.insert(0, str(ROOT))                               # ensure root on sys.path

SAMPLES = ROOT / "tests" / "samples"
TMP_DIR = pathlib.Path("/tmp")

SIZE_CAP = 200_000                # gzip if fixture > 200 kB (changed from 100 kB)
RAW_FMT = "raw_{run}.html"        # extension can be .html, .json, …
EXP_FMT = "exp_{run}.json"

# --------------------------------------------------------------------------- #
# Helper functions
# --------------------------------------------------------------------------- #
def discover_module(short_name: str, *, debug: bool = False) -> str:
    """
    Resolve *short_name* to a fully-qualified import path under ``scrapers.*``.

    Resolution order:

    1. If caller already passed ``scrapers.….``   → trust it.
    2. If caller passed ``pkg.mod``              → prepend ``scrapers.``.
    3. Prefer package precedence list
       (balldontlie > espn > nbacom) over generic dir iteration.
    """
    # caller gave full dotted path
    if short_name.startswith("scrapers."):
        return short_name

    # caller gave "pkg.mod"
    if "." in short_name:
        return f"scrapers.{short_name}"

    # attempt top‑level
    probe = f"scrapers.{short_name}"
    if _import_ok(probe, debug):
        return probe

    # precedence list beats alphabet soup
    precedence = ["balldontlie", "espn", "nbacom"]
    packages: List[str] = precedence + [
        d.name for d in (ROOT / "scrapers").iterdir()
        if d.is_dir() and d.name not in precedence
    ]

    for pkg in packages:
        probe = f"scrapers.{pkg}.{short_name}"
        if _import_ok(probe, debug):
            return probe

    sys.exit(f"✖ Could not find a module path for '{short_name}'")


def _import_ok(path: str, debug: bool) -> bool:
    try:
        importlib.import_module(path)
        if debug:
            print("  resolved:", path)
        return True
    except ModuleNotFoundError:
        return False


def run_scraper(module_path: str, run_id: str, extra_args: list[str], debug: bool) -> None:
    """Invoke the scraper as ``python -m <module_path> …``."""
    cmd = ["python", "-m", module_path,
           "--group", "capture",
           "--runId", run_id]
    if debug:
        cmd.append("--debug")
    cmd += extra_args
    print("•", " ".join(cmd))
    subprocess.run(cmd, check=True,
                   stdout=sys.stdout, stderr=sys.stderr)


def maybe_gzip(src: pathlib.Path) -> pathlib.Path:
    """Gzip *src* if it's larger than SIZE_CAP and not already compressed."""
    if src.stat().st_size <= SIZE_CAP or src.suffix == ".gz":
        return src

    gz_path = src.with_suffix(src.suffix + ".gz")
    with src.open("rb") as fin, gzip.open(gz_path, "wb", compresslevel=9) as fout:
        shutil.copyfileobj(fin, fout)
    print(f"  gzipped → {gz_path.name} ({gz_path.stat().st_size:,} B)")
    return gz_path


def promote(scraper_name: str, src: pathlib.Path) -> None:
    """Copy *src* into tests/samples/<package>/<scraper>/…  preserving filename."""
    dest_dir = SAMPLES / scraper_name.split(".")[-1]          # **just the leaf name**
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    shutil.copy2(src, dest)
    rel = dest.relative_to(ROOT)
    print(f"  copied  → {rel} ({dest.stat().st_size:,} B)")


# --------------------------------------------------------------------------- #
# Single‑scraper helper (so --all can reuse it)
# --------------------------------------------------------------------------- #
def main_one(scraper_name: str,
             extra_args: list[str] | None = None,
             *,
             debug: bool = False) -> None:
    """Run one scraper, harvest RAW+EXP, and move them into tests/samples."""
    extra_args = extra_args or []
    run_id = uuid.uuid4().hex[:8]

    module_path = discover_module(scraper_name, debug=debug)

    # 1) Run scraper (writes raw/exp with run‑id)
    run_scraper(module_path, run_id, extra_args, debug)

    # 2) Collect and promote
    # accept raw_<runId>.html **or** .json
    candidate_glob = f"raw_{run_id}.*"
    matches = list(TMP_DIR.glob(candidate_glob))
    if not matches:
        sys.exit(f"✖ RAW file not found: /tmp/{candidate_glob}")
    raw_file = matches[0]          # there should only be one

    promote(scraper_name, maybe_gzip(raw_file))

    exp_file = TMP_DIR / EXP_FMT.format(run=run_id)
    if exp_file.exists():
        promote(scraper_name, maybe_gzip(exp_file))
    else:
        print(f"  (no {exp_file.name} found – raw only)")


# --------------------------------------------------------------------------- #
# CLI entry
# --------------------------------------------------------------------------- #
def main() -> None:
    p = argparse.ArgumentParser(
        description="Capture raw+golden fixtures for one or many scrapers"
    )
    p.add_argument("scraper", nargs="?",
                   help="bdl_games, balldontlie.bdl_teams … (omit with --all)")
    p.add_argument("--all", action="store_true",
                   help="run every scraper in scrapers.balldontlie.__init__.BDL_SCRAPER_MATRIX")
    p.add_argument("--debug", action="store_true")
    ns, scraper_args = p.parse_known_args()

    if ns.all:
        try:
            from scrapers.balldontlie import BDL_SCRAPER_MATRIX
        except ImportError as err:
            raise SystemExit(
                "✖ Could not import BDL_SCRAPER_MATRIX – did you add it to "
                "scrapers/balldontlie/__init__.py ?"
            ) from err

        for name, default_opts in BDL_SCRAPER_MATRIX.items():
            print(f"\n=== {name} ===")
            main_one(name, extra_args=default_opts, debug=ns.debug)
    else:
        if not ns.scraper:
            p.error("scraper positional argument required unless --all is used")
        main_one(ns.scraper, extra_args=scraper_args, debug=ns.debug)


if __name__ == "__main__":
    main()
