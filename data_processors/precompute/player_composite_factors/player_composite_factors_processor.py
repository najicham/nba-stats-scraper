"""
Path: data_processors/precompute/player_composite_factors/player_composite_factors_processor.py

Player Composite Factors Processor - Phase 4 Precompute
========================================================

Calculates composite adjustment factors that influence player predictions.
Combines multiple contextual signals into quantified adjustments.

Week 1-4 Implementation (v1_4factors):
    Active Factors (4):
        1. Fatigue Score (0-100) → Adjustment (-5.0 to 0.0)
        2. Shot Zone Mismatch (-10.0 to +10.0)
        3. Pace Score (-3.0 to +3.0)
        4. Usage Spike Score (-3.0 to +3.0)
    
    Deferred Factors (4) - Set to 0 (neutral):
        5. Referee Favorability (0.0)
        6. Look-Ahead Pressure (0.0)
        7. Travel Impact (0.0)
        8. Opponent Strength (0.0)

Dependencies:
    - nba_analytics.upcoming_player_game_context (Phase 3)
    - nba_analytics.upcoming_team_game_context (Phase 3)
    - nba_precompute.player_shot_zone_analysis (Phase 4)
    - nba_precompute.team_defense_zone_analysis (Phase 4)

Output:
    - nba_precompute.player_composite_factors

Schedule: Nightly at 11:30 PM (after Phase 3 & 4 upstream)

Version: 1.0 (v1_4factors)
Updated: November 1, 2025
"""

import logging
import json
from datetime import datetime, date, timezone
from typing import Dict, List, Optional
import pandas as pd

from data_processors.precompute.precompute_base import PrecomputeProcessorBase

# Configure logging
logger = logging.getLogger(__name__)


