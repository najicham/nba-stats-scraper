#!/usr/bin/env python3
# File: validation/validators/raw/odds_game_lines_validator.py
"""
Odds API Game Lines Validator v2

NEW FEATURES:
- Team-specific validation via --team CLI argument
- GCS file validation with schedule cross-check
- Playoff game detection and validation

Validates odds data from DraftKings and FanDuel for NBA game lines (spreads and totals).
Includes cross-validation with NBA Schedule Service to detect API scraper failures.

Usage:
    # Last 7 days (default summary output)
    python -m validation.validators.raw.odds_game_lines_validator --last-days 7
    
    # Specific team validation (Clippers)
    python -m validation.validators.raw.odds_game_lines_validator \
        --start-date 2024-04-01 --end-date 2024-06-30 \
        --team "LA Clippers"
    
    # Check GCS files (includes playoffs)
    python -m validation.validators.raw.odds_game_lines_validator \
        --start-date 2024-04-01 --end-date 2024-06-30 \
        --check-gcs
    
    # Full validation with all features
    python -m validation.validators.raw.odds_game_lines_validator \
        --start-date 2024-04-01 --end-date 2024-06-30 \
        --team "LA Clippers" \
        --check-gcs \
        --output detailed
"""

import os
import sys
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple
import argparse
import logging

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from validation.base_validator import BaseValidator, ValidationResult, ValidationSeverity
from google.cloud import storage

# Try to import NBA Schedule Service for cross-validation
try:
    from shared.utils.schedule import NBAScheduleService
    SCHEDULE_SERVICE_AVAILABLE = True
except ImportError:
    SCHEDULE_SERVICE_AVAILABLE = False
    logging.warning("NBA Schedule Service not available - cross-validation will be limited")

# Try to import NBATeamMapper for robust team filtering
try:
    from shared.utils.nba_team_mapper import NBATeamMapper
    TEAM_MAPPER_AVAILABLE = True
