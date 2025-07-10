"""
odds_api_historical_event_odds.py
Scraper for The-Odds-API v4 “historical event odds” endpoint.

Docs:
  https://the-odds-api.com/liveapi/guides/v4/#get-historical-event-odds

# Activate your venv and ensure ODDS_API_KEY is exported (or in .env)
    python -m scrapers.oddsapi.odds_api_historical_event_odds \
        --sport=basketball_nba \
        --eventId=6f0b6f8d8cc9c5bc6375cdee \
        --date=2025-06-10T00:00:00Z \
        --regions=us \
        --markets=player_points,player_assists \
        --group=dev --debug
"""

from __future__ import annotations

import os
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from typing import Any, Dict, List
from flask import Flask, request, jsonify

from scrapers.scraper_base import ScraperBase, ExportMode
from scrapers.utils.exceptions import DownloadDataException

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
# Scraper                                                                     #
# --------------------------------------------------------------------------- #
class GetOddsApiHistoricalEventOdds(ScraperBase):
    """
    Required opts:
      • sport      - e.g. basketball_nba
      • eventId    - e.g. 6f0b6f8d8cc9…
      • date       - snapshot timestamp (ISO-8601)
      • regions    - comma-separated list (us, uk, eu, au)
      • markets    - comma-separated list (player_points, player_assists, …)

    Optional:
      • oddsFormat  - american | decimal | fractional
      • dateFormat  - iso | unix
      • apiKey      - if omitted, pulled from env `ODDS_API_KEY`
    """

    # required_opts = ["sport", "eventId", "date", "regions", "markets"]
    required_opts = ["eventId", "date"]

    proxy_enabled = False
    browser_enabled = False

    # ------------------------------------------------------------------ #
    # Exporters                                                          #
    # ------------------------------------------------------------------ #
    exporters = [
        {   # RAW payload for prod / GCS archival
            "type": "gcs",
            "key": "oddsapi/historical-event-odds/%(sport)s/%(eventId)s_%(date)s.raw.json",
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
        },
        {   # Pretty JSON for dev & capture
            "type": "file",
            "filename": "/tmp/oddsapi_hist_event_odds_%(sport)s_%(eventId)s.json",
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
        # Snap to valid snapshot boundary
        self.opts["date"] = snap_iso_ts_to_five_minutes(self.opts["date"])
        # ── season‑wide defaults ──────────────────────────────
        self.opts.setdefault("sport", "basketball_nba")
        self.opts.setdefault("regions", "us")
        self.opts.setdefault("markets", "player_points")
        self.opts.setdefault("bookmakers", "draftkings,fanduel")

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT_TMPL = (
        "https://api.the-odds-api.com/v4/historical/sports/"
        "{sport}/events/{eventId}/odds"
    )

    def set_url(self) -> None:
        api_key = self.opts.get("apiKey") or os.getenv("ODDS_API_KEY")
        if not api_key:
            raise DownloadDataException(
                "Missing apiKey and env var ODDS_API_KEY not set."
            )

        base = self._API_ROOT_TMPL.format(
            sport=self.opts["sport"],
            eventId=self.opts["eventId"],
        )

        query: Dict[str, Any] = {
            "apiKey": api_key,
            "date": self.opts["date"],
            "regions": self.opts["regions"],
            "markets": self.opts["markets"],
            "bookmakers": self.opts["bookmakers"],
            "oddsFormat": self.opts.get("oddsFormat"),
            "dateFormat": self.opts.get("dateFormat"),
        }
        query = {k: v for k, v in query.items() if v is not None}
        self.url = f"{base}?{urlencode(query, doseq=True)}"
        logger.info("Odds-API Historical Event Odds URL: %s", self.url)

    def set_headers(self) -> None:
        self.headers = {"Accept": "application/json"}

    # ------------------------------------------------------------------ #
    # HTTP status handling                                               #
    # ------------------------------------------------------------------ #
    def check_download_status(self) -> None:
        """
        200 and 204 are “okay” for this endpoint.
        """
        if self.raw_response.status_code in (200, 204):
            return
        super().check_download_status()

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        """
        Expect wrapper dict with 'data' object.
        """
        if isinstance(self.decoded_data, dict) and "message" in self.decoded_data:
            raise DownloadDataException(f"API error: {self.decoded_data['message']}")

        if not (isinstance(self.decoded_data, dict) and "data" in self.decoded_data):
            raise DownloadDataException("Expected dict with 'data' key.")

    # ------------------------------------------------------------------ #
    # Transform                                                          #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        wrapper: Dict[str, Any] = self.decoded_data  # type: ignore[assignment]
        event_odds: Dict[str, Any] = wrapper.get("data", {})

        # Count distinct bookmaker × market entries
        row_count = 0
        for bm in event_odds.get("bookmakers", []):
            for mk in bm.get("markets", []):
                row_count += len(mk.get("outcomes", [])) or 1

        self.data = {
            "sport": self.opts["sport"],
            "eventId": self.opts["eventId"],
            "snapshot_timestamp": wrapper.get("timestamp"),
            "previous_snapshot": wrapper.get("previous_timestamp"),
            "next_snapshot": wrapper.get("next_timestamp"),
            "regions": self.opts["regions"],
            "markets": self.opts["markets"],
            "rowCount": row_count,
            "eventOdds": event_odds,
        }
        logger.info(
            "Fetched %d bookmaker-market rows for event %s", row_count, self.opts["eventId"]
        )

    # ------------------------------------------------------------------ #
    # Conditional save                                                   #
    # ------------------------------------------------------------------ #
    def should_save_data(self) -> bool:
        return bool(self.data.get("rowCount"))

    # ------------------------------------------------------------------ #
    # Stats line                                                         #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {
            "rowCount": self.data.get("rowCount", 0),
            "sport": self.opts.get("sport"),
            "eventId": self.opts.get("eventId"),
            "markets": self.opts.get("markets"),
            "regions": self.opts.get("regions"),
            "snapshot": self.data.get("snapshot_timestamp"),
        }


# --------------------------------------------------------------------------- #
# Cloud Run / Flask entry point for Player Props Scraper                     #
# --------------------------------------------------------------------------- #
def create_app():
    """Create Flask app for Player Props Scraper."""
    from dotenv import load_dotenv
    import sys
    
    app = Flask(__name__)
    load_dotenv()
    
    # Configure logging for Cloud Run
    if not app.debug:
        logging.basicConfig(level=logging.INFO)
    
    @app.route('/', methods=['GET'])
    @app.route('/health', methods=['GET'])
    def health_check():
        return jsonify({
            "status": "healthy", 
            "service": "scrapers",
            "scraper": "odds_api_historical_event_odds",
            "version": "1.0.0",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }), 200
    
    @app.route('/scrape', methods=['POST'])
    def scrape_player_props():
        """Scrape historical NBA player prop odds"""
        try:
            # Get parameters from JSON body or query params
            if request.is_json:
                params = request.get_json()
            else:
                params = request.args.to_dict()
            
            # Player props scraper specific parameters
            opts = {
                "apiKey": params.get("apiKey"),  # Falls back to env var
                "sport": params.get("sport", "basketball_nba"),
                "eventId": params.get("eventId"),  # REQUIRED
                "date": params.get("date"),  # REQUIRED
                "regions": params.get("regions", "us"),
                "markets": params.get("markets", "player_points"),
                "bookmakers": params.get("bookmakers", "draftkings,fanduel"),
                "oddsFormat": params.get("oddsFormat"),
                "dateFormat": params.get("dateFormat"),
                "group": params.get("group", "prod"),
                "runId": params.get("runId"),
                "debug": bool(params.get("debug", False))
            }
            
            # Validate required params for player props scraper
            if not opts["date"]:
                return jsonify({"error": "Missing required parameter: date"}), 400
            if not opts["eventId"]:
                return jsonify({"error": "Missing required parameter: eventId"}), 400
            
            # Set debug logging
            if opts["debug"]:
                logging.getLogger().setLevel(logging.DEBUG)
            
            # Run the player props scraper
            scraper = GetOddsApiHistoricalEventOdds()
            result = scraper.run(opts)
            
            if result:
                return jsonify({
                    "status": "success",
                    "message": "Player props scraping completed successfully",
                    "scraper": "odds_api_historical_event_odds",
                    "run_id": scraper.run_id,
                    "data_summary": scraper.get_scraper_stats()
                }), 200
            else:
                return jsonify({
                    "status": "error",
                    "message": "Player props scraping failed",
                    "scraper": "odds_api_historical_event_odds",
                    "run_id": scraper.run_id
                }), 500
                
        except Exception as e:
            app.logger.error(f"Player props scraper error: {str(e)}", exc_info=True)
            return jsonify({
                "status": "error",
                "scraper": "odds_api_historical_event_odds",
                "message": str(e)
            }), 500
    
    return app


# --------------------------------------------------------------------------- #
# Main entry point for Player Props Scraper                                   #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv
    import sys
    
    load_dotenv()

    # Check if we're running as a web service or CLI
    if len(sys.argv) > 1 and sys.argv[1] == "--serve":
        # Web service mode for Cloud Run
        app = create_app()
        port = int(os.getenv("PORT", 8080))
        debug = "--debug" in sys.argv
        app.run(host="0.0.0.0", port=port, debug=debug)
    else:
        # CLI mode (existing argparse code)
        parser = argparse.ArgumentParser(description="Scrape The-Odds-API historical player props")
        parser.add_argument("--serve", action="store_true", help="Start web server")
        parser.add_argument("--apiKey", help="Optional - env ODDS_API_KEY fallback")
        parser.add_argument("--sport", default="basketball_nba", help="e.g. basketball_nba")
        parser.add_argument("--eventId", help="Event ID (required for CLI)")
        parser.add_argument("--date", help="ISO timestamp (required for CLI)")
        parser.add_argument("--regions", default="us")
        parser.add_argument("--markets", default="player_points")
        parser.add_argument("--bookmakers", default="draftkings,fanduel")
        parser.add_argument("--oddsFormat", choices=["american", "decimal", "fractional"])
        parser.add_argument("--dateFormat", choices=["iso", "unix"])
        parser.add_argument("--debug", action="store_true", help="Verbose logging")
        parser.add_argument("--group", default="dev", help="exporter group")
        parser.add_argument("--runId", help="Optional correlation ID")
        
        args = parser.parse_args()
        
        if args.serve:
            # Start web server
            app = create_app()
            port = int(os.getenv("PORT", 8080))
            app.run(host="0.0.0.0", port=port, debug=args.debug)
        else:
            # CLI scraping mode
            if not args.date:
                parser.error("--date is required for CLI scraping")
            if not args.eventId:
                parser.error("--eventId is required for CLI scraping")
                
            if args.debug:
                logging.getLogger().setLevel(logging.DEBUG)
                
            # Run the player props scraper
            scraper = GetOddsApiHistoricalEventOdds()
            scraper.run(vars(args))
