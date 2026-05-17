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

    PATTERN = re.compile(r'mlb-stats-api/(schedule|lineups|box-scores|umpire-assignments)/(\d{4}-\d{2}-\d{2})/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from paths:
        - mlb-stats-api/schedule/{date}/{timestamp}.json
        - mlb-stats-api/lineups/{date}/{timestamp}.json
        - mlb-stats-api/box-scores/{date}/{timestamp}.json
        - mlb-stats-api/umpire-assignments/{date}/{timestamp}.json
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
    """Extract options from MLB OddsAPI game lines paths.

    Accepts TODAY/YESTERDAY literals (resolved to actual date) as a
    backstop for unresolved scraper opts. The deeper scraper-side fix
    is to ensure date resolution happens before path interpolation, but
    this extractor needs to handle whatever lands in GCS.
    """

    PATTERN = re.compile(r'mlb-odds-api/game-lines/(\d{4}-\d{2}-\d{2}|TODAY|YESTERDAY)/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: mlb-odds-api/game-lines/{date}/{timestamp}.json
        Falls back to extracting date from the timestamp (YYYYMMDD_HHMMSS)
        when the path segment is TODAY/YESTERDAY.
        """
        match = self.PATTERN.search(path)
        if not match:
            return {}
        date_str = match.group(1)
        if date_str in ('TODAY', 'YESTERDAY'):
            ts_match = re.search(r'/(\d{8})_\d{6}\.json', path)
            if ts_match:
                try:
                    game_date = datetime.strptime(ts_match.group(1), '%Y%m%d').date()
                    if date_str == 'YESTERDAY':
                        from datetime import timedelta as _td
                        game_date = game_date - _td(days=1)
                    return {'game_date': game_date}
                except ValueError as e:
                    logger.warning(f"Could not parse timestamp date from MLB game-lines path: {path}: {e}")
            from datetime import timezone as _tz
            today = datetime.now(_tz.utc).date()
            if date_str == 'YESTERDAY':
                from datetime import timedelta as _td
                today = today - _td(days=1)
            logger.warning(f"MLB game-lines path used {date_str} literal with no timestamp; falling back to {today}: {path}")
            return {'game_date': today}
        try:
            game_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            return {'game_date': game_date}
        except ValueError as e:
            logger.warning(f"Could not parse date from MLB game-lines path: {path}: {e}")
            return {}


class MLBOddsAPIEventsExtractor(PathExtractor):
    """Extract options from MLB OddsAPI events paths."""

    PATTERN = re.compile(r'mlb-odds-api/events/(\d{4}-\d{2}-\d{2}|TODAY|YESTERDAY)/')

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
