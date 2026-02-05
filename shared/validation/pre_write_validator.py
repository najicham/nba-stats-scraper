"""
Pre-Write Validation for BigQuery Operations
=============================================
Validates records against business logic rules BEFORE writing to BigQuery.
Blocks records that would corrupt downstream data (e.g., DNP with points=0).

This module provides:
1. ValidationRule - Define individual validation rules
2. PreWriteValidator - Validate records against rules for a target table
3. Pre-built rules for player_game_summary, player_composite_factors, ml_feature_store_v2

Usage:
    from shared.validation.pre_write_validator import PreWriteValidator

    validator = PreWriteValidator('player_game_summary')
    valid_records, invalid_records = validator.validate(records)

    if invalid_records:
        logger.error(f"Blocked {len(invalid_records)} invalid records")
        # Log to validation_failures table

    # Only write valid records
    write_to_bigquery(valid_records)

Version: 1.0
Created: 2026-01-30
Part of: Data Quality Self-Healing System
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
import uuid

logger = logging.getLogger(__name__)


@dataclass
class ValidationRule:
    """A single validation rule with condition and error message."""
    name: str
    condition: Callable[[dict], bool]  # Returns True if record is VALID
    error_message: str
    severity: str = "ERROR"  # ERROR blocks write, WARNING logs only

    def validate(self, record: dict) -> Optional[str]:
        """
        Validate a record against this rule.

        Returns:
            None if valid, error message string if invalid
        """
        try:
            if not self.condition(record):
                return f"{self.name}: {self.error_message}"
        except Exception as e:
            logger.warning(f"Rule {self.name} raised exception: {e}")
            return f"{self.name}: Validation error - {e}"
        return None


@dataclass
class ValidationResult:
    """Result of pre-write validation."""
    is_valid: bool
    valid_records: List[dict] = field(default_factory=list)
    invalid_records: List[dict] = field(default_factory=list)
    violations: List[dict] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return len([v for v in self.violations if v.get('severity') == 'ERROR'])

    @property
    def warning_count(self) -> int:
        return len([v for v in self.violations if v.get('severity') == 'WARNING'])


# =============================================================================
# BUSINESS RULES BY TABLE
# =============================================================================

BUSINESS_RULES: Dict[str, List[ValidationRule]] = {

    # -------------------------------------------------------------------------
    # player_game_summary - Phase 3 Analytics
    # -------------------------------------------------------------------------
    'player_game_summary': [
        # DNP players must have NULL stats (not 0)
        # This is the EXACT bug that caused the January 2026 incident
        ValidationRule(
            name='dnp_null_points',
            condition=lambda r: not r.get('is_dnp') or r.get('points') is None,
            error_message="DNP players must have NULL points, not 0 or any value"
        ),
        ValidationRule(
            name='dnp_null_minutes',
            condition=lambda r: not r.get('is_dnp') or r.get('minutes') is None,
            error_message="DNP players must have NULL minutes"
        ),
        ValidationRule(
            name='dnp_null_rebounds',
            condition=lambda r: not r.get('is_dnp') or r.get('rebounds') is None,
            error_message="DNP players must have NULL rebounds"
        ),
        ValidationRule(
            name='dnp_null_assists',
            condition=lambda r: not r.get('is_dnp') or r.get('assists') is None,
            error_message="DNP players must have NULL assists"
        ),

        # Active players must have valid stats
        ValidationRule(
            name='active_non_negative_points',
            condition=lambda r: r.get('is_dnp') or (r.get('points') is None or r.get('points', 0) >= 0),
            error_message="Active players cannot have negative points"
        ),
        ValidationRule(
            name='active_non_negative_minutes',
            condition=lambda r: r.get('is_dnp') or (r.get('minutes') is None or r.get('minutes', 0) >= 0),
            error_message="Active players cannot have negative minutes"
        ),

        # Required fields for identity
        ValidationRule(
            name='required_player_lookup',
            condition=lambda r: r.get('player_lookup') is not None,
            error_message="player_lookup is required"
        ),
        ValidationRule(
            name='required_game_date',
            condition=lambda r: r.get('game_date') is not None,
            error_message="game_date is required"
        ),
        ValidationRule(
            name='required_game_id',
            condition=lambda r: r.get('game_id') is not None,
            error_message="game_id is required"
        ),

        # Stat ranges (when not NULL)
        ValidationRule(
            name='points_range',
            condition=lambda r: r.get('points') is None or 0 <= r.get('points', 0) <= 100,
            error_message="points must be 0-100 (or NULL)",
            severity="WARNING"
        ),
        ValidationRule(
            name='minutes_range',
            condition=lambda r: r.get('minutes') is None or 0 <= r.get('minutes', 0) <= 60,
            error_message="minutes must be 0-60 (or NULL)",
            severity="WARNING"
        ),
        ValidationRule(
            name='usage_rate_range',
            condition=lambda r: r.get('usage_rate') is None or 0 <= r.get('usage_rate', 0) <= 50,
            error_message="usage_rate must be 0-50% (or NULL) - values >100% indicate calculation error",
            severity="ERROR"  # BLOCK writes - this is a data corruption issue
        ),
    ],

    # -------------------------------------------------------------------------
    # player_composite_factors - Phase 4 Precompute
    # -------------------------------------------------------------------------
    'player_composite_factors': [
        # Fatigue score must be in valid range
        # This catches the parallel processing bug from January 2026
        ValidationRule(
            name='fatigue_score_range',
            condition=lambda r: r.get('fatigue_score') is None or 0 <= r.get('fatigue_score', 0) <= 100,
            error_message="fatigue_score must be 0-100"
        ),

        # Context scores ranges
        ValidationRule(
            name='matchup_difficulty_range',
            condition=lambda r: r.get('matchup_difficulty_score') is None or -50 <= r.get('matchup_difficulty_score', 0) <= 50,
            error_message="matchup_difficulty_score must be -50 to 50"
        ),
        ValidationRule(
            name='pace_score_range',
            condition=lambda r: r.get('pace_score') is None or 70 <= r.get('pace_score', 100) <= 130,
            error_message="pace_score must be 70-130",
            severity="WARNING"
        ),

        # Required fields
        ValidationRule(
            name='required_player_lookup',
            condition=lambda r: r.get('player_lookup') is not None,
            error_message="player_lookup is required"
        ),
        ValidationRule(
            name='required_game_date',
            condition=lambda r: r.get('game_date') is not None,
            error_message="game_date is required"
        ),
    ],

    # -------------------------------------------------------------------------
    # ml_feature_store_v2 - Phase 4 Precompute (ML Features)
    # -------------------------------------------------------------------------
    'ml_feature_store_v2': [
        # Feature array must have correct count
        ValidationRule(
            name='feature_array_length',
            condition=lambda r: r.get('features') is None or len(r.get('features', [])) == 34,
            error_message="features array must have exactly 34 elements"
        ),

        # No NaN or Inf in features
        ValidationRule(
            name='no_nan_features',
            condition=lambda r: r.get('features') is None or not any(
                str(f).lower() in ('nan', 'inf', '-inf', 'none')
                for f in r.get('features', [])
            ),
            error_message="features array cannot contain NaN or Inf values"
        ),

        # Required fields
        ValidationRule(
            name='required_player_lookup',
            condition=lambda r: r.get('player_lookup') is not None,
            error_message="player_lookup is required"
        ),
        ValidationRule(
            name='required_game_date',
            condition=lambda r: r.get('game_date') is not None,
            error_message="game_date is required"
        ),

        # Feature ranges (for key features at known indices)
        # Index 0: points_avg (0-50 typical)
        ValidationRule(
            name='feature_points_avg_range',
            condition=lambda r: (
                r.get('features') is None or
                len(r.get('features', [])) < 1 or
                r.get('features')[0] is None or
                0 <= r.get('features')[0] <= 60
            ),
            error_message="features[0] (points_avg) should be 0-60",
            severity="WARNING"
        ),
        # Index 5: fatigue_score (0-100)
        ValidationRule(
            name='feature_fatigue_range',
            condition=lambda r: (
                r.get('features') is None or
                len(r.get('features', [])) < 6 or
                r.get('features')[5] is None or
                0 <= r.get('features')[5] <= 100
            ),
            error_message="features[5] (fatigue_score) must be 0-100"
        ),
    ],

    # -------------------------------------------------------------------------
    # prediction_accuracy - Phase 5 Grading
    # -------------------------------------------------------------------------
    'prediction_accuracy': [
        ValidationRule(
            name='required_prediction_id',
            condition=lambda r: r.get('prediction_id') is not None,
            error_message="prediction_id is required"
        ),
        ValidationRule(
            name='required_game_date',
            condition=lambda r: r.get('game_date') is not None,
            error_message="game_date is required"
        ),
        ValidationRule(
            name='actual_points_range',
            condition=lambda r: r.get('actual_points') is None or 0 <= r.get('actual_points', 0) <= 100,
            error_message="actual_points must be 0-100",
            severity="WARNING"
        ),
    ],

    # -------------------------------------------------------------------------
    # team_offense_game_summary - Phase 3 Analytics
    # Session 117: Prevent 0-value bad data from being written
    # -------------------------------------------------------------------------
    'team_offense_game_summary': [
        # ERROR: Block placeholder/incomplete data
        ValidationRule(
            name='points_not_zero',
            condition=lambda r: r.get('points_scored', 0) > 0,
            error_message="Team scored 0 points - bad source data or placeholder"
        ),
        ValidationRule(
            name='fg_attempts_not_zero',
            condition=lambda r: r.get('fg_attempts', 0) > 0,
            error_message="Team has 0 FG attempts - bad source data"
        ),
        ValidationRule(
            name='possessions_required',
            condition=lambda r: r.get('possessions') is not None,
            error_message="Possessions NULL - cannot calculate usage_rate"
        ),

        # WARNING: Unusual but possible scenarios
        ValidationRule(
            name='unusually_low_score',
            condition=lambda r: r.get('points_scored', 0) == 0 or r.get('points_scored', 100) >= 80,
            error_message="Team scored <80 points - unusual but possible",
            severity="WARNING"
        ),

        # Required identity fields
        ValidationRule(
            name='required_game_id',
            condition=lambda r: r.get('game_id') is not None,
            error_message="game_id is required"
        ),
        ValidationRule(
            name='required_game_date',
            condition=lambda r: r.get('game_date') is not None,
            error_message="game_date is required"
        ),
        ValidationRule(
            name='required_team_abbr',
            condition=lambda r: r.get('team_abbr') is not None,
            error_message="team_abbr is required"
        ),

        # Stat sanity checks
        ValidationRule(
            name='fg_made_not_exceed_attempts',
            condition=lambda r: r.get('fg_made', 0) <= r.get('fg_attempts', 999),
            error_message="FG made cannot exceed FG attempts"
        ),
        ValidationRule(
            name='points_reasonable_range',
            condition=lambda r: r.get('points_scored') is None or 0 < r.get('points_scored', 100) <= 200,
            error_message="points_scored must be 1-200",
            severity="WARNING"
        ),
    ],

    # -------------------------------------------------------------------------
    # team_defense_game_summary - Phase 3 Analytics
    # Session 118: Prevent 0-value bad defensive data
    # -------------------------------------------------------------------------
    'team_defense_game_summary': [
        # ERROR: Block placeholder/incomplete data
        ValidationRule(
            name='points_allowed_not_zero',
            condition=lambda r: r.get('points_allowed', 0) > 0,
            error_message="Team allowed 0 points - bad source data or placeholder"
        ),
        ValidationRule(
            name='opp_fg_attempts_not_zero',
            condition=lambda r: r.get('opp_fg_attempts', 0) > 0,
            error_message="Opponent had 0 FG attempts - bad source data"
        ),
        ValidationRule(
            name='defensive_rating_valid',
            condition=lambda r: r.get('defensive_rating') is None or r.get('defensive_rating', 1) > 0,
            error_message="Defensive rating is 0 or negative - calculation error"
        ),

        # WARNING: Unusual but possible scenarios
        ValidationRule(
            name='unusually_low_points_allowed',
            condition=lambda r: r.get('points_allowed', 0) == 0 or r.get('points_allowed', 100) >= 70,
            error_message="Team allowed <70 points - unusual but possible",
            severity="WARNING"
        ),
        ValidationRule(
            name='unusually_high_points_allowed',
            condition=lambda r: r.get('points_allowed') is None or r.get('points_allowed', 100) <= 180,
            error_message="Team allowed >180 points - unusual but possible",
            severity="WARNING"
        ),

        # Required identity fields
        ValidationRule(
            name='required_game_id',
            condition=lambda r: r.get('game_id') is not None,
            error_message="game_id is required"
        ),
        ValidationRule(
            name='required_game_date',
            condition=lambda r: r.get('game_date') is not None,
            error_message="game_date is required"
        ),
        ValidationRule(
            name='required_defending_team',
            condition=lambda r: r.get('defending_team_abbr') is not None,
            error_message="defending_team_abbr is required"
        ),

        # Stat sanity checks
        ValidationRule(
            name='opp_fg_made_not_exceed_attempts',
            condition=lambda r: r.get('opp_fg_makes', 0) <= r.get('opp_fg_attempts', 999),
            error_message="Opponent FG made cannot exceed FG attempts"
        ),
        ValidationRule(
            name='opp_ft_made_not_exceed_attempts',
            condition=lambda r: r.get('opp_ft_makes', 0) <= r.get('opp_ft_attempts', 999),
            error_message="Opponent FT made cannot exceed FT attempts"
        ),
    ],

    # -------------------------------------------------------------------------
    # player_shot_zone_analysis - Phase 4 Precompute (Player Zone Stats)
    # -------------------------------------------------------------------------
    'player_shot_zone_analysis': [
        # Required fields
        ValidationRule(
            name='required_player_lookup',
            condition=lambda r: r.get('player_lookup') is not None,
            error_message="player_lookup is required"
        ),
        ValidationRule(
            name='required_analysis_date',
            condition=lambda r: r.get('analysis_date') is not None,
            error_message="analysis_date is required"
        ),

        # Zone rate percentages (distribution: should sum to ~100%)
        ValidationRule(
            name='paint_rate_range',
            condition=lambda r: r.get('paint_rate_last_10') is None or 0 <= r.get('paint_rate_last_10') <= 100,
            error_message="paint_rate_last_10 must be 0-100%"
        ),
        ValidationRule(
            name='mid_range_rate_range',
            condition=lambda r: r.get('mid_range_rate_last_10') is None or 0 <= r.get('mid_range_rate_last_10') <= 100,
            error_message="mid_range_rate_last_10 must be 0-100%"
        ),
        ValidationRule(
            name='three_pt_rate_range',
            condition=lambda r: r.get('three_pt_rate_last_10') is None or 0 <= r.get('three_pt_rate_last_10') <= 100,
            error_message="three_pt_rate_last_10 must be 0-100%"
        ),

        # Zone efficiency percentages (FG%)
        ValidationRule(
            name='paint_pct_range',
            condition=lambda r: r.get('paint_pct_last_10') is None or 0 <= r.get('paint_pct_last_10') <= 1.0,
            error_message="paint_pct_last_10 must be 0-1.0 (0-100%)"
        ),
        ValidationRule(
            name='mid_range_pct_range',
            condition=lambda r: r.get('mid_range_pct_last_10') is None or 0 <= r.get('mid_range_pct_last_10') <= 1.0,
            error_message="mid_range_pct_last_10 must be 0-1.0 (0-100%)"
        ),
        ValidationRule(
            name='three_pt_pct_range',
            condition=lambda r: r.get('three_pt_pct_last_10') is None or 0 <= r.get('three_pt_pct_last_10') <= 1.0,
            error_message="three_pt_pct_last_10 must be 0-1.0 (0-100%)"
        ),

        # Attempts per game (non-negative, reasonable max)
        ValidationRule(
            name='paint_attempts_pg_range',
            condition=lambda r: r.get('paint_attempts_per_game') is None or 0 <= r.get('paint_attempts_per_game') <= 40,
            error_message="paint_attempts_per_game must be 0-40"
        ),
        ValidationRule(
            name='mid_range_attempts_pg_range',
            condition=lambda r: r.get('mid_range_attempts_per_game') is None or 0 <= r.get('mid_range_attempts_per_game') <= 40,
            error_message="mid_range_attempts_per_game must be 0-40"
        ),
        ValidationRule(
            name='three_pt_attempts_pg_range',
            condition=lambda r: r.get('three_pt_attempts_per_game') is None or 0 <= r.get('three_pt_attempts_per_game') <= 40,
            error_message="three_pt_attempts_per_game must be 0-40"
        ),

        # Games in sample (positive integer)
        ValidationRule(
            name='games_in_sample_positive',
            condition=lambda r: r.get('games_in_sample_10') is None or r.get('games_in_sample_10', 0) >= 0,
            error_message="games_in_sample_10 must be non-negative"
        ),

        # Total shots sanity check
        ValidationRule(
            name='total_shots_reasonable',
            condition=lambda r: r.get('total_shots_last_10') is None or 0 <= r.get('total_shots_last_10') <= 400,
            error_message="total_shots_last_10 must be 0-400 (reasonable for 10 games)"
        ),
    ],

    # -------------------------------------------------------------------------
    # team_defense_zone_analysis - Phase 4 Precompute (Team Defense Zones)
    # -------------------------------------------------------------------------
    'team_defense_zone_analysis': [
        # Required fields
        ValidationRule(
            name='required_team_abbr',
            condition=lambda r: r.get('team_abbr') is not None,
            error_message="team_abbr is required"
        ),
        ValidationRule(
            name='required_analysis_date',
            condition=lambda r: r.get('analysis_date') is not None,
            error_message="analysis_date is required"
        ),

        # FG% allowed by zone (0-100% stored as 0-1.0)
        ValidationRule(
            name='paint_pct_allowed_range',
            condition=lambda r: r.get('paint_pct_allowed_last_15') is None or 0 <= r.get('paint_pct_allowed_last_15') <= 1.0,
            error_message="paint_pct_allowed_last_15 must be 0-1.0 (0-100%)"
        ),
        ValidationRule(
            name='mid_range_pct_allowed_range',
            condition=lambda r: r.get('mid_range_pct_allowed_last_15') is None or 0 <= r.get('mid_range_pct_allowed_last_15') <= 1.0,
            error_message="mid_range_pct_allowed_last_15 must be 0-1.0 (0-100%)"
        ),
        ValidationRule(
            name='three_pt_pct_allowed_range',
            condition=lambda r: r.get('three_pt_pct_allowed_last_15') is None or 0 <= r.get('three_pt_pct_allowed_last_15') <= 1.0,
            error_message="three_pt_pct_allowed_last_15 must be 0-1.0 (0-100%)"
        ),

        # Attempts allowed per game (non-negative, reasonable max)
        ValidationRule(
            name='paint_attempts_allowed_range',
            condition=lambda r: r.get('paint_attempts_allowed_per_game') is None or 0 <= r.get('paint_attempts_allowed_per_game') <= 100,
            error_message="paint_attempts_allowed_per_game must be 0-100"
        ),
        ValidationRule(
            name='mid_range_attempts_allowed_range',
            condition=lambda r: r.get('mid_range_attempts_allowed_per_game') is None or 0 <= r.get('mid_range_attempts_allowed_per_game') <= 100,
            error_message="mid_range_attempts_allowed_per_game must be 0-100"
        ),
        ValidationRule(
            name='three_pt_attempts_allowed_range',
            condition=lambda r: r.get('three_pt_attempts_allowed_per_game') is None or 0 <= r.get('three_pt_attempts_allowed_per_game') <= 100,
            error_message="three_pt_attempts_allowed_per_game must be 0-100"
        ),

        # Points allowed per game (paint zone)
        ValidationRule(
            name='paint_points_allowed_range',
            condition=lambda r: r.get('paint_points_allowed_per_game') is None or 0 <= r.get('paint_points_allowed_per_game') <= 150,
            error_message="paint_points_allowed_per_game must be 0-150"
        ),

        # Defensive rating (typical range: 80-130)
        ValidationRule(
            name='defensive_rating_range',
            condition=lambda r: r.get('defensive_rating_last_15') is None or 70 <= r.get('defensive_rating_last_15') <= 140,
            error_message="defensive_rating_last_15 must be 70-140 (reasonable NBA range)"
        ),

        # Opponent points per game
        ValidationRule(
            name='opponent_ppg_range',
            condition=lambda r: r.get('opponent_points_per_game') is None or 70 <= r.get('opponent_points_per_game') <= 150,
            error_message="opponent_points_per_game must be 70-150"
        ),

        # Games in sample (positive integer)
        ValidationRule(
            name='games_in_sample_positive',
            condition=lambda r: r.get('games_in_sample') is None or r.get('games_in_sample', 0) >= 0,
            error_message="games_in_sample must be non-negative"
        ),

        # Defense vs league average (difference, typically -20 to +20)
        ValidationRule(
            name='paint_defense_vs_avg_range',
            condition=lambda r: r.get('paint_defense_vs_league_avg') is None or -0.30 <= r.get('paint_defense_vs_league_avg') <= 0.30,
            error_message="paint_defense_vs_league_avg must be -0.30 to +0.30 (±30%)"
        ),
        ValidationRule(
            name='mid_range_defense_vs_avg_range',
            condition=lambda r: r.get('mid_range_defense_vs_league_avg') is None or -0.30 <= r.get('mid_range_defense_vs_league_avg') <= 0.30,
            error_message="mid_range_defense_vs_league_avg must be -0.30 to +0.30 (±30%)"
        ),
        ValidationRule(
            name='three_pt_defense_vs_avg_range',
            condition=lambda r: r.get('three_pt_defense_vs_league_avg') is None or -0.30 <= r.get('three_pt_defense_vs_league_avg') <= 0.30,
            error_message="three_pt_defense_vs_league_avg must be -0.30 to +0.30 (±30%)"
        ),
    ],

    # -------------------------------------------------------------------------
    # daily_opponent_defense_zones - Phase 4 Precompute (Daily Opponent Defense)
    # -------------------------------------------------------------------------
    'daily_opponent_defense_zones': [
        # Required fields
        ValidationRule(
            name='required_game_date',
            condition=lambda r: r.get('game_date') is not None,
            error_message="game_date is required"
        ),
        ValidationRule(
            name='required_opponent_team_abbr',
            condition=lambda r: r.get('opponent_team_abbr') is not None,
            error_message="opponent_team_abbr is required"
        ),

        # FG% allowed by zone (0-100% stored as 0-1.0 in NUMERIC)
        ValidationRule(
            name='paint_fg_pct_allowed_range',
            condition=lambda r: r.get('paint_fg_pct_allowed') is None or 0 <= r.get('paint_fg_pct_allowed') <= 1.0,
            error_message="paint_fg_pct_allowed must be 0-1.0 (0-100%)"
        ),
        ValidationRule(
            name='mid_range_fg_pct_allowed_range',
            condition=lambda r: r.get('mid_range_fg_pct_allowed') is None or 0 <= r.get('mid_range_fg_pct_allowed') <= 1.0,
            error_message="mid_range_fg_pct_allowed must be 0-1.0 (0-100%)"
        ),
        ValidationRule(
            name='three_pt_fg_pct_allowed_range',
            condition=lambda r: r.get('three_pt_fg_pct_allowed') is None or 0 <= r.get('three_pt_fg_pct_allowed') <= 1.0,
            error_message="three_pt_fg_pct_allowed must be 0-1.0 (0-100%)"
        ),

        # Attempts allowed (non-negative)
        ValidationRule(
            name='paint_attempts_allowed_nonnegative',
            condition=lambda r: r.get('paint_attempts_allowed') is None or r.get('paint_attempts_allowed', 0) >= 0,
            error_message="paint_attempts_allowed must be non-negative"
        ),
        ValidationRule(
            name='mid_range_attempts_allowed_nonnegative',
            condition=lambda r: r.get('mid_range_attempts_allowed') is None or r.get('mid_range_attempts_allowed', 0) >= 0,
            error_message="mid_range_attempts_allowed must be non-negative"
        ),
        ValidationRule(
            name='three_pt_attempts_allowed_nonnegative',
            condition=lambda r: r.get('three_pt_attempts_allowed') is None or r.get('three_pt_attempts_allowed', 0) >= 0,
            error_message="three_pt_attempts_allowed must be non-negative"
        ),

        # Blocks (non-negative)
        ValidationRule(
            name='paint_blocks_nonnegative',
            condition=lambda r: r.get('paint_blocks') is None or r.get('paint_blocks', 0) >= 0,
            error_message="paint_blocks must be non-negative"
        ),
        ValidationRule(
            name='mid_range_blocks_nonnegative',
            condition=lambda r: r.get('mid_range_blocks') is None or r.get('mid_range_blocks', 0) >= 0,
            error_message="mid_range_blocks must be non-negative"
        ),
        ValidationRule(
            name='three_pt_blocks_nonnegative',
            condition=lambda r: r.get('three_pt_blocks') is None or r.get('three_pt_blocks', 0) >= 0,
            error_message="three_pt_blocks must be non-negative"
        ),

        # Defensive rating (typical range: 80-130)
        ValidationRule(
            name='defensive_rating_range',
            condition=lambda r: r.get('defensive_rating') is None or 70 <= r.get('defensive_rating') <= 140,
            error_message="defensive_rating must be 70-140 (reasonable NBA range)"
        ),

        # Opponent points average
        ValidationRule(
            name='opponent_points_avg_range',
            condition=lambda r: r.get('opponent_points_avg') is None or 70 <= r.get('opponent_points_avg') <= 150,
            error_message="opponent_points_avg must be 70-150"
        ),

        # Games in sample (positive integer)
        ValidationRule(
            name='games_in_sample_positive',
            condition=lambda r: r.get('games_in_sample') is None or r.get('games_in_sample', 0) >= 0,
            error_message="games_in_sample must be non-negative"
        ),
    ],
}


class PreWriteValidator:
    """
    Validates records against business rules before BigQuery write.

    Usage:
        validator = PreWriteValidator('player_game_summary')
        valid, invalid = validator.validate(records)
    """

    def __init__(self, table_name: str, custom_rules: List[ValidationRule] = None):
        """
        Initialize validator for a specific table.

        Args:
            table_name: Target BigQuery table name
            custom_rules: Optional additional rules to apply
        """
        self.table_name = table_name
        self.rules = BUSINESS_RULES.get(table_name, []).copy()

        if custom_rules:
            self.rules.extend(custom_rules)

        if not self.rules:
            logger.warning(f"No validation rules defined for table: {table_name}")

    def validate(self, records: List[dict]) -> Tuple[List[dict], List[dict]]:
        """
        Validate records, returning (valid_records, invalid_records).

        Invalid records include a '_validation_violations' key with list of errors.

        Args:
            records: List of record dicts to validate

        Returns:
            Tuple of (valid_records, invalid_records)
        """
        if not records:
            return [], []

        valid_records = []
        invalid_records = []

        for i, record in enumerate(records):
            violations = self._check_rules(record, i)
            error_violations = [v for v in violations if v.get('severity') == 'ERROR']

            if error_violations:
                # Add violations to record for debugging
                record_copy = record.copy()
                record_copy['_validation_violations'] = violations
                record_copy['_validation_timestamp'] = datetime.now(timezone.utc).isoformat()
                invalid_records.append(record_copy)
                self._log_violations(record, violations)
            else:
                valid_records.append(record)
                # Log warnings but don't block
                warning_violations = [v for v in violations if v.get('severity') == 'WARNING']
                if warning_violations:
                    self._log_warnings(record, warning_violations)

        return valid_records, invalid_records

    def validate_single(self, record: dict) -> ValidationResult:
        """
        Validate a single record with detailed result.

        Args:
            record: Single record dict

        Returns:
            ValidationResult with details
        """
        violations = self._check_rules(record, 0)
        error_violations = [v for v in violations if v.get('severity') == 'ERROR']

        result = ValidationResult(
            is_valid=len(error_violations) == 0,
            valid_records=[record] if len(error_violations) == 0 else [],
            invalid_records=[record] if len(error_violations) > 0 else [],
            violations=violations
        )

        return result

    def _check_rules(self, record: dict, record_index: int) -> List[dict]:
        """Check all rules against a record."""
        violations = []

        for rule in self.rules:
            error_msg = rule.validate(record)
            if error_msg:
                violations.append({
                    'rule_name': rule.name,
                    'error_message': error_msg,
                    'severity': rule.severity,
                    'record_index': record_index,
                    'field_values': self._extract_relevant_fields(record, rule.name)
                })

        return violations

    def _extract_relevant_fields(self, record: dict, rule_name: str) -> dict:
        """Extract fields relevant to a rule for debugging."""
        # Map rule names to relevant fields
        field_map = {
            'dnp_null_points': ['is_dnp', 'points', 'player_lookup', 'game_date'],
            'dnp_null_minutes': ['is_dnp', 'minutes', 'player_lookup', 'game_date'],
            'dnp_null_rebounds': ['is_dnp', 'rebounds', 'player_lookup', 'game_date'],
            'dnp_null_assists': ['is_dnp', 'assists', 'player_lookup', 'game_date'],
            'fatigue_score_range': ['fatigue_score', 'player_lookup', 'game_date'],
            'feature_array_length': ['player_lookup', 'game_date'],
        }

        fields = field_map.get(rule_name, ['player_lookup', 'game_date', 'game_id'])
        return {f: record.get(f) for f in fields if f in record}

    def _log_violations(self, record: dict, violations: List[dict]) -> None:
        """Log validation violations."""
        player = record.get('player_lookup', 'unknown')
        game_date = record.get('game_date', 'unknown')

        for v in violations:
            if v.get('severity') == 'ERROR':
                logger.error(
                    f"PRE_WRITE_VALIDATION_BLOCKED: table={self.table_name} "
                    f"player={player} date={game_date} rule={v['rule_name']} "
                    f"error={v['error_message']} fields={v.get('field_values')}"
                )

    def _log_warnings(self, record: dict, violations: List[dict]) -> None:
        """Log validation warnings (non-blocking)."""
        player = record.get('player_lookup', 'unknown')
        game_date = record.get('game_date', 'unknown')

        for v in violations:
            logger.warning(
                f"PRE_WRITE_VALIDATION_WARNING: table={self.table_name} "
                f"player={player} date={game_date} rule={v['rule_name']} "
                f"warning={v['error_message']}"
            )

    def add_rule(self, rule: ValidationRule) -> None:
        """Add a custom rule at runtime."""
        self.rules.append(rule)

    def disable_rule(self, rule_name: str) -> None:
        """Disable a rule by name (for testing/migration)."""
        self.rules = [r for r in self.rules if r.name != rule_name]


def create_validation_failure_record(
    table_name: str,
    record: dict,
    violations: List[dict],
    processor_name: str = None,
    session_id: str = None
) -> dict:
    """
    Create a record for the validation_failures table.

    Args:
        table_name: Target table that was being written to
        record: The record that failed validation
        violations: List of violation dicts
        processor_name: Name of the processor (optional)
        session_id: Processing session ID (optional)

    Returns:
        Dict ready to insert into validation_failures table
    """
    import json

    return {
        'failure_id': str(uuid.uuid4()),
        'failure_timestamp': datetime.now(timezone.utc).isoformat(),
        'table_name': table_name,
        'processor_name': processor_name,
        'game_date': str(record.get('game_date')) if record.get('game_date') else None,
        'player_lookup': record.get('player_lookup'),
        'game_id': record.get('game_id'),
        'violations': [v.get('error_message', str(v)) for v in violations],
        'record_json': json.dumps(record, default=str)[:10000],  # Truncate large records
        'session_id': session_id,
        'environment': 'production'
    }


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def validate_player_game_summary(records: List[dict]) -> Tuple[List[dict], List[dict]]:
    """Validate player_game_summary records."""
    validator = PreWriteValidator('player_game_summary')
    return validator.validate(records)


def validate_composite_factors(records: List[dict]) -> Tuple[List[dict], List[dict]]:
    """Validate player_composite_factors records."""
    validator = PreWriteValidator('player_composite_factors')
    return validator.validate(records)


def validate_ml_features(records: List[dict]) -> Tuple[List[dict], List[dict]]:
    """Validate ml_feature_store_v2 records."""
    validator = PreWriteValidator('ml_feature_store_v2')
    return validator.validate(records)
