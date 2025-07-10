"""
odds_api_historical_events.py
Scraper for The-Odds-API v4 “historical events” endpoint.

Endpoint:
  GET /v4/historical/sports/{sport}/events
Docs:
  https://the-odds-api.com/liveapi/guides/v4/#get-historical-events

python tools/fixtures/capture.py oddsa_events_his \
    --sport basketball_nba \
    --date 2025-03-10T00:00:00Z \
    --debug
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from typing import Any, Dict, List
from flask import Flask, request, jsonify

from ..scraper_base import ScraperBase, ExportMode
from ..utils.exceptions import DownloadDataException

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Helper - snap any datetime string to the previous 5-minute boundary
# (Avoids burning quota on unsupported :01, :02, … timestamps.)
# --------------------------------------------------------------------------- #
def snap_iso_ts_to_five_minutes(iso: str) -> str:
    """
    >>> snap_iso_ts_to_five_minutes("2025-06-10T22:43:17Z")
    '2025-06-10T22:40:00Z'
    """
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    floored = dt - timedelta(minutes=dt.minute % 5,
                             seconds=dt.second,
                             microseconds=dt.microsecond)
    return floored.replace(tzinfo=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# --------------------------------------------------------------------------- #
# Scraper                                                                     #
# --------------------------------------------------------------------------- #
class GetOddsApiHistoricalEvents(ScraperBase):
    """
    Required opts:
      • apiKey - your Odds-API key
      • sport  - e.g. basketball_nba
      • date   - ISO-8601 timestamp to snap (The-Odds snapshots are every 5 min)

    Optional opts:
      • commenceTimeFrom / commenceTimeTo - ISO filters on event commence_time
      • eventIds  - comma-sep or list[str]
      • dateFormat - 'iso' (default) or 'unix'
    """

    # required_opts = ["apiKey", "sport", "date"]
    required_opts = ["sport", "date"]

    # Odds-API responds quickly and is not Cloudflare-protected
    proxy_enabled = False
    browser_enabled = False

    # ------------------------------------------------------------------ #
    # Exporters                                                          #
    # ------------------------------------------------------------------ #
    exporters = [
        # RAW ⇒ good for archival / debugging on prod or GCS
        {
            "type": "gcs",
            "key": "oddsapi/historical-events/%(date)s_%(run_id)s.raw.json",
            "export_mode": ExportMode.RAW,
            "groups": ["prod", "gcs"],
        },
        # Pretty JSON for local dev or fixture capture
        {
            "type": "file",
            "filename": "/tmp/oddsapi_hist_events_%(date)s.json",
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
        """
        Round the supplied timestamp down to the nearest 5-minute snapshot
        (doc: snapshots are 5 min granularity after 2022-09-18).
        """
        if self.opts.get("date"):
            self.opts["date"] = snap_iso_ts_to_five_minutes(self.opts["date"])

    # ------------------------------------------------------------------ #
    # URL & headers                                                      #
    # ------------------------------------------------------------------ #
    _API_ROOT_TMPL = "https://api.the-odds-api.com/v4/historical/sports/{sport}/events"

    def set_url(self) -> None:
        base = self._API_ROOT_TMPL.format(sport=self.opts["sport"])

        api_key = self.opts.get("apiKey") or os.getenv("ODDS_API_KEY")
        if not api_key:
            raise DownloadDataException("Missing apiKey and no ODDS_API_KEY env var found.")

        query: Dict[str, Any] = {
            "apiKey": api_key,
            "date": self.opts["date"],
            "commenceTimeFrom": self.opts.get("commenceTimeFrom"),
            "commenceTimeTo": self.opts.get("commenceTimeTo"),
            "eventIds": self.opts.get("eventIds"),
            "dateFormat": self.opts.get("dateFormat"),
        }
        # scrub None values
        query = {k: v for k, v in query.items() if v is not None}
        self.url = f"{base}?{urlencode(query, doseq=True)}"
        logger.info("Odds-API Historical Events URL: %s", self.url)

    def set_headers(self) -> None:
        self.headers = {"Accept": "application/json"}  # UA not required

    # ------------------------------------------------------------------ #
    # HTTP status handling                                               #
    # ------------------------------------------------------------------ #
    def check_download_status(self) -> None:
        """
        Treat 200 **and 204** as success (204 ⇒ empty snapshot, costs 0 credits).
        """
        if self.raw_response.status_code in (200, 204):
            return
        super().check_download_status()  # will raise on other status codes

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        """
        Expect wrapper dict with 'data' list.  Handle 'message' (errors).
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

        events: List[Dict[str, Any]] = wrapper.get("data", [])
        events.sort(key=lambda e: e.get("commence_time", ""))

        self.data = {
            "sport": self.opts["sport"],
            "snapshot_timestamp": wrapper.get("timestamp"),
            "previous_snapshot": wrapper.get("previous_timestamp"),
            "next_snapshot": wrapper.get("next_timestamp"),
            "rowCount": len(events),
            "events": events,
        }
        logger.info("Fetched %d events @ %s", len(events), self.data["snapshot_timestamp"])

    # ------------------------------------------------------------------ #
    # Conditional save                                                   #
    # ------------------------------------------------------------------ #
    def should_save_data(self) -> bool:
        """Skip export when rowCount == 0 (i.e., 204 empty snapshot)."""
        return bool(self.data.get("rowCount"))

    # ------------------------------------------------------------------ #
    # Stats line                                                         #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        return {
            "rowCount": self.data.get("rowCount", 0),
            "sport": self.opts.get("sport"),
            "snapshot": self.data.get("snapshot_timestamp"),
        }

