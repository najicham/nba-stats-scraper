"""
Prop Calculator for Player Game Summary

Calculates prop betting results with OddsAPI + BettingPros fallback.

Extracted from: player_game_summary_processor.py::_process_single_player_game()
"""

import logging
from typing import Optional, Tuple
import pandas as pd

logger = logging.getLogger(__name__)


class PropCalculator:
    """
    Calculate prop betting outcomes for player performances.

    Handles:
    - Over/under result calculation
    - Margin calculation (actual vs line)
    - Line movement tracking (future enhancement)
    """

    @staticmethod
    def calculate_prop_outcome(
        points: Optional[float],
        points_line: Optional[float]
    ) -> Tuple[Optional[str], Optional[float]]:
        """
        Calculate prop betting outcome.

        Args:
            points: Actual points scored
            points_line: Prop betting line

        Returns:
            Tuple of (over_under_result, margin)
            - over_under_result: 'OVER', 'UNDER', or None
            - margin: Difference between actual and line, or None
        """
        if pd.notna(points) and pd.notna(points_line):
            # NOTE: Using >= means pushes (points == line) are counted as OVER.
            # In real betting, pushes typically result in a refund (neither over nor under).
            # This simplification is acceptable for accuracy tracking but may slightly
            # inflate OVER hit rate when there are many pushes.
            over_under_result = 'OVER' if points >= points_line else 'UNDER'
            margin = float(points) - float(points_line)
            return over_under_result, round(margin, 2)

        return None, None

    @staticmethod
    def get_prop_fields(
        points: Optional[float],
        points_line: Optional[float],
        points_line_source: Optional[str] = None
    ) -> dict:
        """
        Get all prop-related fields for a player game record.

        Args:
            points: Actual points scored
            points_line: Prop betting line
            points_line_source: Source of the prop line

        Returns:
            Dictionary with prop fields
        """
        over_under_result, margin = PropCalculator.calculate_prop_outcome(
            points, points_line
        )

        return {
            'points_line': float(points_line) if pd.notna(points_line) else None,
            'over_under_result': over_under_result,
            'margin': margin,
            'opening_line': None,  # Pass 3 enhancement
            'line_movement': None,
            'points_line_source': points_line_source,
            'opening_line_source': None,
        }
