#!/usr/bin/env python3
"""
Path: data_processors/analytics/upcoming_team_game_context/upcoming_team_game_context_processor.py

Phase 3 Analytics Processor: Upcoming Team Game Context

Purpose:
    Calculate comprehensive team-level context for upcoming games including:
    - Fatigue metrics (days rest, back-to-backs, games in windows)
    - Betting context (spreads, totals, line movement)
    - Personnel availability (injuries, questionable players)
    - Recent performance (streaks, margins, momentum)
    - Travel impact (miles traveled)

Dependencies (Phase 2 Raw Tables):
    1. nba_raw.nbac_schedule (CRITICAL) - Game schedule, matchups, results
    2. nba_raw.odds_api_game_lines (OPTIONAL) - Betting lines
    3. nba_raw.nbac_injury_report (OPTIONAL) - Player availability

Output:
    nba_analytics.upcoming_team_game_context
    - 2 rows per game (home team view + away team view)
    - Typical: ~60 rows per day (30 team-games)

Update Frequency:
    - After Phase 2 schedule updates (2-4 hours)
    - After Phase 2 injury updates (3-5x daily)
    - On-demand for betting line updates

Version: 2.0 - Added dependency tracking, enhanced validation, quality tracking
Last Updated: November 2, 2025
"""

import logging
import os
from datetime import datetime, timedelta, date, timezone
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np
from google.cloud import bigquery

from data_processors.analytics.analytics_base import AnalyticsProcessorBase

# Pattern imports (Week 1 - Foundation Patterns)
from shared.processors.patterns import SmartSkipMixin, EarlyExitMixin, CircuitBreakerMixin
from shared.processors.patterns.quality_columns import build_standard_quality_columns

# Completeness checking (Week 7 - Phase 3 Multi-Window for Teams)
from shared.utils.completeness_checker import CompletenessChecker

logger = logging.getLogger(__name__)


# ============================================================================
# CUSTOM EXCEPTIONS
# ============================================================================

class DependencyError(Exception):
    """Raised when a critical dependency is missing or unavailable."""
    pass


class DataTooStaleError(Exception):
    """Raised when data dependencies are too old to be reliable."""
    pass


class ValidationError(Exception):
    """Raised when data validation fails."""
    pass


