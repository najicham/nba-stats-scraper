#!/usr/bin/env python3
"""
Path: data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py

Player Shot Zone Analysis Processor

Analyzes each player's shot distribution and efficiency by court zone over their
last 10 games. Produces pre-calculated shot zone metrics for Phase 5 predictions.

Input: nba_analytics.player_game_summary (last 10 games per player)
Output: nba_precompute.player_shot_zone_analysis
Strategy: MERGE (update existing or insert new)
Schedule: Nightly at 11:15 PM (after team defense completes)
Duration: ~5-8 minutes for 450 players

Shot Zones:
- Paint: ≤8 feet from basket
- Mid-range: 9+ feet, 2-point shots
- Three-point: Beyond the arc

Version: 1.0 with v4.0 dependency tracking
Updated: October 30, 2025 - Fixed save method and datetime deprecations
"""

import logging
import os
import pandas as pd
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional
from google.cloud import bigquery

from data_processors.precompute.precompute_base import PrecomputeProcessorBase

# Pattern imports (Week 1 - Foundation Patterns)
from shared.processors.patterns import SmartSkipMixin, EarlyExitMixin, CircuitBreakerMixin

# Custom exceptions for dependency handling
class DependencyError(Exception):
    """Raised when critical dependencies are missing."""
    pass

class DataTooStaleError(Exception):
    """Raised when source data is too old."""
    pass

logger = logging.getLogger(__name__)


