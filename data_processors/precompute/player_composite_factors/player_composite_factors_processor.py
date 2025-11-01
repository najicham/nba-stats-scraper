#!/usr/bin/env python3
"""
Path: data_processors/precompute/player_composite_factors/player_composite_factors_processor.py

Player Composite Factors Processor
===================================

Purpose:
    Calculate composite adjustment factors for each player's upcoming game by combining
    multiple contextual elements (fatigue, matchup, pace, usage) into weighted scores.
    These factors adjust base predictions in Phase 5.

Implementation Strategy (Week 1-4):
    - ACTIVE (4 factors): fatigue, shot_zone_mismatch, pace, usage_spike
    - DEFERRED (4 factors): referee, look_ahead, matchup_history, momentum (all set to 0)

Dependencies:
    Phase 3: nba_analytics.upcoming_player_game_context (CRITICAL)
    Phase 3: nba_analytics.upcoming_team_game_context (CRITICAL)
    Phase 4: nba_precompute.player_shot_zone_analysis (must run first)
    Phase 4: nba_precompute.team_defense_zone_analysis (must run first)

Output:
    BigQuery table: nba_precompute.player_composite_factors
    Strategy: MERGE (update existing or insert new)

Schedule:
    Nightly at 11:30 PM (after zone analysis completes)
    Duration: 10-15 minutes (all 450 players with upcoming games)

Version: 1.0 (v4.0 dependency tracking)
Date: October 30, 2025
"""

import json
import logging
import os
from datetime import datetime, date
from typing import Dict, List, Optional
from google.cloud import bigquery
import pandas as pd

