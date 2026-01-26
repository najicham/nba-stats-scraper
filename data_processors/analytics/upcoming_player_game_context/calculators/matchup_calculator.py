#!/usr/bin/env python3
"""
Path: data_processors/analytics/upcoming_player_game_context/calculators/matchup_calculator.py

Matchup Calculator - Calculate opponent matchup metrics for player context.

This module calculates opponent-specific metrics that affect player performance:
- Pace metrics (pace differential, opponent pace)
- Free throw rate allowed
- Defensive/offensive ratings
- Variance metrics (volatility in opponent performance)
"""

import logging
from datetime import date
from typing import Optional

from ..team_context import TeamContextCalculator

logger = logging.getLogger(__name__)


class MatchupCalculator:
    """Calculate opponent matchup metrics for player context."""

    def __init__(self, bq_client, project_id: str):
        """
        Initialize matchup calculator.

        Args:
            bq_client: BigQuery client instance
            project_id: GCP project ID
        """
        self.team_calc = TeamContextCalculator(bq_client, project_id)

    def calculate_matchup_metrics(
        self,
        team_abbr: str,
        opponent_team_abbr: str,
        target_date: date
    ) -> dict:
        """
        Calculate all opponent matchup metrics.

        Args:
            team_abbr: Player's team abbreviation
            opponent_team_abbr: Opponent team abbreviation
            target_date: Game date

        Returns:
            Dict with matchup metrics:
            - pace_differential
            - opponent_pace_last_10
            - opponent_ft_rate_allowed
            - opponent_def_rating
            - opponent_off_rating
            - opponent_rebounding_rate
        """
        return {
            'pace_differential': self._calculate_pace_differential(
                team_abbr, opponent_team_abbr, target_date
            ),
            'opponent_pace_last_10': self._get_opponent_pace_last_10(
                opponent_team_abbr, target_date
            ),
            'opponent_ft_rate_allowed': self._get_opponent_ft_rate_allowed(
                opponent_team_abbr, target_date
            ),
            'opponent_def_rating': self._get_opponent_def_rating_last_10(
                opponent_team_abbr, target_date
            ),
            'opponent_off_rating': self._get_opponent_off_rating_last_10(
                opponent_team_abbr, target_date
            ),
            'opponent_rebounding_rate': self._get_opponent_rebounding_rate(
                opponent_team_abbr, target_date
            ),
        }

    def calculate_variance_metrics(self, opponent_team_abbr: str, target_date: date) -> dict:
        """
        Calculate opponent variance (volatility) metrics.

        Args:
            opponent_team_abbr: Opponent team abbreviation
            target_date: Game date

        Returns:
            Dict with variance metrics:
            - opponent_pace_variance
            - opponent_ft_rate_variance
            - opponent_def_rating_variance
            - opponent_off_rating_variance
            - opponent_rebounding_rate_variance
        """
        return {
            'opponent_pace_variance': self._get_opponent_pace_variance(
                opponent_team_abbr, target_date
            ),
            'opponent_ft_rate_variance': self._get_opponent_ft_rate_variance(
                opponent_team_abbr, target_date
            ),
            'opponent_def_rating_variance': self._get_opponent_def_rating_variance(
                opponent_team_abbr, target_date
            ),
            'opponent_off_rating_variance': self._get_opponent_off_rating_variance(
                opponent_team_abbr, target_date
            ),
            'opponent_rebounding_rate_variance': self._get_opponent_rebounding_rate_variance(
                opponent_team_abbr, target_date
            ),
        }

    # ========================================================================
    # Private Helper Methods - Delegate to TeamContextCalculator
    # ========================================================================

    def _calculate_pace_differential(
        self, team_abbr: str, opponent_team_abbr: str, target_date: date
    ) -> Optional[float]:
        """Calculate pace differential between teams."""
        return self.team_calc.calculate_pace_differential(
            team_abbr, opponent_team_abbr, target_date
        )

    def _get_opponent_pace_last_10(
        self, opponent_team_abbr: str, target_date: date
    ) -> Optional[float]:
        """Get opponent's pace over last 10 games."""
        return self.team_calc.get_opponent_pace_last_10(opponent_team_abbr, target_date)

    def _get_opponent_ft_rate_allowed(
        self, opponent_team_abbr: str, target_date: date
    ) -> Optional[float]:
        """Get opponent's free throw rate allowed."""
        return self.team_calc.get_opponent_ft_rate_allowed(opponent_team_abbr, target_date)

    def _get_opponent_def_rating_last_10(
        self, opponent_team_abbr: str, target_date: date
    ) -> Optional[float]:
        """Get opponent's defensive rating over last 10 games."""
        return self.team_calc.get_opponent_def_rating_last_10(opponent_team_abbr, target_date)

    def _get_opponent_off_rating_last_10(
        self, opponent_team_abbr: str, target_date: date
    ) -> Optional[float]:
        """Get opponent's offensive rating over last 10 games."""
        return self.team_calc.get_opponent_off_rating_last_10(opponent_team_abbr, target_date)

    def _get_opponent_rebounding_rate(
        self, opponent_team_abbr: str, target_date: date
    ) -> Optional[float]:
        """Get opponent's rebounding rate."""
        return self.team_calc.get_opponent_rebounding_rate(opponent_team_abbr, target_date)

    def _get_opponent_pace_variance(
        self, opponent_team_abbr: str, target_date: date
    ) -> Optional[float]:
        """Get variance in opponent's pace."""
        return self.team_calc.get_opponent_pace_variance(opponent_team_abbr, target_date)

    def _get_opponent_ft_rate_variance(
        self, opponent_team_abbr: str, target_date: date
    ) -> Optional[float]:
        """Get variance in opponent's free throw rate allowed."""
        return self.team_calc.get_opponent_ft_rate_variance(opponent_team_abbr, target_date)

    def _get_opponent_def_rating_variance(
        self, opponent_team_abbr: str, target_date: date
    ) -> Optional[float]:
        """Get variance in opponent's defensive rating."""
        return self.team_calc.get_opponent_def_rating_variance(opponent_team_abbr, target_date)

    def _get_opponent_off_rating_variance(
        self, opponent_team_abbr: str, target_date: date
    ) -> Optional[float]:
        """Get variance in opponent's offensive rating."""
        return self.team_calc.get_opponent_off_rating_variance(opponent_team_abbr, target_date)

    def _get_opponent_rebounding_rate_variance(
        self, opponent_team_abbr: str, target_date: date
    ) -> Optional[float]:
        """Get variance in opponent's rebounding rate."""
        return self.team_calc.get_opponent_rebounding_rate_variance(opponent_team_abbr, target_date)
