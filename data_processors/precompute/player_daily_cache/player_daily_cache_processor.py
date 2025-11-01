#!/usr/bin/env python3
"""
Path: data_processors/precompute/player_daily_cache/player_daily_cache_processor.py

Player Daily Cache Processor

Purpose:
    Cache static daily player data that won't change during the day.
    Eliminates repeated BigQuery queries during Phase 5 real-time updates.
    
Input Sources:
    - nba_analytics.player_game_summary (recent performance)
    - nba_analytics.team_offense_game_summary (team context)
    - nba_analytics.upcoming_player_game_context (fatigue metrics)
    - nba_precompute.player_shot_zone_analysis (shot tendencies)
    
Output:
    - nba_precompute.player_daily_cache
    
Schedule:
    - Nightly at 12:00 AM (after all Phase 4 processors complete)
    - Processes ~450 active players in 5-10 minutes
    
Performance Impact:
    - Cost savings: 79% reduction vs repeated queries
    - Speed: 2000x faster lookups (cache vs BigQuery)
    - Phase 5 loads cache once at 6 AM and reuses all day

Version: 1.0
Date: October 30, 2025
"""

import logging
import os
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional
import pandas as pd
import numpy as np
from google.cloud import bigquery

from data_processors.precompute.precompute_base import PrecomputeProcessorBase

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PlayerDailyCacheProcessor(PrecomputeProcessorBase):
    """
    Cache static daily player data for fast Phase 5 real-time updates.
    
    This processor aggregates player performance, team context, fatigue metrics,
    and shot zone tendencies into a single cache table. Phase 5 loads this cache
    once at 6 AM and reuses it for all real-time predictions during the day.
    
    Dependencies:
        - nba_analytics.player_game_summary (CRITICAL)
        - nba_analytics.team_offense_game_summary (CRITICAL)
        - nba_analytics.upcoming_player_game_context (CRITICAL)
        - nba_precompute.player_shot_zone_analysis (CRITICAL)
    
    Processing Strategy:
        - MERGE: Update existing rows or insert new ones
        - One row per player per cache_date
        - Handles early season (< 10 games) with partial data
        - Minimum 5 games required to write cache record
    """
    
    def __init__(self):
        """Initialize the player daily cache processor."""
        super().__init__()
        
        # Table configuration
        self.table_name = 'player_daily_cache'
        self.entity_type = 'player'
        self.entity_field = 'player_lookup'
        
        # Data requirements
        self.min_games_required = 10  # Preferred minimum
        self.absolute_min_games = 5   # Absolute minimum to write record
        
        # BigQuery client (CRITICAL)
        self.bq_client = bigquery.Client()
        self.project_id = os.environ.get('GCP_PROJECT_ID', self.bq_client.project)
        
        # Data containers
        self.player_game_data = None
        self.team_offense_data = None
        self.upcoming_context_data = None
        self.shot_zone_data = None
        
        # Cache version
        self.cache_version = "v1"
        
        logger.info("PlayerDailyCacheProcessor initialized")
    
    def get_dependencies(self) -> dict:
        """
        Define upstream source requirements.
        
        Returns:
            dict: Dependency configuration for each source table
        """
        return {
            'nba_analytics.player_game_summary': {
                'field_prefix': 'source_player_game',
                'description': 'Player performance stats (season to date)',
                'check_type': 'lookback_days',
                'lookback_days': 180,  # Full season
                'expected_count_min': 1000,  # ~450 players × 5+ games
                'max_age_hours_warn': 24,
                'max_age_hours_fail': 72,
                'early_season_days': 14,
                'early_season_behavior': 'WRITE_PLACEHOLDER',
                'critical': True
            },
            'nba_analytics.team_offense_game_summary': {
                'field_prefix': 'source_team_offense',
                'description': 'Team offensive stats (last 10 games)',
                'check_type': 'lookback_days',
                'lookback_days': 30,
                'expected_count_min': 300,  # ~30 teams × 10 games
                'max_age_hours_warn': 24,
                'max_age_hours_fail': 72,
                'critical': True
            },
            'nba_analytics.upcoming_player_game_context': {
                'field_prefix': 'source_upcoming_context',
                'description': 'Pre-calculated fatigue metrics and context',
                'check_type': 'date_match',
                'expected_count_min': 100,  # Players with games today
                'max_age_hours_warn': 12,
                'max_age_hours_fail': 48,
                'critical': True
            },
            'nba_precompute.player_shot_zone_analysis': {
                'field_prefix': 'source_shot_zone',
                'description': 'Shot zone tendencies (must complete first)',
                'check_type': 'date_match',
                'expected_count_min': 100,  # Players with games today
                'max_age_hours_warn': 6,
                'max_age_hours_fail': 24,
                'critical': True
            }
        }

    def build_source_tracking_fields(self) -> Dict:
        """
        Build source tracking fields from tracked source attributes.
        
        This method collects all source tracking data (timestamps, row counts,
        completeness percentages) from processor attributes and returns them
        as a dictionary ready to be included in output records.
        
        Returns:
            Dict: Source tracking fields for all dependencies
            
        Example output:
            {
                'source_player_game_last_updated': datetime(2025, 1, 21, 2, 15),
                'source_player_game_rows_found': 450,
                'source_player_game_completeness_pct': 98.5,
                'source_team_offense_last_updated': datetime(2025, 1, 21, 2, 20),
                ...
            }
        """
        tracking_fields = {}
        
        # Get dependencies to know which sources to track
        deps = self.get_dependencies()
        
        for source_table, config in deps.items():
            prefix = config['field_prefix']
            
            # Build field names based on prefix
            last_updated_field = f"{prefix}_last_updated"
            rows_found_field = f"{prefix}_rows_found"
            completeness_field = f"{prefix}_completeness_pct"
            
            # Get values from processor attributes (set by track_source_usage during extract)
            tracking_fields[last_updated_field] = getattr(self, last_updated_field, None)
            tracking_fields[rows_found_field] = getattr(self, rows_found_field, None)
            tracking_fields[completeness_field] = getattr(self, completeness_field, None)
        
        return tracking_fields
    
    def extract_raw_data(self) -> None:
        """
        Extract data from all upstream sources with dependency checking.
        
        Queries:
            1. player_game_summary: Season games for all active players
            2. team_offense_game_summary: Last 10 games per team
            3. upcoming_player_game_context: Today's context (fatigue, age)
            4. player_shot_zone_analysis: Today's shot zone analysis
        
        Raises:
            DependencyError: If critical dependencies missing
            DataTooStaleError: If critical data too old
        """
        analysis_date = self.opts['analysis_date']
        season_year = self.opts.get('season_year', analysis_date.year)
        
        logger.info(f"Extracting data for cache_date: {analysis_date}")
        
        # Check dependencies
        dep_check = self.check_dependencies(analysis_date)
        
        # Track source usage (populates source_* attributes)
        self.track_source_usage(dep_check)
        
        # Handle early season
        if dep_check.get('is_early_season'):
            logger.warning("Early season detected - will write partial cache records")
            self.early_season_flag = True
            self.insufficient_data_reason = "Season just started, using available games"
        
        # Handle failures
        if not dep_check['all_critical_present']:
            missing = ', '.join(dep_check['missing'])
            raise DependencyError(f"Missing critical dependencies: {missing}")
        
        if dep_check.get('has_stale_fail'):
            stale = ', '.join(dep_check['stale_fail'])
            raise DataTooStaleError(f"Stale dependencies: {stale}")
        
        # Extract from each source
        logger.info("Extracting player game summary data...")
        self._extract_player_game_data(analysis_date, season_year)
        
        logger.info("Extracting team offense data...")
        self._extract_team_offense_data(analysis_date)
        
        logger.info("Extracting upcoming player context data...")
        self._extract_upcoming_context_data(analysis_date)
        
        logger.info("Extracting shot zone analysis data...")
        self._extract_shot_zone_data(analysis_date)
        
        logger.info(f"Extraction complete: {len(self.upcoming_context_data)} players to process")
    
    def _extract_player_game_data(self, analysis_date: date, season_year: int) -> None:
        """Extract player game summary data (season to date)."""
        
        query = f"""
        WITH ranked_games AS (
            SELECT 
                player_lookup,
                universal_player_id,
                game_date,
                team_abbr,
                points,
                minutes_played,
                usage_rate,
                ts_pct,
                fg_makes,
                assisted_fg_makes,
                ROW_NUMBER() OVER (
                    PARTITION BY player_lookup 
                    ORDER BY game_date DESC
                ) as game_rank
            FROM `{self.project_id}.nba_analytics.player_game_summary`
            WHERE game_date <= '{analysis_date.isoformat()}'
              AND season_year = {season_year}
              AND is_active = TRUE
              AND minutes_played > 0
        )
        SELECT *
        FROM ranked_games
        WHERE game_rank <= 82  -- Full season
        ORDER BY player_lookup, game_date DESC
        """
        
        self.player_game_data = self.bq_client.query(query).to_dataframe()
        logger.info(f"Extracted {len(self.player_game_data)} player game records")
    
    def _extract_team_offense_data(self, analysis_date: date) -> None:
        """Extract team offense data (last 10 games per team)."""
        
        query = f"""
        WITH ranked_games AS (
            SELECT 
                team_abbr,
                game_date,
                pace,
                offensive_rating,
                ROW_NUMBER() OVER (
                    PARTITION BY team_abbr 
                    ORDER BY game_date DESC
                ) as game_rank
            FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
            WHERE game_date <= '{analysis_date.isoformat()}'
        )
        SELECT *
        FROM ranked_games
        WHERE game_rank <= 10
        ORDER BY team_abbr, game_date DESC
        """
        
        self.team_offense_data = self.bq_client.query(query).to_dataframe()
        logger.info(f"Extracted {len(self.team_offense_data)} team offense records")
    
    def _extract_upcoming_context_data(self, analysis_date: date) -> None:
        """Extract upcoming player game context (today's games)."""
        
        query = f"""
        SELECT 
            player_lookup,
            universal_player_id,
            team_abbr,
            game_date,
            games_in_last_7_days,
            games_in_last_14_days,
            minutes_in_last_7_days,
            minutes_in_last_14_days,
            back_to_backs_last_14_days,
            avg_minutes_per_game_last_7,
            fourth_quarter_minutes_last_7,
            player_age
        FROM `{self.project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date = '{analysis_date.isoformat()}'
        """
        
        self.upcoming_context_data = self.bq_client.query(query).to_dataframe()
        logger.info(f"Extracted {len(self.upcoming_context_data)} upcoming player contexts")
    
    def _extract_shot_zone_data(self, analysis_date: date) -> None:
        """Extract shot zone analysis (today's analysis)."""
        
        query = f"""
        SELECT 
            player_lookup,
            universal_player_id,
            analysis_date,
            primary_scoring_zone,
            paint_rate_last_10,
            three_pt_rate_last_10
        FROM `{self.project_id}.nba_precompute.player_shot_zone_analysis`
        WHERE analysis_date = '{analysis_date.isoformat()}'
        """
        
        self.shot_zone_data = self.bq_client.query(query).to_dataframe()
        logger.info(f"Extracted {len(self.shot_zone_data)} shot zone analyses")
    
    def calculate_precompute(self) -> None:
        """
        Calculate cache records for all players.
        
        Process:
            1. Iterate through all players in upcoming_context
            2. Calculate recent performance metrics (last 5, last 10, season)
            3. Calculate team context (pace, offensive rating)
            4. Copy fatigue metrics from upcoming_context
            5. Copy shot zone tendencies from shot_zone_analysis
            6. Calculate assisted rate from player_game_summary
            7. Build complete cache record with source tracking
        
        Output:
            - self.transformed_data: List of successful cache records
            - self.failed_entities: List of failed players with reasons
        """
        analysis_date = self.opts['analysis_date']
        
        successful = []
        failed = []

        if self.upcoming_context_data.empty:
            logger.info("No players scheduled today - skipping cache generation")
            self.transformed_data = successful
            self.failed_entities = failed
            return
        
        # Get all players scheduled to play today
        all_players = self.upcoming_context_data['player_lookup'].unique()
        logger.info(f"Processing cache for {len(all_players)} players")
        
        for player_lookup in all_players:
            try:
                # Get player's context data
                context_row = self.upcoming_context_data[
                    self.upcoming_context_data['player_lookup'] == player_lookup
                ].iloc[0]
                
                # Get player's game history
                player_games = self.player_game_data[
                    self.player_game_data['player_lookup'] == player_lookup
                ].copy()
                
                # Check minimum games requirement
                games_count = len(player_games)
                if games_count < self.absolute_min_games:
                    failed.append({
                        'entity_id': player_lookup,
                        'reason': f"Only {games_count} games played, need {self.absolute_min_games} minimum",
                        'category': 'INSUFFICIENT_DATA',
                        'can_retry': True
                    })
                    continue
                
                # Flag if below preferred minimum
                is_early_season = games_count < self.min_games_required
                
                # Get team context
                current_team = context_row['team_abbr']
                team_games = self.team_offense_data[
                    self.team_offense_data['team_abbr'] == current_team
                ].copy()
                
                # Get shot zone data
                shot_zone_row = self.shot_zone_data[
                    self.shot_zone_data['player_lookup'] == player_lookup
                ]
                
                # Check if shot zones available
                if shot_zone_row.empty:
                    failed.append({
                        'entity_id': player_lookup,
                        'reason': "No shot zone analysis available",
                        'category': 'MISSING_DEPENDENCY',
                        'can_retry': True
                    })
                    continue
                
                shot_zone_row = shot_zone_row.iloc[0]
                
                # Calculate all metrics
                cache_record = self._calculate_player_cache(
                    player_lookup=player_lookup,
                    context_row=context_row,
                    player_games=player_games,
                    team_games=team_games,
                    shot_zone_row=shot_zone_row,
                    analysis_date=analysis_date,
                    is_early_season=is_early_season
                )
                
                successful.append(cache_record)
                
            except Exception as e:
                logger.error(f"Failed to process {player_lookup}: {e}", exc_info=True)
                failed.append({
                    'entity_id': player_lookup,
                    'reason': str(e),
                    'category': 'PROCESSING_ERROR',
                    'can_retry': False
                })
        
        self.transformed_data = successful
        self.failed_entities = failed
        
        logger.info(f"Cache calculation complete: {len(successful)} successful, {len(failed)} failed")
    
    def _calculate_player_cache(
        self,
        player_lookup: str,
        context_row: pd.Series,
        player_games: pd.DataFrame,
        team_games: pd.DataFrame,
        shot_zone_row: pd.Series,
        analysis_date: date,
        is_early_season: bool
    ) -> Dict:
        """
        Calculate complete cache record for a single player.
        
        Args:
            player_lookup: Player identifier
            context_row: Row from upcoming_player_game_context
            player_games: Player's game history (sorted desc by date)
            team_games: Team's game history (sorted desc by date)
            shot_zone_row: Row from player_shot_zone_analysis
            analysis_date: Cache date
            is_early_season: Whether player has < min_games_required
        
        Returns:
            Dict: Complete cache record ready for BigQuery
        """
        # Recent performance (last 5, last 10, season)
        last_5_games = player_games.head(5)
        last_10_games = player_games.head(10)
        
        points_avg_last_5 = float(last_5_games['points'].mean()) if len(last_5_games) > 0 else None
        points_avg_last_10 = float(last_10_games['points'].mean()) if len(last_10_games) > 0 else None
        points_avg_season = float(player_games['points'].mean())
        points_std_last_10 = float(last_10_games['points'].std()) if len(last_10_games) > 1 else None
        
        minutes_avg_last_10 = float(last_10_games['minutes_played'].mean()) if len(last_10_games) > 0 else None
        usage_rate_last_10 = float(last_10_games['usage_rate'].mean()) if len(last_10_games) > 0 else None
        ts_pct_last_10 = float(last_10_games['ts_pct'].mean()) if len(last_10_games) > 0 else None
        
        games_played_season = int(len(player_games))
        player_usage_rate_season = float(player_games['usage_rate'].mean())
        
        # Team context (last 10 games)
        team_pace_last_10 = float(team_games['pace'].mean()) if len(team_games) > 0 else None
        team_off_rating_last_10 = float(team_games['offensive_rating'].mean()) if len(team_games) > 0 else None
        
        # Fatigue metrics (direct copy from context)
        games_in_last_7_days = int(context_row['games_in_last_7_days']) if pd.notna(context_row['games_in_last_7_days']) else None
        games_in_last_14_days = int(context_row['games_in_last_14_days']) if pd.notna(context_row['games_in_last_14_days']) else None
        minutes_in_last_7_days = int(context_row['minutes_in_last_7_days']) if pd.notna(context_row['minutes_in_last_7_days']) else None
        minutes_in_last_14_days = int(context_row['minutes_in_last_14_days']) if pd.notna(context_row['minutes_in_last_14_days']) else None
        back_to_backs_last_14_days = int(context_row['back_to_backs_last_14_days']) if pd.notna(context_row['back_to_backs_last_14_days']) else None
        avg_minutes_per_game_last_7 = float(context_row['avg_minutes_per_game_last_7']) if pd.notna(context_row['avg_minutes_per_game_last_7']) else None
        fourth_quarter_minutes_last_7 = int(context_row['fourth_quarter_minutes_last_7']) if pd.notna(context_row['fourth_quarter_minutes_last_7']) else None
        
        # Player demographics
        player_age = int(context_row['player_age']) if pd.notna(context_row['player_age']) else None
        
        # Shot zone tendencies (direct copy from shot_zone_analysis)
        primary_scoring_zone = str(shot_zone_row['primary_scoring_zone']) if pd.notna(shot_zone_row['primary_scoring_zone']) else None
        paint_rate_last_10 = float(shot_zone_row['paint_rate_last_10']) if pd.notna(shot_zone_row['paint_rate_last_10']) else None
        three_pt_rate_last_10 = float(shot_zone_row['three_pt_rate_last_10']) if pd.notna(shot_zone_row['three_pt_rate_last_10']) else None
        
        # Calculate assisted rate (from last 10 games)
        assisted_rate_last_10 = None
        if len(last_10_games) > 0:
            total_fg_makes = last_10_games['fg_makes'].sum()
            total_assisted = last_10_games['assisted_fg_makes'].sum()
            if total_fg_makes > 0:
                assisted_rate_last_10 = float(total_assisted / total_fg_makes)
        
        # Build complete record
        record = {
            # Identifiers
            'player_lookup': player_lookup,
            'universal_player_id': str(context_row['universal_player_id']) if pd.notna(context_row['universal_player_id']) else None,
            'cache_date': analysis_date.isoformat(),
            
            # Recent performance
            'points_avg_last_5': points_avg_last_5,
            'points_avg_last_10': points_avg_last_10,
            'points_avg_season': points_avg_season,
            'points_std_last_10': points_std_last_10,
            'minutes_avg_last_10': minutes_avg_last_10,
            'usage_rate_last_10': usage_rate_last_10,
            'ts_pct_last_10': ts_pct_last_10,
            'games_played_season': games_played_season,
            
            # Team context
            'team_pace_last_10': team_pace_last_10,
            'team_off_rating_last_10': team_off_rating_last_10,
            'player_usage_rate_season': player_usage_rate_season,
            
            # Fatigue metrics
            'games_in_last_7_days': games_in_last_7_days,
            'games_in_last_14_days': games_in_last_14_days,
            'minutes_in_last_7_days': minutes_in_last_7_days,
            'minutes_in_last_14_days': minutes_in_last_14_days,
            'back_to_backs_last_14_days': back_to_backs_last_14_days,
            'avg_minutes_per_game_last_7': avg_minutes_per_game_last_7,
            'fourth_quarter_minutes_last_7': fourth_quarter_minutes_last_7,
            
            # Shot zone tendencies
            'primary_scoring_zone': primary_scoring_zone,
            'paint_rate_last_10': paint_rate_last_10,
            'three_pt_rate_last_10': three_pt_rate_last_10,
            'assisted_rate_last_10': assisted_rate_last_10,
            
            # Demographics
            'player_age': player_age,
            
            # Source tracking (one-liner!)
            **self.build_source_tracking_fields(),
            
            # Early season flag
            'early_season_flag': is_early_season,
            'insufficient_data_reason': f"Only {games_played_season} games played, need {self.min_games_required} minimum" if is_early_season else None,

            # Metadata
            'cache_version': self.cache_version,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'processed_at': datetime.now(timezone.utc).isoformat()
        }
        
        return record


