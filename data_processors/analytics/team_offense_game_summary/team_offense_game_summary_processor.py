#!/usr/bin/env python3
"""
Path: analytics_processors/team_offense_game_summary/team_offense_game_summary_processor.py

Team Offense Game Summary Processor for NBA Props Platform Analytics.
Aggregates team box score statistics into comprehensive offensive analytics.

Phase 3 Analytics Processor with full dependency tracking (v4.0 pattern).

Dependencies (Phase 2):
  - nba_raw.nbac_team_boxscore (PRIMARY - CRITICAL)
  - nba_raw.nbac_play_by_play (ENHANCEMENT - OPTIONAL for shot zones)

Output: nba_analytics.team_offense_game_summary

Processing Strategy: MERGE_UPDATE
  - Allows re-processing to add shot zones when play-by-play arrives
  - Updates existing records rather than creating duplicates

Key Features:
  - Full dependency checking before extraction
  - Source tracking per v4.0 dependency guide
  - Advanced metric calculations (ORtg, pace, possessions, TS%)
  - OT period parsing from minutes string
  - Win/loss determination via self-join
  - Optional shot zone extraction from play-by-play
  - Comprehensive data quality validation

Version: 2.0 (updated for AnalyticsProcessorBase v2.0)
Updated: January 2025
"""

import logging
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from data_processors.analytics.analytics_base import AnalyticsProcessorBase
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

# Pattern imports (Week 1 - Foundation Patterns)
from shared.processors.patterns import SmartSkipMixin, EarlyExitMixin, CircuitBreakerMixin

logger = logging.getLogger(__name__)


