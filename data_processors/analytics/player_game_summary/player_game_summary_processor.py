#!/usr/bin/env python3
"""
Path: analytics_processors/player_game_summary/player_game_summary_processor.py

Player Game Summary Analytics Processor - Version 2.0
Complete rewrite with proper dependency tracking per v4.0 guide.

Transforms raw Phase 2 data into player game analytics with:
- Multi-source fallback logic (NBA.com → BDL for stats)
- Universal player ID integration via RegistryReader
- Shot zone tracking (deferred to Pass 2)
- Prop betting results calculation
- Full source tracking (6 sources × 3 fields = 18 fields)

REFACTORED: This file has been split into modules for maintainability:
- sources/shot_zone_analyzer.py: Shot zone extraction from BigDataBall PBP
- sources/prop_calculator.py: Prop betting calculations
- sources/player_registry.py: Universal ID integration
- calculators/quality_scorer.py: Source coverage quality scoring
- calculators/change_detector.py: Change detection wrapper

Version: 2.0 (Clean rewrite)
Last Updated: November 2025
Status: Production Ready
"""

import hashlib
import json
import logging
import os
import time
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from google.api_core.exceptions import NotFound
from google.cloud import bigquery
from data_processors.analytics.analytics_base import AnalyticsProcessorBase
from shared.utils.notification_system import notify_error, notify_warning, notify_info

# Pattern imports (Week 1 - Foundation Patterns)
from shared.processors.patterns import SmartSkipMixin, EarlyExitMixin, CircuitBreakerMixin, QualityMixin
from shared.config.source_coverage import SourceCoverageEventType, SourceCoverageSeverity
from shared.processors.patterns.quality_columns import build_quality_columns_with_legacy

# Data lineage integrity (2026-01-27)
from shared.validation.processing_gate import ProcessingGate, GateStatus, ProcessingBlockedError

# Extracted modules for maintainability
from .sources import ShotZoneAnalyzer, PropCalculator, PlayerRegistryHandler
from .calculators import QualityScorer, ChangeDetectorWrapper

logger = logging.getLogger(__name__)


