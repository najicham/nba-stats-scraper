"""
File: scrapers/mlb/external/mlb_ballpark_factors.py

MLB Ballpark Factors                                              v1.0 - 2026-01-06
--------------------------------------------------------------------------------
Static ballpark factor data for MLB stadiums.

Data Source: Historical park factors from FanGraphs/Baseball Reference
- Updated annually (beginning of each season)
- Factors are relative to league average (100 = neutral)

Key Factors for K Predictions:
- k_factor: Strikeout factor (>100 = pitcher friendly, more Ks)
- run_factor: Run scoring factor
- hr_factor: Home run factor
- altitude: Elevation affects ball flight

High K Parks (k_factor > 105):
- Petco Park (San Diego)
- Oracle Park (San Francisco)
- Citi Field (New York Mets)

Low K Parks (k_factor < 95):
- Coors Field (Colorado) - thin air, more offense
- Great American Ball Park (Cincinnati)

Usage:
  python scrapers/mlb/external/mlb_ballpark_factors.py --debug
  python scrapers/mlb/external/mlb_ballpark_factors.py --team_abbr NYY
"""

from __future__ import annotations

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


# Static ballpark factors data (2024-2025 estimates)
# Source: FanGraphs Park Factors, Baseball Reference
# 100 = league average, >100 = favors that stat
BALLPARK_FACTORS = {
    # American League
    "BAL": {  # Camden Yards
        "name": "Oriole Park at Camden Yards",
        "city": "Baltimore",
        "team": "Orioles",
        "k_factor": 98,
        "run_factor": 102,
        "hr_factor": 108,
        "altitude_ft": 33,
        "roof": "open",
        "surface": "grass",
    },
    "BOS": {  # Fenway Park
        "name": "Fenway Park",
        "city": "Boston",
        "team": "Red Sox",
        "k_factor": 96,
        "run_factor": 106,
        "hr_factor": 104,
        "altitude_ft": 21,
        "roof": "open",
        "surface": "grass",
    },
    "NYY": {  # Yankee Stadium
        "name": "Yankee Stadium",
        "city": "New York",
        "team": "Yankees",
        "k_factor": 100,
        "run_factor": 104,
        "hr_factor": 112,
        "altitude_ft": 55,
        "roof": "open",
        "surface": "grass",
    },
    "TB": {  # Tropicana Field
        "name": "Tropicana Field",
        "city": "St. Petersburg",
        "team": "Rays",
        "k_factor": 102,
        "run_factor": 96,
        "hr_factor": 94,
        "altitude_ft": 43,
        "roof": "dome",
        "surface": "turf",
    },
    "TOR": {  # Rogers Centre
        "name": "Rogers Centre",
        "city": "Toronto",
        "team": "Blue Jays",
        "k_factor": 99,
        "run_factor": 100,
        "hr_factor": 102,
        "altitude_ft": 269,
        "roof": "retractable",
        "surface": "turf",
    },
    "CLE": {  # Progressive Field
        "name": "Progressive Field",
        "city": "Cleveland",
        "team": "Guardians",
        "k_factor": 101,
        "run_factor": 97,
        "hr_factor": 96,
        "altitude_ft": 653,
        "roof": "open",
        "surface": "grass",
    },
    "CWS": {  # Guaranteed Rate Field
        "name": "Guaranteed Rate Field",
        "city": "Chicago",
        "team": "White Sox",
        "k_factor": 99,
        "run_factor": 101,
        "hr_factor": 105,
        "altitude_ft": 595,
        "roof": "open",
        "surface": "grass",
    },
    "DET": {  # Comerica Park
        "name": "Comerica Park",
        "city": "Detroit",
        "team": "Tigers",
        "k_factor": 103,
        "run_factor": 95,
        "hr_factor": 92,
        "altitude_ft": 600,
        "roof": "open",
        "surface": "grass",
    },
    "KC": {  # Kauffman Stadium
        "name": "Kauffman Stadium",
        "city": "Kansas City",
        "team": "Royals",
        "k_factor": 100,
        "run_factor": 98,
        "hr_factor": 96,
        "altitude_ft": 889,
        "roof": "open",
        "surface": "grass",
    },
    "MIN": {  # Target Field
        "name": "Target Field",
        "city": "Minneapolis",
        "team": "Twins",
        "k_factor": 100,
        "run_factor": 99,
        "hr_factor": 98,
        "altitude_ft": 841,
        "roof": "open",
        "surface": "grass",
    },
    "HOU": {  # Minute Maid Park
        "name": "Minute Maid Park",
        "city": "Houston",
        "team": "Astros",
        "k_factor": 98,
        "run_factor": 103,
        "hr_factor": 108,
        "altitude_ft": 43,
        "roof": "retractable",
        "surface": "grass",
    },
    "LAA": {  # Angel Stadium
        "name": "Angel Stadium",
        "city": "Anaheim",
        "team": "Angels",
        "k_factor": 99,
        "run_factor": 98,
        "hr_factor": 98,
        "altitude_ft": 160,
        "roof": "open",
        "surface": "grass",
    },
    "OAK": {  # Oakland Coliseum
        "name": "Oakland Coliseum",
        "city": "Oakland",
        "team": "Athletics",
        "k_factor": 104,
        "run_factor": 93,
        "hr_factor": 90,
        "altitude_ft": 39,
        "roof": "open",
        "surface": "grass",
    },
    "SEA": {  # T-Mobile Park
        "name": "T-Mobile Park",
        "city": "Seattle",
        "team": "Mariners",
        "k_factor": 103,
        "run_factor": 94,
        "hr_factor": 92,
        "altitude_ft": 20,
        "roof": "retractable",
        "surface": "grass",
    },
    "TEX": {  # Globe Life Field
        "name": "Globe Life Field",
        "city": "Arlington",
        "team": "Rangers",
        "k_factor": 101,
        "run_factor": 98,
        "hr_factor": 98,
        "altitude_ft": 551,
        "roof": "retractable",
        "surface": "grass",
    },
    # National League
    "ATL": {  # Truist Park
        "name": "Truist Park",
        "city": "Atlanta",
        "team": "Braves",
        "k_factor": 99,
        "run_factor": 100,
        "hr_factor": 102,
        "altitude_ft": 1050,
        "roof": "open",
        "surface": "grass",
    },
    "MIA": {  # loanDepot park
        "name": "loanDepot park",
        "city": "Miami",
        "team": "Marlins",
        "k_factor": 102,
        "run_factor": 96,
        "hr_factor": 93,
        "altitude_ft": 7,
        "roof": "retractable",
        "surface": "grass",
    },
    "NYM": {  # Citi Field
        "name": "Citi Field",
        "city": "New York",
        "team": "Mets",
        "k_factor": 105,
        "run_factor": 94,
        "hr_factor": 91,
        "altitude_ft": 20,
        "roof": "open",
        "surface": "grass",
    },
    "PHI": {  # Citizens Bank Park
        "name": "Citizens Bank Park",
        "city": "Philadelphia",
        "team": "Phillies",
        "k_factor": 97,
        "run_factor": 105,
        "hr_factor": 110,
        "altitude_ft": 20,
        "roof": "open",
        "surface": "grass",
    },
    "WSH": {  # Nationals Park
        "name": "Nationals Park",
        "city": "Washington",
        "team": "Nationals",
        "k_factor": 100,
        "run_factor": 99,
        "hr_factor": 100,
        "altitude_ft": 25,
        "roof": "open",
        "surface": "grass",
    },
    "CHC": {  # Wrigley Field
        "name": "Wrigley Field",
        "city": "Chicago",
        "team": "Cubs",
        "k_factor": 98,
        "run_factor": 102,
        "hr_factor": 104,
        "altitude_ft": 600,
        "roof": "open",
        "surface": "grass",
    },
    "CIN": {  # Great American Ball Park
        "name": "Great American Ball Park",
        "city": "Cincinnati",
        "team": "Reds",
        "k_factor": 94,
        "run_factor": 108,
        "hr_factor": 115,
        "altitude_ft": 490,
        "roof": "open",
        "surface": "grass",
    },
    "MIL": {  # American Family Field
        "name": "American Family Field",
        "city": "Milwaukee",
        "team": "Brewers",
        "k_factor": 100,
        "run_factor": 100,
        "hr_factor": 102,
        "altitude_ft": 635,
        "roof": "retractable",
        "surface": "grass",
    },
    "PIT": {  # PNC Park
        "name": "PNC Park",
        "city": "Pittsburgh",
        "team": "Pirates",
        "k_factor": 102,
        "run_factor": 96,
        "hr_factor": 93,
        "altitude_ft": 730,
        "roof": "open",
        "surface": "grass",
    },
    "STL": {  # Busch Stadium
        "name": "Busch Stadium",
        "city": "St. Louis",
        "team": "Cardinals",
        "k_factor": 99,
        "run_factor": 98,
        "hr_factor": 97,
        "altitude_ft": 455,
        "roof": "open",
        "surface": "grass",
    },
    "AZ": {  # Chase Field
        "name": "Chase Field",
        "city": "Phoenix",
        "team": "Diamondbacks",
        "k_factor": 98,
        "run_factor": 104,
        "hr_factor": 106,
        "altitude_ft": 1082,
        "roof": "retractable",
        "surface": "grass",
    },
    "COL": {  # Coors Field - THE outlier!
        "name": "Coors Field",
        "city": "Denver",
        "team": "Rockies",
        "k_factor": 88,  # MUCH fewer Ks at altitude
        "run_factor": 118,  # Highest run environment
        "hr_factor": 120,  # HR heaven
        "altitude_ft": 5280,  # Mile high!
        "roof": "open",
        "surface": "grass",
    },
    "LAD": {  # Dodger Stadium
        "name": "Dodger Stadium",
        "city": "Los Angeles",
        "team": "Dodgers",
        "k_factor": 101,
        "run_factor": 97,
        "hr_factor": 96,
        "altitude_ft": 512,
        "roof": "open",
        "surface": "grass",
    },
    "SD": {  # Petco Park
        "name": "Petco Park",
        "city": "San Diego",
        "team": "Padres",
        "k_factor": 106,  # Very pitcher friendly
        "run_factor": 92,
        "hr_factor": 88,
        "altitude_ft": 22,
        "roof": "open",
        "surface": "grass",
    },
    "SF": {  # Oracle Park
        "name": "Oracle Park",
        "city": "San Francisco",
        "team": "Giants",
        "k_factor": 105,  # Very pitcher friendly
        "run_factor": 93,
        "hr_factor": 86,
        "altitude_ft": 2,
        "roof": "open",
        "surface": "grass",
    },
}


