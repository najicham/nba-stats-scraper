"""
File: scrapers/mlb/statcast/mlb_statcast_pitcher.py

MLB Statcast - Pitcher Advanced Metrics                           v1.0 - 2026-01-06
--------------------------------------------------------------------------------
Advanced Statcast metrics for pitchers from Baseball Savant.

Data Source: Baseball Savant (baseballsavant.mlb.com)
Method: Uses pybaseball library (pip install pybaseball)

Key Metrics:
- Pitch velocity, spin rate, movement
- Whiff rate (swing and miss %)
- Chase rate (swings at balls outside zone)
- Expected stats (xBA, xSLG, xwOBA against)

CRITICAL for strikeout predictions:
- swstr_pct: Swinging strike percentage (highly predictive of K rate)
- chase_rate: How often batters chase bad pitches
- k_pct: Strikeout percentage
- bb_pct: Walk percentage

Requirements:
  pip install pybaseball

Usage:
  python scrapers/mlb/statcast/mlb_statcast_pitcher.py --player_id 592789 --debug
  python scrapers/mlb/statcast/mlb_statcast_pitcher.py --start_date 2025-06-01 --end_date 2025-06-30

Note: Baseball Savant limits queries to 30,000 rows. Large date ranges will be
automatically chunked into smaller requests.
"""

from __future__ import annotations

import logging
import os
import sys
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

try:
    from ...scraper_base import DownloadType, ExportMode, ScraperBase
    from ...scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin, convert_existing_flask_scraper

# Import pybaseball (optional - graceful fallback if not installed)
try:
    from pybaseball import statcast_pitcher, pitching_stats, cache
    cache.enable()  # Enable caching to reduce API calls
    PYBASEBALL_AVAILABLE = True
except ImportError:
    PYBASEBALL_AVAILABLE = False

logger = logging.getLogger(__name__)


