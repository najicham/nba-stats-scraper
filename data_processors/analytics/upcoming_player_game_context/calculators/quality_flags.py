"""
Data Quality Flags Calculator

Calculates data quality metrics based on sample size and game context completeness.

Extracted from upcoming_player_game_context_processor.py for maintainability.
"""

import logging
from typing import Dict, List
import pandas as pd
from shared.processors.patterns.quality_columns import build_quality_columns_with_legacy

logger = logging.getLogger(__name__)


class QualityFlagsCalculator:
    """
    Calculator for data quality flags and metrics.

    Determines quality tier (gold/silver/bronze) based on:
    - Historical data sample size
    - Game context completeness (spreads, totals)
    """

    def __init__(
        self,
        min_games_for_high_quality: int = 10,
        min_games_for_medium_quality: int = 5
    ):
        """
        Initialize quality calculator.

        Args:
            min_games_for_high_quality: Minimum games for 'gold' tier
            min_games_for_medium_quality: Minimum games for 'silver' tier
        """
        self.min_games_for_high_quality = min_games_for_high_quality
        self.min_games_for_medium_quality = min_games_for_medium_quality

    def calculate_data_quality(
        self,
        historical_data: pd.DataFrame,
        game_lines_info: Dict
    ) -> Dict:
        """
        Calculate data quality metrics using centralized helper.

        Args:
            historical_data: DataFrame of historical boxscores
            game_lines_info: Dict with game spread/total info

        Returns:
            Dict with quality columns (tier, score, issues, etc.)
        """
        # Sample size determines tier
        games_count = len(historical_data)
        if games_count >= self.min_games_for_high_quality:
            tier = 'gold'
            score = 95.0
        elif games_count >= self.min_games_for_medium_quality:
            tier = 'silver'
            score = 75.0
        else:
            tier = 'bronze'
            score = 50.0

        # Build quality issues list
        issues = []
        if game_lines_info.get('game_spread') is None:
            issues.append('missing_game_spread')
        if game_lines_info.get('game_total') is None:
            issues.append('missing_game_total')
        if games_count < 3:
            issues.append(f'thin_sample:{games_count}/3')

        primary_source = 'nbac_gamebook_player_stats'

        quality_cols = build_quality_columns_with_legacy(
            tier=tier,
            score=score,
            issues=issues,
            sources=[primary_source],
        )

        quality_cols['primary_source_used'] = primary_source
        quality_cols['processed_with_issues'] = len(issues) > 0

        return quality_cols
