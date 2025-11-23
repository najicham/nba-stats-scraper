# File: data_processors/precompute/ml_feature_store/ml_feature_store_processor.py
"""
ML Feature Store V2 Processor - Phase 4 Precompute
==================================================

Generates feature vectors for ML predictions by extracting data from
Phase 3 analytics and Phase 4 precompute tables.

Schedule: Nightly at 12:00 AM (AFTER all other Phase 4 processors)
Duration: ~2 minutes for 450 players
Output: nba_predictions.ml_feature_store_v2

Features Generated: 25 total
- 19 direct copy from Phase 3/4
- 6 calculated on-the-fly (indices 9-12, 21, 24)

CRITICAL: This processor runs LAST in Phase 4 because it depends on:
- player_daily_cache (11:45 PM)
- player_composite_factors (11:30 PM)
- player_shot_zone_analysis (11:15 PM)
- team_defense_zone_analysis (11:00 PM)

Version: 2.0 (Added v4.0 dependency tracking)
Date: November 6, 2025
"""

import logging
import json
from datetime import datetime, date, timezone, timedelta
from typing import Dict, List, Optional
import pandas as pd
from google.cloud import bigquery

from data_processors.precompute.precompute_base import PrecomputeProcessorBase

# Pattern imports (Week 1 - Foundation Patterns)
from shared.processors.patterns import SmartSkipMixin, EarlyExitMixin, CircuitBreakerMixin

# Smart Idempotency (Pattern #1)
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin

# Completeness checking (Week 4 - Phase 4 Cascade Dependencies)
from shared.utils.completeness_checker import CompletenessChecker

from .feature_extractor import FeatureExtractor
from .feature_calculator import FeatureCalculator
from .quality_scorer import QualityScorer
from .batch_writer import BatchWriter

# Configure logging
logger = logging.getLogger(__name__)

# Feature version and names
FEATURE_VERSION = 'v1_baseline_25'
FEATURE_COUNT = 25

FEATURE_NAMES = [
    # Recent Performance (0-4)
    'points_avg_last_5', 'points_avg_last_10', 'points_avg_season',
    'points_std_last_10', 'games_in_last_7_days',
    
    # Composite Factors (5-8)
    'fatigue_score', 'shot_zone_mismatch_score', 'pace_score', 'usage_spike_score',
    
    # Derived Factors (9-12)
    'rest_advantage', 'injury_risk', 'recent_trend', 'minutes_change',
    
    # Matchup Context (13-17)
    'opponent_def_rating', 'opponent_pace', 'home_away', 'back_to_back', 'playoff_game',
    
    # Shot Zones (18-21)
    'pct_paint', 'pct_mid_range', 'pct_three', 'pct_free_throw',
    
    # Team Context (22-24)
    'team_pace', 'team_off_rating', 'team_win_pct'
]


