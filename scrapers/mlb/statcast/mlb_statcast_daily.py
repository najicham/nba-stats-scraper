"""
File: scrapers/mlb/statcast/mlb_statcast_daily.py

MLB Statcast - Daily Pitcher Summary (Batch)                     v1.0 - 2026-03-06
--------------------------------------------------------------------------------
Batch scraper that fetches ALL pitch data for a given date and aggregates
per-pitcher metrics. Unlike mlb_statcast_pitcher.py (single-pitcher queries),
this pulls every pitcher who threw on the target date in one call.

Data Source: Baseball Savant (baseballsavant.mlb.com)
Method: Uses pybaseball.statcast() for full-day pitch data

Key Metrics per pitcher:
- Velocity (avg fastball, max)
- Spin rate
- Swinging strike % (swstr_pct)
- Called + swinging strike % (csw_pct)
- Whiff rate (swing-and-miss on swings)
- Zone % and chase rate
- Pitch type breakdown (pitch mix)

Requirements:
  pip install pybaseball

Usage:
  python scrapers/mlb/statcast/mlb_statcast_daily.py --debug
  python scrapers/mlb/statcast/mlb_statcast_daily.py --date 2025-06-15 --debug
"""

from __future__ import annotations

import logging
import math
import os
import sys
from datetime import datetime, timezone
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
    from pybaseball import statcast, cache
    cache.enable()
    PYBASEBALL_AVAILABLE = True
except ImportError:
    PYBASEBALL_AVAILABLE = False

logger = logging.getLogger(__name__)

# Pitch descriptions for classification
SWINGING_STRIKE_DESCRIPTIONS = frozenset([
    "swinging_strike",
    "swinging_strike_blocked",
])

CALLED_STRIKE_DESCRIPTIONS = frozenset([
    "called_strike",
])

FOUL_DESCRIPTIONS = frozenset([
    "foul",
    "foul_tip",
])

BALL_DESCRIPTIONS = frozenset([
    "ball",
    "blocked_ball",
    "hit_by_pitch",
])

IN_PLAY_DESCRIPTIONS = frozenset([
    "hit_into_play",
    "hit_into_play_no_out",
    "hit_into_play_score",
])

# All swing descriptions (for chase rate calculation)
SWING_DESCRIPTIONS = SWINGING_STRIKE_DESCRIPTIONS | FOUL_DESCRIPTIONS | IN_PLAY_DESCRIPTIONS

# Fastball pitch types (for avg_velocity calculation)
FASTBALL_TYPES = frozenset(["FF", "SI", "FC"])


def _safe_round(value: Any, decimals: int = 1) -> Optional[float]:
    """Round a value, returning None if it's NaN/None."""
    if value is None:
        return None
    try:
        if math.isnan(value) or math.isinf(value):
            return None
        return round(float(value), decimals)
    except (TypeError, ValueError):
        return None


def _safe_div(numerator: int, denominator: int, scale: float = 100.0) -> Optional[float]:
    """Safe division returning rounded percentage, or None if denominator is 0."""
    if denominator == 0:
        return None
    return _safe_round(numerator / denominator * scale)