from data_processors.precompute.precompute_base import PrecomputeProcessorBase

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PlayerCompositeFactorsProcessor(PrecomputeProcessorBase):
    """
    Calculate composite adjustment factors for player predictions.
    
    Combines fatigue, matchup, pace, and usage context into quantified
    adjustment scores that Phase 5 systems use to modify predictions.
    
    Week 1-4 Implementation:
        - 4 active factors fully calculated
        - 4 deferred factors set to 0 (neutral)
        - XGBoost feature importance analysis after 3 months
    """
    
    def __init__(self):
        super().__init__()
        
        # Table configuration
        self.table_name = 'player_composite_factors'
        self.entity_type = 'player'
        self.entity_field = 'player_lookup'
        
        # Version tracking
        self.calculation_version = "v1_4factors"
        self.factors_active = "fatigue,shot_zone,pace,usage_spike"
        self.factors_deferred = "referee,look_ahead,matchup_history,momentum"
        
        # BigQuery setup
        self.bq_client = bigquery.Client()
        self.project_id = os.environ.get('GCP_PROJECT_ID', self.bq_client.project)
        
        # League baseline (for calculations)
        self.league_avg_pace = 100.0
        
        logger.info(f"Initialized {self.__class__.__name__} - Version: {self.calculation_version}")
    
    def get_dependencies(self) -> dict:
        """
        Define upstream source requirements with v4.0 tracking.
        
        Returns:
            Dict mapping table names to dependency configurations
        """
        return {
            'nba_analytics.upcoming_player_game_context': {
                'field_prefix': 'source_player_context',
                'description': 'Player fatigue, usage, and pace context for upcoming games',
                'check_type': 'date_match',
                'expected_count_min': 50,  # At least 50 players with upcoming games
                'max_age_hours_warn': 12,
                'max_age_hours_fail': 48,
                'critical': True
            },
            'nba_analytics.upcoming_team_game_context': {
                'field_prefix': 'source_team_context',
                'description': 'Team context and betting lines for upcoming games',
                'check_type': 'date_match',
                'expected_count_min': 10,  # At least 10 games (20 teams)
                'max_age_hours_warn': 12,
                'max_age_hours_fail': 48,
                'critical': True
            },
            'nba_precompute.player_shot_zone_analysis': {
                'field_prefix': 'source_player_shot',
                'description': 'Player shot zone preferences and efficiency',
                'check_type': 'date_match',
                'expected_count_min': 100,  # Most active players
                'max_age_hours_warn': 6,
                'max_age_hours_fail': 24,
                'critical': True
            },
            'nba_precompute.team_defense_zone_analysis': {
                'field_prefix': 'source_team_defense',
                'description': 'Team defensive performance by zone',
                'check_type': 'date_match',
                'expected_count_min': 30,  # All 30 teams
                'max_age_hours_warn': 6,
                'max_age_hours_fail': 24,
                'critical': True
            }
        }
    
    def extract_raw_data(self) -> None:
        """
        Extract data from all upstream sources with dependency checking.
        
        Queries:
            1. Player game context (fatigue, usage, pace)
            2. Team game context (betting lines)
            3. Player shot zone analysis (shooting preferences)
            4. Team defense zone analysis (defensive ratings)
        """
        analysis_date = self.opts.get('analysis_date')
        if not analysis_date:
            raise ValueError("analysis_date required in opts")
        
        logger.info(f"Extracting data for analysis_date: {analysis_date}")
        
        # Check dependencies
        dep_check = self.check_dependencies(analysis_date)
        
        # Track source usage (populates source_* attributes)
        self.track_source_usage(dep_check)
        
        # Handle dependency failures
        if not dep_check['all_critical_present']:
            missing = dep_check.get('missing', [])
            raise Exception(f"Missing critical dependencies: {missing}")
        
        if dep_check.get('has_stale_fail'):
            stale = dep_check.get('stale_fail', [])
            raise Exception(f"Stale data (fail threshold): {stale}")
        
        # Check for early season in zone analysis tables
        if self._check_upstream_early_season(analysis_date):
            logger.warning("Upstream zone analysis has early_season_flag, writing placeholders")
            self._write_placeholder_rows_from_player_context(analysis_date)
            return
        
        # Extract from all sources
        logger.info("Extracting player game context...")
        self.player_context_df = self._extract_player_context(analysis_date)
        
        logger.info("Extracting team game context...")
        self.team_context_df = self._extract_team_context(analysis_date)
        
        logger.info("Extracting player shot zone analysis...")
        self.player_shot_df = self._extract_player_shot_zones(analysis_date)
        
        logger.info("Extracting team defense zone analysis...")
        self.team_defense_df = self._extract_team_defense_zones(analysis_date)
        
        logger.info(f"Extracted data - Players: {len(self.player_context_df)}, "
                   f"Shot zones: {len(self.player_shot_df)}, "
                   f"Defense zones: {len(self.team_defense_df)}")
    
    def _check_upstream_early_season(self, analysis_date: date) -> bool:
        """Check if upstream zone analysis tables have early_season_flag."""
        query = f"""
        SELECT 
            COUNT(*) as total_players,
            COUNT(CASE WHEN early_season_flag = TRUE THEN 1 END) as early_season_players
        FROM `{self.project_id}.nba_precompute.player_shot_zone_analysis`
        WHERE analysis_date = '{analysis_date}'
        """
        
        try:
            df = self.bq_client.query(query).to_dataframe()
            if len(df) > 0:
                early_pct = (df['early_season_players'].iloc[0] / df['total_players'].iloc[0]) * 100
                if early_pct > 50:  # More than 50% have early season flag
                    logger.warning(f"Early season detected: {early_pct:.1f}% of players flagged")
                    return True
        except Exception as e:
            logger.warning(f"Error checking early season status: {e}")
        
        return False
    
    def _write_placeholder_rows_from_player_context(self, analysis_date: date) -> None:
        """Write placeholder rows when zone analysis is in early season."""
        query = f"""
        SELECT 
            player_lookup,
            universal_player_id,
            game_id,
            game_date
        FROM `{self.project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date = '{analysis_date}'
        """
        
        df = self.bq_client.query(query).to_dataframe()
        
        placeholders = []
        for _, row in df.iterrows():
            placeholder = {
                'player_lookup': row['player_lookup'],
                'universal_player_id': row['universal_player_id'],
                'game_date': row['game_date'].isoformat(),
                'game_id': row['game_id'],
                
                # All scores NULL
                'fatigue_score': None,
                'shot_zone_mismatch_score': None,
                'pace_score': None,
                'usage_spike_score': None,
                
                # Deferred scores (0)
                'referee_favorability_score': 0.0,
                'look_ahead_pressure_score': 0.0,
                'matchup_history_score': 0,
                'momentum_score': 0,
                
                # All adjustments NULL
                'fatigue_adjustment': None,
                'shot_zone_adjustment': None,
                'pace_adjustment': None,
                'usage_spike_adjustment': None,
                'referee_adjustment': 0.0,
                'look_ahead_adjustment': 0.0,
                'matchup_history_adjustment': 0.0,
                'momentum_adjustment': 0.0,
                'total_composite_adjustment': None,
                
                # Version tracking
                'calculation_version': self.calculation_version,
                'factors_active': self.factors_active,
                'factors_deferred': self.factors_deferred,
                
                # Context (empty)
                'fatigue_context': None,
                'shot_zone_context': None,
                'pace_context': None,
                'usage_context': None,
                
                # Quality
                'data_completeness_pct': 0.0,
                'missing_data_fields': 'player_shot_zone_analysis,team_defense_zone_analysis',
                'has_warnings': True,
                'warning_details': 'EARLY_SEASON',
                
                # Source tracking
                **self.build_source_tracking_fields(),
                
                # Early season flag
                'early_season_flag': True,
                'insufficient_data_reason': 'Zone analysis tables have early_season_flag=true',
                
                # Timestamps
                'created_at': datetime.utcnow().isoformat(),
                'updated_at': None,
                'processed_at': datetime.utcnow().isoformat()
            }
            placeholders.append(placeholder)
        
        self.transformed_data = placeholders
        logger.info(f"Created {len(placeholders)} placeholder rows for early season")
    
    def _extract_player_context(self, analysis_date: date) -> pd.DataFrame:
        """Extract player game context data."""
        query = f"""
        SELECT 
            player_lookup,
            universal_player_id,
            game_id,
            game_date,
            opponent_team_abbr,
            
            -- Fatigue fields
            days_rest,
            back_to_back,
            games_in_last_7_days,
            minutes_in_last_7_days,
            avg_minutes_per_game_last_7,
            back_to_backs_last_14_days,
            player_age,
            
            -- Usage fields
            projected_usage_rate,
            avg_usage_rate_last_7_games,
            star_teammates_out,
            
            -- Pace fields
            pace_differential,
            opponent_pace_last_10
            
        FROM `{self.project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date = '{analysis_date}'
        """
        
        return self.bq_client.query(query).to_dataframe()
    
    def _extract_team_context(self, analysis_date: date) -> pd.DataFrame:
        """Extract team game context data."""
        query = f"""
        SELECT 
            team_abbr,
            game_id,
            game_date,
            game_total,
            game_spread
            
        FROM `{self.project_id}.nba_analytics.upcoming_team_game_context`
        WHERE game_date = '{analysis_date}'
        """
        
        return self.bq_client.query(query).to_dataframe()
    
    def _extract_player_shot_zones(self, analysis_date: date) -> pd.DataFrame:
        """Extract player shot zone analysis."""
        query = f"""
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
            AND (early_season_flag IS NULL OR early_season_flag = FALSE)
        """
        
        return self.bq_client.query(query).to_dataframe()
    
    def _extract_team_defense_zones(self, analysis_date: date) -> pd.DataFrame:
        """Extract team defense zone analysis."""
        query = f"""
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
            AND (early_season_flag IS NULL OR early_season_flag = FALSE)
        """
        
        return self.bq_client.query(query).to_dataframe()
    
    def calculate_precompute(self) -> None:
        """
        Calculate composite factors for all players.
        
        For each player with an upcoming game:
            1. Calculate fatigue_score (0-100)
            2. Calculate shot_zone_mismatch_score (-10.0 to +10.0)
            3. Calculate pace_score (-3.0 to +3.0)
            4. Calculate usage_spike_score (-3.0 to +3.0)
            5. Set deferred scores to 0
            6. Convert scores to point adjustments
            7. Calculate total_composite_adjustment
        """
        successful = []
        failed = []
        
        # Process each player
        for _, player_row in self.player_context_df.iterrows():
            try:
                player_lookup = player_row['player_lookup']
                
                # Get related data
                opponent_team = player_row['opponent_team_abbr']
                team_context = self._get_team_context(player_row['game_id'])
                player_shot = self._get_player_shot_zone(player_lookup)
                team_defense = self._get_team_defense_zone(opponent_team)
                
                # Calculate active factors
                fatigue_score = self._calculate_fatigue_score(player_row)
                shot_zone_score = self._calculate_shot_zone_mismatch(player_shot, team_defense)
                pace_score = self._calculate_pace_score(player_row)
                usage_score = self._calculate_usage_spike_score(player_row)
                
                # Convert to adjustments
                fatigue_adj = self._fatigue_score_to_adjustment(fatigue_score)
                shot_zone_adj = shot_zone_score  # Direct conversion
                pace_adj = pace_score  # Direct conversion
                usage_adj = usage_score  # Direct conversion
                
                # Deferred adjustments (all 0)
                referee_adj = 0.0
                look_ahead_adj = 0.0
                matchup_history_adj = 0.0
                momentum_adj = 0.0
                
                # Total adjustment
                total_adj = (fatigue_adj + shot_zone_adj + pace_adj + usage_adj +
                           referee_adj + look_ahead_adj + matchup_history_adj + momentum_adj)
                
                # Build context JSON
                fatigue_context = self._build_fatigue_context(player_row, fatigue_score)
                shot_zone_context = self._build_shot_zone_context(player_shot, team_defense, shot_zone_score)
                pace_context = self._build_pace_context(player_row, pace_score)
                usage_context = self._build_usage_context(player_row, usage_score)
                
                # Check data completeness
                completeness, missing_fields = self._calculate_completeness(
                    player_row, player_shot, team_defense
                )
                
                # Check for warnings
                has_warnings, warning_details = self._check_warnings(
                    fatigue_score, shot_zone_score, total_adj
                )
                
                # Build output record
                record = {
                    # Identifiers
                    'player_lookup': player_lookup,
                    'universal_player_id': player_row['universal_player_id'],
                    'game_date': player_row['game_date'].isoformat(),
                    'game_id': player_row['game_id'],
                    
                    # Active scores
                    'fatigue_score': int(fatigue_score),
                    'shot_zone_mismatch_score': float(shot_zone_score),
                    'pace_score': float(pace_score),
                    'usage_spike_score': float(usage_score),
                    
                    # Deferred scores
                    'referee_favorability_score': 0.0,
                    'look_ahead_pressure_score': 0.0,
                    'matchup_history_score': 0,
                    'momentum_score': 0,
                    
                    # Adjustments
                    'fatigue_adjustment': float(fatigue_adj),
                    'shot_zone_adjustment': float(shot_zone_adj),
                    'pace_adjustment': float(pace_adj),
                    'usage_spike_adjustment': float(usage_adj),
                    'referee_adjustment': 0.0,
                    'look_ahead_adjustment': 0.0,
                    'matchup_history_adjustment': 0.0,
                    'momentum_adjustment': 0.0,
                    'total_composite_adjustment': float(total_adj),
                    
                    # Version tracking
                    'calculation_version': self.calculation_version,
                    'factors_active': self.factors_active,
                    'factors_deferred': self.factors_deferred,
                    
                    # Context
                    'fatigue_context': json.dumps(fatigue_context),
                    'shot_zone_context': json.dumps(shot_zone_context),
                    'pace_context': json.dumps(pace_context),
                    'usage_context': json.dumps(usage_context),
                    
                    # Quality
                    'data_completeness_pct': float(completeness),
                    'missing_data_fields': missing_fields if missing_fields else None,
                    'has_warnings': has_warnings,
                    'warning_details': warning_details if warning_details else None,
                    
                    # Source tracking (v4.0)
                    **self.build_source_tracking_fields(),
                    
                    # Early season (not applicable for normal processing)
                    'early_season_flag': None,
                    'insufficient_data_reason': None,
                    
                    # Timestamps
                    'created_at': datetime.utcnow().isoformat(),
                    'updated_at': None,
                    'processed_at': datetime.utcnow().isoformat()
                }
                
                successful.append(record)
                
            except Exception as e:
                logger.error(f"Failed to process {player_lookup}: {e}")
                failed.append({
                    'entity_id': player_lookup,
                    'reason': str(e),
                    'category': 'PROCESSING_ERROR',
                    'can_retry': False
                })
        
        self.transformed_data = successful
        self.failed_entities = failed
        
        logger.info(f"Calculated composite factors: {len(successful)} successful, {len(failed)} failed")
    
    def _get_team_context(self, game_id: str) -> Optional[pd.Series]:
        """Get team context for a game."""
        matches = self.team_context_df[self.team_context_df['game_id'] == game_id]
        return matches.iloc[0] if len(matches) > 0 else None
    
    def _get_player_shot_zone(self, player_lookup: str) -> Optional[pd.Series]:
        """Get player shot zone analysis."""
        matches = self.player_shot_df[self.player_shot_df['player_lookup'] == player_lookup]
        return matches.iloc[0] if len(matches) > 0 else None
    
    def _get_team_defense_zone(self, team_abbr: str) -> Optional[pd.Series]:
        """Get team defense zone analysis."""
        matches = self.team_defense_df[self.team_defense_df['team_abbr'] == team_abbr]
        return matches.iloc[0] if len(matches) > 0 else None
    
    # ============================================================================
    # FACTOR CALCULATION METHODS
    # ============================================================================
    
    def _calculate_fatigue_score(self, player_row: pd.Series) -> float:
        """
        Calculate fatigue score (0-100).
        
        100 = fresh/well-rested
        0 = exhausted
        
        Factors:
            - days_rest
            - back_to_back
            - games_in_last_7_days
            - minutes_in_last_7_days
            - avg_minutes_per_game_last_7
            - back_to_backs_last_14_days
            - player_age
        """
        score = 100  # Start fresh
        
        days_rest = player_row.get('days_rest', 1)
        back_to_back = player_row.get('back_to_back', False)
        games_last_7 = player_row.get('games_in_last_7_days', 0)
        minutes_last_7 = player_row.get('minutes_in_last_7_days', 0)
        avg_mpg = player_row.get('avg_minutes_per_game_last_7', 0)
        b2b_last_14 = player_row.get('back_to_backs_last_14_days', 0)
        age = player_row.get('player_age', 25)
        
        # Rest days penalty
        if days_rest == 0 or back_to_back:
            score -= 15
        elif days_rest == 1:
            score -= 5
        elif days_rest >= 3:
            score += 5
        
        # Recent games penalty
        if games_last_7 >= 4:
            score -= 10
        
        # Minutes load penalty
        if minutes_last_7 > 240:
            score -= 10
        elif minutes_last_7 > 200:
            score -= 5
        
        # Heavy minutes per game
        if avg_mpg > 35:
            score -= 8
        
        # Multiple back-to-backs
        if b2b_last_14 >= 2:
            score -= 12
        
        # Age penalty
        if age >= 35:
            score -= 5
        elif age >= 30:
            score -= 3
        
        # Clamp to 0-100
        return max(0, min(100, score))
    
    def _calculate_shot_zone_mismatch(
        self, 
        player_shot: Optional[pd.Series], 
        team_defense: Optional[pd.Series]
    ) -> float:
        """
        Calculate shot zone mismatch score (-10.0 to +10.0).
        
        Positive = favorable matchup (opponent weak in player's zone)
        Negative = unfavorable matchup (opponent strong in player's zone)
        
        Returns 0.0 if data missing.
        """
        if player_shot is None or team_defense is None:
            return 0.0
        
        primary_zone = player_shot.get('primary_scoring_zone')
        if not primary_zone:
            return 0.0
        
        # Get opponent defense rating in player's primary zone
        if primary_zone == 'paint':
            opp_defense = team_defense.get('paint_defense_vs_league_avg', 0.0)
            zone_frequency = player_shot.get('paint_rate_last_10', 0.0)
        elif primary_zone == 'mid_range':
            opp_defense = team_defense.get('mid_range_defense_vs_league_avg', 0.0)
            zone_frequency = player_shot.get('mid_range_rate_last_10', 0.0)
        elif primary_zone == 'perimeter' or primary_zone == '3pt':
            opp_defense = team_defense.get('three_pt_defense_vs_league_avg', 0.0)
            zone_frequency = player_shot.get('three_pt_rate_last_10', 0.0)
        else:
            return 0.0
        
        # Convert defense rating to mismatch score
        # Positive defense rating = weak defense = good for offense
        score = float(opp_defense)
        
        # Weight by how much player uses this zone
        zone_weight = min(zone_frequency / 50.0, 1.0)  # 50%+ usage = full weight
        score *= zone_weight
        
        # Extreme matchup bonus
        if abs(score) > 5.0:
            score *= 1.2
        
        # Clamp to -10.0 to +10.0
        return max(-10.0, min(10.0, score))
    
    def _calculate_pace_score(self, player_row: pd.Series) -> float:
        """
        Calculate pace score (-3.0 to +3.0).
        
        Positive = faster game (more possessions)
        Negative = slower game (fewer possessions)
        
        Based on pace_differential from player context.
        """
        pace_diff = player_row.get('pace_differential', 0.0)
        
        # Scale to ±3.0 range
        score = float(pace_diff) / 2.0
        
        # Clamp to -3.0 to +3.0
        return max(-3.0, min(3.0, score))
    
    def _calculate_usage_spike_score(self, player_row: pd.Series) -> float:
        """
        Calculate usage spike score (-3.0 to +3.0).
        
        Positive = usage increase (more opportunities)
        Negative = usage decrease
        
        Based on projected_usage_rate vs avg_usage_rate_last_7_games.
        """
        projected_usage = player_row.get('projected_usage_rate', 0.0)
        avg_usage = player_row.get('avg_usage_rate_last_7_games', 0.0)
        
        if avg_usage == 0:
            return 0.0
        
        # Calculate usage differential
        usage_diff = projected_usage - avg_usage
        
        # Scale to ±3.0 range (10% usage change = significant)
        score = float(usage_diff) * 0.3
        
        # Boost if stars are out (validates usage spike)
        stars_out = player_row.get('star_teammates_out', 0)
        if stars_out >= 2 and score > 0:
            score *= 1.3
        elif stars_out == 1 and score > 0:
            score *= 1.15
        
        # Clamp to -3.0 to +3.0
        return max(-3.0, min(3.0, score))
    
    def _fatigue_score_to_adjustment(self, fatigue_score: float) -> float:
        """
        Convert fatigue score (0-100) to point adjustment.
        
        Formula: (fatigue_score - 100) * 0.05
        Range: 0.0 (fresh) to -5.0 (exhausted)
        """
        return (fatigue_score - 100) * 0.05
    
    # ============================================================================
    # CONTEXT BUILDING METHODS
    # ============================================================================
    
    def _build_fatigue_context(self, player_row: pd.Series, fatigue_score: float) -> dict:
        """Build fatigue context JSON for debugging."""
        penalties = []
        bonuses = []
        
        days_rest = player_row.get('days_rest', 1)
        back_to_back = player_row.get('back_to_back', False)
        age = player_row.get('player_age', 25)
        
        if back_to_back or days_rest == 0:
            penalties.append("back_to_back")
        if days_rest >= 3:
            bonuses.append("well_rested")
        if player_row.get('games_in_last_7_days', 0) >= 4:
            penalties.append("high_game_density")
        if player_row.get('avg_minutes_per_game_last_7', 0) > 35:
            penalties.append("heavy_mpg")
        if age >= 30:
            penalties.append(f"age_{age}")
        
        return {
            'days_rest': int(days_rest),
            'back_to_back': bool(back_to_back),
            'games_last_7': int(player_row.get('games_in_last_7_days', 0)),
            'minutes_last_7': float(player_row.get('minutes_in_last_7_days', 0)),
            'avg_mpg_last_7': float(player_row.get('avg_minutes_per_game_last_7', 0)),
            'back_to_backs_last_14': int(player_row.get('back_to_backs_last_14_days', 0)),
            'player_age': int(age),
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
        """Build shot zone context JSON for debugging."""
        if player_shot is None or team_defense is None:
            return {'error': 'Missing data'}
        
        primary_zone = player_shot.get('primary_scoring_zone', 'unknown')
        weakest_zone = team_defense.get('weakest_zone', 'unknown')
        
        if primary_zone == 'paint':
            opp_defense = team_defense.get('paint_defense_vs_league_avg', 0.0)
            zone_freq = player_shot.get('paint_rate_last_10', 0.0)
        elif primary_zone == 'mid_range':
            opp_defense = team_defense.get('mid_range_defense_vs_league_avg', 0.0)
            zone_freq = player_shot.get('mid_range_rate_last_10', 0.0)
        else:
            opp_defense = team_defense.get('three_pt_defense_vs_league_avg', 0.0)
            zone_freq = player_shot.get('three_pt_rate_last_10', 0.0)
        
        return {
            'player_primary_zone': primary_zone,
            'primary_zone_frequency': float(zone_freq),
            'opponent_weak_zone': weakest_zone,
            'opponent_defense_vs_league': float(opp_defense),
            'zone_weight': min(zone_freq / 50.0, 1.0),
            'extreme_matchup': abs(score) > 6.0,
            'mismatch_type': 'favorable' if score > 0 else 'unfavorable' if score < 0 else 'neutral'
        }
    
    def _build_pace_context(self, player_row: pd.Series, pace_score: float) -> dict:
        """Build pace context JSON for debugging."""
        pace_diff = player_row.get('pace_differential', 0.0)
        opp_pace = player_row.get('opponent_pace_last_10', self.league_avg_pace)
        
        return {
            'pace_differential': float(pace_diff),
            'opponent_pace_last_10': float(opp_pace),
            'league_avg_pace': self.league_avg_pace,
            'pace_environment': 'fast' if pace_score > 1.0 else 'slow' if pace_score < -1.0 else 'normal',
            'score': float(pace_score)
        }
    
    def _build_usage_context(self, player_row: pd.Series, usage_score: float) -> dict:
        """Build usage context JSON for debugging."""
        projected = player_row.get('projected_usage_rate', 0.0)
        recent = player_row.get('avg_usage_rate_last_7_games', 0.0)
        stars_out = player_row.get('star_teammates_out', 0)
        
        return {
            'projected_usage_rate': float(projected),
            'avg_usage_last_7': float(recent),
            'usage_differential': float(projected - recent),
            'star_teammates_out': int(stars_out),
            'usage_boost_applied': stars_out > 0 and usage_score > 0,
            'boost_multiplier': 1.3 if stars_out >= 2 else 1.15 if stars_out == 1 else 1.0,
            'usage_trend': 'spike' if usage_score > 1.0 else 'drop' if usage_score < -1.0 else 'stable'
        }
    
    def _calculate_completeness(
        self, 
        player_row: pd.Series,
        player_shot: Optional[pd.Series],
        team_defense: Optional[pd.Series]
    ) -> tuple[float, str]:
        """
        Calculate data completeness percentage.
        
        Returns:
            (completeness_pct, missing_fields_str)
        """
        required_fields = {
            'days_rest': player_row.get('days_rest') is not None,
            'minutes_in_last_7_days': player_row.get('minutes_in_last_7_days') is not None,
            'projected_usage_rate': player_row.get('projected_usage_rate') is not None,
            'pace_differential': player_row.get('pace_differential') is not None,
            'player_shot_zone': player_shot is not None,
            'team_defense_zone': team_defense is not None
        }
        
        present = sum(1 for v in required_fields.values() if v)
        total = len(required_fields)
        completeness_pct = (present / total) * 100
        
        missing = [k for k, v in required_fields.items() if not v]
        missing_fields_str = ','.join(missing) if missing else None
        
        return completeness_pct, missing_fields_str
    
    def _check_warnings(
        self, 
        fatigue_score: float, 
        shot_zone_score: float, 
        total_adj: float
    ) -> tuple[bool, str]:
        """
        Check for warning conditions.
        
        Returns:
            (has_warnings, warning_details)
        """
        warnings = []
        
        # Extreme fatigue
        if fatigue_score < 50:
            warnings.append("EXTREME_FATIGUE")
        
        # Extreme matchup
        if abs(shot_zone_score) > 8.0:
            warnings.append("EXTREME_MATCHUP")
        
        # Extreme total adjustment
        if abs(total_adj) > 12.0:
            warnings.append("EXTREME_ADJUSTMENT")
        
        has_warnings = len(warnings) > 0
        warning_details = ','.join(warnings) if warnings else None
        
        return has_warnings, warning_details


if __name__ == '__main__':
    """
    Test the processor locally.
    
    Usage:
        python player_composite_factors_processor.py
    """
    import sys
    from datetime import date
    
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create processor
    processor = PlayerCompositeFactorsProcessor()
    
    # Test date (use tomorrow for upcoming games)
    test_date = date.today()
    
    logger.info(f"Testing processor for date: {test_date}")
    
    try:
        # Run processor
        result = processor.run({'analysis_date': test_date})
        
        logger.info(f"Processing complete!")
        logger.info(f"Status: {result.get('status')}")
        logger.info(f"Players processed: {len(result.get('transformed_data', []))}")
        logger.info(f"Failures: {len(result.get('failed_entities', []))}")
        
        # Show sample
        if result.get('transformed_data'):
            sample = result['transformed_data'][0]
            logger.info(f"\nSample record:")
            logger.info(f"  Player: {sample['player_lookup']}")
            logger.info(f"  Fatigue: {sample['fatigue_score']}")
            logger.info(f"  Shot Zone: {sample['shot_zone_mismatch_score']}")
            logger.info(f"  Pace: {sample['pace_score']}")
            logger.info(f"  Usage: {sample['usage_spike_score']}")
            logger.info(f"  Total Adjustment: {sample['total_composite_adjustment']}")
        
        sys.exit(0 if result.get('status') == 'success' else 1)
        
    except Exception as e:
        logger.error(f"Error running processor: {e}", exc_info=True)
        sys.exit(1)