class MLFeatureStoreProcessor(
    SmartIdempotencyMixin,
    SmartSkipMixin,
    EarlyExitMixin,
    CircuitBreakerMixin,
    PrecomputeProcessorBase
):
    """
    Generate and cache 25 ML features for all active NBA players.

    This is a Phase 4 processor that:
    1. Checks Phase 4 dependencies (hard requirements)
    2. Queries Phase 4 tables for player data (preferred)
    3. Falls back to Phase 3 if Phase 4 incomplete
    4. Calculates 6 derived features
    5. Scores feature quality (0-100)
    6. Writes to nba_predictions.ml_feature_store_v2 in batches

    Consumers: All 5 Phase 5 prediction systems
    """
    
    # Processor configuration
    table_name = "ml_feature_store_v2"
    dataset_id = "nba_predictions"  # Cross-dataset write!
    
    # Required options
    required_opts = ['analysis_date']
    
    # Feature version
    feature_version = FEATURE_VERSION
    feature_count = FEATURE_COUNT

    # Smart Idempotency: Fields to hash (meaningful business fields only)
    HASH_FIELDS = [
        'player_lookup', 'universal_player_id', 'game_date', 'game_id',
        'features', 'feature_names', 'feature_count', 'feature_version',
        'feature_quality_score', 'opponent_team_abbr', 'is_home', 'days_rest',
        'data_source', 'early_season_flag', 'insufficient_data_reason'
    ]

    def __init__(self):
        """Initialize processor and helper classes."""
        super().__init__()

        # Initialize completeness checker (Week 4 - Cascade Dependencies)
        self.completeness_checker = CompletenessChecker(self.bq_client, self.project_id)

        # Helper classes
        self.feature_extractor = FeatureExtractor(self.bq_client, self.project_id)
        self.feature_calculator = FeatureCalculator()
        self.quality_scorer = QualityScorer()
        self.batch_writer = BatchWriter(self.bq_client, self.project_id)

        # Data storage
        self.players_with_games = None

        # Source hash cache (4 Phase 4 dependencies)
        self.source_daily_cache_hash = None
        self.source_composite_hash = None
        self.source_shot_zones_hash = None
        self.source_team_defense_hash = None

        # Season start date (for completeness checking - Week 4)
        self.season_start_date = None

        # Tracking
        self.early_season_flag = False
        self.insufficient_data_reason = None
        self.failed_entities = []

    # ============================================================
    # Pattern #1: Smart Skip Configuration
    # ============================================================
    RELEVANT_SOURCES = {
        # Phase 4 Precompute sources - RELEVANT (CRITICAL - depends on these)
        'player_daily_cache': True,
        'player_composite_factors': True,
        'player_shot_zone_analysis': True,
        'team_defense_zone_analysis': True,

        # Phase 3 Analytics sources - RELEVANT (fallback sources)
        'player_game_summary': True,
        'team_offense_game_summary': True,
        'team_defense_game_summary': True,
        'upcoming_player_game_context': True,
        'upcoming_team_game_context': True,

        # Phase 2 Raw sources - NOT RELEVANT (reads from Phase 3/4, not Phase 2)
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
    ENABLE_NO_GAMES_CHECK = False      # Don't skip - generates features for next day
    ENABLE_OFFSEASON_CHECK = True      # Skip in July-September
    ENABLE_HISTORICAL_DATE_CHECK = False  # Don't skip - can generate for any future date

    # ============================================================
    # Pattern #5: Circuit Breaker Configuration
    # ============================================================
    CIRCUIT_BREAKER_THRESHOLD = 5  # Open after 5 consecutive failures
    CIRCUIT_BREAKER_TIMEOUT = timedelta(minutes=30)  # Stay open 30 minutes

    # ========================================================================
    # DEPENDENCY CONFIGURATION (v4.0)
    # ========================================================================

    def get_dependencies(self) -> dict:
        """
        Define upstream Phase 4 data dependencies.
        
        Returns 4 critical sources with HARD requirements:
        - player_daily_cache (features 0-4, 18-20, 22-23)
        - player_composite_factors (features 5-8)
        - player_shot_zone_analysis (features 18-20)
        - team_defense_zone_analysis (features 13-14)
        
        Note: These are HARD dependencies - processor fails if missing
        (except during early season when placeholders are written).
        Phase 3 tables are fallback only, not tracked as dependencies.
        """
        return {
            'nba_precompute.player_daily_cache': {
                'field_prefix': 'source_daily_cache',
                'description': 'Player performance cache (features 0-4, 18-20, 22-23)',
                'check_type': 'date_match',
                'date_field': 'cache_date',
                'expected_count_min': 100,  # At least 100 players
                'max_age_hours': 2,  # Should be fresh (just ran at 11:45 PM)
                'critical': True
            },
            'nba_precompute.player_composite_factors': {
                'field_prefix': 'source_composite',
                'description': 'Composite adjustment factors (features 5-8)',
                'check_type': 'date_match',
                'date_field': 'game_date',
                'expected_count_min': 100,
                'max_age_hours': 2,  # Should be fresh (just ran at 11:30 PM)
                'critical': True
            },
            'nba_precompute.player_shot_zone_analysis': {
                'field_prefix': 'source_shot_zones',
                'description': 'Player shot distribution (features 18-20)',
                'check_type': 'date_match',
                'date_field': 'analysis_date',
                'expected_count_min': 100,
                'max_age_hours': 2,  # Should be fresh (just ran at 11:15 PM)
                'critical': True
            },
            'nba_precompute.team_defense_zone_analysis': {
                'field_prefix': 'source_team_defense',
                'description': 'Team defensive zones (features 13-14)',
                'check_type': 'date_match',
                'date_field': 'analysis_date',
                'expected_count_min': 20,  # At least 20 teams
                'max_age_hours': 2,  # Should be fresh (just ran at 11:00 PM)
                'critical': True
            }
        }
    
    # ========================================================================
    # DATA EXTRACTION
    # ========================================================================
    
    def extract_raw_data(self) -> None:
        """
        Extract data from Phase 3/4 tables.

        Steps:
        1. Check Phase 4 dependencies (HARD requirements)
        2. Check for early season (>50% players lack data)
        3. Track source usage (v4.0 dependency tracking)
        4. Get list of players with games today

        Early season: Creates placeholders for all players
        Normal season: Phase 4 must be complete or processor fails
        """
        if 'analysis_date' not in self.opts:
            raise ValueError("analysis_date required in opts")

        analysis_date = self.opts['analysis_date']
        logger.info(f"Extracting data for {analysis_date}")

        # Store season start date for completeness checking (Week 4)
        season_year = analysis_date.year if analysis_date.month >= 10 else analysis_date.year - 1
        self.season_start_date = date(season_year, 10, 1)
        
        # Check dependencies FIRST (v4.0 pattern)
        dep_check = self.check_dependencies(analysis_date)
        
        # Track source usage (populates source_* attributes for v4.0 tracking)
        self.track_source_usage(dep_check)
        
        # Check for early season BEFORE failing on missing dependencies
        if self._is_early_season(analysis_date):
            logger.warning("Early season detected - creating placeholder records")
            self._create_early_season_placeholders(analysis_date)
            return
        
        # Normal season: Phase 4 dependencies MUST be present
        if not dep_check['all_critical_present']:
            missing = ', '.join(dep_check['missing'])
            raise ValueError(f"Missing critical Phase 4 dependencies: {missing}")
        
        # Warn about stale data (but continue)
        if not dep_check['all_fresh']:
            logger.warning(f"Stale Phase 4 data detected: {dep_check['stale']}")
        
        # Get players with games today
        self.players_with_games = self.feature_extractor.get_players_with_games(analysis_date)
        logger.info(f"Found {len(self.players_with_games)} players with games on {analysis_date}")

        # Extract source hashes from all 4 Phase 4 dependencies (Smart Reprocessing - Pattern #3)
        self._extract_source_hashes(analysis_date)
        
        if len(self.players_with_games) == 0:
            raise ValueError(f"No players found with games on {analysis_date}")

        # Data is extracted per-player in calculate_precompute()
        # (More efficient than bulk extraction due to fallback logic)

    def _extract_source_hashes(self, analysis_date: date) -> None:
        """Extract data_hash from all 4 Phase 4 upstream tables."""
        try:
            # 1. player_daily_cache
            query = f"""SELECT data_hash FROM `{self.project_id}.nba_precompute.player_daily_cache`
            WHERE cache_date = '{analysis_date}' AND data_hash IS NOT NULL ORDER BY processed_at DESC LIMIT 1"""
            result = self.bq_client.query(query).to_dataframe()
            self.source_daily_cache_hash = str(result['data_hash'].iloc[0]) if not result.empty else None

            # 2. player_composite_factors
            query = f"""SELECT data_hash FROM `{self.project_id}.nba_precompute.player_composite_factors`
            WHERE analysis_date = '{analysis_date}' AND data_hash IS NOT NULL ORDER BY processed_at DESC LIMIT 1"""
            result = self.bq_client.query(query).to_dataframe()
            self.source_composite_hash = str(result['data_hash'].iloc[0]) if not result.empty else None

            # 3. player_shot_zone_analysis
            query = f"""SELECT data_hash FROM `{self.project_id}.nba_precompute.player_shot_zone_analysis`
            WHERE analysis_date = '{analysis_date}' AND data_hash IS NOT NULL ORDER BY processed_at DESC LIMIT 1"""
            result = self.bq_client.query(query).to_dataframe()
            self.source_shot_zones_hash = str(result['data_hash'].iloc[0]) if not result.empty else None

            # 4. team_defense_zone_analysis
            query = f"""SELECT data_hash FROM `{self.project_id}.nba_precompute.team_defense_zone_analysis`
            WHERE analysis_date = '{analysis_date}' AND data_hash IS NOT NULL ORDER BY processed_at DESC LIMIT 1"""
            result = self.bq_client.query(query).to_dataframe()
            self.source_team_defense_hash = str(result['data_hash'].iloc[0]) if not result.empty else None

            logger.info(f"Extracted 4 source hashes from Phase 4 tables")
        except Exception as e:
            logger.warning(f"Failed to extract source hashes: {e}")

    def _is_early_season(self, analysis_date: date) -> bool:
        """
        Check if we're in early season (insufficient data).
        
        Early season = >50% of players have early_season_flag set in
        their Phase 4 player_daily_cache data.
        
        This cascades the early season decision from upstream processor.
        """
        try:
            # Check player_daily_cache for early_season_flag
            query = f"""
            SELECT
                COUNT(*) as total_players,
                SUM(CASE WHEN early_season_flag = TRUE THEN 1 ELSE 0 END) as early_season_players
            FROM `{self.project_id}.nba_precompute.player_daily_cache`
            WHERE cache_date = '{analysis_date}'
            """
            
            result_df = self.bq_client.query(query).to_dataframe()
            
            if result_df.empty:
                return False
            
            total = result_df.iloc[0].get('total_players', 0)
            early = result_df.iloc[0].get('early_season_players', 0)
            
            if total > 0 and (early / total) > 0.5:
                self.early_season_flag = True
                self.insufficient_data_reason = f"Early season: {early}/{total} players lack historical data"
                logger.warning(self.insufficient_data_reason)
                return True
            
            return False
            
        except Exception as e:
            logger.warning(f"Error checking early season status: {e}")
            return False
    
    def _create_early_season_placeholders(self, analysis_date: date) -> None:
        """
        Create placeholder records for early season.
        
        All features set to NULL, early_season_flag = TRUE.
        Source tracking still populated to show Phase 4 status.
        """
        # Get list of players with games
        players = self.feature_extractor.get_players_with_games(analysis_date)
        
        self.transformed_data = []
        
        for player_row in players:
            record = {
                'player_lookup': player_row['player_lookup'],
                'universal_player_id': player_row.get('universal_player_id'),
                'game_date': analysis_date.isoformat(),
                'game_id': player_row['game_id'],
                
                # NULL feature array
                'features': [None] * FEATURE_COUNT,
                'feature_names': FEATURE_NAMES,
                'feature_count': FEATURE_COUNT,
                'feature_version': FEATURE_VERSION,
                
                # Context
                'opponent_team_abbr': player_row.get('opponent_team_abbr'),
                'is_home': player_row.get('is_home'),
                'days_rest': player_row.get('days_rest'),
                
                # Quality
                'feature_quality_score': 0.0,
                'feature_generation_time_ms': None,
                'data_source': 'early_season',
                
                # v4.0 Source tracking (still populated!)
                **self.build_source_tracking_fields(),

                # Early season flags (AFTER source tracking to override if needed)
                'early_season_flag': True,
                'insufficient_data_reason': self.insufficient_data_reason,

                # Completeness Checking Metadata (14 fields) - Early season defaults
                'expected_games_count': 0,
                'actual_games_count': 0,
                'completeness_percentage': 0.0,
                'missing_games_count': 0,
                'is_production_ready': False,
                'data_quality_issues': [],
                'last_reprocess_attempt_at': None,
                'reprocess_attempt_count': 0,
                'circuit_breaker_active': False,
                'circuit_breaker_until': None,
                'manual_override_required': False,
                'season_boundary_detected': False,
                'backfill_bootstrap_mode': True,
                'processing_decision_reason': 'early_season_placeholder',

                # Timestamps
                'created_at': datetime.now(timezone.utc).isoformat(),
                'updated_at': None
            }

            # Add source hashes (Smart Reprocessing - Pattern #3)
            record['source_daily_cache_hash'] = self.source_daily_cache_hash
            record['source_composite_hash'] = self.source_composite_hash
            record['source_shot_zones_hash'] = self.source_shot_zones_hash
            record['source_team_defense_hash'] = self.source_team_defense_hash

            # Compute and add data hash (Smart Idempotency - Pattern #1)
            record['data_hash'] = self.compute_data_hash(record)

            self.transformed_data.append(record)
        
        logger.info(f"Created {len(self.transformed_data)} early season placeholder records")

    # ========================================================================
    # CIRCUIT BREAKER METHODS (Week 4 - Completeness Checking)
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

    def _query_upstream_completeness(self, all_players: List[str], analysis_date: date) -> Dict[str, Dict[str, bool]]:
        """
        Query upstream Phase 4 tables for is_production_ready status (CASCADE PATTERN).

        Checks 4 upstream dependencies:
        1. player_daily_cache.is_production_ready (per player)
        2. player_composite_factors.is_production_ready (per player)
        3. player_shot_zone_analysis.is_production_ready (per player)
        4. team_defense_zone_analysis.is_production_ready (per opponent team)

        Args:
            all_players: List of player_lookup IDs
            analysis_date: Date to check

        Returns:
            Dict mapping player_lookup to upstream status dict:
            {
                'player_lookup': {
                    'player_daily_cache_ready': bool,
                    'player_composite_factors_ready': bool,
                    'player_shot_zone_ready': bool,
                    'team_defense_zone_ready': bool,
                    'all_upstreams_ready': bool
                }
            }
        """
        upstream_status = {}

        try:
            # Query 1: player_daily_cache
            query = f"""
            SELECT player_lookup, is_production_ready
            FROM `{self.project_id}.nba_precompute.player_daily_cache`
            WHERE cache_date = '{analysis_date}'
              AND player_lookup IN UNNEST(@players)
            """
            daily_cache_df = self.bq_client.query(
                query,
                job_config=bigquery.QueryJobConfig(
                    query_parameters=[bigquery.ArrayQueryParameter("players", "STRING", list(all_players))]
                )
            ).to_dataframe()

            # Query 2: player_composite_factors
            query = f"""
            SELECT player_lookup, is_production_ready
            FROM `{self.project_id}.nba_precompute.player_composite_factors`
            WHERE game_date = '{analysis_date}'
              AND player_lookup IN UNNEST(@players)
            """
            composite_df = self.bq_client.query(
                query,
                job_config=bigquery.QueryJobConfig(
                    query_parameters=[bigquery.ArrayQueryParameter("players", "STRING", list(all_players))]
                )
            ).to_dataframe()

            # Query 3: player_shot_zone_analysis
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

            # Query 4: team_defense_zone_analysis (by opponent)
            # Get opponent teams for each player from feature_extractor
            players_with_games = self.feature_extractor.get_players_with_games(analysis_date)
            opponent_map = {p['player_lookup']: p.get('opponent_team_abbr') for p in players_with_games}
            unique_opponents = list(set(opponent_map.values()))

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

            # Build status dict for each player
            for player in all_players:
                # Check each upstream
                daily_cache_ready = False
                if player in daily_cache_df['player_lookup'].values:
                    daily_cache_ready = bool(daily_cache_df[daily_cache_df['player_lookup'] == player]['is_production_ready'].iloc[0])

                composite_ready = False
                if player in composite_df['player_lookup'].values:
                    composite_ready = bool(composite_df[composite_df['player_lookup'] == player]['is_production_ready'].iloc[0])

                shot_zone_ready = False
                if player in shot_zone_df['player_lookup'].values:
                    shot_zone_ready = bool(shot_zone_df[shot_zone_df['player_lookup'] == player]['is_production_ready'].iloc[0])

                team_defense_ready = False
                opponent_team = opponent_map.get(player)
                if opponent_team and opponent_team in team_defense_df['team_abbr'].values:
                    team_defense_ready = bool(team_defense_df[team_defense_df['team_abbr'] == opponent_team]['is_production_ready'].iloc[0])

                upstream_status[player] = {
                    'player_daily_cache_ready': daily_cache_ready,
                    'player_composite_factors_ready': composite_ready,
                    'player_shot_zone_ready': shot_zone_ready,
                    'team_defense_zone_ready': team_defense_ready,
                    'all_upstreams_ready': (daily_cache_ready and composite_ready and
                                           shot_zone_ready and team_defense_ready)
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
                    'player_daily_cache_ready': False,
                    'player_composite_factors_ready': False,
                    'player_shot_zone_ready': False,
                    'team_defense_zone_ready': False,
                    'all_upstreams_ready': False
                }

        return upstream_status

    # ========================================================================
    # CALCULATION - MAIN FLOW
    # ========================================================================
    
    def calculate_precompute(self) -> None:
        """
        Calculate 25 features for each player.

        Flow:
        1. Batch completeness checking (Week 4)
        2. Iterate through each player with a game today
        3. Extract Phase 4 data (preferred)
        4. Fallback to Phase 3 if Phase 4 incomplete
        5. Calculate 6 derived features
        6. Calculate quality score
        7. Build output record with source tracking
        """
        if self.early_season_flag:
            # Placeholders already created in extract_raw_data()
            logger.info("Early season - using placeholder records")
            return

        if self.players_with_games is None or len(self.players_with_games) == 0:
            logger.warning("No players to process")
            return

        self.transformed_data = []
        self.failed_entities = []

        # Get all players and analysis date
        all_players = [p['player_lookup'] for p in self.players_with_games]
        analysis_date = self.opts['analysis_date']

        # ============================================================
        # NEW (Week 4): Batch completeness checking
        # ============================================================
        logger.info(f"Checking completeness for {len(all_players)} players...")

        # Check own data completeness (player_game_summary - base data for features)
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

        logger.info(f"Calculating features for {len(self.players_with_games)} players")

        for idx, player_row in enumerate(self.players_with_games):
            try:
                player_lookup = player_row.get('player_lookup', 'unknown')

                # ============================================================
                # NEW (Week 4): Get completeness for this player
                # ============================================================
                completeness = completeness_results.get(player_lookup, {
                    'expected_count': 0, 'actual_count': 0, 'completeness_pct': 0.0,
                    'missing_count': 0, 'is_complete': False, 'is_production_ready': False
                })

                # Check circuit breaker
                circuit_breaker_status = self._check_circuit_breaker(player_lookup, analysis_date)

                if circuit_breaker_status['active']:
                    logger.warning(
                        f"{player_lookup}: Circuit breaker active until "
                        f"{circuit_breaker_status['until']} - skipping"
                    )
                    self.failed_entities.append({
                        'entity_id': player_lookup,
                        'entity_type': 'player',
                        'reason': f"Circuit breaker active until {circuit_breaker_status['until']}",
                        'category': 'CIRCUIT_BREAKER_ACTIVE'
                    })
                    continue

                # Check production readiness (skip if incomplete, unless in bootstrap mode)
                if not completeness['is_production_ready'] and not is_bootstrap:
                    logger.warning(
                        f"{player_lookup}: Completeness {completeness['completeness_pct']:.1f}% "
                        f"({completeness['actual_count']}/{completeness['expected_count']} games) - skipping"
                    )

                    # Track reprocessing attempt
                    self._increment_reprocess_count(
                        player_lookup, analysis_date,
                        completeness['completeness_pct'],
                        'incomplete_own_data'
                    )

                    self.failed_entities.append({
                        'entity_id': player_lookup,
                        'entity_type': 'player',
                        'reason': f"Incomplete own data: {completeness['completeness_pct']:.1f}%",
                        'category': 'INCOMPLETE_DATA_SKIPPED'
                    })
                    continue

                # Check upstream completeness (CASCADE PATTERN)
                upstream_status = upstream_completeness.get(player_lookup, {
                    'player_daily_cache_ready': False,
                    'player_composite_factors_ready': False,
                    'player_shot_zone_ready': False,
                    'team_defense_zone_ready': False,
                    'all_upstreams_ready': False
                })

                if not upstream_status['all_upstreams_ready'] and not is_bootstrap:
                    logger.warning(
                        f"{player_lookup}: Upstream not ready "
                        f"(daily_cache={upstream_status['player_daily_cache_ready']}, "
                        f"composite={upstream_status['player_composite_factors_ready']}, "
                        f"shot_zone={upstream_status['player_shot_zone_ready']}, "
                        f"team_defense={upstream_status['team_defense_zone_ready']}) - skipping"
                    )

                    # Track reprocessing attempt
                    self._increment_reprocess_count(
                        player_lookup, analysis_date,
                        completeness['completeness_pct'],
                        'incomplete_upstream_dependencies'
                    )

                    self.failed_entities.append({
                        'entity_id': player_lookup,
                        'entity_type': 'player',
                        'reason': f"Upstream Phase 4 dependencies not ready",
                        'category': 'UPSTREAM_INCOMPLETE'
                    })
                    continue
                # ============================================================

                # Generate features for this player
                start_time = datetime.now()
                record = self._generate_player_features(player_row, completeness, upstream_status, circuit_breaker_status, is_bootstrap, is_season_boundary)
                generation_time_ms = (datetime.now() - start_time).total_seconds() * 1000

                record['feature_generation_time_ms'] = int(generation_time_ms)

                self.transformed_data.append(record)

                if (idx + 1) % 50 == 0:
                    logger.info(f"Processed {idx + 1}/{len(self.players_with_games)} players")

            except Exception as e:
                player_lookup = player_row.get('player_lookup', 'unknown')
                logger.error(f"Failed to process {player_lookup}: {e}")

                self.failed_entities.append({
                    'entity_id': player_lookup,
                    'entity_type': 'player',
                    'reason': str(e),
                    'category': 'calculation_error'
                })
        
        success_count = len(self.transformed_data)
        fail_count = len(self.failed_entities)
        success_rate = (success_count / (success_count + fail_count) * 100) if (success_count + fail_count) > 0 else 0
        
        logger.info(f"Feature generation complete: {success_count} success, {fail_count} failed ({success_rate:.1f}% success rate)")
    
    def _generate_player_features(self, player_row: Dict, completeness: Dict, upstream_status: Dict, circuit_breaker_status: Dict, is_bootstrap: bool, is_season_boundary: bool) -> Dict:
        """
        Generate complete feature vector for one player.

        Args:
            player_row: Dict with player_lookup, game_date, game_id, etc.
            completeness: Completeness check results for this player (own data)
            upstream_status: Upstream completeness status (CASCADE PATTERN)
            circuit_breaker_status: Circuit breaker status for this player
            is_bootstrap: Whether in bootstrap mode
            is_season_boundary: Whether at season boundary

        Returns:
            Dict with complete record ready for BigQuery (with v4.0 source tracking + completeness metadata)
        """
        player_lookup = player_row['player_lookup']
        game_date = self.opts['analysis_date']
        
        # Extract Phase 4 data (preferred)
        phase4_data = self.feature_extractor.extract_phase4_data(player_lookup, game_date)
        
        # Extract Phase 3 data (fallback + calculated features)
        phase3_data = self.feature_extractor.extract_phase3_data(player_lookup, game_date)
        
        # Generate 25 features
        features, feature_sources = self._extract_all_features(phase4_data, phase3_data)
        
        # Calculate quality score
        quality_score = self.quality_scorer.calculate_quality_score(feature_sources)
        data_source = self.quality_scorer.determine_primary_source(feature_sources)
        
        # Build output record with v4.0 source tracking
        record = {
            'player_lookup': player_lookup,
            'universal_player_id': player_row.get('universal_player_id'),
            'game_date': game_date.isoformat(),
            'game_id': player_row['game_id'],
            
            # Features
            'features': features,  # List of 25 floats
            'feature_names': FEATURE_NAMES,
            'feature_count': FEATURE_COUNT,
            'feature_version': FEATURE_VERSION,
            
            # Context
            'opponent_team_abbr': player_row.get('opponent_team_abbr'),
            'is_home': player_row.get('is_home'),
            'days_rest': phase3_data.get('days_rest'),
            
            # Quality
            'feature_quality_score': quality_score,
            'data_source': data_source,
            
            # v4.0 Source tracking (one line via base class method!)
            **self.build_source_tracking_fields(),

            # ============================================================
            # NEW (Week 4): Completeness Checking Metadata (14 fields)
            # ============================================================
            # Completeness Metrics
            'expected_games_count': completeness['expected_count'],
            'actual_games_count': completeness['actual_count'],
            'completeness_percentage': completeness['completeness_pct'],
            'missing_games_count': completeness['missing_count'],

            # Production Readiness (CASCADE PATTERN: own complete AND all Phase 4 upstreams complete)
            'is_production_ready': (
                completeness['is_production_ready'] and
                upstream_status['all_upstreams_ready']
            ),
            'data_quality_issues': [issue for issue in [
                "upstream_player_daily_cache_incomplete" if not upstream_status['player_daily_cache_ready'] else None,
                "upstream_player_composite_factors_incomplete" if not upstream_status['player_composite_factors_ready'] else None,
                "upstream_player_shot_zone_incomplete" if not upstream_status['player_shot_zone_ready'] else None,
                "upstream_team_defense_zone_incomplete" if not upstream_status['team_defense_zone_ready'] else None,
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
            'updated_at': None
        }

        # Add source hashes (Smart Reprocessing - Pattern #3)
        record['source_daily_cache_hash'] = self.source_daily_cache_hash
        record['source_composite_hash'] = self.source_composite_hash
        record['source_shot_zones_hash'] = self.source_shot_zones_hash
        record['source_team_defense_hash'] = self.source_team_defense_hash

        # Compute and add data hash (Smart Idempotency - Pattern #1)
        record['data_hash'] = self.compute_data_hash(record)

        return record
    
    def _extract_all_features(self, phase4_data: Dict, phase3_data: Dict) -> tuple:
        """
        Extract all 25 features with Phase 4 → Phase 3 → Default fallback.
        
        Args:
            phase4_data: Dict with Phase 4 table data
            phase3_data: Dict with Phase 3 table data
            
        Returns:
            tuple: (features_list, feature_sources_dict)
                features_list: List of 25 float values
                feature_sources_dict: Dict mapping feature index to source
        """
        features = []
        feature_sources = {}
        
        # Features 0-4: Recent Performance
        features.append(self._get_feature_with_fallback(0, 'points_avg_last_5', phase4_data, phase3_data, 10.0, feature_sources))
        features.append(self._get_feature_with_fallback(1, 'points_avg_last_10', phase4_data, phase3_data, 10.0, feature_sources))
        features.append(self._get_feature_with_fallback(2, 'points_avg_season', phase4_data, phase3_data, 10.0, feature_sources))
        features.append(self._get_feature_with_fallback(3, 'points_std_last_10', phase4_data, phase3_data, 5.0, feature_sources))
        features.append(self._get_feature_with_fallback(4, 'games_in_last_7_days', phase4_data, phase3_data, 3.0, feature_sources))
        
        # Features 5-8: Composite Factors (Phase 4 ONLY)
        features.append(self._get_feature_phase4_only(5, 'fatigue_score', phase4_data, 50.0, feature_sources))
        features.append(self._get_feature_phase4_only(6, 'shot_zone_mismatch_score', phase4_data, 0.0, feature_sources))
        features.append(self._get_feature_phase4_only(7, 'pace_score', phase4_data, 0.0, feature_sources))
        features.append(self._get_feature_phase4_only(8, 'usage_spike_score', phase4_data, 0.0, feature_sources))
        
        # Features 9-12: Derived Factors (CALCULATE)
        features.append(self.feature_calculator.calculate_rest_advantage(phase3_data))
        feature_sources[9] = 'calculated'
        
        features.append(self.feature_calculator.calculate_injury_risk(phase3_data))
        feature_sources[10] = 'calculated'
        
        features.append(self.feature_calculator.calculate_recent_trend(phase3_data))
        feature_sources[11] = 'calculated'
        
        features.append(self.feature_calculator.calculate_minutes_change(phase4_data, phase3_data))
        feature_sources[12] = 'calculated'
        
        # Features 13-14: Matchup Context
        features.append(self._get_feature_with_fallback(13, 'opponent_def_rating', phase4_data, phase3_data, 112.0, feature_sources))
        features.append(self._get_feature_with_fallback(14, 'opponent_pace', phase4_data, phase3_data, 100.0, feature_sources))
        
        # Features 15-17: Game Context (Phase 3 only)
        features.append(float(phase3_data.get('home_game', 0)))
        feature_sources[15] = 'phase3'
        
        features.append(float(phase3_data.get('back_to_back', 0)))
        feature_sources[16] = 'phase3'
        
        features.append(1.0 if phase3_data.get('season_phase', '').lower() == 'playoffs' else 0.0)
        feature_sources[17] = 'phase3'
        
        # Features 18-21: Shot Zones
        features.append(self._get_feature_with_fallback(18, 'paint_rate_last_10', phase4_data, phase3_data, 30.0, feature_sources) / 100.0)  # Convert to decimal
        features.append(self._get_feature_with_fallback(19, 'mid_range_rate_last_10', phase4_data, phase3_data, 20.0, feature_sources) / 100.0)
        features.append(self._get_feature_with_fallback(20, 'three_pt_rate_last_10', phase4_data, phase3_data, 35.0, feature_sources) / 100.0)
        
        features.append(self.feature_calculator.calculate_pct_free_throw(phase3_data))
        feature_sources[21] = 'calculated'
        
        # Features 22-24: Team Context
        features.append(self._get_feature_with_fallback(22, 'team_pace_last_10', phase4_data, phase3_data, 100.0, feature_sources))
        features.append(self._get_feature_with_fallback(23, 'team_off_rating_last_10', phase4_data, phase3_data, 112.0, feature_sources))
        
        features.append(self.feature_calculator.calculate_team_win_pct(phase3_data))
        feature_sources[24] = 'calculated'
        
        return features, feature_sources
    
    def _get_feature_with_fallback(self, index: int, field_name: str, 
                                   phase4_data: Dict, phase3_data: Dict,
                                   default: float, feature_sources: Dict) -> float:
        """
        Get feature with Phase 4 → Phase 3 → default fallback.
        
        Args:
            index: Feature index (0-24)
            field_name: Field name in source dicts
            phase4_data: Phase 4 data dict
            phase3_data: Phase 3 data dict
            default: Default value if all sources missing
            feature_sources: Dict to track source (mutated)
            
        Returns:
            float: Feature value
        """
        # Try Phase 4 first
        if field_name in phase4_data and phase4_data[field_name] is not None:
            feature_sources[index] = 'phase4'
            return float(phase4_data[field_name])
        
        # Fallback to Phase 3
        if field_name in phase3_data and phase3_data[field_name] is not None:
            feature_sources[index] = 'phase3'
            return float(phase3_data[field_name])
        
        # Last resort: default
        feature_sources[index] = 'default'
        return float(default)
    
    def _get_feature_phase4_only(self, index: int, field_name: str,
                                 phase4_data: Dict, default: float,
                                 feature_sources: Dict) -> float:
        """
        Get feature from Phase 4 ONLY (no Phase 3 fallback).
        
        Args:
            index: Feature index (5-8)
            field_name: Field name in Phase 4 dict
            phase4_data: Phase 4 data dict
            default: Default value if Phase 4 missing
            feature_sources: Dict to track source (mutated)
            
        Returns:
            float: Feature value
        """
        if field_name in phase4_data and phase4_data[field_name] is not None:
            feature_sources[index] = 'phase4'
            return float(phase4_data[field_name])
        
        # No Phase 3 fallback - use default
        feature_sources[index] = 'default'
        logger.warning(f"Feature {index} ({field_name}) missing from Phase 4, using default={default}")
        return float(default)
    
    # ========================================================================
    # SAVE TO BIGQUERY (Override base class)
    # ========================================================================
    
    def save_precompute(self) -> None:
        """
        Save feature vectors to BigQuery using BatchWriter.
        
        Overrides base class because:
        1. Cross-dataset write (nba_predictions not nba_precompute)
        2. Uses specialized BatchWriter with retry logic
        3. Different merge key (player_lookup + game_date)
        """
        if not self.transformed_data:
            logger.warning("No transformed data to write")
            return
        
        analysis_date = self.opts['analysis_date']
        
        logger.info(f"Writing {len(self.transformed_data)} feature records to {self.dataset_id}.{self.table_name}")
        
        # Write using BatchWriter (handles DELETE + batch INSERT with retries)
        write_stats = self.batch_writer.write_batch(
            rows=self.transformed_data,
            dataset_id=self.dataset_id,  # nba_predictions
            table_name=self.table_name,   # ml_feature_store_v2
            game_date=analysis_date
        )
        
        # Track stats for monitoring
        self.stats['rows_processed'] = write_stats['rows_processed']
        self.stats['rows_failed'] = write_stats['rows_failed']
        self.stats['batches_written'] = write_stats['batches_written']
        self.stats['batches_failed'] = write_stats['batches_failed']
        
        if write_stats['errors']:
            logger.error(f"Write errors: {write_stats['errors']}")
        
        logger.info(f"Write complete: {write_stats['rows_processed']}/{len(self.transformed_data)} rows "
                   f"({write_stats['batches_written']} batches)")
    
    # ========================================================================
    # STATS & REPORTING
    # ========================================================================
    
    def get_precompute_stats(self) -> dict:
        """Get processor-specific stats for logging."""
        return {
            'players_processed': len(self.transformed_data) if self.transformed_data else 0,
            'players_failed': len(self.failed_entities) if hasattr(self, 'failed_entities') else 0,
            'early_season': self.early_season_flag,
            'feature_version': self.feature_version,
            'feature_count': self.feature_count
        }