"""Module-level worker function for multiprocessing.

This worker must remain at module level (not a class method) to be picklable
by ProcessPoolExecutor. All parameters must be plain dicts/primitives.
"""

import json
import logging
from datetime import datetime, date, timezone
from typing import Optional
import pandas as pd

logger = logging.getLogger(__name__)


def _process_single_player_worker(
    player_lookup: str,
    player_row_dict: dict,
    player_shot_dict: Optional[dict],
    team_defense_dict: Optional[dict],
    completeness: dict,
    upstream_status: dict,
    circuit_breaker_status: dict,
    is_bootstrap: bool,
    is_season_boundary: bool,
    analysis_date: date,
    calculation_version: str,
    source_hashes: dict,
    source_tracking: dict,
    hash_fields: list
) -> tuple:
    """Process one player (multiprocessing-safe worker).

    This function is picklable (no self references) for ProcessPoolExecutor.
    All data is passed as plain dicts/primitives.

    Args:
        player_lookup: Player ID
        player_row_dict: Player context data as dict
        player_shot_dict: Player shot zone data as dict (or None)
        team_defense_dict: Team defense zone data as dict (or None)
        completeness: Completeness check results
        upstream_status: Upstream completeness status
        circuit_breaker_status: Circuit breaker status
        is_bootstrap: Bootstrap mode flag
        is_season_boundary: Season boundary flag
        analysis_date: Analysis date
        calculation_version: Calculation version string
        source_hashes: Source hash dict
        source_tracking: Source tracking fields
        hash_fields: Fields to hash for data_hash

    Returns:
        tuple: (success: bool, data: dict)
    """
    try:
        # Import here to avoid pickling issues
        from shared.utils.hash_utils import compute_hash_from_dict
        from .factors import ACTIVE_FACTORS, DEFERRED_FACTORS

        # Convert dicts to pd.Series for factor calculators
        player_row = pd.Series(player_row_dict)
        player_shot = pd.Series(player_shot_dict) if player_shot_dict is not None else None
        team_defense = pd.Series(team_defense_dict) if team_defense_dict is not None else None

        # Calculate all factors using the factor calculators
        factor_scores = {}
        factor_contexts = {}

        for factor in ACTIVE_FACTORS:
            score = factor.calculate(player_row, player_shot, team_defense)
            context = factor.build_context(player_row, player_shot, team_defense)
            factor_scores[factor.name] = score
            factor_contexts[factor.context_field] = context

        for factor in DEFERRED_FACTORS:
            score = factor.calculate(player_row, player_shot, team_defense)
            context = factor.build_context(player_row, player_shot, team_defense)
            factor_scores[factor.name] = score
            factor_contexts[factor.context_field] = context

        # Sum all adjustments for total composite
        total_adjustment = sum(factor_scores.values())

        # Calculate data completeness
        required_fields_present = 0
        total_checks = 5
        if pd.notna(player_row_dict.get('days_rest')):
            required_fields_present += 1
        if pd.notna(player_row_dict.get('projected_usage_rate')):
            required_fields_present += 1
        if pd.notna(player_row_dict.get('pace_differential')):
            required_fields_present += 1
        if player_shot_dict is not None:
            required_fields_present += 1
        if team_defense_dict is not None:
            required_fields_present += 1
        completeness_pct = (required_fields_present / total_checks) * 100

        missing = []
        if not pd.notna(player_row_dict.get('days_rest')):
            missing.append('days_rest')
        if not pd.notna(player_row_dict.get('projected_usage_rate')):
            missing.append('projected_usage_rate')
        if not pd.notna(player_row_dict.get('pace_differential')):
            missing.append('pace_differential')
        if player_shot_dict is None:
            missing.append('player_shot_zone')
        if team_defense_dict is None:
            missing.append('team_defense_zone')
        missing_str = ', '.join(missing) if missing else None

        # Check for warnings
        warnings = []
        fatigue_score = factor_scores.get('fatigue_score', 0)
        shot_zone_score = factor_scores.get('shot_zone_mismatch_score', 0)

        if fatigue_score < 50:
            warnings.append("EXTREME_FATIGUE: Player showing severe fatigue")
        if abs(shot_zone_score) > 8.0:
            warnings.append("EXTREME_MATCHUP: Unusual zone mismatch")
        if abs(total_adjustment) > 12.0:
            warnings.append("EXTREME_ADJUSTMENT: Very large composite adjustment")
        has_warnings = len(warnings) > 0
        warning_details = '; '.join(warnings) if warnings else None

        # Build output record
        record = {
            # Identifiers
            'player_lookup': player_lookup,
            'universal_player_id': player_row_dict['universal_player_id'],
            'game_date': player_row_dict['game_date'],
            'game_id': player_row_dict['game_id'],
            'analysis_date': analysis_date,

            # Active factor scores
            'fatigue_score': int(factor_scores['fatigue_score']),
            'shot_zone_mismatch_score': round(factor_scores['shot_zone_mismatch_score'], 1),
            'pace_score': round(factor_scores['pace_score'], 1),
            'usage_spike_score': round(factor_scores['usage_spike_score'], 1),

            # Deferred factor scores
            'referee_favorability_score': round(factor_scores['referee_favorability_score'], 1),
            'look_ahead_pressure_score': round(factor_scores['look_ahead_pressure_score'], 1),
            'travel_impact_score': round(factor_scores['travel_impact_score'], 1),
            'opponent_strength_score': round(factor_scores['opponent_strength_score'], 1),

            # Total composite adjustment
            'total_composite_adjustment': round(total_adjustment, 2),

            # Context JSONs
            'fatigue_context_json': json.dumps(factor_contexts['fatigue_context_json']),
            'shot_zone_context_json': json.dumps(factor_contexts['shot_zone_context_json']),
            'pace_context_json': json.dumps(factor_contexts['pace_context_json']),
            'usage_context_json': json.dumps(factor_contexts['usage_context_json']),

            # Metadata
            'calculation_version': calculation_version,
            'early_season_flag': False,
            'insufficient_data_reason': None,
            'data_completeness_pct': completeness_pct,
            'missing_data_fields': missing_str,
            'has_warnings': has_warnings,
            'warning_details': warning_details,

            # Completeness Checking Metadata
            'expected_games_count': completeness['expected_count'],
            'actual_games_count': completeness['actual_count'],
            'completeness_percentage': completeness['completeness_pct'],
            'missing_games_count': completeness['missing_count'],

            # Production Readiness
            'is_production_ready': (
                completeness['is_production_ready'] and
                upstream_status['all_upstreams_ready']
            ),

            # Upstream Readiness Flags
            'upstream_player_shot_ready': upstream_status['player_shot_zone_ready'],
            'upstream_team_defense_ready': upstream_status['team_defense_zone_ready'],
            'upstream_player_context_ready': upstream_status['upcoming_player_context_ready'],
            'upstream_team_context_ready': upstream_status['upcoming_team_context_ready'],
            'all_upstreams_ready': upstream_status['all_upstreams_ready'],

            'data_quality_issues': [issue for issue in [
                "own_data_incomplete" if not completeness['is_production_ready'] else None,
                "upstream_player_shot_zone_incomplete" if not upstream_status['player_shot_zone_ready'] else None,
                "upstream_team_defense_zone_incomplete" if not upstream_status['team_defense_zone_ready'] else None,
                "upstream_player_context_incomplete" if not upstream_status['upcoming_player_context_ready'] else None,
                "upstream_team_context_incomplete" if not upstream_status['upcoming_team_context_ready'] else None,
            ] if issue is not None],

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

            # Timestamps
            'created_at': datetime.now(timezone.utc).isoformat(),
            'processed_at': datetime.now(timezone.utc).isoformat()
        }

        # Add source tracking fields
        record.update(source_tracking)

        # Add source hashes
        record['source_player_context_hash'] = source_hashes.get('player_context')
        record['source_team_context_hash'] = source_hashes.get('team_context')
        record['source_player_shot_hash'] = source_hashes.get('player_shot')
        record['source_team_defense_hash'] = source_hashes.get('team_defense')

        # Compute data hash
        hash_data = {k: record.get(k) for k in hash_fields if k in record}
        record['data_hash'] = compute_hash_from_dict(hash_data)

        return (True, record)

    except Exception as e:
        logger.error(f"Failed to process {player_lookup}: {e}")
        return (False, {
            'entity_id': player_lookup,
            'entity_type': 'player',
            'reason': str(e),
            'category': 'calculation_error'
        })