class PlayerShotZoneAnalysisProcessor(
    SmartSkipMixin,
    EarlyExitMixin,
    CircuitBreakerMixin,
    PrecomputeProcessorBase
):
    """
    Analyze player shot distribution and efficiency by court zone.

    Calculates for each player:
    - Shot distribution rates (paint %, mid-range %, three-point %)
    - Efficiency by zone (FG% in each zone)
    - Volume by zone (attempts per game)
    - Shot creation (assisted vs unassisted rates)
    - Primary scoring zone identification

    Uses last 10 games for primary analysis, last 20 games for trend comparison.
    """
    
    def __init__(self):
        """Initialize the processor."""
        super().__init__()
        
        # Table configuration
        self.table_name = 'player_shot_zone_analysis'
        self.entity_type = 'player'
        self.entity_field = 'player_lookup'
        
        # Processing requirements
        self.min_games_required = 10  # Minimum games for quality analysis
        self.sample_window = 10       # Primary analysis window
        self.trend_window = 20        # Broader trend window
        
        # BigQuery client initialization (CRITICAL)
        self.bq_client = bigquery.Client()
        self.project_id = os.environ.get('GCP_PROJECT_ID', self.bq_client.project)
        
        # Data containers
        self.raw_data = None
        self.transformed_data = []
        self.failed_entities = []

        logger.info(f"Initialized {self.__class__.__name__}")

    # ============================================================
    # Pattern #1: Smart Skip Configuration
    # ============================================================
    RELEVANT_SOURCES = {
        # Phase 3 Analytics sources - RELEVANT (depends on these)
        'player_game_summary': True,
        'team_offense_game_summary': True,
        'team_defense_game_summary': True,

        # Play-by-play sources - RELEVANT (for shot zone data)
        'bigdataball_play_by_play': True,
        'nbac_play_by_play': True,

        # Phase 4 Precompute sources - NOT RELEVANT (this processor doesn't depend on other Phase 4 tables)
        'player_composite_factors': False,
        'team_defense_zone_analysis': False,
        'player_daily_cache': False,

        # Phase 2 Raw sources - NOT RELEVANT (Phase 4 reads from Phase 3, not Phase 2 directly)
        'nbac_gamebook_player_stats': False,
        'bdl_player_boxscores': False,
        'nbac_team_boxscore': False,
        'odds_api_player_points_props': False,
        'odds_api_game_lines': False,
        'nbac_schedule': False,
        'nbac_injury_report': False
    }

    # ============================================================
    # Pattern #3: Early Exit Configuration
    # ============================================================
    ENABLE_NO_GAMES_CHECK = False      # Don't skip - analyzes historical games
    ENABLE_OFFSEASON_CHECK = True      # Skip in July-September
    ENABLE_HISTORICAL_DATE_CHECK = False  # Don't skip - can analyze any past date

    # ============================================================
    # Pattern #5: Circuit Breaker Configuration
    # ============================================================
    CIRCUIT_BREAKER_THRESHOLD = 5  # Open after 5 consecutive failures
    CIRCUIT_BREAKER_TIMEOUT = timedelta(minutes=30)  # Stay open 30 minutes

    def get_dependencies(self) -> dict:
        """
        Define source table requirements.
        
        Returns:
            dict: Dependency configuration for player_game_summary
        """
        return {
            'nba_analytics.player_game_summary': {
                'field_prefix': 'source_player_game',
                'description': 'Player game-level shot zone stats',
                'check_type': 'per_player_game_count',
                
                # Requirements
                'min_games_required': self.min_games_required,
                'min_players_with_data': 400,  # Expect at least 400 active players
                'entity_field': 'player_lookup',
                
                # Freshness thresholds
                'max_age_hours_warn': 24,   # Warn if >24 hours old
                'max_age_hours_fail': 72,   # Fail if >72 hours old
                
                # Early season handling (first 2 weeks of season)
                'early_season_days': 14,
                'early_season_behavior': 'WRITE_PLACEHOLDER',
                
                'critical': True
            }
        }
    
    def extract_raw_data(self) -> None:
        """
        Extract player game data from Phase 3 analytics.
        
        Queries last 10 games (and last 20 for trends) per player from
        player_game_summary. Includes dependency checking and early season handling.
        """
        analysis_date = self.opts.get('analysis_date')
        if not analysis_date:
            raise ValueError("analysis_date is required")
        
        logger.info(f"Extracting player shot zone data for {analysis_date}")
        
        # Check dependencies
        dep_check = self.check_dependencies(analysis_date)
        
        # Track source usage (populates source_* attributes for v4.0)
        self.track_source_usage(dep_check)
        
        # Handle early season (not enough games yet)
        if dep_check.get('is_early_season'):
            logger.warning(f"Early season detected: {dep_check.get('early_season_reason')}")
            self._write_placeholder_rows(dep_check)
            return
        
        # Handle critical dependency failures
        if not dep_check['all_critical_present']:
            missing = dep_check.get('missing', [])
            raise DependencyError(f"Missing critical dependencies: {missing}")
        
        if dep_check.get('has_stale_fail'):
            stale = dep_check.get('stale_fail', [])
            raise DataTooStaleError(f"Data too stale: {stale}")
        
        # Determine season start date (for filtering)
        season_year = analysis_date.year if analysis_date.month >= 10 else analysis_date.year - 1
        season_start_date = date(season_year, 10, 1)
        
        # Query player game data
        # Get last 20 games to support both 10-game and 20-game windows
        query = f"""
        WITH ranked_games AS (
            SELECT 
                -- Identifiers
                player_lookup,
                universal_player_id,
                game_id,
                game_date,
                opponent_team_abbr,
                
                -- Shot zone fields
                paint_attempts,
                paint_makes,
                mid_range_attempts,
                mid_range_makes,
                three_pt_attempts,
                three_pt_makes,
                
                -- Shot creation
                assisted_fg_makes,
                unassisted_fg_makes,
                fg_makes,
                
                -- Supporting fields
                minutes_played,
                is_active,
                
                -- Rank by recency
                ROW_NUMBER() OVER (
                    PARTITION BY player_lookup 
                    ORDER BY game_date DESC
                ) as game_rank
                
            FROM `{self.project_id}.nba_analytics.player_game_summary`
            WHERE game_date <= '{analysis_date}'
              AND game_date >= '{season_start_date}'
              AND is_active = TRUE
              AND minutes_played > 0
        )
        SELECT * 
        FROM ranked_games
        WHERE game_rank <= {self.trend_window}
        ORDER BY player_lookup, game_date DESC
        """
        
        logger.info(f"Querying player_game_summary for last {self.trend_window} games per player")
        
        try:
            self.raw_data = self.bq_client.query(query).to_dataframe()
            
            if self.raw_data.empty:
                logger.warning(f"No player game data found for {analysis_date}")
                return
            
            logger.info(f"Extracted {len(self.raw_data)} game records for "
                       f"{self.raw_data['player_lookup'].nunique()} players")
            
        except Exception as e:
            logger.error(f"Error extracting data: {e}")
            raise
    
    def _write_placeholder_rows(self, dep_check: dict) -> None:
        """
        Write placeholder rows for early season when insufficient games available.
        
        Args:
            dep_check: Dependency check results with early season info
        """
        analysis_date = self.opts.get('analysis_date')
        
        logger.info(f"Writing early season placeholders for {analysis_date}")
        
        # Query active players (even if <10 games)
        query = f"""
        SELECT DISTINCT
            player_lookup,
            universal_player_id
        FROM `{self.project_id}.nba_analytics.player_game_summary`
        WHERE game_date <= '{analysis_date}'
          AND game_date >= DATE_SUB('{analysis_date}', INTERVAL 30 DAY)
          AND is_active = TRUE
        """
        
        try:
            players_df = self.bq_client.query(query).to_dataframe()
            
            placeholder_rows = []
            for _, player in players_df.iterrows():
                row = {
                    # Identifiers
                    'player_lookup': player['player_lookup'],
                    'universal_player_id': player.get('universal_player_id'),
                    'analysis_date': analysis_date.isoformat(),
                    
                    # All metrics NULL for early season
                    'paint_rate_last_10': None,
                    'mid_range_rate_last_10': None,
                    'three_pt_rate_last_10': None,
                    'total_shots_last_10': None,
                    'games_in_sample_10': 0,
                    'sample_quality_10': 'insufficient',
                    
                    'paint_pct_last_10': None,
                    'mid_range_pct_last_10': None,
                    'three_pt_pct_last_10': None,
                    
                    'paint_attempts_per_game': None,
                    'mid_range_attempts_per_game': None,
                    'three_pt_attempts_per_game': None,
                    
                    'paint_rate_last_20': None,
                    'paint_pct_last_20': None,
                    'games_in_sample_20': 0,
                    'sample_quality_20': 'insufficient',
                    
                    'assisted_rate_last_10': None,
                    'unassisted_rate_last_10': None,
                    
                    'player_position': None,
                    'primary_scoring_zone': None,
                    
                    'data_quality_tier': 'low',
                    'calculation_notes': 'Early season - insufficient games for analysis',
                    
                    # v4.0 source tracking
                    **self.build_source_tracking_fields(),
                    
                    # Early season flags
                    'early_season_flag': True,
                    'insufficient_data_reason': dep_check.get('early_season_reason', 
                                                              'Season start - insufficient games'),
                    
                    # Processing metadata
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'processed_at': datetime.now(timezone.utc).isoformat()
                }
                placeholder_rows.append(row)
            
            self.transformed_data = placeholder_rows
            logger.info(f"Created {len(placeholder_rows)} early season placeholder rows")
            
        except Exception as e:
            logger.error(f"Error creating placeholder rows: {e}")
            raise
    
    def calculate_precompute(self) -> None:
        """
        Calculate shot zone metrics for each player.
        
        For each player with sufficient games:
        - Calculate shot distribution rates by zone
        - Calculate efficiency by zone (FG%)
        - Calculate volume per game
        - Calculate assisted vs unassisted rates
        - Determine primary scoring zone
        - Assess sample quality
        """
        if self.raw_data is None or self.raw_data.empty:
            logger.warning("No raw data to process")
            return
        
        logger.info("Calculating shot zone metrics for all players")
        
        successful = []
        failed = []
        
        # Get all unique players
        all_players = self.raw_data['player_lookup'].unique()
        
        for player_lookup in all_players:
            try:
                # Filter data for this player
                player_data = self.raw_data[
                    self.raw_data['player_lookup'] == player_lookup
                ].copy()
                
                # Separate 10-game and 20-game samples
                games_10 = player_data[player_data['game_rank'] <= self.sample_window]
                games_20 = player_data[player_data['game_rank'] <= self.trend_window]
                
                # Check sufficient games for 10-game analysis
                if len(games_10) < self.min_games_required:
                    failed.append({
                        'entity_id': player_lookup,
                        'reason': f"Only {len(games_10)} games, need {self.min_games_required}",
                        'category': 'INSUFFICIENT_DATA',
                        'can_retry': True
                    })
                    continue
                
                # Calculate metrics for 10-game window
                metrics_10 = self._calculate_zone_metrics(games_10)
                
                # Calculate metrics for 20-game window (for trends)
                metrics_20 = self._calculate_zone_metrics(games_20) if len(games_20) >= 15 else {}
                
                # Determine primary scoring zone
                primary_zone = self._determine_primary_zone(metrics_10)
                
                # Assess data quality
                quality_tier = self._determine_quality_tier(len(games_10))
                sample_quality_10 = self._determine_sample_quality(len(games_10), self.sample_window)
                sample_quality_20 = self._determine_sample_quality(len(games_20), self.trend_window)
                
                # Build output record
                record = {
                    # Identifiers
                    'player_lookup': player_lookup,
                    'universal_player_id': player_data.iloc[0].get('universal_player_id'),
                    'analysis_date': self.opts['analysis_date'].isoformat(),
                    
                    # Shot distribution - Last 10 games
                    'paint_rate_last_10': metrics_10.get('paint_rate'),
                    'mid_range_rate_last_10': metrics_10.get('mid_range_rate'),
                    'three_pt_rate_last_10': metrics_10.get('three_pt_rate'),
                    'total_shots_last_10': metrics_10.get('total_shots'),
                    'games_in_sample_10': int(len(games_10)),
                    'sample_quality_10': sample_quality_10,
                    
                    # Efficiency - Last 10 games
                    'paint_pct_last_10': metrics_10.get('paint_pct'),
                    'mid_range_pct_last_10': metrics_10.get('mid_range_pct'),
                    'three_pt_pct_last_10': metrics_10.get('three_pt_pct'),
                    
                    # Volume - Last 10 games
                    'paint_attempts_per_game': metrics_10.get('paint_attempts_pg'),
                    'mid_range_attempts_per_game': metrics_10.get('mid_range_attempts_pg'),
                    'three_pt_attempts_per_game': metrics_10.get('three_pt_attempts_pg'),
                    
                    # Trend comparison - Last 20 games
                    'paint_rate_last_20': metrics_20.get('paint_rate'),
                    'paint_pct_last_20': metrics_20.get('paint_pct'),
                    'games_in_sample_20': int(len(games_20)),
                    'sample_quality_20': sample_quality_20,
                    
                    # Shot creation
                    'assisted_rate_last_10': metrics_10.get('assisted_rate'),
                    'unassisted_rate_last_10': metrics_10.get('unassisted_rate'),
                    
                    # Player characteristics
                    'player_position': None,  # TODO: Get from player registry
                    'primary_scoring_zone': primary_zone,
                    
                    # Data quality
                    'data_quality_tier': quality_tier,
                    'calculation_notes': None,
                    
                    # v4.0 source tracking (one line!)
                    **self.build_source_tracking_fields(),
                    
                    # Early season (not early season if we got here)
                    'early_season_flag': False,
                    'insufficient_data_reason': None,
                    
                    # Processing metadata
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'processed_at': datetime.now(timezone.utc).isoformat()
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
        
        logger.info(f"Calculated metrics for {len(successful)} players, "
                   f"{len(failed)} failures")
    
    def _calculate_zone_metrics(self, games_df: pd.DataFrame) -> dict:
        """
        Calculate shot zone metrics for a sample of games.
        
        Args:
            games_df: DataFrame of games for a player
            
        Returns:
            dict: Calculated metrics
        """
        # Aggregate totals
        paint_att = games_df['paint_attempts'].sum()
        paint_makes = games_df['paint_makes'].sum()
        mid_att = games_df['mid_range_attempts'].sum()
        mid_makes = games_df['mid_range_makes'].sum()
        three_att = games_df['three_pt_attempts'].sum()
        three_makes = games_df['three_pt_makes'].sum()
        
        total_att = paint_att + mid_att + three_att
        total_makes = games_df['fg_makes'].sum()
        assisted_makes = games_df['assisted_fg_makes'].sum()
        unassisted_makes = games_df['unassisted_fg_makes'].sum()
        
        games_count = len(games_df)
        
        # Calculate rates (distribution)
        paint_rate = (paint_att / total_att * 100) if total_att > 0 else None
        mid_rate = (mid_att / total_att * 100) if total_att > 0 else None
        three_rate = (three_att / total_att * 100) if total_att > 0 else None
        
        # Calculate efficiency (FG%)
        paint_pct = (paint_makes / paint_att) if paint_att > 0 else None
        mid_pct = (mid_makes / mid_att) if mid_att > 0 else None
        three_pct = (three_makes / three_att) if three_att > 0 else None
        
        # Calculate volume per game
        paint_pg = paint_att / games_count if games_count > 0 else None
        mid_pg = mid_att / games_count if games_count > 0 else None
        three_pg = three_att / games_count if games_count > 0 else None
        
        # Calculate assisted rates
        assisted_rate = (assisted_makes / total_makes * 100) if total_makes > 0 else None
        unassisted_rate = (unassisted_makes / total_makes * 100) if total_makes > 0 else None
        
        return {
            'paint_rate': round(paint_rate, 2) if paint_rate is not None else None,
            'mid_range_rate': round(mid_rate, 2) if mid_rate is not None else None,
            'three_pt_rate': round(three_rate, 2) if three_rate is not None else None,
            'paint_pct': round(paint_pct, 3) if paint_pct is not None else None,
            'mid_range_pct': round(mid_pct, 3) if mid_pct is not None else None,
            'three_pt_pct': round(three_pct, 3) if three_pct is not None else None,
            'paint_attempts_pg': round(paint_pg, 1) if paint_pg is not None else None,
            'mid_range_attempts_pg': round(mid_pg, 1) if mid_pg is not None else None,
            'three_pt_attempts_pg': round(three_pg, 1) if three_pg is not None else None,
            'assisted_rate': round(assisted_rate, 2) if assisted_rate is not None else None,
            'unassisted_rate': round(unassisted_rate, 2) if unassisted_rate is not None else None,
            'total_shots': int(total_att) if total_att > 0 else None
        }
    
    def _determine_primary_zone(self, metrics: dict) -> Optional[str]:
        """
        Determine player's primary scoring zone based on shot distribution.
        """
        paint_rate = metrics.get('paint_rate', 0) or 0
        mid_rate = metrics.get('mid_range_rate', 0) or 0
        three_rate = metrics.get('three_pt_rate', 0) or 0
        
        # If missing data, return None
        if paint_rate == 0 and mid_rate == 0 and three_rate == 0:
            return None
        
        # Check for clear dominance first
        if paint_rate >= 40:
            return 'paint'
        elif three_rate >= 40:
            return 'perimeter'
        elif mid_rate >= 35:  # Raised threshold so 33.3% doesn't trigger
            return 'mid_range'
        else:
            return 'balanced'
    
    def _determine_quality_tier(self, games_count: int) -> str:
        """
        Assess data quality based on sample size.
        
        Args:
            games_count: Number of games in sample
            
        Returns:
            str: 'high', 'medium', or 'low'
        """
        if games_count >= self.min_games_required:
            return 'high'
        elif games_count >= 7:
            return 'medium'
        else:
            return 'low'
    
    def _determine_sample_quality(self, games_count: int, target_window: int) -> str:
        """
        Assess sample quality relative to target window.
        
        Args:
            games_count: Number of games in sample
            target_window: Target number of games (10 or 20)
            
        Returns:
            str: 'excellent', 'good', 'limited', or 'insufficient'
        """
        if games_count >= target_window:
            return 'excellent'
        elif games_count >= int(target_window * 0.7):
            return 'good'
        elif games_count >= int(target_window * 0.5):
            return 'limited'
        else:
            return 'insufficient'
    
    def save_precompute(self) -> bool:
        """
        Save calculated metrics to BigQuery using parent class implementation.
        
        Parent class handles:
        - MERGE_UPDATE strategy (delete + insert)
        - Batch INSERT via BigQuery load jobs
        - Streaming buffer error handling
        
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.transformed_data:
            logger.warning("No data to save")
            return True
        
        logger.info(f"Saving {len(self.transformed_data)} records")
        
        try:
            # Use parent class save implementation
            super().save_precompute()
            
            # Save failure records if any
            if self.failed_entities:
                self._save_failures()
            
            logger.info(f"Successfully saved {len(self.transformed_data)} records")
            return True
            
        except Exception as e:
            logger.error(f"Error saving to BigQuery: {e}")
            return False
    
    def _save_failures(self) -> None:
        """Save failed entity records for debugging."""
        if not self.failed_entities:
            return
        
        try:
            table_id = f"{self.project_id}.nba_processing.precompute_failures"
            
            failure_records = []
            for failure in self.failed_entities:
                failure_records.append({
                    'processor_name': self.__class__.__name__,
                    'run_id': self.run_id,
                    'analysis_date': self.opts['analysis_date'].isoformat(),
                    'entity_id': failure['entity_id'],
                    'failure_category': failure['category'],
                    'failure_reason': failure['reason'],
                    'can_retry': failure['can_retry'],
                    'created_at': datetime.now(timezone.utc).isoformat()
                })
            
            self.bq_client.insert_rows_json(table_id, failure_records)
            logger.info(f"Saved {len(failure_records)} failure records")
            
        except Exception as e:
            logger.warning(f"Failed to save failure records: {e}")


# CLI entry point for testing
if __name__ == '__main__':
    import sys
    from datetime import date
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Parse command line arguments
    if len(sys.argv) > 1:
        analysis_date = datetime.strptime(sys.argv[1], '%Y-%m-%d').date()
    else:
        analysis_date = date.today()
    
    logger.info(f"Running Player Shot Zone Analysis for {analysis_date}")
    
    # Initialize and run processor
    processor = PlayerShotZoneAnalysisProcessor()
    processor.opts = {'analysis_date': analysis_date}
    
    try:
        # Extract data
        processor.extract_raw_data()
        
        # Calculate metrics
        processor.calculate_precompute()
        
        # Save results
        if processor.save_precompute():
            logger.info("✓ Processing complete!")
        else:
            logger.error("✗ Processing failed")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"✗ Processing error: {e}")
        sys.exit(1)