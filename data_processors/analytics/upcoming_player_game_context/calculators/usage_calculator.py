#!/usr/bin/env python3
"""
Path: data_processors/analytics/upcoming_player_game_context/calculators/usage_calculator.py

Usage Calculator - Calculate star teammate impact on player usage.

This module calculates metrics related to star teammate availability,
which affects player usage rates and opportunities:
- Star teammates out (injury/absence)
- Questionable star teammates
- Star tier analysis
"""

import logging
from datetime import date
from typing import Optional

from ..team_context import TeamContextCalculator

logger = logging.getLogger(__name__)


class UsageCalculator:
    """Calculate star teammate impact metrics for player context."""

    def __init__(self, bq_client, project_id: str):
        """
        Initialize usage calculator.

        Args:
            bq_client: BigQuery client instance
            project_id: GCP project ID
        """
        self.team_calc = TeamContextCalculator(bq_client, project_id)

    def calculate_usage_impact(self, team_abbr: str, target_date: date) -> dict:
        """
        Calculate star teammate usage impact metrics.

        When star teammates are out, remaining players typically see increased:
        - Usage rate (shot attempts per minute)
        - Assist opportunities
        - Defensive attention

        Args:
            team_abbr: Player's team abbreviation
            target_date: Game date

        Returns:
            Dict with usage impact metrics:
            - star_teammates_out: Number of star teammates out
            - questionable_star_teammates: Number of questionable star teammates
            - star_tier_out: Highest star tier out (1=superstar, 2=all-star, 3=starter)
        """
        return {
            'star_teammates_out': self._get_star_teammates_out(team_abbr, target_date),
            'questionable_star_teammates': self._get_questionable_star_teammates(
                team_abbr, target_date
            ),
            'star_tier_out': self._get_star_tier_out(team_abbr, target_date),
        }

    # ========================================================================
    # Private Helper Methods - Delegate to TeamContextCalculator
    # ========================================================================

    def _get_star_teammates_out(
        self, team_abbr: str, target_date: date
    ) -> Optional[int]:
        """Get number of star teammates out for a game."""
        return self.team_calc.get_star_teammates_out(team_abbr, target_date)

    def _get_questionable_star_teammates(
        self, team_abbr: str, target_date: date
    ) -> Optional[int]:
        """Get number of questionable star teammates for a game."""
        return self.team_calc.get_questionable_star_teammates(team_abbr, target_date)

    def _get_star_tier_out(
        self, team_abbr: str, target_date: date
    ) -> Optional[int]:
        """
        Get highest star tier out for a game.

        Returns:
            1: Superstar out (MVP candidate)
            2: All-star out
            3: Quality starter out
            None: No significant players out
        """
        return self.team_calc.get_star_tier_out(team_abbr, target_date)
