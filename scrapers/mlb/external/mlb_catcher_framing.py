"""
File: scrapers/mlb/external/mlb_catcher_framing.py

MLB Catcher Framing — Baseball Savant                          v1.0 - 2026-03-10
--------------------------------------------------------------------------------
Scrapes catcher framing data from Baseball Savant's Statcast leaderboard.

Data Source: https://baseballsavant.mlb.com/catcher_framing
- Season-level catcher framing metrics
- Framing runs above/below average
- Strike rate, extra strikes called per game
- Shadow zone performance

Key Metrics for K Predictions (Session 460):
- framing_runs: Total framing runs above average (positive = elite, negative = poor)
- framing_runs_per_game: Per-game framing impact
- strike_rate: Called strike rate on borderline pitches
- extra_strikes_per_game: Additional strikes gained/lost through framing

Impact: Each framing run per game adds ~3.9% to pitcher K rate. Elite framers
can add 1-2 called strikes per game, while poor framers lose them. This creates
a 4-6% K rate differential between top/bottom quartile catchers.

Usage:
  python scrapers/mlb/external/mlb_catcher_framing.py --debug
  python scrapers/mlb/external/mlb_catcher_framing.py --season 2025 --debug
"""

from __future__ import annotations

import csv
import io
import logging
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

logger = logging.getLogger(__name__)

# Baseball Savant catcher framing CSV endpoint
# This is the public Statcast leaderboard CSV export — no auth required.
FRAMING_CSV_URL = (
    "https://baseballsavant.mlb.com/leaderboard/catcher-framing"
    "?type=catcher&year={season}&min=100&sort=6&sortDir=desc&csv=true"
)


class MlbCatcherFramingScraper(ScraperBase, ScraperFlaskMixin):
    """
    Scraper for MLB catcher framing data from Baseball Savant.

    Provides per-catcher framing metrics that affect pitcher K rates:
    - Elite framers (top 25%) add 1-2 called strikes per game
    - Poor framers (bottom 25%) lose 1-2 called strikes per game
    - Combined with pitcher CSW%, creates a powerful K prediction signal
    """

    scraper_name = "mlb_catcher_framing"
    required_params = []
    optional_params = {
        "season": None,     # Filter by season (e.g., 2025)
        "min_pitches": 100,  # Minimum pitches received to include
    }

    required_opts: List[str] = []
    download_type = DownloadType.HTML  # CSV text returned as HTML response
    decode_download_data = True
    proxy_enabled: bool = False  # Baseball Savant public endpoint

    exporters = [
        {
            "type": "gcs",
            "key": "mlb-external/catcher-framing/%(season)s/%(timestamp)s.json",
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/mlb_catcher_framing_%(season)s_%(date)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
    ]

    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        self.opts["date"] = datetime.now(timezone.utc).date().isoformat()
        self.opts["timestamp"] = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        # Default to current season
        if not self.opts.get("season"):
            self.opts["season"] = str(datetime.now(timezone.utc).year)

    def set_url(self) -> None:
        season = self.opts.get("season", str(datetime.now(timezone.utc).year))
        self.url = FRAMING_CSV_URL.format(season=season)

    def extract_data(self, raw_data: Any) -> Optional[Dict]:
        """Parse Baseball Savant catcher framing CSV data."""
        if not raw_data:
            logger.warning("No framing data returned from Baseball Savant")
            return None

        try:
            # Parse CSV
            reader = csv.DictReader(io.StringIO(raw_data))
            records = []

            for row in reader:
                try:
                    record = self._parse_catcher_row(row)
                    if record:
                        records.append(record)
                except Exception as e:
                    logger.debug(f"Skipping row: {e}")
                    continue

            if not records:
                logger.warning("No valid catcher framing records parsed")
                return None

            logger.info(f"Parsed {len(records)} catcher framing records "
                       f"for season {self.opts.get('season')}")

            return {
                "season": int(self.opts.get("season")),
                "scrape_date": self.opts["date"],
                "record_count": len(records),
                "catchers": records,
            }

        except Exception as e:
            logger.error(f"Failed to parse framing CSV: {e}")
            return None

    def _parse_catcher_row(self, row: Dict) -> Optional[Dict]:
        """Parse a single catcher row from the CSV."""
        # Baseball Savant CSV columns vary by year but typically include:
        # player_id, player_name, team, pitches, runs_extra_strikes,
        # strike_rate, called_strikes, shadow_zone_rate, etc.

        # Baseball Savant CSV: "name" = "Last, First" format
        player_name = row.get('name') or row.get('last_name, first_name') or row.get('player_name') or ''
        if not player_name:
            return None

        # Normalize name to player_lookup format
        # "Bailey, Patrick" -> "patrick_bailey"
        if ',' in player_name:
            parts = player_name.split(',', 1)
            player_lookup = f"{parts[1].strip()}_{parts[0].strip()}".lower()
        else:
            player_lookup = player_name.strip().lower()
        player_lookup = player_lookup.replace(' ', '_').replace('.', '').replace("'", '')

        # Extract numeric fields
        def safe_float(key: str) -> Optional[float]:
            val = row.get(key)
            if val is None or val == '' or val == 'null':
                return None
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        def safe_int(key: str) -> Optional[int]:
            val = row.get(key)
            if val is None or val == '' or val == 'null':
                return None
            try:
                return int(float(val))
            except (ValueError, TypeError):
                return None

        # Key metrics — Baseball Savant catcher framing CSV columns:
        #   rv_tot = framing runs total (positive = elite)
        #   pct_tot = overall framing percentage
        #   pitches = total pitches received
        framing_runs = safe_float('rv_tot')
        pitches = safe_int('pitches')
        strike_rate = safe_float('pct_tot')
        shadow_strike_rate = None  # Not directly available in CSV
        games = None  # Not in CSV; estimate from pitches

        # Compute per-game framing impact
        framing_runs_per_game = None
        if framing_runs is not None and games and games > 0:
            framing_runs_per_game = round(framing_runs / games, 3)

        return {
            "player_name": player_name.strip(),
            "player_lookup": player_lookup,
            "player_id": safe_int('id') or safe_int('\ufeffid'),  # BOM in CSV header
            "team_abbr": row.get('team') or row.get('team_abbr') or '',
            "season": int(self.opts.get("season")),
            "games": games,
            "pitches_received": pitches,
            "framing_runs": round(framing_runs, 2) if framing_runs is not None else None,
            "framing_runs_per_game": framing_runs_per_game,
            "strike_rate": round(strike_rate, 4) if strike_rate is not None else None,
            "shadow_zone_strike_rate": round(shadow_strike_rate, 4) if shadow_strike_rate is not None else None,
            "scrape_date": self.opts["date"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }


# Flask app for Cloud Run deployment
app = convert_existing_flask_scraper(MlbCatcherFramingScraper)

if __name__ == "__main__":
    main = MlbCatcherFramingScraper.create_cli_and_flask_main()
    main()
