# scrapers/nbacom/nbac_referee_assignments.py
"""
NBA.com Referee Assignments scraper                     v1 - 2025-09-12
-----------------------------------------------------------------------
Downloads official referee assignments from official.nba.com for a given date.
This is NBA's official source for daily referee assignments.

Usage examples
--------------
  # Via capture tool (recommended for data collection):
   python tools/fixtures/capture.py nbac_referee_assignments \
      --date 2025-01-08 \
      --debug

  # Direct CLI execution:
  python scrapers/nbacom/nbac_referee_assignments.py --date 2025-01-08 --debug

  # Flask web service:
  python scrapers/nbacom/nbac_referee_assignments.py --serve --debug
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict

# Support both module execution (python -m) and direct execution
try:
    # Module execution: python -m scrapers.nbacom.nbac_referee_assignments
    from ..scraper_base import DownloadType, ExportMode, ScraperBase
    from ..scraper_flask_mixin import ScraperFlaskMixin
    from ..scraper_flask_mixin import convert_existing_flask_scraper
    from ..utils.exceptions import DownloadDataException
    from ..utils.gcs_path_builder import GCSPathBuilder
except ImportError:
    # Direct execution: python scrapers/nbacom/nbac_referee_assignments.py
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.scraper_base import DownloadType, ExportMode, ScraperBase
    from scrapers.scraper_flask_mixin import ScraperFlaskMixin
    from scrapers.scraper_flask_mixin import convert_existing_flask_scraper
    from scrapers.utils.exceptions import DownloadDataException
    from scrapers.utils.gcs_path_builder import GCSPathBuilder

# Import notification system
try:
    from shared.utils.notification_system import (
        notify_error,
        notify_warning,
        notify_info
    )
except ImportError:
    # Fallback if shared module not available
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from shared.utils.notification_system import (
        notify_error,
        notify_warning,
        notify_info
    )

logger = logging.getLogger("scraper_base")


class GetNbaComRefereeAssignments(ScraperBase, ScraperFlaskMixin):
    """Downloads official referee assignments JSON from NBA.com."""

    # Flask Mixin Configuration
    scraper_name = "nbac_referee_assignments"
    required_params = ["date"]
    optional_params = {
        "api_key": None,  # Falls back to env var if needed
    }

    # ------------------------------------------------------------------ #
    # Configuration
    # ------------------------------------------------------------------ #
    required_opts = ["date"]
    download_type: DownloadType = DownloadType.JSON
    proxy_enabled: bool = True
    decode_download_data: bool = True
    header_profile: str | None = "data"

    GCS_PATH_KEY = "nba_com_referee_assignments"
    exporters = [
        {
            "type": "gcs",
            "key": GCSPathBuilder.get_path(GCS_PATH_KEY),
            "export_mode": ExportMode.DATA,
            "groups": ["prod", "gcs"],
        },
        {
            "type": "file",
            "filename": "/tmp/nbacom_referee_assignments_%(date)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["dev", "test", "prod"],
        },        
        # ADD CAPTURE EXPORTERS for testing with capture.py
        {
            "type": "file",
            "filename": "/tmp/raw_%(run_id)s.json",
            "export_mode": ExportMode.RAW,
            "groups": ["capture"],
        },
        {
            "type": "file", 
            "filename": "/tmp/exp_%(run_id)s.json",
            "export_mode": ExportMode.DATA,
            "pretty_print": True,
            "groups": ["capture"],
        },
    ]

    # ------------------------------------------------------------------ #
    # Additional opts helper (derive season)
    # ------------------------------------------------------------------ #
    def set_additional_opts(self) -> None:
        super().set_additional_opts()
        
        # Add timestamp for exports
        now = datetime.now(timezone.utc)
        self.opts["time"] = now.strftime("%H-%M-%S")
        
        # Derive season from date (assumes current season format)
        try:
            date_obj = datetime.strptime(self.opts["date"], "%Y-%m-%d")
            # NBA season spans Oct-June, so if month >= 10, it's start of season
            if date_obj.month >= 10:
                season_start = date_obj.year
            else:
                season_start = date_obj.year - 1
            
            self.opts["season"] = f"{season_start}-{(season_start + 1) % 100:02d}"
            
            # Format date for URL (YYYY-MM-DD format expected by API)
            self.opts["formatted_date"] = self.opts["date"]
            
        except ValueError:
            try:
                notify_error(
                    title="NBA.com Referee Assignments - Invalid Date",
                    message=f"Invalid date format: {self.opts.get('date')}. Expected YYYY-MM-DD",
                    details={
                        'scraper': 'nbac_referee_assignments',
                        'date': self.opts.get('date'),
                        'expected_format': 'YYYY-MM-DD'
                    },
                    processor_name="NBA.com Referee Assignments Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise DownloadDataException("Invalid date format. Expected YYYY-MM-DD")

    # ------------------------------------------------------------------ #
    # URL builder
    # ------------------------------------------------------------------ #
    def set_url(self) -> None:
        date = self.opts["formatted_date"]
        self.url = (
            f"https://official.nba.com/wp-json/api/v1/get-game-officials"
            f"?&date={date}"
        )
        logger.info("Referee assignments URL: %s", self.url)

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #
    def validate_download_data(self) -> None:
        try:
            if not isinstance(self.decoded_data, dict):
                try:
                    notify_error(
                        title="NBA.com Referee Assignments - Invalid Response",
                        message=f"Response is not a valid JSON object for date {self.opts['formatted_date']}",
                        details={
                            'scraper': 'nbac_referee_assignments',
                            'date': self.opts['formatted_date'],
                            'response_type': type(self.decoded_data).__name__,
                            'url': self.url
                        },
                        processor_name="NBA.com Referee Assignments Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException("Referee response is not a valid JSON object")
                
            # Check for main league data (NBA)
            nba_data = self.decoded_data.get("nba")
            if nba_data is None:
                try:
                    notify_error(
                        title="NBA.com Referee Assignments - Missing NBA Data",
                        message=f"Response missing 'nba' key for date {self.opts['formatted_date']}",
                        details={
                            'scraper': 'nbac_referee_assignments',
                            'date': self.opts['formatted_date'],
                            'available_keys': list(self.decoded_data.keys()),
                            'url': self.url
                        },
                        processor_name="NBA.com Referee Assignments Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException("Response missing 'nba' key")
                
            # Check for table structure
            table_data = nba_data.get("Table")
            if table_data is None:
                try:
                    notify_error(
                        title="NBA.com Referee Assignments - Missing Table",
                        message=f"NBA data missing 'Table' key for date {self.opts['formatted_date']}",
                        details={
                            'scraper': 'nbac_referee_assignments',
                            'date': self.opts['formatted_date'],
                            'nba_keys': list(nba_data.keys()),
                            'url': self.url
                        },
                        processor_name="NBA.com Referee Assignments Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException("NBA data missing 'Table' key")
                
            rows = table_data.get("rows", [])
            if not isinstance(rows, list):
                try:
                    notify_error(
                        title="NBA.com Referee Assignments - Invalid Rows",
                        message=f"Table.rows is not a list for date {self.opts['formatted_date']}",
                        details={
                            'scraper': 'nbac_referee_assignments',
                            'date': self.opts['formatted_date'],
                            'rows_type': type(rows).__name__,
                            'url': self.url
                        },
                        processor_name="NBA.com Referee Assignments Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException("Table.rows is not a list")
                
        except DownloadDataException:
            # Re-raise validation exceptions (already notified above)
            raise
        except Exception as e:
            # Catch any unexpected validation errors
            try:
                notify_error(
                    title="NBA.com Referee Assignments - Validation Failed",
                    message=f"Unexpected validation error for date {self.opts['formatted_date']}: {str(e)}",
                    details={
                        'scraper': 'nbac_referee_assignments',
                        'date': self.opts['formatted_date'],
                        'error_type': type(e).__name__,
                        'error': str(e),
                        'url': self.url
                    },
                    processor_name="NBA.com Referee Assignments Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise

    # ------------------------------------------------------------------ #
    # Enhanced validation for production use
    # ------------------------------------------------------------------ #
    def validate_referee_data(self) -> None:
        """
        Production validation for referee assignment data quality.
        """
        try:
            nba_data = self.data["refereeAssignments"]["nba"]
            rows = nba_data["Table"]["rows"]
            
            # 1. GAME COUNT CHECK
            game_count = len(rows)
            if game_count == 0:
                # No games - could be off-season or all-star break (INFO, not error)
                try:
                    notify_info(
                        title="NBA.com Referee Assignments - No Games",
                        message=f"No NBA games found for date {self.opts['formatted_date']} (off-season or break)",
                        details={
                            'scraper': 'nbac_referee_assignments',
                            'date': self.opts['formatted_date'],
                            'season': self.opts['season'],
                            'game_count': 0
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                logger.warning("No NBA games found for this date - could be off-season or all-star break")
            elif game_count > 20:
                try:
                    notify_error(
                        title="NBA.com Referee Assignments - High Game Count",
                        message=f"Suspiciously high game count: {game_count} for date {self.opts['formatted_date']}",
                        details={
                            'scraper': 'nbac_referee_assignments',
                            'date': self.opts['formatted_date'],
                            'game_count': game_count,
                            'threshold_max': 20
                        },
                        processor_name="NBA.com Referee Assignments Scraper"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                raise DownloadDataException(f"Suspiciously high game count: {game_count} (expected 1-15)")
            
            # 2. BASIC DATA STRUCTURE VALIDATION  
            required_table_keys = ['rows', 'columns']
            for key in required_table_keys:
                if key not in nba_data["Table"]:
                    try:
                        notify_error(
                            title="NBA.com Referee Assignments - Missing Table Key",
                            message=f"Missing required table key '{key}' for date {self.opts['formatted_date']}",
                            details={
                                'scraper': 'nbac_referee_assignments',
                                'date': self.opts['formatted_date'],
                                'missing_key': key,
                                'available_keys': list(nba_data["Table"].keys())
                            },
                            processor_name="NBA.com Referee Assignments Scraper"
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send notification: {notify_ex}")
                    raise DownloadDataException(f"Missing required table key: {key}")
            
            # 3. SAMPLE GAME VALIDATION (check referee assignments)
            sample_size = min(5, len(rows))
            for i, game in enumerate(rows[:sample_size]):
                if not isinstance(game, dict):
                    try:
                        notify_error(
                            title="NBA.com Referee Assignments - Invalid Game Type",
                            message=f"Game {i} has invalid type for date {self.opts['formatted_date']}",
                            details={
                                'scraper': 'nbac_referee_assignments',
                                'date': self.opts['formatted_date'],
                                'game_index': i,
                                'game_type': type(game).__name__
                            },
                            processor_name="NBA.com Referee Assignments Scraper"
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send notification: {notify_ex}")
                    raise DownloadDataException(f"Game {i} is not a dict: {type(game)}")
                    
                # Check for essential game fields
                required_fields = ['game_id', 'home_team', 'away_team', 'official1']
                for field in required_fields:
                    if field not in game:
                        try:
                            notify_error(
                                title="NBA.com Referee Assignments - Missing Game Field",
                                message=f"Game {i} missing required field '{field}' for date {self.opts['formatted_date']}",
                                details={
                                    'scraper': 'nbac_referee_assignments',
                                    'date': self.opts['formatted_date'],
                                    'game_index': i,
                                    'missing_field': field,
                                    'available_fields': list(game.keys())[:10]
                                },
                                processor_name="NBA.com Referee Assignments Scraper"
                            )
                        except Exception as notify_ex:
                            logger.warning(f"Failed to send notification: {notify_ex}")
                        raise DownloadDataException(f"Game {i} missing required field: {field}")
                
                # Validate referee assignments (should have at least official1)
                if not game.get('official1'):
                    try:
                        notify_error(
                            title="NBA.com Referee Assignments - Missing Official",
                            message=f"Game {i} missing primary official assignment for date {self.opts['formatted_date']}",
                            details={
                                'scraper': 'nbac_referee_assignments',
                                'date': self.opts['formatted_date'],
                                'game_index': i,
                                'game_id': game.get('game_id'),
                                'matchup': f"{game.get('away_team')} @ {game.get('home_team')}"
                            },
                            processor_name="NBA.com Referee Assignments Scraper"
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send notification: {notify_ex}")
                    raise DownloadDataException(f"Game {i} missing primary official assignment")
            
            # 4. DATE CONSISTENCY
            expected_date = self.opts['formatted_date']
            date_mismatches = 0
            for i, game in enumerate(rows[:sample_size]):
                game_date = game.get('game_date', '')
                # Convert MM/DD/YYYY to YYYY-MM-DD for comparison
                if game_date:
                    try:
                        parsed_date = datetime.strptime(game_date, "%m/%d/%Y")
                        formatted_game_date = parsed_date.strftime("%Y-%m-%d")
                        if formatted_game_date != expected_date:
                            date_mismatches += 1
                            logger.warning(f"Game {i} date mismatch: expected {expected_date}, got {formatted_game_date}")
                    except ValueError:
                        logger.warning(f"Game {i} has invalid date format: {game_date}")
            
            if date_mismatches > 0:
                try:
                    notify_warning(
                        title="NBA.com Referee Assignments - Date Mismatches",
                        message=f"{date_mismatches} games have date mismatches for expected date {expected_date}",
                        details={
                            'scraper': 'nbac_referee_assignments',
                            'date': expected_date,
                            'mismatches': date_mismatches,
                            'sample_size': sample_size
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
            
            logger.info(f"✅ Referee validation passed: {game_count} games")
            
            # Send success notification
            try:
                notify_info(
                    title="NBA.com Referee Assignments - Download Complete",
                    message=f"Successfully downloaded referee assignments for date {self.opts['formatted_date']}",
                    details={
                        'scraper': 'nbac_referee_assignments',
                        'date': self.opts['formatted_date'],
                        'season': self.opts['season'],
                        'game_count': game_count,
                        'url': self.url
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
                
        except DownloadDataException:
            # Re-raise validation exceptions (already notified above)
            raise
        except Exception as e:
            # Catch any unexpected validation errors
            try:
                notify_error(
                    title="NBA.com Referee Assignments - Enhanced Validation Failed",
                    message=f"Unexpected enhanced validation error for date {self.opts['formatted_date']}: {str(e)}",
                    details={
                        'scraper': 'nbac_referee_assignments',
                        'date': self.opts['formatted_date'],
                        'error_type': type(e).__name__,
                        'error': str(e)
                    },
                    processor_name="NBA.com Referee Assignments Scraper"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise

    # ------------------------------------------------------------------ #
    # Transform (wrap with metadata)
    # ------------------------------------------------------------------ #
    def transform_data(self) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        
        # Count games across all leagues
        total_games = 0
        nba_games = len(self.decoded_data.get("nba", {}).get("Table", {}).get("rows", []))
        gl_games = len(self.decoded_data.get("gl", {}).get("Table", {}).get("rows", []))
        wnba_games = len(self.decoded_data.get("wnba", {}).get("Table", {}).get("rows", []))
        total_games = nba_games + gl_games + wnba_games
        
        # Extract replay center officials
        replay_officials = self.decoded_data.get("nba", {}).get("Table1", {}).get("rows", [])

        self.data: Dict[str, Any] = {
            "metadata": {
                "date": self.opts["formatted_date"],
                "season": self.opts["season"],
                "fetchedUtc": ts,
                "gameCount": {
                    "nba": nba_games,
                    "gLeague": gl_games,
                    "wnba": wnba_games,
                    "total": total_games
                },
                "replayCenterOfficials": len(replay_officials),
            },
            "refereeAssignments": self.decoded_data,
        }
        
        # Add production validation
        if nba_games > 0:  # Only validate if NBA games exist
            self.validate_referee_data()

    # ------------------------------------------------------------------ #
    # Only save if we have reasonable data
    # ------------------------------------------------------------------ #
    def should_save_data(self) -> bool:
        if not isinstance(self.data, dict):
            return False
        
        # Save even if no games (could be off-season) but ensure we got valid response
        metadata = self.data.get("metadata", {})
        return "fetchedUtc" in metadata

    # ------------------------------------------------------------------ #
    # Stats line
    # ------------------------------------------------------------------ #
    def get_scraper_stats(self) -> dict:
        metadata = self.data.get("metadata", {})
        game_counts = metadata.get("gameCount", {})
        
        return {
            "date": self.opts["formatted_date"],
            "season": self.opts["season"],
            "nba_games": game_counts.get("nba", 0),
            "g_league_games": game_counts.get("gLeague", 0),
            "wnba_games": game_counts.get("wnba", 0),
            "total_games": game_counts.get("total", 0),
            "replay_officials": metadata.get("replayCenterOfficials", 0),
        }


# --------------------------------------------------------------------------- #
# MIXIN-BASED Flask and CLI entry points
# --------------------------------------------------------------------------- #

# Use the mixin's utility to create the Flask app
create_app = convert_existing_flask_scraper(GetNbaComRefereeAssignments)

# Use the mixin's main function generator
if __name__ == "__main__":
    main = GetNbaComRefereeAssignments.create_cli_and_flask_main()
    main()