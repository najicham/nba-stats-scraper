"""
BigDataBall path extractors.

Handles:
- Play-by-play CSV files
"""

import logging
import re
from datetime import datetime

from .base import PathExtractor


logger = logging.getLogger(__name__)


class BigDataBallPbpExtractor(PathExtractor):
    """Extract options from BigDataBall play-by-play paths."""

    PATTERN = re.compile(r'(big-data-ball|bigdataball)/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path:
        - /big-data-ball/{season}/{date}/game_{id}/{filename}.csv
        - /bigdataball/{season}/{date}/game_{id}/{filename}.csv
        """
        parts = path.split('/')
        opts = {}

        # Find date part (YYYY-MM-DD format)
        for part in parts:
            if re.match(r'\d{4}-\d{2}-\d{2}', part):
                opts['game_date'] = part

                # Calculate season year from game date
                try:
                    game_date_obj = datetime.strptime(part, '%Y-%m-%d').date()
                    season_year = game_date_obj.year if game_date_obj.month >= 10 else game_date_obj.year - 1
                    opts['season_year'] = season_year
                except ValueError as e:
                    logger.warning(f"Could not parse date from BigDataBall path: {part}: {e}")
                break

        # Find game ID from game_{gameId} directory
        for part in parts:
            if part.startswith('game_'):
                opts['game_id'] = part.replace('game_', '')
                break

        return opts


class BasketballRefRosterExtractor(PathExtractor):
    """Extract options from Basketball Reference roster paths."""

    PATTERN = re.compile(r'basketball-ref/season-rosters/(\d{4}-\d{2})/([^/]+)\.json')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: basketball_reference/season_rosters/2023-24/LAL.json
        """
        match = self.PATTERN.search(path)
        if match:
            season_str = match.group(1)  # "2023-24"
            team_abbrev = match.group(2)  # "LAL"

            try:
                season_year = int(season_str.split('-')[0])  # 2023
                return {
                    'season_year': season_year,
                    'team_abbrev': team_abbrev
                }
            except (ValueError, IndexError) as e:
                logger.warning(f"Could not parse season from Basketball Reference path: {path}: {e}")

        return {}