class PlayerCompositeFactorsProcessor(PrecomputeProcessorBase):
    """
    Calculate composite adjustment factors for player predictions.
    
    Processes upcoming games to generate contextual adjustments that
    influence baseline predictions. Week 1-4 implementation includes
    4 active factors with 4 deferred factors set to neutral (0).
    """
    
    # Processor configuration
    table_name = "player_composite_factors"
    dataset_id = "nba_precompute"
    processing_strategy = "MERGE_UPDATE"
    
    # Required options
    required_opts = ['analysis_date']
    
    # Calculation version
    calculation_version = "v1_4factors"
    
    # League constants
    league_avg_pace = 100.0  # Baseline NBA pace
    
    def __init__(self):
        """Initialize processor."""
        super().__init__()
        
        # DataFrames for extracted data
        self.player_context_df = None
        self.team_context_df = None
        self.player_shot_df = None
        self.team_defense_df = None
        
        # Early season tracking
        self.early_season_flag = False
        self.insufficient_data_reason = None
        
        # Failed entity tracking
        self.failed_entities = []
    
    # ========================================================================
    # DEPENDENCY CONFIGURATION
    # ========================================================================
    
    def get_dependencies(self) -> dict:
        """
        Define upstream data dependencies.
        
        Returns 4 critical sources needed for composite factor calculation:
        - Player game context (fatigue, usage, pace info)
        - Team game context (betting lines, opponent info)
        - Player shot zone analysis (scoring patterns)
        - Team defense zone analysis (defensive weaknesses)
        """
        return {
            'nba_analytics.upcoming_player_game_context': {
                'description': 'Player context for upcoming games',
                'date_field': 'game_date',
                'check_type': 'date_match',
                'expected_count_min': 100,
                'max_age_hours': 12,
                'critical': True,
                'field_prefix': 'source_player_context'
            },
            'nba_analytics.upcoming_team_game_context': {
                'description': 'Team context for upcoming games',
                'date_field': 'game_date',
                'check_type': 'date_match',
                'expected_count_min': 10,
                'max_age_hours': 12,
                'critical': True,
                'field_prefix': 'source_team_context'
            },
            'nba_precompute.player_shot_zone_analysis': {
                'description': 'Player shot zone patterns',
                'date_field': 'analysis_date',
                'check_type': 'date_match',
                'expected_count_min': 100,
                'max_age_hours': 24,
                'critical': True,
                'field_prefix': 'source_player_shot'
            },
            'nba_precompute.team_defense_zone_analysis': {
                'description': 'Team defensive zone weaknesses',
                'date_field': 'analysis_date',
                'check_type': 'date_match',
                'expected_count_min': 30,
                'max_age_hours': 24,
                'critical': True,
                'field_prefix': 'source_team_defense'
            }
        }
    
    # ========================================================================
    # DATA EXTRACTION
    # ========================================================================
    
    def extract_raw_data(self) -> None:
        """
        Extract data from Phase 3 analytics and Phase 4 precompute tables.
        
        Pulls:
        1. Player game context (fatigue indicators, usage projections)
        2. Team game context (pace, betting lines)
        3. Player shot zone analysis (scoring patterns)
        4. Team defense zone analysis (defensive weaknesses)
        """
        if 'analysis_date' not in self.opts:
            raise ValueError("analysis_date required in opts")
        
        analysis_date = self.opts['analysis_date']
        logger.info(f"Extracting data for {analysis_date}")
        
        # Check for early season before extracting
        if self._is_early_season(analysis_date):
            logger.info("Early season detected - creating placeholder records")
            self._create_early_season_placeholders(analysis_date)
            return
        
        # Extract player context
        player_context_query = f"""
        SELECT
            player_lookup,
            universal_player_id,
            game_id,
            game_date,
            opponent_team_abbr,
            days_rest,
            back_to_back,
            games_in_last_7_days,
            minutes_in_last_7_days,
            avg_minutes_per_game_last_7,
            back_to_backs_last_14_days,
            player_age,
            projected_usage_rate,
            avg_usage_rate_last_7_games,
            star_teammates_out,
            pace_differential,
            opponent_pace_last_10
        FROM `{self.project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date = '{analysis_date}'
        """
        
        self.player_context_df = self.bq_client.query(player_context_query).to_dataframe()
        logger.info(f"Extracted {len(self.player_context_df)} player context records")
        
        # Extract team context
        team_context_query = f"""
        SELECT
            team_abbr,
            game_id,
            game_date,
            game_total,
            game_spread
        FROM `{self.project_id}.nba_analytics.upcoming_team_game_context`
        WHERE game_date = '{analysis_date}'
        """
        
        self.team_context_df = self.bq_client.query(team_context_query).to_dataframe()
        logger.info(f"Extracted {len(self.team_context_df)} team context records")
        
        # Extract player shot zone analysis
        player_shot_query = f"""
        SELECT
            player_lookup,
            analysis_date,
            primary_scoring_zone,
            paint_rate_last_10,
            mid_range_rate_last_10,
            three_pt_rate_last_10,
            early_season_flag
        FROM `{self.project_id}.nba_precompute.player_shot_zone_analysis`
        WHERE analysis_date = '{analysis_date}'
        """
        
        self.player_shot_df = self.bq_client.query(player_shot_query).to_dataframe()
        logger.info(f"Extracted {len(self.player_shot_df)} player shot zone records")
        
        # Extract team defense zone analysis
        team_defense_query = f"""
        SELECT
            team_abbr,
            analysis_date,
            paint_defense_vs_league_avg,
            mid_range_defense_vs_league_avg,
            three_pt_defense_vs_league_avg,
            weakest_zone,
            early_season_flag
        FROM `{self.project_id}.nba_precompute.team_defense_zone_analysis`
        WHERE analysis_date = '{analysis_date}'
        """
        
        self.team_defense_df = self.bq_client.query(team_defense_query).to_dataframe()
        logger.info(f"Extracted {len(self.team_defense_df)} team defense zone records")
    
    def _is_early_season(self, analysis_date: date) -> bool:
        """
        Check if we're in early season (insufficient data).
        
        Early season = >50% of players have early_season_flag set in
        their shot zone analysis.
        """
        try:
            early_season_query = f"""
            SELECT
                COUNT(*) as total_players,
                SUM(CASE WHEN early_season_flag = TRUE THEN 1 ELSE 0 END) as early_season_players
            FROM `{self.project_id}.nba_precompute.player_shot_zone_analysis`
            WHERE analysis_date = '{analysis_date}'
            """
            
            result_df = self.bq_client.query(early_season_query).to_dataframe()
            
            if result_df.empty:
                return False
            
            total = result_df.iloc[0].get('total_players', 0)
            early = result_df.iloc[0].get('early_season_players', 0)
            
            if total > 0 and (early / total) > 0.5:
                self.early_season_flag = True  # Set instance flag
                self.insufficient_data_reason = f"Early season: {early}/{total} players lack historical data"
                return True
            
            return False
            
        except Exception as e:
            logger.warning(f"Error checking early season status: {e}")
            return False
    
    def _create_early_season_placeholders(self, analysis_date: date) -> None:
        """
        Create placeholder records for early season.
        
        All factor scores set to NULL, early_season_flag = TRUE.
        """
        # Get list of players with games
        player_query = f"""
        SELECT
            player_lookup,
            universal_player_id,
            game_id,
            game_date
        FROM `{self.project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date = '{analysis_date}'
        """
        
        players_df = self.bq_client.query(player_query).to_dataframe()
        
        self.transformed_data = []
        
        for _, row in players_df.iterrows():
            record = {
                'player_lookup': row['player_lookup'],
                'universal_player_id': row['universal_player_id'],
                'game_date': row['game_date'],
                'game_id': row['game_id'],
                'analysis_date': analysis_date,
                
                # All scores NULL
                'fatigue_score': None,
                'shot_zone_mismatch_score': None,
                'pace_score': None,
                'usage_spike_score': None,
                'referee_favorability_score': 0.0,
                'look_ahead_pressure_score': 0.0,
                'travel_impact_score': 0.0,
                'opponent_strength_score': 0.0,
                'total_composite_adjustment': None,
                
                # Metadata
                'calculation_version': self.calculation_version,
                'early_season_flag': True,
                'insufficient_data_reason': self.insufficient_data_reason,
                'data_completeness_pct': 0.0,
                'missing_data_fields': 'All: Early season',
                'has_warnings': True,
                'warning_details': 'EARLY_SEASON: Insufficient historical data',
                
                # Timestamps
                'created_at': datetime.now(timezone.utc).isoformat(),
                'processed_at': datetime.now(timezone.utc).isoformat()
            }
            
            # Add source tracking fields
            record.update(self.build_source_tracking_fields())
            
            self.transformed_data.append(record)
        
        logger.info(f"Created {len(self.transformed_data)} early season placeholder records")
    
    # ========================================================================
    # CALCULATION - MAIN FLOW
    # ========================================================================
    
    def calculate_precompute(self) -> None:
        """
        Calculate composite factors for each player.
        
        Flow:
        1. Iterate through each player in upcoming games
        2. Calculate 4 active factor scores
        3. Convert scores to adjustments
        4. Sum to total composite adjustment
        5. Add metadata, quality checks, source tracking
        """
        if self.early_season_flag:
            # Placeholders already created in extract
            return
        
        if self.player_context_df is None or self.player_context_df.empty:
            logger.warning("No player context data to process")
            return
        
        self.transformed_data = []
        self.failed_entities = []
        
        logger.info(f"Calculating composite factors for {len(self.player_context_df)} players")
        
        for idx, player_row in self.player_context_df.iterrows():
            try:
                record = self._calculate_player_composite(player_row)
                self.transformed_data.append(record)
                
            except Exception as e:
                player_lookup = player_row.get('player_lookup', 'unknown')
                logger.error(f"Failed to process {player_lookup}: {e}")
                
                self.failed_entities.append({
                    'entity_id': player_lookup,
                    'entity_type': 'player',
                    'reason': str(e),
                    'category': 'calculation_error'
                })
        
        logger.info(f"Successfully processed {len(self.transformed_data)} players")
        if self.failed_entities:
            logger.warning(f"Failed to process {len(self.failed_entities)} players")
    
    def _calculate_player_composite(self, player_row: pd.Series) -> dict:
        """
        Calculate all composite factors for one player.
        
        Returns complete record dict ready for BigQuery.
        """
        player_lookup = player_row['player_lookup']
        
        # Get related data
        player_shot = self._get_player_shot_data(player_lookup)
        opponent_abbr = player_row.get('opponent_team_abbr')
        team_defense = self._get_team_defense_data(opponent_abbr)
        
        # Calculate 4 active factor scores
        fatigue_score = self._calculate_fatigue_score(player_row)
        shot_zone_score = self._calculate_shot_zone_mismatch(player_shot, team_defense)
        pace_score = self._calculate_pace_score(player_row)
        usage_spike_score = self._calculate_usage_spike_score(player_row)
        
        # Convert scores to adjustments
        fatigue_adj = self._fatigue_score_to_adjustment(fatigue_score)
        shot_zone_adj = shot_zone_score  # Direct conversion
        pace_adj = pace_score  # Direct conversion
        usage_spike_adj = usage_spike_score  # Direct conversion
        
        # Deferred factors (set to 0)
        referee_adj = 0.0
        look_ahead_adj = 0.0
        travel_adj = 0.0
        opponent_strength_adj = 0.0
        
        # Sum all adjustments
        total_adjustment = (
            fatigue_adj + shot_zone_adj + pace_adj + usage_spike_adj +
            referee_adj + look_ahead_adj + travel_adj + opponent_strength_adj
        )
        
        # Calculate data quality metrics
        completeness_pct, missing_fields = self._calculate_completeness(
            player_row, player_shot, team_defense
        )
        
        # Check for warnings
        has_warnings, warning_details = self._check_warnings(
            fatigue_score, shot_zone_score, total_adjustment
        )
        
        # Build output record
        record = {
            # Identifiers
            'player_lookup': player_lookup,
            'universal_player_id': player_row['universal_player_id'],
            'game_date': player_row['game_date'],
            'game_id': player_row['game_id'],
            'analysis_date': self.opts['analysis_date'],
            
            # Active factor scores (v1)
            'fatigue_score': fatigue_score,
            'shot_zone_mismatch_score': shot_zone_score,
            'pace_score': pace_score,
            'usage_spike_score': usage_spike_score,
            
            # Deferred factor scores (neutral for now)
            'referee_favorability_score': referee_adj,
            'look_ahead_pressure_score': look_ahead_adj,
            'travel_impact_score': travel_adj,
            'opponent_strength_score': opponent_strength_adj,
            
            # Total composite adjustment
            'total_composite_adjustment': round(total_adjustment, 2),
            
            # Context JSONs for debugging
            'fatigue_context_json': json.dumps(
                self._build_fatigue_context(player_row, fatigue_score)
            ),
            'shot_zone_context_json': json.dumps(
                self._build_shot_zone_context(player_shot, team_defense, shot_zone_score)
            ),
            'pace_context_json': json.dumps(
                self._build_pace_context(player_row, pace_score)
            ),
            'usage_context_json': json.dumps(
                self._build_usage_context(player_row, usage_spike_score)
            ),
            
            # Metadata
            'calculation_version': self.calculation_version,
            'early_season_flag': self.early_season_flag,
            'insufficient_data_reason': self.insufficient_data_reason,
            'data_completeness_pct': completeness_pct,
            'missing_data_fields': missing_fields,
            'has_warnings': has_warnings,
            'warning_details': warning_details,
            
            # Timestamps
            'created_at': datetime.now(timezone.utc).isoformat(),
            'processed_at': datetime.now(timezone.utc).isoformat()
        }
        
        # Add v4.0 source tracking fields
        record.update(self.build_source_tracking_fields())
        
        return record
    
    # ========================================================================
    # FACTOR CALCULATIONS - ACTIVE FACTORS
    # ========================================================================
    
    def _calculate_fatigue_score(self, player_row: pd.Series) -> int:
        """
        Calculate fatigue score (0-100).
        
        Higher score = better rested (less fatigued).
        
        Factors:
        - Days rest (0 = B2B, 1-2 = normal, 3+ = bonus)
        - Recent workload (games & minutes in last 7 days)
        - Recent back-to-backs (last 14 days)
        - Player age (30+ penalty, 35+ bigger penalty)
        
        Returns:
            int: Fatigue score (0-100), clamped to range
        """
        score = 100  # Start at baseline
        
        # Days rest impact
        days_rest = int(player_row.get('days_rest', 1))
        back_to_back = bool(player_row.get('back_to_back', False))
        
        if back_to_back:
            score -= 15  # Heavy penalty for B2B
        elif days_rest >= 3:
            score += 5  # Bonus for extra rest
        
        # Recent workload
        games_last_7 = int(player_row.get('games_in_last_7_days', 3))
        minutes_last_7 = float(player_row.get('minutes_in_last_7_days', 200))
        avg_mpg_last_7 = float(player_row.get('avg_minutes_per_game_last_7', 30))
        
        if games_last_7 >= 4:
            score -= 10  # Playing frequently
        
        if minutes_last_7 > 240:
            score -= 10  # Heavy minutes load
        
        if avg_mpg_last_7 > 35:
            score -= 8  # Playing long stretches
        
        # Recent B2Bs
        recent_b2bs = int(player_row.get('back_to_backs_last_14_days', 0))
        if recent_b2bs >= 2:
            score -= 12  # Multiple recent B2Bs
        elif recent_b2bs == 1:
            score -= 5
        
        # Age factor
        age = int(player_row.get('player_age', 25))
        if age >= 35:
            score -= 10  # Veteran penalty
        elif age >= 30:
            score -= 5
        
        # Clamp to 0-100
        return max(0, min(100, score))
    
    def _calculate_shot_zone_mismatch(
        self,
        player_shot: Optional[pd.Series],
        team_defense: Optional[pd.Series]
    ) -> float:
        """
        Calculate shot zone mismatch score (-10.0 to +10.0).
        
        Positive = favorable matchup (player's strength vs defense weakness)
        Negative = unfavorable matchup (player's strength vs defense strength)
        
        Logic:
        1. Identify player's primary scoring zone
        2. Get opponent's defense rating in that zone
        3. Weight by player's usage of that zone
        4. Apply extreme matchup bonus if diff > 5.0
        
        Args:
            player_shot: Player shot zone data (or None if missing)
            team_defense: Team defense data (or None if missing)
        
        Returns:
            float: Mismatch score (-10.0 to +10.0), 0.0 if data missing
        """
        if player_shot is None or team_defense is None:
            return 0.0
        
        # Get player's primary zone and usage rate
        primary_zone = player_shot.get('primary_scoring_zone', 'paint')
        
        # Map zone to usage rate field
        zone_rate_map = {
            'paint': 'paint_rate_last_10',
            'mid_range': 'mid_range_rate_last_10',
            'perimeter': 'three_pt_rate_last_10'
        }
        
        zone_rate_field = zone_rate_map.get(primary_zone, 'paint_rate_last_10')
        zone_usage_pct = float(player_shot.get(zone_rate_field, 50.0))
        
        # Get opponent's defense rating in that zone
        defense_field_map = {
            'paint': 'paint_defense_vs_league_avg',
            'mid_range': 'mid_range_defense_vs_league_avg',
            'perimeter': 'three_pt_defense_vs_league_avg'
        }
        
        defense_field = defense_field_map.get(primary_zone, 'paint_defense_vs_league_avg')
        defense_rating = float(team_defense.get(defense_field, 0.0))
        
        # Calculate mismatch
        # Positive defense rating = weak defense (good for offense)
        # Negative defense rating = strong defense (bad for offense)
        base_mismatch = defense_rating
        
        # Weight by zone usage (50%+ usage = full weight, lower = reduced)
        usage_weight = min(zone_usage_pct / 50.0, 1.0)
        weighted_mismatch = base_mismatch * usage_weight
        
        # Apply extreme matchup bonus (20% boost if abs > 5.0)
        if abs(weighted_mismatch) > 5.0:
            weighted_mismatch *= 1.2
        
        # Clamp to -10.0 to +10.0
        return max(-10.0, min(10.0, weighted_mismatch))
    
    def _calculate_pace_score(self, player_row: pd.Series) -> float:
        """
        Calculate pace score (-3.0 to +3.0).
        
        Faster pace = more possessions = more opportunities = positive
        Slower pace = fewer possessions = fewer opportunities = negative
        
        Formula: pace_differential / 2.0
        (Scaled down from typical 4-6 point differentials)
        
        Args:
            player_row: Player context data
        
        Returns:
            float: Pace score (-3.0 to +3.0)
        """
        pace_diff = float(player_row.get('pace_differential', 0.0))
        
        # Simple scaling: divide by 2 to get reasonable adjustment range
        pace_score = pace_diff / 2.0
        
        # Clamp to -3.0 to +3.0
        return max(-3.0, min(3.0, pace_score))
    
    def _calculate_usage_spike_score(self, player_row: pd.Series) -> float:
        """
        Calculate usage spike score (-3.0 to +3.0).
        
        Higher projected usage vs recent = more opportunities = positive
        Lower projected usage vs recent = fewer opportunities = negative
        
        Star teammates out amplifies positive spikes:
        - 1 star out: +15% boost
        - 2+ stars out: +30% boost
        
        Args:
            player_row: Player context data
        
        Returns:
            float: Usage spike score (-3.0 to +3.0)
        """
        projected_usage = float(player_row.get('projected_usage_rate', 25.0))
        baseline_usage = float(player_row.get('avg_usage_rate_last_7_games', 25.0))
        stars_out = int(player_row.get('star_teammates_out', 0))
        
        # Avoid division by zero
        if baseline_usage == 0:
            return 0.0
        
        # Calculate usage differential
        usage_diff = projected_usage - baseline_usage
        
        # Scale to adjustment range (typical usage diffs are 2-5 points)
        base_score = usage_diff * 0.3
        
        # Apply star teammates out boost (only for positive spikes)
        if stars_out > 0 and base_score > 0:
            if stars_out >= 2:
                base_score *= 1.30  # 30% boost
            else:
                base_score *= 1.15  # 15% boost
        
        # Clamp to -3.0 to +3.0
        return max(-3.0, min(3.0, base_score))
    
    # ========================================================================
    # SCORE CONVERSIONS
    # ========================================================================
    
    def _fatigue_score_to_adjustment(self, fatigue_score: int) -> float:
        """
        Convert fatigue score (0-100) to adjustment (-5.0 to 0.0).
        
        Linear mapping:
        - 100 (fresh) → 0.0 adjustment
        - 80 → -1.0
        - 50 → -2.5
        - 0 (exhausted) → -5.0 adjustment
        
        Formula: (fatigue_score - 100) / 20
        """
        return (fatigue_score - 100) / 20.0
    
    # ========================================================================
    # CONTEXT BUILDING (for debugging)
    # ========================================================================
    
    def _build_fatigue_context(self, player_row: pd.Series, fatigue_score: float) -> dict:
        """Build fatigue factor context for debugging."""
        days_rest = int(player_row.get('days_rest', 0))
        back_to_back = bool(player_row.get('back_to_back', False))
        
        penalties = []
        bonuses = []
        
        if back_to_back:
            penalties.append("back_to_back: -15")
        if int(player_row.get('games_in_last_7_days', 0)) >= 4:
            penalties.append("frequent_games: -10")
        if float(player_row.get('minutes_in_last_7_days', 0)) > 240:
            penalties.append("heavy_minutes: -10")
        if int(player_row.get('player_age', 0)) >= 35:
            penalties.append("veteran_age: -10")
        
        if days_rest >= 3:
            bonuses.append("extra_rest: +5")
        
        return {
            'days_rest': days_rest,
            'back_to_back': back_to_back,
            'games_last_7': int(player_row.get('games_in_last_7_days', 0)),
            'minutes_last_7': float(player_row.get('minutes_in_last_7_days', 0)),
            'avg_minutes_pg_last_7': float(player_row.get('avg_minutes_per_game_last_7', 0)),
            'back_to_backs_last_14': int(player_row.get('back_to_backs_last_14_days', 0)),
            'player_age': int(player_row.get('player_age', 25)),
            'penalties_applied': penalties,
            'bonuses_applied': bonuses,
            'final_score': int(fatigue_score)
        }
    
    def _build_shot_zone_context(
        self,
        player_shot: Optional[pd.Series],
        team_defense: Optional[pd.Series],
        score: float
    ) -> dict:
        """Build shot zone mismatch context for debugging."""
        if player_shot is None or team_defense is None:
            return {'missing_data': True}
        
        primary_zone = str(player_shot.get('primary_scoring_zone', 'unknown'))
        
        zone_rate_map = {
            'paint': 'paint_rate_last_10',
            'mid_range': 'mid_range_rate_last_10',
            'perimeter': 'three_pt_rate_last_10'
        }
        
        rate_field = zone_rate_map.get(primary_zone, 'paint_rate_last_10')
        zone_freq = float(player_shot.get(rate_field, 0))
        
        defense_field_map = {
            'paint': 'paint_defense_vs_league_avg',
            'mid_range': 'mid_range_defense_vs_league_avg',
            'perimeter': 'three_pt_defense_vs_league_avg'
        }
        
        defense_field = defense_field_map.get(primary_zone, 'paint_defense_vs_league_avg')
        defense_rating = float(team_defense.get(defense_field, 0))
        
        mismatch_type = 'neutral'
        if score > 2.0:
            mismatch_type = 'favorable'
        elif score < -2.0:
            mismatch_type = 'unfavorable'
        
        return {
            'player_primary_zone': primary_zone,
            'primary_zone_frequency': zone_freq,
            'opponent_weak_zone': str(team_defense.get('weakest_zone', 'unknown')),
            'opponent_defense_vs_league': defense_rating,
            'mismatch_type': mismatch_type,
            'final_score': float(score)
        }
    
    def _build_pace_context(self, player_row: pd.Series, score: float) -> dict:
        """Build pace context for debugging."""
        pace_diff = float(player_row.get('pace_differential', 0))
        opponent_pace = float(player_row.get('opponent_pace_last_10', self.league_avg_pace))
        
        pace_env = 'normal'
        if pace_diff > 2.0:
            pace_env = 'fast'
        elif pace_diff < -2.0:
            pace_env = 'slow'
        
        return {
            'pace_differential': pace_diff,
            'opponent_pace_last_10': opponent_pace,
            'league_avg_pace': self.league_avg_pace,
            'pace_environment': pace_env,
            'final_score': float(score)
        }
    
    def _build_usage_context(self, player_row: pd.Series, score: float) -> dict:
        """Build usage spike context for debugging."""
        projected = float(player_row.get('projected_usage_rate', 0))
        baseline = float(player_row.get('avg_usage_rate_last_7_games', 0))
        stars_out = int(player_row.get('star_teammates_out', 0))
        
        usage_diff = projected - baseline
        
        trend = 'stable'
        if usage_diff > 2.0:
            trend = 'spike'
        elif usage_diff < -2.0:
            trend = 'drop'
        
        return {
            'projected_usage_rate': projected,
            'avg_usage_last_7': baseline,
            'usage_differential': usage_diff,
            'star_teammates_out': stars_out,
            'usage_trend': trend,
            'final_score': float(score)
        }
    
    # ========================================================================
    # DATA QUALITY CHECKS
    # ========================================================================
    
    def _calculate_completeness(
        self,
        player_row: pd.Series,
        player_shot: Optional[pd.Series],
        team_defense: Optional[pd.Series]
    ) -> tuple:
        """
        Calculate data completeness percentage and identify missing fields.
        
        Returns:
            tuple: (completeness_pct, missing_fields_str)
        """
        required_fields = {
            'player_context': ['days_rest', 'projected_usage_rate', 'pace_differential'],
            'player_shot_zone': player_shot is not None,
            'team_defense_zone': team_defense is not None
        }
        
        missing = []
        total_checks = 5  # 3 player fields + 2 zone datasets
        passed_checks = 0
        
        # Check player context fields
        for field in required_fields['player_context']:
            if pd.notna(player_row.get(field)):
                passed_checks += 1
            else:
                missing.append(field)
        
        # Check zone datasets
        if required_fields['player_shot_zone']:
            passed_checks += 1
        else:
            missing.append('player_shot_zone')
        
        if required_fields['team_defense_zone']:
            passed_checks += 1
        else:
            missing.append('team_defense_zone')
        
        completeness_pct = (passed_checks / total_checks) * 100
        missing_str = ', '.join(missing) if missing else None
        
        return round(completeness_pct, 1), missing_str
    
    def _check_warnings(
        self,
        fatigue_score: float,
        shot_zone_score: float,
        total_adj: float
    ) -> tuple:
        """
        Check for warning conditions.
        
        Returns:
            tuple: (has_warnings, warning_details_str)
        """
        warnings = []
        
        if fatigue_score < 50:
            warnings.append("EXTREME_FATIGUE: Player showing severe fatigue")
        
        if abs(shot_zone_score) > 8.0:
            warnings.append("EXTREME_MATCHUP: Unusual zone mismatch")
        
        if abs(total_adj) > 12.0:
            warnings.append("EXTREME_ADJUSTMENT: Very large composite adjustment")
        
        if warnings:
            return True, '; '.join(warnings)
        
        return False, None
    
    # ========================================================================
    # HELPER METHODS
    # ========================================================================
    
    def _get_player_shot_data(self, player_lookup: str) -> Optional[pd.Series]:
        """Get player shot zone data."""
        if self.player_shot_df is None or self.player_shot_df.empty:
            return None
        
        match = self.player_shot_df[
            self.player_shot_df['player_lookup'] == player_lookup
        ]
        
        if match.empty:
            return None
        
        return match.iloc[0]
    
    def _get_team_defense_data(self, team_abbr: str) -> Optional[pd.Series]:
        """Get team defense zone data."""
        if team_abbr is None or self.team_defense_df is None or self.team_defense_df.empty:
            return None
        
        match = self.team_defense_df[
            self.team_defense_df['team_abbr'] == team_abbr
        ]
        
        if match.empty:
            return None
        
        return match.iloc[0]
    
    # ========================================================================
    # SOURCE TRACKING (v4.0)
    # ========================================================================
    
    def build_source_tracking_fields(self) -> dict:
        """
        Build dict of all source tracking fields for output records.
        Uses attributes set by track_source_usage() in base class.
        
        Returns:
            Dict with 12 source tracking fields (3 per source × 4 sources)
        """
        fields = {}
        
        # Source 1: Player Context
        fields['source_player_context_last_updated'] = getattr(
            self, 'source_player_context_last_updated', None
        )
        fields['source_player_context_rows_found'] = getattr(
            self, 'source_player_context_rows_found', None
        )
        fields['source_player_context_completeness_pct'] = getattr(
            self, 'source_player_context_completeness_pct', None
        )
        
        # Source 2: Team Context
        fields['source_team_context_last_updated'] = getattr(
            self, 'source_team_context_last_updated', None
        )
        fields['source_team_context_rows_found'] = getattr(
            self, 'source_team_context_rows_found', None
        )
        fields['source_team_context_completeness_pct'] = getattr(
            self, 'source_team_context_completeness_pct', None
        )
        
        # Source 3: Player Shot Zone
        fields['source_player_shot_last_updated'] = getattr(
            self, 'source_player_shot_last_updated', None
        )
        fields['source_player_shot_rows_found'] = getattr(
            self, 'source_player_shot_rows_found', None
        )
        fields['source_player_shot_completeness_pct'] = getattr(
            self, 'source_player_shot_completeness_pct', None
        )
        
        # Source 4: Team Defense Zone
        fields['source_team_defense_last_updated'] = getattr(
            self, 'source_team_defense_last_updated', None
        )
        fields['source_team_defense_rows_found'] = getattr(
            self, 'source_team_defense_rows_found', None
        )
        fields['source_team_defense_completeness_pct'] = getattr(
            self, 'source_team_defense_completeness_pct', None
        )
        
        # Early season fields
        fields['early_season_flag'] = getattr(self, 'early_season_flag', None)
        fields['insufficient_data_reason'] = getattr(self, 'insufficient_data_reason', None)
        
        return fields
    
    # ========================================================================
    # STATS & REPORTING
    # ========================================================================
    
    def get_precompute_stats(self) -> dict:
        """Get processor-specific stats for logging."""
        return {
            'players_processed': len(self.transformed_data),
            'players_failed': len(self.failed_entities),
            'early_season': self.early_season_flag,
            'calculation_version': self.calculation_version
        }