class PlayerGameSummaryProcessor(
    QualityMixin,          # Source coverage quality tracking
    SmartSkipMixin,
    EarlyExitMixin,
    CircuitBreakerMixin,
    AnalyticsProcessorBase
):
    """
    Process player game summary analytics from 6 Phase 2 raw sources.

    Dependencies (5 Phase 2 tables):
    1. nba_raw.nbac_gamebook_player_stats - PRIMARY stats (CRITICAL)
    2. nba_raw.bigdataball_play_by_play - PREFERRED shot zones (OPTIONAL)
    3. nba_raw.nbac_play_by_play - BACKUP shot zones (OPTIONAL)
    4. nba_raw.odds_api_player_points_props - PRIMARY prop lines (OPTIONAL)
    5. nba_raw.bettingpros_player_points_props - BACKUP prop lines (OPTIONAL)

    REMOVED (2026-02-01):
    - nba_raw.bdl_player_boxscores - Unreliable data quality (28% major errors on bad days)

    Processing Strategy: MERGE_UPDATE (allows multi-pass enrichment)

    Optimization Patterns (Week 1):
    - Pattern #1 (Smart Skip): Only processes player stat sources
    - Pattern #3 (Early Exit): Skips no-game days, offseason, historical dates
    - Pattern #5 (Circuit Breaker): Prevents infinite retry loops
    """

    # =========================================================================
    # BDL Data Source Configuration
    # =========================================================================
    # DISABLED 2026-01-28: BDL API returns incorrect data (roughly half the actual
    # minutes/points for many players). NBA.com gamebook is authoritative.
    # Set to True to re-enable BDL as fallback source.
    # See: docs/09-handoff/2026-01-28-SESSION-8-HANDOFF.md for investigation details
    USE_BDL_DATA = False

    # =========================================================================
    # ENABLED 2026-02-02: Use NBA.com live boxscores as fallback for evening processing.
    # Gamebook PDFs are only available the next morning, but nbac_player_boxscores
    # is scraped live during games and has 100% accurate stats.
    # This enables same-day processing when gamebook isn't available yet.
    # See: docs/09-handoff/2026-02-02-SESSION-73-HANDOFF.md
    USE_NBAC_BOXSCORES_FALLBACK = True

    # =========================================================================
    # Pattern #1: Smart Skip Configuration
    # =========================================================================
    RELEVANT_SOURCES = {
        # Player stats sources - RELEVANT
        'nbac_gamebook_player_stats': True,
        'nbac_player_boxscores': True,  # ENABLED 2026-02-02: Evening processing fallback
        'bdl_player_boxscores': False,  # DISABLED - BDL data quality issues (2026-01-28)

        # Shot zone sources - RELEVANT
        'bigdataball_play_by_play': True,
        'nbac_play_by_play': True,

        # Prop betting sources - RELEVANT
        'odds_api_player_points_props': True,
        'bettingpros_player_points_props': True,

        # Team-level sources - NOT RELEVANT
        'nbac_gamebook_team_stats': False,
        'bdl_team_boxscores': False,
        'espn_team_stats': False,

        # Odds/spreads sources - NOT RELEVANT (player stats don't need spreads)
        'odds_api_spreads': False,
        'odds_api_totals': False,
        'odds_game_lines': False,

        # Injury/roster sources - NOT RELEVANT (player stats use completed games)
        'nbac_injury_report': False,
        'nbacom_roster': False,

        # Schedule sources - NOT RELEVANT
        'nbacom_schedule': False,
        'espn_scoreboard': False
    }

    # =========================================================================
    # Pattern #3: Early Exit Configuration
    # =========================================================================
    ENABLE_NO_GAMES_CHECK = True       # Skip if no games scheduled
    ENABLE_GAMES_FINISHED_CHECK = True # Skip if games not finished (NEW: prevents retry storms)
    ENABLE_OFFSEASON_CHECK = True      # Skip in July-September
    ENABLE_HISTORICAL_DATE_CHECK = True  # Skip dates >90 days old

    # =========================================================================
    # Pattern #5: Circuit Breaker Configuration
    # =========================================================================
    CIRCUIT_BREAKER_THRESHOLD = 5  # Open after 5 consecutive failures
    CIRCUIT_BREAKER_TIMEOUT = timedelta(hours=4)  # Stay open 4 hours (was 30 min - R-009: prevent retry storms for staleness issues)

    # =========================================================================
    # Pattern #3: Smart Reprocessing - Data Hash Fields
    # =========================================================================
    # Fields included in data_hash calculation (48 fields total)
    # INCLUDE: All meaningful analytics output (identifiers, stats, metrics, props)
    # EXCLUDE: Metadata (created_at, processed_at), source_* fields, quality fields
    HASH_FIELDS = [
        # Core identifiers (8)
        'player_lookup', 'universal_player_id', 'player_full_name', 'game_id',
        'game_date', 'team_abbr', 'opponent_team_abbr', 'season_year',

        # Basic performance stats (16)
        'points', 'minutes_played', 'assists', 'offensive_rebounds', 'defensive_rebounds',
        'steals', 'blocks', 'turnovers', 'fg_attempts', 'fg_makes',
        'three_pt_attempts', 'three_pt_makes', 'ft_attempts', 'ft_makes',
        'plus_minus', 'personal_fouls',

        # Shot zone performance (8)
        'paint_attempts', 'paint_makes', 'mid_range_attempts', 'mid_range_makes',
        'paint_blocks', 'mid_range_blocks', 'three_pt_blocks', 'and1_count',

        # Shot creation analysis (2)
        'assisted_fg_makes', 'unassisted_fg_makes',

        # Advanced efficiency (5)
        'usage_rate', 'ts_pct', 'efg_pct', 'starter_flag', 'win_flag',

        # Prop betting results (7)
        'points_line', 'over_under_result', 'margin', 'opening_line',
        'line_movement', 'points_line_source', 'opening_line_source',

        # Player availability (2)
        'is_active', 'player_status'
    ]

    # Primary key fields for duplicate detection and MERGE operations
    # Session 103: Changed from ['game_id', 'player_lookup'] to ['game_date', 'player_lookup']
    # This prevents duplicates caused by different game_id formats (AWAY_HOME vs HOME_AWAY)
    # Business logic: A player plays at most one game per day
    PRIMARY_KEY_FIELDS = ['game_date', 'player_lookup']

    def __init__(self):
        super().__init__()
        self.table_name = 'player_game_summary'
        self.processing_strategy = 'MERGE_UPDATE'

        # Lazy-loaded modules (initialized when needed)
        self._shot_zone_analyzer: Optional[ShotZoneAnalyzer] = None
        self._registry_handler: Optional[PlayerRegistryHandler] = None
        self._processing_gate: Optional[ProcessingGate] = None

        # Team stats availability flag (2026-01-27: Bug #2 fix)
        self._team_stats_available: bool = False

    @property
    def shot_zone_analyzer(self) -> ShotZoneAnalyzer:
        """Lazy-load shot zone analyzer."""
        if self._shot_zone_analyzer is None:
            self._shot_zone_analyzer = ShotZoneAnalyzer(
                bq_client=self.bq_client,
                project_id=self.project_id
            )
        return self._shot_zone_analyzer

    @property
    def registry_handler(self) -> PlayerRegistryHandler:
        """Lazy-load registry handler."""
        if self._registry_handler is None:
            self._registry_handler = PlayerRegistryHandler(
                source_name='player_game_summary',
                cache_ttl_seconds=300
            )
        return self._registry_handler

    @property
    def processing_gate(self) -> ProcessingGate:
        """Lazy-load processing gate for data lineage integrity."""
        if self._processing_gate is None:
            self._processing_gate = ProcessingGate(
                bq_client=self.bq_client,
                project_id=self.project_id,
                min_completeness=0.8,  # 80% minimum for processing
                grace_period_hours=36,  # Wait 36h before failing
                window_completeness_threshold=0.7  # 70% for window computation
            )
        return self._processing_gate

    def get_dependencies(self) -> dict:
        """
        Define all 7 source requirements (6 Phase 2 + 1 Phase 3).
        Per dependency tracking guide v4.0.
        """
        return {
            # SOURCE 1: NBA.com Gamebook (PRIMARY - Critical)
            'nba_raw.nbac_gamebook_player_stats': {
                'field_prefix': 'source_nbac',
                'description': 'NBA.com gamebook - primary stats with plus_minus',
                'date_field': 'game_date',
                'check_type': 'date_range',
                'expected_count_min': 200,  # ~200+ active players per day
                'max_age_hours_warn': 12,  # Increased from 6h - allow for late game completion
                'max_age_hours_fail': 24,
                'critical': True
            },
            
            # NOTE: nbac_player_boxscores is NOT listed as a dependency because it's used as a
            # FALLBACK source (substitutes for gamebook when not available), not an additional source.
            # Availability is checked in _check_source_data_available() and used via the
            # extraction query's nbac_boxscore_data CTE when gamebook has 0 records.
            # This avoids generating new source tracking columns (source_nbac_box_*).

            # SOURCE 2: BDL Boxscores (FALLBACK - Non-Critical)
            'nba_raw.bdl_player_boxscores': {
                'field_prefix': 'source_bdl',
                'description': 'BDL boxscores - fallback for basic stats',
                'date_field': 'game_date',
                'check_type': 'date_range',
                'expected_count_min': 200,
                'max_age_hours_warn': 12,  # Increased from 6h - allow for late game completion + scraper delay
                'max_age_hours_fail': 72,  # Increased from 36h - BDL has documented reliability issues (30-40% gaps)
                'critical': False  # NBA.com gamebook is primary (100% reliable), BDL is fallback only
            },
            
            # SOURCE 3: Big Ball Data (OPTIONAL - shot zones primary)
            'nba_raw.bigdataball_play_by_play': {
                'field_prefix': 'source_bbd',
                'description': 'Big Ball Data - shot zones primary source',
                'date_field': 'game_date',
                'check_type': 'date_range',
                'expected_count_min': 2000,  # Many shot events per day
                'max_age_hours_warn': 12,  # Increased from 6h - consistent with critical sources
                'max_age_hours_fail': 24,
                'critical': False  # Optional, has fallbacks
            },
            
            # SOURCE 4: NBA.com Play-by-Play (BACKUP - shot zones unverified)
            'nba_raw.nbac_play_by_play': {
                'field_prefix': 'source_nbac_pbp',
                'description': 'NBA.com PBP - shot zones backup (UNVERIFIED)',
                'date_field': 'game_date',
                'check_type': 'date_range',
                'expected_count_min': 2000,
                'max_age_hours_warn': 12,  # Increased from 6h - consistent with other sources
                'max_age_hours_fail': 24,
                'critical': False  # Backup only
            },
            
            # SOURCE 5: Odds API (OPTIONAL - prop lines primary)
            # Note: Props for past games are not updated, so use longer staleness threshold
            'nba_raw.odds_api_player_points_props': {
                'field_prefix': 'source_odds',
                'description': 'Odds API - prop lines primary source',
                'date_field': 'game_date',
                'check_type': 'date_range',
                'expected_count_min': 100,  # ~100+ players with props
                'max_age_hours_warn': 24,
                'max_age_hours_fail': 168,  # 7 days - props aren't updated after games
                'critical': False  # Optional, has backup
            },
            
            # SOURCE 6: BettingPros (BACKUP - prop lines)
            # Note: Props for past games are not updated, so use longer staleness threshold
            'nba_raw.bettingpros_player_points_props': {
                'field_prefix': 'source_bp',
                'description': 'BettingPros - prop lines backup',
                'date_field': 'game_date',
                'check_type': 'date_range',
                'expected_count_min': 100,
                'max_age_hours_warn': 24,
                'max_age_hours_fail': 168,  # 7 days - props aren't updated after games
                'critical': False  # Backup only
            },

            # SOURCE 7: Team Offense Analytics (REQUIRED - for usage_rate calculation)
            # CRITICAL: Must process BEFORE player_game_summary to prevent NULL usage_rate (Bug #2 fix)
            'nba_analytics.team_offense_game_summary': {
                'field_prefix': 'source_team',
                'description': 'Team offense analytics - for usage_rate calculation',
                'date_field': 'game_date',
                'check_type': 'date_range',
                'expected_count_min': 20,  # ~20-30 team games per day
                'max_age_hours_warn': 48,  # Increased from 24h - allow for delayed team processing
                'max_age_hours_fail': 168,  # Increased from 72h (Session 57) - prevents cascade failure when team processors have "no data" bug
                'critical': True  # CRITICAL: Processing order enforcement (2026-01-27 fix)
            }
        }

    def get_change_detector(self):
        """
        Provide change detector for incremental processing (v1.1 feature).

        Enables 99%+ efficiency gain for mid-day updates by detecting
        which players have changed data since last processing.

        Returns:
            PlayerChangeDetector configured for player stats
        """
        return ChangeDetectorWrapper.create_detector(project_id=self.project_id)

    def _check_team_stats_available(self, start_date: str, end_date: str) -> tuple[bool, int]:
        """
        Check team_offense_game_summary data availability (INFORMATIONAL ONLY).

        Session 96 Update: This method is now for MONITORING only, not a gate.
        usage_rate is calculated per-game based on whether THAT game has team stats.
        A global threshold no longer blocks all usage_rate calculations.

        Previous behavior (Bug #2 fix, 2026-01-27): Used as a global gate that
        blocked ALL usage_rate calculations if threshold wasn't met.

        Current behavior (Session 96): Returns availability info for logging/alerts,
        but usage_rate is calculated per-game regardless of this threshold.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            (meets_threshold, record_count) - For monitoring purposes only
        """
        # Get actual team-game count from team_offense_game_summary
        query = f"""
        SELECT COUNT(DISTINCT CONCAT(game_id, '_', team_abbr)) as team_game_count
        FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        """
        result = self.bq_client.query(query).result()
        count = next(result).team_game_count

        # Get expected count from NBA schedule (2 teams per game)
        expected_query = f"""
        SELECT COALESCE(COUNT(DISTINCT game_id) * 2, 0) as expected_team_game_count
        FROM `{self.project_id}.nba_reference.nba_schedule`
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
          AND game_status = 3
        """
        expected_result = self.bq_client.query(expected_query).result()
        expected_count = next(expected_result).expected_team_game_count

        # Consider ready if we have at least 50% of expected data
        # or if no games are scheduled (allow processing to continue)
        # NOTE: Lowered from 80% to 50% in Session 96 - the previous threshold
        # blocked ALL usage_rate calculations when a single game was delayed,
        # even for games that had valid team data. 50% ensures we calculate
        # usage_rate for available games rather than blocking everything.
        threshold_pct = 0.50
        if expected_count == 0:
            is_available = True  # No games scheduled, allow processing
        else:
            is_available = count >= (expected_count * threshold_pct)

        if not is_available:
            logger.warning(
                f"Team stats not ready: {count}/{expected_count} records "
                f"({100.0 * count / expected_count if expected_count > 0 else 0:.1f}% complete). "
                f"Usage rate will be NULL for this run."
            )

        return is_available, count

    def _validate_team_stats_dependency(self, start_date: str, end_date: str) -> tuple[bool, str, dict]:
        """
        Validate team stats dependency for usage_rate calculation (BLOCKING CHECK).

        Session 119 Fix: Prevent NULL usage_rate from timing race conditions.
        This is a QUALITY-FOCUSED check that validates:
        1. Team stats exist (sufficient coverage for date range)
        2. Team stats have valid possessions (required for usage_rate formula)

        Unlike _check_team_stats_available() (monitoring only), this method is a
        PROCESSING GATE that blocks extraction if dependencies aren't ready.

        Root Cause Fixed:
        - Player processor can run before team stats are written → NULL usage_rate
        - BigQuery caches stale JOIN results → NULL usage_rate even after correction
        - No pre-processing validation → silent failures

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            (is_valid, error_message, details) - is_valid=True if dependencies ready,
                                                  False with error message if not
        """
        # Get team stats with quality metrics
        query = f"""
        SELECT
            COUNT(DISTINCT CONCAT(game_id, '_', team_abbr)) as team_count,
            COUNTIF(possessions IS NULL) as null_possessions_count,
            COUNTIF(possessions IS NULL AND points_scored > 0) as invalid_quality_count
        FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        """

        try:
            result = self.bq_client.query(query).result()
            row = next(result)
            team_count = row.team_count
            null_possessions = row.null_possessions_count
            invalid_quality = row.invalid_quality_count
        except Exception as e:
            return False, f"Failed to query team stats: {e}", {}

        # Get expected count from schedule
        expected_query = f"""
        SELECT COALESCE(COUNT(DISTINCT game_id) * 2, 0) as expected_team_count
        FROM `{self.project_id}.nba_reference.nba_schedule`
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
          AND game_status = 3
        """

        try:
            expected_result = self.bq_client.query(expected_query).result()
            expected_count = next(expected_result).expected_team_count
        except Exception as e:
            return False, f"Failed to query schedule: {e}", {}

        details = {
            'team_count': team_count,
            'expected_count': expected_count,
            'null_possessions': null_possessions,
            'invalid_quality': invalid_quality,
            'coverage_pct': round(100.0 * team_count / expected_count, 1) if expected_count > 0 else 0.0,
            'quality_pct': round(100.0 * (team_count - null_possessions) / team_count, 1) if team_count > 0 else 0.0
        }

        # Validation Rule 1: Minimum team coverage (80% of expected)
        # Lower threshold than team processor (which aims for 100%) to allow for some missing games
        min_coverage_threshold = 0.80
        if expected_count > 0 and team_count < (expected_count * min_coverage_threshold):
            return False, (
                f"Team stats insufficient: {team_count}/{expected_count} teams "
                f"({details['coverage_pct']}% < {min_coverage_threshold*100}% threshold). "
                f"Run TeamOffenseGameSummaryProcessor first."
            ), details

        # Validation Rule 2: Quality check - possessions must be non-NULL
        # Allow up to 20% NULL possessions (edge cases like forfeits, data issues)
        max_null_threshold = 0.20
        if team_count > 0:
            null_pct = null_possessions / team_count
            if null_pct > max_null_threshold:
                return False, (
                    f"Team stats have invalid possessions: {null_possessions}/{team_count} NULL "
                    f"({round(null_pct*100, 1)}% > {max_null_threshold*100}% threshold). "
                    f"usage_rate calculation requires valid possessions. "
                    f"Re-run TeamOffenseGameSummaryProcessor to fix data quality."
                ), details

        # Validation Rule 3: No games scheduled - allow processing to continue
        if expected_count == 0:
            return True, "No games scheduled - validation passed", details

        # All checks passed
        return True, f"Team stats validated: {team_count} teams with {details['quality_pct']}% valid possessions", details

    def _check_source_data_available(self, start_date: str, end_date: str) -> tuple[bool, int]:
        """
        Pre-extraction check for upstream data availability.

        Checks sources in order:
        1. nbac_gamebook_player_stats (PRIMARY - from gamebook PDF, available next morning)
        2. nbac_player_boxscores (FALLBACK - from live API, available same-day)

        Sets self._use_boxscore_fallback to indicate which source will be used.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            (is_available, record_count) - True if data exists, False otherwise
        """
        # Initialize fallback flag
        self._use_boxscore_fallback = False

        # Check PRIMARY source: gamebook
        gamebook_query = f"""
        SELECT COUNT(*) as record_count
        FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
        WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
            AND player_status = 'active'
        """
        try:
            result = self.bq_client.query(gamebook_query).result()
            gamebook_count = next(result).record_count

            if gamebook_count > 0:
                logger.info(f"PRIMARY source available: nbac_gamebook_player_stats has {gamebook_count} records")
                return True, gamebook_count

            # Gamebook has no data - try boxscore fallback if enabled
            if self.USE_NBAC_BOXSCORES_FALLBACK:
                boxscore_query = f"""
                SELECT COUNT(*) as record_count
                FROM `{self.project_id}.nba_raw.nbac_player_boxscores`
                WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
                    AND game_status = 'Final'
                """
                result = self.bq_client.query(boxscore_query).result()
                boxscore_count = next(result).record_count

                if boxscore_count > 0:
                    logger.info(
                        f"FALLBACK source available: nbac_player_boxscores has {boxscore_count} records "
                        f"(gamebook has 0 - using live boxscores for evening processing)"
                    )
                    self._use_boxscore_fallback = True
                    return True, boxscore_count

                logger.warning(
                    f"No source data available: both nbac_gamebook_player_stats (0 records) "
                    f"and nbac_player_boxscores (0 Final games) have no data for {start_date} to {end_date}"
                )
            else:
                logger.warning(
                    f"No source data available: nbac_gamebook_player_stats has 0 records "
                    f"for date range {start_date} to {end_date}"
                )

            return False, 0

        except Exception as e:
            logger.error(f"Error checking source data availability: {e}")
            # On error, proceed with extraction (fail gracefully)
            return True, -1

    def get_upstream_data_check_query(self, start_date: str, end_date: str) -> Optional[str]:
        """
        Check if upstream data is available for circuit breaker auto-reset.

        Prevents retry storms by checking:
        1. Games are finished (not scheduled/in-progress)
        2. BDL boxscore data exists

        This enables the circuit breaker to automatically close when:
        - Games finish and data becomes available
        - Prevents wasteful retries before games start

        Args:
            start_date: Start of date range (YYYY-MM-DD)
            end_date: End of date range (YYYY-MM-DD)

        Returns:
            SQL query that returns {data_available: boolean} or {cnt: int}
        """
        # Check if:
        # 1. At least one game in date range is finished (game_status != 1)
        # 2. BDL boxscore data exists for that game
        #
        # game_status values: 1=Scheduled, 2=In Progress, 3=Final
        return f"""
        SELECT
            COUNTIF(
                schedule.game_status >= 3  -- Final only
                AND bdl.game_id IS NOT NULL
            ) > 0 AS data_available
        FROM `nba_raw.v_nbac_schedule_latest` AS schedule
        LEFT JOIN `nba_raw.bdl_player_boxscores` AS bdl
            ON schedule.game_id = bdl.game_id
        WHERE schedule.game_date BETWEEN '{start_date}' AND '{end_date}'
        """

    def _calculate_data_hash(self, record: Dict) -> str:
        """
        Calculate SHA256 hash of meaningful analytics fields.

        Pattern #3: Smart Reprocessing
        - Phase 4 processors extract this hash to detect changes
        - Comparison with previous hash detects meaningful changes
        - Unchanged hashes allow Phase 4 to skip expensive reprocessing

        Args:
            record: Dictionary containing analytics fields

        Returns:
            First 16 characters of SHA256 hash (sufficient for uniqueness)
        """
        hash_data = {field: record.get(field) for field in self.HASH_FIELDS}
        sorted_data = json.dumps(hash_data, sort_keys=True, default=str)
        return hashlib.sha256(sorted_data.encode()).hexdigest()[:16]

    def _determine_processing_context(self) -> str:
        """
        Determine processing context based on timing (2026-01-27).

        Returns:
            Context string: 'daily', 'backfill', 'manual', or 'cascade'
        """
        start_date = self.opts.get('start_date')
        if not start_date:
            return 'manual'

        # Calculate days since game date
        try:
            from datetime import date
            if isinstance(start_date, str):
                game_date = datetime.strptime(start_date, '%Y-%m-%d').date()
            else:
                game_date = start_date

            days_since = (date.today() - game_date).days

            if days_since <= 2:
                return 'daily'
            elif days_since <= 7:
                return 'cascade'
            else:
                return 'backfill'
        except Exception:
            return 'manual'

    def _categorize_dnp_reason(self, reason_text: str | None) -> str | None:
        """
        Categorize DNP reason into standard categories.

        Args:
            reason_text: Raw reason from gamebook (e.g., "Injury - Right Knee")

        Returns:
            Category: 'injury', 'rest', 'coach_decision', 'personal', or 'other'
        """
        if not reason_text:
            return None

        reason_lower = str(reason_text).lower()

        # Injury patterns
        if any(word in reason_lower for word in [
            'injury', 'injured', 'illness', 'sprain', 'strain',
            'sore', 'pain', 'surgery', 'concussion', 'knee',
            'ankle', 'back', 'hamstring', 'shoulder', 'hip',
            'foot', 'calf', 'quad', 'groin', 'wrist', 'elbow'
        ]):
            return 'injury'

        # Rest patterns
        if any(word in reason_lower for word in [
            'rest', 'load management', 'recovery', 'maintenance',
            'scheduled rest', 'precautionary'
        ]):
            return 'rest'

        # Personal patterns
        if any(word in reason_lower for word in [
            'personal', 'family', 'birth', 'funeral', 'bereavement'
        ]):
            return 'personal'

        # Coach decision patterns
        if any(word in reason_lower for word in [
            'coach', 'decision', 'not with team', 'suspension',
            'team decision', 'disciplinary'
        ]):
            return 'coach_decision'

        return 'other'

    def _derive_team_abbr(self, row: dict) -> str | None:
        """
        Derive team_abbr from game context when it's NULL in raw data.

        This handles DNP players who sometimes have NULL team_abbr in gamebook extraction.

        Derivation strategy:
        1. Use existing team_abbr if available
        2. Parse from game_id (format: YYYYMMDD_AWAY_HOME) using player's is_home flag
        3. Use source_home_team/source_away_team with is_home flag

        Args:
            row: Data row with game_id, team_abbr, is_home, source_home_team, source_away_team

        Returns:
            Team abbreviation or None if cannot be derived
        """
        # Strategy 1: Use existing team_abbr
        if pd.notna(row.get('team_abbr')) and row['team_abbr']:
            return row['team_abbr']

        # Strategy 2: Parse from game_id (YYYYMMDD_AWAY_HOME format)
        game_id = row.get('game_id', '')
        if game_id and '_' in game_id:
            try:
                parts = game_id.split('_')
                if len(parts) >= 3:
                    away_team = parts[1]  # e.g., 'ATL'
                    home_team = parts[2]  # e.g., 'CHA'

                    # Use is_home flag to determine which team
                    is_home = row.get('is_home')
                    if is_home is True:
                        return home_team
                    elif is_home is False:
                        return away_team

                    # If is_home not available, try source_home/away_team
                    source_home = row.get('source_home_team')
                    source_away = row.get('source_away_team')
                    if source_home and source_home == home_team:
                        return home_team
                    if source_away and source_away == away_team:
                        return away_team
            except Exception:
                pass

        # Strategy 3: Fallback to source team fields with is_home
        is_home = row.get('is_home')
        if is_home is True and pd.notna(row.get('source_home_team')):
            return row['source_home_team']
        elif is_home is False and pd.notna(row.get('source_away_team')):
            return row['source_away_team']

        # Cannot derive - return None
        return None

    def extract_raw_data(self) -> None:
        """
        Extract data with automatic dependency checking and source tracking.

        NEW in v2.0: Proper integration with base class check_dependencies().
        No more manual source tracking!

        NEW in v3.0: Smart reprocessing - skip processing if Phase 2 source unchanged.
        """
        start_date = self.opts['start_date']
        end_date = self.opts['end_date']

        # PRE-EXTRACTION DATA AVAILABILITY CHECK
        # Run a quick COUNT(*) to verify upstream data exists before expensive queries
        source_available, source_count = self._check_source_data_available(start_date, end_date)
        if not source_available:
            # Track the issue for monitoring
            self.track_source_coverage_event(
                event_type=SourceCoverageEventType.SOURCE_MISSING,
                severity=SourceCoverageSeverity.WARNING,
                source='nbac_gamebook_player_stats',
                message=f"No source data available for date range {start_date} to {end_date}",
                details={'record_count': source_count, 'date_range': f"{start_date} to {end_date}"}
            )
            logger.warning(
                f"PRE-EXTRACTION CHECK: No data in nbac_gamebook_player_stats for {start_date} to {end_date}. "
                f"Skipping extraction to avoid expensive queries."
            )
            self.raw_data = pd.DataFrame()
            return

        # Log which source we're using
        if getattr(self, '_use_boxscore_fallback', False):
            logger.info(
                f"PRE-EXTRACTION CHECK: Using BOXSCORE FALLBACK - found {source_count} records "
                f"(gamebook not available, using nbac_player_boxscores for evening processing)"
            )
        else:
            logger.info(f"PRE-EXTRACTION CHECK: Found {source_count} records in gamebook (primary source)")

        # DEPENDENCY CHECKING: Already done in base class run() method!
        # Base class calls check_dependencies() and track_source_usage()
        # before calling this method, so all source_* attributes are populated.

        # TEAM STATS DEPENDENCY VALIDATION (Session 119 - BLOCKING CHECK)
        # Validate team stats exist AND have valid possessions before processing.
        # Prevents NULL usage_rate from timing race conditions.
        is_valid, validation_msg, validation_details = self._validate_team_stats_dependency(start_date, end_date)

        if not is_valid:
            # FAIL EARLY - block processing until dependencies are ready
            error_msg = f"DEPENDENCY VALIDATION FAILED: {validation_msg}"
            logger.error(error_msg)
            logger.error(f"Validation details: {validation_details}")

            # Track the issue for monitoring
            self.track_source_coverage_event(
                event_type=SourceCoverageEventType.DEPENDENCY_STALE,
                severity=SourceCoverageSeverity.ERROR,  # Elevated to ERROR (was WARNING)
                source='team_offense_game_summary',
                message=validation_msg,
                details=validation_details
            )

            # Raise exception to block processing
            raise ValueError(
                f"Cannot process player stats without valid team stats. {validation_msg}\n"
                f"Resolution: Run TeamOffenseGameSummaryProcessor for date range {start_date} to {end_date} first."
            )

        # Validation passed - log success
        logger.info(f"✅ DEPENDENCY VALIDATION PASSED: {validation_msg}")
        logger.info(f"Team stats details: {validation_details}")

        # Keep legacy check for backward compatibility (monitoring only)
        team_stats_available, team_stats_count = self._check_team_stats_available(start_date, end_date)
        self._team_stats_available = team_stats_available

        # SMART REPROCESSING: Check if we can skip processing
        skip, reason = self.should_skip_processing(start_date)
        if skip:
            logger.info(f"SMART REPROCESSING: Skipping processing - {reason}")
            self.raw_data = pd.DataFrame()
            return

        logger.info(f"PROCESSING: {reason}")

        # ═══════════════════════════════════════════════════════════════
        # SELECTIVE PROCESSING (v1.1 Feature)
        # ═══════════════════════════════════════════════════════════════
        # If incremental mode, only process changed players
        # Otherwise, process all players
        # ═══════════════════════════════════════════════════════════════
        player_filter_clause = ""
        if self.is_incremental_run and self.entities_changed:
            # Build IN clause for changed players
            changed_players_list = "', '".join(self.entities_changed)
            player_filter_clause = f"AND player_lookup IN ('{changed_players_list}')"
            logger.info(
                f"🎯 INCREMENTAL: Filtering query to {len(self.entities_changed)} changed players"
            )
        else:
            logger.info("📊 FULL BATCH: Processing all players")

        # Just extract the data
        query = f"""
        WITH nba_com_data AS (
            SELECT
                game_id,
                game_date,
                season_year,
                player_lookup,
                player_name as player_full_name,
                team_abbr,
                player_status,
                dnp_reason,  -- DNP reason text from gamebook
                -- Team context from source (avoids game_id parsing)
                home_team_abbr as source_home_team,
                away_team_abbr as source_away_team,

                -- Core stats
                points,
                assists,
                total_rebounds,
                offensive_rebounds,
                defensive_rebounds,
                steals,
                blocks,
                turnovers,
                personal_fouls,

                -- Shooting stats
                field_goals_made,
                field_goals_attempted,
                three_pointers_made,
                three_pointers_attempted,
                free_throws_made,
                free_throws_attempted,

                -- Game context
                minutes,
                plus_minus,

                -- Metadata
                processed_at as source_processed_at,
                'nbac_gamebook' as primary_source

            FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
                AND player_status IN ('active', 'dnp', 'inactive')  -- Include DNP players
                {player_filter_clause}
        ),
        
        bdl_data AS (
            SELECT
                game_id,
                game_date,
                season_year,
                player_lookup,
                player_full_name,
                team_abbr,
                'active' as player_status,
                CAST(NULL AS STRING) as dnp_reason,  -- BDL doesn't have DNP reason
                -- Team context: NULL for bdl, will be parsed from game_id
                CAST(NULL AS STRING) as source_home_team,
                CAST(NULL AS STRING) as source_away_team,

                -- Core stats
                points,
                assists,
                rebounds as total_rebounds,
                NULL as offensive_rebounds,
                NULL as defensive_rebounds,
                steals,
                blocks,
                turnovers,
                personal_fouls,

                -- Shooting stats (BDL now has all these fields as of 2024)
                field_goals_made,
                field_goals_attempted,
                three_pointers_made,
                three_pointers_attempted,
                free_throws_made,
                free_throws_attempted,

                -- Game context
                minutes,
                NULL as plus_minus,

                -- Metadata
                processed_at as source_processed_at,
                'bdl_boxscores' as primary_source
                
            FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
                {player_filter_clause}
        ),

        -- NBA.com Live Boxscores (FALLBACK - for evening processing)
        -- ENABLED 2026-02-02: Use when gamebook not available yet
        -- Only includes Final games (game_status = 'Final')
        nbac_boxscore_data AS (
            SELECT
                game_id,
                game_date,
                season_year,
                player_lookup,
                player_full_name,
                team_abbr,
                'active' as player_status,  -- Boxscores don't have DNP - those players aren't in the data
                CAST(NULL AS STRING) as dnp_reason,
                -- Team context from boxscore
                home_team_abbr as source_home_team,
                away_team_abbr as source_away_team,

                -- Core stats
                points,
                assists,
                total_rebounds,
                offensive_rebounds,
                defensive_rebounds,
                steals,
                blocks,
                turnovers,
                personal_fouls,

                -- Shooting stats
                field_goals_made,
                field_goals_attempted,
                three_pointers_made,
                three_pointers_attempted,
                free_throws_made,
                free_throws_attempted,

                -- Game context (minutes is STRING in boxscores, need to handle)
                minutes,
                plus_minus,

                -- Metadata
                processed_at as source_processed_at,
                'nbac_boxscores' as primary_source

            FROM `{self.project_id}.nba_raw.nbac_player_boxscores`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
                AND game_status = 'Final'  -- Only completed games
                {player_filter_clause}
        ),

        -- Combine with NBA.com priority (player-level merge)
        -- Priority: gamebook > boxscores > BDL
        -- CRITICAL FIX (2026-01-27): Changed from game-level to player-level merge
        --   Previously excluded 119 players/day including Jayson Tatum, Kyrie Irving, etc.
        -- DISABLED (2026-01-28): BDL data quality issues - using NBA.com only
        --   BDL returns ~50% of actual minutes/points for many players
        --   Set USE_BDL_DATA = True to re-enable
        -- ENABLED (2026-02-02): nbac_player_boxscores as evening fallback
        combined_data AS (
            {"-- Using boxscore fallback (gamebook not available)" if getattr(self, '_use_boxscore_fallback', False) else "-- All NBA.com gamebook data (primary source)"}
            SELECT * FROM {"nbac_boxscore_data" if getattr(self, '_use_boxscore_fallback', False) else "nba_com_data"}
            {"" if self.USE_BDL_DATA else "-- BDL DISABLED: Data quality issues (2026-01-28)"}
            {'''
            UNION ALL

            -- BDL data for players NOT in NBA.com (fills gaps)
            -- This ensures players like Jayson Tatum who may only be in BDL are included
            SELECT * FROM bdl_data bd
            WHERE NOT EXISTS (
                SELECT 1 FROM nba_com_data nc
                WHERE nc.game_id = bd.game_id
                  AND nc.player_lookup = bd.player_lookup
            )
            ''' if self.USE_BDL_DATA else ''}
        ),

        -- Deduplicate combined data (prevents duplicates from source overlap)
        -- Keeps most recent record by source_processed_at timestamp
        deduplicated_combined AS (
            SELECT * EXCEPT(rn) FROM (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY game_id, player_lookup
                        ORDER BY source_processed_at DESC
                    ) as rn
                FROM combined_data
            ) WHERE rn = 1
        ),

        -- Deduplicate props: DraftKings first, then FanDuel, then others
        deduplicated_props AS (
            SELECT
                game_id,
                player_lookup,
                points_line,
                over_price_american,
                under_price_american,
                bookmaker,
                ROW_NUMBER() OVER (
                    PARTITION BY game_id, player_lookup
                    ORDER BY
                        CASE bookmaker
                            WHEN 'draftkings' THEN 1
                            WHEN 'fanduel' THEN 2
                            ELSE 3
                        END,
                        bookmaker
                ) as rn
            FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
            WHERE game_id IN (SELECT DISTINCT game_id FROM deduplicated_combined)
        ),

        -- Add props context
        with_props AS (
            SELECT
                c.*,
                p.points_line,
                p.over_price_american,
                p.under_price_american,
                p.bookmaker as points_line_source
            FROM deduplicated_combined c
            LEFT JOIN deduplicated_props p
                ON c.game_id = p.game_id
                AND c.player_lookup = p.player_lookup
                AND p.rn = 1
        ),
        
        -- Add opponent context
        -- Expected game_id format: YYYYMMDD_AWAY_HOME (e.g., "20251229_ATL_OKC")
        -- See: shared/utils/game_id_converter.py for standard format
        --
        -- Strategy:
        -- 1. Prefer source_home_team/source_away_team from nbac_gamebook (most reliable)
        -- 2. Fall back to parsing game_id (handles BDL data and any edge cases)
        -- SAFE_OFFSET used for backward compatibility with old non-standard game_ids
        games_context AS (
            SELECT DISTINCT
                game_id,
                game_date,
                source_home_team,
                source_away_team,
                -- Use source data if available, else parse from game_id
                COALESCE(
                    source_away_team,
                    CASE WHEN game_id LIKE '%_%_%' THEN SPLIT(game_id, '_')[SAFE_OFFSET(1)] END
                ) as away_team_abbr,
                COALESCE(
                    source_home_team,
                    CASE WHEN game_id LIKE '%_%_%' THEN SPLIT(game_id, '_')[SAFE_OFFSET(2)] END
                ) as home_team_abbr
            FROM deduplicated_combined
        ),

        -- Team stats for usage_rate calculation
        -- Note: game_id format may differ (Away_Home vs Home_Away), so we add reversed format for matching
        -- IMPORTANT: Use ROW_NUMBER to prefer gold > silver quality when duplicates exist with different game_ids
        team_stats_raw AS (
            SELECT
                game_id,
                -- Also compute reversed game_id for matching (handles format mismatch)
                CASE
                    WHEN game_id LIKE '%_%_%' THEN
                        CONCAT(
                            SUBSTR(game_id, 1, 9),  -- date prefix (YYYYMMDD_)
                            SPLIT(game_id, '_')[OFFSET(2)], '_',  -- swap team positions
                            SPLIT(game_id, '_')[OFFSET(1)]
                        )
                    ELSE game_id
                END as game_id_reversed,
                team_abbr,
                fg_attempts as team_fg_attempts,
                ft_attempts as team_ft_attempts,
                turnovers as team_turnovers,
                possessions as team_possessions,
                quality_tier,
                -- Rank by quality tier (gold > silver > bronze) to pick best when duplicates exist
                ROW_NUMBER() OVER (
                    PARTITION BY
                        game_date,
                        -- Normalize game_id by sorting team abbrs alphabetically
                        CASE
                            WHEN SPLIT(game_id, '_')[SAFE_OFFSET(1)] < SPLIT(game_id, '_')[SAFE_OFFSET(2)]
                            THEN CONCAT(SUBSTR(game_id, 1, 9), SPLIT(game_id, '_')[SAFE_OFFSET(1)], '_', SPLIT(game_id, '_')[SAFE_OFFSET(2)])
                            ELSE CONCAT(SUBSTR(game_id, 1, 9), SPLIT(game_id, '_')[SAFE_OFFSET(2)], '_', SPLIT(game_id, '_')[SAFE_OFFSET(1)])
                        END,
                        team_abbr
                    ORDER BY
                        CASE quality_tier WHEN 'gold' THEN 1 WHEN 'silver' THEN 2 WHEN 'bronze' THEN 3 ELSE 4 END,
                        possessions DESC  -- Prefer higher possession count (more complete data)
                ) as quality_rank
            FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
        ),
        -- Only keep the best quality record for each game+team combination
        team_stats AS (
            SELECT game_id, game_id_reversed, team_abbr, team_fg_attempts, team_ft_attempts, team_turnovers, team_possessions
            FROM team_stats_raw
            WHERE quality_rank = 1
        )

        SELECT
            wp.*,
            gc.away_team_abbr,
            gc.home_team_abbr,
            -- Team stats for usage_rate (will be NULL if team_offense_game_summary unavailable)
            ts.team_fg_attempts,
            ts.team_ft_attempts,
            ts.team_turnovers,
            ts.team_possessions,
            COALESCE(
                CASE
                    WHEN wp.team_abbr = gc.home_team_abbr THEN gc.away_team_abbr
                    ELSE gc.home_team_abbr
                END,
                ''  -- Default to empty string when NULL (handles non-standard game_ids from BDL)
            ) as opponent_team_abbr,
            CASE
                WHEN wp.team_abbr = gc.home_team_abbr THEN TRUE
                ELSE FALSE
            END as home_game

        FROM with_props wp
        LEFT JOIN games_context gc ON wp.game_id = gc.game_id
        -- Join on either exact game_id OR reversed format (handles Away_Home vs Home_Away mismatch)
        LEFT JOIN team_stats ts ON (wp.game_id = ts.game_id OR wp.game_id = ts.game_id_reversed)
            AND wp.team_abbr = ts.team_abbr
        ORDER BY wp.game_date DESC, wp.game_id, wp.player_lookup
        """

        logger.info(f"Extracting data for {start_date} to {end_date}")

        # SESSION 119: Disable BigQuery cache for regenerations
        # Prevents stale cached JOIN results when team stats are updated
        job_config = bigquery.QueryJobConfig()
        if self.opts.get('backfill_mode', False):
            job_config.use_query_cache = False
            logger.info("🔄 REGENERATION MODE: BigQuery cache disabled (prevents stale JOIN results)")

        try:
            self.raw_data = self.bq_client.query(query, job_config=job_config).to_dataframe()
            logger.info(f"✅ Extracted {len(self.raw_data)} player-game records")
            
            if not self.raw_data.empty:
                source_counts = self.raw_data['primary_source'].value_counts()
                logger.info(f"Source distribution: {dict(source_counts)}")
            else:
                logger.warning(f"⚠️ No data extracted for {start_date} to {end_date}")
                try:
                    notify_warning(
                        title="Player Game Summary: No Data Extracted",
                        message=f"No player-game records found for {start_date} to {end_date}",
                        details={
                            'processor': 'player_game_summary',
                            'start_date': start_date,
                            'end_date': end_date
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                    
        except Exception as e:
            logger.error(f"BigQuery extraction failed: {e}")
            raise

        # Extract shot zones from play-by-play (Pass 2 enrichment)
        if not self.raw_data.empty:
            self.shot_zone_analyzer.extract_shot_zones(start_date, end_date)

            # Persist games that need BDB re-run when data becomes available
            pending_count = self.shot_zone_analyzer.persist_pending_bdb_games()
            if pending_count > 0:
                logger.warning(
                    f"⚠️ {pending_count} games added to pending_bdb_games table "
                    f"(missing BigDataBall data, will retry when available)"
                )

    def validate_extracted_data(self) -> None:
        """Enhanced validation with cross-source quality checks."""
        super().validate_extracted_data()

        # Handle case where base class returned early (data exists via alternate source)
        if self.raw_data is None or self.raw_data.empty:
            return
        
        # Clean data types before validation
        self._clean_numeric_columns()
        
        # Run validation suite
        self._validate_critical_fields()
        self._validate_player_data()
        self._validate_statistical_integrity()
        
        logger.info("✅ Validation complete")
    
    def _clean_numeric_columns(self) -> None:
        """Ensure numeric columns have consistent data types."""
        numeric_columns = [
            'points', 'assists', 'field_goals_made', 'field_goals_attempted',
            'three_pointers_made', 'three_pointers_attempted', 'free_throws_made',
            'free_throws_attempted', 'steals', 'blocks', 'turnovers', 'personal_fouls',
            'total_rebounds', 'offensive_rebounds', 'defensive_rebounds', 'season_year'
        ]
        # NOTE: 'minutes' is NOT included because it's in "MM:SS" format and must be
        # parsed by _parse_minutes_to_decimal() later, not coerced to numeric here
        
        for col in numeric_columns:
            if col in self.raw_data.columns:
                self.raw_data[col] = pd.to_numeric(self.raw_data[col], errors='coerce')
        
        # Handle plus_minus separately (can have '+' prefix)
        if 'plus_minus' in self.raw_data.columns:
            self.raw_data['plus_minus'] = self.raw_data['plus_minus'].astype(str).str.replace('+', '')
            self.raw_data['plus_minus'] = pd.to_numeric(self.raw_data['plus_minus'], errors='coerce')
    
    def _validate_critical_fields(self) -> None:
        """Check for missing critical fields."""
        critical_fields = ['game_id', 'player_lookup', 'points', 'team_abbr']
        
        for field in critical_fields:
            # Use isna() and convert to int to handle pd.NA gracefully
            null_count = int(self.raw_data[field].isna().sum())
            if null_count > 0:
                logger.warning(f"⚠️ {field}: {null_count} null values ({null_count/len(self.raw_data)*100:.1f}%)")
    
    def _validate_player_data(self) -> None:
        """Validate player names and lookups."""
        # Check for duplicates
        duplicates = self.raw_data.groupby(['game_id', 'player_lookup']).size()
        duplicate_records = duplicates[duplicates > 1]
        
        if not duplicate_records.empty:
            logger.warning(f"⚠️ Found {len(duplicate_records)} duplicate player-game records")
    
    def _validate_statistical_integrity(self) -> None:
        """Check for statistical anomalies in shooting stats."""
        
        # Check Field Goals
        if 'field_goals_made' in self.raw_data.columns:
            valid_fg = self.raw_data[
                (self.raw_data['field_goals_made'].notna()) &
                (self.raw_data['field_goals_attempted'].notna())
            ]
            
            if not valid_fg.empty:
                impossible = valid_fg[
                    valid_fg['field_goals_made'] > valid_fg['field_goals_attempted']
                ]
                
                if not impossible.empty:
                    logger.warning(f"⚠️ Found {len(impossible)} records with FGM > FGA")
        
        # Check Three-Pointers (NEW)
        if 'three_pointers_made' in self.raw_data.columns:
            valid_3pt = self.raw_data[
                (self.raw_data['three_pointers_made'].notna()) &
                (self.raw_data['three_pointers_attempted'].notna())
            ]
            
            if not valid_3pt.empty:
                impossible_3pt = valid_3pt[
                    valid_3pt['three_pointers_made'] > valid_3pt['three_pointers_attempted']
                ]
                
                if not impossible_3pt.empty:
                    logger.warning(f"⚠️ Found {len(impossible_3pt)} records with 3PM > 3PA")
        
        # Check Free Throws (NEW)
        if 'free_throws_made' in self.raw_data.columns:
            valid_ft = self.raw_data[
                (self.raw_data['free_throws_made'].notna()) &
                (self.raw_data['free_throws_attempted'].notna())
            ]
            
            if not valid_ft.empty:
                impossible_ft = valid_ft[
                    valid_ft['free_throws_made'] > valid_ft['free_throws_attempted']
                ]
                
                if not impossible_ft.empty:
                    logger.warning(f"⚠️ Found {len(impossible_ft)} records with FTM > FTA")
    
    def calculate_analytics(self) -> None:
        """
        Calculate analytics with full source tracking.

        Key features in v2.0:
        - Universal player ID via PlayerRegistryHandler (batch lookup)
        - Source tracking via **self.build_source_tracking_fields()
        - No manual attribute setting!
        """
        # =====================================================================
        # GUARD: Handle empty raw_data before processing
        # =====================================================================
        # This can happen when:
        # 1. should_skip_processing() returns True (sets raw_data = pd.DataFrame())
        # 2. Incremental filter returns no matching players
        # 3. Source data is genuinely empty
        # In all cases, we should return early with empty results, not fail.
        if self.raw_data is None or self.raw_data.empty or 'player_lookup' not in self.raw_data.columns:
            logger.info(
                "⏭️  No data to process - raw_data is empty or missing columns. "
                "Returning empty results."
            )
            self.transformed_data = []
            self.stats['skipped_reason'] = 'no_data_to_process'
            return

        # =====================================================================
        # REGISTRY: Batch lookup for universal player IDs
        # =====================================================================
        logger.info("Looking up universal player IDs...")

        season_year = None
        if not self.raw_data.empty and 'season_year' in self.raw_data.columns:
            season_year = int(self.raw_data['season_year'].mode()[0])

        unique_players = self.raw_data['player_lookup'].dropna().unique().tolist()
        uid_map = self.registry_handler.batch_lookup_universal_ids(
            unique_players,
            season_year=season_year
        )
        
        # =====================================================================
        # Process records - PARALLEL OR SERIAL based on environment variable
        # =====================================================================
        ENABLE_PARALLELIZATION = os.environ.get('ENABLE_PLAYER_PARALLELIZATION', 'true').lower() == 'true'

        if ENABLE_PARALLELIZATION:
            records = self._process_player_games_parallel(uid_map)
        else:
            records = self._process_player_games_serial(uid_map)

        self.transformed_data = records

        stats = self.registry_handler.get_stats()
        logger.info(f"✅ Processed {len(records)} records")
        logger.info(f"⚠️ Skipped {stats['registry_records_skipped']} (no registry match)")

        # Save failure records to BigQuery for observability (v2.1 feature)
        failures = self.registry_handler.get_failures()
        if failures:
            self.save_registry_failures(failures)

    def _parse_minutes_to_decimal(self, minutes_str: str) -> Optional[float]:
        """
        Parse minutes string to decimal format (40:11 → 40.18).

        Handles multiple formats:
        - "MM:SS" (e.g., "04:00", "14:21") → decimal (4.0, 14.35)
        - Integer string (e.g., "32") → float (32.0)
        - Float string (e.g., "32.5") → float (32.5)
        - NULL/empty/"-" → None

        Robust handling for whitespace, type issues, encoding problems.
        """
        # Handle NULL, None, NaN, empty string
        if minutes_str is None or pd.isna(minutes_str):
            return None

        # Convert to string and strip whitespace (handles bytes, int, float types)
        try:
            minutes_clean = str(minutes_str).strip()
        except Exception as e:
            logger.warning(f"Failed to convert minutes to string: {repr(minutes_str)} (type: {type(minutes_str)}): {e}")
            return None

        # Handle empty or dash
        if not minutes_clean or minutes_clean == '-' or minutes_clean.lower() == 'null':
            return None

        try:
            # Handle "MM:SS" format (e.g., "04:00", "14:21", "40:11")
            if ':' in minutes_clean:
                parts = minutes_clean.split(':')
                if len(parts) == 2:
                    # Strip each part to handle " 04 : 00 " cases
                    mins_str = parts[0].strip()
                    secs_str = parts[1].strip()

                    # Convert to integers
                    mins = int(mins_str)
                    secs = int(secs_str)

                    # Validate ranges
                    if secs < 0 or secs >= 60:
                        logger.warning(f"Invalid seconds value in minutes: {repr(minutes_str)} (seconds={secs}, expected 0-59)")
                        return None

                    if mins < 0 or mins > 60:
                        logger.warning(f"Suspicious minutes value: {repr(minutes_str)} (mins={mins}, expected 0-60)")
                        # Don't return None - some overtime games might have > 48 min

                    # Convert to decimal: MM + (SS/60)
                    return round(mins + (secs / 60), 2)
                else:
                    logger.warning(f"Unexpected ':' format in minutes (expected MM:SS): {repr(minutes_str)}")
                    return None

            # Handle plain number (integer or float string)
            return float(minutes_clean)

        except (ValueError, TypeError) as e:
            # This is now a WARNING because it's unexpected - raw data should be clean
            logger.warning(f"Could not parse minutes: {repr(minutes_str)} (cleaned: {repr(minutes_clean)}), type: {type(minutes_str)}, error: {e}")
            return None
        except Exception as e:
            # Catch any other unexpected exceptions
            logger.error(f"Unexpected error parsing minutes: {repr(minutes_str)}, error: {e}")
            return None
    
    def _parse_plus_minus(self, plus_minus_str: str) -> Optional[int]:
        """Parse plus/minus string to integer (+7 → 7)."""
        if pd.isna(plus_minus_str) or not plus_minus_str or plus_minus_str == '-':
            return None
            
        try:
            cleaned = str(plus_minus_str).replace('+', '')
            return int(cleaned)
            
        except (ValueError, TypeError) as e:
            logger.debug(f"Could not parse plus/minus: {plus_minus_str}: {e}")
            return None
    
    def get_analytics_stats(self) -> Dict:
        """Return processing stats for monitoring including data quality metrics."""
        if not self.transformed_data:
            return {}

        stats = self.registry_handler.get_stats() if self._registry_handler else {}

        # Calculate data quality metrics from transformed data (Session 96)
        quality_metrics = self._calculate_quality_metrics()

        return {
            'records_processed': len(self.transformed_data),
            **stats,
            'source_nbac_completeness': getattr(self, 'source_nbac_completeness_pct', None),
            'source_bdl_completeness': getattr(self, 'source_bdl_completeness_pct', None),
            'source_odds_completeness': getattr(self, 'source_odds_completeness_pct', None),
            **quality_metrics
        }

    def _calculate_quality_metrics(self) -> Dict:
        """
        Calculate data quality metrics from transformed data (Session 96).

        Returns metrics about usage_rate and minutes coverage which are
        critical for ML feature quality downstream.
        """
        if not self.transformed_data:
            return {}

        try:
            import pandas as pd

            df = pd.DataFrame(self.transformed_data)
            if df.empty:
                return {}

            # Filter to active players only (exclude DNPs)
            active_df = df[df.get('is_dnp', True) == False] if 'is_dnp' in df.columns else df

            total_active = len(active_df)
            if total_active == 0:
                return {'quality_total_active': 0, 'quality_usage_rate_pct': 0, 'quality_minutes_pct': 0}

            # Count players with usage_rate
            has_usage_rate = active_df['usage_rate'].notna().sum() if 'usage_rate' in active_df.columns else 0
            usage_rate_pct = round(100.0 * has_usage_rate / total_active, 1)

            # Count players with minutes
            has_minutes = (active_df['minutes_played'].notna() & (active_df['minutes_played'] > 0)).sum() if 'minutes_played' in active_df.columns else 0
            minutes_pct = round(100.0 * has_minutes / total_active, 1)

            # Per-game breakdown for detailed logging
            game_count = df['game_id'].nunique() if 'game_id' in df.columns else 0

            return {
                'quality_total_active': total_active,
                'quality_has_usage_rate': int(has_usage_rate),
                'quality_usage_rate_pct': usage_rate_pct,
                'quality_has_minutes': int(has_minutes),
                'quality_minutes_pct': minutes_pct,
                'quality_game_count': game_count,
            }
        except Exception as e:
            logger.warning(f"Failed to calculate quality metrics: {e}")
            return {}

    def save_registry_failures(self, failures: List[Dict]) -> None:
        """
        Save registry failures to BigQuery for observability.

        Args:
            failures: List of registry failure records
        """
        if not failures:
            return

        try:
            table_id = f"{self.project_id}.nba_analytics.registry_failures"
            errors = self.bq_client.insert_rows_json(table_id, failures)
            if errors:
                logger.warning(f"Failed to save registry failures: {errors}")
            else:
                logger.info(f"Saved {len(failures)} registry failure records")
        except Exception as e:
            logger.warning(f"Failed to save registry failures: {e}")
    
    def post_process(self) -> None:
        """Send success notification and run post-processing validations."""
        super().post_process()

        # Validate analytics player counts against boxscores
        self._validate_analytics_player_counts()

        stats = self.get_analytics_stats()

        # Check data quality and alert if issues (Session 96)
        self._check_and_alert_quality(stats)

        # Write quality metrics to tracking table (Session 96)
        self._write_quality_metrics(stats)

        try:
            notify_info(
                title="Player Game Summary: Complete",
                message=f"Processed {stats.get('records_processed', 0)} records",
                details={
                    'processor': 'player_game_summary',
                    'date_range': f"{self.opts['start_date']} to {self.opts['end_date']}",
                    **stats
                },
                processor_name=self.__class__.__name__
            )
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")

    def _check_and_alert_quality(self, stats: Dict) -> None:
        """
        Check data quality metrics and send alerts if below thresholds (Session 96).

        Thresholds:
        - CRITICAL: usage_rate < 50% (should block predictions)
        - WARNING: usage_rate < 80% (degraded quality)
        """
        CRITICAL_THRESHOLD = 50.0
        WARNING_THRESHOLD = 80.0

        usage_rate_pct = stats.get('quality_usage_rate_pct', 100.0)
        minutes_pct = stats.get('quality_minutes_pct', 100.0)
        game_count = stats.get('quality_game_count', 0)

        # Skip if no games processed
        if game_count == 0:
            return

        issues = []

        # Check usage_rate coverage
        if usage_rate_pct < CRITICAL_THRESHOLD:
            issues.append(f"CRITICAL: usage_rate coverage {usage_rate_pct}% < {CRITICAL_THRESHOLD}%")
        elif usage_rate_pct < WARNING_THRESHOLD:
            issues.append(f"WARNING: usage_rate coverage {usage_rate_pct}% < {WARNING_THRESHOLD}%")

        # Check minutes coverage
        if minutes_pct < 80.0:
            issues.append(f"WARNING: minutes coverage {minutes_pct}% < 80%")

        if issues:
            severity = "CRITICAL" if usage_rate_pct < CRITICAL_THRESHOLD else "WARNING"
            logger.warning(
                f"DATA_QUALITY_{severity}: {', '.join(issues)} | "
                f"games={game_count}, active={stats.get('quality_total_active', 0)}"
            )

            # Send Slack alert for critical issues
            if usage_rate_pct < CRITICAL_THRESHOLD:
                try:
                    notify_warning(
                        title=f"Player Game Summary: Data Quality {severity}",
                        message=f"usage_rate coverage is {usage_rate_pct}% (threshold: {CRITICAL_THRESHOLD}%)",
                        details={
                            'processor': 'player_game_summary',
                            'date_range': f"{self.opts.get('start_date')} to {self.opts.get('end_date')}",
                            'issues': issues,
                            'usage_rate_pct': usage_rate_pct,
                            'minutes_pct': minutes_pct,
                            'game_count': game_count,
                            'total_active': stats.get('quality_total_active', 0),
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as e:
                    logger.warning(f"Failed to send quality alert: {e}")
        else:
            logger.info(
                f"DATA_QUALITY_OK: usage_rate={usage_rate_pct}%, minutes={minutes_pct}%, "
                f"games={game_count}, active={stats.get('quality_total_active', 0)}"
            )

    def _write_quality_metrics(self, stats: Dict) -> None:
        """
        Write quality metrics to tracking table for historical analysis (Session 96).

        Table: nba_analytics.data_quality_history
        """
        try:
            # Build quality record
            record = {
                'check_timestamp': datetime.now(timezone.utc).isoformat(),
                'check_date': self.opts.get('end_date', self.opts.get('start_date')),
                'processor': 'player_game_summary',
                'game_count': stats.get('quality_game_count', 0),
                'total_active_players': stats.get('quality_total_active', 0),
                'usage_rate_coverage_pct': stats.get('quality_usage_rate_pct', 0),
                'minutes_coverage_pct': stats.get('quality_minutes_pct', 0),
                'records_processed': stats.get('records_processed', 0),
                'run_id': getattr(self, 'run_id', None),
            }

            # Write to BigQuery (create table if not exists)
            table_id = f"{self.project_id}.nba_analytics.data_quality_history"

            try:
                errors = self.bq_client.insert_rows_json(table_id, [record])
                if errors:
                    logger.warning(f"Failed to write quality metrics: {errors}")
                else:
                    logger.debug(f"Wrote quality metrics to {table_id}")
            except NotFound:
                # Table doesn't exist yet - log but don't fail
                logger.info(f"Quality history table {table_id} not found - skipping metrics write")
            except Exception as e:
                logger.warning(f"Failed to write quality metrics: {e}")

        except Exception as e:
            logger.warning(f"Failed to build quality metrics record: {e}")

    def _validate_analytics_player_counts(self) -> None:
        """
        Validate analytics player counts against boxscore player counts.

        Catches cases like NYK@PHI (19 analytics vs 34 boxscore) where
        analytics processor skipped some players.

        Logs warnings for games where analytics_count < boxscore_count * 0.9
        (allowing 10% variance for legitimate reasons like DNPs).
        """
        if not self.transformed_data:
            return

        start_date = self.opts.get('start_date')
        end_date = self.opts.get('end_date')

        try:
            # Query to compare analytics vs boxscore player counts per game
            query = f"""
            WITH analytics_counts AS (
                SELECT game_id, COUNT(DISTINCT player_lookup) as analytics_count
                FROM `{self.project_id}.nba_analytics.player_game_summary`
                WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
                GROUP BY game_id
            ),
            boxscore_counts AS (
                SELECT game_id, COUNT(DISTINCT player_lookup) as boxscore_count
                FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
                WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
                GROUP BY game_id
            )
            SELECT
                COALESCE(b.game_id, a.game_id) as game_id,
                COALESCE(a.analytics_count, 0) as analytics_count,
                COALESCE(b.boxscore_count, 0) as boxscore_count,
                SAFE_DIVIDE(a.analytics_count, b.boxscore_count) as coverage_ratio
            FROM boxscore_counts b
            FULL OUTER JOIN analytics_counts a ON b.game_id = a.game_id
            WHERE SAFE_DIVIDE(a.analytics_count, b.boxscore_count) < 0.9
               OR a.analytics_count IS NULL
            ORDER BY coverage_ratio ASC
            """

            result = self.bq_client.query(query).result()
            gaps = list(result)

            if gaps:
                logger.warning(
                    f"⚠️ Analytics player count gaps detected for {len(gaps)} game(s):"
                )
                for row in gaps:
                    coverage_pct = (row.coverage_ratio * 100) if row.coverage_ratio else 0
                    logger.warning(
                        f"  - {row.game_id}: {row.analytics_count} analytics vs {row.boxscore_count} boxscore "
                        f"({coverage_pct:.0f}% coverage)"
                    )

                # Send alert for significant gaps (< 80% coverage)
                significant_gaps = [g for g in gaps if not g.coverage_ratio or g.coverage_ratio < 0.8]
                if significant_gaps:
                    self._send_player_count_gap_alert(significant_gaps)
            else:
                logger.info("✅ Analytics player count validation passed (all games ≥90% coverage)")

        except Exception as e:
            logger.warning(f"Failed to validate analytics player counts: {e}")

    def _send_player_count_gap_alert(self, gaps: list) -> bool:
        """Send Slack alert for significant analytics player count gaps."""
        import os
        import requests

        slack_webhook = os.environ.get('SLACK_WEBHOOK_URL')
        if not slack_webhook:
            return False

        try:
            start_date = self.opts.get('start_date')
            end_date = self.opts.get('end_date')

            gaps_text = "\n".join([
                f"• {g.game_id}: {g.analytics_count}/{g.boxscore_count} players "
                f"({int((g.coverage_ratio or 0) * 100)}%)"
                for g in gaps[:5]
            ])
            if len(gaps) > 5:
                gaps_text += f"\n• ... and {len(gaps) - 5} more"

            payload = {
                "attachments": [{
                    "color": "#FF9800",  # Orange for warning
                    "blocks": [
                        {
                            "type": "header",
                            "text": {
                                "type": "plain_text",
                                "text": ":warning: Analytics Player Count Gaps Detected",
                                "emoji": True
                            }
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"*{len(gaps)} game(s) have significantly fewer analytics players than boxscores*\n"
                                       f"This may indicate players were skipped during processing."
                            }
                        },
                        {
                            "type": "section",
                            "fields": [
                                {"type": "mrkdwn", "text": f"*Date Range:*\n{start_date} to {end_date}"},
                                {"type": "mrkdwn", "text": f"*Affected Games:*\n{len(gaps)}"},
                            ]
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"*Games with <80% coverage:*\n```{gaps_text}```"
                            }
                        },
                        {
                            "type": "context",
                            "elements": [{
                                "type": "mrkdwn",
                                "text": ":bulb: Check registry for unresolved players. May need to add player aliases."
                            }]
                        }
                    ]
                }]
            }

            response = requests.post(slack_webhook, json=payload, timeout=10)
            response.raise_for_status()
            logger.info(f"Player count gap alert sent for {len(gaps)} games")
            return True

        except Exception as e:
            logger.warning(f"Failed to send player count gap alert: {e}")
            return False
    
    def finalize(self) -> None:
        """Cleanup - flush unresolved players and save failures."""
        logger.info("Flushing unresolved players...")

        try:
            self.registry_handler.flush_unresolved_players()
            cache_stats = self.registry_handler.get_cache_stats()
            logger.info(f"Registry cache: {cache_stats['hit_rate']:.1%} hit rate")
        except Exception as e:
            logger.error(f"Failed to flush registry: {e}")

        # Convert registry_failures to unified failure tracking format
        # This enables enhanced failure tracking with DNP classification
        if hasattr(self, 'registry_failures') and self.registry_failures:
            for failure in self.registry_failures:
                self.record_failure(
                    entity_id=failure.get('player_lookup', 'unknown'),
                    entity_type='PLAYER',
                    category='REGISTRY_LOOKUP_FAILED',
                    reason=f"Player not found in registry for game {failure.get('game_id', 'unknown')}",
                    can_retry=True,  # Can retry after adding alias
                    missing_game_ids=[failure.get('game_id')] if failure.get('game_id') else None
                )
            logger.info(f"Converted {len(self.registry_failures)} registry failures to unified tracking")

        # Call parent finalize() which saves failures to analytics_failures table
        super().finalize()

    # =========================================================================
    # Parallelization Methods
    # =========================================================================

    def _process_player_games_parallel(self, uid_map: dict) -> List[Dict]:
        """Process all player-game records using ThreadPoolExecutor."""
        # Determine worker count with environment variable support
        DEFAULT_WORKERS = 10
        max_workers = int(os.environ.get(
            'PGS_WORKERS',
            os.environ.get('PARALLELIZATION_WORKERS', DEFAULT_WORKERS)
        ))
        max_workers = min(max_workers, os.cpu_count() or 1)
        total_records = len(self.raw_data)
        logger.info(f"Processing {total_records} player-game records with {max_workers} workers (parallel mode)")

        loop_start = time.time()
        processed_count = 0
        records = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all rows
            futures = {
                executor.submit(self._process_single_player_game, idx, row, uid_map): idx
                for idx, row in self.raw_data.iterrows()
            }

            for future in as_completed(futures):
                idx = futures[future]
                processed_count += 1

                try:
                    record = future.result()
                    if record is not None:
                        records.append(record)

                    # Progress logging every 50 records
                    if processed_count % 50 == 0:
                        elapsed = time.time() - loop_start
                        rate = processed_count / elapsed
                        remaining = total_records - processed_count
                        eta = remaining / rate if rate > 0 else 0
                        logger.info(
                            f"Player-game processing progress: {processed_count}/{total_records} "
                            f"| Rate: {rate:.1f} records/sec | ETA: {eta/60:.1f}min"
                        )
                except Exception as e:
                    logger.error(f"Error processing record {idx}: {e}")
                    continue

        total_time = time.time() - loop_start
        logger.info(
            f"Completed {len(records)} records in {total_time:.1f}s "
            f"(avg {total_time/len(records) if records else 0:.2f}s/record)"
        )

        return records

    def _process_single_player_game(self, idx: int, row: pd.Series, uid_map: dict) -> Optional[Dict]:
        """Process one player-game record (thread-safe). Returns record dict or None."""
        try:
            player_lookup = row['player_lookup']
            universal_player_id = uid_map.get(player_lookup)

            if universal_player_id is None:
                # Log unresolved player with game context
                game_context = {
                    'game_id': row['game_id'],
                    'game_date': row['game_date'].isoformat() if pd.notna(row['game_date']) else None,
                    'season': f"{int(row['season_year'])}-{str(int(row['season_year']) + 1)[-2:]}" if pd.notna(row['season_year']) else None,
                    'team_abbr': row['team_abbr'] if pd.notna(row['team_abbr']) else None,
                    'source': 'player_game_summary'
                }
                self.registry_handler.log_unresolved_player(player_lookup, game_context)

                # Track failure for observability (v2.1 feature)
                self.registry_handler.track_registry_failure(
                    player_lookup=player_lookup,
                    game_date=row['game_date'],
                    team_abbr=row['team_abbr'] if pd.notna(row['team_abbr']) else None,
                    season_year=int(row['season_year']) if pd.notna(row['season_year']) else None,
                    game_id=row['game_id']
                )
                return None

            # Parse minutes
            # Use 'is not None' to handle 0.0 correctly (0 minutes is valid, not missing)
            minutes_decimal = self._parse_minutes_to_decimal(row['minutes'])
            # Session 109: Preserve decimal precision (schema is NUMERIC(5,1))
            # Round to 1 decimal place instead of rounding to integer
            minutes_int = round(minutes_decimal, 1) if minutes_decimal is not None else None

            # Parse plus/minus
            plus_minus_int = self._parse_plus_minus(row['plus_minus'])

            # Calculate efficiency
            ts_pct = None
            efg_pct = None

            if (pd.notna(row['field_goals_attempted']) and
                row['field_goals_attempted'] > 0):

                fga = row['field_goals_attempted']
                three_makes = row['three_pointers_made'] if pd.notna(row['three_pointers_made']) else 0

                efg_pct = (row['field_goals_made'] + 0.5 * three_makes) / fga

                if pd.notna(row['free_throws_attempted']):
                    fta = row['free_throws_attempted']
                    total_shots = fga + 0.44 * fta
                    if total_shots > 0:
                        ts_pct = row['points'] / (2 * total_shots)

            # Calculate usage_rate (requires team stats for THIS game)
            # Session 96: Changed from global threshold to per-game calculation
            # If team stats exist for THIS game (via JOIN), calculate usage_rate
            # If not, leave NULL only for this game's players (not ALL players)
            usage_rate = None
            has_team_stats_for_game = (
                pd.notna(row.get('team_fg_attempts')) and
                pd.notna(row.get('team_ft_attempts')) and
                pd.notna(row.get('team_turnovers'))
            )
            if (has_team_stats_for_game and
                pd.notna(row['field_goals_attempted']) and
                pd.notna(row['turnovers']) and
                minutes_decimal and minutes_decimal > 0):

                # Player usage components
                player_fga = row['field_goals_attempted']
                player_fta_val = row.get('free_throws_attempted', 0)
                player_fta = player_fta_val if pd.notna(player_fta_val) else 0
                player_to = row['turnovers']
                player_poss_used = player_fga + 0.44 * player_fta + player_to

                # Team usage components
                team_fga = row['team_fg_attempts']
                team_fta = row['team_ft_attempts']
                team_to = row['team_turnovers']
                team_poss_used = team_fga + 0.44 * team_fta + team_to

                # Usage Rate formula (assumes 48 min team total / 5 players = 240 min shared)
                # USG% = 100 × (Player FGA + 0.44 × Player FTA + Player TO) × (Tm Min / 5)
                #            / (Player Min × (Tm FGA + 0.44 × Tm FTA + Tm TO))
                # Approximation: Tm Min ≈ 240 (48 min × 5 players)
                if team_poss_used > 0:
                    usage_rate = 100.0 * player_poss_used * 48.0 / (minutes_decimal * team_poss_used)
                    # Sanity check: usage_rate > 100% indicates data quality issue (e.g., incomplete team stats)
                    # Log warning but don't reject - set to None so downstream can handle gracefully
                    if usage_rate > 100.0:
                        logger.warning(
                            f"Impossible usage_rate {usage_rate:.1f}% for {player_lookup} in {row['game_id']} - "
                            f"likely incomplete team stats (team_poss={team_poss_used:.1f}, player_poss={player_poss_used:.1f})"
                        )
                        usage_rate = None  # Set to None rather than store invalid value

            # Derive team_abbr with fallback logic for DNP players
            # (Session 46: Fix for NULL team_abbr in raw gamebook data)
            derived_team_abbr = self._derive_team_abbr(row)

            # Derive opponent_team_abbr based on team_abbr and game context
            derived_opponent_abbr = row.get('opponent_team_abbr')
            if not derived_opponent_abbr and derived_team_abbr:
                # Parse from game_id: YYYYMMDD_AWAY_HOME
                game_id = row.get('game_id', '')
                if game_id and '_' in game_id:
                    try:
                        parts = game_id.split('_')
                        if len(parts) >= 3:
                            away_team = parts[1]
                            home_team = parts[2]
                            # Opponent is the team that's not derived_team_abbr
                            if derived_team_abbr == home_team:
                                derived_opponent_abbr = away_team
                            elif derived_team_abbr == away_team:
                                derived_opponent_abbr = home_team
                    except Exception:
                        pass

            # CRITICAL: Get shot zone data (all from same source - PBP, not box score)
            # This ensures data consistency (avoid mixing PBP paint/mid with box score three_pt)
            shot_zone_data = self.shot_zone_analyzer.get_shot_zone_data(row['game_id'], player_lookup)

            # Check if we have complete shot zone data from PBP
            has_complete_shot_zones = (
                shot_zone_data.get('paint_attempts') is not None and
                shot_zone_data.get('mid_range_attempts') is not None and
                shot_zone_data.get('three_attempts_pbp') is not None
            )

            # Build record with source tracking
            record = {
                # Core identifiers
                'player_lookup': player_lookup,
                'universal_player_id': universal_player_id,
                'player_full_name': row['player_full_name'],
                'game_id': row['game_id'],
                'game_date': row['game_date'].isoformat() if pd.notna(row['game_date']) else None,
                'team_abbr': derived_team_abbr,
                'opponent_team_abbr': derived_opponent_abbr,
                'season_year': int(row['season_year']) if pd.notna(row['season_year']) else None,

                # Basic stats
                'points': int(row['points']) if pd.notna(row['points']) else None,
                'minutes_played': minutes_int,
                'assists': int(row['assists']) if pd.notna(row['assists']) else None,
                'offensive_rebounds': int(row['offensive_rebounds']) if pd.notna(row['offensive_rebounds']) else None,
                'defensive_rebounds': int(row['defensive_rebounds']) if pd.notna(row['defensive_rebounds']) else None,
                'steals': int(row['steals']) if pd.notna(row['steals']) else None,
                'blocks': int(row['blocks']) if pd.notna(row['blocks']) else None,
                'turnovers': int(row['turnovers']) if pd.notna(row['turnovers']) else None,
                'personal_fouls': int(row['personal_fouls']) if pd.notna(row['personal_fouls']) else None,
                'plus_minus': plus_minus_int,

                # Shooting
                'fg_attempts': int(row['field_goals_attempted']) if pd.notna(row['field_goals_attempted']) else None,
                'fg_makes': int(row['field_goals_made']) if pd.notna(row['field_goals_made']) else None,
                # CRITICAL: Use PBP three_pt (not box score) for source consistency with paint/mid
                # If PBP not available, set to None to avoid mixed-source corruption
                'three_pt_attempts': shot_zone_data.get('three_attempts_pbp'),
                'three_pt_makes': shot_zone_data.get('three_makes_pbp'),
                'ft_attempts': int(row['free_throws_attempted']) if pd.notna(row['free_throws_attempted']) else None,
                'ft_makes': int(row['free_throws_made']) if pd.notna(row['free_throws_made']) else None,

                # Shot zones + shot creation (Pass 2 enrichment from BigDataBall play-by-play)
                **shot_zone_data,

                # Efficiency
                'usage_rate': round(usage_rate, 1) if usage_rate else None,
                'ts_pct': round(ts_pct, 3) if ts_pct else None,
                'efg_pct': round(efg_pct, 3) if efg_pct else None,
                'starter_flag': bool(minutes_decimal and minutes_decimal > 20) if minutes_decimal else False,
                'win_flag': False,

                # Prop betting (using PropCalculator)
                **PropCalculator.get_prop_fields(
                    points=row['points'] if pd.notna(row['points']) else None,
                    points_line=row['points_line'] if pd.notna(row['points_line']) else None,
                    points_line_source=row.get('points_line_source')
                ),

                # Availability
                'is_active': bool(row['player_status'] == 'active'),
                'player_status': row['player_status'],

                # DNP (Did Not Play) tracking - Session 13 fix
                'is_dnp': (
                    row['player_status'] in ('dnp', 'inactive') or
                    (minutes_decimal == 0 and row['player_status'] == 'active')
                ),
                'dnp_reason': row.get('dnp_reason') if row['player_status'] != 'active' else None,
                'dnp_reason_category': self._categorize_dnp_reason(row.get('dnp_reason')) if row['player_status'] != 'active' else None,

                # SOURCE TRACKING: One-liner adds all 18 fields!
                **self.build_source_tracking_fields(),

                # Quality columns (using QualityScorer)
                **QualityScorer.calculate_quality(
                    primary_source=row['primary_source'],
                    has_plus_minus=pd.notna(row.get('plus_minus')),
                    has_shot_zones=self.shot_zone_analyzer.shot_zones_available
                ),

                # Additional quality tracking fields
                **QualityScorer.get_additional_quality_fields(
                    primary_source=row['primary_source'],
                    shot_zones_estimated=False
                ),

                # Data lineage integrity (2026-01-27)
                'processing_context': self._determine_processing_context(),
                # Session 96: data_quality_flag now per-game based on whether THIS game has team stats
                'data_quality_flag': 'complete' if (usage_rate is not None and has_team_stats_for_game) else ('partial_no_team_stats' if not has_team_stats_for_game else 'partial'),
                'team_stats_available_at_processing': has_team_stats_for_game,  # Per-game, not global

                # Shot zone completeness tracking (2026-01-31)
                # Tracks if all three zones have data from same PBP source (not mixed with box score)
                'has_complete_shot_zones': has_complete_shot_zones,

                # Metadata
                'processed_at': datetime.now(timezone.utc).isoformat()
            }

            # Pattern #3: Smart Reprocessing - Calculate data hash
            record['data_hash'] = self._calculate_data_hash(record)

            return record

        except Exception as e:
            logger.error(f"Failed to process record {idx} ({row.get('game_id', 'unknown')}_{row.get('player_lookup', 'unknown')}): {e}")

            # Record failure for unified failure tracking
            self.record_failure(
                entity_id=row.get('player_lookup', 'unknown'),
                entity_type='PLAYER',
                category='PROCESSING_ERROR',
                reason=f"Exception processing player game record: {str(e)[:200]}",
                can_retry=True,
                missing_game_ids=[row.get('game_id')] if row.get('game_id') else None
            )
            return None

    # =========================================================================
    # Single Game Reprocessing (for resolved player names)
    # =========================================================================

    def process_single_game(self, game_id: str, game_date: str, season: str) -> bool:
        """
        Process a single game to enable reprocessing after alias creation.

        This method is called by reprocess_resolved.py when player names have been
        resolved and we need to re-run analytics for affected games.

        Args:
            game_id: The game ID to reprocess (e.g., '20251206_LAL_GSW')
            game_date: Game date in YYYY-MM-DD format
            season: Season string (e.g., '2024-25')

        Returns:
            True if processing succeeded (even if 0 records), False on error

        Flow:
        1. Extract Phase 2 data for this specific game_id
        2. Get players from this game
        3. Batch-lookup their registry IDs (with fresh alias data)
        4. Calculate analytics for these players
        5. MERGE-update to player_game_summary table
        6. Return success status
        """
        logger.info(f"🔄 REPROCESSING: game_id={game_id}, date={game_date}, season={season}")

        try:
            # Initialize minimal state for processing
            self.opts = {
                'start_date': game_date,
                'end_date': game_date,
                'skip_downstream_trigger': True,  # Don't trigger Phase 4 for reprocessing
            }
            self.raw_data = pd.DataFrame()
            self.transformed_data = []
            # Reset lazy-loaded modules for fresh processing
            self._registry_handler = None
            self._shot_zone_analyzer = None
            self.registry_stats = {
                'players_found': 0,
                'players_not_found': 0,
                'records_skipped': 0
            }
            self.shot_zone_data = {}
            self.shot_zones_available = False
            self.shot_zones_source = None

            # Step 1: Extract Phase 2 data for this specific game
            self._extract_single_game_data(game_id, game_date)

            if self.raw_data.empty:
                logger.warning(f"No data found for game {game_id} on {game_date}")
                return True  # Not an error, just no data

            logger.info(f"Extracted {len(self.raw_data)} player records for game {game_id}")

            # Step 2: Extract shot zones for this game
            self.shot_zone_analyzer.extract_shot_zones(game_date, game_date)

            # Persist games that need BDB re-run when data becomes available
            pending_count = self.shot_zone_analyzer.persist_pending_bdb_games()
            if pending_count > 0:
                logger.info(f"Game {game_id} added to pending_bdb_games (missing BDB data)")

            # Step 3: Set registry context and do batch lookup
            # Registry context set in batch_lookup_universal_ids
            # self.registry.set_default_context(season=season)

            unique_players = self.raw_data['player_lookup'].dropna().unique().tolist()
            logger.info(f"Looking up {len(unique_players)} players in registry")

            uid_map = self.registry_handler.registry.get_universal_ids_batch(
                unique_players,
                skip_unresolved_logging=True
            )

            self.registry_stats['players_found'] = len(uid_map)
            self.registry_stats['players_not_found'] = len(unique_players) - len(uid_map)

            logger.info(
                f"Registry: {self.registry_stats['players_found']} found, "
                f"{self.registry_stats['players_not_found']} not found"
            )

            # Step 4: Process records (use serial for single game - simpler)
            records = []
            for idx, row in self.raw_data.iterrows():
                record = self._process_single_player_game(idx, row, uid_map)
                if record is not None:
                    records.append(record)

            if not records:
                logger.warning(f"No records processed for game {game_id} (all players unresolved?)")
                return True  # Not an error, just no resolvable players

            self.transformed_data = records
            logger.info(f"Processed {len(records)} records for game {game_id}")

            # Step 5: Save to BigQuery using MERGE
            self._save_single_game_records(records)

            logger.info(f"✅ REPROCESSING COMPLETE: {game_id} - {len(records)} records saved")
            return True

        except Exception as e:
            logger.error(f"❌ REPROCESSING FAILED for {game_id}: {e}", exc_info=True)
            return False

    def _extract_single_game_data(self, game_id: str, game_date: str) -> None:
        """
        Extract Phase 2 data for a single game.

        Similar to extract_raw_data() but filtered to one game_id.
        """
        query = f"""
        WITH nba_com_data AS (
            SELECT
                game_id,
                game_date,
                season_year,
                player_lookup,
                player_name as player_full_name,
                team_abbr,
                player_status,
                home_team_abbr as source_home_team,
                away_team_abbr as source_away_team,
                points,
                assists,
                total_rebounds,
                offensive_rebounds,
                defensive_rebounds,
                steals,
                blocks,
                turnovers,
                personal_fouls,
                field_goals_made,
                field_goals_attempted,
                three_pointers_made,
                three_pointers_attempted,
                free_throws_made,
                free_throws_attempted,
                minutes,
                plus_minus,
                processed_at as source_processed_at,
                'nbac_gamebook' as primary_source
            FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
            WHERE game_id = @game_id
                AND player_status = 'active'
        ),

        bdl_data AS (
            SELECT
                game_id,
                game_date,
                season_year,
                player_lookup,
                player_full_name,
                team_abbr,
                'active' as player_status,
                CAST(NULL AS STRING) as source_home_team,
                CAST(NULL AS STRING) as source_away_team,
                points,
                assists,
                rebounds as total_rebounds,
                NULL as offensive_rebounds,
                NULL as defensive_rebounds,
                steals,
                blocks,
                turnovers,
                personal_fouls,
                -- Shooting stats (BDL now has all these fields as of 2024)
                field_goals_made,
                field_goals_attempted,
                three_pointers_made,
                three_pointers_attempted,
                free_throws_made,
                free_throws_attempted,
                minutes,
                NULL as plus_minus,
                processed_at as source_processed_at,
                'bdl_boxscores' as primary_source
            FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
            WHERE game_id = @game_id
                AND game_date = @game_date
        ),

        combined_data AS (
            -- CRITICAL FIX (2026-01-27): Player-level merge, not game-level
            SELECT * FROM nba_com_data
            UNION ALL
            SELECT * FROM bdl_data bd
            WHERE NOT EXISTS (
                SELECT 1 FROM nba_com_data nc
                WHERE nc.game_id = bd.game_id
                  AND nc.player_lookup = bd.player_lookup
            )
        ),

        -- Deduplicate combined data (prevents duplicates from source overlap)
        -- Keeps most recent record by source_processed_at timestamp
        deduplicated_combined AS (
            SELECT * EXCEPT(rn) FROM (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY game_id, player_lookup
                        ORDER BY source_processed_at DESC
                    ) as rn
                FROM combined_data
            ) WHERE rn = 1
        ),

        deduplicated_props AS (
            SELECT
                game_id,
                player_lookup,
                points_line,
                over_price_american,
                under_price_american,
                bookmaker,
                ROW_NUMBER() OVER (
                    PARTITION BY game_id, player_lookup
                    ORDER BY
                        CASE bookmaker
                            WHEN 'draftkings' THEN 1
                            WHEN 'fanduel' THEN 2
                            ELSE 3
                        END,
                        bookmaker
                ) as rn
            FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
            WHERE game_id = @game_id
        ),

        with_props AS (
            SELECT
                c.*,
                p.points_line,
                p.over_price_american,
                p.under_price_american,
                p.bookmaker as points_line_source
            FROM deduplicated_combined c
            LEFT JOIN deduplicated_props p
                ON c.game_id = p.game_id
                AND c.player_lookup = p.player_lookup
                AND p.rn = 1
        ),

        games_context AS (
            SELECT DISTINCT
                game_id,
                game_date,
                source_home_team,
                source_away_team,
                COALESCE(
                    source_away_team,
                    CASE WHEN game_id LIKE '%_%_%' THEN SPLIT(game_id, '_')[SAFE_OFFSET(1)] END
                ) as away_team_abbr,
                COALESCE(
                    source_home_team,
                    CASE WHEN game_id LIKE '%_%_%' THEN SPLIT(game_id, '_')[SAFE_OFFSET(2)] END
                ) as home_team_abbr
            FROM deduplicated_combined
        ),

        -- Team stats - check both game_id and reversed format (handles Away_Home vs Home_Away mismatch)
        -- Session 103: Added deduplication to handle duplicate team records with different stats
        -- Keeps the record with highest possessions (most complete data)
        team_stats_raw AS (
            SELECT
                game_id,
                CASE
                    WHEN game_id LIKE '%_%_%' THEN
                        CONCAT(
                            SUBSTR(game_id, 1, 9),
                            SPLIT(game_id, '_')[OFFSET(2)], '_',
                            SPLIT(game_id, '_')[OFFSET(1)]
                        )
                    ELSE game_id
                END as game_id_reversed,
                team_abbr,
                fg_attempts as team_fg_attempts,
                ft_attempts as team_ft_attempts,
                turnovers as team_turnovers,
                possessions as team_possessions,
                -- Deduplicate: prefer record with highest possessions (most complete data)
                ROW_NUMBER() OVER (
                    PARTITION BY team_abbr
                    ORDER BY possessions DESC
                ) as quality_rank
            FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
            WHERE game_date = @game_date
              AND (game_id = @game_id OR game_id = CONCAT(
                    SUBSTR(@game_id, 1, 9),
                    SPLIT(@game_id, '_')[OFFSET(2)], '_',
                    SPLIT(@game_id, '_')[OFFSET(1)]
                ))
        ),
        -- Only keep best quality record per team (Session 103 fix)
        team_stats AS (
            SELECT game_id, game_id_reversed, team_abbr, team_fg_attempts, team_ft_attempts, team_turnovers, team_possessions
            FROM team_stats_raw
            WHERE quality_rank = 1
        )

        SELECT
            wp.*,
            gc.away_team_abbr,
            gc.home_team_abbr,
            ts.team_fg_attempts,
            ts.team_ft_attempts,
            ts.team_turnovers,
            ts.team_possessions,
            COALESCE(
                CASE
                    WHEN wp.team_abbr = gc.home_team_abbr THEN gc.away_team_abbr
                    ELSE gc.home_team_abbr
                END,
                ''
            ) as opponent_team_abbr,
            CASE
                WHEN wp.team_abbr = gc.home_team_abbr THEN TRUE
                ELSE FALSE
            END as home_game
        FROM with_props wp
        LEFT JOIN games_context gc ON wp.game_id = gc.game_id
        LEFT JOIN team_stats ts ON (wp.game_id = ts.game_id OR wp.game_id = ts.game_id_reversed)
            AND wp.team_abbr = ts.team_abbr
        ORDER BY wp.player_lookup
        """

        from google.cloud import bigquery

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_id", "STRING", game_id),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
            ]
        )

        # SESSION 119: Disable BigQuery cache for regenerations
        if self.opts.get('backfill_mode', False):
            job_config.use_query_cache = False
            logger.info("🔄 REGENERATION MODE: BigQuery cache disabled (prevents stale JOIN results)")

        try:
            self.raw_data = self.bq_client.query(query, job_config=job_config).to_dataframe()

            if not self.raw_data.empty:
                # Clean numeric columns
                self._clean_numeric_columns()
                source_counts = self.raw_data['primary_source'].value_counts()
                logger.info(f"Source distribution: {dict(source_counts)}")

        except Exception as e:
            logger.error(f"BigQuery extraction failed for game {game_id}: {e}")
            raise

    def _save_single_game_records(self, records: List[Dict]) -> None:
        """
        Save processed records for a single game using MERGE.

        Uses the base class _save_with_proper_merge() for atomic upsert.
        """
        if not records:
            return

        table_id = f"{self.project_id}.{self.dataset_id}.{self.table_name}"

        # Deduplicate records before validation (Session 116 pattern)
        records = self._deduplicate_records(records)

        # Pre-write validation: Block records that would corrupt downstream data
        # Session 122: Added to prevent usage_rate anomaly (1228% values)
        records = self._validate_before_write(records, table_id)
        if not records:
            logger.warning("All records blocked by pre-write validation")
            return

        # Get table schema
        try:
            table_ref = self.bq_client.get_table(table_id)
            table_schema = table_ref.schema
        except Exception as e:
            logger.warning(f"Could not get table schema: {e}")
            table_schema = None

        # Use parent class MERGE method
        self._save_with_proper_merge(records, table_id, table_schema)

        logger.info(f"Saved {len(records)} records to {table_id}")

    def _process_player_games_serial(self, uid_map: dict) -> List[Dict]:
        """Original serial processing (kept for fallback)."""
        logger.info(f"Processing {len(self.raw_data)} player-game records (serial mode)")

        records = []

        for _, row in self.raw_data.iterrows():
            try:
                player_lookup = row['player_lookup']
                universal_player_id = uid_map.get(player_lookup)

                if universal_player_id is None:
                    # Log unresolved player with game context
                    game_context = {
                        'game_id': row['game_id'],
                        'game_date': row['game_date'].isoformat() if pd.notna(row['game_date']) else None,
                        'season': f"{int(row['season_year'])}-{str(int(row['season_year']) + 1)[-2:]}" if pd.notna(row['season_year']) else None,
                        'team_abbr': row['team_abbr'] if pd.notna(row['team_abbr']) else None,
                        'source': 'player_game_summary'
                    }
                    self.registry_handler._log_unresolved_player(player_lookup, game_context)
                    self.registry_stats['records_skipped'] += 1

                    # Track failure for observability (v2.1 feature)
                    self.registry_failures.append({
                        'player_lookup': player_lookup,
                        'game_date': row['game_date'],
                        'team_abbr': row['team_abbr'] if pd.notna(row['team_abbr']) else None,
                        'season': f"{int(row['season_year'])}-{str(int(row['season_year']) + 1)[-2:]}" if pd.notna(row['season_year']) else None,
                        'game_id': row['game_id']
                    })
                    continue

                # Parse minutes
                minutes_decimal = self._parse_minutes_to_decimal(row['minutes'])
                # Session 109: Preserve decimal precision (schema is NUMERIC(5,1))
                minutes_int = round(minutes_decimal, 1) if minutes_decimal else None

                # Parse plus/minus
                plus_minus_int = self._parse_plus_minus(row['plus_minus'])

                # Calculate prop outcome
                over_under_result = None
                margin = None
                if pd.notna(row['points']) and pd.notna(row['points_line']):
                    over_under_result = 'OVER' if row['points'] >= row['points_line'] else 'UNDER'
                    margin = float(row['points']) - float(row['points_line'])

                # Calculate efficiency
                ts_pct = None
                efg_pct = None

                if (pd.notna(row['field_goals_attempted']) and
                    row['field_goals_attempted'] > 0):

                    fga = row['field_goals_attempted']
                    three_makes = row['three_pointers_made'] or 0

                    efg_pct = (row['field_goals_made'] + 0.5 * three_makes) / fga

                    if pd.notna(row['free_throws_attempted']):
                        fta = row['free_throws_attempted']
                        total_shots = fga + 0.44 * fta
                        if total_shots > 0:
                            ts_pct = row['points'] / (2 * total_shots)

                # Calculate usage_rate (requires team stats for THIS game)
                # Session 96: Changed from global threshold to per-game calculation
                usage_rate = None
                has_team_stats_for_game = (
                    pd.notna(row.get('team_fg_attempts')) and
                    pd.notna(row.get('team_ft_attempts')) and
                    pd.notna(row.get('team_turnovers'))
                )
                if (has_team_stats_for_game and
                    pd.notna(row['field_goals_attempted']) and
                    pd.notna(row['turnovers']) and
                    minutes_decimal and minutes_decimal > 0):

                    # Player usage components
                    player_fga = row['field_goals_attempted']
                    player_fta = row.get('free_throws_attempted', 0) or 0
                    player_to = row['turnovers']
                    player_poss_used = player_fga + 0.44 * player_fta + player_to

                    # Team usage components
                    team_fga = row['team_fg_attempts']
                    team_fta = row['team_ft_attempts']
                    team_to = row['team_turnovers']
                    team_poss_used = team_fga + 0.44 * team_fta + team_to

                    # Usage Rate formula (assumes 48 min team total / 5 players = 240 min shared)
                    # USG% = 100 × (Player FGA + 0.44 × Player FTA + Player TO) × (Tm Min / 5)
                    #            / (Player Min × (Tm FGA + 0.44 × Tm FTA + Tm TO))
                    # Approximation: Tm Min ≈ 240 (48 min × 5 players)
                    if team_poss_used > 0:
                        usage_rate = 100.0 * player_poss_used * 48.0 / (minutes_decimal * team_poss_used)
                        # Sanity check: usage_rate > 100% indicates data quality issue
                        if usage_rate > 100.0:
                            logger.warning(
                                f"Impossible usage_rate {usage_rate:.1f}% for {player_lookup} in {row['game_id']} - "
                                f"likely incomplete team stats (team_poss={team_poss_used:.1f})"
                            )
                            usage_rate = None

                # CRITICAL: Get shot zone data (all from same source - PBP, not box score)
                # This ensures data consistency (avoid mixing PBP paint/mid with box score three_pt)
                shot_zone_data = self.shot_zone_analyzer.get_shot_zone_data(row['game_id'], player_lookup)

                # Check if we have complete shot zone data from PBP
                has_complete_shot_zones = (
                    shot_zone_data.get('paint_attempts') is not None and
                    shot_zone_data.get('mid_range_attempts') is not None and
                    shot_zone_data.get('three_attempts_pbp') is not None
                )

                # Build record with source tracking
                record = {
                    # Core identifiers
                    'player_lookup': player_lookup,
                    'universal_player_id': universal_player_id,
                    'player_full_name': row['player_full_name'],
                    'game_id': row['game_id'],
                    'game_date': row['game_date'].isoformat() if pd.notna(row['game_date']) else None,
                    'team_abbr': row['team_abbr'],
                    'opponent_team_abbr': row['opponent_team_abbr'],
                    'season_year': int(row['season_year']) if pd.notna(row['season_year']) else None,

                    # Basic stats
                    'points': int(row['points']) if pd.notna(row['points']) else None,
                    'minutes_played': minutes_int,
                    'assists': int(row['assists']) if pd.notna(row['assists']) else None,
                    'offensive_rebounds': int(row['offensive_rebounds']) if pd.notna(row['offensive_rebounds']) else None,
                    'defensive_rebounds': int(row['defensive_rebounds']) if pd.notna(row['defensive_rebounds']) else None,
                    'steals': int(row['steals']) if pd.notna(row['steals']) else None,
                    'blocks': int(row['blocks']) if pd.notna(row['blocks']) else None,
                    'turnovers': int(row['turnovers']) if pd.notna(row['turnovers']) else None,
                    'personal_fouls': int(row['personal_fouls']) if pd.notna(row['personal_fouls']) else None,
                    'plus_minus': plus_minus_int,

                    # Shooting
                    'fg_attempts': int(row['field_goals_attempted']) if pd.notna(row['field_goals_attempted']) else None,
                    'fg_makes': int(row['field_goals_made']) if pd.notna(row['field_goals_made']) else None,
                    # CRITICAL: Use PBP three_pt (not box score) for source consistency with paint/mid
                    # If PBP not available, set to None to avoid mixed-source corruption
                    'three_pt_attempts': shot_zone_data.get('three_attempts_pbp'),
                    'three_pt_makes': shot_zone_data.get('three_makes_pbp'),
                    'ft_attempts': int(row['free_throws_attempted']) if pd.notna(row['free_throws_attempted']) else None,
                    'ft_makes': int(row['free_throws_made']) if pd.notna(row['free_throws_made']) else None,

                    # Shot zones + shot creation (Pass 2 enrichment from BigDataBall play-by-play)
                    **shot_zone_data,

                    # Efficiency
                    'usage_rate': round(usage_rate, 1) if usage_rate else None,
                    'ts_pct': round(ts_pct, 3) if ts_pct else None,
                    'efg_pct': round(efg_pct, 3) if efg_pct else None,
                    'starter_flag': bool(minutes_decimal and minutes_decimal > 20) if minutes_decimal else False,
                    'win_flag': False,

                    # Prop betting
                    'points_line': float(row['points_line']) if pd.notna(row['points_line']) else None,
                    'over_under_result': over_under_result,
                    'margin': round(margin, 2) if margin is not None else None,
                    'opening_line': None,  # Pass 3 enhancement
                    'line_movement': None,
                    'points_line_source': row.get('points_line_source'),
                    'opening_line_source': None,

                    # Availability
                    'is_active': bool(row['player_status'] == 'active'),
                    'player_status': row['player_status'],

                    # SOURCE TRACKING: One-liner adds all 18 fields!
                    **self.build_source_tracking_fields(),

                    # Quality columns using centralized helper
                    **build_quality_columns_with_legacy(
                        tier='gold' if row['primary_source'] == 'nbac_gamebook' else 'silver',
                        score=100.0 if row['primary_source'] == 'nbac_gamebook' else 85.0,
                        issues=[] if row['primary_source'] == 'nbac_gamebook' else ['backup_source_used'],
                        sources=[row['primary_source']] if row['primary_source'] else ['unknown'],
                    ),

                    # Additional tracking fields
                    'primary_source_used': row['primary_source'],
                    'processed_with_issues': False,
                    'shot_zones_estimated': None,
                    'quality_sample_size': None,  # Populated by Phase 4
                    'quality_used_fallback': row['primary_source'] != 'nbac_gamebook',
                    'quality_reconstructed': False,
                    'quality_calculated_at': datetime.now(timezone.utc).isoformat(),
                    'quality_metadata': {'sources_used': [row['primary_source']], 'early_season': False},

                    # Data lineage integrity (2026-01-27)
                    'processing_context': self._determine_processing_context(),
                    # Session 96: data_quality_flag now per-game based on whether THIS game has team stats
                    'data_quality_flag': 'complete' if (usage_rate is not None and has_team_stats_for_game) else ('partial_no_team_stats' if not has_team_stats_for_game else 'partial'),
                    'team_stats_available_at_processing': has_team_stats_for_game,  # Per-game, not global

                    # Shot zone completeness tracking (2026-01-31)
                    # Tracks if all three zones have data from same PBP source (not mixed with box score)
                    'has_complete_shot_zones': has_complete_shot_zones,

                    # Metadata
                    'processed_at': datetime.now(timezone.utc).isoformat()
                }

                # Pattern #3: Smart Reprocessing - Calculate data hash
                record['data_hash'] = self._calculate_data_hash(record)

                records.append(record)

            except Exception as e:
                logger.error(f"Error processing {row['game_id']}_{row['player_lookup']}: {e}")

                # Record failure for unified failure tracking
                self.record_failure(
                    entity_id=row.get('player_lookup', 'unknown'),
                    entity_type='PLAYER',
                    category='PROCESSING_ERROR',
                    reason=f"Exception processing player game record: {str(e)[:200]}",
                    can_retry=True,
                    missing_game_ids=[row.get('game_id')] if row.get('game_id') else None
                )
                continue

        return records


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Process player game summary")
    parser.add_argument('--start-date', required=True, help='YYYY-MM-DD')
    parser.add_argument('--end-date', required=True, help='YYYY-MM-DD')
    parser.add_argument('--debug', action='store_true')
    parser.add_argument(
        '--skip-downstream-trigger',
        action='store_true',
        help='Disable Pub/Sub trigger to Phase 4 (for backfills)'
    )
    parser.add_argument(
        '--backfill-mode',
        action='store_true',
        help='Enable backfill mode: bypass stale data checks and suppress alerts'
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    try:
        processor = PlayerGameSummaryProcessor()
        success = processor.run({
            'start_date': args.start_date,
            'end_date': args.end_date,
            'skip_downstream_trigger': args.skip_downstream_trigger,
            'backfill_mode': args.backfill_mode
        })
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)