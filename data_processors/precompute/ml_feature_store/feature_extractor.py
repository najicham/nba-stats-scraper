# File: data_processors/precompute/ml_feature_store/feature_extractor.py
"""
Feature Extractor - Query Phase 3/4 Tables

Extracts raw data from:
- Phase 4 (preferred): player_daily_cache, player_composite_factors, 
                       player_shot_zone_analysis, team_defense_zone_analysis
- Phase 3 (fallback): player_game_summary, upcoming_player_game_context,
                      team_offense_game_summary, team_defense_game_summary

Version: 1.1 (Fixed field name consistency: games_in_last_7_days)
"""

import logging
from datetime import date
from typing import Dict, List, Optional
from google.cloud import bigquery

logger = logging.getLogger(__name__)


class FeatureExtractor:
    """Extract features from Phase 3/4 BigQuery tables."""
    
    def __init__(self, bq_client: bigquery.Client, project_id: str):
        """
        Initialize feature extractor.
        
        Args:
            bq_client: BigQuery client instance
            project_id: GCP project ID
        """
        self.bq_client = bq_client
        self.project_id = project_id
    
    # ========================================================================
    # PLAYER LIST
    # ========================================================================
    
    def get_players_with_games(self, game_date: date) -> List[Dict]:
        """
        Get list of all players with games on game_date.
        
        Args:
            game_date: Date to query
            
        Returns:
            List of dicts with player_lookup, game_id, opponent, etc.
        """
        query = f"""
        SELECT
            player_lookup,
            universal_player_id,
            game_id,
            game_date,
            opponent_team_abbr,
            home_game AS is_home,
            days_rest
        FROM `{self.project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date = '{game_date}'
        ORDER BY player_lookup
        """
        
        result = self.bq_client.query(query).to_dataframe()
        
        if result.empty:
            logger.warning(f"No players found with games on {game_date}")
            return []
        
        return result.to_dict('records')
    
    # ========================================================================
    # PHASE 4 EXTRACTION (PREFERRED)
    # ========================================================================
    
    def extract_phase4_data(self, player_lookup: str, game_date: date) -> Dict:
        """
        Extract all Phase 4 data for a player.
        
        Queries 4 Phase 4 tables:
        - player_daily_cache (features 0-4, 18-20, 22-23)
        - player_composite_factors (features 5-8)
        - player_shot_zone_analysis (features 18-20)
        - team_defense_zone_analysis (features 13-14)
        
        Args:
            player_lookup: Player identifier
            game_date: Game date
            
        Returns:
            Dict with all Phase 4 fields (may have None values)
        """
        phase4_data = {}
        
        # 1. Player daily cache
        cache_data = self._query_player_daily_cache(player_lookup, game_date)
        phase4_data.update(cache_data)
        
        # 2. Composite factors
        composite_data = self._query_composite_factors(player_lookup, game_date)
        phase4_data.update(composite_data)
        
        # 3. Shot zone analysis
        shot_zone_data = self._query_shot_zone_analysis(player_lookup, game_date)
        phase4_data.update(shot_zone_data)
        
        # 4. Team defense (requires opponent)
        opponent = phase4_data.get('opponent_team_abbr')
        if opponent:
            team_defense_data = self._query_team_defense(opponent, game_date)
            phase4_data.update(team_defense_data)
        
        return phase4_data
    
    def _query_player_daily_cache(self, player_lookup: str, game_date: date) -> Dict:
        """Query player_daily_cache table."""
        query = f"""
        SELECT
            -- Features 0-4: Recent Performance
            points_avg_last_5,
            points_avg_last_10,
            points_avg_season,
            points_std_last_10,
            games_in_last_7_days,  -- FIXED: Consistent with processor
            
            -- Features 18-20: Shot Zones (partial)
            paint_rate_last_10,
            three_pt_rate_last_10,
            assisted_rate_last_10,
            
            -- Features 22-23: Team Context
            team_pace_last_10,
            team_off_rating_last_10,
            
            -- Additional context
            minutes_avg_last_10,
            player_age
        FROM `{self.project_id}.nba_precompute.player_daily_cache`
        WHERE player_lookup = '{player_lookup}'
          AND cache_date = '{game_date}'
        """
        
        result = self.bq_client.query(query).to_dataframe()
        
        if result.empty:
            logger.debug(f"No player_daily_cache data for {player_lookup} on {game_date}")
            return {}
        
        return result.iloc[0].to_dict()
    
    def _query_composite_factors(self, player_lookup: str, game_date: date) -> Dict:
        """Query player_composite_factors table."""
        query = f"""
        SELECT
            -- Features 5-8: Composite Factors
            fatigue_score,
            shot_zone_mismatch_score,
            pace_score,
            usage_spike_score,
            
            -- Context
            opponent_team_abbr
        FROM `{self.project_id}.nba_precompute.player_composite_factors`
        WHERE player_lookup = '{player_lookup}'
          AND game_date = '{game_date}'
        """
        
        result = self.bq_client.query(query).to_dataframe()
        
        if result.empty:
            logger.debug(f"No composite_factors data for {player_lookup} on {game_date}")
            return {}
        
        return result.iloc[0].to_dict()
    
    def _query_shot_zone_analysis(self, player_lookup: str, game_date: date) -> Dict:
        """Query player_shot_zone_analysis table."""
        query = f"""
        SELECT
            -- Features 18-20: Shot Zones
            paint_rate_last_10,
            mid_range_rate_last_10,
            three_pt_rate_last_10
        FROM `{self.project_id}.nba_precompute.player_shot_zone_analysis`
        WHERE player_lookup = '{player_lookup}'
          AND analysis_date = '{game_date}'
        """
        
        result = self.bq_client.query(query).to_dataframe()
        
        if result.empty:
            logger.debug(f"No shot_zone_analysis data for {player_lookup} on {game_date}")
            return {}
        
        return result.iloc[0].to_dict()
    
    def _query_team_defense(self, team_abbr: str, game_date: date) -> Dict:
        """Query team_defense_zone_analysis table."""
        query = f"""
        SELECT
            -- Features 13-14: Opponent Defense
            defensive_rating_last_15 AS opponent_def_rating,
            opponent_pace
        FROM `{self.project_id}.nba_precompute.team_defense_zone_analysis`
        WHERE team_abbr = '{team_abbr}'
          AND analysis_date = '{game_date}'
        """
        
        result = self.bq_client.query(query).to_dataframe()
        
        if result.empty:
            logger.debug(f"No team_defense data for {team_abbr} on {game_date}")
            return {}
        
        return result.iloc[0].to_dict()
    
    # ========================================================================
    # PHASE 3 EXTRACTION (FALLBACK)
    # ========================================================================
    
    def extract_phase3_data(self, player_lookup: str, game_date: date) -> Dict:
        """
        Extract Phase 3 data for a player.
        
        Used as fallback when Phase 4 incomplete, and for calculated features.
        
        Args:
            player_lookup: Player identifier
            game_date: Game date
            
        Returns:
            Dict with Phase 3 fields
        """
        phase3_data = {}
        
        # 1. Upcoming player context (critical for calculated features)
        context_data = self._query_player_context(player_lookup, game_date)
        phase3_data.update(context_data)
        
        # 2. Last 10 games (for aggregations and trend)
        last_10_games = self._query_last_n_games(player_lookup, game_date, 10)
        phase3_data['last_10_games'] = last_10_games
        
        # Calculate aggregations from games
        if last_10_games:
            phase3_data['points_avg_last_10'] = sum(g['points'] for g in last_10_games) / len(last_10_games)
            
            if len(last_10_games) >= 5:
                last_5 = last_10_games[:5]
                phase3_data['points_avg_last_5'] = sum(g['points'] for g in last_5) / 5
        
        # 3. Season stats
        season_stats = self._query_season_stats(player_lookup, game_date)
        phase3_data.update(season_stats)
        
        # 4. Team season games (for win_pct calculation)
        team_abbr = context_data.get('team_abbr')
        if team_abbr:
            season_year = game_date.year if game_date.month >= 10 else game_date.year - 1
            team_games = self._query_team_season_games(team_abbr, season_year, game_date)
            phase3_data['team_season_games'] = team_games
        
        return phase3_data
    
    def _query_player_context(self, player_lookup: str, game_date: date) -> Dict:
        """Query upcoming_player_game_context."""
        query = f"""
        SELECT
            player_lookup,
            game_date,
            game_id,
            team_abbr,
            opponent_team_abbr,
            
            -- Features 15-17: Game Context
            home_game,
            back_to_back,
            season_phase,
            
            -- For calculated features
            days_rest,
            player_status,
            opponent_days_rest
        FROM `{self.project_id}.nba_analytics.upcoming_player_game_context`
        WHERE player_lookup = '{player_lookup}'
          AND game_date = '{game_date}'
        """
        
        result = self.bq_client.query(query).to_dataframe()
        
        if result.empty:
            logger.warning(f"No upcoming_player_game_context for {player_lookup} on {game_date}")
            return {}
        
        return result.iloc[0].to_dict()
    
    def _query_last_n_games(self, player_lookup: str, game_date: date, n: int) -> List[Dict]:
        """Query last N games for a player."""
        query = f"""
        SELECT
            game_date,
            points,
            minutes_played,
            ft_makes,
            fg_attempts,
            paint_attempts,
            mid_range_attempts,
            three_pt_attempts
        FROM `{self.project_id}.nba_analytics.player_game_summary`
        WHERE player_lookup = '{player_lookup}'
          AND game_date < '{game_date}'
        ORDER BY game_date DESC
        LIMIT {n}
        """
        
        result = self.bq_client.query(query).to_dataframe()
        
        if result.empty:
            logger.debug(f"No historical games for {player_lookup} before {game_date}")
            return []
        
        return result.to_dict('records')
    
    def _query_season_stats(self, player_lookup: str, game_date: date) -> Dict:
        """Query season-level stats."""
        season_year = game_date.year if game_date.month >= 10 else game_date.year - 1
        
        query = f"""
        SELECT
            AVG(points) AS points_avg_season,
            AVG(minutes_played) AS minutes_avg_season,
            COUNT(*) AS games_played_season
        FROM `{self.project_id}.nba_analytics.player_game_summary`
        WHERE player_lookup = '{player_lookup}'
          AND season_year = {season_year}
          AND game_date < '{game_date}'
        """
        
        result = self.bq_client.query(query).to_dataframe()
        
        if result.empty:
            return {}
        
        return result.iloc[0].to_dict()
    
    def _query_team_season_games(self, team_abbr: str, season_year: int, game_date: date) -> List[Dict]:
        """Query team's season games for win percentage."""
        query = f"""
        SELECT
            game_date,
            win_flag
        FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
        WHERE team_abbr = '{team_abbr}'
          AND season_year = {season_year}
          AND game_date < '{game_date}'
        ORDER BY game_date
        """
        
        result = self.bq_client.query(query).to_dataframe()
        
        if result.empty:
            return []
        
        return result.to_dict('records')