# --------------------------------------------------------------------------- #
# Cloud Run / Flask entry point for Events Scraper                           #
# --------------------------------------------------------------------------- #
def create_app():
    """Create Flask app for Events Scraper."""
    from flask import Flask, request, jsonify
    from dotenv import load_dotenv
    import logging
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
            "scraper": "odds_api_historical_events",
            "version": "1.0.0",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }), 200
    
    @app.route('/scrape', methods=['POST'])
    def scrape_events():
        """Scrape historical NBA events"""
        try:
            # Get parameters from JSON body or query params
            if request.is_json:
                params = request.get_json()
            else:
                params = request.args.to_dict()
            
            # Events scraper specific parameters
            opts = {
                "apiKey": params.get("apiKey"),  # Falls back to env var
                "sport": params.get("sport", "basketball_nba"),
                "date": params.get("date"),  # REQUIRED
                "commenceTimeFrom": params.get("commenceTimeFrom"),
                "commenceTimeTo": params.get("commenceTimeTo"),
                "eventIds": params.get("eventIds"),
                "dateFormat": params.get("dateFormat"),
                "group": params.get("group", "prod"),
                "runId": params.get("runId"),
                "debug": bool(params.get("debug", False))
            }
            
            # Validate required params for events scraper
            if not opts["date"]:
                return jsonify({"error": "Missing required parameter: date"}), 400
            
            # Set debug logging
            if opts["debug"]:
                logging.getLogger().setLevel(logging.DEBUG)
            
            # Run the events scraper
            scraper = GetOddsApiHistoricalEvents()
            result = scraper.run(opts)
            
            if result:
                return jsonify({
                    "status": "success",
                    "message": "Events scraping completed successfully",
                    "scraper": "odds_api_historical_events",
                    "run_id": scraper.run_id,
                    "data_summary": scraper.get_scraper_stats()
                }), 200
            else:
                return jsonify({
                    "status": "error",
                    "message": "Events scraping failed",
                    "scraper": "odds_api_historical_events",
                    "run_id": scraper.run_id
                }), 500
                
        except Exception as e:
            app.logger.error(f"Events scraper error: {str(e)}", exc_info=True)
            return jsonify({
                "status": "error",
                "scraper": "odds_api_historical_events",
                "message": str(e)
            }), 500
    
    return app


# --------------------------------------------------------------------------- #
# Main entry point for Events Scraper                                         #
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
        parser = argparse.ArgumentParser(description="Scrape The-Odds-API historical events")
        parser.add_argument("--serve", action="store_true", help="Start web server")
        parser.add_argument("--apiKey", help="Optional - env ODDS_API_KEY fallback")
        parser.add_argument("--sport", default="basketball_nba", help="e.g. basketball_nba")
        parser.add_argument("--date", help="ISO timestamp (required for CLI)")
        parser.add_argument("--commenceTimeFrom")
        parser.add_argument("--commenceTimeTo")
        parser.add_argument("--eventIds")
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
                
            if args.debug:
                logging.getLogger().setLevel(logging.DEBUG)
                
            # Run the events scraper
            scraper = GetOddsApiHistoricalEvents()
            scraper.run(vars(args))
