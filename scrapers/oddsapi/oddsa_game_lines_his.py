"""
odds_api_historical_game_lines.py
Scraper for The-Odds-API v4 "historical event odds" endpoint for NBA game lines (spreads/totals).

Docs:
  https://the-odds-api.com/liveapi/guides/v4/#get-historical-event-odds

Usage examples
--------------
  # Via capture tool (recommended for data collection):
  python tools/fixtures/capture.py oddsa_game_lines_his \
      --event_id cd0bc7d0c238f4446ce1c03d0cea7ec4 \
      --game_date 2024-01-25 \
      --snapshot_timestamp 2024-01-25T04:00:00Z \
      --markets spreads,totals \
      --debug

  # Direct CLI execution:
  python scrapers/oddsapi/oddsa_game_lines_his.py \
      --event_id cd0bc7d0c238f4446ce1c03d0cea7ec4 \
      --game_date 2024-01-25 \
      --snapshot_timestamp 2024-01-25T04:00:00Z \
      --markets spreads,totals \
      --debug

  # Flask web service:
  python scrapers/oddsapi/oddsa_game_lines_his.py --serve --debug

  CRITICAL TIMING CONSTRAINT FOR HISTORICAL ODDS:
  Events disappear from the API when games start or shortly before. If your 
  snapshot_timestamp is too far after the event was available, you'll get 404 errors.

  WORKFLOW TO AVOID 404s:
  1. First run oddsa_events_his to discover available events and their timestamps
  2. Use the SAME or slightly LATER timestamp for odds requests
  3. DO NOT use timestamps hours later in the day

  EXAMPLE OF WHAT CAUSES 404s:
  ✗ Events found at: 2024-01-25T03:55:40Z (3:55 AM UTC)
  ✗ Odds requested at: 2024-01-25T14:00:00Z (2:00 PM UTC) → 404 ERROR
  
  CORRECT APPROACH:
  ✓ Events found at: 2024-01-25T03:55:40Z (3:55 AM UTC)  
  ✓ Odds requested at: 2024-01-25T04:00:00Z (4:00 AM UTC) → SUCCESS

  SAFE TIMING WINDOWS:
  • Early morning (04:00-10:00 UTC): Opening lines available
  • Afternoon (14:00-18:00 UTC): Updated lines (may work if events still listed)
  • Evening (20:00+ UTC): Final lines (risky - events may have started)

  NBA games typically start 23:00-02:00 UTC (evening US time), so events 
  disappear around game time. Always test with events scraper first!
"""

from __future__ import annotations

import os
import logging
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from typing import Any, Dict, List

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.oddsapi.oddsa_game_lines_his
    from ..scraper_base import ScraperBase, ExportMode
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.exceptions import DownloadDataException
    from ..utils.gcs_path_builder import GCSPathBuilder
    from ..utils.nba_team_mapper import build_event_teams_suffix
except ImportError:
    # Direct execution: python scrapers/oddsapi/oddsa_game_lines_his.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import ScraperBase, ExportMode
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.exceptions import DownloadDataException
    from scrapers.utils.gcs_path_builder import GCSPathBuilder
    from scrapers.utils.nba_team_mapper import build_event_teams_suffix

# Notification system imports
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

# Authentication utilities
from shared.utils.auth_utils import get_api_key

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Helper - snap ISO timestamp to previous 5-minute boundary                   #
# --------------------------------------------------------------------------- #
def snap_iso_ts_to_five_minutes(iso_ts: str) -> str:
    """
    '2025-06-10T22:43:17Z'  ->  '2025-06-10T22:40:00Z'
    """
    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    floored = dt - timedelta(minutes=dt.minute % 5,
                             seconds=dt.second,
                             microseconds=dt.microsecond)
    return (floored.replace(tzinfo=timezone.utc)
                   .isoformat(timespec="seconds")
                   .replace("+00:00", "Z"))