class MlbStatcastDailyScraper(ScraperBase, ScraperFlaskMixin):
    """
    Batch scraper for daily MLB Statcast pitcher summaries.

    Fetches ALL pitch data for a target date using pybaseball.statcast(),
    then aggregates per-pitcher metrics including velocity, spin rate,
    swinging strike %, CSW%, whiff rate, zone %, chase rate, and pitch mix.

    NOTE: Requires pybaseball to be installed: pip install pybaseball
    """

    scraper_name = "mlb_statcast_daily"
    required_params = []
    optional_params = {
        "date": None,  # Target date (YYYY-MM-DD), defaults to yesterday Pacific
    }

    required_opts: List[str] = ["date"]
    download_type = DownloadType.JSON
    decode_download_data = False  # We're not downloading from URL
    proxy_enabled: bool = False

    exporters = [
        {
            "type": "gcs",
            "key": "mlb-statcast/daily-pitcher-summary/%(date)s/%(timestamp)s.json",
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/mlb_statcast_daily_%(date)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
    ]

    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        self.opts["timestamp"] = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        # Default to yesterday Pacific if no date specified
        if not self.opts.get("date"):
            from scrapers.utils.date_utils import get_yesterday_pacific
            self.opts["date"] = get_yesterday_pacific()

    def set_url(self) -> None:
        # Not using URL - data comes from pybaseball
        self.url = "pybaseball://statcast"

    def set_headers(self) -> None:
        self.headers = {}

    def download_and_decode(self) -> None:
        """Override download_and_decode to use pybaseball instead of HTTP.

        Must override download_and_decode (not download) because the base
        lifecycle calls download_and_decode from the HTTP handler mixin.
        """
        if not PYBASEBALL_AVAILABLE:
            raise ImportError(
                "pybaseball is required for Statcast data. "
                "Install with: pip install pybaseball"
            )

        target_date = self.opts["date"]
        logger.info("Fetching Statcast data for all pitchers on %s", target_date)

        try:
            df = statcast(start_dt=target_date, end_dt=target_date)
        except Exception as e:
            logger.error("Error fetching Statcast data for %s: %s", target_date, e)
            raise

        if df is None or df.empty:
            logger.warning("No Statcast data returned for %s", target_date)
            self.data = {
                "date": target_date,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "pitchers_found": 0,
                "total_pitches": 0,
                "pitcher_summaries": [],
            }
            return

        logger.info("Retrieved %d total pitches for %s", len(df), target_date)
        result = self._aggregate_all_pitchers(df)

        self.data = {
            "date": target_date,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pitchers_found": len(result.get("pitcher_summaries", [])),
            "total_pitches": result.get("total_pitches", 0),
            "pitcher_summaries": result.get("pitcher_summaries", []),
        }

    def _aggregate_all_pitchers(self, df) -> Dict[str, Any]:
        """Aggregate pitch-level data into per-pitcher summaries."""
        import pandas as pd

        summaries = []

        # Group by pitcher AND game (a pitcher could appear in multiple games,
        # e.g., traded mid-day doubleheader — though extremely rare)
        group_cols = ["pitcher"]
        if "game_pk" in df.columns:
            group_cols.append("game_pk")

        for group_key, pitcher_df in df.groupby(group_cols):
            if len(group_cols) == 2:
                pitcher_id, game_pk = group_key
            else:
                pitcher_id = group_key
                game_pk = None

            summary = self._aggregate_single_pitcher(pitcher_df, pitcher_id, game_pk)
            if summary is not None:
                summaries.append(summary)

        # Sort by total_pitches descending (starters first)
        summaries.sort(key=lambda x: x.get("total_pitches", 0), reverse=True)

        total_pitches = sum(s.get("total_pitches", 0) for s in summaries)

        return {
            "pitcher_summaries": summaries,
            "total_pitches": total_pitches,
        }

    def _aggregate_single_pitcher(
        self, df, pitcher_id: int, game_pk: Optional[int]
    ) -> Optional[Dict[str, Any]]:
        """Compute aggregated metrics for a single pitcher's outing."""
        import pandas as pd

        total_pitches = len(df)
        if total_pitches == 0:
            return None

        # Pitcher name — pybaseball uses 'player_name' column
        pitcher_name = None
        if "player_name" in df.columns:
            names = df["player_name"].dropna()
            if not names.empty:
                pitcher_name = str(names.iloc[0])

        # Game date
        game_date = None
        if "game_date" in df.columns:
            dates = df["game_date"].dropna()
            if not dates.empty:
                gd = dates.iloc[0]
                game_date = str(gd)[:10] if gd is not None else None

        # ----- Velocity -----
        avg_velocity = None
        if "release_speed" in df.columns and "pitch_type" in df.columns:
            fastballs = df[df["pitch_type"].isin(FASTBALL_TYPES)]
            if not fastballs.empty:
                avg_velocity = _safe_round(fastballs["release_speed"].mean())

        max_velocity = None
        if "release_speed" in df.columns:
            max_velocity = _safe_round(df["release_speed"].max())

        # ----- Spin rate -----
        avg_spin_rate = None
        if "release_spin_rate" in df.columns:
            avg_spin_rate = _safe_round(df["release_spin_rate"].mean(), 0)

        # ----- Pitch outcome counts -----
        desc_col = df["description"] if "description" in df.columns else pd.Series(dtype=str)

        swinging_strikes = int(desc_col.isin(SWINGING_STRIKE_DESCRIPTIONS).sum())
        called_strikes = int(desc_col.isin(CALLED_STRIKE_DESCRIPTIONS).sum())
        fouls = int(desc_col.isin(FOUL_DESCRIPTIONS).sum())
        balls = int(desc_col.isin(BALL_DESCRIPTIONS).sum())
        in_play = int(desc_col.isin(IN_PLAY_DESCRIPTIONS).sum())

        # ----- Derived rates -----
        swstr_pct = _safe_div(swinging_strikes, total_pitches)
        csw_pct = _safe_div(called_strikes + swinging_strikes, total_pitches)

        # Whiff rate: swinging strikes / total swings (swinging_strikes + fouls + in_play)
        total_swings = swinging_strikes + fouls + in_play
        whiff_rate = _safe_div(swinging_strikes, total_swings)

        # ----- Zone analysis -----
        zone_pitches = 0
        zone_pct = None
        chase_swings = 0
        out_of_zone = 0
        chase_rate = None

        if "zone" in df.columns:
            zone_series = pd.to_numeric(df["zone"], errors="coerce")
            zone_pitches = int(zone_series.between(1, 9).sum())
            zone_pct = _safe_div(zone_pitches, total_pitches)

            out_of_zone_mask = zone_series > 9
            out_of_zone = int(out_of_zone_mask.sum())

            if out_of_zone > 0 and "description" in df.columns:
                out_zone_df = df[out_of_zone_mask]
                chase_swings = int(out_zone_df["description"].isin(SWING_DESCRIPTIONS).sum())
                chase_rate = _safe_div(chase_swings, out_of_zone)

        # ----- Pitch type breakdown -----
        pitch_types = {}
        if "pitch_type" in df.columns:
            counts = df["pitch_type"].value_counts()
            pitch_types = {str(k): int(v) for k, v in counts.items() if pd.notna(k)}

        return {
            "pitcher_id": int(pitcher_id),
            "pitcher_name": pitcher_name,
            "game_date": game_date,
            "game_pk": int(game_pk) if game_pk is not None else None,
            "total_pitches": total_pitches,
            "avg_velocity": avg_velocity,
            "max_velocity": max_velocity,
            "avg_spin_rate": avg_spin_rate,
            "swinging_strikes": swinging_strikes,
            "called_strikes": called_strikes,
            "fouls": fouls,
            "balls": balls,
            "in_play": in_play,
            "swstr_pct": swstr_pct,
            "csw_pct": csw_pct,
            "whiff_rate": whiff_rate,
            "zone_pitches": zone_pitches,
            "zone_pct": zone_pct,
            "chase_swings": chase_swings,
            "out_of_zone": out_of_zone,
            "chase_rate": chase_rate,
            "pitch_types": pitch_types,
        }

    def validate_download_data(self) -> None:
        if self.download_data is None:
            raise ValueError("No Statcast data retrieved")

    def transform_data(self) -> None:
        summaries = self.download_data.get("pitcher_summaries", [])
        total_pitches = self.download_data.get("total_pitches", 0)

        self.data = {
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pitchers_found": len(summaries),
            "total_pitches": total_pitches,
            "pitcher_summaries": summaries,
        }

        logger.info(
            "Processed daily Statcast data for %s: %d pitchers, %d total pitches",
            self.opts["date"],
            len(summaries),
            total_pitches,
        )

    def get_scraper_stats(self) -> dict:
        return {
            "date": self.opts.get("date"),
            "pitchers_found": self.data.get("pitchers_found", 0),
            "total_pitches": self.data.get("total_pitches", 0),
        }


create_app = convert_existing_flask_scraper(MlbStatcastDailyScraper)

if __name__ == "__main__":
    main = MlbStatcastDailyScraper.create_cli_and_flask_main()
    main()
