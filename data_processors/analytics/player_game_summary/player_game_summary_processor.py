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
from shared.utils.player_registry import RegistryReader, PlayerNotFoundError

# Pattern imports (Week 1 - Foundation Patterns)
from shared.processors.patterns import SmartSkipMixin, EarlyExitMixin, CircuitBreakerMixin, QualityMixin
from shared.config.source_coverage import SourceCoverageEventType, SourceCoverageSeverity
from shared.processors.patterns.quality_columns import build_quality_columns_with_legacy

# Change detection (v1.1 feature)
from shared.change_detection.change_detector import PlayerChangeDetector

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
    ENABLE_OFFSEASON_CHECK = True      # Skip in July-September
    ENABLE_HISTORICAL_DATE_CHECK = True  # Skip dates >90 days old

    # =========================================================================
    # Pattern #5: Circuit Breaker Configuration
    # =========================================================================
    CIRCUIT_BREAKER_THRESHOLD = 5  # Open after 5 consecutive failures
    CIRCUIT_BREAKER_TIMEOUT = timedelta(minutes=30)  # Stay open 30 minutes

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

    def __init__(self):
        super().__init__()
        self.table_name = 'player_game_summary'
        self.processing_strategy = 'MERGE_UPDATE'
        
        # Registry for universal player IDs
        self.registry = RegistryReader(
            source_name='player_game_summary',
            cache_ttl_seconds=300
        )
        
        # Track registry stats
        self.registry_stats = {
            'players_found': 0,
            'players_not_found': 0,
            'records_skipped': 0
        }
    
    def get_dependencies(self) -> dict:
        """
        Define all 6 Phase 2 source requirements.
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
                'max_age_hours_warn': 6,
                'max_age_hours_fail': 24,
                'critical': True
            },
            
            # SOURCE 2: BDL Boxscores (FALLBACK - Critical)
            'nba_raw.bdl_player_boxscores': {
                'field_prefix': 'source_bdl',
                'description': 'BDL boxscores - fallback for basic stats',
                'date_field': 'game_date',
                'check_type': 'date_range',
                'expected_count_min': 200,
                'max_age_hours_warn': 4,
                'max_age_hours_fail': 12,
                'critical': True  # Need either NBA.com OR BDL
            },
            
            # SOURCE 3: Big Ball Data (OPTIONAL - shot zones primary)
            'nba_raw.bigdataball_play_by_play': {
                'field_prefix': 'source_bbd',
                'description': 'Big Ball Data - shot zones primary source',
                'date_field': 'game_date',
                'check_type': 'date_range',
                'expected_count_min': 2000,  # Many shot events per day
                'max_age_hours_warn': 6,
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
                'max_age_hours_warn': 6,
                'max_age_hours_fail': 24,
                'critical': False  # Backup only
            },
            
            # SOURCE 5: Odds API (OPTIONAL - prop lines primary)
            'nba_raw.odds_api_player_points_props': {
                'field_prefix': 'source_odds',
                'description': 'Odds API - prop lines primary source',
                'date_field': 'game_date',
                'check_type': 'date_range',
                'expected_count_min': 100,  # ~100+ players with props
                'max_age_hours_warn': 12,
                'max_age_hours_fail': 48,
                'critical': False  # Optional, has backup
            },
            
            # SOURCE 6: BettingPros (BACKUP - prop lines)
            'nba_raw.bettingpros_player_points_props': {
                'field_prefix': 'source_bp',
                'description': 'BettingPros - prop lines backup',
                'date_field': 'game_date',
                'check_type': 'date_range',
                'expected_count_min': 100,
                'max_age_hours_warn': 12,
                'max_age_hours_fail': 48,
                'critical': False  # Backup only
            }
        }

    def get_change_detector(self) -> PlayerChangeDetector:
        """
        Provide change detector for incremental processing (v1.1 feature).

        Enables 99%+ efficiency gain for mid-day updates by detecting
        which players have changed data since last processing.

        Returns:
            PlayerChangeDetector configured for player stats
        """
        return PlayerChangeDetector(project_id=self.project_id)

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
            self.raw_data = []
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
        
        -- Combine with NBA.com priority
        combined_data AS (
            SELECT * FROM nba_com_data
            
            UNION ALL
            
            SELECT * FROM bdl_data
            WHERE game_id NOT IN (SELECT DISTINCT game_id FROM nba_com_data)
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
        games_context AS (
            SELECT DISTINCT
                game_id,
                game_date,
                CASE 
                    WHEN game_id LIKE '%_%_%' THEN
                        SPLIT(game_id, '_')[OFFSET(1)]
                    ELSE NULL
                END as away_team_abbr,
                CASE 
                    WHEN game_id LIKE '%_%_%' THEN  
                        SPLIT(game_id, '_')[OFFSET(2)]
                    ELSE NULL
                END as home_team_abbr
            FROM combined_data
        )
        
        SELECT 
            wp.*,
            gc.away_team_abbr,
            gc.home_team_abbr,
            CASE 
                WHEN wp.team_abbr = gc.home_team_abbr THEN gc.away_team_abbr
                ELSE gc.home_team_abbr  
            END as opponent_team_abbr,
            CASE 
                WHEN wp.team_abbr = gc.home_team_abbr THEN TRUE
                ELSE FALSE
            END as home_game
            
        FROM with_props wp
        LEFT JOIN games_context gc ON wp.game_id = gc.game_id
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
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                    
        except Exception as e:
            logger.error(f"BigQuery extraction failed: {e}")
            raise
    
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
            'points', 'assists', 'minutes', 'field_goals_made', 'field_goals_attempted',
            'three_pointers_made', 'three_pointers_attempted', 'free_throws_made', 
            'free_throws_attempted', 'steals', 'blocks', 'turnovers', 'personal_fouls',
            'total_rebounds', 'offensive_rebounds', 'defensive_rebounds', 'season_year'
        ]
        
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
        - Universal player ID via RegistryReader (batch lookup)
        - Source tracking via **self.build_source_tracking_fields()
        - No manual attribute setting!
        """
        # =====================================================================
        # REGISTRY: Batch lookup for universal player IDs
        # =====================================================================
        logger.info("Looking up universal player IDs...")
        
        if not self.raw_data.empty and 'season_year' in self.raw_data.columns:
            season_year = int(self.raw_data['season_year'].mode()[0])
            season_str = f"{season_year}-{str(season_year + 1)[-2:]}"
            self.registry.set_default_context(season=season_str)
            logger.info(f"Registry context: {season_str}")
        
        unique_players = self.raw_data['player_lookup'].dropna().unique().tolist()
        logger.info(f"Batch lookup for {len(unique_players)} players")

        # Skip logging unresolved players here - we'll log them during game processing
        # with full context (game_id, game_date, etc.)
        uid_map = self.registry.get_universal_ids_batch(
            unique_players,
            skip_unresolved_logging=True
        )
        
        self.registry_stats['players_found'] = len(uid_map)
        self.registry_stats['players_not_found'] = len(unique_players) - len(uid_map)
        
        logger.info(
            f"Registry: {self.registry_stats['players_found']} found, "
            f"{self.registry_stats['players_not_found']} not found"
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

        logger.info(f"✅ Processed {len(records)} records")
        logger.info(f"⚠️ Skipped {self.registry_stats['records_skipped']} (no registry match)")

        # Save failure records to BigQuery for observability (v2.1 feature)
        if self.registry_failures:
            self.save_registry_failures()

    def _parse_minutes_to_decimal(self, minutes_str: str) -> Optional[float]:
        """Parse minutes string to decimal format (40:11 → 40.18)."""
        if pd.isna(minutes_str) or not minutes_str or minutes_str == '-':
            return None
            
        try:
            if ':' in str(minutes_str):
                parts = str(minutes_str).split(':')
                if len(parts) == 2:
                    mins = int(parts[0])
                    secs = int(parts[1])
                    return round(mins + (secs / 60), 2)
            
            return float(minutes_str)
            
        except (ValueError, TypeError) as e:
            logger.debug(f"Could not parse minutes: {minutes_str}: {e}")
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
            
        return {
            'records_processed': len(self.transformed_data),
            'registry_players_found': self.registry_stats['players_found'],
            'registry_records_skipped': self.registry_stats['records_skipped'],
            'source_nbac_completeness': getattr(self, 'source_nbac_completeness_pct', None),
            'source_bdl_completeness': getattr(self, 'source_bdl_completeness_pct', None),
            'source_odds_completeness': getattr(self, 'source_odds_completeness_pct', None)
        }
    
    def post_process(self) -> None:
        """Send success notification."""
        super().post_process()
        
        stats = self.get_analytics_stats()
        
        try:
            notify_info(
                title="Player Game Summary: Complete",
                message=f"Processed {stats.get('records_processed', 0)} records",
                details={
                    'processor': 'player_game_summary',
                    'date_range': f"{self.opts['start_date']} to {self.opts['end_date']}",
                    **stats
                }
            )
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")
    
    def finalize(self) -> None:
        """Cleanup - flush unresolved players."""
        logger.info("Flushing unresolved players...")

        try:
            self.registry.flush_unresolved_players()
            cache_stats = self.registry.get_cache_stats()
            logger.info(f"Registry cache: {cache_stats['hit_rate']:.1%} hit rate")
        except Exception as e:
            logger.error(f"Failed to flush registry: {e}")

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
                self.registry._log_unresolved_player(player_lookup, game_context)
                self.registry_stats['records_skipped'] += 1

                # Track failure for observability (v2.1 feature)
                self.registry_failures.append({
                    'player_lookup': player_lookup,
                    'game_date': row['game_date'],
                    'team_abbr': row['team_abbr'] if pd.notna(row['team_abbr']) else None,
                    'season': f"{int(row['season_year'])}-{str(int(row['season_year']) + 1)[-2:]}" if pd.notna(row['season_year']) else None,
                    'game_id': row['game_id']
                })
                return None

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

                # Shot zones (Pass 2 implementation - future)
                'paint_attempts': None,
                'paint_makes': None,
                'mid_range_attempts': None,
                'mid_range_makes': None,
                'paint_blocks': None,
                'mid_range_blocks': None,
                'three_pt_blocks': None,
                'and1_count': None,

                # Shot creation (Pass 2 implementation - future)
                'assisted_fg_makes': None,
                'unassisted_fg_makes': None,

                # Efficiency
                'usage_rate': None,  # Requires team stats
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

            return record

        except Exception as e:
            logger.error(f"Failed to process record {idx} ({row.get('game_id', 'unknown')}_{row.get('player_lookup', 'unknown')}): {e}")
            return None

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
                    self.registry._log_unresolved_player(player_lookup, game_context)
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

                    # Shot zones (Pass 2 implementation - future)
                    'paint_attempts': None,
                    'paint_makes': None,
                    'mid_range_attempts': None,
                    'mid_range_makes': None,
                    'paint_blocks': None,
                    'mid_range_blocks': None,
                    'three_pt_blocks': None,
                    'and1_count': None,

                    # Shot creation (Pass 2 implementation - future)
                    'assisted_fg_makes': None,
                    'unassisted_fg_makes': None,

                    # Efficiency
                    'usage_rate': None,  # Requires team stats
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
            'skip_downstream_trigger': args.skip_downstream_trigger
        })
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)