class MlbBallparkFactorsScraper(ScraperBase, ScraperFlaskMixin):
    """
    Scraper for MLB ballpark factors (static data).

    Provides park-specific adjustments for K predictions:
    - Some parks favor pitchers (more Ks)
    - Some parks favor hitters (fewer Ks)
    - Altitude significantly affects strikeout rates
    """

    scraper_name = "mlb_ballpark_factors"
    required_params = []
    optional_params = {
        "team_abbr": None,   # Filter by team
        "season": None,      # For versioning
    }

    required_opts: List[str] = []
    download_type = DownloadType.JSON
    decode_download_data = False  # Using static data
    proxy_enabled: bool = False

    exporters = [
        {
            "type": "gcs",
            "key": "mlb-external/ballpark-factors/%(season)s/%(timestamp)s.json",
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/mlb_ballpark_factors_%(season)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
    ]

    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        self.opts["date"] = datetime.now(timezone.utc).date().isoformat()
        self.opts["timestamp"] = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        if not self.opts.get("season"):
            now = datetime.now(timezone.utc)
            if now.month < 4:
                self.opts["season"] = str(now.year - 1)
            else:
                self.opts["season"] = str(now.year)

    def set_url(self) -> None:
        # Static data - no URL needed
        self.url = "static://ballpark_factors"

    def set_headers(self) -> None:
        self.headers = {}

    def download(self) -> None:
        """Override download to use static data."""
        self.download_data = BALLPARK_FACTORS

    def validate_download_data(self) -> None:
        if not self.download_data:
            raise ValueError("Ballpark factors data not loaded")

    def transform_data(self) -> None:
        """Transform ballpark factors into standardized format."""
        parks = []

        for abbr, park_data in BALLPARK_FACTORS.items():
            park = {
                "team_abbr": abbr,
                **park_data,
                "k_adjustment": self._calculate_k_adjustment(park_data["k_factor"]),
            }
            parks.append(park)

        # Filter by team if specified
        if self.opts.get("team_abbr"):
            team_filter = self.opts["team_abbr"].upper()
            parks = [p for p in parks if p["team_abbr"] == team_filter]

        # Sort by K factor (pitcher friendly first)
        parks_sorted = sorted(parks, key=lambda x: x["k_factor"], reverse=True)

        # Categorize parks
        high_k_parks = [p for p in parks if p["k_factor"] >= 103]
        low_k_parks = [p for p in parks if p["k_factor"] <= 97]
        neutral_parks = [p for p in parks if 97 < p["k_factor"] < 103]

        self.data = {
            "season": self.opts.get("season"),
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "FanGraphs/Baseball Reference (compiled)",
            "parkCount": len(parks),
            "parks": parks_sorted,
            "highKParks": high_k_parks,
            "lowKParks": low_k_parks,
            "neutralParks": neutral_parks,
            "lookupByTeam": {p["team_abbr"]: p for p in parks},
        }

        logger.info("Loaded ballpark factors for %d parks", len(parks))

    def _calculate_k_adjustment(self, k_factor: int) -> float:
        """
        Calculate K adjustment multiplier from park factor.

        Returns a multiplier to apply to K predictions.
        100 = 1.0 (no adjustment)
        110 = 1.10 (10% more Ks expected)
        90 = 0.90 (10% fewer Ks expected)
        """
        return round(k_factor / 100, 3)

    def get_scraper_stats(self) -> dict:
        return {
            "parkCount": self.data.get("parkCount", 0),
            "season": self.data.get("season"),
        }


create_app = convert_existing_flask_scraper(MlbBallparkFactorsScraper)

if __name__ == "__main__":
    main = MlbBallparkFactorsScraper.create_cli_and_flask_main()
    main()
