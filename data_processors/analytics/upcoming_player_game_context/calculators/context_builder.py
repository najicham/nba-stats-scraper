"""
Context Builder - Final Context Assembly

Assembles the complete player game context record from all component pieces.

Extracted from upcoming_player_game_context_processor.py for maintainability.
"""

import logging
import hashlib
import json
from datetime import datetime, date, timezone
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class ContextBuilder:
    """
    Builder for assembling final player game context records.

    Takes all component pieces (fatigue, performance, team context, etc.)
    and builds the complete output record with all required fields.
    """

    # Fields included in data_hash calculation
    HASH_FIELDS = [
        # Core identifiers
        'player_lookup',
        'universal_player_id',
        'game_id',
        'game_date',
        'team_abbr',
        'opponent_team_abbr',
        'has_prop_line',

        # Player prop betting context
        'current_points_line',
        'opening_points_line',
        'line_movement',
        'current_points_line_source',
        'opening_points_line_source',

        # Game spread context
        'game_spread',
        'opening_spread',
        'spread_movement',
        'game_spread_source',
        'spread_public_betting_pct',

        # Game total context
        'game_total',
        'opening_total',
        'total_movement',
        'game_total_source',
        'total_public_betting_pct',

        # Pre-game context
        'pace_differential',
        'opponent_pace_last_10',
        'game_start_time_local',
        'opponent_ft_rate_allowed',
        'home_game',
        'back_to_back',
        'season_phase',
        'projected_usage_rate',

        # Player fatigue analysis
        'days_rest',
        'days_rest_before_last_game',
        'days_since_2_plus_days_rest',
        'games_in_last_7_days',
        'games_in_last_14_days',
        'minutes_in_last_7_days',
        'minutes_in_last_14_days',
        'avg_minutes_per_game_last_7',
        'back_to_backs_last_14_days',
        'avg_usage_rate_last_7_games',
        'fourth_quarter_minutes_last_7',
        'clutch_minutes_last_7_games',

        # Travel context
        'travel_miles',
        'time_zone_changes',
        'consecutive_road_games',
        'miles_traveled_last_14_days',
        'time_zones_crossed_last_14_days',

        # Player characteristics
        'player_age',

        # Recent performance context
        'points_avg_last_5',
        'points_avg_last_10',
        'prop_over_streak',
        'prop_under_streak',
        'star_teammates_out',
        'opponent_def_rating_last_10',
        'shooting_pct_decline_last_5',
        'fourth_quarter_production_last_7',

        # Forward-looking schedule context
        'next_game_days_rest',
        'games_in_next_7_days',
        'next_opponent_win_pct',
        'next_game_is_primetime',

        # Opponent asymmetry context
        'opponent_days_rest',
        'opponent_games_in_next_7_days',
        'opponent_next_game_days_rest',

        # Real-time updates
        'player_status',
        'injury_report',
        'questionable_teammates',
        'probable_teammates',

        # Completeness metrics
        'expected_games_count',
        'actual_games_count',
        'completeness_percentage',
        'missing_games_count',
        'is_production_ready',
        'manual_override_required',
        'season_boundary_detected',
        'backfill_bootstrap_mode',
        'processing_decision_reason',

        # Multi-window completeness
        'l5_completeness_pct',
        'l5_is_complete',
        'l10_completeness_pct',
        'l10_is_complete',
        'l7d_completeness_pct',
        'l7d_is_complete',
        'l14d_completeness_pct',
        'l14d_is_complete',
        'l30d_completeness_pct',
        'l30d_is_complete',
        'all_windows_complete',

        # Update tracking (context_version only - not timestamps)
        'context_version',
    ]

    def __init__(self, roster_ages: Optional[Dict] = None):
        """
        Initialize context builder.

        Args:
            roster_ages: Optional dict of player_lookup -> age
        """
        self.roster_ages = roster_ages or {}

    def build_context_record(
        self,
        player_lookup: str,
        universal_player_id: Optional[str],
        game_id: str,
        target_date: date,
        team_abbr: str,
        opponent_team_abbr: str,
        game_info: Dict,
        has_prop_line: bool,
        prop_info: Dict,
        game_lines_info: Dict,
        fatigue_metrics: Dict,
        performance_metrics: Dict,
        pace_differential: float,
        opponent_pace_last_10: float,
        opponent_ft_rate_allowed: float,
        opponent_def_rating: float,
        opponent_off_rating: float,
        opponent_rebounding_rate: float,
        opponent_pace_variance: float,
        opponent_ft_rate_variance: float,
        opponent_def_rating_variance: float,
        opponent_off_rating_variance: float,
        opponent_rebounding_rate_variance: float,
        star_teammates_out: int,
        questionable_star_teammates: int,
        star_tier_out: Optional[str],
        travel_context: Dict,
        injury_info: Dict,
        source_tracking_fields: Dict,
        data_quality: Dict,
        completeness_l5: Dict,
        completeness_l10: Dict,
        completeness_l7d: Dict,
        completeness_l14d: Dict,
        completeness_l30d: Dict,
        circuit_breaker_status: Dict,
        is_bootstrap: bool,
        is_season_boundary: bool,
        season_phase: str,
        game_start_time_local: Optional[str],
        spread_public_betting_pct: Optional[float],
        total_public_betting_pct: Optional[float],
        schedule_context: Optional[Dict] = None,
        opponent_schedule_asymmetry: Optional[Dict] = None,
        probable_teammates: Optional[int] = None
    ) -> Dict:
        """
        Build complete context record from all component pieces.

        Args:
            player_lookup: Player identifier
            universal_player_id: Universal player ID from registry
            game_id: Game identifier
            target_date: Target game date
            team_abbr: Player's team abbreviation
            opponent_team_abbr: Opponent team abbreviation
            game_info: Game context (home/away teams, etc.)
            has_prop_line: Whether player has a prop line
            prop_info: Prop betting information
            game_lines_info: Game lines (spreads, totals)
            fatigue_metrics: Fatigue metrics dict
            performance_metrics: Performance metrics dict
            pace_differential: Pace differential
            opponent_pace_last_10: Opponent pace last 10 games
            opponent_ft_rate_allowed: Opponent FT rate allowed
            opponent_def_rating: Opponent defensive rating
            opponent_off_rating: Opponent offensive rating
            opponent_rebounding_rate: Opponent rebounding rate
            opponent_pace_variance: Opponent pace variance
            opponent_ft_rate_variance: Opponent FT rate variance
            opponent_def_rating_variance: Opponent defensive rating variance
            opponent_off_rating_variance: Opponent offensive rating variance
            opponent_rebounding_rate_variance: Opponent rebounding rate variance
            star_teammates_out: Number of star teammates out
            questionable_star_teammates: Number of questionable star teammates
            star_tier_out: Star tier out
            travel_context: Travel context dict
            injury_info: Injury information dict
            source_tracking_fields: Source tracking fields
            data_quality: Data quality dict
            completeness_l5: L5 completeness dict
            completeness_l10: L10 completeness dict
            completeness_l7d: L7D completeness dict
            completeness_l14d: L14D completeness dict
            completeness_l30d: L30D completeness dict
            circuit_breaker_status: Circuit breaker status dict
            is_bootstrap: Whether in bootstrap mode
            is_season_boundary: Whether at season boundary
            season_phase: Season phase
            game_start_time_local: Game start time local
            spread_public_betting_pct: Spread public betting percentage
            total_public_betting_pct: Total public betting percentage

        Returns:
            Dict with complete context record ready for BigQuery insertion
        """
        context = {
            # Core identifiers
            'player_lookup': player_lookup,
            'universal_player_id': universal_player_id,
            'game_id': game_id,
            'game_date': target_date.isoformat(),
            'team_abbr': team_abbr,
            'opponent_team_abbr': opponent_team_abbr,

            # Has prop line flag (NEW - v3.2 All-Player Predictions)
            'has_prop_line': has_prop_line,

            # Prop betting context
            'current_points_line': prop_info.get('current_line'),
            'opening_points_line': prop_info.get('opening_line'),
            'line_movement': prop_info.get('line_movement'),
            'current_points_line_source': prop_info.get('current_source'),
            'opening_points_line_source': prop_info.get('opening_source'),

            # Game spread context
            'game_spread': game_lines_info.get('game_spread'),
            'opening_spread': game_lines_info.get('opening_spread'),
            'spread_movement': game_lines_info.get('spread_movement'),
            'game_spread_source': game_lines_info.get('spread_source'),
            'spread_public_betting_pct': spread_public_betting_pct,

            # Game total context
            'game_total': game_lines_info.get('game_total'),
            'opening_total': game_lines_info.get('opening_total'),
            'total_movement': game_lines_info.get('total_movement'),
            'game_total_source': game_lines_info.get('total_source'),
            'total_public_betting_pct': total_public_betting_pct,

            # Pre-game context
            'pace_differential': pace_differential,
            'opponent_pace_last_10': opponent_pace_last_10,
            'game_start_time_local': game_start_time_local,
            'opponent_ft_rate_allowed': opponent_ft_rate_allowed,
            'home_game': (team_abbr == game_info['home_team_abbr']),
            'back_to_back': fatigue_metrics['back_to_back'],
            'season_phase': season_phase,
            'projected_usage_rate': None,  # TODO: future

            # Fatigue metrics
            **fatigue_metrics,

            # Travel context
            'travel_miles': travel_context.get('travel_miles'),
            'time_zone_changes': travel_context.get('time_zone_changes'),
            'consecutive_road_games': travel_context.get('consecutive_road_games'),
            'miles_traveled_last_14_days': travel_context.get('miles_traveled_last_14_days'),
            'time_zones_crossed_last_14_days': travel_context.get('time_zones_crossed_last_14_days'),

            # Player characteristics
            'player_age': self.roster_ages.get(player_lookup),

            # Performance metrics
            **performance_metrics,

            # Override opponent metrics with calculated values
            'opponent_def_rating_last_10': opponent_def_rating,
            'opponent_off_rating_last_10': opponent_off_rating,
            'opponent_rebounding_rate': opponent_rebounding_rate,
            'opponent_pace_variance': opponent_pace_variance,
            'opponent_ft_rate_variance': opponent_ft_rate_variance,
            'opponent_def_rating_variance': opponent_def_rating_variance,
            'opponent_off_rating_variance': opponent_off_rating_variance,
            'opponent_rebounding_rate_variance': opponent_rebounding_rate_variance,

            # Forward-looking schedule (TODO: future)
            'next_game_days_rest': 0,
            'games_in_next_7_days': 0,
            'next_opponent_win_pct': None,
            'next_game_is_primetime': False,

            # Opponent asymmetry (TODO: future)
            'opponent_days_rest': 0,
            'opponent_games_in_next_7_days': 0,
            'opponent_next_game_days_rest': 0,

            # Real-time updates
            'player_status': injury_info.get('status'),
            'injury_report': injury_info.get('report'),
            'star_teammates_out': star_teammates_out,
            'questionable_star_teammates': questionable_star_teammates,
            'star_tier_out': star_tier_out,
            'probable_teammates': None,  # TODO: future

            # Source tracking
            **source_tracking_fields,

            # Data quality
            **data_quality,

            # Completeness Metadata (25 fields)
            'expected_games_count': completeness_l30d['expected_count'],
            'actual_games_count': completeness_l30d['actual_count'],
            'completeness_percentage': completeness_l30d['completeness_pct'],
            'missing_games_count': completeness_l30d['missing_count'],

            # Production Readiness
            'is_production_ready': is_season_boundary or is_bootstrap or (
                completeness_l5['is_production_ready'] and
                completeness_l10['is_production_ready'] and
                completeness_l7d['is_production_ready'] and
                completeness_l14d['is_production_ready'] and
                completeness_l30d['is_production_ready']
            ),
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

            # Multi-Window Completeness (11 fields)
            'l5_completeness_pct': completeness_l5['completeness_pct'],
            'l5_is_complete': completeness_l5['is_complete'],
            'l10_completeness_pct': completeness_l10['completeness_pct'],
            'l10_is_complete': completeness_l10['is_complete'],
            'l7d_completeness_pct': completeness_l7d['completeness_pct'],
            'l7d_is_complete': completeness_l7d['is_complete'],
            'l14d_completeness_pct': completeness_l14d['completeness_pct'],
            'l14d_is_complete': completeness_l14d['is_complete'],
            'l30d_completeness_pct': completeness_l30d['completeness_pct'],
            'l30d_is_complete': completeness_l30d['is_complete'],
            'all_windows_complete': (
                completeness_l5['is_complete'] and
                completeness_l10['is_complete'] and
                completeness_l7d['is_complete'] and
                completeness_l14d['is_complete'] and
                completeness_l30d['is_complete']
            ),

            # Update tracking
            'context_version': 1,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'processed_at': datetime.now(timezone.utc).isoformat()
        }

        # Calculate data_hash AFTER all fields are populated
        context['data_hash'] = self._calculate_data_hash(context)

        return context

    def _calculate_data_hash(self, record: Dict) -> str:
        """
        Calculate SHA256 hash of meaningful analytics fields.

        Args:
            record: Complete context record

        Returns:
            16-character hex hash
        """
        hash_data = {field: record.get(field) for field in self.HASH_FIELDS}
        sorted_data = json.dumps(hash_data, sort_keys=True, default=str)
        return hashlib.sha256(sorted_data.encode()).hexdigest()[:16]
