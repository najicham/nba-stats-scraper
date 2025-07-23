"""
BIGDATABALL - Game Download endpoint (OPTIMIZED)               v2.0 - 2025-07-22
-------------------------------------------------------------------------------
Download specific BigDataBall games via Google Drive (optimized for single-game downloads):

    Download individual game play-by-play data by game ID

--game_id is REQUIRED for focused game downloads
--teams can be used as alternative to game_id

Usage examples:
  # Get specific game by ID (RECOMMENDED):
  python scrapers/bigdataball/bigdataball_pbp.py --debug --game_id=0042400407

  # Get specific team matchup:
  python scrapers/bigdataball/bigdataball_pbp.py --debug --teams="IND@OKC"

  # Via capture tool (recommended):
  python tools/fixtures/capture.py bigdataball_pbp --game_id=0042400407 --debug
"""

from __future__ import annotations

import logging
import os
import sys
import io
import json
import pandas as pd
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from googleapiclient.discovery import build
from google.oauth2 import service_account
from googleapiclient.http import MediaIoBaseDownload

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.bigdataball.bigdataball_pbp
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/bigdataball/bigdataball_pbp.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Optimized PBP Scraper (FOCUSED ON SPECIFIC GAMES)
# --------------------------------------------------------------------------- #
class BigDataBallPbpScraper(ScraperBase, ScraperFlaskMixin):
    """Optimized scraper for downloading specific BigDataBall games by ID."""

    # Flask Mixin Configuration
    scraper_name = "bigdataball_pbp"
    required_params = []  # No required parameters
    optional_params = {
        "service_account_key_path": None,  # Falls back to env var
        "game_id": None,  # Specific NBA game ID (e.g., 0042400407) - RECOMMENDED
        "teams": None,  # Team matchup filter (e.g., "IND@OKC") - ALTERNATIVE
    }

    # Original scraper config
    required_opts: List[str] = []
    download_type = DownloadType.BINARY  # We're downloading CSV files
    decode_download_data = True  # We manually populate decoded_data

    # ------------------------------------------------------------------ #
    # Exporters (includes capture support)
    # ------------------------------------------------------------------ #
    exporters = [
        # GCS export for production
        {
            "type": "gcs",
            "key": "big-data-ball/games/%(date)s/%(game_id)s.json",
            "export_mode": ExportMode.DATA,
            "groups": ["prod"],
        },
        # Local file for development
        {
            "type": "file",
            "filename": "/tmp/bigdataball_game_%(game_id)s.json",
            "pretty_print": True,
            "export_mode": ExportMode.DATA,
            "groups": ["dev"],
        },
        # Capture RAW + EXP
        {
            "type": "file",
            "filename": "/tmp/raw_%(run_id)s.csv",
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
        self.downloaded_file_path = None

    # ------------------------------------------------------------------ #
    # Additional opts                                                    #
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        
        # Validate that we have either game_id or teams
        if not self.opts.get("game_id") and not self.opts.get("teams"):
            raise ValueError("Either game_id or teams parameter is required")
        
        # Build search query for the specific game
        if self.opts.get("game_id"):
            game_id = self.opts["game_id"]
            self.opts["search_query"] = f"name contains '{game_id}' and not name contains 'combined-stats'"
        elif self.opts.get("teams"):
            teams = self.opts["teams"]
            if "@" in teams:
                self.opts["search_query"] = f"name contains '{teams}' and not name contains 'combined-stats'"
            elif "," in teams:
                # Handle comma-separated teams
                team1, team2 = teams.split(",")
                team1, team2 = team1.strip(), team2.strip()
                self.opts["search_query"] = f"(name contains '{team1}@{team2}' or name contains '{team2}@{team1}') and not name contains 'combined-stats'"
            else:
                self.opts["search_query"] = f"name contains '{teams}' and not name contains 'combined-stats'"

    # ------------------------------------------------------------------ #
    # Google Drive Setup (replaces URL & headers)                       #
    # ------------------------------------------------------------------ #
    def set_url(self) -> None:
        """BigDataBall uses Google Drive, so we don't have a traditional URL"""
        self.url = "google_drive_api"  # Placeholder for logging
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
            
            if not service_account_key_path:
                raise ValueError("No service account key path provided. Set BIGDATABALL_SERVICE_ACCOUNT_KEY_PATH or GOOGLE_APPLICATION_CREDENTIALS environment variable.")
            
            if not os.path.exists(service_account_key_path):
                raise ValueError(f"Service account key file not found: {service_account_key_path}")

            credentials = service_account.Credentials.from_service_account_file(
                service_account_key_path, 
                scopes=self.SCOPES
            )
            self.drive_service = build('drive', 'v3', credentials=credentials)
            self.step_info("drive_init", "Successfully initialized Google Drive service")
            
        except Exception as e:
            logger.error(f"Failed to initialize Google Drive service: {e}")
            raise

    # ------------------------------------------------------------------ #
    # Download & Decode (Override for Google Drive)                     #
    # ------------------------------------------------------------------ #
    def download_and_decode(self):
        """Override to use Google Drive API instead of HTTP requests"""
        try:
            # Search for the specific game file
            self.step_info("drive_search", "Searching for specific game", 
                          extra={"query": self.opts["search_query"]})
            
            files = self._search_drive_files()
            if not files:
                raise ValueError(f"No game found matching query: {self.opts['search_query']}")

            # Get the target file (should be only one for specific game)
            target_file = self._get_target_file(files)
            self.step_info("drive_file_found", f"Found game file: {target_file['name']}", 
                          extra={"file_id": target_file['id'], "modified": target_file.get('modifiedTime')})

            # Download the file
            self.downloaded_file_path = self._download_drive_file(target_file)
            
            # Store the raw CSV content
            with open(self.downloaded_file_path, 'rb') as f:
                raw_content = f.read()
            
            # Create a mock response object for compatibility with base class
            class MockResponse:
                def __init__(self, content):
                    self.content = content
                    self.status_code = 200
            
            self.raw_response = MockResponse(raw_content)
            
            # Process CSV file into decoded_data
            self._process_csv_file()
            
        except Exception as e:
            logger.error(f"Error in BigDataBall download_and_decode: {e}")
            raise

    def _search_drive_files(self) -> List[Dict]:
        """Search for the specific game file"""
        try:
            query = self.opts["search_query"]
            
            results = self.drive_service.files().list(
                q=query,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                fields="nextPageToken, files(id, name, modifiedTime, size)",
                pageSize=10  # Should only be 1 file for specific game
            ).execute()
            
            files = results.get('files', [])
            self.step_info("drive_search_complete", f"Found {len(files)} files matching game query", 
                          extra={"query": query})
            
            return files
            
        except Exception as e:
            logger.error(f"Error searching Drive files: {e}")
            raise

    def _get_target_file(self, files: List[Dict]) -> Dict:
        """Get the target file, with optional filtering for team matchups"""
        if not files:
            raise ValueError("No files provided to get target from")
        
        # For comma-separated teams, filter to find the right matchup
        if self.opts.get("teams") and "," in self.opts["teams"]:
            team1, team2 = self.opts["teams"].split(",")
            team1, team2 = team1.strip(), team2.strip()
            
            for file in files:
                name = file['name']
                if (f"{team1}@{team2}" in name) or (f"{team2}@{team1}" in name):
                    logger.info(f"Found matching game: {name}")
                    return file
            
            raise ValueError(f"No game found for teams {team1} vs {team2}")
        
        # For game_id or direct team matchup, take the first (should be only) result
        target_file = files[0]
        if len(files) > 1:
            logger.warning(f"Multiple files found, taking first: {target_file['name']}")
        
        return target_file

    def _download_drive_file(self, file_info: Dict) -> str:
        """Download a file from Google Drive to local temp storage"""
        try:
            # Create temp file path
            temp_filename = f"bigdataball_{self.run_id}_{file_info['name']}"
            local_path = f"/tmp/{temp_filename}"
            
            # Download file
            request = self.drive_service.files().get_media(fileId=file_info['id'])
            
            with io.FileIO(local_path, 'wb') as fh:
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    status, done = downloader.next_chunk()
                    if status:
                        progress = int(status.progress() * 100)
                        if progress % 25 == 0:  # Log every 25%
                            logger.info(f"Download progress: {progress}%")
            
            self.step_info("drive_download", f"Downloaded file to {local_path}", 
                          extra={"file_size": os.path.getsize(local_path)})
            return local_path
            
        except Exception as e:
            logger.error(f"Error downloading file {file_info['name']}: {e}")
            raise

    def _process_csv_file(self) -> None:
        """Process the downloaded CSV file and convert to our standard format"""
        try:
            # Read CSV file
            df = pd.read_csv(self.downloaded_file_path)
            
            # Extract game info from filename or data
            game_info = self._extract_game_info_from_data(df)
            
            # Convert to records first, then clean up NaN values
            play_records = df.to_dict('records')
            
            # Clean up NaN values in the records
            import math
            for record in play_records:
                for key, value in record.items():
                    if pd.isna(value) or (isinstance(value, float) and math.isnan(value)):
                        record[key] = None
            
            # Store processed data in decoded_data for compatibility
            self.decoded_data = {
                'file_name': os.path.basename(self.downloaded_file_path),
                'processed_at': datetime.now(timezone.utc).isoformat(),
                'total_plays': len(df),
                'columns': df.columns.tolist(),
                'game_info': game_info,
                'play_by_play_data': play_records
            }
            
            self.step_info("csv_process", f"Processed CSV file: {len(df)} plays found", 
                          extra={"columns": len(df.columns), "rows": len(df), "game_id": game_info.get("game_id")})
            
        except Exception as e:
            logger.error(f"Error processing CSV file: {e}")
            raise
        finally:
            # Clean up temp file
            if self.downloaded_file_path and os.path.exists(self.downloaded_file_path):
                os.remove(self.downloaded_file_path)

    def _extract_game_info_from_data(self, df: pd.DataFrame) -> Dict:
        """Extract game metadata from the play-by-play data"""
        game_info = {}
        
        if not df.empty:
            first_row = df.iloc[0]
            
            # Extract teams from filename if available, fallback to data
            away_team = "unknown"
            home_team = "unknown"
            
            # Try to extract from filename first
            filename = self.downloaded_file_path or ""
            if "@" in filename:
                try:
                    # Extract from pattern like: [2025-06-22]-0042400407-IND@OKC.csv
                    team_part = filename.split("-")[-1].replace(".csv", "")  # "IND@OKC"
                    if "@" in team_part:
                        away_team, home_team = team_part.split("@")
                except:
                    pass
            
            # Extract key game information
            game_info = {
                'game_id': str(first_row.get('game_id', '')),
                'date': str(first_row.get('date', '')),
                'data_set': str(first_row.get('data_set', '')),
                'away_team': away_team,
                'home_team': home_team
            }
            
            # Try to extract final score from last few rows
            last_rows = df.tail(5)
            final_row = last_rows[last_rows['event_type'] == 'end of period'].iloc[-1] if not last_rows[last_rows['event_type'] == 'end of period'].empty else df.iloc[-1]
            
            game_info.update({
                'final_away_score': int(final_row.get('away_score', 0)) if pd.notna(final_row.get('away_score')) else 0,
                'final_home_score': int(final_row.get('home_score', 0)) if pd.notna(final_row.get('home_score')) else 0,
                'periods_played': int(final_row.get('period', 4)) if pd.notna(final_row.get('period')) else 4
            })
        
        return game_info

    # ------------------------------------------------------------------ #
    # Validation                                                         #
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        """Validate that we successfully processed the CSV data"""
        if not isinstance(self.decoded_data, dict) or "play_by_play_data" not in self.decoded_data:
            raise ValueError("BigDataBall response malformed: missing 'play_by_play_data' key")
        
        if not self.decoded_data["play_by_play_data"]:
            raise ValueError("BigDataBall data is empty: no play-by-play records found")

    # ------------------------------------------------------------------ #
    # Transform                                                          #
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        """Transform the CSV data into our standard format"""
        plays = self.decoded_data["play_by_play_data"]
        game_info = self.decoded_data["game_info"]
        
        # Sort plays by period and time for proper sequence
        if plays:
            try:
                plays.sort(key=lambda x: (
                    x.get('period', 0),
                    x.get('elapsed', 0)  # Use elapsed time for sorting
                ))
            except (TypeError, KeyError):
                logger.warning("Could not sort plays by expected keys")

        # Extract game_id for path substitution
        game_id = game_info.get('game_id', 'unknown')
        if game_id and game_id != 'unknown':
            self.opts['game_id'] = game_id

        self.data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "bigdataball",
            "game_info": game_info,
            "file_info": {
                "name": self.decoded_data.get("file_name"),
                "processed_at": self.decoded_data.get("processed_at"),
                "total_plays": self.decoded_data.get("total_plays", 0),
                "columns": self.decoded_data.get("columns", [])
            },
            "playByPlay": plays
        }
        
        logger.info("Transformed %d play-by-play records for game %s", 
                   len(plays), game_id)

    # ------------------------------------------------------------------ #
    # Stats                                                              #
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        play_count = len(self.data.get("playByPlay", []))
        game_info = self.data.get("game_info", {})
        file_name = self.data.get("file_info", {}).get("name", "unknown")
        
        return {
            "playCount": play_count,
            "gameId": game_info.get("game_id"),
            "gameDate": game_info.get("date"),
            "awayTeam": game_info.get("away_team"),
            "homeTeam": game_info.get("home_team"),
            "finalScore": f"{game_info.get('final_away_score', 0)}-{game_info.get('final_home_score', 0)}",
            "fileName": file_name,
            "source": "bigdataball"
        }


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(BigDataBallPbpScraper)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = BigDataBallPbpScraper.create_cli_and_flask_main()
    main()
    