"""
scrapers/utils/cli_utils.py
---------------------------

One place to register the “standard four” CLI options every scraper
understands.  Import it from each scraper's `if __name__ == "__main__":`
block instead of repeating the same `argparse` lines 16 times.
"""

from __future__ import annotations
import argparse

__all__ = ["add_common_args"]


def add_common_args(parser: argparse.ArgumentParser, *, want_api_key: bool = False) -> None:
    """
    Injects the shared flags **in a single call**.

        --group   dev | test | prod | capture
        --apiKey  override $BDL_API_KEY (optional)
        --runId   externally-fixed run-id (optional, used by fixture capture)
        --debug   ask the scraper to be extra chatty (optional)
    """
    parser.add_argument("--group", default="test",
                        help="exporter group: dev, test, prod, capture (default: test)")
    parser.add_argument("--debug", action="store_true",
                        help="enable verbose logging in the scraper")
    parser.add_argument("--runId",
                        help="external run-id (fixture capture sets this)")
    if want_api_key:
        parser.add_argument("--apiKey",
                            help="override $BDL_API_KEY or other endpoint key")
        