class UpcomingTeamGameContextProcessor(
    SmartSkipMixin,
    EarlyExitMixin,
    CircuitBreakerMixin,
    AnalyticsProcessorBase
):
    """
    Calculate team-level game context with comprehensive quality tracking.

    Features:
    - Dependency checking on Phase 2 sources
    - Source metadata tracking (last_updated, rows_found, completeness)
    - Dual-source fallback (nbac_schedule → espn_scoreboard)
    - Extended lookback windows for context calculations
    - Quality issue logging throughout
    """
    
    def __init__(self):
        super().__init__()
        self.table_name = 'nba_analytics.upcoming_team_game_context'
        self.entity_type = 'team_game'
        self.entity_field = 'team_abbr'

        # Initialize BigQuery client
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)

        # Initialize completeness checker (Week 7 - Team Multi-Window)
        self.completeness_checker = CompletenessChecker(self.bq_client, self.project_id)

        # Season start date (for completeness checking - Week 7)
        self.season_start_date = None

        # Data containers
        self.schedule_data: Optional[pd.DataFrame] = None
        self.betting_lines: Optional[pd.DataFrame] = None
        self.injury_data: Optional[pd.DataFrame] = None
        self.travel_distances: Optional[Dict] = None
        
        # Quality tracking
        self.quality_issues: List[Dict] = []
        self.failed_entities: List[Dict] = []
        
        # Source tracking attributes (set by track_source_usage)
        self.source_nbac_schedule_last_updated = None
        self.source_nbac_schedule_rows_found = None
        self.source_nbac_schedule_completeness_pct = None
        self.source_odds_lines_last_updated = None
        self.source_odds_lines_rows_found = None
        self.source_odds_lines_completeness_pct = None
        self.source_injury_report_last_updated = None
        self.source_injury_report_rows_found = None
        self.source_injury_report_completeness_pct = None
        
        # Early season tracking
        self.early_season_flag = False
        self.insufficient_data_reason = None

    # ============================================================
    # Pattern #1: Smart Skip Configuration
    # ============================================================
    RELEVANT_SOURCES = {
        # Schedule sources - RELEVANT (CRITICAL - game timing, matchups)
        'nbacom_schedule': True,
        'espn_scoreboard': True,

        # Game odds sources - RELEVANT (spreads, totals, line movement)
        'odds_api_game_lines': True,
        'odds_api_spreads': True,
        'odds_api_totals': True,

        # Injury/roster sources - RELEVANT (player availability)
        'nbac_injury_report': True,
        'nbacom_roster': True,
        'espn_team_rosters': True,

        # Team boxscore sources - RELEVANT (recent performance, streaks)
        'nbac_team_boxscore': True,
        'bdl_team_boxscores': True,
        'espn_team_stats': True,

        # Player prop sources - NOT RELEVANT (not needed for team context)
        'odds_api_player_points_props': False,
        'bettingpros_player_points_props': False,
        'odds_api_player_rebounds_props': False,
        'odds_api_player_assists_props': False,

        # Individual player boxscores - NOT RELEVANT (not needed for team context)
        'nbac_gamebook_player_stats': False,
        'bdl_player_boxscores': False,
        'nbac_player_boxscores': False,

        # Play-by-play sources - NOT RELEVANT (not needed for pre-game team context)
        'bigdataball_play_by_play': False,
        'nbac_play_by_play': False
    }

    # ============================================================
    # Pattern #3: Early Exit Configuration
    # ============================================================
    ENABLE_NO_GAMES_CHECK = True       # Skip if no games scheduled
    ENABLE_OFFSEASON_CHECK = True      # Skip in July-September
    ENABLE_HISTORICAL_DATE_CHECK = False  # Don't skip - this is for UPCOMING games (future dates)

    # ============================================================
    # Pattern #5: Circuit Breaker Configuration
    # ============================================================
    CIRCUIT_BREAKER_THRESHOLD = 5  # Open after 5 consecutive failures
    CIRCUIT_BREAKER_TIMEOUT = timedelta(minutes=30)  # Stay open 30 minutes

    # ========================================================================
    # DEPENDENCY CONFIGURATION
    # ========================================================================

    def get_dependencies(self) -> dict:
        """
        Define Phase 2 source requirements following Dependency Tracking v4.0.
        
        Returns:
            dict: Dependency configuration for each source table
        """
        return {
            'nba_raw.nbac_schedule': {
                'field_prefix': 'source_nbac_schedule',
                'description': 'Game schedule and matchups',
                'check_type': 'date_range',
                
                # Data requirements
                'expected_count_min': 20,  # ~10 games × 2 teams per day
                
                # Freshness thresholds
                'max_age_hours_warn': 12,  # Warn if schedule >12h old
                'max_age_hours_fail': 36,  # Fail if schedule >36h old
                
                # Early season handling
                'early_season_days': 0,  # No early season for schedule
                'early_season_behavior': 'CONTINUE',
                
                'critical': True  # Cannot process without schedule
            },
            
            'nba_raw.odds_api_game_lines': {
                'field_prefix': 'source_odds_lines',
                'description': 'Betting lines (spreads and totals)',
                'check_type': 'date_range',
                
                # Data requirements (more lenient - optional source)
                'expected_count_min': 40,  # Multiple bookmakers × games
                
                # Freshness thresholds (more strict - lines change fast)
                'max_age_hours_warn': 4,   # Warn if lines >4h old
                'max_age_hours_fail': 12,  # Fail if lines >12h old
                
                'critical': False  # Can process without betting lines
            },
            
            'nba_raw.nbac_injury_report': {
                'field_prefix': 'source_injury_report',
                'description': 'Player injury and availability status',
                'check_type': 'date_range',
                
                # Data requirements (variable by day)
                'expected_count_min': 10,  # 0-50 injured players typical
                
                # Freshness thresholds
                'max_age_hours_warn': 8,   # Warn if report >8h old
                'max_age_hours_fail': 24,  # Fail if report >24h old
                
                'critical': False  # Can process without injury data
            }
        }
    
    # ========================================================================
    # DATA EXTRACTION
    # ========================================================================
    
    def extract_raw_data(self) -> None:
        """
        Extract data from Phase 2 sources with full dependency checking.

        Process:
        1. Check all dependencies (critical and optional)
        2. Handle missing/stale data appropriately
        3. Extract schedule data (CRITICAL)
        4. Extract betting lines (OPTIONAL)
        5. Extract injury reports (OPTIONAL)
        6. Load travel distances (static reference)
        7. Track source usage

        Raises:
            DependencyError: If critical dependencies missing
            DataTooStaleError: If critical dependencies too old

        NEW in v3.0: Smart reprocessing - skip processing if Phase 2 source unchanged.
        """

        logger.info("=" * 80)
        logger.info("PHASE 3: UPCOMING TEAM GAME CONTEXT - EXTRACTION STARTED")
        logger.info("=" * 80)

        # Store season start date for completeness checking (Week 7)
        season_year = self.target_date.year if self.target_date.month >= 10 else self.target_date.year - 1
        self.season_start_date = date(season_year, 10, 1)

        # SMART REPROCESSING: Check if we can skip processing
        skip, reason = self.should_skip_processing(self.target_date)
        if skip:
            logger.info(f"✅ SMART REPROCESSING: Skipping processing - {reason}")
            self.raw_data = []
            return

        logger.info(f"🔄 PROCESSING: {reason}")

        # ====================================================================
        # STEP 1: Check Dependencies
        # ====================================================================
        logger.info("Step 1: Checking dependencies...")
        
        start_date = self.opts.get('start_date')
        end_date = self.opts.get('end_date')
        
        if not start_date or not end_date:
            raise ValueError("start_date and end_date are required")
        
        # Check all dependencies
        dep_check = self.check_dependencies(
            start_date=start_date,
            end_date=end_date
        )
        
        # Log dependency status
        logger.info(f"Dependency check results:")
        logger.info(f"  All critical present: {dep_check['all_critical_present']}")
        logger.info(f"  Has stale warnings: {dep_check.get('has_stale_warn', False)}")
        logger.info(f"  Has stale failures: {dep_check.get('has_stale_fail', False)}")
        
        for table_name, details in dep_check['details'].items():
            status = "✓" if details.get('exists') else "✗"
            logger.info(f"  {status} {table_name}: {details.get('row_count', 0)} rows")
        
        # ====================================================================
        # STEP 2: Handle Critical Failures
        # ====================================================================
        
        # Check critical dependencies
        if not dep_check['all_critical_present']:
            missing = dep_check.get('missing', [])
            error_msg = f"Missing critical dependencies: {', '.join(missing)}"
            logger.error(error_msg)
            
            self.log_quality_issue(
                severity='CRITICAL',
                category='MISSING_DEPENDENCY',
                message=error_msg,
                details={'missing': missing}
            )
            
            raise DependencyError(error_msg)
        
        # Check critical staleness
        if dep_check.get('has_stale_fail'):
            stale = dep_check.get('stale_fail', [])
            error_msg = f"Critical dependencies too stale: {', '.join(stale)}"
            logger.error(error_msg)
            
            self.log_quality_issue(
                severity='CRITICAL',
                category='STALE_DEPENDENCY',
                message=error_msg,
                details={'stale': stale}
            )
            
            raise DataTooStaleError(error_msg)
        
        # ====================================================================
        # STEP 3: Track Source Usage
        # ====================================================================
        logger.info("Step 2: Tracking source usage...")
        
        # Populate source tracking attributes
        self.track_source_usage(dep_check)
        
        # Log source metadata
        logger.info(f"Source Tracking:")
        logger.info(f"  Schedule: {self.source_nbac_schedule_rows_found} rows, "
                   f"{self.source_nbac_schedule_completeness_pct}% complete")
        logger.info(f"  Odds Lines: {self.source_odds_lines_rows_found} rows, "
                   f"{self.source_odds_lines_completeness_pct}% complete")
        logger.info(f"  Injury Report: {self.source_injury_report_rows_found} rows, "
                   f"{self.source_injury_report_completeness_pct}% complete")
        
        # ====================================================================
        # STEP 4: Extract Schedule Data (CRITICAL)
        # ====================================================================
        logger.info("Step 3: Extracting schedule data (CRITICAL)...")
        
        self.schedule_data = self._extract_schedule_data(start_date, end_date)
        
        if self.schedule_data is None or len(self.schedule_data) == 0:
            error_msg = "No schedule data found - cannot continue"
            logger.error(error_msg)
            
            self.log_quality_issue(
                severity='CRITICAL',
                category='NO_DATA',
                message=error_msg,
                details={'date_range': f"{start_date} to {end_date}"}
            )
            
            raise DependencyError(error_msg)
        
        logger.info(f"✓ Extracted {len(self.schedule_data)} schedule records")
        
        # ====================================================================
        # STEP 5: Extract Betting Lines (OPTIONAL)
        # ====================================================================
        logger.info("Step 4: Extracting betting lines (OPTIONAL)...")
        
        self.betting_lines = self._extract_betting_lines(start_date, end_date)
        
        if self.betting_lines is None or len(self.betting_lines) == 0:
            logger.warning("No betting lines available - will continue with NULL spreads/totals")
            self.betting_lines = pd.DataFrame()  # Empty but not None
        else:
            logger.info(f"✓ Extracted {len(self.betting_lines)} betting line records")
        
        # ====================================================================
        # STEP 6: Extract Injury Reports (OPTIONAL)
        # ====================================================================
        logger.info("Step 5: Extracting injury reports (OPTIONAL)...")
        
        self.injury_data = self._extract_injury_data(start_date, end_date)
        
        if self.injury_data is None or len(self.injury_data) == 0:
            logger.warning("No injury data available - will continue with 0 injuries")
            self.injury_data = pd.DataFrame()  # Empty but not None
        else:
            logger.info(f"✓ Extracted {len(self.injury_data)} injury records")
        
        # ====================================================================
        # STEP 7: Load Travel Distances (STATIC)
        # ====================================================================
        logger.info("Step 6: Loading travel distances (STATIC)...")
        
        self.travel_distances = self._load_travel_distances()
        logger.info(f"✓ Loaded {len(self.travel_distances)} travel distance mappings")
        
        logger.info("=" * 80)
        logger.info("EXTRACTION COMPLETE")
        logger.info("=" * 80)
    
    def _extract_schedule_data(
        self, 
        start_date: date, 
        end_date: date
    ) -> pd.DataFrame:
        """
        Extract schedule data with extended lookback window.
        
        Strategy:
        1. Try primary source (nbac_schedule)
        2. If gaps found, backfill from ESPN scoreboard
        3. Use extended window (30 days before, 7 days after)
        
        Args:
            start_date: Start of target date range
            end_date: End of target date range
            
        Returns:
            DataFrame with schedule data or None if extraction fails
        """
        
        # Extended window for context calculations
        extended_start = start_date - timedelta(days=30)  # 30-day lookback
        extended_end = end_date + timedelta(days=7)       # 7-day lookahead
        
        logger.info(f"Extracting schedule: {extended_start} to {extended_end}")
        
        # Primary source: nbac_schedule
        query = f"""
        SELECT 
            game_id,
            game_date,
            season_year,
            home_team_tricode as home_team_abbr,
            away_team_tricode as away_team_abbr,
            game_status,
            home_team_score,
            away_team_score,
            winning_team_tricode as winning_team_abbr,
            data_source,
            processed_at
        FROM `{self.project_id}.nba_raw.nbac_schedule`
        WHERE game_date BETWEEN '{extended_start}' AND '{extended_end}'
          AND game_status IN (1, 3)  -- Scheduled or Final
        ORDER BY game_date, game_id
        """
        
        try:
            schedule_df = self.bq_client.query(query).to_dataframe()
            
            if len(schedule_df) == 0:
                logger.warning("nbac_schedule returned 0 rows")
                return None
            
            logger.info(f"Primary source (nbac_schedule): {len(schedule_df)} games")
            
            # Check for gaps in target date range
            dates_found = set(schedule_df['game_date'].dt.date.unique())
            dates_needed = set(pd.date_range(start_date, end_date).date)
            missing_dates = dates_needed - dates_found
            
            if missing_dates:
                logger.warning(f"Found {len(missing_dates)} missing dates in schedule")
                logger.info(f"Missing dates: {sorted(missing_dates)}")
                
                # Attempt ESPN fallback
                espn_df = self._extract_espn_fallback(list(missing_dates))
                
                if espn_df is not None and len(espn_df) > 0:
                    logger.info(f"ESPN fallback: {len(espn_df)} games")
                    schedule_df = pd.concat([schedule_df, espn_df], ignore_index=True)
                    logger.info(f"Combined total: {len(schedule_df)} games")
            
            return schedule_df
            
        except Exception as e:
            logger.error(f"Error extracting schedule data: {e}")
            self.log_quality_issue(
                severity='ERROR',
                category='EXTRACTION_FAILED',
                message=f"Schedule extraction failed: {str(e)}",
                details={'error_type': type(e).__name__}
            )
            return None
    
    def _extract_espn_fallback(self, missing_dates: List[date]) -> pd.DataFrame:
        """
        Fallback to ESPN scoreboard for missing schedule dates.
        
        Args:
            missing_dates: List of dates missing from nbac_schedule
            
        Returns:
            DataFrame with ESPN data or None if unavailable
        """
        
        if not missing_dates:
            return None
        
        logger.info(f"Attempting ESPN fallback for {len(missing_dates)} dates")
        
        # Format dates for SQL IN clause
        date_list = "', '".join([d.isoformat() for d in missing_dates])
        
        query = f"""
        SELECT 
            game_id,
            game_date,
            season_year,
            home_team_abbr,
            away_team_abbr,
            3 as game_status,  -- Final (ESPN only has completed games)
            home_team_score,
            away_team_score,
            CASE 
                WHEN home_team_winner THEN home_team_abbr
                WHEN away_team_winner THEN away_team_abbr
            END as winning_team_abbr,
            'espn_scoreboard' as data_source,
            processed_at
        FROM `{self.project_id}.nba_raw.espn_scoreboard`
        WHERE game_date IN ('{date_list}')
          AND is_completed = TRUE
          AND game_status = 'final'
        """
        
        try:
            espn_df = self.bq_client.query(query).to_dataframe()
            
            if len(espn_df) > 0:
                logger.info(f"✓ ESPN fallback found {len(espn_df)} games")
            else:
                logger.warning("ESPN fallback returned 0 rows")
            
            return espn_df
            
        except Exception as e:
            logger.warning(f"ESPN fallback failed: {e}")
            return None
    
    def _extract_betting_lines(
        self, 
        start_date: date, 
        end_date: date
    ) -> pd.DataFrame:
        """
        Extract latest betting lines for target date range.
        
        Strategy:
        - Get latest snapshot per game per bookmaker per market
        - Focus on target dates (no extended window needed)
        
        Args:
            start_date: Start of target date range
            end_date: End of target date range
            
        Returns:
            DataFrame with betting lines or None if unavailable
        """
        
        logger.info(f"Extracting betting lines: {start_date} to {end_date}")
        
        query = f"""
        WITH latest_lines AS (
          SELECT *,
            ROW_NUMBER() OVER (
              PARTITION BY game_date, game_id, bookmaker_key, market_key, outcome_name 
              ORDER BY snapshot_timestamp DESC
            ) as rn
          FROM `{self.project_id}.nba_raw.odds_api_game_lines`
          WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        )
        SELECT 
            game_date,
            game_id,
            home_team_abbr,
            away_team_abbr,
            bookmaker_key,
            market_key,
            outcome_name,
            outcome_point,
            outcome_price,
            snapshot_timestamp
        FROM latest_lines
        WHERE rn = 1
        ORDER BY game_date, game_id, market_key
        """
        
        try:
            lines_df = self.bq_client.query(query).to_dataframe()
            
            if len(lines_df) == 0:
                logger.warning("No betting lines found for date range")
                return None
            
            return lines_df
            
        except Exception as e:
            logger.warning(f"Error extracting betting lines: {e}")
            self.log_quality_issue(
                severity='WARNING',
                category='EXTRACTION_FAILED',
                message=f"Betting lines extraction failed: {str(e)}",
                details={'error_type': type(e).__name__}
            )
            return None
    
    def _extract_injury_data(
        self, 
        start_date: date, 
        end_date: date
    ) -> pd.DataFrame:
        """
        Extract latest injury reports for target date range.
        
        Strategy:
        - Get latest report per player per game
        - Focus on target dates
        
        Args:
            start_date: Start of target date range
            end_date: End of target date range
            
        Returns:
            DataFrame with injury data or None if unavailable
        """
        
        logger.info(f"Extracting injury data: {start_date} to {end_date}")
        
        query = f"""
        WITH latest_status AS (
          SELECT *,
            ROW_NUMBER() OVER (
              PARTITION BY game_date, player_lookup 
              ORDER BY report_date DESC, report_hour DESC
            ) as rn
          FROM `{self.project_id}.nba_raw.nbac_injury_report`
          WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        )
        SELECT 
            game_date,
            team,
            player_lookup,
            injury_status,
            reason_category,
            confidence_score
        FROM latest_status
        WHERE rn = 1
          AND confidence_score >= 0.8  -- Only use high-confidence records
        """
        
        try:
            injury_df = self.bq_client.query(query).to_dataframe()
            
            if len(injury_df) == 0:
                logger.warning("No injury data found for date range")
                return None
            
            return injury_df
            
        except Exception as e:
            logger.warning(f"Error extracting injury data: {e}")
            self.log_quality_issue(
                severity='WARNING',
                category='EXTRACTION_FAILED',
                message=f"Injury data extraction failed: {str(e)}",
                details={'error_type': type(e).__name__}
            )
            return None
    
    def _load_travel_distances(self) -> Dict:
        """
        Load travel distance mappings from static table.
        
        Returns:
            Dict mapping "FROM_TO" → distance_miles
        """
        
        query = f"""
        SELECT 
            from_team,
            to_team,
            distance_miles
        FROM `{self.project_id}.nba_static.travel_distances`
        """
        
        try:
            df = self.bq_client.query(query).to_dataframe()
            
            # Build lookup dict
            distances = {}
            for _, row in df.iterrows():
                key = f"{row['from_team']}_{row['to_team']}"
                distances[key] = row['distance_miles']
            
            return distances
            
        except Exception as e:
            logger.warning(f"Error loading travel distances: {e}")
            return {}
    
    # ========================================================================
    # DATA VALIDATION
    # ========================================================================
    
    def validate_extracted_data(self) -> None:
        """
        Validate extracted data quality with comprehensive checks.
        
        Validations:
        1. Schedule data completeness
        2. Date range coverage
        3. Required fields present
        4. Value ranges valid
        5. Team abbreviations valid
        """
        
        logger.info("=" * 80)
        logger.info("VALIDATION STARTED")
        logger.info("=" * 80)
        
        validation_passed = True
        
        # ====================================================================
        # VALIDATION 1: Schedule Data Completeness
        # ====================================================================
        logger.info("Validation 1: Checking schedule data completeness...")
        
        if self.schedule_data is None or len(self.schedule_data) == 0:
            error_msg = "CRITICAL: No schedule data available"
            logger.error(error_msg)
            self.log_quality_issue(
                severity='CRITICAL',
                category='NO_DATA',
                message=error_msg
            )
            raise ValidationError(error_msg)
        
        # Check for required fields
        required_fields = [
            'game_id', 'game_date', 'home_team_abbr', 'away_team_abbr',
            'season_year', 'game_status'
        ]
        
        missing_fields = [f for f in required_fields if f not in self.schedule_data.columns]
        
        if missing_fields:
            error_msg = f"Schedule missing required fields: {missing_fields}"
            logger.error(error_msg)
            self.log_quality_issue(
                severity='CRITICAL',
                category='MISSING_FIELDS',
                message=error_msg,
                details={'missing_fields': missing_fields}
            )
            raise ValidationError(error_msg)
        
        logger.info("✓ Schedule data has all required fields")
        
        # ====================================================================
        # VALIDATION 2: Date Range Coverage
        # ====================================================================
        logger.info("Validation 2: Checking date range coverage...")
        
        start_date = self.opts['start_date']
        end_date = self.opts['end_date']
        
        target_games = self.schedule_data[
            (self.schedule_data['game_date'].dt.date >= start_date) &
            (self.schedule_data['game_date'].dt.date <= end_date)
        ]
        
        if len(target_games) == 0:
            error_msg = f"No games found in target date range: {start_date} to {end_date}"
            logger.error(error_msg)
            self.log_quality_issue(
                severity='CRITICAL',
                category='NO_DATA',
                message=error_msg,
                details={'start_date': str(start_date), 'end_date': str(end_date)}
            )
            raise ValidationError(error_msg)
        
        logger.info(f"✓ Found {len(target_games)} games in target date range")
        
        # Check for date gaps
        dates_found = set(target_games['game_date'].dt.date.unique())
        dates_expected = set(pd.date_range(start_date, end_date).date)
        missing_dates = dates_expected - dates_found
        
        if missing_dates and len(missing_dates) > len(dates_expected) * 0.2:  # >20% missing
            warning_msg = f"Missing {len(missing_dates)} dates (>20% of range)"
            logger.warning(warning_msg)
            self.log_quality_issue(
                severity='WARNING',
                category='INCOMPLETE_DATA',
                message=warning_msg,
                details={'missing_dates': sorted([str(d) for d in missing_dates])}
            )
            validation_passed = False
        
        # ====================================================================
        # VALIDATION 3: Value Ranges
        # ====================================================================
        logger.info("Validation 3: Checking value ranges...")
        
        # Check for NULL game_ids
        null_game_ids = self.schedule_data['game_id'].isnull().sum()
        if null_game_ids > 0:
            error_msg = f"Found {null_game_ids} records with NULL game_id"
            logger.error(error_msg)
            self.log_quality_issue(
                severity='ERROR',
                category='INVALID_DATA',
                message=error_msg,
                details={'null_count': int(null_game_ids)}
            )
            validation_passed = False
        
        # Check for invalid game_status
        valid_statuses = [1, 2, 3]
        invalid_status = self.schedule_data[
            ~self.schedule_data['game_status'].isin(valid_statuses)
        ]
        
        if len(invalid_status) > 0:
            warning_msg = f"Found {len(invalid_status)} games with invalid status"
            logger.warning(warning_msg)
            self.log_quality_issue(
                severity='WARNING',
                category='INVALID_DATA',
                message=warning_msg,
                details={'invalid_count': len(invalid_status)}
            )
        
        logger.info("✓ Value range validation complete")
        
        # ====================================================================
        # VALIDATION 4: Team Abbreviations
        # ====================================================================
        logger.info("Validation 4: Checking team abbreviations...")
        
        # Valid NBA team abbreviations
        valid_teams = {
            'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW',
            'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK',
            'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS'
        }
        
        home_teams = set(self.schedule_data['home_team_abbr'].unique())
        away_teams = set(self.schedule_data['away_team_abbr'].unique())
        all_teams = home_teams.union(away_teams)
        
        invalid_teams = all_teams - valid_teams
        
        if invalid_teams:
            warning_msg = f"Found invalid team abbreviations: {invalid_teams}"
            logger.warning(warning_msg)
            self.log_quality_issue(
                severity='WARNING',
                category='INVALID_DATA',
                message=warning_msg,
                details={'invalid_teams': list(invalid_teams)}
            )
        
        logger.info(f"✓ Found {len(all_teams)} unique teams")
        
        # ====================================================================
        # VALIDATION SUMMARY
        # ====================================================================
        logger.info("=" * 80)
        if validation_passed:
            logger.info("VALIDATION PASSED ✓")
        else:
            logger.warning("VALIDATION PASSED WITH WARNINGS ⚠")
        logger.info("=" * 80)

    # ========================================================================
    # CIRCUIT BREAKER METHODS (Week 7 - Completeness Checking)
    # ========================================================================

    def _check_circuit_breaker(self, entity_id: str, analysis_date: date) -> dict:
        """Check if circuit breaker is active for entity."""
        query = f"""
        SELECT attempt_number, attempted_at, circuit_breaker_tripped, circuit_breaker_until
        FROM `{self.project_id}.nba_orchestration.reprocess_attempts`
        WHERE processor_name = '{self.table_name}'
          AND entity_id = '{entity_id}'
          AND analysis_date = DATE('{analysis_date}')
        ORDER BY attempt_number DESC LIMIT 1
        """
        try:
            result = list(self.bq_client.query(query).result())
            if not result:
                return {'active': False, 'attempts': 0, 'until': None}
            row = result[0]
            if row.circuit_breaker_tripped:
                if row.circuit_breaker_until and datetime.now(timezone.utc) < row.circuit_breaker_until:
                    return {'active': True, 'attempts': row.attempt_number, 'until': row.circuit_breaker_until}
            return {'active': False, 'attempts': row.attempt_number, 'until': None}
        except Exception as e:
            logger.warning(f"Error checking circuit breaker for {entity_id}: {e}")
            return {'active': False, 'attempts': 0, 'until': None}

    def _increment_reprocess_count(self, entity_id: str, analysis_date: date, completeness_pct: float, skip_reason: str) -> None:
        """Track reprocessing attempt and trip circuit breaker if needed."""
        circuit_status = self._check_circuit_breaker(entity_id, analysis_date)
        next_attempt = circuit_status['attempts'] + 1
        circuit_breaker_tripped = next_attempt >= 3
        circuit_breaker_until = None
        if circuit_breaker_tripped:
            circuit_breaker_until = datetime.now(timezone.utc) + timedelta(days=7)
            logger.error(f"{entity_id}: Circuit breaker TRIPPED after {next_attempt} attempts")
        insert_query = f"""
        INSERT INTO `{self.project_id}.nba_orchestration.reprocess_attempts`
        (processor_name, entity_id, analysis_date, attempt_number, attempted_at,
         completeness_pct, skip_reason, circuit_breaker_tripped, circuit_breaker_until,
         manual_override_applied, notes)
        VALUES ('{self.table_name}', '{entity_id}', DATE('{analysis_date}'), {next_attempt},
                CURRENT_TIMESTAMP(), {completeness_pct}, '{skip_reason}', {circuit_breaker_tripped},
                {'TIMESTAMP("' + circuit_breaker_until.isoformat() + '")' if circuit_breaker_until else 'NULL'},
                FALSE, 'Attempt {next_attempt}: {completeness_pct:.1f}% complete')
        """
        try:
            self.bq_client.query(insert_query).result()
        except Exception as e:
            logger.warning(f"Failed to record reprocess attempt for {entity_id}: {e}")

    # ========================================================================
    # DATA TRANSFORMATION
    # ========================================================================

    def calculate_analytics(self) -> None:
        """
        Calculate team game context with comprehensive tracking.
        
        Process:
        1. Identify target games
        2. For each game, create 2 records (home + away view)
        3. Calculate all context metrics
        4. Include source tracking
        5. Handle failures gracefully
        """
        
        logger.info("=" * 80)
        logger.info("ANALYTICS CALCULATION STARTED")
        logger.info("=" * 80)
        
        successful_records = []
        failed_count = 0
        
        # Get target games
        start_date = self.opts['start_date']
        end_date = self.opts['end_date']
        
        target_games = self.schedule_data[
            (self.schedule_data['game_date'].dt.date >= start_date) &
            (self.schedule_data['game_date'].dt.date <= end_date)
        ].copy()

        logger.info(f"Processing {len(target_games)} games ({len(target_games) * 2} team-game records)")

        # ============================================================
        # NEW (Week 7): Batch completeness checking for ALL teams (2 windows)
        # ============================================================
        # Collect all unique teams from games
        all_teams = set(target_games['home_team_abbr'].tolist() + target_games['away_team_abbr'].tolist())

        logger.info(f"Checking completeness for {len(all_teams)} teams across 2 windows...")

        # Window 1: L7 days
        comp_l7d = self.completeness_checker.check_completeness_batch(
            entity_ids=list(all_teams),
            entity_type='team',
            analysis_date=end_date,  # Use end_date for consistency
            upstream_table='nba_raw.nbac_schedule',
            upstream_entity_field='home_team_abbr',  # Schedule uses home/away, checker will handle
            lookback_window=7,
            window_type='days',
            season_start_date=self.season_start_date
        )

        # Window 2: L14 days
        comp_l14d = self.completeness_checker.check_completeness_batch(
            entity_ids=list(all_teams),
            entity_type='team',
            analysis_date=end_date,
            upstream_table='nba_raw.nbac_schedule',
            upstream_entity_field='home_team_abbr',
            lookback_window=14,
            window_type='days',
            season_start_date=self.season_start_date
        )

        # Check bootstrap mode
        is_bootstrap = self.completeness_checker.is_bootstrap_mode(
            end_date, self.season_start_date
        )
        is_season_boundary = self.completeness_checker.is_season_boundary(end_date)

        logger.info(
            f"Completeness check complete. Bootstrap mode: {is_bootstrap}, "
            f"Season boundary: {is_season_boundary}"
        )
        # ============================================================

        # Process each game
        for idx, game in target_games.iterrows():
            try:
                # Create home team record
                home_record = self._calculate_team_game_context(
                    game=game,
                    team_abbr=game['home_team_abbr'],
                    opponent_abbr=game['away_team_abbr'],
                    home_game=True,
                    comp_l7d=comp_l7d,
                    comp_l14d=comp_l14d,
                    is_bootstrap=is_bootstrap,
                    is_season_boundary=is_season_boundary
                )

                if home_record:
                    successful_records.append(home_record)
                else:
                    failed_count += 1

                # Create away team record
                away_record = self._calculate_team_game_context(
                    game=game,
                    team_abbr=game['away_team_abbr'],
                    opponent_abbr=game['home_team_abbr'],
                    home_game=False,
                    comp_l7d=comp_l7d,
                    comp_l14d=comp_l14d,
                    is_bootstrap=is_bootstrap,
                    is_season_boundary=is_season_boundary
                )
                
                if away_record:
                    successful_records.append(away_record)
                else:
                    failed_count += 1
                    
            except Exception as e:
                logger.error(f"Error processing game {game.get('game_id')}: {e}")
                self.log_quality_issue(
                    severity='ERROR',
                    category='PROCESSING_ERROR',
                    message=f"Failed to process game: {str(e)}",
                    details={
                        'game_id': game.get('game_id'),
                        'error_type': type(e).__name__
                    }
                )
                failed_count += 2  # Both home and away failed
                continue
        
        self.transformed_data = successful_records
        
        logger.info("=" * 80)
        logger.info(f"CALCULATION COMPLETE:")
        logger.info(f"  ✓ Successful: {len(successful_records)} team-game records")
        logger.info(f"  ✗ Failed: {failed_count} team-game records")
        logger.info("=" * 80)
    
    def _calculate_team_game_context(
        self,
        game: pd.Series,
        team_abbr: str,
        opponent_abbr: str,
        home_game: bool,
        comp_l7d: Dict,
        comp_l14d: Dict,
        is_bootstrap: bool,
        is_season_boundary: bool
    ) -> Optional[Dict]:
        """
        Calculate complete context for one team-game.

        Args:
            game: Game record from schedule
            team_abbr: Team to calculate context for
            opponent_abbr: Opposing team
            home_game: True if team is home
            comp_l7d: L7d completeness results for all teams
            comp_l14d: L14d completeness results for all teams
            is_bootstrap: Whether in bootstrap mode
            is_season_boundary: Whether at season boundary

        Returns:
            Dict with all context fields (including 19 completeness metadata fields) or None if calculation fails
        """
        
        try:
            # Start with business keys
            record = {
                'team_abbr': team_abbr,
                'game_id': game['game_id'],
                'game_date': game['game_date'].date().isoformat(),
                'season_year': int(game['season_year']),
                'opponent_team_abbr': opponent_abbr,
                'home_game': bool(home_game)
            }
            
            # Calculate each context type
            basic_context = self._calculate_basic_context(game, team_abbr, home_game)
            fatigue_context = self._calculate_fatigue_context(game, team_abbr)
            betting_context = self._calculate_betting_context(game, team_abbr, home_game)
            personnel_context = self._calculate_personnel_context(game, team_abbr)
            momentum_context = self._calculate_momentum_context(game, team_abbr)
            travel_context = self._calculate_travel_context(game, team_abbr, home_game, fatigue_context)
            
            # Merge all contexts
            record.update(basic_context)
            record.update(fatigue_context)
            record.update(betting_context)
            record.update(personnel_context)
            record.update(momentum_context)
            record.update(travel_context)
            
            # Add source tracking (one line!)
            record.update(self.build_source_tracking_fields())

            # ============================================================
            # NEW (Week 7): Completeness Checking Metadata (19 fields)
            # ============================================================
            # Get completeness for this team
            default_comp = {
                'expected_count': 0, 'actual_count': 0, 'completeness_pct': 0.0,
                'missing_count': 0, 'is_complete': False, 'is_production_ready': False
            }

            completeness_l7d = comp_l7d.get(team_abbr, default_comp)
            completeness_l14d = comp_l14d.get(team_abbr, default_comp)

            # Check circuit breaker (entity_id is team_abbr+game_date for uniqueness)
            entity_id = f"{team_abbr}_{game['game_date'].date()}"
            circuit_breaker_status = self._check_circuit_breaker(entity_id, game['game_date'].date())

            # Completeness Metrics (use L14d as primary - longer window)
            record['expected_games_count'] = completeness_l14d['expected_count']
            record['actual_games_count'] = completeness_l14d['actual_count']
            record['completeness_percentage'] = completeness_l14d['completeness_pct']
            record['missing_games_count'] = completeness_l14d['missing_count']

            # Build quality columns using centralized helper
            # Determine tier based on completeness
            if completeness_l14d['completeness_pct'] >= 95:
                tier = 'gold'
                score = 95.0
            elif completeness_l14d['completeness_pct'] >= 75:
                tier = 'silver'
                score = 75.0
            elif completeness_l14d['completeness_pct'] >= 50:
                tier = 'bronze'
                score = 50.0
            else:
                tier = 'poor'
                score = 25.0

            # Build issues list
            quality_issues = []
            if not completeness_l7d['is_complete']:
                quality_issues.append(f"l7d_incomplete:{completeness_l7d['completeness_pct']:.0f}%")
            if not completeness_l14d['is_complete']:
                quality_issues.append(f"l14d_incomplete:{completeness_l14d['completeness_pct']:.0f}%")
            if is_season_boundary:
                quality_issues.append('season_boundary')
            if is_bootstrap:
                quality_issues.append('bootstrap_mode')

            # Production Readiness (both windows must be ready)
            is_prod_ready = (
                completeness_l7d['is_production_ready'] and
                completeness_l14d['is_production_ready']
            )

            # Use centralized helper
            quality_cols = build_standard_quality_columns(
                tier=tier,
                score=score,
                issues=quality_issues,
                sources=['nbac_schedule'],
                is_production_ready=is_prod_ready,
            )
            record.update(quality_cols)
            record['data_quality_issues'] = quality_issues  # Legacy field

            # Circuit Breaker
            record['last_reprocess_attempt_at'] = None  # Would need separate query
            record['reprocess_attempt_count'] = circuit_breaker_status['attempts']
            record['circuit_breaker_active'] = circuit_breaker_status['active']
            record['circuit_breaker_until'] = (
                circuit_breaker_status['until'].isoformat()
                if circuit_breaker_status['until'] else None
            )

            # Bootstrap/Override
            record['manual_override_required'] = False
            record['season_boundary_detected'] = is_season_boundary
            record['backfill_bootstrap_mode'] = is_bootstrap
            record['processing_decision_reason'] = 'processed_successfully'

            # Multi-Window Completeness (5 fields)
            record['l7d_completeness_pct'] = completeness_l7d['completeness_pct']
            record['l7d_is_complete'] = completeness_l7d['is_complete']
            record['l14d_completeness_pct'] = completeness_l14d['completeness_pct']
            record['l14d_is_complete'] = completeness_l14d['is_complete']
            record['all_windows_complete'] = (
                completeness_l7d['is_complete'] and
                completeness_l14d['is_complete']
            )
            # ============================================================

            # Add processing metadata
            record['processed_at'] = datetime.now(timezone.utc).isoformat()
            record['created_at'] = datetime.now(timezone.utc).isoformat()

            return record
            
        except Exception as e:
            logger.error(f"Error calculating context for {team_abbr} in game {game['game_id']}: {e}")
            return None
    
    def _calculate_basic_context(
        self,
        game: pd.Series,
        team_abbr: str,
        home_game: bool
    ) -> Dict:
        """Calculate basic game context fields."""
        
        return {
            'is_back_to_back': False,  # Will be set in fatigue calculation
            'days_since_last_game': None,  # Will be set in fatigue calculation
            'game_number_in_season': None  # Will be set in fatigue calculation
        }
    
    def _calculate_fatigue_context(
        self,
        game: pd.Series,
        team_abbr: str
    ) -> Dict:
        """
        Calculate fatigue metrics using team's recent schedule.
        
        Metrics:
        - team_days_rest: Days since last game
        - team_back_to_back: Boolean for consecutive days
        - games_in_last_7_days: Count
        - games_in_last_14_days: Count
        """
        
        game_date = game['game_date']
        
        # Get team's games before this one
        team_games = self.schedule_data[
            (
                (self.schedule_data['home_team_abbr'] == team_abbr) |
                (self.schedule_data['away_team_abbr'] == team_abbr)
            ) &
            (self.schedule_data['game_date'] < game_date) &
            (self.schedule_data['game_status'] == 3)  # Only completed games
        ].sort_values('game_date')
        
        if len(team_games) == 0:
            # First game of season
            return {
                'team_days_rest': None,
                'team_back_to_back': False,
                'games_in_last_7_days': 0,
                'games_in_last_14_days': 0,
                'is_back_to_back': False,
                'days_since_last_game': None,
                'game_number_in_season': 1
            }
        
        # Last game date
        last_game_date = team_games.iloc[-1]['game_date']
        days_rest = (game_date - last_game_date).days - 1  # Subtract 1 (0 = back-to-back)
        is_b2b = days_rest == 0
        
        # Games in windows
        seven_days_ago = game_date - timedelta(days=7)
        fourteen_days_ago = game_date - timedelta(days=14)
        
        games_last_7 = len(team_games[team_games['game_date'] > seven_days_ago])
        games_last_14 = len(team_games[team_games['game_date'] > fourteen_days_ago])
        
        return {
            'team_days_rest': int(days_rest),
            'team_back_to_back': bool(is_b2b),
            'games_in_last_7_days': int(games_last_7),
            'games_in_last_14_days': int(games_last_14),
            'is_back_to_back': bool(is_b2b),
            'days_since_last_game': int((game_date - last_game_date).days),
            'game_number_in_season': int(len(team_games) + 1)
        }
    
    def _calculate_betting_context(
        self,
        game: pd.Series,
        team_abbr: str,
        home_game: bool
    ) -> Dict:
        """
        Calculate betting context from odds API data.
        
        Handles team name mapping: "Los Angeles Lakers" → "LAL"
        """
        
        if self.betting_lines is None or len(self.betting_lines) == 0:
            return {
                'game_spread': None,
                'game_total': None,
                'game_spread_source': None,
                'game_total_source': None,
                'spread_movement': None,
                'total_movement': None,
                'betting_lines_updated_at': None
            }
        
        game_date = game['game_date'].date()
        game_id = game.get('game_id')
        
        # Filter lines for this game
        game_lines = self.betting_lines[
            (self.betting_lines['game_date'] == game_date)
        ]
        
        # Additional filtering by game_id if available
        if game_id and 'game_id' in game_lines.columns:
            game_lines = game_lines[game_lines['game_id'] == game_id]
        
        if len(game_lines) == 0:
            return {
                'game_spread': None,
                'game_total': None,
                'game_spread_source': None,
                'game_total_source': None,
                'spread_movement': None,
                'total_movement': None,
                'betting_lines_updated_at': None
            }
        
        # Prioritize DraftKings, fallback to FanDuel
        preferred_books = ['draftkings', 'fanduel']
        
        spread = None
        spread_source = None
        total = None
        total_source = None
        lines_timestamp = None
        
        for bookmaker in preferred_books:
            book_lines = game_lines[game_lines['bookmaker_key'] == bookmaker]
            
            if len(book_lines) == 0:
                continue
            
            # Get spread
            if spread is None:
                spread_lines = book_lines[book_lines['market_key'] == 'spreads']
                
                for _, line in spread_lines.iterrows():
                    outcome_name = line['outcome_name']
                    
                    # Map team name to abbreviation
                    if self._team_name_matches(outcome_name, team_abbr):
                        spread = float(line['outcome_point'])
                        spread_source = bookmaker
                        lines_timestamp = line['snapshot_timestamp']
                        break
            
            # Get total
            if total is None:
                total_lines = book_lines[book_lines['market_key'] == 'totals']
                over_lines = total_lines[total_lines['outcome_name'] == 'Over']
                
                if len(over_lines) > 0:
                    total = float(over_lines.iloc[0]['outcome_point'])
                    total_source = bookmaker
                    if lines_timestamp is None:
                        lines_timestamp = over_lines.iloc[0]['snapshot_timestamp']
            
            # Stop if we found both
            if spread is not None and total is not None:
                break
        
        return {
            'game_spread': spread,
            'game_total': total,
            'game_spread_source': spread_source,
            'game_total_source': total_source,
            'spread_movement': None,  # TODO: Implement with opening line tracking
            'total_movement': None,   # TODO: Implement with opening line tracking
            'betting_lines_updated_at': lines_timestamp.isoformat() if lines_timestamp else None
        }
    
    def _team_name_matches(self, outcome_name: str, team_abbr: str) -> bool:
        """
        Check if betting line outcome name matches team abbreviation.
        
        Handles mapping: "Los Angeles Lakers" → "LAL"
        """
        
        # Team name mapping
        TEAM_NAME_MAP = {
            'Atlanta Hawks': 'ATL',
            'Boston Celtics': 'BOS',
            'Brooklyn Nets': 'BKN',
            'Charlotte Hornets': 'CHA',
            'Chicago Bulls': 'CHI',
            'Cleveland Cavaliers': 'CLE',
            'Dallas Mavericks': 'DAL',
            'Denver Nuggets': 'DEN',
            'Detroit Pistons': 'DET',
            'Golden State Warriors': 'GSW',
            'Houston Rockets': 'HOU',
            'Indiana Pacers': 'IND',
            'LA Clippers': 'LAC',
            'Los Angeles Clippers': 'LAC',
            'Los Angeles Lakers': 'LAL',
            'Memphis Grizzlies': 'MEM',
            'Miami Heat': 'MIA',
            'Milwaukee Bucks': 'MIL',
            'Minnesota Timberwolves': 'MIN',
            'New Orleans Pelicans': 'NOP',
            'New York Knicks': 'NYK',
            'Oklahoma City Thunder': 'OKC',
            'Orlando Magic': 'ORL',
            'Philadelphia 76ers': 'PHI',
            'Phoenix Suns': 'PHX',
            'Portland Trail Blazers': 'POR',
            'Sacramento Kings': 'SAC',
            'San Antonio Spurs': 'SAS',
            'Toronto Raptors': 'TOR',
            'Utah Jazz': 'UTA',
            'Washington Wizards': 'WAS'
        }
        
        # Strategy 1: Exact abbreviation match
        if outcome_name == team_abbr:
            return True
        
        # Strategy 2: Full name mapping
        if outcome_name in TEAM_NAME_MAP:
            return TEAM_NAME_MAP[outcome_name] == team_abbr
        
        # Strategy 3: Contains abbreviation
        if team_abbr in outcome_name:
            return True
        
        return False
    
    def _calculate_personnel_context(
        self,
        game: pd.Series,
        team_abbr: str
    ) -> Dict:
        """
        Calculate personnel availability from injury reports.
        """
        
        if self.injury_data is None or len(self.injury_data) == 0:
            return {
                'starters_out_count': 0,
                'questionable_players_count': 0
            }
        
        game_date = game['game_date'].date()
        
        # Get team's injury data for this game
        team_injuries = self.injury_data[
            (self.injury_data['game_date'] == game_date) &
            (self.injury_data['team'] == team_abbr)
        ]
        
        if len(team_injuries) == 0:
            return {
                'starters_out_count': 0,
                'questionable_players_count': 0
            }
        
        # Count by status
        out_count = len(team_injuries[team_injuries['injury_status'] == 'out'])
        questionable_count = len(team_injuries[
            team_injuries['injury_status'].isin(['questionable', 'doubtful'])
        ])
        
        return {
            'starters_out_count': int(out_count),
            'questionable_players_count': int(questionable_count)
        }
    
    def _calculate_momentum_context(
        self,
        game: pd.Series,
        team_abbr: str
    ) -> Dict:
        """
        Calculate recent performance and momentum.
        """
        
        game_date = game['game_date']
        
        # Get team's completed games before this one
        team_games = self.schedule_data[
            (
                (self.schedule_data['home_team_abbr'] == team_abbr) |
                (self.schedule_data['away_team_abbr'] == team_abbr)
            ) &
            (self.schedule_data['game_date'] < game_date) &
            (self.schedule_data['game_status'] == 3) &  # Final
            (self.schedule_data['winning_team_abbr'].notna())  # Has result
        ].sort_values('game_date', ascending=False)
        
        if len(team_games) == 0:
            return {
                'team_win_streak_entering': 0,
                'team_loss_streak_entering': 0,
                'last_game_margin': None,
                'last_game_result': None
            }
        
        # Last game result
        last_game = team_games.iloc[0]
        last_game_winner = last_game['winning_team_abbr']
        last_game_won = last_game_winner == team_abbr
        
        # Calculate margin
        if pd.notna(last_game['home_team_score']) and pd.notna(last_game['away_team_score']):
            if last_game['home_team_abbr'] == team_abbr:
                margin = int(last_game['home_team_score'] - last_game['away_team_score'])
            else:
                margin = int(last_game['away_team_score'] - last_game['home_team_score'])
        else:
            margin = None
        
        # Calculate streaks
        win_streak = 0
        loss_streak = 0
        
        for _, g in team_games.iterrows():
            winner = g['winning_team_abbr']
            if pd.isna(winner):
                break
            
            if winner == team_abbr:
                if loss_streak > 0:
                    break
                win_streak += 1
            else:
                if win_streak > 0:
                    break
                loss_streak += 1
        
        return {
            'team_win_streak_entering': int(win_streak),
            'team_loss_streak_entering': int(loss_streak),
            'last_game_margin': margin,
            'last_game_result': 'W' if last_game_won else 'L'
        }
    
    def _calculate_travel_context(
        self,
        game: pd.Series,
        team_abbr: str,
        home_game: bool,
        fatigue_context: Dict
    ) -> Dict:
        """
        Calculate travel distance to this game.
        """
        
        if home_game:
            return {'travel_miles': 0}
        
        # For away games, need last opponent location
        game_date = game['game_date']
        
        team_games = self.schedule_data[
            (
                (self.schedule_data['home_team_abbr'] == team_abbr) |
                (self.schedule_data['away_team_abbr'] == team_abbr)
            ) &
            (self.schedule_data['game_date'] < game_date)
        ].sort_values('game_date')
        
        if len(team_games) == 0:
            return {'travel_miles': 0}
        
        # Last game location
        last_game = team_games.iloc[-1]
        if last_game['home_team_abbr'] == team_abbr:
            last_location = team_abbr  # Was at home
        else:
            last_location = last_game['home_team_abbr']  # Was at opponent's arena
        
        # Current game location (opponent's arena for away game)
        current_location = game['home_team_abbr']
        
        # Lookup travel distance
        travel_key = f"{last_location}_{current_location}"
        travel_miles = self.travel_distances.get(travel_key, 0)
        
        return {'travel_miles': int(travel_miles)}
    
    # ========================================================================
    # HELPER METHODS
    # ========================================================================
    
    def log_quality_issue(
        self,
        severity: str,
        category: str,
        message: str,
        details: Optional[Dict] = None
    ) -> None:
        """
        Log a data quality issue for monitoring.
        
        Args:
            severity: 'CRITICAL', 'ERROR', 'WARNING', 'INFO'
            category: Issue category
            message: Human-readable description
            details: Additional context
        """
        
        issue = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'severity': severity,
            'category': category,
            'message': message,
            'details': details or {}
        }
        
        self.quality_issues.append(issue)
        
        # Also log to standard logger
        log_method = {
            'CRITICAL': logger.critical,
            'ERROR': logger.error,
            'WARNING': logger.warning,
            'INFO': logger.info
        }.get(severity, logger.info)
        
        log_method(f"[{category}] {message}")
    
    # ========================================================================
    # SAVE LOGIC
    # ========================================================================
    
    def save_analytics(self) -> bool:
        """
        Save results using MERGE strategy.
        
        Returns:
            True if save successful, False otherwise
        """
        
        if not self.transformed_data:
            logger.warning("No data to save")
            return True
        
        logger.info("=" * 80)
        logger.info("SAVING TO BIGQUERY")
        logger.info("=" * 80)
        
        try:
            # MERGE: Update existing rows or insert new ones
            table_id = f"{self.project_id}.{self.table_name}"
            
            # Delete existing records for this date range first
            start_date = self.opts['start_date']
            end_date = self.opts['end_date']
            
            delete_query = f"""
            DELETE FROM `{table_id}`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
            """
            
            logger.info(f"Deleting existing records: {start_date} to {end_date}")
            self.bq_client.query(delete_query).result()
            
            # Insert new records using batch loading (not streaming insert)
            # This avoids the 20 DML limit and streaming buffer issues
            logger.info(f"Loading {len(self.transformed_data)} records using batch load")

            # Get table schema for load job
            table = self.bq_client.get_table(table_id)

            # Configure batch load job
            job_config = bigquery.LoadJobConfig(
                schema=table.schema,
                autodetect=False,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED
            )

            # Load using batch job
            load_job = self.bq_client.load_table_from_json(
                self.transformed_data,
                table_id,
                job_config=job_config
            )

            # Wait for completion
            load_job.result()
            logger.info(f"Successfully loaded {len(self.transformed_data)} records")
            logger.info("=" * 80)
            return True
            
        except Exception as e:
            logger.error(f"Error saving data: {e}")
            return False