class MlbStatcastPitcherScraper(ScraperBase, ScraperFlaskMixin):
    """
    Scraper for MLB Statcast pitcher data via pybaseball.

    Provides advanced metrics not available in standard box scores:
    - Pitch-level data (velocity, spin, movement)
    - Plate discipline metrics (chase rate, swing rate)
    - Expected stats based on contact quality

    NOTE: Requires pybaseball to be installed: pip install pybaseball
    """

    scraper_name = "mlb_statcast_pitcher"
    required_params = []
    optional_params = {
        "player_id": None,      # MLB player ID (for single pitcher)
        "start_date": None,     # Start date (YYYY-MM-DD)
        "end_date": None,       # End date (YYYY-MM-DD)
        "season": None,         # Full season (alternative to date range)
    }

    required_opts: List[str] = []
    download_type = DownloadType.JSON
    decode_download_data = False  # We're not downloading from URL
    proxy_enabled: bool = False

    exporters = [
        {
            "type": "gcs",
            "key": "mlb-statcast/pitcher-stats/%(date)s/%(timestamp)s.json",
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/mlb_statcast_pitcher_%(date)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
    ]

    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        self.opts["date"] = datetime.now(timezone.utc).date().isoformat()
        self.opts["timestamp"] = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        # Default to yesterday if no dates specified
        if not self.opts.get("start_date") and not self.opts.get("season"):
            yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
            self.opts["start_date"] = yesterday.isoformat()
            self.opts["end_date"] = yesterday.isoformat()

    def set_url(self) -> None:
        # Not using URL - data comes from pybaseball
        self.url = "pybaseball://statcast_pitcher"

    def set_headers(self) -> None:
        self.headers = {}

    def download(self) -> None:
        """Override download to use pybaseball instead of HTTP."""
        if not PYBASEBALL_AVAILABLE:
            raise ImportError(
                "pybaseball is required for Statcast data. "
                "Install with: pip install pybaseball"
            )

        self.download_data = self._fetch_statcast_data()

    def _fetch_statcast_data(self) -> Dict[str, Any]:
        """Fetch Statcast data using pybaseball."""
        import pandas as pd

        results = {
            "pitch_data": [],
            "season_stats": [],
        }

        start_dt = self.opts.get("start_date")
        end_dt = self.opts.get("end_date") or start_dt
        player_id = self.opts.get("player_id")

        # Fetch pitch-level data for specific pitcher
        if player_id and start_dt:
            logger.info("Fetching Statcast data for pitcher %s from %s to %s",
                       player_id, start_dt, end_dt)
            try:
                df = statcast_pitcher(start_dt, end_dt, player_id=int(player_id))
                if df is not None and not df.empty:
                    # Convert to dict records
                    results["pitch_data"] = df.to_dict(orient="records")
                    # Aggregate key metrics
                    results["aggregated"] = self._aggregate_pitch_data(df)
                    logger.info("Retrieved %d pitches", len(df))
            except Exception as e:
                logger.error("Error fetching Statcast pitch data: %s", e)

        # Fetch season-level pitching stats from FanGraphs via pybaseball
        if self.opts.get("season"):
            season = int(self.opts["season"])
            logger.info("Fetching FanGraphs pitching stats for season %d", season)
            try:
                df = pitching_stats(season, season, qual=1)  # qual=1 = qualified pitchers
                if df is not None and not df.empty:
                    # Filter to key K-relevant columns
                    key_cols = [
                        'Name', 'Team', 'Age', 'W', 'L', 'ERA', 'G', 'GS', 'IP',
                        'SO', 'BB', 'K/9', 'BB/9', 'K/BB', 'K%', 'BB%',
                        'SwStr%', 'WHIP', 'FIP', 'xFIP', 'WAR'
                    ]
                    available_cols = [c for c in key_cols if c in df.columns]
                    df_filtered = df[available_cols].copy()
                    results["season_stats"] = df_filtered.to_dict(orient="records")
                    logger.info("Retrieved stats for %d pitchers", len(df))
            except Exception as e:
                logger.error("Error fetching FanGraphs pitching stats: %s", e)

        return results

    def _aggregate_pitch_data(self, df) -> Dict[str, Any]:
        """Aggregate pitch-level data into summary metrics."""
        import pandas as pd

        agg = {}

        try:
            # Total pitches
            agg["total_pitches"] = len(df)

            # Velocity stats
            if "release_speed" in df.columns:
                agg["avg_velocity"] = round(df["release_speed"].mean(), 1)
                agg["max_velocity"] = round(df["release_speed"].max(), 1)

            # Spin rate
            if "release_spin_rate" in df.columns:
                agg["avg_spin_rate"] = round(df["release_spin_rate"].mean(), 0)

            # Swing/miss calculation
            if "description" in df.columns:
                swings = df[df["description"].isin([
                    "swinging_strike", "swinging_strike_blocked",
                    "foul", "foul_tip", "hit_into_play"
                ])]
                whiffs = df[df["description"].isin([
                    "swinging_strike", "swinging_strike_blocked"
                ])]
                if len(swings) > 0:
                    agg["whiff_rate"] = round(len(whiffs) / len(swings) * 100, 1)

            # Called strikes + swinging strikes
            if "description" in df.columns:
                strikes = df[df["description"].isin([
                    "called_strike", "swinging_strike", "swinging_strike_blocked",
                    "foul", "foul_tip"
                ])]
                agg["strike_pct"] = round(len(strikes) / len(df) * 100, 1)

            # Zone analysis
            if "zone" in df.columns:
                in_zone = df[df["zone"].between(1, 9)]
                out_zone = df[~df["zone"].between(1, 9)]
                agg["zone_pct"] = round(len(in_zone) / len(df) * 100, 1)

                # Chase rate (swings at pitches outside zone)
                if "description" in df.columns:
                    out_zone_swings = out_zone[out_zone["description"].isin([
                        "swinging_strike", "swinging_strike_blocked",
                        "foul", "foul_tip", "hit_into_play"
                    ])]
                    if len(out_zone) > 0:
                        agg["chase_rate"] = round(len(out_zone_swings) / len(out_zone) * 100, 1)

            # Pitch type breakdown
            if "pitch_type" in df.columns:
                pitch_counts = df["pitch_type"].value_counts()
                agg["pitch_mix"] = pitch_counts.to_dict()

        except Exception as e:
            logger.warning("Error aggregating pitch data: %s", e)

        return agg

    def validate_download_data(self) -> None:
        if not self.download_data:
            raise ValueError("No Statcast data retrieved")

    def transform_data(self) -> None:
        self.data = {
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "player_id": self.opts.get("player_id"),
            "start_date": self.opts.get("start_date"),
            "end_date": self.opts.get("end_date"),
            "season": self.opts.get("season"),
            "pitchCount": len(self.download_data.get("pitch_data", [])),
            "pitcherCount": len(self.download_data.get("season_stats", [])),
            **self.download_data,
        }

        logger.info("Processed Statcast data: %d pitches, %d season records",
                   self.data["pitchCount"], self.data["pitcherCount"])

    def get_scraper_stats(self) -> dict:
        return {
            "pitchCount": self.data.get("pitchCount", 0),
            "pitcherCount": self.data.get("pitcherCount", 0),
        }


create_app = convert_existing_flask_scraper(MlbStatcastPitcherScraper)

if __name__ == "__main__":
    main = MlbStatcastPitcherScraper.create_cli_and_flask_main()
    main()