def main():
    """
    Main entry point for the player daily cache processor.
    
    Usage:
        python player_daily_cache_processor.py --analysis_date 2025-01-21
    """
    import argparse
    
    parser = argparse.ArgumentParser(description='Player Daily Cache Processor')
    parser.add_argument(
        '--analysis_date',
        type=str,
        required=True,
        help='Analysis date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--season_year',
        type=int,
        help='Season year (optional, will auto-detect from date)'
    )
    
    args = parser.parse_args()
    
    # Parse analysis date
    analysis_date = datetime.strptime(args.analysis_date, '%Y-%m-%d').date()
    
    # Auto-detect season year if not provided
    season_year = args.season_year
    if not season_year:
        season_year = analysis_date.year if analysis_date.month >= 10 else analysis_date.year - 1
    
    # Initialize processor
    processor = PlayerDailyCacheProcessor()
    
    # Set options
    processor.opts = {
        'analysis_date': analysis_date,
        'season_year': season_year
    }
    
    try:
        # Extract data
        logger.info("Starting data extraction...")
        processor.extract_raw_data()
        
        # Calculate cache
        logger.info("Starting cache calculation...")
        processor.calculate_precompute()
        
        # Save results
        logger.info("Saving cache to BigQuery...")
        success = processor.save_precompute()
        
        if success:
            logger.info("✓ Player daily cache processing complete!")
            logger.info(f"  - Cached: {len(processor.transformed_data)} players")
            logger.info(f"  - Failed: {len(processor.failed_entities)} players")
        else:
            logger.error("✗ Failed to save player daily cache")
            return 1
        
        return 0
        
    except Exception as e:
        logger.error(f"✗ Fatal error: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    exit(main())
