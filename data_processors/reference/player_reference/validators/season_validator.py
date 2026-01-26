"""
Season Validator

Prevents processing historical seasons with roster registry processor.
Roster data is for current season only - historical data comes from gamebook.
"""

import logging
from datetime import date
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class SeasonValidator:
    """
    Validates that only current season is processed (unless backfill allowed).

    Roster registry is designed for current-season real-time updates.
    Historical roster data should come from gamebook processor.
    """

    @staticmethod
    def validate(
        season_year: int,
        allow_backfill: bool = False
    ) -> Optional[Dict]:
        """
        Validate that season is current season.

        Args:
            season_year: Season year being processed
            allow_backfill: If True, allow processing historical seasons

        Returns:
            None if validation passes
            Dict with error details if validation fails
        """
        # Calculate current season year
        current_season_year = date.today().year if date.today().month >= 10 else date.today().year - 1

        if season_year < current_season_year and not allow_backfill:
            error_msg = (
                f"Cannot process historical season {season_year}-{season_year+1}. "
                f"Current season is {current_season_year}-{current_season_year+1}. "
                f"Roster processor is for current season only. "
                f"Use --allow-backfill flag only if you need to fix historical roster data."
            )
            logger.error(error_msg)

            return {
                'status': 'blocked',
                'reason': error_msg,
                'season_year': season_year,
                'current_season_year': current_season_year,
                'protection_layer': 'season_protection'
            }

        return None
