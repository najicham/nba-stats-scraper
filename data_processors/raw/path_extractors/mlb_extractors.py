"""
MLB path extractors.

Handles:
- Ball-Don't-Lie MLB pitcher/batter stats
- MLB Stats API schedule and lineups
- MLB OddsAPI props, game lines, and events
"""

import logging
import re
from datetime import datetime

from .base import PathExtractor


logger = logging.getLogger(__name__)


class MLBBDLStatsExtractor(PathExtractor):
    """Extract options from Ball-Don't-Lie MLB stats paths."""

    PATTERN = re.compile(r'ball-dont-lie/mlb-(pitcher|batter)-stats/(\d{4}-\d{2}-\d{2})/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from paths:
        - ball-dont-lie/mlb-pitcher-stats/{date}/{timestamp}.json
        - ball-dont-lie/mlb-batter-stats/{date}/{timestamp}.json
        """
        match = self.PATTERN.search(path)
        if match:
            date_str = match.group(2)
            try:
                game_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                return {'game_date': game_date}
            except ValueError as e:
                logger.warning(f"Could not parse date from MLB BDL path: {path}: {e}")

        return {}


class MLBStatsAPIExtractor(PathExtractor):
    """Extract options from MLB Stats API paths."""

    PATTERN = re.compile(r'mlb-stats-api/(schedule|lineups)/(\d{4}-\d{2}-\d{2})/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from paths:
        - mlb-stats-api/schedule/{date}/{timestamp}.json
        - mlb-stats-api/lineups/{date}/{timestamp}.json
        """
        match = self.PATTERN.search(path)
        if match:
            date_str = match.group(2)
            try:
                game_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                return {'game_date': game_date}
            except ValueError as e:
                logger.warning(f"Could not parse date from MLB Stats API path: {path}: {e}")

        return {}


class MLBOddsAPIPropsExtractor(PathExtractor):
    """Extract options from MLB OddsAPI props paths."""

    PATTERN = re.compile(r'mlb-odds-api/(pitcher|batter)-props/(\d{4}-\d{2}-\d{2})/([^/]+)/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from paths:
        - mlb-odds-api/pitcher-props/{date}/{event_id}-{teams}/{timestamp}-snap-{snap}.json
        - mlb-odds-api/batter-props/{date}/{event_id}-{teams}/{timestamp}-snap-{snap}.json
        """
        match = self.PATTERN.search(path)
        if match:
            date_str = match.group(2)
            event_teams = match.group(3)

            try:
                game_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                return {
                    'game_date': game_date,
                    'event_teams': event_teams
                }
            except ValueError as e:
                logger.warning(f"Could not parse date from MLB props path: {path}: {e}")

        return {}


class MLBOddsAPIGameLinesExtractor(PathExtractor):
    """Extract options from MLB OddsAPI game lines paths."""

    PATTERN = re.compile(r'mlb-odds-api/game-lines/(\d{4}-\d{2}-\d{2})/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: mlb-odds-api/game-lines/{date}/{timestamp}.json
        """
        match = self.PATTERN.search(path)
        if match:
            date_str = match.group(1)
            try:
                game_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                return {'game_date': game_date}
            except ValueError as e:
                logger.warning(f"Could not parse date from MLB game-lines path: {path}: {e}")

        return {}


class MLBOddsAPIEventsExtractor(PathExtractor):
    """Extract options from MLB OddsAPI events paths."""

    PATTERN = re.compile(r'mlb-odds-api/events/(\d{4}-\d{2}-\d{2})/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: mlb-odds-api/events/{date}/{timestamp}.json
        """
        match = self.PATTERN.search(path)
        if match:
            date_str = match.group(1)
            try:
                game_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                return {'game_date': game_date}
            except ValueError as e:
                logger.warning(f"Could not parse date from MLB events path: {path}: {e}")

        return {}
