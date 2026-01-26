"""
NBA.com path extractors.

Handles:
- Scoreboard V2
- Player boxscores
- Play-by-play
- Referee assignments
- Schedule
- Gamebooks data
- Player movement
- Team boxscores
- Injury reports
- Player list
"""

import logging
import re
from datetime import datetime

from .base import PathExtractor


logger = logging.getLogger(__name__)


class NBAScoreboardV2Extractor(PathExtractor):
    """Extract options from NBA.com Scoreboard V2 paths."""

    PATTERN = re.compile(r'nba-com/scoreboard-v2/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: /nba-com/scoreboard-v2/{date}/{timestamp}.json
        """
        parts = path.split('/')
        if len(parts) >= 4:
            try:
                date_str = parts[-2]
                return {'scoreDate': date_str}
            except (IndexError, ValueError) as e:
                logger.warning(f"Could not extract date from scoreboard-v2 path: {path}: {e}")

        return {}


class NBAPlayerBoxscoresExtractor(PathExtractor):
    """Extract options from NBA.com player boxscores paths."""

    PATTERN = re.compile(r'nba-com/player-boxscores/(\d{4}-\d{2}-\d{2})/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: /nba-com/player-boxscores/2024-01-15/timestamp.json
        """
        match = self.PATTERN.search(path)
        if match:
            return {'date': match.group(1)}
        return {}


class NBAPlayByPlayExtractor(PathExtractor):
    """Extract options from NBA.com play-by-play paths."""

    PATTERN = re.compile(r'nba-com/play-by-play/(\d{4}-\d{2}-\d{2})/game_([^/]+)/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: /nba-com/play-by-play/{date}/game_{gameId}/{timestamp}.json
        """
        match = self.PATTERN.search(path)
        if match:
            return {
                'game_date': match.group(1),
                'nba_game_id': match.group(2)
            }
        return {}


class NBARefereeAssignmentsExtractor(PathExtractor):
    """Extract options from NBA.com referee assignments paths."""

    PATTERN = re.compile(r'nba-com/referee-assignments/(\d{4}-\d{2}-\d{2})/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: /nba-com/referee-assignments/{date}/{timestamp}.json
        """
        match = self.PATTERN.search(path)
        if not match:
            raise ValueError(f"Could not extract referee assignment info from path: {path}")

        date_str = match.group(1)

        try:
            assignment_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            season_year = assignment_date.year if assignment_date.month >= 10 else assignment_date.year - 1

            return {
                'assignment_date': assignment_date,
                'season_year': season_year
            }
        except ValueError as e:
            logger.warning(f"Could not parse referee assignment date from path: {path}: {e}")
            return {}


class NBAScheduleExtractor(PathExtractor):
    """Extract options from NBA.com schedule paths."""

    PATTERN = re.compile(r'nba-com/schedule/(\d{4}-\d{2})/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: /nba-com/schedule/{season}/{timestamp}.json
        """
        match = self.PATTERN.search(path)
        if not match:
            raise ValueError(f"Could not extract schedule info from path: {path}")

        season_str = match.group(1)  # "2023-24"

        try:
            season_year = int(season_str.split('-')[0])  # 2023
            return {
                'season_year': season_year,
                'season_nba_format': season_str
            }
        except (ValueError, IndexError) as e:
            logger.warning(f"Could not parse season from schedule path: {path}: {e}")
            return {}


class NBAGamebooksDataExtractor(PathExtractor):
    """Extract options from NBA.com gamebooks data paths."""

    PATTERN = re.compile(r'nba-com/gamebooks-data/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: nba-com/gamebooks-data/2025-12-21/20251221-TORBKN/timestamp.json
        """
        parts = path.split('/')
        for part in parts:
            # Find date part (YYYY-MM-DD format)
            if len(part) == 10 and part[4] == '-' and part[7] == '-':
                try:
                    game_date = datetime.strptime(part, '%Y-%m-%d').date()
                    season_year = game_date.year if game_date.month >= 10 else game_date.year - 1

                    return {
                        'game_date': game_date,
                        'date': str(game_date),
                        'season_year': season_year
                    }
                except ValueError as e:
                    logger.warning(f"Could not parse date from gamebook path: {path}: {e}")

        return {}


class NBAPlayerMovementExtractor(PathExtractor):
    """Extract options from NBA.com player movement paths."""

    PATTERN = re.compile(r'nba-com/player-movement/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: nba-com/player-movement/{...}

        Currently no specific extraction needed.
        """
        return {}


class NBATeamBoxscoreExtractor(PathExtractor):
    """Extract options from NBA.com team boxscore paths."""

    PATTERN = re.compile(r'nba-com/team-boxscore/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: nba-com/team-boxscore/{...}

        Currently no specific extraction needed.
        """
        return {}


class NBAInjuryReportExtractor(PathExtractor):
    """Extract options from NBA.com injury report paths."""

    PATTERN = re.compile(r'nba-com/injury-report-data/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: nba-com/injury-report-data/{...}

        Currently no specific extraction needed.
        """
        return {}


class NBAPlayerListExtractor(PathExtractor):
    """Extract options from NBA.com player list paths."""

    PATTERN = re.compile(r'nba-com/player-list/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: nba-com/player-list/{...}

        Currently no specific extraction needed.
        """
        return {}
