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

    Dependencies (6 Phase 2 tables):
    1. nba_raw.nbac_gamebook_player_stats - PRIMARY stats (CRITICAL)
    2. nba_raw.bdl_player_boxscores - FALLBACK stats (CRITICAL)
    3. nba_raw.bigdataball_play_by_play - PREFERRED shot zones (OPTIONAL)
    4. nba_raw.nbac_play_by_play - BACKUP shot zones (OPTIONAL)
    5. nba_raw.odds_api_player_points_props - PRIMARY prop lines (OPTIONAL)
    6. nba_raw.bettingpros_player_points_props - BACKUP prop lines (OPTIONAL)

    Processing Strategy: MERGE_UPDATE (allows multi-pass enrichment)

    Optimization Patterns (Week 1):
    - Pattern #1 (Smart Skip): Only processes player stat sources
    - Pattern #3 (Early Exit): Skips no-game days, offseason, historical dates
    - Pattern #5 (Circuit Breaker): Prevents infinite retry loops
    """

    # =========================================================================
    # Pattern #1: Smart Skip Configuration
    # =========================================================================
    RELEVANT_SOURCES = {
        # Player stats sources - RELEVANT
        'nbac_gamebook_player_stats': True,
        'bdl_player_boxscores': True,

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
    PRIMARY_KEY_FIELDS = ['game_id', 'player_lookup']

    def __init__(self):
        super().__init__()
        self.table_name = 'player_game_summary'
        self.processing_strategy = 'MERGE_UPDATE'

        # Lazy-loaded modules (initialized when needed)
        self._shot_zone_analyzer: Optional[ShotZoneAnalyzer] = None
        self._registry_handler: Optional[PlayerRegistryHandler] = None
        self._processing_gate: Optional[ProcessingGate] = None

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
                'max_age_hours_warn': 24,
                'max_age_hours_fail': 72,
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

    def extract_raw_data(self) -> None:
        """
        Extract data with automatic dependency checking and source tracking.

        NEW in v2.0: Proper integration with base class check_dependencies().
        No more manual source tracking!

        NEW in v3.0: Smart reprocessing - skip processing if Phase 2 source unchanged.
        """
        start_date = self.opts['start_date']
        end_date = self.opts['end_date']

        # DEPENDENCY CHECKING: Already done in base class run() method!
        # Base class calls check_dependencies() and track_source_usage()
        # before calling this method, so all source_* attributes are populated.

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
                AND player_status = 'active'
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

                -- Shooting stats
                field_goals_made,
                NULL as field_goals_attempted,
                three_pointers_made,
                NULL as three_pointers_attempted,
                free_throws_made,
                NULL as free_throws_attempted,

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
        
        -- Combine with NBA.com priority (player-level merge)
        -- NBA.com is preferred source when available; BDL fills gaps for missing players
        -- CRITICAL FIX (2026-01-27): Changed from game-level to player-level merge
        --   Previously excluded 119 players/day including Jayson Tatum, Kyrie Irving, etc.
        combined_data AS (
            -- All NBA.com data (primary source)
            SELECT * FROM nba_com_data

            UNION ALL

            -- BDL data for players NOT in NBA.com (fills gaps)
            -- This ensures players like Jayson Tatum who may only be in BDL are included
            SELECT * FROM bdl_data bd
            WHERE NOT EXISTS (
                SELECT 1 FROM nba_com_data nc
                WHERE nc.game_id = bd.game_id
                  AND nc.player_lookup = bd.player_lookup
            )
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
            WHERE game_id IN (SELECT DISTINCT game_id FROM combined_data)
        ),
        
        -- Add props context
        with_props AS (
            SELECT 
                c.*,
                p.points_line,
                p.over_price_american,
                p.under_price_american,
                p.bookmaker as points_line_source
            FROM combined_data c
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
            FROM combined_data
        ),

        -- Team stats for usage_rate calculation
        team_stats AS (
            SELECT
                game_id,
                team_abbr,
                fg_attempts as team_fg_attempts,
                ft_attempts as team_ft_attempts,
                turnovers as team_turnovers,
                possessions as team_possessions
            FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
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
        LEFT JOIN team_stats ts ON wp.game_id = ts.game_id AND wp.team_abbr = ts.team_abbr
        ORDER BY wp.game_date DESC, wp.game_id, wp.player_lookup
        """
        
        logger.info(f"Extracting data for {start_date} to {end_date}")
        
        try:
            self.raw_data = self.bq_client.query(query).to_dataframe()
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

    def validate_extracted_data(self) -> None:
        """Enhanced validation with cross-source quality checks."""
        super().validate_extracted_data()
        
        if self.raw_data.empty:
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
        """Return processing stats for monitoring."""
        if not self.transformed_data:
            return {}

        stats = self.registry_handler.get_stats() if self._registry_handler else {}
        return {
            'records_processed': len(self.transformed_data),
            **stats,
            'source_nbac_completeness': getattr(self, 'source_nbac_completeness_pct', None),
            'source_bdl_completeness': getattr(self, 'source_bdl_completeness_pct', None),
            'source_odds_completeness': getattr(self, 'source_odds_completeness_pct', None)
        }

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
            minutes_decimal = self._parse_minutes_to_decimal(row['minutes'])
            minutes_int = int(round(minutes_decimal)) if minutes_decimal else None

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

            # Calculate usage_rate (requires team stats)
            usage_rate = None
            if (pd.notna(row.get('team_fg_attempts')) and
                pd.notna(row.get('team_ft_attempts')) and
                pd.notna(row.get('team_turnovers')) and
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
                'three_pt_attempts': int(row['three_pointers_attempted']) if pd.notna(row['three_pointers_attempted']) else None,
                'three_pt_makes': int(row['three_pointers_made']) if pd.notna(row['three_pointers_made']) else None,
                'ft_attempts': int(row['free_throws_attempted']) if pd.notna(row['free_throws_attempted']) else None,
                'ft_makes': int(row['free_throws_made']) if pd.notna(row['free_throws_made']) else None,

                # Shot zones + shot creation (Pass 2 enrichment from BigDataBall play-by-play)
                **self.shot_zone_analyzer.get_shot_zone_data(row['game_id'], player_lookup),

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
                'data_quality_flag': 'complete' if usage_rate is not None else 'partial',

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
                field_goals_made,
                NULL as field_goals_attempted,
                three_pointers_made,
                NULL as three_pointers_attempted,
                free_throws_made,
                NULL as free_throws_attempted,
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
            FROM combined_data c
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
            FROM combined_data
        ),

        team_stats AS (
            SELECT
                game_id,
                team_abbr,
                fg_attempts as team_fg_attempts,
                ft_attempts as team_ft_attempts,
                turnovers as team_turnovers,
                possessions as team_possessions
            FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
            WHERE game_id = @game_id
                AND game_date = @game_date
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
        LEFT JOIN team_stats ts ON wp.game_id = ts.game_id AND wp.team_abbr = ts.team_abbr
        ORDER BY wp.player_lookup
        """

        from google.cloud import bigquery

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_id", "STRING", game_id),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
            ]
        )

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
                minutes_int = int(round(minutes_decimal)) if minutes_decimal else None

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

                # Calculate usage_rate (requires team stats)
                usage_rate = None
                if (pd.notna(row.get('team_fg_attempts')) and
                    pd.notna(row.get('team_ft_attempts')) and
                    pd.notna(row.get('team_turnovers')) and
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
                    'three_pt_attempts': int(row['three_pointers_attempted']) if pd.notna(row['three_pointers_attempted']) else None,
                    'three_pt_makes': int(row['three_pointers_made']) if pd.notna(row['three_pointers_made']) else None,
                    'ft_attempts': int(row['free_throws_attempted']) if pd.notna(row['free_throws_attempted']) else None,
                    'ft_makes': int(row['free_throws_made']) if pd.notna(row['free_throws_made']) else None,

                    # Shot zones + shot creation (Pass 2 enrichment from BigDataBall play-by-play)
                    **self._get_shot_zone_data(row['game_id'], player_lookup),

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