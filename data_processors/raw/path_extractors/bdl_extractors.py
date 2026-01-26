"""
Ball-Don't-Lie path extractors.

Handles:
- Standings
- Injuries
- Live boxscores
- Player box scores
- Boxscores
- Active players
"""

import json
import logging
import re
from datetime import datetime

from google.api_core.exceptions import GoogleAPIError, NotFound

from shared.clients import get_storage_client
from .base import PathExtractor


logger = logging.getLogger(__name__)


class BDLStandingsExtractor(PathExtractor):
    """Extract options from Ball-Don't-Lie standings paths."""

    PATTERN = re.compile(r'ball-dont-lie/standings/(\d{4}-\d{2})/(\d{4}-\d{2}-\d{2})/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: ball-dont-lie/standings/2024-25/2025-01-15/timestamp.json
        """
        match = self.PATTERN.search(path)
        if not match:
            raise ValueError(f"Could not extract standings info from path: {path}")

        season_formatted = match.group(1)  # "2024-25"
        date_str = match.group(2)  # "2025-01-15"

        try:
            date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
            season_year = int(season_formatted.split('-')[0])

            return {
                'date_recorded': date_obj,
                'season_year': season_year
            }
        except (ValueError, IndexError) as e:
            logger.warning(f"Could not parse standings date/season from path: {path}: {e}")
            return {}


class BDLInjuriesExtractor(PathExtractor):
    """Extract options from Ball-Don't-Lie injuries paths."""

    PATTERN = re.compile(r'ball-dont-lie/injuries/(\d{4}-\d{2}-\d{2})/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: ball-dont-lie/injuries/2025-01-15/timestamp.json
        """
        match = self.PATTERN.search(path)
        if not match:
            raise ValueError(f"Could not extract injuries info from path: {path}")

        date_str = match.group(1)

        try:
            scrape_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            season_year = scrape_date.year if scrape_date.month >= 10 else scrape_date.year - 1

            return {
                'scrape_date': scrape_date,
                'season_year': season_year
            }
        except ValueError as e:
            logger.warning(f"Could not parse injuries date from path: {path}: {e}")
            return {}


class BDLLiveBoxscoresExtractor(PathExtractor):
    """Extract options from Ball-Don't-Lie live boxscores paths."""

    PATTERN = re.compile(r'ball-dont-lie/live-boxscores/(\d{4}-\d{2}-\d{2})/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: ball-dont-lie/live-boxscores/2025-12-27/timestamp.json
        """
        match = self.PATTERN.search(path)
        if not match:
            raise ValueError(f"Could not extract live boxscores info from path: {path}")

        date_str = match.group(1)

        try:
            game_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            return {'game_date': game_date}
        except ValueError as e:
            logger.warning(f"Could not parse live boxscores date from path: {path}: {e}")
            return {}


class BDLPlayerBoxScoresExtractor(PathExtractor):
    """
    Extract options from Ball-Don't-Lie player box scores paths.

    IMPORTANT: For backfill files, the file path date may differ from the actual
    game dates in the data. We read the JSON to get the correct dates.
    """

    PATTERN = re.compile(r'ball-dont-lie/player-box-scores/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: ball-dont-lie/player-box-scores/{date}/timestamp.json

        Reads the JSON file to get actual start_date and end_date from the data.
        """
        try:
            # Download and read the JSON file to get actual dates
            storage_client = get_storage_client()
            bucket_name = 'nba-scraped-data'
            bucket_obj = storage_client.bucket(bucket_name)
            blob = bucket_obj.blob(path)
            file_content = blob.download_as_text()
            file_data = json.loads(file_content)

            # Get actual date range from the data
            start_date_str = file_data.get('startDate')
            end_date_str = file_data.get('endDate')

            if start_date_str and end_date_str:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()

                # Use start_date for run history tracking (single date key)
                season_year = start_date.year if start_date.month >= 10 else start_date.year - 1

                logger.info(
                    f"BDL player-box-scores: actual dates {start_date} to {end_date} "
                    f"(file created {path.split('/')[-2]})"
                )

                return {
                    'game_date': start_date,
                    'start_date': start_date,
                    'end_date': end_date,
                    'is_multi_date': (start_date != end_date),
                    'season_year': season_year
                }

        except (GoogleAPIError, NotFound, json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Failed to read dates from BDL player-box-scores file: {e}")

        # Fallback to file path parsing
        parts = path.split('/')
        if len(parts) >= 4:
            try:
                date_str = parts[-2]
                game_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                season_year = game_date.year if game_date.month >= 10 else game_date.year - 1

                logger.warning(f"BDL player-box-scores: using file path date {game_date} (startDate/endDate not in JSON)")

                return {
                    'game_date': game_date,
                    'season_year': season_year
                }
            except ValueError as e:
                logger.warning(f"Could not parse date from player-box-scores path: {date_str}: {e}")

        return {}


class BDLBoxscoresExtractor(PathExtractor):
    """Extract options from Ball-Don't-Lie boxscores paths."""

    PATTERN = re.compile(r'ball-dont-lie/boxscores/(\d{4}-\d{2}-\d{2})/')

    def matches(self, path: str) -> bool:
        # Must NOT match player-box-scores or live-boxscores
        if 'player-box-scores' in path or 'live-boxscores' in path:
            return False
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: ball-dont-lie/boxscores/2021-12-04/timestamp.json
        """
        match = self.PATTERN.search(path)
        if not match:
            raise ValueError(f"Could not extract boxscores info from path: {path}")

        date_str = match.group(1)

        try:
            game_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            season_year = game_date.year if game_date.month >= 10 else game_date.year - 1

            return {
                'game_date': game_date,
                'season_year': season_year
            }
        except ValueError as e:
            logger.warning(f"Could not parse boxscores date from path: {path}: {e}")
            return {}


class BDLActivePlayersExtractor(PathExtractor):
    """Extract options from Ball-Don't-Lie active players paths."""

    PATTERN = re.compile(r'ball-dont-lie/active-players/(\d{4}-\d{2}-\d{2})/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: ball-dont-lie/active-players/2025-01-15/timestamp.json
        """
        match = self.PATTERN.search(path)
        if not match:
            raise ValueError(f"Could not extract active players info from path: {path}")

        date_str = match.group(1)

        try:
            collection_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            season_year = collection_date.year if collection_date.month >= 10 else collection_date.year - 1

            return {
                'collection_date': collection_date,
                'season_year': season_year
            }
        except ValueError as e:
            logger.warning(f"Could not parse active players date from path: {path}: {e}")
            return {}
