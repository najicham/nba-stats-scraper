"""
Quality Scorer for Player Game Summary

Source coverage quality scoring logic.

Extracted from: player_game_summary_processor.py::_process_single_player_game()
"""

import logging
from typing import Dict, List
from shared.processors.patterns.quality_columns import build_quality_columns_with_legacy

logger = logging.getLogger(__name__)


class QualityScorer:
    """
    Calculate quality scores based on source coverage.

    Quality tiers:
    - gold: NBA.com gamebook (100% complete data, primary source)
    - silver: BDL fallback (85% complete, missing some fields)
    - bronze: Reconstructed/estimated data
    """

    @staticmethod
    def calculate_quality(
        primary_source: str,
        has_plus_minus: bool = True,
        has_shot_zones: bool = False
    ) -> Dict:
        """
        Calculate quality fields based on data sources.

        Args:
            primary_source: Primary source used ('nbac_gamebook' or 'bdl_boxscores')
            has_plus_minus: Whether plus_minus is available
            has_shot_zones: Whether shot zone data is available

        Returns:
            Dictionary with quality fields
        """
        # Determine tier and score
        if primary_source == 'nbac_gamebook':
            tier = 'gold'
            score = 100.0
            issues = []
        else:
            tier = 'silver'
            score = 85.0
            issues = ['backup_source_used']

        # Adjust score based on data completeness
        if not has_plus_minus:
            score -= 5.0
            issues.append('missing_plus_minus')

        if not has_shot_zones:
            score -= 5.0
            issues.append('missing_shot_zones')

        # Build sources list
        sources = [primary_source] if primary_source else ['unknown']

        return build_quality_columns_with_legacy(
            tier=tier,
            score=score,
            issues=issues,
            sources=sources
        )

    @staticmethod
    def get_additional_quality_fields(
        primary_source: str,
        shot_zones_estimated: bool = False
    ) -> Dict:
        """
        Get additional quality tracking fields.

        Args:
            primary_source: Primary source used
            shot_zones_estimated: Whether shot zones were estimated

        Returns:
            Dictionary with additional quality fields
        """
        from datetime import datetime, timezone

        return {
            'primary_source_used': primary_source,
            'processed_with_issues': False,
            'shot_zones_estimated': shot_zones_estimated if shot_zones_estimated else None,
            'quality_sample_size': None,  # Populated by Phase 4
            'quality_used_fallback': primary_source != 'nbac_gamebook',
            'quality_reconstructed': False,
            'quality_calculated_at': datetime.now(timezone.utc).isoformat(),
            'quality_metadata': {
                'sources_used': [primary_source],
                'early_season': False
            }
        }
