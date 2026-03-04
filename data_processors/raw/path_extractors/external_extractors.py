"""
Path extractors for external data sources and projection scrapers.

Handles:
- NumberFire projections
- FantasyPros projections
- TeamRankings team stats
- Hashtag Basketball DvP
- RotoWire lineups
- Covers referee stats
"""

import logging
import re

from .base import PathExtractor

logger = logging.getLogger(__name__)


class NumberFireProjectionsExtractor(PathExtractor):
    """Extract options from NumberFire projections paths."""

    PATTERN = re.compile(r'projections/numberfire/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: projections/numberfire/{date}/{timestamp}.json
        """
        parts = path.split('/')
        try:
            idx = parts.index('numberfire')
            if idx + 1 < len(parts):
                return {'game_date': parts[idx + 1]}
        except (ValueError, IndexError) as e:
            logger.warning(f"Could not extract from NumberFire path: {path}: {e}")
        return {}


class FantasyProsProjectionsExtractor(PathExtractor):
    """Extract options from FantasyPros projections paths."""

    PATTERN = re.compile(r'projections/fantasypros/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: projections/fantasypros/{date}/{timestamp}.json
        """
        parts = path.split('/')
        try:
            idx = parts.index('fantasypros')
            if idx + 1 < len(parts):
                return {'game_date': parts[idx + 1]}
        except (ValueError, IndexError) as e:
            logger.warning(f"Could not extract from FantasyPros path: {path}: {e}")
        return {}


class TeamRankingsStatsExtractor(PathExtractor):
    """Extract options from TeamRankings team stats paths."""

    PATTERN = re.compile(r'external/teamrankings/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: external/teamrankings/{date}/{timestamp}.json
        """
        parts = path.split('/')
        try:
            idx = parts.index('teamrankings')
            if idx + 1 < len(parts):
                return {'game_date': parts[idx + 1]}
        except (ValueError, IndexError) as e:
            logger.warning(f"Could not extract from TeamRankings path: {path}: {e}")
        return {}


class HashtagBasketballDvpExtractor(PathExtractor):
    """Extract options from Hashtag Basketball DvP paths."""

    PATTERN = re.compile(r'external/hashtagbasketball/dvp/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: external/hashtagbasketball/dvp/{date}/{timestamp}.json
        """
        parts = path.split('/')
        try:
            idx = parts.index('dvp')
            if idx + 1 < len(parts):
                return {'game_date': parts[idx + 1]}
        except (ValueError, IndexError) as e:
            logger.warning(f"Could not extract from DvP path: {path}: {e}")
        return {}


class RotoWireLineupsExtractor(PathExtractor):
    """Extract options from RotoWire lineups paths."""

    PATTERN = re.compile(r'external/rotowire/lineups/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: external/rotowire/lineups/{date}/{timestamp}.json
        """
        parts = path.split('/')
        try:
            idx = parts.index('lineups')
            if idx + 1 < len(parts):
                return {'game_date': parts[idx + 1]}
        except (ValueError, IndexError) as e:
            logger.warning(f"Could not extract from RotoWire path: {path}: {e}")
        return {}


class CoversRefereeStatsExtractor(PathExtractor):
    """Extract options from Covers referee stats paths."""

    PATTERN = re.compile(r'external/covers/referee-stats/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: external/covers/referee-stats/{season}/{timestamp}.json
        """
        parts = path.split('/')
        try:
            idx = parts.index('referee-stats')
            if idx + 1 < len(parts):
                return {'season': parts[idx + 1]}
        except (ValueError, IndexError) as e:
            logger.warning(f"Could not extract from Covers path: {path}: {e}")
        return {}


class NBATrackingStatsExtractor(PathExtractor):
    """Extract options from NBA tracking stats paths."""

    PATTERN = re.compile(r'external/nba-tracking/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: external/nba-tracking/{date}/{timestamp}.json
        """
        parts = path.split('/')
        try:
            idx = parts.index('nba-tracking')
            if idx + 1 < len(parts):
                return {'game_date': parts[idx + 1]}
        except (ValueError, IndexError) as e:
            logger.warning(f"Could not extract from NBA tracking path: {path}: {e}")
        return {}


class VSiNBettingSplitsExtractor(PathExtractor):
    """Extract options from VSiN betting splits paths."""

    PATTERN = re.compile(r'external/vsin/betting-splits/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: external/vsin/betting-splits/{date}/{timestamp}.json
        """
        parts = path.split('/')
        try:
            idx = parts.index('betting-splits')
            if idx + 1 < len(parts):
                return {'game_date': parts[idx + 1]}
        except (ValueError, IndexError) as e:
            logger.warning(f"Could not extract from VSiN path: {path}: {e}")
        return {}


class DailyFantasyFuelProjectionsExtractor(PathExtractor):
    """Extract options from DailyFantasyFuel projections paths."""

    PATTERN = re.compile(r'projections/dailyfantasyfuel/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: projections/dailyfantasyfuel/{date}/{timestamp}.json
        """
        parts = path.split('/')
        try:
            idx = parts.index('dailyfantasyfuel')
            if idx + 1 < len(parts):
                return {'game_date': parts[idx + 1]}
        except (ValueError, IndexError) as e:
            logger.warning(f"Could not extract from DFF path: {path}: {e}")
        return {}


class DimersProjectionsExtractor(PathExtractor):
    """Extract options from Dimers projections paths."""

    PATTERN = re.compile(r'projections/dimers/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: projections/dimers/{date}/{timestamp}.json
        """
        parts = path.split('/')
        try:
            idx = parts.index('dimers')
            if idx + 1 < len(parts):
                return {'game_date': parts[idx + 1]}
        except (ValueError, IndexError) as e:
            logger.warning(f"Could not extract from Dimers path: {path}: {e}")
        return {}