except ImportError:
    TEAM_MAPPER_AVAILABLE = False
    logging.warning("NBATeamMapper not available - team filtering will be basic")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class OddsGameLinesValidator(BaseValidator):
    """
    Validator for Odds API game lines data
    
    NEW v2 Features:
    - Team-specific filtering
    - GCS file validation
    - Playoff game detection
    
    Validates:
    - Game completeness (8 rows per game)
    - Bookmaker coverage (DraftKings + FanDuel)
    - Market coverage (spreads + totals)
    - Data value ranges
    - Team name validity
    - Cross-validation with NBA Schedule Service
    - GCS file presence (including playoffs)
    """
    
    def __init__(self, config_path: str = None, team_filter: Optional[str] = None, check_gcs: bool = False):
        """
        Initialize validator
        
        Args:
            config_path: Path to config file (default: auto-detect)
            team_filter: Filter validations to specific team (e.g., "LA Clippers", "LAC", "Clippers")
            check_gcs: Enable GCS file validation
        """
        if config_path is None:
            config_path = project_root / "validation" / "configs" / "raw" / "odds_game_lines.yaml"
        
        super().__init__(config_path)
        
        # NEW: Team filter with NBATeamMapper normalization
        self.team_filter = None
        self.team_filter_normalized = None
        if team_filter:
            if TEAM_MAPPER_AVAILABLE:
                # Use team mapper to normalize team name
                team_mapper = NBATeamMapper(use_database=False)
                normalized = team_mapper.get_team_full_name(team_filter)
                if normalized:
                    self.team_filter = team_filter
                    self.team_filter_normalized = normalized
                    logger.info(f"🎯 Team filter enabled: '{team_filter}' → '{normalized}'")
                else:
                    logger.warning(f"⚠️  Team filter '{team_filter}' not recognized, validation will include all teams")
            else:
                # Fallback: use raw filter
                self.team_filter = team_filter
                self.team_filter_normalized = team_filter
                logger.info(f"🎯 Team filter enabled: {team_filter} (basic mode)")
        
        # NEW: GCS validation flag
        self.check_gcs = check_gcs
        if check_gcs:
            logger.info(f"📦 GCS file validation enabled")
        
        # Initialize schedule service if available
        self.schedule_service = None
        self.schedule_service_enabled = False
        
        if SCHEDULE_SERVICE_AVAILABLE and self.config.get('schedule_service', {}).get('enabled', False):
            try:
                self.schedule_service = NBAScheduleService()
                self.schedule_service_enabled = True
                logger.info("✅ NBA Schedule Service: ENABLED")
            except Exception as e:
                logger.warning(f"⚠️  NBA Schedule Service: DISABLED ({str(e)})")
        else:
            logger.info("⚠️  NBA Schedule Service: DISABLED (using basic checks only)")
    
    # ========================================================================
    # CRITICAL FIX: Method signature must match base class
    # ========================================================================
    def _run_custom_validations(self, start_date: str, end_date: str, season_year: Optional[int]):
        """
        Run odds-specific custom validations (overrides base class method)
        
        Args:
            start_date: Start date for validation
            end_date: End date for validation
            season_year: Season year (optional)
        """
        logger.info("Running Odds API custom validations...")
        
        # NEW: GCS file validation (if enabled)
        if self.check_gcs:
            self.results.append(self._validate_gcs_files())
        
        # 1. Game completeness check
        self.results.append(self._validate_game_completeness())
        
        # 2. Bookmaker coverage
        self.results.append(self._validate_bookmaker_coverage())
        
        # 3. Market coverage
        self.results.append(self._validate_market_coverage())
        
        # 4. Spread reasonableness
        self.results.append(self._validate_spread_ranges())
        
        # 5. Totals reasonableness
        self.results.append(self._validate_totals_ranges())
        
        # 6. Team name consistency
        self.results.append(self._validate_team_names())
        
        # 7. Odds timing
        self.results.append(self._validate_odds_timing())
        
        # 8. Schedule service cross-validation (if enabled)
        if self.schedule_service_enabled:
            self.results.append(self._validate_against_schedule())
        
        logger.info("Completed Odds API custom validations")
    
    # ========================================================================
    # NEW: GCS File Validation with Schedule Service
    # ========================================================================
    def _validate_gcs_files(self) -> ValidationResult:
        """
        Validate GCS files exist for all games in schedule (INCLUDING PLAYOFFS!)
        
        Uses Schedule Service to get expected games, then checks GCS.
        This is the ROOT CAUSE detector - if GCS file missing, scraper didn't run!
        
        Returns:
            ValidationResult with missing GCS files
        """
        if not self.schedule_service:
            return ValidationResult(
                check_name="gcs_file_validation",
                check_type="custom",
                layer="GCS",
                passed=True,
                severity=ValidationSeverity.INFO.value,
                message="Schedule service not available - skipping GCS validation"
            )
        
        logger.info("Validating GCS files using Schedule Service...")
        
        # Get GCS config
        gcs_config = self.config.get('gcs', {})
        bucket_name = gcs_config.get('bucket', 'nba-scraped-data')
        prefix = gcs_config.get('prefix', 'odds-api/game-lines-history')
        
        try:
            from shared.utils.schedule import GameType
            
            # Get all game dates in range using Schedule Service
            current_date = datetime.strptime(self.start_date, '%Y-%m-%d').date()
            end_date_obj = datetime.strptime(self.end_date, '%Y-%m-%d').date()
            
            storage_client = storage.Client()
            bucket = storage_client.bucket(bucket_name)
            
            missing_files = []
            missing_playoff_games = []
            total_games_checked = 0
            
            while current_date <= end_date_obj:
                date_str = current_date.isoformat()
                
                # Use Schedule Service to get games for this date
                games = self.schedule_service.get_games_for_date(
                    game_date=date_str,
                    game_type=GameType.REGULAR_PLAYOFF  # Regular season + playoffs
                )
                
                # Apply team filter if specified
                if self.team_filter_normalized:
                    games = [g for g in games if 
                            self.team_filter_normalized == g.home_team_full or 
                            self.team_filter_normalized == g.away_team_full]
                
                if games:
                    total_games_checked += len(games)
                    
                    # Check if GCS files exist for this date
                    date_prefix = f"{prefix}/{date_str}/"
                    blobs = list(bucket.list_blobs(prefix=date_prefix, max_results=5))
                    
                    if not blobs:
                        # No files for this date - all games missing!
                        for game in games:
                            game_info = {
                                'date': date_str,
                                'game_id': game.game_id,
                                'matchup': game.matchup,
                                'full_matchup': f"{game.away_team_full} @ {game.home_team_full}",
                                'is_playoff': game.is_playoff,
                                'game_label': game.game_label
                            }
                            missing_files.append(game_info)
                            
                            if game.is_playoff:
                                missing_playoff_games.append(game_info)
                
                current_date += timedelta(days=1)
            
            # Build result message
            if not missing_files:
                team_msg = f" for {self.team_filter_normalized}" if self.team_filter_normalized else ""
                return ValidationResult(
                    check_name="gcs_file_validation",
                    check_type="custom",
                    layer="GCS",
                    passed=True,
                    severity=ValidationSeverity.CRITICAL.value,
                    message=f"All {total_games_checked} games have GCS files{team_msg} ✅",
                    affected_count=0
                )
            
            details = []
            team_msg = f" for {self.team_filter_normalized}" if self.team_filter_normalized else ""
            details.append(f"🔴 CRITICAL: {len(missing_files)} games missing GCS files{team_msg}")
            details.append(f"   (Scraper didn't run for these dates!)")
            details.append("")
            
            if missing_playoff_games:
                details.append(f"🏀 PLAYOFF GAMES MISSING: {len(missing_playoff_games)}")
                for game in missing_playoff_games[:10]:
                    details.append(f"  {game['date']}: {game['full_matchup']} - {game['game_label']}")
                if len(missing_playoff_games) > 10:
                    details.append(f"  ... and {len(missing_playoff_games) - 10} more playoff games")
                details.append("")
            
            # Regular season missing
            regular_season_missing = [g for g in missing_files if not g['is_playoff']]
            if regular_season_missing:
                details.append(f"📅 REGULAR SEASON MISSING: {len(regular_season_missing)}")
                for game in regular_season_missing[:10]:
                    details.append(f"  {game['date']}: {game['full_matchup']}")
                if len(regular_season_missing) > 10:
                    details.append(f"  ... and {len(regular_season_missing) - 10} more regular season games")
            
            message = "\n".join(details)
            
            return ValidationResult(
                check_name="gcs_file_validation",
                check_type="custom",
                layer="GCS",
                passed=False,
                severity=ValidationSeverity.CRITICAL.value,
                message=message,
                affected_count=len(missing_files),
                affected_items=[f"{g['date']}: {g['matchup']}" for g in missing_files[:20]]
            )
            
        except Exception as e:
            logger.error(f"GCS file validation failed: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return ValidationResult(
                check_name="gcs_file_validation",
                check_type="custom",
                layer="GCS",
                passed=False,
                severity=ValidationSeverity.ERROR.value,
                message=f"GCS validation error: {str(e)}"
            )
    
    # ========================================================================
    # Helper: Build team filter SQL
    # ========================================================================
    def _build_team_filter_sql(self) -> str:
        """
        Build SQL WHERE clause for team filtering using normalized team name.
        
        Returns:
            SQL string for team filter (empty if no filter)
        """
        if not self.team_filter_normalized:
            return ""
        
        # Use normalized team name from NBATeamMapper
        # This handles all variations: "LAC" → "LA Clippers", "Clippers" → "LA Clippers"
        return f"""
        AND (home_team = '{self.team_filter_normalized}' OR away_team = '{self.team_filter_normalized}')
        """
    
    # ========================================================================
    # Existing Validation Methods (with team filter support)
    # ========================================================================
    
    def _validate_game_completeness(self) -> ValidationResult:
        """
        Validate each game has 8 rows (2 bookmakers × 2 markets × 2 outcomes)
        
        Returns:
            ValidationResult with details of incomplete games
        """
        # Get table info from config
        bigquery_config = self.config.get('bigquery', {})
        project = bigquery_config.get('project', self.project_id)
        dataset = bigquery_config.get('dataset', 'nba_raw')
        table = bigquery_config.get('table', 'odds_api_game_lines')
        
        # NEW: Apply team filter
        team_filter_sql = self._build_team_filter_sql()
        
        query = f"""
        WITH game_row_counts AS (
          SELECT 
            game_date,
            game_id,
            home_team,
            away_team,
            COUNT(*) as row_count
          FROM `{project}.{dataset}.{table}`
          WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
            {team_filter_sql}
          GROUP BY game_date, game_id, home_team, away_team
        )
        SELECT 
          game_date,
          game_id,
          home_team,
          away_team,
          row_count,
          CASE
            WHEN row_count < 8 THEN 'incomplete'
            WHEN row_count > 8 THEN 'extra_rows'
            ELSE 'complete'
          END as status
        FROM game_row_counts
        WHERE row_count != 8
        ORDER BY game_date, game_id
        """
        
        try:
            results = self._execute_query(query, self.start_date, self.end_date)
            results = list(results)  # Convert to list
            
            if not results:
                team_msg = f" for {self.team_filter_normalized}" if self.team_filter_normalized else ""
                return ValidationResult(
                    check_name="game_completeness",
                    check_type="custom",
                    layer="BigQuery",
                    passed=True,
                    severity=ValidationSeverity.ERROR.value,
                    message=f"All games have complete data (8 rows each){team_msg}",
                    affected_count=0
                )
            
            # Categorize issues
            incomplete = [r for r in results if r['row_count'] < 8]
            extra = [r for r in results if r['row_count'] > 8]
            
            # Group by row count to show patterns
            from collections import Counter
            row_count_dist = Counter([r['row_count'] for r in results])
            
            details = []
            team_msg = f" for {self.team_filter_normalized}" if self.team_filter_normalized else ""
            details.append(f"Found {len(results)} incomplete games{team_msg}:")
            for count, freq in sorted(row_count_dist.items()):
                details.append(f"  {freq} games with {count} rows (expected 8)")
            
            # Show a few examples
            if incomplete:
                details.append(f"\nExample incomplete games:")
                for game in incomplete[:5]:
                    details.append(
                        f"  {game['game_date']}: {game['away_team']} @ {game['home_team']} "
                        f"({game['row_count']} rows)"
                    )
            
            if extra:
                details.append(f"\nGames with extra rows:")
                for game in extra:
                    details.append(
                        f"  {game['game_date']}: {game['away_team']} @ {game['home_team']} "
                        f"({game['row_count']} rows)"
                    )
            
            message = "\n".join(details)
            
            return ValidationResult(
                check_name="game_completeness",
                check_type="custom",
                layer="BigQuery",
                passed=False,
                severity=ValidationSeverity.ERROR.value,
                message=message,
                affected_count=len(results),
                affected_items=[f"{r['game_id']}" for r in results]
            )
            
        except Exception as e:
            logger.error(f"Game completeness validation failed: {str(e)}")
            return ValidationResult(
                check_name="game_completeness",
                check_type="custom",
                layer="BigQuery",
                passed=False,
                severity=ValidationSeverity.ERROR.value,
                message=f"Failed to check game completeness: {str(e)}"
            )
    
    def _validate_bookmaker_coverage(self) -> ValidationResult:
        """
        Validate both DraftKings and FanDuel are present for each game
        
        Returns:
            ValidationResult with games missing either bookmaker
        """
        # Get table info from config
        bigquery_config = self.config.get('bigquery', {})
        project = bigquery_config.get('project', self.project_id)
        dataset = bigquery_config.get('dataset', 'nba_raw')
        table = bigquery_config.get('table', 'odds_api_game_lines')
        
        # NEW: Apply team filter
        team_filter_sql = self._build_team_filter_sql()
        
        query = f"""
        WITH game_bookmakers AS (
          SELECT 
            game_date,
            game_id,
            home_team,
            away_team,
            COUNTIF(bookmaker_key = 'draftkings') as dk_count,
            COUNTIF(bookmaker_key = 'fanduel') as fd_count
          FROM `{project}.{dataset}.{table}`
          WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
            {team_filter_sql}
          GROUP BY game_date, game_id, home_team, away_team
        )
        SELECT 
          game_date,
          game_id,
          home_team,
          away_team,
          dk_count,
          fd_count,
          CASE
            WHEN dk_count = 0 AND fd_count = 0 THEN 'both_missing'
            WHEN dk_count = 0 THEN 'dk_missing'
            WHEN fd_count = 0 THEN 'fd_missing'
          END as issue
        FROM game_bookmakers
        WHERE dk_count = 0 OR fd_count = 0
        ORDER BY game_date, game_id
        """
        
        try:
            results = self._execute_query(query, self.start_date, self.end_date)
            results = list(results)
            
            if not results:
                team_msg = f" for {self.team_filter_normalized}" if self.team_filter_normalized else ""
                return ValidationResult(
                    check_name="bookmaker_coverage",
                    check_type="custom",
                    layer="BigQuery",
                    passed=True,
                    severity=ValidationSeverity.ERROR.value,
                    message=f"All games have both DraftKings and FanDuel data{team_msg}",
                    affected_count=0
                )
            
            # Categorize by issue type
            both_missing = [r for r in results if r['issue'] == 'both_missing']
            dk_missing = [r for r in results if r['issue'] == 'dk_missing']
            fd_missing = [r for r in results if r['issue'] == 'fd_missing']
            
            details = []
            if both_missing:
                details.append(f"{len(both_missing)} games missing both bookmakers")
            if dk_missing:
                details.append(f"{len(dk_missing)} games missing DraftKings")
            if fd_missing:
                details.append(f"{len(fd_missing)} games missing FanDuel")
            
            # Show examples
            details.append("\nExamples:")
            for game in results[:5]:
                details.append(
                    f"  {game['game_date']}: {game['away_team']} @ {game['home_team']} "
                    f"(DK: {game['dk_count']}, FD: {game['fd_count']})"
                )
            
            message = "\n".join(details)
            
            return ValidationResult(
                check_name="bookmaker_coverage",
                check_type="custom",
                layer="BigQuery",
                passed=False,
                severity=ValidationSeverity.ERROR.value,
                message=message,
                affected_count=len(results),
                affected_items=[f"{r['game_id']}" for r in results]
            )
            
        except Exception as e:
            logger.error(f"Bookmaker coverage validation failed: {str(e)}")
            return ValidationResult(
                check_name="bookmaker_coverage",
                check_type="custom",
                layer="BigQuery",
                passed=False,
                severity=ValidationSeverity.ERROR.value,
                message=f"Failed to check bookmaker coverage: {str(e)}"
            )
    
    def _validate_market_coverage(self) -> ValidationResult:
        """
        Validate both spreads and totals are present for each game
        
        Returns:
            ValidationResult with games missing either market
        """
        # Get table info from config
        bigquery_config = self.config.get('bigquery', {})
        project = bigquery_config.get('project', self.project_id)
        dataset = bigquery_config.get('dataset', 'nba_raw')
        table = bigquery_config.get('table', 'odds_api_game_lines')
        
        # NEW: Apply team filter
        team_filter_sql = self._build_team_filter_sql()
        
        query = f"""
        WITH game_markets AS (
          SELECT 
            game_date,
            game_id,
            home_team,
            away_team,
            COUNTIF(market_key = 'spreads') as spread_count,
            COUNTIF(market_key = 'totals') as total_count
          FROM `{project}.{dataset}.{table}`
          WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
            {team_filter_sql}
          GROUP BY game_date, game_id, home_team, away_team
        )
        SELECT 
          game_date,
          game_id,
          home_team,
          away_team,
          spread_count,
          total_count
        FROM game_markets
        WHERE spread_count = 0 OR total_count = 0
        ORDER BY game_date, game_id
        """
        
        try:
            results = self._execute_query(query, self.start_date, self.end_date)
            results = list(results)
            
            if not results:
                team_msg = f" for {self.team_filter_normalized}" if self.team_filter_normalized else ""
                return ValidationResult(
                    check_name="market_coverage",
                    check_type="custom",
                    layer="BigQuery",
                    passed=True,
                    severity=ValidationSeverity.ERROR.value,
                    message=f"All games have both spreads and totals{team_msg}",
                    affected_count=0
                )
            
            spread_missing = [r for r in results if r['spread_count'] == 0]
            total_missing = [r for r in results if r['total_count'] == 0]
            
            details = []
            if spread_missing:
                details.append(f"{len(spread_missing)} games missing spreads")
            if total_missing:
                details.append(f"{len(total_missing)} games missing totals")
            
            message = "\n".join(details)
            
            return ValidationResult(
                check_name="market_coverage",
                check_type="custom",
                layer="BigQuery",
                passed=False,
                severity=ValidationSeverity.ERROR.value,
                message=message,
                affected_count=len(results),
                affected_items=[f"{r['game_id']}" for r in results]
            )
            
        except Exception as e:
            logger.error(f"Market coverage validation failed: {str(e)}")
            return ValidationResult(
                check_name="market_coverage",
                check_type="custom",
                layer="BigQuery",
                passed=False,
                severity=ValidationSeverity.ERROR.value,
                message=f"Failed to check market coverage: {str(e)}"
            )
    
    def _validate_spread_ranges(self) -> ValidationResult:
        """
        Check for spreads outside reasonable range (-20 to +20)
        
        Returns:
            ValidationResult with unreasonable spreads
        """
        # Get table info from config
        bigquery_config = self.config.get('bigquery', {})
        project = bigquery_config.get('project', self.project_id)
        dataset = bigquery_config.get('dataset', 'nba_raw')
        table = bigquery_config.get('table', 'odds_api_game_lines')
        
        # NEW: Apply team filter
        team_filter_sql = self._build_team_filter_sql()
        
        query = f"""
        SELECT 
          game_date,
          game_id,
          home_team,
          away_team,
          bookmaker_key,
          outcome_name,
          outcome_point as spread
        FROM `{project}.{dataset}.{table}`
        WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
          AND market_key = 'spreads'
          AND (outcome_point < -20 OR outcome_point > 20)
          {team_filter_sql}
        ORDER BY ABS(outcome_point) DESC
        LIMIT 50
        """
        
        try:
            results = self._execute_query(query, self.start_date, self.end_date)
            results = list(results)
            
            if not results:
                team_msg = f" for {self.team_filter_normalized}" if self.team_filter_normalized else ""
                return ValidationResult(
                    check_name="spread_reasonableness",
                    check_type="custom",
                    layer="BigQuery",
                    passed=True,
                    severity=ValidationSeverity.WARNING.value,
                    message=f"All spreads within reasonable range (-20 to +20){team_msg}",
                    affected_count=0
                )
            
            details = [f"Found {len(results)} spreads outside -20 to +20:"]
            for r in results[:10]:
                details.append(
                    f"  {r['game_date']}: {r['away_team']} @ {r['home_team']} "
                    f"{r['bookmaker_key']}: {r['outcome_name']} {r['spread']:+.1f}"
                )
            
            message = "\n".join(details)
            
            return ValidationResult(
                check_name="spread_reasonableness",
                check_type="custom",
                layer="BigQuery",
                passed=False,
                severity=ValidationSeverity.WARNING.value,
                message=message,
                affected_count=len(results)
            )
            
        except Exception as e:
            logger.error(f"Spread range validation failed: {str(e)}")
            return ValidationResult(
                check_name="spread_reasonableness",
                check_type="custom",
                layer="BigQuery",
                passed=False,
                severity=ValidationSeverity.WARNING.value,
                message=f"Failed to check spread ranges: {str(e)}"
            )
    
    def _validate_totals_ranges(self) -> ValidationResult:
        """
        Check for totals outside reasonable range (200 to 245)
        
        Returns:
            ValidationResult with unreasonable totals
        """
        # Get table info from config
        bigquery_config = self.config.get('bigquery', {})
        project = bigquery_config.get('project', self.project_id)
        dataset = bigquery_config.get('dataset', 'nba_raw')
        table = bigquery_config.get('table', 'odds_api_game_lines')
        
        # NEW: Apply team filter
        team_filter_sql = self._build_team_filter_sql()
        
        query = f"""
        SELECT 
          game_date,
          game_id,
          home_team,
          away_team,
          bookmaker_key,
          outcome_name,
          outcome_point as total
        FROM `{project}.{dataset}.{table}`
        WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
          AND market_key = 'totals'
          AND (outcome_point < 200 OR outcome_point > 245)
          {team_filter_sql}
        ORDER BY outcome_point
        LIMIT 50
        """
        
        try:
            results = self._execute_query(query, self.start_date, self.end_date)
            results = list(results)
            
            if not results:
                team_msg = f" for {self.team_filter_normalized}" if self.team_filter_normalized else ""
                return ValidationResult(
                    check_name="totals_reasonableness",
                    check_type="custom",
                    layer="BigQuery",
                    passed=True,
                    severity=ValidationSeverity.WARNING.value,
                    message=f"All totals within reasonable range (200 to 245){team_msg}",
                    affected_count=0
                )
            
            details = [f"Found {len(results)} totals outside 200-245:"]
            for r in results[:10]:
                details.append(
                    f"  {r['game_date']}: {r['away_team']} @ {r['home_team']} "
                    f"{r['bookmaker_key']}: {r['outcome_name']} {r['total']:.1f}"
                )
            
            message = "\n".join(details)
            
            return ValidationResult(
                check_name="totals_reasonableness",
                check_type="custom",
                layer="BigQuery",
                passed=False,
                severity=ValidationSeverity.WARNING.value,
                message=message,
                affected_count=len(results)
            )
            
        except Exception as e:
            logger.error(f"Totals range validation failed: {str(e)}")
            return ValidationResult(
                check_name="totals_reasonableness",
                check_type="custom",
                layer="BigQuery",
                passed=False,
                severity=ValidationSeverity.WARNING.value,
                message=f"Failed to check totals ranges: {str(e)}"
            )
    
    def _validate_team_names(self) -> ValidationResult:
        """
        Validate team names match valid NBA teams
        
        Returns:
            ValidationResult with invalid team names
        """
        # Get table info from config
        bigquery_config = self.config.get('bigquery', {})
        project = bigquery_config.get('project', self.project_id)
        dataset = bigquery_config.get('dataset', 'nba_raw')
        table = bigquery_config.get('table', 'odds_api_game_lines')
        
        valid_teams = [
            'Atlanta Hawks', 'Boston Celtics', 'Brooklyn Nets', 'Charlotte Hornets', 'Chicago Bulls',
            'Cleveland Cavaliers', 'Dallas Mavericks', 'Denver Nuggets', 'Detroit Pistons',
            'Golden State Warriors', 'Houston Rockets', 'Indiana Pacers', 'LA Clippers',
            'Los Angeles Lakers', 'Memphis Grizzlies', 'Miami Heat', 'Milwaukee Bucks',
            'Minnesota Timberwolves', 'New Orleans Pelicans', 'New York Knicks',
            'Oklahoma City Thunder', 'Orlando Magic', 'Philadelphia 76ers', 'Phoenix Suns',
            'Portland Trail Blazers', 'Sacramento Kings', 'San Antonio Spurs', 'Toronto Raptors',
            'Utah Jazz', 'Washington Wizards'
        ]
        
        # Create string list for SQL
        teams_list = ", ".join([f"'{team}'" for team in valid_teams])
        
        # NEW: Apply team filter
        team_filter_sql = self._build_team_filter_sql()
        
        query = f"""
        WITH valid_teams AS (
          SELECT team FROM UNNEST([{teams_list}]) AS team
        ),
        invalid_home AS (
          SELECT DISTINCT 'home_team' as team_type, home_team as team_name
          FROM `{project}.{dataset}.{table}`
          WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
            AND home_team NOT IN (SELECT team FROM valid_teams)
            {team_filter_sql}
        ),
        invalid_away AS (
          SELECT DISTINCT 'away_team' as team_type, away_team as team_name
          FROM `{project}.{dataset}.{table}`
          WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
            AND away_team NOT IN (SELECT team FROM valid_teams)
            {team_filter_sql}
        )
        SELECT * FROM invalid_home
        UNION ALL
        SELECT * FROM invalid_away
        """
        
        try:
            results = self._execute_query(query, self.start_date, self.end_date)
            results = list(results)
            
            if not results:
                team_msg = f" for {self.team_filter_normalized}" if self.team_filter_normalized else ""
                return ValidationResult(
                    check_name="team_name_consistency",
                    check_type="custom",
                    layer="BigQuery",
                    passed=True,
                    severity=ValidationSeverity.ERROR.value,
                    message=f"All team names are valid NBA teams{team_msg}",
                    affected_count=0
                )
            
            details = [f"Found {len(results)} invalid team names:"]
            for r in results:
                details.append(f"  {r['team_type']}: {r['team_name']}")
            
            message = "\n".join(details)
            
            return ValidationResult(
                check_name="team_name_consistency",
                check_type="custom",
                layer="BigQuery",
                passed=False,
                severity=ValidationSeverity.ERROR.value,
                message=message,
                affected_count=len(results),
                affected_items=[r['team_name'] for r in results]
            )
            
        except Exception as e:
            logger.error(f"Team name validation failed: {str(e)}")
            return ValidationResult(
                check_name="team_name_consistency",
                check_type="custom",
                layer="BigQuery",
                passed=False,
                severity=ValidationSeverity.ERROR.value,
                message=f"Failed to validate team names: {str(e)}"
            )
    
    def _validate_odds_timing(self) -> ValidationResult:
        """
        Check for snapshots taken after game started
        
        Returns:
            ValidationResult with late snapshots
        """
        # Get table info from config
        bigquery_config = self.config.get('bigquery', {})
        project = bigquery_config.get('project', self.project_id)
        dataset = bigquery_config.get('dataset', 'nba_raw')
        table = bigquery_config.get('table', 'odds_api_game_lines')
        
        # NEW: Apply team filter
        team_filter_sql = self._build_team_filter_sql()
        
        query = f"""
        SELECT 
          game_date,
          game_id,
          home_team,
          away_team,
          commence_time,
          MAX(snapshot_timestamp) as latest_snapshot,
          TIMESTAMP_DIFF(MAX(snapshot_timestamp), commence_time, MINUTE) as minutes_after
        FROM `{project}.{dataset}.{table}`
        WHERE game_date BETWEEN '{self.start_date}' AND '{self.end_date}'
          AND snapshot_timestamp > commence_time
          {team_filter_sql}
        GROUP BY game_date, game_id, home_team, away_team, commence_time
        ORDER BY minutes_after DESC
        LIMIT 50
        """
        
        try:
            results = self._execute_query(query, self.start_date, self.end_date)
            results = list(results)
            
            if not results:
                team_msg = f" for {self.team_filter_normalized}" if self.team_filter_normalized else ""
                return ValidationResult(
                    check_name="odds_timing",
                    check_type="custom",
                    layer="BigQuery",
                    passed=True,
                    severity=ValidationSeverity.INFO.value,
                    message=f"All odds snapshots taken before game start{team_msg}",
                    affected_count=0
                )
            
            details = [f"Found {len(results)} games with late snapshots:"]
            for r in results[:10]:
                details.append(
                    f"  {r['game_date']}: {r['away_team']} @ {r['home_team']} "
                    f"(snapshot {r['minutes_after']} min after start)"
                )
            
            message = "\n".join(details)
            
            return ValidationResult(
                check_name="odds_timing",
                check_type="custom",
                layer="BigQuery",
                passed=True,  # INFO severity, so still passes
                severity=ValidationSeverity.INFO.value,
                message=message,
                affected_count=len(results)
            )
            
        except Exception as e:
            logger.error(f"Odds timing validation failed: {str(e)}")
            return ValidationResult(
                check_name="odds_timing",
                check_type="custom",
                layer="BigQuery",
                passed=False,
                severity=ValidationSeverity.INFO.value,
                message=f"Failed to check odds timing: {str(e)}"
            )
    
    def _validate_against_schedule(self) -> ValidationResult:
        """
        Cross-validate with NBA Schedule Service to detect missing games/dates
        
        This detects API scraper failures!
        
        Returns:
            ValidationResult with missing dates/games
        """
        if not self.schedule_service:
            return ValidationResult(
                check_name="schedule_service_validation",
                check_type="custom",
                layer="Schedule",
                passed=True,
                severity=ValidationSeverity.INFO.value,
                message="Schedule service not available - skipping cross-validation"
            )
        
        # Get table info from config
        bigquery_config = self.config.get('bigquery', {})
        project = bigquery_config.get('project', self.project_id)
        dataset = bigquery_config.get('dataset', 'nba_raw')
        table = bigquery_config.get('table', 'odds_api_game_lines')
        
        try:
            # Get all dates in our range that should have games
            current_date = datetime.strptime(self.start_date, '%Y-%m-%d').date()
            end_date_obj = datetime.strptime(self.end_date, '%Y-%m-%d').date()
            
            missing_dates = []
            count_mismatches = []
            
            while current_date <= end_date_obj:
                # Check if this date should have games
                expected_count = self.schedule_service.get_game_count(current_date.isoformat())
                
                if expected_count > 0:
                    # NEW: Apply team filter if specified
                    team_filter_sql = self._build_team_filter_sql()
                    
                    # Query our odds data for this date
                    query = f"""
                    SELECT 
                      COUNT(DISTINCT game_id) as game_count
                    FROM `{project}.{dataset}.{table}`
                    WHERE game_date = '{current_date.isoformat()}'
                      {team_filter_sql}
                    """
                    
                    results = self._execute_query(query, self.start_date, self.end_date)
                    results = list(results)
                    actual_count = results[0]['game_count'] if results else 0
                    
                    if actual_count == 0:
                        # Complete date failure - API scraper likely failed
                        missing_dates.append({
                            'date': current_date.isoformat(),
                            'expected': expected_count,
                            'actual': 0
                        })
                    elif actual_count < expected_count:
                        # Partial failure - some games missing
                        count_mismatches.append({
                            'date': current_date.isoformat(),
                            'expected': expected_count,
                            'actual': actual_count,
                            'missing': expected_count - actual_count
                        })
                
                current_date += timedelta(days=1)
            
            # Build result message
            if not missing_dates and not count_mismatches:
                team_msg = f" for {self.team_filter_normalized}" if self.team_filter_normalized else ""
                return ValidationResult(
                    check_name="schedule_service_validation",
                    check_type="custom",
                    layer="Schedule",
                    passed=True,
                    severity=ValidationSeverity.CRITICAL.value,
                    message=f"All scheduled games have odds data{team_msg} ✅",
                    affected_count=0
                )
            
            details = []
            
            if missing_dates:
                details.append(f"🔴 CRITICAL: {len(missing_dates)} dates with NO odds data (API scraper failure!):")
                for item in missing_dates[:10]:
                    details.append(f"  {item['date']}: expected {item['expected']} games, found 0")
                if len(missing_dates) > 10:
                    details.append(f"  ... and {len(missing_dates) - 10} more dates")
            
            if count_mismatches:
                details.append(f"\n🟡 ERROR: {len(count_mismatches)} dates with incomplete data:")
                for item in count_mismatches[:10]:
                    details.append(
                        f"  {item['date']}: expected {item['expected']} games, "
                        f"found {item['actual']} ({item['missing']} missing)"
                    )
                if len(count_mismatches) > 10:
                    details.append(f"  ... and {len(count_mismatches) - 10} more dates")
            
            message = "\n".join(details)
            
            # Determine severity based on what we found
            if missing_dates:
                passed = False
                severity = ValidationSeverity.CRITICAL.value
            else:
                passed = False
                severity = ValidationSeverity.ERROR.value
            
            return ValidationResult(
                check_name="schedule_service_validation",
                check_type="custom",
                layer="Schedule",
                passed=passed,
                severity=severity,
                message=message,
                affected_count=len(missing_dates) + len(count_mismatches),
                affected_items=[d['date'] for d in missing_dates + count_mismatches]
            )
            
        except Exception as e:
            logger.error(f"Schedule service validation failed: {str(e)}")
            return ValidationResult(
                check_name="schedule_service_validation",
                check_type="custom",
                layer="Schedule",
                passed=False,
                severity=ValidationSeverity.ERROR.value,
                message=f"Schedule service validation error: {str(e)}"
            )


