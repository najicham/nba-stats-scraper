# File: scrapers/bigdataball/bigdataball_discovery.py
"""
BIGDATABALL DISCOVERY - Game ID Discovery endpoint (OPTIMIZED)  v2.0 - 2025-07-22
-------------------------------------------------------------------------------
Discover available BigDataBall game IDs via Google Drive (optimized for game ID extraction):

    Fast discovery of game IDs for targeted downloading

--date param defaults to **yesterday (UTC)**.

Usage examples:
  # Get game IDs for specific date:
  python scrapers/bigdataball/bigdataball_discovery.py --debug --date=2025-06-22

  # Via capture tool (recommended):
  python tools/fixtures/capture.py bigdataball_discovery --date=2025-06-22 --debug
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from googleapiclient.discovery import build
from google.oauth2 import service_account

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.bigdataball.bigdataball_discovery
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/bigdataball/bigdataball_discovery.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

# Notification system imports
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Optimized Discovery Scraper (FOCUSED ON GAME IDS)
# --------------------------------------------------------------------------- #
class BigDataBallDiscoveryScraper(ScraperBase, ScraperFlaskMixin):
    """Optimized discovery scraper for BigDataBall game IDs only."""

    # Flask Mixin Configuration
    scraper_name = "bigdataball_discovery"
    required_params = []  # No required parameters
    optional_params = {
        "date": None,  # Defaults to yesterday if not provided
        "service_account_key_path": None,  # Falls back to env var
        "teams": None,  # Optional team filter
    }

    # Original scraper config
    required_opts: List[str] = []
    download_type = DownloadType.JSON  # We generate JSON directly (no HTTP download)
    decode_download_data = True  # We manually populate decoded_data

    # ------------------------------------------------------------------ #
    # Exporters (includes capture support)
    # ------------------------------------------------------------------ #
    exporters = [
        # GCS export for production
        {
            "type": "gcs",
            "key": "big-data-ball/discovery/%(date)s/%(timestamp)s.json",
            "export_mode": ExportMode.DATA,
            "groups": ["prod"],
        },
        # Local file for development
        {
            "type": "file",
            "filename": "/tmp/bigdataball_discovery_%(date)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev"],
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
    # Google Drive Configuration
    # ------------------------------------------------------------------ #
    SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

    def __init__(self):
        super().__init__()
        self.drive_service = None

    # ------------------------------------------------------------------ #
    # Additional opts                                                    #
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        if not self.opts.get("date"):
            yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
            self.opts["date"] = yesterday.isoformat()

    # ------------------------------------------------------------------ #
    # URL & headers (overridden for Google Drive)                       #
    # ------------------------------------------------------------------ #
    def set_url(self) -> None:
        """BigDataBall uses Google Drive, so we don't have a traditional URL"""
        self.url = "google_drive_discovery"  # Placeholder for logging
        self._init_drive_service()

    def set_headers(self) -> None:
        """Google Drive API uses service account auth, no custom headers needed"""
        self.headers = {}

    def _init_drive_service(self) -> None:
        """Initialize Google Drive API service"""
        try:
            service_account_key_path = (
                self.opts.get("service_account_key_path") or 
                os.getenv("BIGDATABALL_SERVICE_ACCOUNT_KEY_PATH") or
                os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            )
            
            if service_account_key_path and os.path.exists(service_account_key_path):
                # Use explicit key file if provided
                credentials = service_account.Credentials.from_service_account_file(
                    service_account_key_path, 
                    scopes=self.SCOPES
                )
                self.step_info("drive_init", f"Using service account key: {service_account_key_path}")
            else:
                # Use default credentials (for Cloud Run with service account)
                from google.auth import default
                credentials, _ = default(scopes=self.SCOPES)
                self.step_info("drive_init", "Using default credentials (Cloud Run service account)")
            
            self.drive_service = build('drive', 'v3', credentials=credentials)
            self.step_info("drive_init", "Successfully initialized Google Drive service")
            
        except Exception as e:
            logger.error(f"Failed to initialize Google Drive service: {e}")
            
            # Send error notification
            try:
                notify_error(
                    title="BigDataBall Discovery Drive Service Failed",
                    message=f"Failed to initialize Google Drive API: {str(e)}",
                    details={
                        'scraper': 'bigdataball_discovery',
                        'error_type': type(e).__name__,
                        'service_account_key_exists': bool(service_account_key_path and os.path.exists(service_account_key_path))
                    },
                    processor_name="BigDataBall Discovery Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise

    # ------------------------------------------------------------------ #
    # Download & Decode (Override for Discovery)                        #
    # ------------------------------------------------------------------ #
    def download_and_decode(self):
        """Override to perform discovery instead of downloading files"""
        try:
            date_str = self.opts["date"]
            self.step_info("discovery_start", f"Starting game ID discovery for {date_str}")
            
            # Simple date-based discovery only
            files = self._discover_games_by_date(date_str)
            
            # Check if any games were found
            if not files:
                warning_msg = f"No games found for date {date_str}"
                logger.warning(warning_msg)
                
                # Send warning notification
                try:
                    notify_warning(
                        title="BigDataBall No Games Found",
                        message=warning_msg,
                        details={
                            'scraper': 'bigdataball_discovery',
                            'date': date_str,
                            'teams_filter': self.opts.get('teams')
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
            
            # Process into simple game ID list
            discovery_results = self._process_game_files(files)
            
            # Store in decoded_data (standard scraper pattern)
            self.decoded_data = discovery_results
            
            # Create mock response for compatibility with base class
            class MockResponse:
                def __init__(self):
                    self.content = b'{"discovery": "completed"}'
                    self.status_code = 200
            
            self.raw_response = MockResponse()
            
            self.step_info("discovery_complete", f"Discovery completed", 
                          extra={"game_count": discovery_results.get("count", 0)})
            
        except Exception as e:
            logger.error(f"Error in BigDataBall discovery: {e}")
            
            # Send error notification
            try:
                notify_error(
                    title="BigDataBall Discovery Failed",
                    message=f"Game discovery failed: {str(e)}",
                    details={
                        'scraper': 'bigdataball_discovery',
                        'error_type': type(e).__name__,
                        'date': self.opts.get('date'),
                        'teams_filter': self.opts.get('teams')
                    },
                    processor_name="BigDataBall Discovery Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise

    def _discover_games_by_date(self, date_str: str) -> List[Dict]:
        """Discover individual game files for a specific date"""
        # Focus only on individual games (not combined files)
        query = f"name contains '[{date_str}]' and not name contains 'combined-stats'"
        
        self.step_info("discovery_search", f"Searching for individual games on {date_str}", 
                      extra={"query": query})
        
        return self._search_drive_files(query)

    def _search_drive_files(self, query: str, max_results: int = 20) -> List[Dict]:
        """Search for files in the shared BigDataBall folder"""
        try:
            results = self.drive_service.files().list(
                q=query,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                fields="files(id, name, modifiedTime, size)",
                pageSize=max_results,
                orderBy="modifiedTime desc"
            ).execute()
            
            files = results.get('files', [])
            self.step_info("drive_search_complete", f"Found {len(files)} files", 
                          extra={"query": query, "count": len(files)})
            
            return files
            
        except Exception as e:
            logger.error(f"Error searching Drive files: {e}")
            
            # Send error notification
            try:
                notify_error(
                    title="BigDataBall Drive Search Failed",
                    message=f"Failed to search Google Drive: {str(e)}",
                    details={
                        'scraper': 'bigdataball_discovery',
                        'error_type': type(e).__name__,
                        'query': query,
                        'date': self.opts.get('date')
                    },
                    processor_name="BigDataBall Discovery Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise

    def _process_game_files(self, files: List[Dict]) -> Dict:
        """Process files into simple game ID format"""
        games = []
        
        for file in files:
            name = file['name']
            
            # Extract game metadata from filename
            game_info = self._extract_game_info(name)
            if game_info:
                # Apply team filter if provided
                if self.opts.get("teams"):
                    team_filter = self.opts["teams"].upper()
                    if team_filter not in game_info.get("teams", "").upper():
                        continue
                
                games.append({
                    'file_id': file['id'],
                    'file_name': name,
                    'size_bytes': int(file.get('size', 0)) if file.get('size', '').isdigit() else 0,
                    'modified': file.get('modifiedTime'),
                    **game_info
                })
        
        # Sort games by date, then by game_id
        games.sort(key=lambda x: (x.get('date', ''), x.get('game_id', '')))
        
        return {
            'date': self.opts["date"],
            'teams_filter': self.opts.get("teams"),
            'processed_at': datetime.now(timezone.utc).isoformat(),
            'count': len(games),
            'games': games
        }

    def _extract_game_info(self, filename: str) -> Optional[Dict]:
        """Extract game information from filename"""
        try:
            # Parse filename like: [2025-06-22]-0042400407-IND@OKC.csv
            if '[' in filename and ']' in filename and '@' in filename:
                # Extract date
                date_start = filename.find('[')
                date_end = filename.find(']')
                if date_start >= 0 and date_end > date_start:
                    date_part = filename[date_start + 1:date_end]  # "2025-06-22"
                    
                    # Extract game_id and teams
                    after_date = filename[date_end + 2:]  # Skip "]-"
                    if after_date.endswith('.csv'):
                        after_date = after_date[:-4]  # Remove ".csv"
                    
                    # Split on last dash to get game_id and teams
                    last_dash = after_date.rfind('-')
                    if last_dash > 0:
                        game_id = after_date[:last_dash]
                        teams = after_date[last_dash + 1:]
                        
                        # Split teams into away/home
                        if '@' in teams:
                            away_team, home_team = teams.split('@')
                            
                            return {
                                'game_id': game_id,
                                'date': date_part,
                                'teams': teams,
                                'away_team': away_team,
                                'home_team': home_team
                            }
        except Exception as e:
            logger.warning(f"Could not extract game info from {filename}: {e}")
        
        return None

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        """Validate that discovery completed successfully"""
        try:
            if not isinstance(self.decoded_data, dict):
                raise ValueError("Discovery failed: missing results data")
            
            if "count" not in self.decoded_data:
                raise ValueError("Discovery failed: missing count data")
        except Exception as e:
            logger.error(f"Validation failed: {e}")
            
            # Send error notification
            try:
                notify_error(
                    title="BigDataBall Discovery Validation Failed",
                    message=f"Discovery data validation failed: {str(e)}",
                    details={
                        'scraper': 'bigdataball_discovery',
                        'error_type': type(e).__name__,
                        'has_decoded_data': bool(self.decoded_data),
                        'date': self.opts.get('date')
                    },
                    processor_name="BigDataBall Discovery Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise

    # ------------------------------------------------------------------ #
    # Transform                                                          #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        """Transform discovery results into final format"""
        discovery_results = self.decoded_data
        
        self.data = {
            "date": self.opts["date"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "bigdataball",
            "mode": "discovery",
            "results": discovery_results
        }
        
        total_games = discovery_results.get("count", 0)
        logger.info("Discovery transformation complete: %d games catalogued", total_games)
        
        # Send success notification
        try:
            notify_info(
                title="BigDataBall Game Discovery Complete",
                message=f"Successfully discovered {total_games} games for {self.opts['date']}",
                details={
                    'scraper': 'bigdataball_discovery',
                    'date': self.opts['date'],
                    'total_games': total_games,
                    'teams_filter': self.opts.get('teams'),
                    'games': discovery_results.get('games', [])
                }
            )
        except Exception as notify_ex:
            logger.warning(f"Failed to send notification: {notify_ex}")

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        results = self.data.get("results", {})
        
        return {
            "mode": "discovery",
            "totalGames": results.get("count", 0),
            "date": self.opts["date"],
            "teams_filter": self.opts.get("teams"),
            "source": "bigdataball",
            "games": results.get("games", [])
        }


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(BigDataBallDiscoveryScraper)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = BigDataBallDiscoveryScraper.create_cli_and_flask_main()
    main()