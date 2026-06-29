# File: scrapers/external/espn_injuries.py
"""
ESPN NBA Injuries Scraper                                        v1.0 - 2026-06-29
----------------------------------------------------------------------------------
Polls ESPN's public injuries API to capture player injury status snapshots with
timestamps. Designed to run hourly on game days to detect GTD→Out status flips
in the window before tip-off.

API: https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries
     Response is JSON (no auth required, public endpoint).

API Response Structure (verified 2026-06-29):
  {
    "injuries": [
      {
        "id": "-54150",
        "displayName": "Atlanta Hawks",
        "athlete": {
          "firstName": "Jock",
          "lastName": "Landale",
          "displayName": "Jock Landale"
        },
        "shortComment": "Landale (ankle) will be re-evaluated...",
        "longComment": "Narrative text with details...",
        "status": "Day-To-Day",
        "date": "2026-06-16T14:28Z",
        "details": {
          "type": "Ankle",
          "location": "Leg",
          "detail": "Sprain",
          "side": "Right",
          "returnDate": "2026-10-01",
          "fantasyStatus": { "description": "Game-Time Decision", "abbreviation": "GTD" }
        }
      }
    ]
  }

Key fields extracted per injury:
  - espn_injury_id   ESPN injury record ID (string, may be negative)
  - player_name      Full display name of injured player
  - team_name        Team display name (from displayName on the injury object)
  - status           ESPN status string ("Day-To-Day", "Out", "Questionable", etc.)
  - fantasy_status   Fantasy abbreviation from details.fantasyStatus.abbreviation
                     ("GTD", "OUT", "O", etc.) — the key field for GTD→Out detection
  - injury_type      Injury category from details.type (e.g. "Ankle")
  - injury_detail    Specificity from details.detail (e.g. "Sprain")
  - injury_side      Body side from details.side (e.g. "Right")
  - short_comment    Short narrative snippet
  - long_comment     Full narrative text
  - reported_at      UTC timestamp of the injury report from ESPN (details.date)
  - return_date      Projected return date from details.returnDate (if present)
  - game_date        Date the scraper ran (partition key for BQ)
  - scraped_at       UTC timestamp when this snapshot was collected

GTD→Out Detection Pattern:
  Multiple runs per game day produce multiple rows per player with different
  scraped_at values. Downstream query:
    SELECT player_name, fantasy_status, scraped_at
    FROM nba_raw.espn_injuries
    WHERE game_date = CURRENT_DATE()
    ORDER BY player_name, scraped_at
  detects any player whose fantasy_status changed from "GTD" to "OUT"/"O" in
  the hours before tip-off — the signal we're building toward.

Usage:
  python scrapers/external/espn_injuries.py --date 2026-06-29 --debug
  python scrapers/external/espn_injuries.py --date 2026-06-29 --group prod
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

# ESPN NBA injuries endpoint — public JSON API, no auth required
ESPN_INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"

GCS_PATH_KEY = "espn_injuries"


class ESPNInjuriesScraper(ScraperBase, ScraperFlaskMixin):
    """Poll ESPN NBA injuries API to capture timestamped injury status snapshots."""

    scraper_name = "espn_injuries"
    required_params = ["date"]
    optional_params = {}

    required_opts: List[str] = ["date"]
    download_type: DownloadType = DownloadType.JSON
    decode_download_data: bool = True
    header_profile: str | None = "espn"   # Injects ESPN User-Agent via ScraperBase
    proxy_enabled: bool = False            # ESPN public API works from Cloud IPs

    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/espn_injuries_%(date)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test"],
        },
        {
            "type": "file",
            "filename": "/tmp/raw_espn_injuries_%(date)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
    ]

    def set_url(self) -> None:
        """ESPN injuries endpoint has no required query params."""
        self.url = ESPN_INJURIES_URL
        logger.info("ESPN NBA injuries URL: %s", self.url)

    def validate_download_data(self) -> None:
        """Verify response is a dict with an 'injuries' key."""
        if not isinstance(self.decoded_data, dict):
            raise ValueError(
                f"Expected JSON dict from ESPN injuries API, got {type(self.decoded_data).__name__}"
            )
        if "injuries" not in self.decoded_data:
            raise ValueError(
                f"Missing 'injuries' key in ESPN response. Keys: {list(self.decoded_data.keys())}"
            )

    def transform_data(self) -> None:
        """Extract relevant fields from each injury entry."""
        raw_injuries = self.decoded_data.get("injuries", [])
        game_date = self.opts["date"]
        scraped_at = datetime.now(timezone.utc).isoformat()

        injuries = []
        for raw in raw_injuries:
            entry = self._parse_injury(raw, game_date, scraped_at)
            if entry:
                injuries.append(entry)

        # Count players flagged GTD vs Out for logging
        gtd_count = sum(1 for i in injuries if i.get("fantasy_status") in ("GTD", "Q"))
        out_count = sum(1 for i in injuries if i.get("fantasy_status") in ("OUT", "O"))

        self.data = {
            "source": "espn",
            "date": game_date,
            "timestamp": scraped_at,
            "injury_count": len(injuries),
            "gtd_count": gtd_count,
            "out_count": out_count,
            "injuries": injuries,
        }

        logger.info(
            "ESPN Injuries: %d players — %d GTD, %d Out for %s",
            len(injuries),
            gtd_count,
            out_count,
            game_date,
        )

        if injuries:
            try:
                notify_info(
                    title="ESPN Injuries Scraped",
                    message=(
                        f"Scraped {len(injuries)} injury entries for {game_date} "
                        f"({gtd_count} GTD, {out_count} Out)"
                    ),
                    details={
                        "injury_count": len(injuries),
                        "gtd_count": gtd_count,
                        "out_count": out_count,
                        "date": game_date,
                    },
                    processor_name=self.__class__.__name__,
                )
            except Exception:
                pass
        else:
            try:
                notify_warning(
                    title="ESPN Injuries: No Entries",
                    message=f"0 injury entries returned for {game_date} (off-season or API issue)",
                    details={"date": game_date, "url": self.url},
                    processor_name=self.__class__.__name__,
                )
            except Exception:
                pass

    def _parse_injury(
        self, raw: dict, game_date: str, scraped_at: str
    ) -> Optional[Dict]:
        """Parse one ESPN injury dict into a flat storage record."""
        try:
            espn_injury_id = raw.get("id")
            if not espn_injury_id:
                return None

            # Athlete info
            athlete = raw.get("athlete") or {}
            player_name = athlete.get("displayName") or (
                f"{athlete.get('firstName', '')} {athlete.get('lastName', '')}".strip()
            )
            if not player_name:
                return None

            # Team name lives on the top-level injury object as displayName
            team_name = raw.get("displayName", "")

            # Top-level status fields
            status = raw.get("status", "")
            reported_at = raw.get("date")  # ISO timestamp string from ESPN

            # Details sub-object — all fields optional
            details = raw.get("details") or {}
            injury_type = details.get("type", "")
            injury_detail = details.get("detail", "")
            injury_side = details.get("side", "")
            return_date_raw = details.get("returnDate")  # "YYYY-MM-DD" or None

            # Fantasy status abbreviation (GTD, OUT, O, Q, etc.)
            fantasy_status_obj = details.get("fantasyStatus") or {}
            fantasy_status = fantasy_status_obj.get("abbreviation", "")

            # Narrative text
            short_comment = raw.get("shortComment", "")
            long_comment = raw.get("longComment", "")

            # Normalise return_date to DATE string (YYYY-MM-DD) if present
            return_date = None
            if return_date_raw:
                # ESPN may return "YYYY-MM-DDT00:00Z" or plain "YYYY-MM-DD"
                try:
                    return_date = return_date_raw[:10]  # Take date portion only
                except Exception:
                    return_date = None

            return {
                "espn_injury_id": str(espn_injury_id),
                "game_date": game_date,
                "scraped_at": scraped_at,
                "player_name": player_name,
                "team_name": team_name,
                "status": status,
                "fantasy_status": fantasy_status,
                "injury_type": injury_type,
                "injury_detail": injury_detail,
                "injury_side": injury_side,
                "short_comment": short_comment,
                "long_comment": long_comment,
                "reported_at": reported_at,
                "return_date": return_date,
            }

        except Exception as e:
            logger.debug(
                "Error parsing ESPN injury entry id=%s: %s", raw.get("id"), e
            )
            return None

    def get_scraper_stats(self) -> dict:
        return {
            "date": self.opts.get("date"),
            "injury_count": self.data.get("injury_count", 0),
            "gtd_count": self.data.get("gtd_count", 0),
            "out_count": self.data.get("out_count", 0),
            "rowCount": self.data.get("injury_count", 0),
        }


# Flask integration
app = convert_existing_flask_scraper(ESPNInjuriesScraper)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ESPN NBA Injuries Scraper")
    parser.add_argument("--date", required=True, help="Game date (YYYY-MM-DD)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--group", default="dev",
                        help="Exporter group: dev|prod|capture (default: dev)")
    parser.add_argument("--serve", action="store_true", help="Start Flask server")

    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    if args.serve:
        app.run(host="0.0.0.0", port=8080, debug=True)
    else:
        scraper = ESPNInjuriesScraper()
        scraper.run(opts={
            "date": args.date,
            "group": args.group,
        })
