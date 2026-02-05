"""Module-level worker functions for multiprocessing.

These workers must remain at module level (not class methods) to be picklable
by ProcessPoolExecutor. All parameters must be plain dicts/primitives or
serializable datastructures.
"""

import hashlib
import json
import logging
from datetime import date
from typing import Dict
import pandas as pd

logger = logging.getLogger(__name__)


def _process_single_player_worker(
    player_lookup: str,
    upcoming_context_data: pd.DataFrame,
    player_game_data: pd.DataFrame,
    team_offense_data: pd.DataFrame,
    shot_zone_data: pd.DataFrame,
    completeness_l5: dict,
    completeness_l10: dict,
    completeness_l7d: dict,
    completeness_l14d: dict,
    is_bootstrap: bool,
    is_season_boundary: bool,
    analysis_date: date,
    circuit_breaker_status: dict,
    min_games_required: int,
    absolute_min_games: int,
    cache_version: str,
    source_tracking_fields: Dict,
    source_hashes: Dict,
    max_days_without_active_game: int = 30  # Session 128: Recency filter parameter
) -> tuple:
    """Module-level worker function for ProcessPoolExecutor.

    Must be at module level (not instance method) to be picklable.
    All required data passed as parameters (no self references).

    Returns (success: bool, data: dict).
    """
    try:
        # Get completeness for all windows
        comp_l5 = completeness_l5.get(player_lookup, {
            'expected_count': 0, 'actual_count': 0, 'completeness_pct': 0.0,
            'missing_count': 0, 'is_complete': False, 'is_production_ready': False
        })
        comp_l10 = completeness_l10.get(player_lookup, {
            'expected_count': 0, 'actual_count': 0, 'completeness_pct': 0.0,
            'missing_count': 0, 'is_complete': False, 'is_production_ready': False
        })
        comp_l7d = completeness_l7d.get(player_lookup, {
            'expected_count': 0, 'actual_count': 0, 'completeness_pct': 0.0,
            'missing_count': 0, 'is_complete': False, 'is_production_ready': False
        })
        comp_l14d = completeness_l14d.get(player_lookup, {
            'expected_count': 0, 'actual_count': 0, 'completeness_pct': 0.0,
            'missing_count': 0, 'is_complete': False, 'is_production_ready': False
        })

        # ALL windows must be production-ready for overall production readiness
        all_windows_complete = (
            comp_l5['is_production_ready'] and
            comp_l10['is_production_ready'] and
            comp_l7d['is_production_ready'] and
            comp_l14d['is_production_ready']
        )

        # Use L10 as primary completeness metric
        completeness = comp_l10

        # Check circuit breaker (already fetched, passed as parameter)
        if circuit_breaker_status['active']:
            return (False, {
                'entity_id': player_lookup,
                'reason': f"Circuit breaker active until {circuit_breaker_status['until']}",
                'category': 'CIRCUIT_BREAKER_ACTIVE',
                'can_retry': False
            })

        # Check production readiness (skip if any window incomplete, unless in bootstrap mode or season boundary)
        if not all_windows_complete and not is_bootstrap and not is_season_boundary:
            # DON'T increment reprocess count here (requires BQ client)
            # Main thread will handle this after collecting all results
            return (False, {
                'entity_id': player_lookup,
                'reason': f"Incomplete data across windows",
                'category': 'INCOMPLETE_DATA',
                'can_retry': True,
                'completeness_pct': completeness['completeness_pct']
            })

        # Get player's context data
        context_rows = upcoming_context_data[
            upcoming_context_data['player_lookup'] == player_lookup
        ]
        if context_rows.empty:
            return (False, {
                'entity_id': player_lookup,
                'reason': 'No upcoming context data found',
                'category': 'PROCESSING_ERROR',
                'can_retry': False
            })
        context_row = context_rows.iloc[0]

        # Get player's game history
        player_games = player_game_data[
            player_game_data['player_lookup'] == player_lookup
        ].copy()

        # Check minimum games requirement
        games_count = len(player_games)
        if games_count < absolute_min_games:
            return (False, {
                'entity_id': player_lookup,
                'reason': f"Only {games_count} games played, need {absolute_min_games} minimum",
                'category': 'INSUFFICIENT_DATA',
                'can_retry': True
            })

        # Session 128: Skip players with no recent active games (prevents stale data)
        # Players on extended DNP/injury who haven't played in 30+ days get stale "last 10" averages
        if not player_games.empty:
            most_recent_game = player_games['game_date'].max()
            days_since_last_game = (analysis_date - most_recent_game).days
            if days_since_last_game > max_days_without_active_game:
                return (False, {
                    'entity_id': player_lookup,
                    'reason': f"No active game in {days_since_last_game} days (max: {max_days_without_active_game})",
                    'category': 'STALE_DATA',
                    'can_retry': False
                })

        # Flag if below preferred minimum
        is_early_season = games_count < min_games_required

        # Get team context
        current_team = context_row['team_abbr']
        team_games = team_offense_data[
            team_offense_data['team_abbr'] == current_team
        ].copy()

        # Get shot zone data (optional - proceeds with nulls if missing)
        shot_zone_rows = shot_zone_data[
            shot_zone_data['player_lookup'] == player_lookup
        ]

        # Track shot zone availability for state tracking
        shot_zone_available = not shot_zone_rows.empty
        if shot_zone_rows.empty:
            # Create placeholder with null values - shot zone is optional enrichment
            shot_zone_row = pd.Series({
                'primary_scoring_zone': None,
                'paint_rate_last_10': None,
                'three_pt_rate_last_10': None
            })
        else:
            shot_zone_row = shot_zone_rows.iloc[0]

        # Calculate all metrics using aggregators and cache builder
        from .aggregators import StatsAggregator, TeamAggregator, ContextAggregator, ShotZoneAggregator
        from .builders import CacheBuilder

        # Aggregate data from all sources
        stats_data = StatsAggregator.aggregate(player_games)
        team_data = TeamAggregator.aggregate(team_games)
        context_data = ContextAggregator.aggregate(context_row)
        shot_zone_data = ShotZoneAggregator.aggregate(shot_zone_row)

        # Build completeness results dict
        completeness_results = {
            'L5': comp_l5,
            'L10': comp_l10,
            'L7d': comp_l7d,
            'L14d': comp_l14d,
        }

        # Build complete cache record
        cache_record = CacheBuilder.build_record(
            player_lookup=player_lookup,
            analysis_date=analysis_date,
            stats_data=stats_data,
            team_data=team_data,
            context_data=context_data,
            shot_zone_data=shot_zone_data,
            completeness_results=completeness_results,
            circuit_breaker_status=circuit_breaker_status,
            source_tracking=source_tracking_fields,
            source_hashes=source_hashes,
            is_early_season=is_early_season,
            is_season_boundary=is_season_boundary,
            is_bootstrap=is_bootstrap,
            shot_zone_available=shot_zone_available,
            min_games_required=min_games_required,
            cache_version=cache_version,
            context_row=context_row
        )

        # Compute data hash
        hash_fields = [
            'player_lookup', 'universal_player_id', 'cache_date',
            'points_avg_last_5', 'points_avg_last_10', 'points_avg_season',
            'points_std_last_10', 'minutes_avg_last_10', 'usage_rate_last_10',
            'ts_pct_last_10', 'games_played_season',
            'team_pace_last_10', 'team_off_rating_last_10', 'player_usage_rate_season',
            'games_in_last_7_days', 'games_in_last_14_days',
            'minutes_in_last_7_days', 'minutes_in_last_14_days',
            'back_to_backs_last_14_days', 'avg_minutes_per_game_last_7',
            'fourth_quarter_minutes_last_7',
            'primary_scoring_zone', 'paint_rate_last_10', 'three_pt_rate_last_10',
            'assisted_rate_last_10', 'player_age', 'cache_quality_score',
            'cache_version'
        ]

        hash_data = {k: cache_record.get(k) for k in hash_fields if k in cache_record}
        hash_str = json.dumps(hash_data, sort_keys=True, default=str)
        cache_record['data_hash'] = hashlib.sha256(hash_str.encode()).hexdigest()

        return (True, cache_record)

    except Exception as e:
        logger.error(f"Failed to process {player_lookup}: {e}", exc_info=True)
        return (False, {
            'entity_id': player_lookup,
            'reason': str(e),
            'category': 'PROCESSING_ERROR',
            'can_retry': False
        })