# --------------------------------------------------------------------------- #
# Scraper (USING MIXIN)
# --------------------------------------------------------------------------- #
class GetOddsApiHistoricalGameLines(ScraperBase, ScraperFlaskMixin):
    """
    Required opts:
      • event_id           - e.g. 6f0b6f8d8cc9c5bc6375cdee
      • game_date          - Eastern date for GCS directory (e.g., "2024-04-10")
      • snapshot_timestamp - UTC timestamp for API snapshot (e.g., "2024-04-11T04:00:00Z")

    Optional opts:
      • sport      - e.g. basketball_nba (defaults to basketball_nba)
      • regions    - comma-separated list (us, uk, eu, au) (defaults to us)
      • markets    - comma-separated list (spreads, totals) (defaults to spreads,totals)
      • bookmakers - comma-separated list (defaults to draftkings,fanduel)
      • oddsFormat  - american | decimal | fractional
      • dateFormat  - iso | unix
      • api_key      - if omitted, pulled from env `ODDS_API_KEY`
      • teams       - team suffix (e.g., LALDET) - if provided, skips team extraction
    """

    # Flask Mixin Configuration
    scraper_name = "oddsa_game_lines_his"
    required_params = ["event_id", "game_date", "snapshot_timestamp"]
    optional_params = {
        "api_key": None,  # Falls back to env ODDS_API_KEY
        "sport": None,  # Defaults to basketball_nba in set_additional_opts
        "regions": None,  # Defaults to us in set_additional_opts
        "markets": None,  # Defaults to spreads,totals in set_additional_opts
        "bookmakers": None,  # Defaults to draftkings,fanduel in set_additional_opts
        "oddsFormat": None,
        "dateFormat": None,
        "teams": None,  # Team suffix for GCS path (optional)
    }

    required_opts = ["event_id", "game_date", "snapshot_timestamp"]
    proxy_enabled = False
    browser_enabled = False

    # ------------------------------------------------------------------ #
    # Exporters                                                          #
    # ------------------------------------------------------------------ #
    GCS_PATH_KEY = "odds_api_game_lines_history"
    exporters = [
        {   # RAW payload for prod / GCS archival
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
            "check_should_save": True,  # Enable conditional save
        },
        {   # Pretty JSON for dev & capture
            "type": "file",
            "filename": "/tmp/oddsapi_hist_game_lines_%(sport)s_%(event_id)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev", "test"],
        },
        # Capture RAW + EXP
        {
            "type": "file",
            "filename": "/tmp/raw_%(run_id)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
        {
            "type": "file",
            "filename": "/tmp/exp_%(run_id)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DECODED,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # Additional opts                                                    #
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        super().set_additional_opts()  # Base class handles game_date → date conversion
        
        # Snap timestamp to valid 5-minute boundary for API
        if self.opts.get("snapshot_timestamp"):
            original_timestamp = self.opts["snapshot_timestamp"]
            self.opts["snapshot_timestamp"] = snap_iso_ts_to_five_minutes(original_timestamp)
            if original_timestamp != self.opts["snapshot_timestamp"]:
                logger.debug("Snapped timestamp %s → %s", original_timestamp, self.opts["snapshot_timestamp"])
        
        # Extract snap time for filename (moved from transform_data for early availability)
        if self.opts.get("snapshot_timestamp"):
            snapshot_time = self.opts["snapshot_timestamp"]  # "2024-04-11T04:00:00Z"
            time_part = snapshot_time.split('T')[1]          # "04:00:00Z"
            snap_hour = time_part[:2] + time_part[3:5]       # "04" + "00" = "0400"
            self.opts["snap"] = snap_hour                    # For GCS path template
            logger.debug("Extracted snap time for filename: %s", snap_hour)
        
        # ── season‑wide defaults for game lines (spreads & totals) ──────────────────────
        if not self.opts.get("sport"):
            self.opts["sport"] = "basketball_nba"
        if not self.opts.get("regions"):
            self.opts["regions"] = "us"
        if not self.opts.get("markets"):
            self.opts["markets"] = "spreads,totals"  # Default to both spreads and totals
        if not self.opts.get("bookmakers"):
            self.opts["bookmakers"] = "draftkings,fanduel,betmgm,williamhill_us,betrivers,bovada,espnbet,hardrockbet,betonlineag,fliff,betparx,ballybet"

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT_TMPL = (
        "https://api.the-odds-api.com/v4/historical/sports/"
        "{sport}/events/{eventId}/odds"
    )

    def set_url(self) -> None:
        # Get API key from Secret Manager (with env var fallback for local dev)
        api_key = get_api_key(
            secret_name='ODDS_API_KEY',
            default_env_var='ODDS_API_KEY'
        )
        if not api_key:
            error_msg = "Missing api_key and env var ODDS_API_KEY not set."
            
            # Send critical notification - API key missing prevents all scraping
            try:
                notify_error(
                    title="Odds API Key Missing",
                    message="Cannot scrape historical game lines - API key not configured",
                    details={
                        'scraper': 'oddsa_game_lines_his',
                        'event_id': self.opts.get('event_id', 'unknown'),
                        'game_date': self.opts.get('game_date', 'unknown'),
                        'snapshot_timestamp': self.opts.get('snapshot_timestamp', 'unknown'),
                        'error': 'ODDS_API_KEY environment variable not set'
                    },
                    processor_name="Odds API Historical Game Lines Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise DownloadDataException(error_msg)

        base = self._API_ROOT_TMPL.format(
            sport=self.opts["sport"],
            eventId=self.opts["event_id"],
        )

        query: Dict[str, Any] = {
            "apiKey": api_key,
            "date": self.opts["snapshot_timestamp"],  # Use snapshot_timestamp for API
            "regions": self.opts["regions"],
            "markets": self.opts["markets"],
            "bookmakers": self.opts["bookmakers"],
            "oddsFormat": self.opts.get("oddsFormat"),
            "dateFormat": self.opts.get("dateFormat"),
        }
        query = {k: v for k, v in query.items() if v is not None}
        self.url = f"{base}?{urlencode(query, doseq=True)}"
        logger.info("Odds-API Historical Game Lines URL: %s", self.url.replace(api_key, "***"))

    def set_headers(self) -> None:
        self.headers = {"Accept": "application/json"}

    # ------------------------------------------------------------------ #
    # HTTP status handling                                               #
    # ------------------------------------------------------------------ #
    def check_download_status(self) -> None:
        """
        200 and 204 are "okay" for this endpoint.
        204 means no odds data available for that snapshot.
        """
        if self.raw_response.status_code in (200, 204):
            # 204 is expected for empty snapshots, just log it
            if self.raw_response.status_code == 204:
                logger.info("204 response - no game lines data at snapshot %s", 
                           self.opts.get("snapshot_timestamp"))
            return
        
        # Special handling for 404 - common in historical data due to timing
        if self.raw_response.status_code == 404:
            try:
                notify_warning(
                    title="Historical Game Lines Not Found (404)",
                    message="Event not found at snapshot timestamp - may have already started or timing issue",
                    details={
                        'scraper': 'oddsa_game_lines_his',
                        'event_id': self.opts.get('event_id', 'unknown'),
                        'game_date': self.opts.get('game_date', 'unknown'),
                        'snapshot_timestamp': self.opts.get('snapshot_timestamp', 'unknown'),
                        'markets': self.opts.get('markets', 'spreads,totals'),
                        'status_code': 404,
                        'note': 'Events disappear when games start. Use earlier timestamp or check event availability first.'
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
        else:
            # Other error status codes
            status_code = self.raw_response.status_code
            try:
                notify_error(
                    title="Odds API HTTP Error",
                    message=f"Historical game lines scraping failed with HTTP {status_code}",
                    details={
                        'scraper': 'oddsa_game_lines_his',
                        'event_id': self.opts.get('event_id', 'unknown'),
                        'game_date': self.opts.get('game_date', 'unknown'),
                        'snapshot_timestamp': self.opts.get('snapshot_timestamp', 'unknown'),
                        'markets': self.opts.get('markets', 'spreads,totals'),
                        'status_code': status_code,
                        'response_text': self.raw_response.text[:500] if hasattr(self.raw_response, 'text') else 'N/A'
                    },
                    processor_name="Odds API Historical Game Lines Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
        
        super().check_download_status()

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        """
        Expect wrapper dict with 'data' object.
        Handle 204 (empty) responses gracefully.
        """
        # Handle 204 responses (empty snapshot)
        if self.raw_response.status_code == 204:
            logger.info("204 response - no game lines data available for snapshot %s", 
                       self.opts.get("snapshot_timestamp"))
            # Create empty response structure for consistency
            self.decoded_data = {
                "data": {},
                "timestamp": self.opts.get("snapshot_timestamp"),
                "message": "No game lines data available for this snapshot"
            }
            
            # Send info notification for 204 (expected but worth tracking)
            try:
                notify_info(
                    title="Empty Historical Snapshot (204)",
                    message="No game lines data available at this snapshot",
                    details={
                        'scraper': 'oddsa_game_lines_his',
                        'event_id': self.opts.get('event_id', 'unknown'),
                        'game_date': self.opts.get('game_date', 'unknown'),
                        'snapshot_timestamp': self.opts.get('snapshot_timestamp', 'unknown'),
                        'markets': self.opts.get('markets', 'spreads,totals'),
                        'status_code': 204,
                        'note': 'May indicate lines not yet available or already removed'
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            return

        if isinstance(self.decoded_data, dict) and "message" in self.decoded_data:
            error_msg = self.decoded_data['message']
            
            # API returned an error message
            try:
                notify_error(
                    title="Odds API Error Response",
                    message=f"Historical game lines API returned error: {error_msg}",
                    details={
                        'scraper': 'oddsa_game_lines_his',
                        'event_id': self.opts.get('event_id', 'unknown'),
                        'game_date': self.opts.get('game_date', 'unknown'),
                        'snapshot_timestamp': self.opts.get('snapshot_timestamp', 'unknown'),
                        'markets': self.opts.get('markets', 'spreads,totals'),
                        'api_error': error_msg
                    },
                    processor_name="Odds API Historical Game Lines Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise DownloadDataException(f"API error: {error_msg}")

        if not (isinstance(self.decoded_data, dict) and "data" in self.decoded_data):
            # Unexpected data format
            try:
                notify_error(
                    title="Odds API Invalid Response Format",
                    message="Historical game lines API returned unexpected data format",
                    details={
                        'scraper': 'oddsa_game_lines_his',
                        'event_id': self.opts.get('event_id', 'unknown'),
                        'game_date': self.opts.get('game_date', 'unknown'),
                        'snapshot_timestamp': self.opts.get('snapshot_timestamp', 'unknown'),
                        'markets': self.opts.get('markets', 'spreads,totals'),
                        'received_type': type(self.decoded_data).__name__,
                        'has_data_key': 'data' in self.decoded_data if isinstance(self.decoded_data, dict) else False
                    },
                    processor_name="Odds API Historical Game Lines Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise DownloadDataException("Expected dict with 'data' key.")

    # ------------------------------------------------------------------ #
    # Transform                                                          #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        wrapper: Dict[str, Any] = self.decoded_data  # type: ignore[assignment]
        event_odds: Dict[str, Any] = wrapper.get("data", {})

        # Count distinct bookmaker × market entries for game lines
        row_count = 0
        spreads_count = 0
        totals_count = 0
        
        for bm in event_odds.get("bookmakers", []):
            for mk in bm.get("markets", []):
                market_key = mk.get("key", "")
                outcome_count = len(mk.get("outcomes", [])) or 1
                row_count += outcome_count
                
                if market_key == "spreads":
                    spreads_count += outcome_count
                elif market_key == "totals":
                    totals_count += outcome_count

        # Extract team information and build teams suffix for GCS path
        teams_suffix = self._extract_teams_suffix(event_odds)
        if teams_suffix:
            self.opts["teams"] = teams_suffix
            logger.debug("Built teams suffix for GCS path: %s", teams_suffix)
        else:
            # Warning: Could not extract team data (affects GCS path)
            try:
                notify_warning(
                    title="Missing Team Data in Historical Game Lines",
                    message="Could not extract team information from historical game lines response",
                    details={
                        'scraper': 'oddsa_game_lines_his',
                        'event_id': self.opts.get('event_id', 'unknown'),
                        'game_date': self.opts.get('game_date', 'unknown'),
                        'snapshot_timestamp': self.opts.get('snapshot_timestamp', 'unknown'),
                        'markets': self.opts.get('markets', 'spreads,totals'),
                        'impact': 'GCS path will not include team suffix',
                        'available_keys': list(event_odds.keys()) if event_odds else []
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")

        # Snap time should already be extracted in set_additional_opts()
        # If not already set, extract it here as fallback
        if not self.opts.get("snap") and self.opts.get("snapshot_timestamp"):
            snapshot_time = self.opts["snapshot_timestamp"]  # "2024-04-11T04:00:00Z"
            time_part = snapshot_time.split('T')[1]          # "04:00:00Z"
            snap_hour = time_part[:2] + time_part[3:5]       # "04" + "00" = "0400"
            self.opts["snap"] = snap_hour                    # For GCS path template
            logger.debug("Extracted snap time for filename (fallback): %s", snap_hour)

        self.data = {
            "sport": self.opts["sport"],
            "eventId": self.opts["event_id"],
            "snapshot_timestamp": wrapper.get("timestamp"),
            "previous_snapshot": wrapper.get("previous_timestamp"),
            "next_snapshot": wrapper.get("next_timestamp"),
            "regions": self.opts["regions"],
            "markets": self.opts["markets"],
            "rowCount": row_count,
            "spreadsCount": spreads_count,
            "totalsCount": totals_count,
            "eventOdds": event_odds,
        }
        
        # Check for no lines in successful response
        if row_count == 0 and self.raw_response.status_code == 200:
            try:
                notify_warning(
                    title="No Historical Game Lines in Snapshot",
                    message="Historical snapshot returned successfully but contains zero game lines",
                    details={
                        'scraper': 'oddsa_game_lines_his',
                        'event_id': self.opts.get('event_id', 'unknown'),
                        'game_date': self.opts.get('game_date', 'unknown'),
                        'snapshot_timestamp': self.opts.get('snapshot_timestamp', 'unknown'),
                        'markets': self.opts.get('markets', 'spreads,totals'),
                        'teams': teams_suffix or 'unknown',
                        'bookmakers_count': len(event_odds.get("bookmakers", [])),
                        'note': 'Lines may not have been available at this timestamp'
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
        elif row_count > 0:
            # Check for missing specific markets (if requested spreads but got 0, or totals but got 0)
            requested_markets = self.opts.get('markets', 'spreads,totals').split(',')
            missing_markets = []
            
            if 'spreads' in requested_markets and spreads_count == 0:
                missing_markets.append('spreads')
            if 'totals' in requested_markets and totals_count == 0:
                missing_markets.append('totals')
            
            if missing_markets:
                try:
                    notify_warning(
                        title="Missing Historical Game Line Markets",
                        message=f"Requested markets returned zero outcomes: {', '.join(missing_markets)}",
                        details={
                            'scraper': 'oddsa_game_lines_his',
                            'event_id': self.opts.get('event_id', 'unknown'),
                            'game_date': self.opts.get('game_date', 'unknown'),
                            'snapshot_timestamp': wrapper.get('timestamp', self.opts.get('snapshot_timestamp', 'unknown')),
                            'requested_markets': requested_markets,
                            'missing_markets': missing_markets,
                            'spreads_count': spreads_count,
                            'totals_count': totals_count,
                            'total_rows': row_count,
                            'teams': teams_suffix or 'unknown'
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
            
            # Success! Send info notification with metrics
            try:
                notify_info(
                    title="Historical Game Lines Scraped Successfully",
                    message=f"Retrieved {row_count} historical game line outcomes ({spreads_count} spreads, {totals_count} totals)",
                    details={
                        'scraper': 'oddsa_game_lines_his',
                        'event_id': self.opts.get('event_id', 'unknown'),
                        'game_date': self.opts.get('game_date', 'unknown'),
                        'snapshot_timestamp': wrapper.get('timestamp', self.opts.get('snapshot_timestamp', 'unknown')),
                        'markets': self.opts.get('markets', 'spreads,totals'),
                        'regions': self.opts.get('regions', 'us'),
                        'bookmakers': self.opts.get('bookmakers', 'draftkings,fanduel'),
                        'row_count': row_count,
                        'spreads_count': spreads_count,
                        'totals_count': totals_count,
                        'bookmakers_count': len(event_odds.get("bookmakers", [])),
                        'teams': teams_suffix or 'unknown',
                        'snap_time': self.opts.get('snap', 'unknown'),
                        'previous_snapshot': wrapper.get('previous_timestamp'),
                        'next_snapshot': wrapper.get('next_timestamp')
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
        
        logger.info(
            "Fetched %d game lines rows (%d spreads, %d totals) for event %s", 
            row_count, spreads_count, totals_count, self.opts["event_id"][:12] + "..."
        )

    def _extract_teams_suffix(self, event_odds: Dict[str, Any]) -> str:
        """
        Extract team information from event odds data and build teams suffix.
        
        The historical event odds endpoint returns event data including team names.
        We use this to build the teams suffix for enhanced GCS paths.
        
        Args:
            event_odds: Event odds data from API response
            
        Returns:
            Teams suffix (e.g., "LALDET") or empty string if teams not found
        """
        # Check if teams suffix was provided directly (from job/external source)
        if self.opts.get("teams"):
            logger.debug("Using provided teams suffix: %s", self.opts["teams"])
            return self.opts["teams"]
        
        try:
            # The API response includes the event data with team information
            # Look for team names in the event data
            away_team = event_odds.get("away_team", "")
            home_team = event_odds.get("home_team", "")
            
            # If not found in top level, check if there's an event object
            if not away_team or not home_team:
                event_info = event_odds.get("event", {})
                away_team = event_info.get("away_team", "")
                home_team = event_info.get("home_team", "")
            
            # If still not found, try common alternate field names
            if not away_team or not home_team:
                away_team = (event_odds.get("awayTeam") or 
                           event_odds.get("away") or 
                           event_odds.get("visitor_team", ""))
                home_team = (event_odds.get("homeTeam") or 
                           event_odds.get("home") or 
                           event_odds.get("home_team", ""))
            
            if away_team and home_team:
                # Build teams suffix using the utility
                teams_suffix = build_event_teams_suffix({
                    "away_team": away_team,
                    "home_team": home_team
                })
                logger.debug("Extracted teams from API response: %s @ %s -> %s", 
                           away_team, home_team, teams_suffix)
                return teams_suffix
            else:
                logger.warning("Could not extract team information from event odds data for event %s", 
                             self.opts.get("event_id", "unknown")[:12] + "...")
                logger.debug("Event odds keys: %s", list(event_odds.keys()))
                return ""
                
        except Exception as e:
            logger.warning("Error extracting teams suffix for event %s: %s", 
                         self.opts.get("event_id", "unknown")[:12] + "...", e)
            return ""

    # ------------------------------------------------------------------ #
    # Conditional save                                                   #
    # ------------------------------------------------------------------ #
    def should_save_data(self) -> bool:
        """
        Only save if we have meaningful data.
        Skip empty 204 responses to avoid cluttering GCS.
        """
        # For 204 responses, don't save empty data
        if self.raw_response and self.raw_response.status_code == 204:
            logger.info("Skipping save for 204 empty response")
            return False
            
        # Save if we have any rows of data
        return bool(self.data.get("rowCount", 0) > 0)

    # ------------------------------------------------------------------ #
    # Stats line                                                         #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {
            "rowCount": self.data.get("rowCount", 0),
            "spreadsCount": self.data.get("spreadsCount", 0),
            "totalsCount": self.data.get("totalsCount", 0),
            "sport": self.opts.get("sport"),
            "eventId": self.opts.get("event_id", "")[:12] + "..." if self.opts.get("event_id") else "",
            "markets": self.opts.get("markets"),
            "regions": self.opts.get("regions"),
            "snapshot": self.data.get("snapshot_timestamp"),
            "teams": self.opts.get("teams", ""),  # Include teams suffix in stats
            "snap": self.opts.get("snap", ""),    # Include snap time in stats
            "status_code": self.raw_response.status_code if self.raw_response else "unknown",
        }


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(GetOddsApiHistoricalGameLines)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = GetOddsApiHistoricalGameLines.create_cli_and_flask_main()
    main()