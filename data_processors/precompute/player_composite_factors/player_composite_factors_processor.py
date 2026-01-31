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
import os
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import datetime, date, timezone, timedelta
from typing import Dict, List, Optional
import pandas as pd
from google.cloud import bigquery

from data_processors.precompute.base import PrecomputeProcessorBase

# Pattern imports (Week 1 - Foundation Patterns)
from shared.processors.patterns import SmartSkipMixin, EarlyExitMixin, CircuitBreakerMixin

# Smart Idempotency (Pattern #1)
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin

# Completeness checking (Week 4 - Phase 4 Cascade Dependencies)
from shared.utils.completeness_checker import CompletenessChecker

# Bootstrap period support (Week 5 - Early Season Handling)
from shared.config.nba_season_dates import is_early_season, get_season_year_from_date, get_season_start_date
from shared.validation.config import BOOTSTRAP_DAYS

# Factor calculators and worker
from .worker import _process_single_player_worker
from .factors import ACTIVE_FACTORS, DEFERRED_FACTORS

# Configure logging
logger = logging.getLogger(__name__)


class PlayerCompositeFactorsProcessor(
    SmartIdempotencyMixin,
    SmartSkipMixin,
    EarlyExitMixin,
    CircuitBreakerMixin,
    PrecomputeProcessorBase
):
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

    # Defensive check configuration (upstream Phase 3 dependency)
    upstream_processor_name = 'UpcomingPlayerGameContextProcessor'
    upstream_table = 'nba_analytics.upcoming_player_game_context'
    lookback_days = 14  # Check for upcoming games context

    # Table schema uses game_date, not analysis_date
    date_column: str = "game_date"

    # Smart Idempotency: Fields to hash (meaningful business fields only)
    HASH_FIELDS = [
        'player_lookup', 'universal_player_id', 'game_date', 'game_id', 'analysis_date',
        'fatigue_score', 'shot_zone_mismatch_score', 'pace_score', 'usage_spike_score',
        'referee_favorability_score', 'look_ahead_pressure_score', 'travel_impact_score',
        'opponent_strength_score', 'total_composite_adjustment',
        'calculation_version', 'early_season_flag', 'insufficient_data_reason',
        'data_completeness_pct', 'missing_data_fields', 'has_warnings', 'warning_details'
    ]

    # Primary key fields for duplicate detection and MERGE operations
    PRIMARY_KEY_FIELDS = ['game_date', 'player_lookup']

    def __init__(self):
        """Initialize processor."""
        super().__init__()

        # Initialize completeness checker (Week 4 - Cascade Dependencies)
        import os
        # BigQuery client already initialized by PrecomputeProcessorBase with pooling
        self.project_id = os.environ.get('GCP_PROJECT_ID', self.bq_client.project)
        self.completeness_checker = CompletenessChecker(self.bq_client, self.project_id)

        # DataFrames for extracted data
        self.player_context_df = None
        self.team_context_df = None
        self.player_shot_df = None
        self.team_defense_df = None

        # Source hash cache (4 dependencies)
        self.source_player_context_hash = None
        self.source_team_context_hash = None
        self.source_player_shot_hash = None
        self.source_team_defense_hash = None

        # Early season tracking
        self.early_season_flag = False
        self.insufficient_data_reason = None

        # Season start date (for completeness checking)
        self.season_start_date = None

        # Failed entity tracking
        self.failed_entities = []

    # ============================================================
    # Pattern #1: Smart Skip Configuration
    # ============================================================
    RELEVANT_SOURCES = {
        # Phase 3 Analytics sources - RELEVANT (depends on these)
        'upcoming_player_game_context': True,
        'upcoming_team_game_context': True,
        'player_game_summary': True,
        'team_offense_game_summary': True,
        'team_defense_game_summary': True,

        # Phase 4 Precompute sources - RELEVANT (depends on these)
        'player_shot_zone_analysis': True,
        'team_defense_zone_analysis': True,

        # Phase 2 Raw sources - NOT RELEVANT (Phase 4 reads from Phase 3, not Phase 2)
        'nbac_gamebook_player_stats': False,
        'bdl_player_boxscores': False,
        'nbac_team_boxscore': False,
        'odds_api_player_points_props': False,
        'odds_api_game_lines': False,
        'nbac_schedule': False,
        'bigdataball_play_by_play': False,
        'nbac_play_by_play': False,
        'nbac_injury_report': False
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

    def get_upstream_data_check_query(self, start_date: str, end_date: str) -> Optional[str]:
        """
        Check if upstream data is available for circuit breaker auto-reset.

        Prevents retry storms by checking Phase 3 player_game_summary data exists.

        Args:
            start_date: Start of date range (YYYY-MM-DD)
            end_date: End of date range (YYYY-MM-DD)

        Returns:
            SQL query that returns {data_available: boolean}
        """
        return f"""
        SELECT COUNT(*) > 0 AS data_available
        FROM `{self.project_id}.nba_analytics.player_game_summary`
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        """

    # ============================================================
    # Soft Dependency Configuration (added after Jan 23 incident)
    # ============================================================
    # When enabled, processor can proceed with degraded upstream data if coverage > threshold
    # This prevents all-or-nothing blocking when upstream processors have partial failures
    use_soft_dependencies = True
    soft_dependency_threshold = 0.80  # Proceed if >80% upstream coverage

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

        Thresholds are lowered in backfill mode to accommodate early season
        where fewer players have enough games for rolling calculations.
        """
        # Lower thresholds for flexibility on low-game days
        # Production: 30 players minimum viable for predictions
        # Team threshold: 2 minimum (at least 2 teams playing)
        # Backfill mode uses even lower thresholds for early season
        player_threshold = 20 if self.is_backfill_mode else 30
        team_threshold = 2 if self.is_backfill_mode else 2

        return {
            'nba_analytics.upcoming_player_game_context': {
                'description': 'Player context for upcoming games',
                'date_field': 'game_date',
                'check_type': 'date_match',
                'expected_count_min': player_threshold,
                'max_age_hours': 12,
                'critical': True,
                'field_prefix': 'source_player_context'
            },
            'nba_analytics.upcoming_team_game_context': {
                'description': 'Team context for upcoming games',
                'date_field': 'game_date',
                'check_type': 'date_match',
                'expected_count_min': team_threshold,
                'max_age_hours': 12,
                'critical': True,
                'field_prefix': 'source_team_context'
            },
            'nba_precompute.player_shot_zone_analysis': {
                'description': 'Player shot zone patterns',
                'date_field': 'analysis_date',
                'check_type': 'date_match',
                'expected_count_min': player_threshold,
                'max_age_hours': 24,
                'critical': True,
                'field_prefix': 'source_player_shot'
            },
            'nba_precompute.team_defense_zone_analysis': {
                'description': 'Team defensive zone weaknesses',
                'date_field': 'analysis_date',
                'check_type': 'date_match',
                'expected_count_min': team_threshold,
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

        Bootstrap Period Handling:
            Skips processing for first 7 days of season (days 0-6).
            Uses schedule service to determine season start date.

        Pulls:
        1. Player game context (fatigue indicators, usage projections)
        2. Team game context (pace, betting lines)
        3. Player shot zone analysis (scoring patterns)
        4. Team defense zone analysis (defensive weaknesses)
        """
        if 'analysis_date' not in self.opts:
            raise ValueError("analysis_date required in opts")

        analysis_date = self.opts['analysis_date']

        # Determine season year using schedule service (Bootstrap period - Week 5)
        season_year = self.opts.get('season_year')
        if season_year is None:
            season_year = get_season_year_from_date(analysis_date)
            self.opts['season_year'] = season_year
            logger.debug(f"Determined season year: {season_year} for date {analysis_date}")

        # BOOTSTRAP PERIOD: Skip early season (days 0-13)
        # Uses schedule service to get accurate season start date
        if is_early_season(analysis_date, season_year, days_threshold=BOOTSTRAP_DAYS):
            logger.info(
                f"⏭️  Skipping {analysis_date}: early season period (day 0-{BOOTSTRAP_DAYS-1} of season {season_year}). "
                f"Regular processing starts day {BOOTSTRAP_DAYS}."
            )
            # Set flag for run history logging
            self.stats['processing_decision'] = 'skipped_early_season'
            self.stats['processing_decision_reason'] = f'bootstrap_period_day_0_{BOOTSTRAP_DAYS-1}_of_season_{season_year}'

            # Exit early - no data extraction, no records written
            self.raw_data = None
            return

        logger.info(f"Extracting data for {analysis_date}")

        # Store season start date for completeness checking (Week 4)
        # BUG FIX: Use actual season start date, not hardcoded Oct 1
        self.season_start_date = get_season_start_date(season_year)
        
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
        upcg_count = len(self.player_context_df)
        logger.info(f"Extracted {upcg_count} player context records from upcoming_player_game_context")

        # DEFENSIVE LOGGING: Compare UPCG count with expected count from player_game_summary
        # This helps detect partial/stale data in the UPCG table
        if self.is_backfill_mode:
            pgs_count_query = f"""
            SELECT COUNT(DISTINCT player_lookup) as player_count
            FROM `{self.project_id}.nba_analytics.player_game_summary`
            WHERE game_date = '{analysis_date}'
            """
            pgs_result = self.bq_client.query(pgs_count_query).to_dataframe()
            expected_count = int(pgs_result['player_count'].iloc[0]) if not pgs_result.empty else 0

            # Log data source comparison
            coverage_pct = (upcg_count / expected_count * 100) if expected_count > 0 else 0
            logger.info(
                f"📊 Data source check for {analysis_date}:\n"
                f"   - upcoming_player_game_context (UPCG): {upcg_count} players\n"
                f"   - player_game_summary (PGS): {expected_count} players\n"
                f"   - Coverage: {coverage_pct:.1f}%"
            )

            # Enhanced fallback decision logging
            if upcg_count == 0:
                logger.warning(
                    f"⚠️  No upcoming_player_game_context for {analysis_date}\n"
                    f"   → Falling back to synthetic context from player_game_summary\n"
                    f"   → Will generate context for {expected_count} players"
                )
            elif upcg_count < expected_count * 0.9:
                logger.error(
                    f"❌ INCOMPLETE DATA DETECTED for {analysis_date}:\n"
                    f"   - upcoming_player_game_context has only {upcg_count}/{expected_count} players ({coverage_pct:.1f}%)\n"
                    f"   - This indicates stale/partial data in UPCG table\n"
                    f"   - Missing {expected_count - upcg_count} players\n"
                    f"   → RECOMMENDATION: Clear stale UPCG data before running backfill"
                )
            else:
                logger.info(
                    f"✅ Using upcoming_player_game_context: {upcg_count} players\n"
                    f"   - Expected from PGS: {expected_count}\n"
                    f"   - Data source: UPCG table"
                )
        else:
            # Production mode - just log what we got
            logger.info(f"Using upcoming_player_game_context: {upcg_count} players (production mode)")

        # BACKFILL MODE: Generate synthetic context from PGS if UPCG data is missing or incomplete
        # CRITICAL FIX: Trigger fallback on partial data, not just empty data
        # This prevents the Jan 6, 2026 incident where 1/187 players blocked fallback
        if self.is_backfill_mode:
            # We already have expected_count and upcg_count from defensive logging above
            should_use_fallback = False
            fallback_reason = ""

            if upcg_count == 0:
                should_use_fallback = True
                fallback_reason = "UPCG is empty"
            elif expected_count > 0 and upcg_count < expected_count * 0.9:
                should_use_fallback = True
                fallback_reason = f"UPCG has incomplete data ({upcg_count}/{expected_count} = {(upcg_count/expected_count*100):.1f}%)"

            if should_use_fallback:
                logger.warning(
                    f"🔄 TRIGGERING FALLBACK for {analysis_date}:\n"
                    f"   - Reason: {fallback_reason}\n"
                    f"   - Action: Generating synthetic context from player_game_summary\n"
                    f"   - Expected coverage: {expected_count} players"
                )
                self._generate_synthetic_player_context(analysis_date)

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

        # Set raw_data to indicate successful extraction (required by base class validation)
        self.raw_data = self.player_context_df

        # Extract source hashes from all 4 dependencies (Smart Reprocessing - Pattern #3)
        self._extract_source_hashes(analysis_date)

    def _extract_source_hashes(self, analysis_date: date) -> None:
        """Extract data_hash from all 4 upstream tables (2 Phase 3, 2 Phase 4)."""
        try:
            # Use parameterized query to prevent SQL injection
            job_config = bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter("analysis_date", "DATE", analysis_date)]
            )

            # 1. upcoming_player_game_context (Phase 3)
            query = f"""SELECT data_hash FROM `{self.project_id}.nba_analytics.upcoming_player_game_context`
            WHERE game_date = @analysis_date AND data_hash IS NOT NULL ORDER BY processed_at DESC LIMIT 1"""
            result = self.bq_client.query(query, job_config=job_config).to_dataframe()
            self.source_player_context_hash = str(result['data_hash'].iloc[0]) if not result.empty else None

            # 2. upcoming_team_game_context (Phase 3)
            query = f"""SELECT data_hash FROM `{self.project_id}.nba_analytics.upcoming_team_game_context`
            WHERE game_date = @analysis_date AND data_hash IS NOT NULL ORDER BY processed_at DESC LIMIT 1"""
            result = self.bq_client.query(query, job_config=job_config).to_dataframe()
            self.source_team_context_hash = str(result['data_hash'].iloc[0]) if not result.empty else None

            # 3. player_shot_zone_analysis (Phase 4!)
            query = f"""SELECT data_hash FROM `{self.project_id}.nba_precompute.player_shot_zone_analysis`
            WHERE analysis_date = @analysis_date AND data_hash IS NOT NULL ORDER BY processed_at DESC LIMIT 1"""
            result = self.bq_client.query(query, job_config=job_config).to_dataframe()
            self.source_player_shot_hash = str(result['data_hash'].iloc[0]) if not result.empty else None

            # 4. team_defense_zone_analysis (Phase 4!)
            query = f"""SELECT data_hash FROM `{self.project_id}.nba_precompute.team_defense_zone_analysis`
            WHERE analysis_date = @analysis_date AND data_hash IS NOT NULL ORDER BY processed_at DESC LIMIT 1"""
            result = self.bq_client.query(query, job_config=job_config).to_dataframe()
            self.source_team_defense_hash = str(result['data_hash'].iloc[0]) if not result.empty else None

            logger.info(f"Extracted 4 source hashes for smart reprocessing")
        except Exception as e:
            logger.warning(f"Failed to extract source hashes: {e}")

    def _generate_synthetic_player_context(self, analysis_date: date) -> None:
        """Generate synthetic player context from player_game_summary for backfill.

        This allows historical backfills to work even when upcoming_player_game_context
        was never populated (betting data wasn't scraped before games).

        Uses players who ACTUALLY played on the date (from PGS) instead of
        who was EXPECTED to play (from upcoming_player_game_context).
        """
        query = f"""
        WITH players_on_date AS (
            -- Get players who actually played on this date with their opponents
            SELECT DISTINCT
                pgs.player_lookup,
                pgs.universal_player_id,
                pgs.game_id,
                pgs.game_date,
                pgs.opponent_team_abbr
            FROM `{self.project_id}.nba_analytics.player_game_summary` pgs
            WHERE pgs.game_date = '{analysis_date.isoformat()}'
        ),
        game_history AS (
            -- Get each player's game history for fatigue metrics
            SELECT
                pgs.player_lookup,
                pgs.game_date,
                pgs.minutes_played,
                pgs.usage_rate
            FROM `{self.project_id}.nba_analytics.player_game_summary` pgs
            WHERE pgs.game_date >= DATE_SUB('{analysis_date.isoformat()}', INTERVAL 14 DAY)
              AND pgs.game_date < '{analysis_date.isoformat()}'
        ),
        fatigue_metrics AS (
            SELECT
                p.player_lookup,
                -- Days rest (simplified - check if played yesterday)
                CASE WHEN EXISTS (
                    SELECT 1 FROM game_history gh2
                    WHERE gh2.player_lookup = p.player_lookup
                      AND gh2.game_date = DATE_SUB('{analysis_date.isoformat()}', INTERVAL 1 DAY)
                ) THEN 0 ELSE 1 END as days_rest,
                -- Back to back
                EXISTS (
                    SELECT 1 FROM game_history gh2
                    WHERE gh2.player_lookup = p.player_lookup
                      AND gh2.game_date = DATE_SUB('{analysis_date.isoformat()}', INTERVAL 1 DAY)
                ) as back_to_back,
                -- Games in last 7 days (Bug fix Session 50: use > not >= for strictly 7 days)
                COUNTIF(gh.game_date > DATE_SUB('{analysis_date.isoformat()}', INTERVAL 7 DAY)) as games_in_last_7_days,
                -- Minutes in last 7 days
                COALESCE(SUM(CASE WHEN gh.game_date > DATE_SUB('{analysis_date.isoformat()}', INTERVAL 7 DAY)
                    THEN gh.minutes_played ELSE 0 END), 0) as minutes_in_last_7_days,
                -- Avg minutes per game last 7
                SAFE_DIVIDE(
                    SUM(CASE WHEN gh.game_date > DATE_SUB('{analysis_date.isoformat()}', INTERVAL 7 DAY)
                        THEN gh.minutes_played ELSE 0 END),
                    COUNTIF(gh.game_date > DATE_SUB('{analysis_date.isoformat()}', INTERVAL 7 DAY))
                ) as avg_minutes_per_game_last_7,
                -- Back to backs in last 14 days (simplified)
                0 as back_to_backs_last_14_days,
                -- Avg usage rate last 7 games
                AVG(CASE WHEN gh.game_date > DATE_SUB('{analysis_date.isoformat()}', INTERVAL 7 DAY)
                    THEN gh.usage_rate ELSE NULL END) as avg_usage_rate_last_7_games
            FROM players_on_date p
            LEFT JOIN game_history gh ON p.player_lookup = gh.player_lookup
            GROUP BY p.player_lookup
        )
        SELECT
            p.player_lookup,
            p.universal_player_id,
            p.game_id,
            p.game_date,
            p.opponent_team_abbr,
            COALESCE(fm.days_rest, 1) as days_rest,
            COALESCE(fm.back_to_back, FALSE) as back_to_back,
            COALESCE(fm.games_in_last_7_days, 0) as games_in_last_7_days,
            CAST(COALESCE(fm.minutes_in_last_7_days, 0) AS INT64) as minutes_in_last_7_days,
            COALESCE(fm.avg_minutes_per_game_last_7, 0) as avg_minutes_per_game_last_7,
            COALESCE(fm.back_to_backs_last_14_days, 0) as back_to_backs_last_14_days,
            NULL as player_age,  -- Not available in PGS
            NULL as projected_usage_rate,  -- Not available in backfill
            fm.avg_usage_rate_last_7_games,
            0 as star_teammates_out,  -- Not available in backfill
            NULL as pace_differential,  -- Not available in backfill
            NULL as opponent_pace_last_10  -- Not available in backfill
        FROM players_on_date p
        LEFT JOIN fatigue_metrics fm ON p.player_lookup = fm.player_lookup
        """

        self.player_context_df = self.bq_client.query(query).to_dataframe()
        logger.info(f"Generated {len(self.player_context_df)} synthetic player contexts from PGS (backfill mode)")

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

            # Add source hashes (Smart Reprocessing - Pattern #3)
            record['source_player_context_hash'] = self.source_player_context_hash
            record['source_team_context_hash'] = self.source_team_context_hash
            record['source_player_shot_hash'] = self.source_player_shot_hash
            record['source_team_defense_hash'] = self.source_team_defense_hash

            # Compute and add data hash (Smart Idempotency - Pattern #1)
            record['data_hash'] = self.compute_data_hash(record)

            self.transformed_data.append(record)
        
        logger.info(f"Created {len(self.transformed_data)} early season placeholder records")

    # ============================================================
    # Completeness Checking Methods (Week 4 - Cascade Dependencies)
    # ============================================================

    def _batch_check_circuit_breakers(self, all_players: List[str], analysis_date: date) -> Dict[str, dict]:
        """
        BATCH check circuit breakers for all players in ONE query.

        This replaces per-player queries which caused N queries (one per player).
        With 400 players, that was 400 queries taking 3-10 minutes.
        Now it's 1 query taking ~2 seconds.
        """
        circuit_breaker_cache = {}

        # Default for all players
        for player in all_players:
            circuit_breaker_cache[player] = {'active': False, 'attempts': 0, 'until': None}

        try:
            query = f"""
            WITH latest_attempts AS (
                SELECT
                    entity_id,
                    attempt_number,
                    circuit_breaker_tripped,
                    circuit_breaker_until,
                    ROW_NUMBER() OVER (PARTITION BY entity_id ORDER BY attempt_number DESC) as rn
                FROM `{self.project_id}.nba_orchestration.reprocess_attempts`
                WHERE processor_name = '{self.table_name}'
                  AND analysis_date = DATE('{analysis_date}')
                  AND entity_id IN UNNEST(@players)
            )
            SELECT entity_id, attempt_number, circuit_breaker_tripped, circuit_breaker_until
            FROM latest_attempts
            WHERE rn = 1
            """
            result_df = self.bq_client.query(
                query,
                job_config=bigquery.QueryJobConfig(
                    query_parameters=[bigquery.ArrayQueryParameter("players", "STRING", list(all_players))]
                )
            ).to_dataframe()

            for _, row in result_df.iterrows():
                entity_id = row['entity_id']
                if row['circuit_breaker_tripped']:
                    cb_until = row['circuit_breaker_until']
                    if cb_until and datetime.now(timezone.utc) < cb_until:
                        circuit_breaker_cache[entity_id] = {
                            'active': True,
                            'attempts': row['attempt_number'],
                            'until': cb_until
                        }
                    else:
                        circuit_breaker_cache[entity_id] = {
                            'active': False,
                            'attempts': row['attempt_number'],
                            'until': None
                        }
                else:
                    circuit_breaker_cache[entity_id] = {
                        'active': False,
                        'attempts': row['attempt_number'],
                        'until': None
                    }

            logger.info(f"Batch circuit breaker check: {len(result_df)} players with history, "
                       f"{sum(1 for v in circuit_breaker_cache.values() if v['active'])} active breakers")

        except Exception as e:
            logger.warning(f"Error in batch circuit breaker check: {e}")

        return circuit_breaker_cache

    def _check_circuit_breaker(self, entity_id: str, analysis_date: date) -> dict:
        """Check if circuit breaker is active for entity (LEGACY - use batch version)."""
        query = f"""
        SELECT attempt_number, attempted_at, circuit_breaker_tripped, circuit_breaker_until
        FROM `{self.project_id}.nba_orchestration.reprocess_attempts`
        WHERE processor_name = '{self.table_name}'
          AND entity_id = '{entity_id}'
          AND analysis_date = DATE('{analysis_date}')
        ORDER BY attempt_number DESC LIMIT 1
        """
        try:
            result = list(self.bq_client.query(query).result(timeout=60))
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
        from shared.config.orchestration_config import get_orchestration_config
        config = get_orchestration_config()

        circuit_status = self._check_circuit_breaker(entity_id, analysis_date)
        next_attempt = circuit_status['attempts'] + 1
        circuit_breaker_tripped = next_attempt >= 3
        circuit_breaker_until = None
        if circuit_breaker_tripped:
            # Use config for lockout duration (default: 24 hours, was 7 days)
            circuit_breaker_until = datetime.now(timezone.utc) + timedelta(hours=config.circuit_breaker.entity_lockout_hours)
            logger.error(f"{entity_id}: Circuit breaker TRIPPED after {next_attempt} attempts (lockout: {config.circuit_breaker.entity_lockout_hours}h)")
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
            self.bq_client.query(insert_query).result(timeout=60)
        except Exception as e:
            logger.warning(f"Failed to record reprocess attempt for {entity_id}: {e}")

    def _query_upstream_completeness(self, all_players: List[str], analysis_date: date) -> Dict[str, Dict[str, bool]]:
        """
        Query upstream tables for is_production_ready status (CASCADE PATTERN).

        Checks 4 upstream dependencies:
        1. player_shot_zone_analysis.is_production_ready (per player)
        2. team_defense_zone_analysis.is_production_ready (per opponent team)
        3. upcoming_player_game_context.is_production_ready (per player)
        4. upcoming_team_game_context.is_production_ready (per team)

        Args:
            all_players: List of player_lookup IDs
            analysis_date: Date to check

        Returns:
            Dict mapping player_lookup to upstream status dict:
            {
                'player_lookup': {
                    'player_shot_zone_ready': bool,
                    'team_defense_zone_ready': bool,
                    'upcoming_player_context_ready': bool,
                    'upcoming_team_context_ready': bool,
                    'all_upstreams_ready': bool
                }
            }
        """
        upstream_status = {}

        # OPTIMIZATION: Skip upstream queries in backfill mode
        # Historical data is trusted, saves ~8s per date (92 min for 680 dates)
        if self.is_backfill_mode:
            logger.info(f"⏭️  BACKFILL MODE: Skipping upstream completeness check for {len(all_players)} players")
            for player in all_players:
                upstream_status[player] = {
                    'player_shot_zone_ready': True,
                    'team_defense_zone_ready': True,
                    'upcoming_player_context_ready': True,
                    'upcoming_team_context_ready': True,
                    'all_upstreams_ready': True
                }
            return upstream_status

        try:
            # Query 1: player_shot_zone_analysis
            query = f"""
            SELECT player_lookup, is_production_ready
            FROM `{self.project_id}.nba_precompute.player_shot_zone_analysis`
            WHERE analysis_date = '{analysis_date}'
              AND player_lookup IN UNNEST(@players)
            """
            shot_zone_df = self.bq_client.query(
                query,
                job_config=bigquery.QueryJobConfig(
                    query_parameters=[bigquery.ArrayQueryParameter("players", "STRING", list(all_players))]
                )
            ).to_dataframe()

            # Query 2: upcoming_player_game_context (from player_context_df we already have)
            # Get game_date for each player from player_context_df
            player_game_dates = {}
            for _, row in self.player_context_df.iterrows():
                player_game_dates[row['player_lookup']] = row['game_date']

            # Query upcoming_player_game_context for is_production_ready
            query = f"""
            SELECT player_lookup, game_date, is_production_ready
            FROM `{self.project_id}.nba_analytics.upcoming_player_game_context`
            WHERE player_lookup IN UNNEST(@players)
              AND game_date = '{analysis_date}'
            """
            player_context_df = self.bq_client.query(
                query,
                job_config=bigquery.QueryJobConfig(
                    query_parameters=[bigquery.ArrayQueryParameter("players", "STRING", list(all_players))]
                )
            ).to_dataframe()

            # Query 3 & 4: team_defense_zone_analysis and upcoming_team_game_context (by opponent)
            # Get opponent teams for each player
            opponent_teams = self.player_context_df[['player_lookup', 'opponent_team_abbr']].drop_duplicates()
            unique_opponents = opponent_teams['opponent_team_abbr'].unique().tolist()

            query = f"""
            SELECT team_abbr, is_production_ready
            FROM `{self.project_id}.nba_precompute.team_defense_zone_analysis`
            WHERE analysis_date = '{analysis_date}'
              AND team_abbr IN UNNEST(@teams)
            """
            team_defense_df = self.bq_client.query(
                query,
                job_config=bigquery.QueryJobConfig(
                    query_parameters=[bigquery.ArrayQueryParameter("teams", "STRING", unique_opponents)]
                )
            ).to_dataframe()

            query = f"""
            SELECT team_abbr, game_date, is_production_ready
            FROM `{self.project_id}.nba_analytics.upcoming_team_game_context`
            WHERE team_abbr IN UNNEST(@teams)
              AND game_date = '{analysis_date}'
            """
            team_context_df = self.bq_client.query(
                query,
                job_config=bigquery.QueryJobConfig(
                    query_parameters=[bigquery.ArrayQueryParameter("teams", "STRING", unique_opponents)]
                )
            ).to_dataframe()

            # Build status dict for each player
            for player in all_players:
                # Get opponent for this player
                opponent_row = opponent_teams[opponent_teams['player_lookup'] == player]
                opponent_team = opponent_row['opponent_team_abbr'].iloc[0] if not opponent_row.empty else None

                # Check each upstream (use safe bool conversion for NA values)
                shot_zone_ready = False
                if player in shot_zone_df['player_lookup'].values:
                    val = shot_zone_df[shot_zone_df['player_lookup'] == player]['is_production_ready'].iloc[0]
                    shot_zone_ready = bool(val) if not pd.isna(val) else False

                player_context_ready = False
                if player in player_context_df['player_lookup'].values:
                    val = player_context_df[player_context_df['player_lookup'] == player]['is_production_ready'].iloc[0]
                    player_context_ready = bool(val) if not pd.isna(val) else False

                team_defense_ready = False
                if opponent_team and opponent_team in team_defense_df['team_abbr'].values:
                    val = team_defense_df[team_defense_df['team_abbr'] == opponent_team]['is_production_ready'].iloc[0]
                    team_defense_ready = bool(val) if not pd.isna(val) else False

                team_context_ready = False
                if opponent_team and opponent_team in team_context_df['team_abbr'].values:
                    val = team_context_df[team_context_df['team_abbr'] == opponent_team]['is_production_ready'].iloc[0]
                    team_context_ready = bool(val) if not pd.isna(val) else False

                upstream_status[player] = {
                    'player_shot_zone_ready': shot_zone_ready,
                    'team_defense_zone_ready': team_defense_ready,
                    'upcoming_player_context_ready': player_context_ready,
                    'upcoming_team_context_ready': team_context_ready,
                    'all_upstreams_ready': (shot_zone_ready and team_defense_ready and
                                           player_context_ready and team_context_ready)
                }

            logger.info(
                f"Upstream completeness check: "
                f"{sum(1 for s in upstream_status.values() if s['all_upstreams_ready'])}/{len(upstream_status)} "
                f"players have all upstreams ready"
            )

        except Exception as e:
            logger.error(f"Error querying upstream completeness: {e}")
            # Return empty dict on error - will be treated as not ready
            for player in all_players:
                upstream_status[player] = {
                    'player_shot_zone_ready': False,
                    'team_defense_zone_ready': False,
                    'upcoming_player_context_ready': False,
                    'upcoming_team_context_ready': False,
                    'all_upstreams_ready': False
                }

        return upstream_status

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

        # Get all players and analysis date
        all_players = self.player_context_df['player_lookup'].unique()
        analysis_date = self.opts['analysis_date']

        # ============================================================
        # NEW (Week 4): Batch completeness checking + upstream tracking
        # ============================================================
        # OPTIMIZATION (Session 64): Skip slow completeness check in backfill mode
        # Backfill already has preflight checks at date-level; player-level is redundant
        if self.is_backfill_mode:
            logger.info(f"⏭️ BACKFILL MODE: Skipping completeness check for {len(all_players)} players")
            # Use actual counts from already-loaded data
            # player_shot_df has shot zone records per player - count those
            # This makes metadata accurate for debugging without additional BQ queries
            if self.player_shot_df is not None and not self.player_shot_df.empty:
                games_per_player = self.player_shot_df.groupby('player_lookup').size().to_dict()
            else:
                games_per_player = {player: 1 for player in all_players}  # At least today's game
            completeness_results = {
                player: {
                    'is_production_ready': True,
                    'completeness_pct': 100.0,
                    'expected_count': games_per_player.get(player, 1),
                    'actual_count': games_per_player.get(player, 1),
                    'missing_count': 0,
                    'is_complete': True
                }
                for player in all_players
            }
            is_bootstrap = False
            is_season_boundary = False
        else:
            logger.info(f"Checking completeness for {len(all_players)} players...")

            # Check own data completeness (player_game_summary)
            completeness_results = self.completeness_checker.check_completeness_batch(
                entity_ids=list(all_players),
                entity_type='player',
                analysis_date=analysis_date,
                upstream_table='nba_analytics.player_game_summary',
                upstream_entity_field='player_lookup',
                lookback_window=10,
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

        # Check upstream completeness (CASCADE PATTERN - Week 5)
        upstream_completeness = self._query_upstream_completeness(list(all_players), analysis_date)
        # ============================================================

        # ============================================================
        # BATCH circuit breaker check (Session 9 fix - avoid N queries)
        # ============================================================
        circuit_breaker_cache = self._batch_check_circuit_breakers(list(all_players), analysis_date)

        # ============================================================
        # Feature flag for parallelization
        # ============================================================
        ENABLE_PARALLELIZATION = os.environ.get('ENABLE_PLAYER_PARALLELIZATION', 'true').lower() == 'true'

        if ENABLE_PARALLELIZATION:
            successful, failed = self._process_players_parallel(
                all_players, completeness_results, upstream_completeness,
                circuit_breaker_cache, is_bootstrap, is_season_boundary, analysis_date
            )
        else:
            successful, failed = self._process_players_serial(
                all_players, completeness_results, upstream_completeness,
                circuit_breaker_cache, is_bootstrap, is_season_boundary, analysis_date
            )

        self.transformed_data = successful
        self.failed_entities = failed

        logger.info(f"Successfully processed {len(self.transformed_data)} players")

        # Count failures by category for clear visibility
        if self.failed_entities:
            category_counts = {}
            for f in self.failed_entities:
                cat = f.get('category', 'UNKNOWN')
                category_counts[cat] = category_counts.get(cat, 0) + 1

            # Show breakdown with clear labeling
            expected_skips = (category_counts.get('INSUFFICIENT_DATA', 0) +
                            category_counts.get('INCOMPLETE_DATA', 0) +
                            category_counts.get('MISSING_UPSTREAM', 0))
            errors_to_investigate = category_counts.get('PROCESSING_ERROR', 0) + category_counts.get('UNKNOWN', 0)

            logger.info(f"📊 Failure breakdown ({len(self.failed_entities)} total):")
            for cat, count in sorted(category_counts.items()):
                if cat in ('INSUFFICIENT_DATA', 'INCOMPLETE_DATA', 'MISSING_UPSTREAM', 'CIRCUIT_BREAKER_ACTIVE'):
                    logger.info(f"   {cat}: {count} (expected - data quality)")
                else:
                    logger.warning(f"   {cat}: {count} ⚠️ INVESTIGATE")

            if errors_to_investigate == 0:
                logger.info(f"✅ No errors to investigate - all {expected_skips} skips are expected (data quality)")

            # Store category breakdown in stats
            self.stats['failure_categories'] = category_counts
            self.stats['errors_to_investigate'] = errors_to_investigate

            # Save failures to BigQuery for auditing
            self.save_failures_to_bq()

    def _process_players_parallel(
        self,
        all_players: List[str],
        completeness_results: dict,
        upstream_completeness: dict,
        circuit_breaker_cache: dict,
        is_bootstrap: bool,
        is_season_boundary: bool,
        analysis_date: date
    ) -> tuple:
        """Process all players using ProcessPoolExecutor for parallelization."""
        # Determine worker count with environment variable support
        DEFAULT_WORKERS = 32  # Increased from 10 for ProcessPoolExecutor
        max_workers = int(os.environ.get(
            'PCF_WORKERS',
            os.environ.get('PARALLELIZATION_WORKERS', DEFAULT_WORKERS)
        ))
        max_workers = min(max_workers, os.cpu_count() or 1)
        logger.info(f"Processing {len(all_players)} players with {max_workers} workers (ProcessPoolExecutor)")

        # Performance timing
        loop_start = time.time()
        processed_count = 0

        # Process-safe result collection
        successful = []
        failed = []

        # ============================================================
        # PRE-FETCH: Prepare all data BEFORE workers (no BQ in workers)
        # ============================================================

        # Convert DataFrames to dicts for pickling
        player_rows = {}
        player_shots = {}
        team_defenses = {}

        for player_lookup in all_players:
            # Get player row
            player_row = self.player_context_df[
                self.player_context_df['player_lookup'] == player_lookup
            ]
            if not player_row.empty:
                player_rows[player_lookup] = player_row.iloc[0].to_dict()
            else:
                player_rows[player_lookup] = None

            # Get player shot data
            if self.player_shot_df is not None and not self.player_shot_df.empty:
                match = self.player_shot_df[
                    self.player_shot_df['player_lookup'] == player_lookup
                ]
                player_shots[player_lookup] = match.iloc[0].to_dict() if not match.empty else None
            else:
                player_shots[player_lookup] = None

            # Get team defense data (by opponent)
            if player_rows[player_lookup]:
                opponent_abbr = player_rows[player_lookup].get('opponent_team_abbr')
                if opponent_abbr and self.team_defense_df is not None and not self.team_defense_df.empty:
                    match = self.team_defense_df[
                        self.team_defense_df['team_abbr'] == opponent_abbr
                    ]
                    team_defenses[player_lookup] = match.iloc[0].to_dict() if not match.empty else None
                else:
                    team_defenses[player_lookup] = None
            else:
                team_defenses[player_lookup] = None

        # Prepare source hashes
        source_hashes = {
            'player_context': self.source_player_context_hash,
            'team_context': self.source_team_context_hash,
            'player_shot': self.source_player_shot_hash,
            'team_defense': self.source_team_defense_hash
        }

        # Prepare source tracking
        source_tracking = self.build_source_tracking_fields()

        # ============================================================
        # WORKERS: Process players in parallel
        # ============================================================

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            # Submit all player tasks
            futures = {}
            for player_lookup in all_players:
                # Skip if no player row
                if player_rows[player_lookup] is None:
                    failed.append({
                        'entity_id': player_lookup,
                        'entity_type': 'player',
                        'reason': 'Player not found in context data',
                        'category': 'MISSING_DATA'
                    })
                    continue

                # Check circuit breaker BEFORE submitting to worker
                circuit_breaker_status = circuit_breaker_cache.get(
                    player_lookup,
                    {'active': False, 'attempts': 0, 'until': None}
                )

                if circuit_breaker_status['active']:
                    failed.append({
                        'entity_id': player_lookup,
                        'entity_type': 'player',
                        'reason': f"Circuit breaker active until {circuit_breaker_status['until']}",
                        'category': 'CIRCUIT_BREAKER_ACTIVE'
                    })
                    continue

                # Get completeness for this player
                completeness = completeness_results.get(player_lookup, {
                    'expected_count': 0, 'actual_count': 0, 'completeness_pct': 0.0,
                    'missing_count': 0, 'is_complete': False, 'is_production_ready': False
                })

                # Get upstream status
                upstream_status = upstream_completeness.get(player_lookup, {
                    'player_shot_zone_ready': False,
                    'team_defense_zone_ready': False,
                    'upcoming_player_context_ready': False,
                    'upcoming_team_context_ready': False,
                    'all_upstreams_ready': False
                })

                # Submit to worker
                future = executor.submit(
                    _process_single_player_worker,
                    player_lookup,
                    player_rows[player_lookup],
                    player_shots[player_lookup],
                    team_defenses[player_lookup],
                    completeness,
                    upstream_status,
                    circuit_breaker_status,
                    is_bootstrap,
                    is_season_boundary,
                    analysis_date,
                    self.calculation_version,
                    source_hashes,
                    source_tracking,
                    self.HASH_FIELDS
                )
                futures[future] = player_lookup

            # Collect results as they complete
            for future in as_completed(futures):
                player_lookup = futures[future]
                processed_count += 1

                try:
                    success, data = future.result()
                    if success:
                        successful.append(data)
                    else:
                        failed.append(data)

                    # Progress logging every 50 players
                    if processed_count % 50 == 0:
                        elapsed = time.time() - loop_start
                        rate = processed_count / elapsed
                        remaining = len(all_players) - processed_count
                        eta = remaining / rate if rate > 0 else 0
                        logger.info(
                            f"Player processing progress: {processed_count}/{len(all_players)} "
                            f"| Rate: {rate:.1f} players/sec | ETA: {eta/60:.1f}min"
                        )
                except Exception as e:
                    logger.error(f"Error processing {player_lookup}: {e}")
                    failed.append({
                        'entity_id': player_lookup,
                        'entity_type': 'player',
                        'reason': str(e),
                        'category': 'PROCESSING_ERROR',
                        'can_retry': False
                    })

        # Final timing summary
        total_time = time.time() - loop_start
        logger.info(
            f"Completed {len(successful)} players in {total_time:.1f}s "
            f"(avg {total_time/len(successful) if successful else 0:.2f}s/player) "
            f"| {len(failed)} failed"
        )

        return successful, failed

    def _process_single_player(
        self,
        player_lookup: str,
        completeness_results: dict,
        upstream_completeness: dict,
        circuit_breaker_cache: dict,
        is_bootstrap: bool,
        is_season_boundary: bool,
        analysis_date: date
    ) -> tuple:
        """Process one player (thread-safe). Returns (success: bool, data: dict)."""
        try:
            # Get player row from DataFrame
            player_row = self.player_context_df[
                self.player_context_df['player_lookup'] == player_lookup
            ]

            if player_row.empty:
                return (False, {
                    'entity_id': player_lookup,
                    'entity_type': 'player',
                    'reason': 'Player not found in context data',
                    'category': 'MISSING_DATA'
                })

            player_row = player_row.iloc[0]

            # Get completeness for this player
            completeness = completeness_results.get(player_lookup, {
                'expected_count': 0, 'actual_count': 0, 'completeness_pct': 0.0,
                'missing_count': 0, 'is_complete': False, 'is_production_ready': False
            })

            # Check circuit breaker (from cache - no BQ query!)
            circuit_breaker_status = circuit_breaker_cache.get(
                player_lookup,
                {'active': False, 'attempts': 0, 'until': None}
            )

            if circuit_breaker_status['active']:
                logger.warning(
                    f"{player_lookup}: Circuit breaker active until "
                    f"{circuit_breaker_status['until']} - skipping"
                )
                return (False, {
                    'entity_id': player_lookup,
                    'entity_type': 'player',
                    'reason': f"Circuit breaker active until {circuit_breaker_status['until']}",
                    'category': 'CIRCUIT_BREAKER_ACTIVE'
                })

            # Check production readiness - LOG but DO NOT SKIP
            if not completeness['is_production_ready']:
                logger.info(
                    f"{player_lookup}: Completeness {completeness['completeness_pct']:.1f}% "
                    f"({completeness['actual_count']}/{completeness['expected_count']} games) - processing with reduced quality"
                )

            # Check upstream completeness (CASCADE PATTERN) - LOG but DO NOT SKIP
            upstream_status = upstream_completeness.get(player_lookup, {
                'player_shot_zone_ready': False,
                'team_defense_zone_ready': False,
                'upcoming_player_context_ready': False,
                'upcoming_team_context_ready': False,
                'all_upstreams_ready': False
            })

            if not upstream_status['all_upstreams_ready']:
                logger.info(
                    f"{player_lookup}: Upstream not fully ready "
                    f"(shot_zone={upstream_status['player_shot_zone_ready']}, "
                    f"team_defense={upstream_status['team_defense_zone_ready']}, "
                    f"player_context={upstream_status['upcoming_player_context_ready']}, "
                    f"team_context={upstream_status['upcoming_team_context_ready']}) - processing with reduced quality"
                )

            # Calculate composite factors
            record = self._calculate_player_composite(
                player_row, completeness, upstream_status, circuit_breaker_status,
                is_bootstrap, is_season_boundary
            )

            return (True, record)

        except Exception as e:
            logger.error(f"Failed to process {player_lookup}: {e}")
            return (False, {
                'entity_id': player_lookup,
                'entity_type': 'player',
                'reason': str(e),
                'category': 'calculation_error'
            })

    def _process_players_serial(
        self,
        all_players: List[str],
        completeness_results: dict,
        upstream_completeness: dict,
        circuit_breaker_cache: dict,
        is_bootstrap: bool,
        is_season_boundary: bool,
        analysis_date: date
    ) -> tuple:
        """Original serial processing (kept for fallback)."""
        logger.info(f"Processing {len(all_players)} players (serial mode)")

        successful = []
        failed = []

        total_players = len(self.player_context_df)
        processed_count = 0

        for idx, player_row in self.player_context_df.iterrows():
            try:
                player_lookup = player_row.get('player_lookup', 'unknown')

                # Progress logging every 50 players
                processed_count += 1
                if processed_count % 50 == 0 or processed_count == total_players:
                    logger.info(f"Processing player {processed_count}/{total_players} ({100*processed_count/total_players:.1f}%)")

                # Get completeness for this player
                completeness = completeness_results.get(player_lookup, {
                    'expected_count': 0, 'actual_count': 0, 'completeness_pct': 0.0,
                    'missing_count': 0, 'is_complete': False, 'is_production_ready': False
                })

                # Check circuit breaker (from cache - no BQ query!)
                circuit_breaker_status = circuit_breaker_cache.get(player_lookup, {'active': False, 'attempts': 0, 'until': None})

                if circuit_breaker_status['active']:
                    logger.warning(
                        f"{player_lookup}: Circuit breaker active until "
                        f"{circuit_breaker_status['until']} - skipping"
                    )
                    failed.append({
                        'entity_id': player_lookup,
                        'entity_type': 'player',
                        'reason': f"Circuit breaker active until {circuit_breaker_status['until']}",
                        'category': 'CIRCUIT_BREAKER_ACTIVE'
                    })
                    continue

                # Check production readiness - LOG but DO NOT SKIP
                if not completeness['is_production_ready']:
                    logger.info(
                        f"{player_lookup}: Completeness {completeness['completeness_pct']:.1f}% "
                        f"({completeness['actual_count']}/{completeness['expected_count']} games) - processing with reduced quality"
                    )

                # Check upstream completeness (CASCADE PATTERN) - LOG but DO NOT SKIP
                upstream_status = upstream_completeness.get(player_lookup, {
                    'player_shot_zone_ready': False,
                    'team_defense_zone_ready': False,
                    'upcoming_player_context_ready': False,
                    'upcoming_team_context_ready': False,
                    'all_upstreams_ready': False
                })

                if not upstream_status['all_upstreams_ready']:
                    logger.info(
                        f"{player_lookup}: Upstream not fully ready "
                        f"(shot_zone={upstream_status['player_shot_zone_ready']}, "
                        f"team_defense={upstream_status['team_defense_zone_ready']}, "
                        f"player_context={upstream_status['upcoming_player_context_ready']}, "
                        f"team_context={upstream_status['upcoming_team_context_ready']}) - processing with reduced quality"
                    )

                # Calculate composite factors
                record = self._calculate_player_composite(
                    player_row, completeness, upstream_status, circuit_breaker_status,
                    is_bootstrap, is_season_boundary
                )
                successful.append(record)

            except Exception as e:
                player_lookup = player_row.get('player_lookup', 'unknown')
                logger.error(f"Failed to process {player_lookup}: {e}")

                failed.append({
                    'entity_id': player_lookup,
                    'entity_type': 'player',
                    'reason': str(e),
                    'category': 'calculation_error'
                })

        return successful, failed

    def _calculate_player_composite(
        self,
        player_row: pd.Series,
        completeness: dict,
        upstream_status: dict,
        circuit_breaker_status: dict,
        is_bootstrap: bool,
        is_season_boundary: bool
    ) -> dict:
        """
        Calculate all composite factors for one player.

        Args:
            player_row: Player context data from DataFrame
            completeness: Completeness check results (own data)
            upstream_status: Upstream completeness status (CASCADE PATTERN)
            circuit_breaker_status: Circuit breaker status
            is_bootstrap: Bootstrap mode flag
            is_season_boundary: Season boundary flag

        Returns complete record dict ready for BigQuery.
        """
        player_lookup = player_row['player_lookup']

        # Get related data
        player_shot = self._get_player_shot_data(player_lookup)
        opponent_abbr = player_row.get('opponent_team_abbr')
        team_defense = self._get_team_defense_data(opponent_abbr)

        # Calculate all factors using the factor calculators
        factor_scores = {}
        factor_contexts = {}

        for factor in ACTIVE_FACTORS:
            score = factor.calculate(player_row, player_shot, team_defense)
            context = factor.build_context(player_row, player_shot, team_defense)
            factor_scores[factor.name] = score
            factor_contexts[factor.context_field] = context

        for factor in DEFERRED_FACTORS:
            score = factor.calculate(player_row, player_shot, team_defense)
            context = factor.build_context(player_row, player_shot, team_defense)
            factor_scores[factor.name] = score
            factor_contexts[factor.context_field] = context

        # Extract individual scores for convenience
        # BUGFIX: factor_scores contains adjustment, use context for raw 0-100 score
        fatigue_score = factor_contexts['fatigue_context_json']['final_score']
        shot_zone_score = factor_scores['shot_zone_mismatch_score']
        pace_score = factor_scores['pace_score']
        usage_spike_score = factor_scores['usage_spike_score']

        # Sum all adjustments for total composite
        total_adjustment = sum(factor_scores.values())
        
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
            # Note: NUMERIC fields have limited scale in BigQuery schema
            # shot_zone_mismatch_score: precision=4, scale=1 (XXX.X)
            # pace_score, usage_spike_score: precision=3, scale=1 (XX.X)
            # BUGFIX: factor_scores contains adjustment (-5 to 0), not raw score (0-100)
            # Use context's final_score which has the correct 0-100 value
            'fatigue_score': factor_contexts['fatigue_context_json']['final_score'],  # INTEGER 0-100
            'shot_zone_mismatch_score': round(factor_scores['shot_zone_mismatch_score'], 1),
            'pace_score': round(factor_scores['pace_score'], 1),
            'usage_spike_score': round(factor_scores['usage_spike_score'], 1),

            # Deferred factor scores (neutral for now) - scale=1
            'referee_favorability_score': round(factor_scores['referee_favorability_score'], 1),
            'look_ahead_pressure_score': round(factor_scores['look_ahead_pressure_score'], 1),
            'travel_impact_score': round(factor_scores['travel_impact_score'], 1),
            'opponent_strength_score': round(factor_scores['opponent_strength_score'], 1),

            # Total composite adjustment
            'total_composite_adjustment': round(total_adjustment, 2),

            # Context JSONs for debugging
            'fatigue_context_json': json.dumps(factor_contexts['fatigue_context_json']),
            'shot_zone_context_json': json.dumps(factor_contexts['shot_zone_context_json']),
            'pace_context_json': json.dumps(factor_contexts['pace_context_json']),
            'usage_context_json': json.dumps(factor_contexts['usage_context_json']),
            
            # Metadata
            'calculation_version': self.calculation_version,
            'early_season_flag': self.early_season_flag,
            'insufficient_data_reason': self.insufficient_data_reason,
            'data_completeness_pct': completeness_pct,
            'missing_data_fields': missing_fields,
            'has_warnings': has_warnings,
            'warning_details': warning_details,

            # ============================================================
            # NEW (Week 4): Completeness Checking Metadata (14 fields)
            # ============================================================
            # Completeness Metrics
            'expected_games_count': completeness['expected_count'],
            'actual_games_count': completeness['actual_count'],
            'completeness_percentage': completeness['completeness_pct'],
            'missing_games_count': completeness['missing_count'],

            # Production Readiness (CASCADE PATTERN: own complete AND all upstreams complete)
            'is_production_ready': (
                completeness['is_production_ready'] and
                upstream_status['all_upstreams_ready']
            ),

            # Upstream Readiness Flags (5 fields for Phase 5 visibility)
            'upstream_player_shot_ready': upstream_status['player_shot_zone_ready'],
            'upstream_team_defense_ready': upstream_status['team_defense_zone_ready'],
            'upstream_player_context_ready': upstream_status['upcoming_player_context_ready'],
            'upstream_team_context_ready': upstream_status['upcoming_team_context_ready'],
            'all_upstreams_ready': upstream_status['all_upstreams_ready'],

            'data_quality_issues': [issue for issue in [
                "own_data_incomplete" if not completeness['is_production_ready'] else None,
                "upstream_player_shot_zone_incomplete" if not upstream_status['player_shot_zone_ready'] else None,
                "upstream_team_defense_zone_incomplete" if not upstream_status['team_defense_zone_ready'] else None,
                "upstream_player_context_incomplete" if not upstream_status['upcoming_player_context_ready'] else None,
                "upstream_team_context_incomplete" if not upstream_status['upcoming_team_context_ready'] else None,
            ] if issue is not None],

            # Circuit Breaker
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

            # Timestamps
            'created_at': datetime.now(timezone.utc).isoformat(),
            'processed_at': datetime.now(timezone.utc).isoformat()
        }
        
        # Add v4.0 source tracking fields
        record.update(self.build_source_tracking_fields())

        # Add source hashes (Smart Reprocessing - Pattern #3)
        record['source_player_context_hash'] = self.source_player_context_hash
        record['source_team_context_hash'] = self.source_team_context_hash
        record['source_player_shot_hash'] = self.source_player_shot_hash
        record['source_team_defense_hash'] = self.source_team_defense_hash

        # Compute and add data hash (Smart Idempotency - Pattern #1)
        record['data_hash'] = self.compute_data_hash(record)

        return record
    
    # ========================================================================
    # SAFE VALUE EXTRACTION HELPERS
    # ========================================================================

    def _safe_int(self, value, default: int = 0) -> int:
        """
        Safely convert a value to int, handling None and pandas NA.

        The issue: player_row.get('field', default) returns the pandas NA value
        (not the default) when the field exists but contains NA. Then int() fails.

        Args:
            value: The value to convert (may be int, float, None, or pandas NA)
            default: Default value if conversion fails

        Returns:
            int: The converted value or default
        """
        if value is None or pd.isna(value):
            return default
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    def _safe_float(self, value, default: float = 0.0) -> float:
        """
        Safely convert a value to float, handling None and pandas NA.

        Args:
            value: The value to convert (may be int, float, None, or pandas NA)
            default: Default value if conversion fails

        Returns:
            float: The converted value or default
        """
        if value is None or pd.isna(value):
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    def _safe_bool(self, value, default: bool = False) -> bool:
        """
        Safely convert a value to bool, handling None and pandas NA.

        Args:
            value: The value to convert
            default: Default value if conversion fails

        Returns:
            bool: The converted value or default
        """
        if value is None or pd.isna(value):
            return default
        return bool(value)

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