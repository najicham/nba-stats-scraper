"""
Odds-related path extractors.

Handles:
- OddsAPI game lines history
- BettingPros player props
"""

import logging
import re

from .base import PathExtractor


logger = logging.getLogger(__name__)


class OddsAPIGameLinesHistoryExtractor(PathExtractor):
    """Extract options from OddsAPI game lines history paths."""

    PATTERN = re.compile(r'odds-api/game-lines-history/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: odds-api/game-lines-history/date/hash-teams/file.json
        """
        parts = path.split('/')
        if len(parts) >= 4:
            opts = {
                'game_date': parts[-3],
                'game_hash_teams': parts[-2],
                'filename': parts[-1]
            }

            # Extract snapshot timestamp if available
            if 'snap-' in parts[-1]:
                snapshot_part = parts[-1].split('snap-')[-1].replace('.json', '')
                opts['snapshot_timestamp'] = snapshot_part

            return opts

        return {}


class BettingPropsExtractor(PathExtractor):
    """Extract options from BettingPros player props paths."""

    PATTERN = re.compile(r'bettingpros/player-props/')

    def matches(self, path: str) -> bool:
        return bool(self.PATTERN.search(path))

    def extract(self, path: str) -> dict:
        """
        Extract from path: /bettingpros/player-props/{market_type}/{date}/{timestamp}.json
        """
        parts = path.split('/')
        try:
            if 'player-props' in parts:
                market_idx = parts.index('player-props')
                if market_idx + 1 < len(parts):
                    return {'market_type': parts[market_idx + 1]}
        except (ValueError, IndexError) as e:
            logger.warning(f"Could not extract market type from BettingPros path: {path}: {e}")

        return {}