# ============================================================================
# ENTRY POINT
# ============================================================================

def main():
    """
    Main entry point for processor.

    Usage:
        python processor.py --start_date=2024-11-01 --end_date=2024-11-07
    """
    import argparse

    parser = argparse.ArgumentParser(description='Upcoming Team Game Context Processor')
    parser.add_argument('--start_date', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end_date', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    parser.add_argument(
        '--skip-downstream-trigger',
        action='store_true',
        help='Disable Pub/Sub trigger to Phase 4 (for backfills)'
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Parse dates
    from datetime import datetime as dt
    start_date = dt.strptime(args.start_date, '%Y-%m-%d').date()
    end_date = dt.strptime(args.end_date, '%Y-%m-%d').date()

    # Create and run processor
    processor = UpcomingTeamGameContextProcessor()
    processor.opts = {
        'start_date': start_date,
        'end_date': end_date,
        'skip_downstream_trigger': args.skip_downstream_trigger
    }
    
    try:
        # Run processing pipeline
        processor.extract_raw_data()
        processor.validate_extracted_data()
        processor.calculate_analytics()
        success = processor.save_analytics()
        
        # Print summary
        print("\n" + "=" * 80)
        print("PROCESSING COMPLETE")
        print("=" * 80)
        print(f"Records saved: {len(processor.transformed_data)}")
        print(f"Quality issues: {len(processor.quality_issues)}")
        print(f"Status: {'SUCCESS' if success else 'FAILED'}")
        print("=" * 80)
        
        return 0 if success else 1
        
    except Exception as e:
        logger.error(f"Processing failed: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    import sys
    sys.exit(main())