def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(
        description='Validate Odds API game lines data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Last 7 days (default summary output)
  %(prog)s --last-days 7
  
  # Specific team validation (accepts multiple variations)
  %(prog)s --start-date 2024-04-01 --end-date 2024-06-30 --team "LA Clippers"
  %(prog)s --start-date 2024-04-01 --end-date 2024-06-30 --team "LAC"
  %(prog)s --start-date 2024-04-01 --end-date 2024-06-30 --team "Clippers"
  
  # Check GCS files (includes playoffs)
  %(prog)s --start-date 2024-04-01 --end-date 2024-06-30 --check-gcs
  
  # Full Clippers validation with GCS check
  %(prog)s --start-date 2024-04-01 --end-date 2024-06-30 \\
    --team "Clippers" --check-gcs --output detailed
  
  # Quiet mode for scripts
  %(prog)s --last-days 7 --output quiet
        """
    )
    
    # Date range options
    date_group = parser.add_mutually_exclusive_group(required=True)
    date_group.add_argument('--last-days', type=int, help='Validate last N days')
    date_group.add_argument('--start-date', help='Start date (YYYY-MM-DD)')
    
    parser.add_argument('--end-date', help='End date (YYYY-MM-DD, required with --start-date)')
    
    # NEW: Team filter
    parser.add_argument('--team', 
                       help='Filter validation to specific team (accepts variations: "LA Clippers", "LAC", "Clippers")')
    
    # NEW: GCS validation
    parser.add_argument('--check-gcs', action='store_true', 
                       help='Validate GCS files exist for all scheduled games (includes playoffs)')
    
    parser.add_argument('--output', choices=['summary', 'detailed', 'quiet'], 
                       default='summary', help='Output verbosity (default: summary)')
    parser.add_argument('--no-notify', action='store_true', 
                       help='Disable email/Slack notifications')
    parser.add_argument('--verbose', action='store_true', 
                       help='Enable verbose logging')
    
    args = parser.parse_args()
    
    # Configure logging
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Calculate date range
    if args.last_days:
        end_date = date.today()
        start_date = end_date - timedelta(days=args.last_days)
    else:
        if not args.end_date:
            parser.error("--end-date is required when using --start-date")
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
    
    # Initialize and run validator
    try:
        # NEW: Pass team_filter and check_gcs to validator
        validator = OddsGameLinesValidator(
            team_filter=args.team,
            check_gcs=args.check_gcs
        )
        
        # Run validation
        report = validator.validate(
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            notify=(not args.no_notify),
            output_mode=args.output
        )
        
        # Exit with appropriate code
        success = report.overall_status == "pass"
        sys.exit(0 if success else 1)
        
    except Exception as e:
        logger.error(f"Validation failed: {str(e)}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(2)


if __name__ == "__main__":
    main()