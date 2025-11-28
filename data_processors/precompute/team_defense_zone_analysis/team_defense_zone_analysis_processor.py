"""
File: data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py

Team Defense Zone Analysis Processor
Aggregates team defensive performance by court zone over last 15 games.

Phase 4 Precompute Processor
Input: nba_analytics.team_defense_game_summary (Phase 3)
Output: nba_precompute.team_defense_zone_analysis
Strategy: MERGE_UPDATE (replace by analysis_date)
Schedule: Nightly at 11:00 PM (before player processors)

Key Features:
- Calculates FG% allowed by zone (paint, mid-range, three-point)
- Compares to league averages (dynamic calculation)
- Identifies defensive strengths and weaknesses
- Uses v4.0 dependency tracking (3 fields per source)
- Handles early season with placeholder rows
"""

import logging
from datetime import datetime, date, timedelta, UTC
from typing import Dict, List, Optional
import pandas as pd
from google.cloud import bigquery

# Import base class
from data_processors.precompute.precompute_base import PrecomputeProcessorBase

# Pattern imports (Week 1 - Foundation Patterns)
from shared.processors.patterns import SmartSkipMixin, EarlyExitMixin, CircuitBreakerMixin

# Smart Idempotency (Pattern #1)
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin

# Import utilities (Bootstrap period support - Week 5)
from shared.config.nba_season_dates import (
    is_early_season,
    get_season_year_from_date
)
from shared.utils.nba_team_mapper import NBATeamMapper

# Completeness checking (Week 1 - Phase 4 Historical Dependency Checking)
from shared.utils.completeness_checker import CompletenessChecker

# Notification imports
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

logger = logging.getLogger(__name__)


