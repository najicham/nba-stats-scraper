"""Cache builder for constructing complete player daily cache records.

Combines aggregated data from all sources into a complete cache record with:
- Identifiers
- Recent performance metrics
- Team context
- Fatigue metrics
- Shot zone tendencies
- Demographics
- Completeness metadata
- Circuit breaker status
- Source tracking
"""

from datetime import datetime, timezone, date
from typing import Dict, Optional
import pandas as pd
from shared.config.source_coverage import get_tier_from_score


class CacheBuilder:
    """Build complete player daily cache records."""

    @staticmethod
    def build_record(
        player_lookup: str,
        analysis_date: date,
        stats_data: dict,
        team_data: dict,
        context_data: dict,
        shot_zone_data: dict,
        completeness_results: dict,
        circuit_breaker_status: dict,
        source_tracking: dict,
        source_hashes: dict,
        is_early_season: bool,
        is_season_boundary: bool,
        is_bootstrap: bool,
        shot_zone_available: bool,
        min_games_required: int,
        cache_version: str,
        context_row: pd.Series
    ) -> dict:
        """Build complete cache record from aggregated data.

        Args:
            player_lookup: Player ID
            analysis_date: Cache date
            stats_data: Aggregated stats from StatsAggregator
            team_data: Aggregated team context from TeamAggregator
            context_data: Context data from ContextAggregator
            shot_zone_data: Shot zone data from ShotZoneAggregator
            completeness_results: Multi-window completeness results
            circuit_breaker_status: Circuit breaker status dict
            source_tracking: Source tracking fields dict
            source_hashes: Source hash dict
            is_early_season: Early season flag
            is_season_boundary: Season boundary flag
            is_bootstrap: Bootstrap mode flag
            shot_zone_available: Whether shot zone data is available
            min_games_required: Minimum games required for production
            cache_version: Cache version string
            context_row: Raw context row for universal_player_id

        Returns:
            Complete cache record dictionary
        """
        # Extract completeness results
        comp_l5 = completeness_results['L5']
        comp_l10 = completeness_results['L10']
        comp_l7d = completeness_results['L7d']
        comp_l14d = completeness_results['L14d']

        # Check if all windows are production-ready
        all_windows_complete = (
            comp_l5['is_production_ready'] and
            comp_l10['is_production_ready'] and
            comp_l7d['is_production_ready'] and
            comp_l14d['is_production_ready']
        )

        # Build complete record
        record = {
            # Identifiers
            'player_lookup': player_lookup,
            'universal_player_id': str(context_row['universal_player_id']) if pd.notna(context_row['universal_player_id']) else None,
            'cache_date': analysis_date.isoformat(),

            # Recent performance (from StatsAggregator)
            'points_avg_last_5': stats_data['points_avg_last_5'],
            'points_avg_last_10': stats_data['points_avg_last_10'],
            'points_avg_season': stats_data['points_avg_season'],
            'points_std_last_10': stats_data['points_std_last_10'],
            'minutes_avg_last_10': stats_data['minutes_avg_last_10'],
            'usage_rate_last_10': stats_data['usage_rate_last_10'],
            'ts_pct_last_10': stats_data['ts_pct_last_10'],
            'games_played_season': stats_data['games_played_season'],

            # Team context (from TeamAggregator)
            'team_pace_last_10': team_data['team_pace_last_10'],
            'team_off_rating_last_10': team_data['team_off_rating_last_10'],
            'player_usage_rate_season': stats_data['player_usage_rate_season'],

            # Fatigue metrics (from ContextAggregator)
            'games_in_last_7_days': context_data['games_in_last_7_days'],
            'games_in_last_14_days': context_data['games_in_last_14_days'],
            'minutes_in_last_7_days': context_data['minutes_in_last_7_days'],
            'minutes_in_last_14_days': context_data['minutes_in_last_14_days'],
            'back_to_backs_last_14_days': context_data['back_to_backs_last_14_days'],
            'avg_minutes_per_game_last_7': context_data['avg_minutes_per_game_last_7'],
            'fourth_quarter_minutes_last_7': context_data['fourth_quarter_minutes_last_7'],

            # Shot zone tendencies (from ShotZoneAggregator)
            'primary_scoring_zone': shot_zone_data['primary_scoring_zone'],
            'paint_rate_last_10': shot_zone_data['paint_rate_last_10'],
            'three_pt_rate_last_10': shot_zone_data['three_pt_rate_last_10'],
            'assisted_rate_last_10': stats_data['assisted_rate_last_10'],

            # Demographics (from ContextAggregator)
            'player_age': context_data['player_age'],

            # Source tracking
            **source_tracking,

            # Early season flag
            'early_season_flag': is_early_season,
            'insufficient_data_reason': f"Only {stats_data['games_played_season']} games played, need {min_games_required} minimum" if is_early_season else None,

            # Shot zone availability tracking
            'shot_zone_data_available': shot_zone_available,

            # Completeness Checking Metadata
            # Standard Completeness Metrics (using L5 as primary)
            'expected_games_count': comp_l5['expected_count'],
            'actual_games_count': comp_l5['actual_count'],
            'completeness_percentage': comp_l5['completeness_pct'],
            'missing_games_count': comp_l5['missing_count'],

            # Quality tier based on completeness (L5 window)
            'quality_tier': get_tier_from_score(comp_l5['completeness_pct']).value,
            'cache_quality_score': comp_l5['completeness_pct'],

            # Production Readiness
            'is_production_ready': all_windows_complete,
            'data_quality_issues': [],

            # Circuit Breaker
            'last_reprocess_attempt_at': None,
            'reprocess_attempt_count': circuit_breaker_status['attempts'],
            'circuit_breaker_active': circuit_breaker_status['active'],
            'circuit_breaker_until': (
                circuit_breaker_status['until'].isoformat()
                if circuit_breaker_status['until'] else None
            ),

            # Bootstrap/Override
            'manual_override_required': False,
            'season_boundary_detected': is_season_boundary,
            'backfill_bootstrap_mode': is_bootstrap,
            'processing_decision_reason': 'processed_successfully',

            # Multi-Window Completeness (9 fields)
            'l5_completeness_pct': comp_l5['completeness_pct'],
            'l5_is_complete': comp_l5['is_production_ready'],
            'l10_completeness_pct': comp_l10['completeness_pct'],
            'l10_is_complete': comp_l10['is_production_ready'],
            'l7d_completeness_pct': comp_l7d['completeness_pct'],
            'l7d_is_complete': comp_l7d['is_production_ready'],
            'l14d_completeness_pct': comp_l14d['completeness_pct'],
            'l14d_is_complete': comp_l14d['is_production_ready'],
            'all_windows_complete': all_windows_complete,

            # Metadata
            'cache_version': cache_version,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'processed_at': datetime.now(timezone.utc).isoformat()
        }

        # Add source hashes
        record['source_player_game_hash'] = source_hashes.get('player_game')
        record['source_team_offense_hash'] = source_hashes.get('team_offense')
        record['source_upcoming_context_hash'] = source_hashes.get('upcoming_context')
        record['source_shot_zone_hash'] = source_hashes.get('shot_zone')

        return record
