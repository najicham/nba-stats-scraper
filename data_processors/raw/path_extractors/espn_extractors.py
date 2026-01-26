"""
ESPN path extractors.

Handles:
- Boxscores
- Rosters
- Scoreboard
"""

import logging
import re

from .base import PathExtractor


logger = logging.getLogger(__name__)


class ESPNBoxscoresExtractor(PathExtractor):
    """Extract options from ESPN boxscores paths."""

    PATTERN = re.compile(r'espn/boxscores/(\d{4}-\d{2}-\d{2})/game_([^/]+)/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: /espn/boxscores/{date}/game_{id}/{timestamp}.json
        """
        match = self.PATTERN.search(path)
        if match:
            return {
                'game_date': match.group(1),
                'espn_game_id': match.group(2)
            }
        return {}


class ESPNRostersExtractor(PathExtractor):
    """Extract options from ESPN rosters paths."""

    PATTERN = re.compile(r'espn/rosters/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: espn/rosters/{date}/team_{team_abbr}/{timestamp}.json
        """
        parts = path.split('/')
        opts = {}

        # Extract date (YYYY-MM-DD format)
        for part in parts:
            if len(part) == 10 and part.count('-') == 2:
                try:
                    opts['roster_date'] = part
                    break
                except (KeyError, TypeError) as e:
                    logger.warning(f"Failed to set roster_date from path part '{part}': {e}")

        # Extract team abbreviation from team_{abbr} folder
        for part in parts:
            if part.startswith('team_') and len(part) > 5:
                opts['team_abbr'] = part[5:]  # Remove 'team_' prefix
                break

        return opts


class ESPNScoreboardExtractor(PathExtractor):
    """Extract options from ESPN scoreboard paths."""

    PATTERN = re.compile(r'espn/scoreboard/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: espn/scoreboard/{date}/{timestamp}.json
        """
        parts = path.split('/')
        if len(parts) >= 3:
            return {'game_date': parts[-2]}
        return {}
