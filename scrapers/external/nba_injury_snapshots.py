# File: scrapers/external/nba_injury_snapshots.py
"""
NBA Injury Snapshot Scraper                                     v1.0 - 2026-06-29
----------------------------------------------------------------------------------
Daily injury snapshot using the `nbainjuries` Python package.

Fetches the official NBA injury report PDF (published by NBA.com) and stores a
flattened, per-player snapshot in BigQuery for narrative/context analysis.

Source: https://ak-static.cms.nba.com/referee/injury/Injury-Report_*.pdf
Data: Per-player injury status at a specific report time.
Access: Free, publicly accessible PDF.
Timing: NBA publishes reports throughout the day (15-min intervals starting 2025-26).
        For daily snapshots, use the ~5 PM ET report (pre-game final status).

Columns returned by nbainjuries.injury.get_reportdata():
  Game Date, Game Time, Matchup, Team, Player Name, Current Status, Reason

This scraper is NOT a Phase 5/best-bets signal source — it is a narrative
forward-collection scraper. Data accumulates in BigQuery for backtesting
whether pre-game injury context predicts player prop outcomes.

Off-season behavior: nbainjuries raises an exception when no report is available
(403 Forbidden). The scraper catches this and writes an empty result.

Usage:
  python scrapers/external/nba_injury_snapshots.py --date 2026-03-15 --debug
  python scrapers/external/nba_injury_snapshots.py --date 2026-03-15 --hour 17 --local
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional

try:
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

from shared.utils.notification_system import notify_warning, notify_info

logger = logging.getLogger("scraper_base")

# Default report hour (ET) — 5 PM ET is typically the pre-game final report
DEFAULT_REPORT_HOUR_ET = 17
DEFAULT_REPORT_MINUTE_ET = 0

GCS_PATH_KEY = "nba_injury_snapshots"


class NBAInjurySnapshotsScraper(ScraperBase, ScraperFlaskMixin):
    """
    Daily NBA injury snapshot scraper using the `nbainjuries` package.

    Calls nbainjuries.injury.get_reportdata() with a constructed ET timestamp
    to fetch the official NBA injury report PDF and extract per-player rows.

    Overrides download_and_decode() entirely — nbainjuries handles the HTTP
    download and PDF parsing internally, so the base class HTTP machinery is
    bypassed. decode_download_data=False prevents double-processing.
    """

    scraper_name = "nba_injury_snapshots"
    required_params = ["date"]
    optional_params = {"hour": None, "minute": None}

    required_opts: List[str] = ["date"]
    # Disable base-class HTTP download — nbainjuries owns the network call
    decode_download_data: bool = False
    download_type = DownloadType.JSON  # not used, but required by base class
    proxy_enabled: bool = False

    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/nba_injury_snapshots_%(date)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
    ]

    # -------------------------------------------------------------------------
    # Lifecycle overrides
    # -------------------------------------------------------------------------

    def set_url(self) -> None:
        """No URL to set — nbainjuries constructs the URL internally."""
        self.url = None

    def download_and_decode(self) -> None:
        """
        Bypass the base-class HTTP machinery and call nbainjuries directly.

        nbainjuries.injury.get_reportdata() downloads the NBA injury report PDF
        from ak-static.cms.nba.com and parses it via tabula/Java. We construct
        a datetime from the scraper's opts and call it here.

        On 403/unavailable (off-season or bad timestamp), logs a warning and
        sets self.data to an empty result so the scraper exits cleanly.
        """
        try:
            from nbainjuries import injury as nbainjuries_injury
        except ImportError:
            raise RuntimeError(
                "nbainjuries package is not installed. Run: pip install nbainjuries"
            )

        report_ts = self._build_report_timestamp()
        logger.info(
            "Fetching NBA injury report for %s (report timestamp: %s)",
            self.opts["date"],
            report_ts.isoformat(),
        )

        try:
            df = nbainjuries_injury.get_reportdata(report_ts, return_df=True)
        except Exception as e:
            # 403 Forbidden during off-season or for timestamps with no report
            logger.warning(
                "nbainjuries could not fetch report for %s at %s: %s",
                self.opts["date"],
                report_ts.isoformat(),
                e,
            )
            self.data = self._empty_result(self.opts["date"], str(e))
            self.decoded_data = self.data
            return

        players = self._transform_dataframe(df, self.opts["date"])
        self.data = {
            "source": "nbainjuries",
            "date": self.opts["date"],
            "report_timestamp": report_ts.isoformat(),
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "player_count": len(players),
            "players": players,
        }
        self.decoded_data = self.data

        logger.info(
            "NBA injury snapshot: %d players for %s",
            len(players),
            self.opts["date"],
        )

        if players:
            try:
                notify_info(
                    title="NBA Injury Snapshot Scraped",
                    message=f"Scraped {len(players)} injury entries for {self.opts['date']}",
                    details={"player_count": len(players), "date": self.opts["date"]},
                    processor_name=self.__class__.__name__,
                )
            except Exception:
                pass
        else:
            try:
                notify_warning(
                    title="NBA Injury Snapshot: No Players",
                    message=f"0 injury entries for {self.opts['date']} — off-season or no injuries filed",
                    details={"date": self.opts["date"]},
                    processor_name=self.__class__.__name__,
                )
            except Exception:
                pass

    def validate_download_data(self) -> None:
        """No-op — data is already populated in download_and_decode()."""
        pass

    def transform_data(self) -> None:
        """No-op — data is already populated in download_and_decode()."""
        pass

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _build_report_timestamp(self) -> datetime:
        """
        Build the datetime that nbainjuries uses to look up the report PDF.

        Priority:
          1. opts['hour'] + opts['minute'] if provided (24-hour ET)
          2. DEFAULT_REPORT_HOUR_ET / DEFAULT_REPORT_MINUTE_ET (5:00 PM ET)

        nbainjuries constructs the PDF URL from this timestamp, so it must
        match an actual report publication time. The library uses 15-minute
        buckets for 2025-26+. The default of 17:00 ET should match the
        Injury-Report_YYYY-MM-DD_05_00PM.pdf published before most games.
        """
        import pytz

        date_str = self.opts["date"]
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            raise ValueError(f"Invalid date format: {date_str!r} — expected YYYY-MM-DD")

        hour_et = int(self.opts["hour"]) if self.opts.get("hour") is not None else DEFAULT_REPORT_HOUR_ET
        minute_et = int(self.opts["minute"]) if self.opts.get("minute") is not None else DEFAULT_REPORT_MINUTE_ET

        eastern = pytz.timezone("US/Eastern")
        # Build as naive datetime (nbainjuries _util.py works with naive datetimes)
        ts_naive = datetime(date_obj.year, date_obj.month, date_obj.day, hour_et, minute_et, 0)
        return ts_naive

    def _transform_dataframe(self, df, game_date: str) -> List[Dict]:
        """
        Convert the nbainjuries DataFrame into a list of plain dicts.

        nbainjuries columns: Game Date, Game Time, Matchup, Team, Player Name,
        Current Status, Reason.

        We flatten these into snake_case fields and add game_date + scraped_at.
        """
        scraped_at = datetime.now(timezone.utc).isoformat()
        players = []

        for _, row in df.iterrows():
            player_name = str(row.get("Player Name", "") or "").strip()
            if not player_name:
                continue

            current_status = str(row.get("Current Status", "") or "").strip()
            # Skip rows that are unsubmitted placeholders (nbainjuries keeps them with status flags)
            if not current_status or current_status.lower() in ("not yet submitted", "nan"):
                continue

            players.append(
                {
                    "game_date": game_date,
                    "player_name": player_name,
                    "team": str(row.get("Team", "") or "").strip() or None,
                    "matchup": str(row.get("Matchup", "") or "").strip() or None,
                    "game_time": str(row.get("Game Time", "") or "").strip() or None,
                    "status": current_status,
                    "reason": str(row.get("Reason", "") or "").strip() or None,
                    "scraped_at": scraped_at,
                }
            )

        return players

    def _empty_result(self, game_date: str, error_msg: str = "") -> Dict:
        return {
            "source": "nbainjuries",
            "date": game_date,
            "report_timestamp": None,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "player_count": 0,
            "players": [],
            "error": error_msg or None,
        }

    def get_scraper_stats(self) -> Dict:
        return {
            "date": self.opts.get("date"),
            "player_count": self.data.get("player_count", 0) if isinstance(self.data, dict) else 0,
        }


# Flask integration
app = convert_existing_flask_scraper(NBAInjurySnapshotsScraper)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="NBA Injury Snapshot Scraper")
    parser.add_argument("--date", required=True, help="Game date (YYYY-MM-DD)")
    parser.add_argument(
        "--hour",
        type=int,
        default=None,
        help="Report hour in ET 24h (default: 17 = 5 PM ET)",
    )
    parser.add_argument(
        "--minute",
        type=int,
        default=None,
        help="Report minute (default: 0)",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--local", action="store_true", help="Run locally with file export only"
    )
    parser.add_argument("--serve", action="store_true", help="Start Flask server")

    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    if args.serve:
        app.run(host="0.0.0.0", port=8080, debug=True)
    else:
        scraper = NBAInjurySnapshotsScraper()
        # "dev" group writes to /tmp; "prod" group writes to GCS
        group = "dev" if args.local else "prod"
        opts: Dict = {"date": args.date, "group": group}
        if args.hour is not None:
            opts["hour"] = args.hour
        if args.minute is not None:
            opts["minute"] = args.minute
        scraper.run(opts=opts)