class TeamOffenseGameSummaryProcessor(
    SmartSkipMixin,
    EarlyExitMixin,
    CircuitBreakerMixin,
    AnalyticsProcessorBase
):
    """
    Process team offensive game summary analytics from team box scores.

    Aggregates team-level statistics with optional shot zone enhancement.
    Includes full dependency tracking and source metadata.
    """
    
    def __init__(self):
        super().__init__()
        self.table_name = 'team_offense_game_summary'
        self.processing_strategy = 'MERGE_UPDATE'
        
        # Source metadata tracking (populated by track_source_usage)
        self.source_metadata = {}
        
        # Per-source attributes (for build_source_tracking_fields)
        self.source_nbac_boxscore_last_updated = None
        self.source_nbac_boxscore_rows_found = None
        self.source_nbac_boxscore_completeness_pct = None
        
        self.source_play_by_play_last_updated = None
        self.source_play_by_play_rows_found = None
        self.source_play_by_play_completeness_pct = None
        
        # Shot zone tracking
        self.shot_zones_available = False
        self.shot_zones_source = None
        self.shot_zone_data = {}  # Keyed by (game_id, team_abbr)

    # ============================================================
    # Pattern #1: Smart Skip Configuration
    # ============================================================
    RELEVANT_SOURCES = {
        # Team boxscore sources - RELEVANT (core offensive data)
        'nbac_team_boxscore': True,
        'bdl_team_boxscores': True,
        'espn_team_stats': True,

        # Player boxscore sources - RELEVANT (for aggregation)
        'nbac_gamebook_player_stats': True,
        'bdl_player_boxscores': True,
        'nbac_player_boxscores': True,

        # Play-by-play sources - RELEVANT (shot zones)
        'bigdataball_play_by_play': True,
        'nbac_play_by_play': True,

        # Player prop sources - NOT RELEVANT
        'odds_api_player_points_props': False,
        'bettingpros_player_points_props': False,
        'odds_api_player_rebounds_props': False,
        'odds_api_player_assists_props': False,

        # Game odds/spreads - NOT RELEVANT
        'odds_api_spreads': False,
        'odds_api_totals': False,
        'odds_game_lines': False,

        # Injury/roster sources - NOT RELEVANT
        'nbac_injury_report': False,
        'nbacom_roster': False,

        # Schedule sources - NOT RELEVANT
        'nbacom_schedule': False,
        'espn_scoreboard': False
    }

    # ============================================================
    # Pattern #3: Early Exit Configuration
    # ============================================================
    ENABLE_NO_GAMES_CHECK = True       # Skip if no games scheduled
    ENABLE_OFFSEASON_CHECK = True      # Skip in July-September
    ENABLE_HISTORICAL_DATE_CHECK = True  # Skip dates >90 days old

    # ============================================================
    # Pattern #5: Circuit Breaker Configuration
    # ============================================================
    CIRCUIT_BREAKER_THRESHOLD = 5  # Open after 5 consecutive failures
    CIRCUIT_BREAKER_TIMEOUT = timedelta(minutes=30)  # Stay open 30 minutes

    # =========================================================================
    # Dependency System (Phase 3 - Date Range Pattern)
    # =========================================================================
    
    def get_dependencies(self) -> dict:
        """
        Define required upstream Phase 2 tables and their constraints.
        
        Returns:
            dict: Dependency configuration per v4.0 spec
        """
        return {
            'nba_raw.nbac_team_boxscore': {
                'field_prefix': 'source_nbac_boxscore',
                'description': 'Team box score statistics',
                'date_field': 'game_date',
                'check_type': 'date_range',  # ✅ FIXED: was 'date_match', now 'date_range'
                'expected_count_min': 20,  # ~10 games × 2 teams per game
                'max_age_hours_warn': 24,
                'max_age_hours_fail': 72,
                'critical': True
            },
            'nba_raw.nbac_play_by_play': {
                'field_prefix': 'source_play_by_play',
                'description': 'Play-by-play for shot zones',
                'date_field': 'game_date',
                'check_type': 'date_range',  # ✅ FIXED: was 'lookback', now 'date_range'
                'expected_count_min': 1000,  # Many events per game day
                'max_age_hours_warn': 48,
                'max_age_hours_fail': 168,
                'critical': False  # Can proceed without shot zones
            }
        }
    
    # =========================================================================
    # Data Extraction (Phase 2 Raw Tables)
    # =========================================================================
    
    def extract_raw_data(self) -> None:
        """
        Extract team offensive data from Phase 2 raw tables.

        Primary source: nba_raw.nbac_team_boxscore (v2.0)
        Enhancement: nba_raw.nbac_play_by_play (for shot zones)

        Note: Dependency checking happens in base class run() before this is called.

        NEW in v3.0: Smart reprocessing - skip processing if Phase 2 source unchanged.
        """
        start_date = self.opts['start_date']
        end_date = self.opts['end_date']

        # SMART REPROCESSING: Check if we can skip processing
        skip, reason = self.should_skip_processing(start_date)
        if skip:
            self.logger.info(f"✅ SMART REPROCESSING: Skipping processing - {reason}")
            self.raw_data = []
            return

        self.logger.info(f"🔄 PROCESSING: {reason}")

        # Extract team box score data with opponent context
        query = f"""
        WITH team_boxscores AS (
            SELECT 
                tb.game_id,
                tb.nba_game_id,
                tb.game_date,
                tb.season_year,
                tb.team_abbr,
                tb.team_name,
                tb.is_home,
                
                -- Opponent via self-join (simplified with v2.0 is_home)
                t2.team_abbr as opponent_team_abbr,
                t2.points as opponent_points,
                
                -- Basic stats
                tb.points,
                tb.fg_made,
                tb.fg_attempted,
                tb.fg_percentage,
                tb.three_pt_made,
                tb.three_pt_attempted,
                tb.three_pt_percentage,
                tb.ft_made,
                tb.ft_attempted,
                tb.ft_percentage,
                tb.offensive_rebounds,
                tb.defensive_rebounds,
                tb.total_rebounds,
                tb.assists,
                tb.steals,
                tb.blocks,
                tb.turnovers,
                tb.personal_fouls,
                tb.plus_minus,
                
                -- Minutes for OT calculation
                tb.minutes,
                
                -- Source tracking
                tb.processed_at as source_last_updated
                
            FROM `{self.project_id}.nba_raw.nbac_team_boxscore` tb
            
            -- Self-join for opponent context (v2.0: simplified with is_home)
            JOIN `{self.project_id}.nba_raw.nbac_team_boxscore` t2
                ON tb.game_id = t2.game_id
                AND tb.game_date = t2.game_date
                AND tb.is_home != t2.is_home  -- Get OTHER team
            
            WHERE tb.game_date BETWEEN '{start_date}' AND '{end_date}'
        )
        SELECT * FROM team_boxscores
        ORDER BY game_date DESC, game_id, team_abbr
        """
        
        logger.info(f"Extracting team offensive data for {start_date} to {end_date}")
        
        try:
            self.raw_data = self.bq_client.query(query).to_dataframe()
            logger.info(f"Extracted {len(self.raw_data)} team-game records from team boxscore")
            
            if self.raw_data.empty:
                logger.warning(f"No team offensive data extracted for {start_date} to {end_date}")
                notify_warning(
                    title="Team Offense: No Data Extracted",
                    message=f"No team records found for {start_date} to {end_date}",
                    details={
                        'processor': 'team_offense_game_summary',
                        'start_date': start_date,
                        'end_date': end_date,
                        'source_completeness': self.source_nbac_boxscore_completeness_pct,
                        'possible_causes': ['no games scheduled', 'team_boxscore incomplete']
                    }
                )
                return
            
            # Extract shot zones if play-by-play available
            self._extract_shot_zones(start_date, end_date)
            
        except Exception as e:
            logger.error(f"BigQuery extraction failed: {e}")
            notify_error(
                title="Team Offense: Data Extraction Failed",
                message=f"Failed to extract team offensive data: {str(e)}",
                details={
                    'processor': 'team_offense_game_summary',
                    'start_date': start_date,
                    'end_date': end_date,
                    'error_type': type(e).__name__
                },
                processor_name="Team Offense Game Summary Processor"
            )
            raise
    
    def _extract_shot_zones(self, start_date: str, end_date: str) -> None:
        """
        Extract shot zone data from play-by-play (optional enhancement).
        
        Gracefully handles missing play-by-play data.
        """
        # Check if play-by-play is available
        if self.source_play_by_play_rows_found is None or self.source_play_by_play_rows_found == 0:
            logger.info("Play-by-play not available, shot zones will be NULL")
            self.shot_zones_available = False
            self.shot_zones_source = None
            return
        
        try:
            query = f"""
            WITH team_shots AS (
                SELECT 
                    game_id,
                    player_1_team_abbr as team_abbr,
                    -- Classify shot zone
                    CASE 
                        WHEN shot_type = '2PT' AND shot_distance <= 8.0 THEN 'paint'
                        WHEN shot_type = '2PT' AND shot_distance > 8.0 THEN 'mid_range'
                        WHEN shot_type = '3PT' THEN 'three'
                        ELSE NULL
                    END as zone,
                    shot_made,
                    CASE 
                        WHEN shot_type = '2PT' THEN 2
                        WHEN shot_type = '3PT' THEN 3
                        ELSE 0
                    END as points_value
                FROM `{self.project_id}.nba_raw.nbac_play_by_play`
                WHERE event_type = 'fieldgoal'
                    AND shot_made IS NOT NULL
                    AND game_date BETWEEN '{start_date}' AND '{end_date}'
            )
            SELECT 
                game_id,
                team_abbr,
                -- Paint
                COUNT(CASE WHEN zone = 'paint' THEN 1 END) as paint_attempts,
                COUNT(CASE WHEN zone = 'paint' AND shot_made = TRUE THEN 1 END) as paint_makes,
                SUM(CASE WHEN zone = 'paint' AND shot_made = TRUE THEN points_value ELSE 0 END) as points_in_paint,
                -- Mid-range
                COUNT(CASE WHEN zone = 'mid_range' THEN 1 END) as mid_range_attempts,
                COUNT(CASE WHEN zone = 'mid_range' AND shot_made = TRUE THEN 1 END) as mid_range_makes,
                -- Three (for validation)
                COUNT(CASE WHEN zone = 'three' THEN 1 END) as three_attempts_pbp,
                COUNT(CASE WHEN zone = 'three' AND shot_made = TRUE THEN 1 END) as three_makes_pbp
            FROM team_shots
            GROUP BY game_id, team_abbr
            """
            
            shot_zones_df = self.bq_client.query(query).to_dataframe()
            
            if not shot_zones_df.empty:
                # Convert to dict keyed by (game_id, team_abbr)
                for _, row in shot_zones_df.iterrows():
                    key = (row['game_id'], row['team_abbr'])
                    self.shot_zone_data[key] = {
                        'paint_attempts': int(row['paint_attempts']) if pd.notna(row['paint_attempts']) else None,
                        'paint_makes': int(row['paint_makes']) if pd.notna(row['paint_makes']) else None,
                        'mid_range_attempts': int(row['mid_range_attempts']) if pd.notna(row['mid_range_attempts']) else None,
                        'mid_range_makes': int(row['mid_range_makes']) if pd.notna(row['mid_range_makes']) else None,
                        'points_in_paint': int(row['points_in_paint']) if pd.notna(row['points_in_paint']) else None,
                        'three_attempts_pbp': int(row['three_attempts_pbp']) if pd.notna(row['three_attempts_pbp']) else None,
                        'three_makes_pbp': int(row['three_makes_pbp']) if pd.notna(row['three_makes_pbp']) else None,
                    }
                
                self.shot_zones_available = True
                self.shot_zones_source = 'nbac_pbp'
                logger.info(f"Extracted shot zones for {len(self.shot_zone_data)} team-games from play-by-play")
            else:
                logger.warning("Play-by-play query returned no shot zones")
                self.shot_zones_available = False
                self.shot_zones_source = None
                
        except Exception as e:
            logger.warning(f"Failed to extract shot zones (non-critical): {e}")
            self.shot_zones_available = False
            self.shot_zones_source = None
    
    # =========================================================================
    # Data Validation
    # =========================================================================
    
    def validate_extracted_data(self) -> None:
        """Enhanced validation for team offensive data."""
        super().validate_extracted_data()
        
        if self.raw_data.empty:
            error_msg = "No team offensive data extracted for date range"
            logger.error(error_msg)
            notify_error(
                title="Team Offense: Validation Failed",
                message=error_msg,
                details={
                    'processor': 'team_offense_game_summary',
                    'start_date': self.opts['start_date'],
                    'end_date': self.opts['end_date']
                },
                processor_name="Team Offense Game Summary Processor"
            )
            raise ValueError(error_msg)
        
        # Validate points calculation
        for _, row in self.raw_data.iterrows():
            two_pt_makes = row['fg_made'] - row['three_pt_made']
            calculated_points = (two_pt_makes * 2) + (row['three_pt_made'] * 3) + row['ft_made']
            
            if calculated_points != row['points']:
                self.log_quality_issue(
                    issue_type='points_calculation_mismatch',
                    severity='high',
                    identifier=f"{row['game_id']}_{row['team_abbr']}",
                    details={
                        'reported_points': int(row['points']),
                        'calculated_points': int(calculated_points),
                        'difference': int(row['points'] - calculated_points)
                    }
                )
        
        # Check for unrealistic team scores
        unrealistic_scores = self.raw_data[
            (self.raw_data['points'].notna()) & 
            ((self.raw_data['points'] < 50) | (self.raw_data['points'] > 200))
        ]
        
        if not unrealistic_scores.empty:
            for _, row in unrealistic_scores.iterrows():
                self.log_quality_issue(
                    issue_type='unrealistic_team_score',
                    severity='high',
                    identifier=f"{row['game_id']}_{row['team_abbr']}",
                    details={
                        'points_scored': int(row['points'])
                    }
                )
    
    # =========================================================================
    # Analytics Calculation
    # =========================================================================
    
    def calculate_analytics(self) -> None:
        """Transform team aggregates to final analytics format."""
        records = []
        processing_errors = []
        
        for _, row in self.raw_data.iterrows():
            try:
                # Parse overtime periods
                overtime_periods = self._parse_overtime_periods(row['minutes'])
                
                # Calculate possessions
                possessions = self._calculate_possessions(
                    row['fg_attempted'],
                    row['ft_attempted'],
                    row['turnovers'],
                    row['offensive_rebounds']
                )
                
                # minutes field is cumulative player-minutes (5 players × game time)
                # Convert to actual game minutes by dividing by 5
                total_player_minutes = int(row['minutes'].split(':')[0]) if pd.notna(row['minutes']) else 240
                actual_game_minutes = total_player_minutes / 5  # Convert to real game time
                offensive_rating = (row['points'] / possessions) * 100 if possessions > 0 else None
                pace = possessions * (48 / actual_game_minutes) if actual_game_minutes > 0 else None
                ts_pct = self._calculate_true_shooting_pct(
                    row['points'],
                    row['fg_attempted'],
                    row['ft_attempted']
                )
                
                # Determine win/loss
                win_flag = row['points'] > row['opponent_points']
                margin_of_victory = row['points'] - row['opponent_points']
                
                # Get shot zones (if available)
                shot_zone_key = (row['game_id'], row['team_abbr'])
                shot_zones = self.shot_zone_data.get(shot_zone_key, {})
                
                # Build record with all fields
                record = {
                    # Core identifiers
                    'game_id': row['game_id'],
                    'nba_game_id': row['nba_game_id'],
                    'game_date': row['game_date'].isoformat() if pd.notna(row['game_date']) else None,
                    'team_abbr': row['team_abbr'],
                    'opponent_team_abbr': row['opponent_team_abbr'],
                    'season_year': int(row['season_year']) if pd.notna(row['season_year']) else None,
                    
                    # Basic offensive stats
                    'points_scored': int(row['points']) if pd.notna(row['points']) else None,
                    'fg_attempts': int(row['fg_attempted']) if pd.notna(row['fg_attempted']) else None,
                    'fg_makes': int(row['fg_made']) if pd.notna(row['fg_made']) else None,
                    'three_pt_attempts': int(row['three_pt_attempted']) if pd.notna(row['three_pt_attempted']) else None,
                    'three_pt_makes': int(row['three_pt_made']) if pd.notna(row['three_pt_made']) else None,
                    'ft_attempts': int(row['ft_attempted']) if pd.notna(row['ft_attempted']) else None,
                    'ft_makes': int(row['ft_made']) if pd.notna(row['ft_made']) else None,
                    'rebounds': int(row['total_rebounds']) if pd.notna(row['total_rebounds']) else None,
                    'assists': int(row['assists']) if pd.notna(row['assists']) else None,
                    'turnovers': int(row['turnovers']) if pd.notna(row['turnovers']) else None,
                    'personal_fouls': int(row['personal_fouls']) if pd.notna(row['personal_fouls']) else None,
                    
                    # Shot zones (from play-by-play if available)
                    'team_paint_attempts': shot_zones.get('paint_attempts'),
                    'team_paint_makes': shot_zones.get('paint_makes'),
                    'team_mid_range_attempts': shot_zones.get('mid_range_attempts'),
                    'team_mid_range_makes': shot_zones.get('mid_range_makes'),
                    'points_in_paint_scored': shot_zones.get('points_in_paint'),
                    'second_chance_points_scored': None,  # TODO: Complex calculation, defer
                    
                    # Advanced offensive metrics
                    'offensive_rating': round(offensive_rating, 2) if offensive_rating else None,
                    'pace': round(pace, 1) if pace else None,
                    'possessions': int(possessions) if possessions else None,
                    'ts_pct': round(ts_pct, 3) if ts_pct else None,
                    
                    # Game context
                    'home_game': bool(row['is_home']) if pd.notna(row['is_home']) else False,
                    'win_flag': bool(win_flag),
                    'margin_of_victory': int(margin_of_victory) if pd.notna(margin_of_victory) else None,
                    'overtime_periods': int(overtime_periods),
                    
                    # Team situation context (placeholders)
                    'players_inactive': None,
                    'starters_inactive': None,
                    
                    # Referee integration (placeholder)
                    'referee_crew_id': None,
                    
                    # Source tracking (one-liner using base class method!)
                    **self.build_source_tracking_fields(),
                    
                    # Data quality tracking
                    'data_quality_tier': self._calculate_quality_tier(shot_zones),
                    'shot_zones_available': self.shot_zones_available,
                    'shot_zones_source': self.shot_zones_source,
                    'primary_source_used': 'nbac_team_boxscore',
                    'processed_with_issues': False,
                    
                    # Processing metadata
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'processed_at': datetime.now(timezone.utc).isoformat()
                }
                
                records.append(record)
                
            except Exception as e:
                error_info = {
                    'game_id': row['game_id'],
                    'team': row['team_abbr'],
                    'error': str(e),
                    'error_type': type(e).__name__
                }
                processing_errors.append(error_info)
                
                logger.error(f"Error processing team record {row['game_id']}_{row['team_abbr']}: {e}")
                self.log_quality_issue(
                    issue_type='processing_error',
                    severity='medium',
                    identifier=f"{row['game_id']}_{row['team_abbr']}",
                    details=error_info
                )
                continue
        
        self.transformed_data = records
        logger.info(f"Calculated team offensive analytics for {len(records)} team-game records")
        
        # Notify if high error rate
        if len(processing_errors) > 0:
            error_rate = len(processing_errors) / len(self.raw_data) * 100
            
            if error_rate > 5:
                notify_warning(
                    title="Team Offense: High Processing Error Rate",
                    message=f"Failed to process {len(processing_errors)} records ({error_rate:.1f}% error rate)",
                    details={
                        'processor': 'team_offense_game_summary',
                        'total_input_records': len(self.raw_data),
                        'processing_errors': len(processing_errors),
                        'error_rate_pct': round(error_rate, 2),
                        'successful_records': len(records),
                        'sample_errors': processing_errors[:5]
                    }
                )
    
    # =========================================================================
    # Helper Calculation Methods
    # =========================================================================
    
    def _parse_overtime_periods(self, minutes_str: str) -> int:
        """
        Parse overtime periods from minutes string.
        
        Examples:
          "240:00" = 0 OT (regulation)
          "265:00" = 1 OT (240 + 25)
          "290:00" = 2 OT (240 + 50)
        """
        if not minutes_str or minutes_str == '':
            return 0
        
        try:
            # Parse total minutes (before colon)
            total_minutes = int(minutes_str.split(':')[0])
            
            if total_minutes <= 240:
                return 0
            
            # Calculate OT periods
            overtime_minutes = total_minutes - 240
            return overtime_minutes // 25
            
        except Exception as e:
            logger.warning(f"Failed to parse OT periods from '{minutes_str}': {e}")
            return 0
    
    def _calculate_possessions(self, fg_attempts: int, ft_attempts: int,
                               turnovers: int, offensive_rebounds: int) -> float:
        """
        Calculate estimated possessions.
        
        Formula: FGA + 0.44×FTA + TO - OREB
        """
        try:
            possessions = (
                fg_attempts + 
                (0.44 * ft_attempts) + 
                turnovers - 
                offensive_rebounds
            )
            return round(possessions, 1)
        except:
            return None
    
    def _calculate_true_shooting_pct(self, points: int, fg_attempts: int,
                                    ft_attempts: int) -> float:
        """
        Calculate true shooting percentage.
        
        Formula: PTS / (2 × (FGA + 0.44×FTA))
        """
        try:
            total_shooting_possessions = 2 * (fg_attempts + 0.44 * ft_attempts)
            
            if total_shooting_possessions <= 0:
                return None
            
            ts_pct = points / total_shooting_possessions
            return round(ts_pct, 3)
        except:
            return None
    
    def _calculate_quality_tier(self, shot_zones: dict) -> str:
        """
        Determine data quality tier based on source availability.
        
        HIGH: Team boxscore complete (100%) + shot zones
        MEDIUM: Team boxscore complete (100%) only
        LOW: Incomplete data or missing source
        """
        # Check if boxscore source is missing (None) OR incomplete (< 100)
        if self.source_nbac_boxscore_completeness_pct is None or self.source_nbac_boxscore_completeness_pct < 100:
            return 'low'
        
        # Boxscore is complete (100%), check if shot zones available
        if shot_zones:
            return 'high'
        else:
            return 'medium'
    
    # =========================================================================
    # Stats & Monitoring
    # =========================================================================
    
    def get_analytics_stats(self) -> Dict:
        """Return team offensive analytics stats."""
        if not self.transformed_data:
            return {}
            
        stats = {
            'records_processed': len(self.transformed_data),
            'shot_zones_available': self.shot_zones_available,
            'shot_zones_source': self.shot_zones_source,
            'avg_team_points': round(sum(r['points_scored'] for r in self.transformed_data if r['points_scored']) / 
                                   len([r for r in self.transformed_data if r['points_scored']]), 1) if any(r['points_scored'] for r in self.transformed_data) else 0,
            'total_assists': sum(r['assists'] for r in self.transformed_data if r['assists']),
            'total_turnovers': sum(r['turnovers'] for r in self.transformed_data if r['turnovers']),
            'home_games': sum(1 for r in self.transformed_data if r['home_game']),
            'road_games': sum(1 for r in self.transformed_data if not r['home_game']),
            'high_quality_records': sum(1 for r in self.transformed_data if r['data_quality_tier'] == 'high'),
            'source_completeness': {
                'nbac_boxscore': self.source_nbac_boxscore_completeness_pct,
                'play_by_play': self.source_play_by_play_completeness_pct
            }
        }
        
        return stats
    
    def post_process(self) -> None:
        """Post-processing - send success notification with stats."""
        super().post_process()
        
        # Send success notification
        analytics_stats = self.get_analytics_stats()
        
        try:
            notify_info(
                title="Team Offense: Processing Complete",
                message=f"Successfully processed {analytics_stats.get('records_processed', 0)} team offensive records",
                details={
                    'processor': 'team_offense_game_summary',
                    'date_range': f"{self.opts['start_date']} to {self.opts['end_date']}",
                    'records_processed': analytics_stats.get('records_processed', 0),
                    'avg_team_points': analytics_stats.get('avg_team_points', 0),
                    'offensive_stats': {
                        'total_assists': analytics_stats.get('total_assists', 0),
                        'total_turnovers': analytics_stats.get('total_turnovers', 0)
                    },
                    'game_splits': {
                        'home_games': analytics_stats.get('home_games', 0),
                        'road_games': analytics_stats.get('road_games', 0)
                    },
                    'shot_zones': {
                        'available': analytics_stats.get('shot_zones_available', False),
                        'source': analytics_stats.get('shot_zones_source')
                    },
                    'data_quality': {
                        'high_quality_records': analytics_stats.get('high_quality_records', 0),
                        'source_completeness': analytics_stats.get('source_completeness', {})
                    }
                }
            )
        except Exception as notify_ex:
            logger.warning(f"Failed to send success notification: {notify_ex}")


if __name__ == "__main__":
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(description="Process team offense game summary analytics")
    parser.add_argument('--start-date', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    
    args = parser.parse_args()
    
    # Configure logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    try:
        processor = TeamOffenseGameSummaryProcessor()
        
        # Call run() with options dict
        success = processor.run({
            'start_date': args.start_date,
            'end_date': args.end_date
        })
        
        sys.exit(0 if success else 1)
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)