class TeamDefenseZoneAnalysisProcessor(
    SmartIdempotencyMixin,
    SmartSkipMixin,
    EarlyExitMixin,
    CircuitBreakerMixin,
    PrecomputeProcessorBase
):
    """
    Aggregate team defensive performance by shot zone.

    Calculates defensive metrics for each NBA team:
    - Paint defense (≤8 feet): FG%, attempts, points allowed
    - Mid-range defense (9+ feet, 2PT): FG%, attempts
    - Three-point defense: FG%, attempts
    - Comparison to league averages
    - Defensive strengths/weaknesses identification

    Processes all 30 NBA teams in ~2 minutes.
    Must complete before player processors start (11:15 PM).
    """
    
    # Configuration
    required_opts = ['analysis_date']
    additional_opts = ['season_year']
    
    # BigQuery settings
    dataset_id = "nba_precompute"
    table_name = "team_defense_zone_analysis"
    processing_strategy = "MERGE_UPDATE"
    
    # Processing parameters
    min_games_required = 15  # Minimum games for calculation
    league_avg_lookback_days = 30  # Days to look back for league averages (configurable)
    early_season_threshold_days = 14  # Days to consider "early season"

    # Smart Idempotency: Fields to hash (meaningful business fields only)
    HASH_FIELDS = [
        'team_abbr', 'analysis_date',
        'paint_pct_allowed_last_15', 'paint_attempts_allowed_per_game',
        'paint_points_allowed_per_game', 'paint_blocks_per_game',
        'paint_defense_vs_league_avg',
        'mid_range_pct_allowed_last_15', 'mid_range_attempts_allowed_per_game',
        'mid_range_blocks_per_game', 'mid_range_defense_vs_league_avg',
        'three_pt_pct_allowed_last_15', 'three_pt_attempts_allowed_per_game',
        'three_pt_blocks_per_game', 'three_pt_defense_vs_league_avg',
        'defensive_rating_last_15', 'opponent_points_per_game', 'opponent_pace',
        'games_in_sample', 'strongest_zone', 'weakest_zone',
        'data_quality_tier', 'calculation_notes'
    ]
    
    def __init__(self):
        super().__init__()

        # Initialize clients
        self.bq_client = bigquery.Client()
        self.project_id = self.bq_client.project

        # Initialize team mapper
        self.team_mapper = NBATeamMapper(use_database=False)

        # Initialize completeness checker (Week 1 - Phase 4 Completeness Checking)
        self.completeness_checker = CompletenessChecker(self.bq_client, self.project_id)

        # League average cache (calculated per run)
        self.league_averages = None

        # Source hash cache (extracted from upstream table)
        self.source_hash = None

        logger.info(f"Initialized {self.__class__.__name__}")

    # ============================================================
    # Pattern #1: Smart Skip Configuration
    # ============================================================
    RELEVANT_SOURCES = {
        # Phase 3 Analytics sources - RELEVANT (depends on these)
        'team_defense_game_summary': True,
        'team_offense_game_summary': True,
        'player_game_summary': True,

        # Play-by-play sources - RELEVANT (for shot zone data)
        'bigdataball_play_by_play': True,
        'nbac_play_by_play': True,

        # Phase 4 Precompute sources - NOT RELEVANT (this processor doesn't depend on other Phase 4 tables)
        'player_composite_factors': False,
        'player_shot_zone_analysis': False,
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
        Define Phase 3 dependency: team_defense_game_summary table.
        
        Returns:
            Dependency configuration with v4.0 tracking fields
        """
        return {
            'nba_analytics.team_defense_game_summary': {
                'field_prefix': 'source_team_defense',
                'description': 'Team defensive stats (last 15 games per team)',
                'check_type': 'per_team_game_count',  # Custom check type
                
                # Requirements
                'min_games_required': self.min_games_required,
                'min_teams_with_data': 25,  # At least 25 teams must have 15 games
                'entity_field': 'defending_team_abbr',
                
                # Freshness thresholds
                'max_age_hours_warn': 72,   # Warn if > 3 days old
                'max_age_hours_fail': 168,  # Fail if > 1 week old
                
                # Early season behavior
                'early_season_days': self.early_season_threshold_days,
                'early_season_behavior': 'WRITE_PLACEHOLDER',
                
                'critical': True
            }
        }
    
    def set_additional_opts(self) -> None:
        """Set season_year if not provided."""
        super().set_additional_opts()
        
        if 'season_year' not in self.opts:
            analysis_date = self.opts['analysis_date']
            self.opts['season_year'] = get_season_year_from_date(analysis_date)
        
        # Get season start date for completeness checking
        # Use hardcoded October 1 as approximate season boundary (actual skip logic uses schedule service)
        season_year = self.opts['season_year']
        self.season_start_date = date(season_year, 10, 1)

        logger.info(f"Processing season {season_year}, season boundary: {self.season_start_date}")
    
    def _check_table_data(self, table_name: str, analysis_date: date, 
                          config: dict) -> tuple:
        """
        Override base class to support 'per_team_game_count' check type.
        
        For team defense, we need to verify each team has minimum games.
        """
        check_type = config.get('check_type')
        
        if check_type != 'per_team_game_count':
            # Use base class implementation for other check types
            return super()._check_table_data(table_name, analysis_date, config)
        
        # Custom logic for per_team_game_count
        min_games = config.get('min_games_required', 15)
        min_teams = config.get('min_teams_with_data', 25)
        entity_field = config.get('entity_field', 'defending_team_abbr')
        
        try:
            # Count games per team
            query = f"""
            WITH team_game_counts AS (
                SELECT 
                    {entity_field} as team,
                    COUNT(*) as game_count,
                    MAX(processed_at) as last_updated
                FROM `{self.project_id}.{table_name}`
                WHERE game_date <= '{analysis_date}'
                  AND game_date >= '{self.season_start_date}'
                GROUP BY {entity_field}
            )
            SELECT 
                COUNT(*) as teams_with_min_games,
                SUM(game_count) as total_games,
                MAX(last_updated) as last_updated,
                COUNT(DISTINCT team) as total_teams
            FROM team_game_counts
            WHERE game_count >= {min_games}
            """
            
            result = list(self.bq_client.query(query).result())
            
            if not result:
                return False, {
                    'exists': False,
                    'row_count': 0,
                    'teams_found': 0,
                    'age_hours': None,
                    'last_updated': None,
                    'error': 'No query results'
                }
            
            row = result[0]
            teams_with_min = row.teams_with_min_games
            total_games = row.total_games
            last_updated = row.last_updated
            total_teams = row.total_teams
            
            # Calculate age
            if last_updated:
                age_hours = (datetime.now(UTC) - last_updated).total_seconds() / 3600
            else:
                age_hours = None
            
            # Check if sufficient teams have data
            exists = teams_with_min >= min_teams
            
            details = {
                'exists': exists,
                'row_count': total_games,
                'teams_found': teams_with_min,
                'total_teams': total_teams,
                'min_games_required': min_games,
                'min_teams_required': min_teams,
                'age_hours': round(age_hours, 2) if age_hours else None,
                'last_updated': last_updated.isoformat() if last_updated else None
            }
            
            if exists:
                logger.info(f"✅ {teams_with_min}/{total_teams} teams have {min_games}+ games")
            else:
                logger.warning(f"⚠️ Only {teams_with_min}/{min_teams} teams have {min_games}+ games")
            
            return exists, details
            
        except Exception as e:
            error_msg = f"Error checking {table_name}: {str(e)}"
            logger.error(error_msg)
            return False, {
                'exists': False,
                'error': error_msg
            }
    
    def check_dependencies(self, analysis_date: date) -> dict:
        """
        Override to add early season detection.
        """
        # Check if early season
        is_early = is_early_season(
            analysis_date,
            self.opts['season_year'],
            self.early_season_threshold_days
        )
        
        # Run base dependency check
        dep_check = super().check_dependencies(analysis_date)
        
        # Add early season flag
        dep_check['is_early_season'] = is_early
        
        if is_early:
            logger.warning(
                f"Early season detected: {(analysis_date - self.season_start_date).days} "
                f"days since season start"
            )
        
        return dep_check
    
    def extract_raw_data(self) -> None:
        """
        Extract last 15 games per team from Phase 3 table.

        Bootstrap Period Handling:
            Skips processing for first 7 days of season (days 0-6).
            Uses schedule service to determine season start date.

        Handles dependency checking and early season behavior.
        """
        analysis_date = self.opts['analysis_date']

        # Determine season year
        season_year = self.opts.get('season_year')
        if season_year is None:
            season_year = get_season_year_from_date(analysis_date)
            self.opts['season_year'] = season_year
            logger.debug(f"Determined season year: {season_year} for date {analysis_date}")

        # BOOTSTRAP PERIOD: Skip early season (days 0-6)
        # Uses schedule service to get accurate season start date
        if is_early_season(analysis_date, season_year, days_threshold=7):
            logger.info(
                f"⏭️  Skipping {analysis_date}: early season period (day 0-6 of season {season_year}). "
                f"Regular processing starts day 7."
            )
            # Set flag for run history logging
            self.stats['processing_decision'] = 'skipped_early_season'
            self.stats['processing_decision_reason'] = f'bootstrap_period_day_0_6_of_season_{season_year}'

            # Exit early - no data extraction, no records written
            self.raw_data = None
            return

        logger.info(f"Extracting team defense data for {analysis_date}")
        
        # Check dependencies
        dep_check = self.check_dependencies(self.opts['analysis_date'])
        
        # Track source usage (v4.0 - populates source_* attributes)
        self.track_source_usage(dep_check)
        
        # Check for early season
        if dep_check.get('is_early_season'):
            logger.warning("Early season detected - writing placeholder rows")
            self._write_placeholder_rows(dep_check)
            return
        
        # Handle dependency failures
        if not dep_check['all_critical_present']:
            missing = ', '.join(dep_check['missing'])
            error_msg = f"Missing critical dependencies: {missing}"
            logger.error(error_msg)
            
            try:
                notify_error(
                    title=f"Team Defense Zone Analysis: Missing Dependencies",
                    message=error_msg,
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'analysis_date': str(self.opts['analysis_date']),
                        'missing': dep_check['missing'],
                        'dependency_details': dep_check['details']
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise ValueError(error_msg)
        
        # Warn about stale data
        if not dep_check['all_fresh']:
            logger.warning(f"Stale upstream data detected: {dep_check['stale']}")
            
            try:
                notify_warning(
                    title=f"Team Defense Zone Analysis: Stale Data",
                    message=f"Upstream data is stale: {dep_check['stale']}",
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'analysis_date': str(self.opts['analysis_date']),
                        'stale_sources': dep_check['stale']
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
        
        # Extract last 15 games per team
        query = f"""
        WITH ranked_games AS (
            SELECT *,
              ROW_NUMBER() OVER (
                PARTITION BY defending_team_abbr 
                ORDER BY game_date DESC
              ) as game_rank
            FROM `{self.project_id}.nba_analytics.team_defense_game_summary`
            WHERE game_date <= '{self.opts['analysis_date']}'
              AND game_date >= '{self.season_start_date}'
        )
        SELECT * 
        FROM ranked_games 
        WHERE game_rank <= {self.min_games_required}
        ORDER BY defending_team_abbr, game_date DESC
        """
        
        self.raw_data = self.bq_client.query(query).to_dataframe()
        
        logger.info(
            f"Extracted {len(self.raw_data)} game records for "
            f"{self.raw_data['defending_team_abbr'].nunique()} teams"
        )
        
        # Calculate league averages for this analysis date
        self._calculate_league_averages()

        # Extract source hash from upstream table (Smart Reprocessing - Pattern #3)
        self._extract_source_hash()
    
    def _calculate_league_averages(self) -> None:
        """
        Calculate league-wide defensive averages.
        
        Uses last N days (configurable via league_avg_lookback_days) to get
        a representative sample of league defensive performance.
        
        Note: 30-day window is configurable via class attribute.
        For early season with <10 teams, uses historical defaults.
        """
        logger.info(f"Calculating league defensive averages ({self.league_avg_lookback_days} day window)")
        
        # Calculate lookback date
        lookback_date = self.opts['analysis_date'] - timedelta(days=self.league_avg_lookback_days)
        
        query = f"""
        WITH team_aggregates AS (
            SELECT
                defending_team_abbr,
                SUM(opp_paint_makes) as paint_makes,
                SUM(opp_paint_attempts) as paint_attempts,
                SUM(opp_mid_range_makes) as mid_range_makes,
                SUM(opp_mid_range_attempts) as mid_range_attempts,
                SUM(opp_three_pt_makes) as three_pt_makes,
                SUM(opp_three_pt_attempts) as three_pt_attempts,
                COUNT(*) as games
            FROM `{self.project_id}.nba_analytics.team_defense_game_summary`
            WHERE game_date BETWEEN '{lookback_date}' AND '{self.opts['analysis_date']}'
            GROUP BY defending_team_abbr
            HAVING COUNT(*) >= 10  -- At least 10 games for reliable average
        ),
        team_percentages AS (
            SELECT
                defending_team_abbr,
                SAFE_DIVIDE(paint_makes, paint_attempts) as paint_pct,
                SAFE_DIVIDE(mid_range_makes, mid_range_attempts) as mid_range_pct,
                SAFE_DIVIDE(three_pt_makes, three_pt_attempts) as three_pt_pct
            FROM team_aggregates
        )
        SELECT
            AVG(paint_pct) as league_avg_paint_pct,
            AVG(mid_range_pct) as league_avg_mid_range_pct,
            AVG(three_pt_pct) as league_avg_three_pt_pct,
            COUNT(*) as teams_in_sample
        FROM team_percentages
        WHERE paint_pct IS NOT NULL
          AND mid_range_pct IS NOT NULL
          AND three_pt_pct IS NOT NULL
        """
        
        result = self.bq_client.query(query).to_dataframe()
        
        if result.empty or result['teams_in_sample'].iloc[0] < 10:
            logger.warning(
                "Insufficient teams for league averages - using defaults "
                f"(only {result['teams_in_sample'].iloc[0] if not result.empty else 0} teams)"
            )
            # Default league averages (historical NBA averages)
            self.league_averages = {
                'paint_pct': 0.580,
                'mid_range_pct': 0.410,
                'three_pt_pct': 0.355,
                'teams_in_sample': 0
            }
        else:
            row = result.iloc[0]
            self.league_averages = {
                'paint_pct': float(row['league_avg_paint_pct']),
                'mid_range_pct': float(row['league_avg_mid_range_pct']),
                'three_pt_pct': float(row['league_avg_three_pt_pct']),
                'teams_in_sample': int(row['teams_in_sample'])
            }
        
        logger.info(
            f"League averages: "
            f"Paint {self.league_averages['paint_pct']:.3f}, "
            f"Mid-range {self.league_averages['mid_range_pct']:.3f}, "
            f"Three-pt {self.league_averages['three_pt_pct']:.3f} "
            f"({self.league_averages['teams_in_sample']} teams)"
        )

    def _extract_source_hash(self) -> None:
        """
        Extract data_hash from upstream Phase 3 table (team_defense_game_summary).

        This hash represents the source data used for this analysis.
        Used for Smart Reprocessing (Pattern #3) to skip processing when
        upstream data hasn't changed.
        """
        try:
            query = f"""
            SELECT data_hash
            FROM `{self.project_id}.nba_analytics.team_defense_game_summary`
            WHERE game_date <= '{self.opts['analysis_date']}'
              AND game_date >= '{self.season_start_date}'
              AND data_hash IS NOT NULL
            ORDER BY processed_at DESC
            LIMIT 1
            """

            result = self.bq_client.query(query).to_dataframe()

            if not result.empty and result['data_hash'].iloc[0]:
                self.source_hash = str(result['data_hash'].iloc[0])
                logger.info(f"Extracted source hash: {self.source_hash[:16]}...")
            else:
                logger.warning("No data_hash found in upstream table")
                self.source_hash = None

        except Exception as e:
            logger.warning(f"Failed to extract source hash: {e}")
            self.source_hash = None

    # ============================================================
    # Completeness Checking Methods (Week 1 - Phase 4)
    # ============================================================

    def _check_circuit_breaker(self, entity_id: str, analysis_date: date) -> dict:
        """
        Check if circuit breaker is active for entity.

        Returns dict with:
            - active: bool (True if circuit breaker active)
            - attempts: int (number of attempts so far)
            - until: datetime (when circuit breaker expires)
        """
        query = f"""
        SELECT
            attempt_number,
            attempted_at,
            circuit_breaker_tripped,
            circuit_breaker_until
        FROM `{self.project_id}.nba_orchestration.reprocess_attempts`
        WHERE processor_name = '{self.table_name}'
          AND entity_id = '{entity_id}'
          AND analysis_date = DATE('{analysis_date}')
        ORDER BY attempt_number DESC
        LIMIT 1
        """

        try:
            result = list(self.bq_client.query(query).result())

            if not result:
                return {'active': False, 'attempts': 0, 'until': None}

            row = result[0]

            if row.circuit_breaker_tripped:
                # Check if 7 days have passed
                if row.circuit_breaker_until and datetime.now(UTC) < row.circuit_breaker_until:
                    return {
                        'active': True,
                        'attempts': row.attempt_number,
                        'until': row.circuit_breaker_until
                    }

            return {
                'active': False,
                'attempts': row.attempt_number,
                'until': None
            }

        except Exception as e:
            logger.warning(f"Error checking circuit breaker for {entity_id}: {e}")
            return {'active': False, 'attempts': 0, 'until': None}

    def _increment_reprocess_count(self, entity_id: str, analysis_date: date, completeness_pct: float, skip_reason: str) -> None:
        """
        Track reprocessing attempt and trip circuit breaker if needed.

        Circuit breaker trips on 3rd attempt.
        """
        circuit_status = self._check_circuit_breaker(entity_id, analysis_date)
        next_attempt = circuit_status['attempts'] + 1

        # Trip circuit breaker on 3rd attempt
        circuit_breaker_tripped = next_attempt >= 3
        circuit_breaker_until = None

        if circuit_breaker_tripped:
            circuit_breaker_until = datetime.now(UTC) + timedelta(days=7)
            logger.error(
                f"{entity_id}: Circuit breaker TRIPPED after {next_attempt} attempts. "
                f"Manual intervention required. Next retry allowed: {circuit_breaker_until}"
            )

        # Record attempt
        insert_query = f"""
        INSERT INTO `{self.project_id}.nba_orchestration.reprocess_attempts`
        (processor_name, entity_id, analysis_date, attempt_number, attempted_at,
         completeness_pct, skip_reason, circuit_breaker_tripped, circuit_breaker_until,
         manual_override_applied, notes)
        VALUES (
            '{self.table_name}',
            '{entity_id}',
            DATE('{analysis_date}'),
            {next_attempt},
            CURRENT_TIMESTAMP(),
            {completeness_pct},
            '{skip_reason}',
            {circuit_breaker_tripped},
            {'TIMESTAMP("' + circuit_breaker_until.isoformat() + '")' if circuit_breaker_until else 'NULL'},
            FALSE,
            'Attempt {next_attempt}: {completeness_pct:.1f}% complete'
        )
        """

        try:
            self.bq_client.query(insert_query).result()
            logger.debug(f"{entity_id}: Recorded reprocess attempt {next_attempt}")
        except Exception as e:
            logger.warning(f"Failed to record reprocess attempt for {entity_id}: {e}")

    def calculate_precompute(self) -> None:
        """
        Calculate team defense zone metrics for all teams.

        For each team:
        - Calculate FG% allowed by zone
        - Calculate volume metrics (attempts/points per game)
        - Compare to league averages
        - Identify strengths and weaknesses

        NEW (Week 1): Includes completeness checking to ensure all required
        historical data is present before processing.
        """
        logger.info("Calculating team defense zone metrics")

        successful = []
        failed = []

        # Get all unique teams
        all_teams = self.raw_data['defending_team_abbr'].unique()
        analysis_date = self.opts['analysis_date']

        # ============================================================
        # NEW (Week 1): Batch completeness checking
        # ============================================================
        # Check if all teams have complete historical data (L15 games)
        logger.info(f"Checking completeness for {len(all_teams)} teams...")

        completeness_results = self.completeness_checker.check_completeness_batch(
            entity_ids=list(all_teams),
            entity_type='team',
            analysis_date=analysis_date,
            upstream_table='nba_analytics.team_defense_game_summary',
            upstream_entity_field='defending_team_abbr',
            lookback_window=self.min_games_required,
            window_type='games',
            season_start_date=self.season_start_date
        )

        # Check bootstrap mode
        is_bootstrap = self.completeness_checker.is_bootstrap_mode(
            analysis_date, self.season_start_date
        )
        is_season_boundary = self.completeness_checker.is_season_boundary(analysis_date)

        logger.info(
            f"Completeness check complete. Bootstrap mode: {is_bootstrap}, "
            f"Season boundary: {is_season_boundary}"
        )
        # ============================================================

        for team_abbr in all_teams:
            try:
                # ============================================================
                # NEW (Week 1): Get completeness for this team
                # ============================================================
                completeness = completeness_results.get(team_abbr, {
                    'expected_count': 0,
                    'actual_count': 0,
                    'completeness_pct': 0.0,
                    'missing_count': 0,
                    'is_complete': False,
                    'is_production_ready': False
                })

                # Check circuit breaker
                circuit_breaker_status = self._check_circuit_breaker(team_abbr, analysis_date)

                if circuit_breaker_status['active']:
                    logger.warning(
                        f"{team_abbr}: Circuit breaker active until "
                        f"{circuit_breaker_status['until']} - skipping"
                    )
                    failed.append({
                        'entity_id': team_abbr,
                        'reason': f"Circuit breaker active until {circuit_breaker_status['until']}",
                        'category': 'CIRCUIT_BREAKER_ACTIVE',
                        'can_retry': False
                    })
                    continue

                # Check production readiness (skip if incomplete, unless in bootstrap mode)
                if not completeness['is_production_ready'] and not is_bootstrap:
                    logger.warning(
                        f"{team_abbr}: Completeness {completeness['completeness_pct']}% "
                        f"({completeness['actual_count']}/{completeness['expected_count']} games) "
                        f"- below 90% threshold, skipping"
                    )

                    # Track reprocessing attempt
                    self._increment_reprocess_count(
                        team_abbr, analysis_date,
                        completeness['completeness_pct'],
                        'incomplete_upstream_data'
                    )

                    failed.append({
                        'entity_id': team_abbr,
                        'reason': (
                            f"Incomplete data: {completeness['completeness_pct']}% "
                            f"({completeness['actual_count']}/{completeness['expected_count']} games)"
                        ),
                        'category': 'INCOMPLETE_DATA',
                        'can_retry': True
                    })
                    continue
                # ============================================================

                # Get team's games
                team_data = self.raw_data[
                    self.raw_data['defending_team_abbr'] == team_abbr
                ].copy()

                games_count = len(team_data)

                # Validate sufficient games
                if games_count < self.min_games_required:
                    failed.append({
                        'entity_id': team_abbr,
                        'reason': f"Only {games_count} games, need {self.min_games_required}",
                        'category': 'INSUFFICIENT_DATA',
                        'can_retry': True
                    })
                    logger.warning(
                        f"{team_abbr}: Only {games_count}/{self.min_games_required} games"
                    )
                    continue
                
                # Calculate zone defense metrics
                zone_metrics = self._calculate_zone_defense(team_data, games_count)
                
                # Identify strengths/weaknesses
                strengths = self._identify_strengths_weaknesses(zone_metrics)
                
                # Build output record with source tracking
                record = {
                    # Identifiers
                    'team_abbr': team_abbr,
                    'analysis_date': self.opts['analysis_date'].isoformat(),
                    
                    # Paint defense
                    'paint_pct_allowed_last_15': zone_metrics['paint_pct'],
                    'paint_attempts_allowed_per_game': zone_metrics['paint_attempts_pg'],
                    'paint_points_allowed_per_game': zone_metrics['paint_points_pg'],
                    'paint_blocks_per_game': zone_metrics['paint_blocks_pg'],
                    'paint_defense_vs_league_avg': zone_metrics['paint_vs_league'],
                    
                    # Mid-range defense
                    'mid_range_pct_allowed_last_15': zone_metrics['mid_range_pct'],
                    'mid_range_attempts_allowed_per_game': zone_metrics['mid_range_attempts_pg'],
                    'mid_range_blocks_per_game': zone_metrics['mid_range_blocks_pg'],
                    'mid_range_defense_vs_league_avg': zone_metrics['mid_range_vs_league'],
                    
                    # Three-point defense
                    'three_pt_pct_allowed_last_15': zone_metrics['three_pt_pct'],
                    'three_pt_attempts_allowed_per_game': zone_metrics['three_pt_attempts_pg'],
                    'three_pt_blocks_per_game': zone_metrics['three_pt_blocks_pg'],
                    'three_pt_defense_vs_league_avg': zone_metrics['three_pt_vs_league'],
                    
                    # Overall metrics
                    'defensive_rating_last_15': zone_metrics['defensive_rating'],
                    'opponent_points_per_game': zone_metrics['opp_points_pg'],
                    'opponent_pace': zone_metrics['opponent_pace'],
                    'games_in_sample': games_count,
                    
                    # Strengths/weaknesses
                    'strongest_zone': strengths['strongest'],
                    'weakest_zone': strengths['weakest'],
                    
                    # Data quality
                    'data_quality_tier': self._determine_quality_tier(games_count),
                    'calculation_notes': zone_metrics.get('notes'),

                    # Source tracking (v4.0 - one line via base class method!)
                    **self.build_source_tracking_fields(),

                    # ============================================================
                    # NEW (Week 1): Completeness Checking Metadata (14 fields)
                    # ============================================================
                    # Completeness Metrics
                    'expected_games_count': completeness['expected_count'],
                    'actual_games_count': completeness['actual_count'],
                    'completeness_percentage': completeness['completeness_pct'],
                    'missing_games_count': completeness['missing_count'],

                    # Production Readiness
                    'is_production_ready': completeness['is_production_ready'],
                    'data_quality_issues': [],  # Populate if specific issues found

                    # Circuit Breaker (queried per entity)
                    'last_reprocess_attempt_at': None,  # Would need separate query
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
                    # ============================================================

                    # Processing metadata
                    'processed_at': datetime.now(UTC).isoformat()
                }

                # Add source hash (Smart Reprocessing - Pattern #3)
                record['source_team_defense_hash'] = self.source_hash

                # Compute and add data hash (Smart Idempotency - Pattern #1)
                record['data_hash'] = self.compute_data_hash(record)
                
                successful.append(record)
                
            except Exception as e:
                logger.error(f"Failed to process {team_abbr}: {e}", exc_info=True)
                failed.append({
                    'entity_id': team_abbr,
                    'reason': str(e),
                    'category': 'PROCESSING_ERROR',
                    'can_retry': False
                })
        
        self.transformed_data = successful
        self.failed_entities = failed
        
        logger.info(
            f"Processed {len(successful)}/{len(all_teams)} teams successfully"
        )
        
        # Alert if too many failures
        if len(failed) > 5:
            try:
                notify_error(
                    title=f"Team Defense Zone Analysis: High Failure Rate",
                    message=f"Failed to process {len(failed)}/{len(all_teams)} teams",
                    details={
                        'processor': self.__class__.__name__,
                        'run_id': self.run_id,
                        'analysis_date': str(self.opts['analysis_date']),
                        'successful': len(successful),
                        'failed': len(failed),
                        'failed_teams': [f['entity_id'] for f in failed]
                    },
                    processor_name=self.__class__.__name__
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
    
    def _calculate_zone_defense(
        self, 
        team_data: pd.DataFrame, 
        games_count: int
    ) -> Dict:
        """
        Calculate all zone defense metrics for a team.
        
        Args:
            team_data: DataFrame with team's game data
            games_count: Number of games in sample
            
        Returns:
            Dictionary with all calculated metrics
        """
        # Sum across all games
        total_paint_makes = team_data['opp_paint_makes'].sum()
        total_paint_attempts = team_data['opp_paint_attempts'].sum()
        total_mid_range_makes = team_data['opp_mid_range_makes'].sum()
        total_mid_range_attempts = team_data['opp_mid_range_attempts'].sum()
        total_three_pt_makes = team_data['opp_three_pt_makes'].sum()
        total_three_pt_attempts = team_data['opp_three_pt_attempts'].sum()
        
        total_paint_points = team_data['points_in_paint_allowed'].sum()
        total_mid_range_points = team_data['mid_range_points_allowed'].sum()
        total_three_pt_points = team_data['three_pt_points_allowed'].sum()
        
        total_paint_blocks = team_data['blocks_paint'].sum()
        total_mid_range_blocks = team_data['blocks_mid_range'].sum()
        total_three_pt_blocks = team_data['blocks_three_pt'].sum()
        
        total_points_allowed = team_data['points_allowed'].sum()
        
        # Calculate FG% allowed
        paint_pct = (
            total_paint_makes / total_paint_attempts 
            if total_paint_attempts > 0 else None
        )
        mid_range_pct = (
            total_mid_range_makes / total_mid_range_attempts 
            if total_mid_range_attempts > 0 else None
        )
        three_pt_pct = (
            total_three_pt_makes / total_three_pt_attempts 
            if total_three_pt_attempts > 0 else None
        )
        
        # Calculate per-game metrics
        paint_attempts_pg = total_paint_attempts / games_count
        mid_range_attempts_pg = total_mid_range_attempts / games_count
        three_pt_attempts_pg = total_three_pt_attempts / games_count
        
        paint_points_pg = total_paint_points / games_count
        
        paint_blocks_pg = total_paint_blocks / games_count
        mid_range_blocks_pg = total_mid_range_blocks / games_count
        three_pt_blocks_pg = total_three_pt_blocks / games_count
        
        opp_points_pg = total_points_allowed / games_count
        
        # Calculate vs league average (percentage points difference)
        # Positive = Worse defense (allowing higher FG%)
        # Negative = Better defense (allowing lower FG%)
        paint_vs_league = None
        mid_range_vs_league = None
        three_pt_vs_league = None
        
        if paint_pct is not None and self.league_averages:
            paint_vs_league = (paint_pct - self.league_averages['paint_pct']) * 100
        
        if mid_range_pct is not None and self.league_averages:
            mid_range_vs_league = (mid_range_pct - self.league_averages['mid_range_pct']) * 100
        
        if three_pt_pct is not None and self.league_averages:
            three_pt_vs_league = (three_pt_pct - self.league_averages['three_pt_pct']) * 100
        
        # Calculate advanced metrics
        defensive_rating = team_data['defensive_rating'].mean()
        opponent_pace = team_data['opponent_pace'].mean()
        
        # Build calculation notes
        notes = []
        if total_paint_attempts == 0:
            notes.append("No paint attempts")
        if total_mid_range_attempts == 0:
            notes.append("No mid-range attempts")
        if total_three_pt_attempts == 0:
            notes.append("No three-point attempts")
        
        return {
            'paint_pct': float(paint_pct) if paint_pct is not None else None,
            'paint_attempts_pg': float(paint_attempts_pg),
            'paint_points_pg': float(paint_points_pg),
            'paint_blocks_pg': float(paint_blocks_pg),
            'paint_vs_league': float(paint_vs_league) if paint_vs_league is not None else None,
            
            'mid_range_pct': float(mid_range_pct) if mid_range_pct is not None else None,
            'mid_range_attempts_pg': float(mid_range_attempts_pg),
            'mid_range_blocks_pg': float(mid_range_blocks_pg),
            'mid_range_vs_league': float(mid_range_vs_league) if mid_range_vs_league is not None else None,
            
            'three_pt_pct': float(three_pt_pct) if three_pt_pct is not None else None,
            'three_pt_attempts_pg': float(three_pt_attempts_pg),
            'three_pt_blocks_pg': float(three_pt_blocks_pg),
            'three_pt_vs_league': float(three_pt_vs_league) if three_pt_vs_league is not None else None,
            
            'defensive_rating': float(defensive_rating),
            'opp_points_pg': float(opp_points_pg),
            'opponent_pace': float(opponent_pace),
            
            'notes': '; '.join(notes) if notes else None
        }
    
    def _identify_strengths_weaknesses(self, zone_metrics: Dict) -> Dict:
        """
        Identify strongest and weakest defensive zones.
        
        Args:
            zone_metrics: Dictionary with zone defense metrics
            
        Returns:
            Dictionary with 'strongest' and 'weakest' zone identifiers
        """
        zones = {}
        
        if zone_metrics['paint_vs_league'] is not None:
            zones['paint'] = zone_metrics['paint_vs_league']
        
        if zone_metrics['mid_range_vs_league'] is not None:
            zones['mid_range'] = zone_metrics['mid_range_vs_league']
        
        if zone_metrics['three_pt_vs_league'] is not None:
            zones['perimeter'] = zone_metrics['three_pt_vs_league']
        
        if not zones:
            return {'strongest': None, 'weakest': None}
        
        # Most negative = best defense (lowest FG% relative to league)
        strongest = min(zones, key=zones.get)
        
        # Most positive = worst defense (highest FG% relative to league)
        weakest = max(zones, key=zones.get)
        
        return {'strongest': strongest, 'weakest': weakest}
    
    def _determine_quality_tier(self, games_count: int) -> str:
        """Determine data quality tier based on sample size."""
        if games_count >= 15:
            return 'high'
        elif games_count >= 10:
            return 'medium'
        else:
            return 'low'
    
    def _write_placeholder_rows(self, dep_check: dict) -> None:
        """
        Write placeholder rows for early season.
        
        All business metrics are NULL, but source tracking is still populated.
        """
        logger.info("Writing placeholder rows for early season")
        
        placeholders = []
        
        # Get all 30 NBA teams
        all_teams = self.team_mapper.get_all_nba_tricodes()
        
        for team_abbr in all_teams:
            # Count games available for this team
            games_query = f"""
            SELECT COUNT(*) as game_count
            FROM `{self.project_id}.nba_analytics.team_defense_game_summary`
            WHERE defending_team_abbr = '{team_abbr}'
              AND game_date <= '{self.opts['analysis_date']}'
              AND game_date >= '{self.season_start_date}'
            """
            
            try:
                games_result = self.bq_client.query(games_query).to_dataframe()
                games_count = int(games_result['game_count'].iloc[0]) if not games_result.empty else 0
            except Exception as e:
                logger.warning(f"Could not count games for {team_abbr}: {e}")
                games_count = 0
            
            placeholder = {
                # Identifiers
                'team_abbr': team_abbr,
                'analysis_date': self.opts['analysis_date'].isoformat(),
                
                # All business metrics = NULL
                'paint_pct_allowed_last_15': None,
                'paint_attempts_allowed_per_game': None,
                'paint_points_allowed_per_game': None,
                'paint_blocks_per_game': None,
                'paint_defense_vs_league_avg': None,
                'mid_range_pct_allowed_last_15': None,
                'mid_range_attempts_allowed_per_game': None,
                'mid_range_blocks_per_game': None,
                'mid_range_defense_vs_league_avg': None,
                'three_pt_pct_allowed_last_15': None,
                'three_pt_attempts_allowed_per_game': None,
                'three_pt_blocks_per_game': None,
                'three_pt_defense_vs_league_avg': None,
                'defensive_rating_last_15': None,
                'opponent_points_per_game': None,
                'opponent_pace': None,
                'strongest_zone': None,
                'weakest_zone': None,
                
                # Context
                'games_in_sample': games_count,
                'data_quality_tier': 'low',
                'calculation_notes': None,
                
                # Source tracking (v4.0 - still populated!)
                **self.build_source_tracking_fields(),

                # Early season flags (AFTER source tracking to prevent overwrite)
                'early_season_flag': True,
                'insufficient_data_reason': f"Only {games_count} games available, need {self.min_games_required}",

                # Processing metadata
                'processed_at': datetime.now(UTC).isoformat()
            }

            # Add source hash (Smart Reprocessing - Pattern #3)
            placeholder['source_team_defense_hash'] = self.source_hash

            # Compute and add data hash (Smart Idempotency - Pattern #1)
            placeholder['data_hash'] = self.compute_data_hash(placeholder)

            placeholders.append(placeholder)
        
        self.transformed_data = placeholders
        logger.info(f"Wrote {len(placeholders)} placeholder rows")
        
        try:
            notify_info(
                title="Team Defense Zone Analysis: Early Season Placeholders",
                message=f"Wrote {len(placeholders)} placeholder rows for early season",
                details={
                    'processor': self.__class__.__name__,
                    'run_id': self.run_id,
                    'analysis_date': str(self.opts['analysis_date']),
                    'teams': len(placeholders),
                    'days_since_season_start': (self.opts['analysis_date'] - self.season_start_date).days
                }
            )
        except Exception as notify_ex:
            logger.warning(f"Failed to send notification: {notify_ex}")
    
    def get_precompute_stats(self) -> Dict:
        """Return processor-specific stats."""
        return {
            'teams_processed': len(self.transformed_data) if self.transformed_data else 0,
            'teams_failed': len(self.failed_entities) if hasattr(self, 'failed_entities') else 0,
            'league_avg_teams_in_sample': self.league_averages.get('teams_in_sample', 0) if self.league_averages else 0,
            'early_season': getattr(self, 'early_season_flag', False)
        }