# File: data_processors/precompute/ml_feature_store/feature_extractor.py
"""
Feature Extractor - Query Phase 3/4 Tables

Extracts raw data from:
- Phase 4 (preferred): player_daily_cache, player_composite_factors,
                       player_shot_zone_analysis, team_defense_zone_analysis
- Phase 3 (fallback): player_game_summary, upcoming_player_game_context,
                      team_offense_game_summary, team_defense_game_summary

Version: 1.4 (Optimized queries with date range pruning for 3-4x speedup)
"""

import logging
from datetime import date, timedelta
from typing import Dict, List, Optional, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.cloud import bigquery
import pandas as pd
import time

logger = logging.getLogger(__name__)


class FeatureExtractor:
    """Extract features from Phase 3/4 BigQuery tables."""

    def __init__(self, bq_client: bigquery.Client, project_id: str) -> None:
        """
        Initialize feature extractor.

        Args:
            bq_client: BigQuery client instance
            project_id: GCP project ID
        """
        self.bq_client: bigquery.Client = bq_client
        self.project_id: str = project_id

        # Batch extraction cache (populated by batch_extract_* methods)
        self._batch_cache_date: Optional[date] = None
        self._daily_cache_lookup: Dict[str, Dict] = {}
        self._composite_factors_lookup: Dict[str, Dict] = {}
        self._shot_zone_lookup: Dict[str, Dict] = {}
        self._team_defense_lookup: Dict[str, Dict] = {}
        self._player_context_lookup: Dict[str, Dict] = {}
        self._last_10_games_lookup: Dict[str, List[Dict]] = {}
        self._season_stats_lookup: Dict[str, Dict] = {}
        self._team_games_lookup: Dict[str, List[Dict]] = {}
    
    # ========================================================================
    # PLAYER LIST
    # ========================================================================
    
    def get_players_with_games(self, game_date: date, backfill_mode: bool = False) -> List[Dict[str, Any]]:
        """
        Get list of all players with games on game_date.

        v3.2 CHANGE (All-Player Predictions):
        Now includes has_prop_line flag to indicate which players have betting lines.

        v3.3 CHANGE (Backfill Mode):
        When backfill_mode=True, queries player_game_summary (who actually played)
        instead of upcoming_player_game_context (who was expected to play).
        This increases backfill coverage from ~65% to ~100% for historical dates.

        Args:
            game_date: Date to query
            backfill_mode: If True, use actual played data instead of expected

        Returns:
            List of dicts with player_lookup, game_id, opponent, has_prop_line, etc.
        """
        if backfill_mode:
            # For historical backfill: use actual played data from player_game_summary
            # This captures ALL players who played, not just those expected to play
            query = f"""
            WITH player_rest AS (
                -- Calculate days rest from previous game
                SELECT
                    player_lookup,
                    game_date,
                    DATE_DIFF(
                        game_date,
                        LAG(game_date) OVER (PARTITION BY player_lookup ORDER BY game_date),
                        DAY
                    ) AS days_since_last
                FROM `{self.project_id}.nba_analytics.player_game_summary`
                WHERE game_date <= '{game_date}'
            )
            SELECT
                pgs.player_lookup,
                pgs.universal_player_id,
                pgs.game_id,
                pgs.game_date,
                pgs.opponent_team_abbr,
                -- Derive is_home from game_id pattern (home team is second in game_id)
                CASE
                    WHEN SPLIT(pgs.game_id, '_')[SAFE_OFFSET(2)] = pgs.team_abbr THEN TRUE
                    ELSE FALSE
                END AS is_home,
                COALESCE(pr.days_since_last, 3) AS days_rest,  -- Default 3 days if first game
                FALSE AS has_prop_line,  -- No betting lines for backfill
                CAST(NULL AS FLOAT64) AS current_points_line
            FROM `{self.project_id}.nba_analytics.player_game_summary` pgs
            LEFT JOIN player_rest pr
                ON pgs.player_lookup = pr.player_lookup AND pgs.game_date = pr.game_date
            WHERE pgs.game_date = '{game_date}'
            ORDER BY pgs.player_lookup
            """
            logger.info(f"[BACKFILL MODE] Querying actual played roster for {game_date}")
        else:
            # For real-time: use expected players from upcoming_player_game_context
            query = f"""
            SELECT
                player_lookup,
                universal_player_id,
                game_id,
                game_date,
                opponent_team_abbr,
                home_game AS is_home,
                days_rest,
                COALESCE(has_prop_line, FALSE) AS has_prop_line,  -- v3.2: Track if player has betting line
                current_points_line  -- v3.2: Pass through for estimated lines
            FROM `{self.project_id}.nba_analytics.upcoming_player_game_context`
            WHERE game_date = '{game_date}'
            ORDER BY player_lookup
            """
            logger.debug(f"Querying expected players with games on {game_date}")

        result: pd.DataFrame = self.bq_client.query(query).to_dataframe()

        if result.empty:
            logger.warning(f"No players found with games on {game_date}")
            return []

        logger.info(f"Found {len(result)} players with games on {game_date}" +
                   (" [BACKFILL MODE]" if backfill_mode else ""))
        return result.to_dict('records')

    # ========================================================================
    # BATCH EXTRACTION (20x SPEEDUP FOR BACKFILL)
    # ========================================================================

    def batch_extract_all_data(self, game_date: date, players_with_games: List[Dict[str, Any]]) -> None:
        """
        Batch extract all Phase 3/4 data for a game date.

        Call this ONCE at the start of processing a day. Subsequent calls to
        extract_phase4_data() and extract_phase3_data() will use cached data.

        Performance: 8 queries run in PARALLEL using ThreadPoolExecutor
        v1.4: Now runs all batch extractions concurrently for ~3x speedup

        Args:
            game_date: Date to extract data for
            players_with_games: List of player dicts (from get_players_with_games)
        """
        if self._batch_cache_date == game_date:
            logger.debug(f"Batch cache already populated for {game_date}")
            return

        start_time = time.time()
        logger.info(f"Batch extracting all data for {game_date} ({len(players_with_games)} players)")

        # Clear old cache
        self._clear_batch_cache()
        self._batch_cache_date = game_date

        # Get list of all players and teams for batch queries
        all_players = [p['player_lookup'] for p in players_with_games]
        all_opponents = list(set(p.get('opponent_team_abbr') for p in players_with_games if p.get('opponent_team_abbr')))
        all_teams = list(set(p.get('team_abbr') for p in players_with_games if p.get('team_abbr')))

        # Run ALL 8 batch extractions in PARALLEL using ThreadPoolExecutor
        # Each query is independent and can run concurrently
        extraction_tasks = [
            ('daily_cache', lambda: self._batch_extract_daily_cache(game_date)),
            ('composite_factors', lambda: self._batch_extract_composite_factors(game_date)),
            ('shot_zone', lambda: self._batch_extract_shot_zone(game_date)),
            ('team_defense', lambda: self._batch_extract_team_defense(game_date, all_opponents)),
            ('player_context', lambda: self._batch_extract_player_context(game_date)),
            ('last_10_games', lambda: self._batch_extract_last_10_games(game_date, all_players)),
            ('season_stats', lambda: self._batch_extract_season_stats(game_date, all_players)),
            ('team_games', lambda: self._batch_extract_team_games(game_date, all_teams)),
        ]

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(task[1]): task[0] for task in extraction_tasks}
            for future in as_completed(futures):
                task_name = futures[future]
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Batch extraction failed for {task_name}: {e}")
                    raise

        elapsed = time.time() - start_time
        logger.info(
            f"Batch extraction complete in {elapsed:.1f}s: "
            f"{len(self._daily_cache_lookup)} daily_cache, "
            f"{len(self._composite_factors_lookup)} composite, "
            f"{len(self._shot_zone_lookup)} shot_zone, "
            f"{len(self._team_defense_lookup)} team_defense, "
            f"{len(self._player_context_lookup)} player_context, "
            f"{len(self._last_10_games_lookup)} last_10_games"
        )

    def _clear_batch_cache(self) -> None:
        """Clear all batch extraction caches."""
        self._batch_cache_date = None
        self._daily_cache_lookup = {}
        self._composite_factors_lookup = {}
        self._shot_zone_lookup = {}
        self._team_defense_lookup = {}
        self._player_context_lookup = {}
        self._last_10_games_lookup = {}
        self._season_stats_lookup = {}
        self._team_games_lookup = {}

    def _batch_extract_daily_cache(self, game_date: date) -> None:
        """Batch extract player_daily_cache for all players."""
        query = f"""
        SELECT
            player_lookup,
            points_avg_last_5,
            points_avg_last_10,
            points_avg_season,
            points_std_last_10,
            games_in_last_7_days,
            paint_rate_last_10,
            three_pt_rate_last_10,
            assisted_rate_last_10,
            team_pace_last_10,
            team_off_rating_last_10,
            minutes_avg_last_10,
            player_age
        FROM `{self.project_id}.nba_precompute.player_daily_cache`
        WHERE cache_date = '{game_date}'
        """
        result = self.bq_client.query(query).to_dataframe()
        # Use efficient to_dict instead of iterrows (3x faster)
        if not result.empty:
            for record in result.to_dict('records'):
                self._daily_cache_lookup[record['player_lookup']] = record
        logger.debug(f"Batch daily_cache: {len(self._daily_cache_lookup)} rows")

    def _batch_extract_composite_factors(self, game_date: date) -> None:
        """Batch extract player_composite_factors for all players."""
        query = f"""
        SELECT
            player_lookup,
            fatigue_score,
            shot_zone_mismatch_score,
            pace_score,
            usage_spike_score
        FROM `{self.project_id}.nba_precompute.player_composite_factors`
        WHERE game_date = '{game_date}'
        """
        result = self.bq_client.query(query).to_dataframe()
        # Use efficient to_dict instead of iterrows (3x faster)
        if not result.empty:
            for record in result.to_dict('records'):
                self._composite_factors_lookup[record['player_lookup']] = record
        logger.debug(f"Batch composite_factors: {len(self._composite_factors_lookup)} rows")

    def _batch_extract_shot_zone(self, game_date: date) -> None:
        """Batch extract player_shot_zone_analysis for all players."""
        query = f"""
        SELECT
            player_lookup,
            paint_rate_last_10,
            mid_range_rate_last_10,
            three_pt_rate_last_10
        FROM `{self.project_id}.nba_precompute.player_shot_zone_analysis`
        WHERE analysis_date = '{game_date}'
        """
        result = self.bq_client.query(query).to_dataframe()
        # Use efficient to_dict instead of iterrows (3x faster)
        if not result.empty:
            for record in result.to_dict('records'):
                self._shot_zone_lookup[record['player_lookup']] = record
        logger.debug(f"Batch shot_zone: {len(self._shot_zone_lookup)} rows")

    def _batch_extract_team_defense(self, game_date: date, team_abbrs: List[str]) -> None:
        """Batch extract team_defense_zone_analysis for all opponent teams."""
        if not team_abbrs:
            return
        query = f"""
        SELECT
            team_abbr,
            defensive_rating_last_15 AS opponent_def_rating,
            opponent_pace
        FROM `{self.project_id}.nba_precompute.team_defense_zone_analysis`
        WHERE analysis_date = '{game_date}'
        """
        result = self.bq_client.query(query).to_dataframe()
        # Use efficient to_dict instead of iterrows (3x faster)
        if not result.empty:
            for record in result.to_dict('records'):
                self._team_defense_lookup[record['team_abbr']] = record
        logger.debug(f"Batch team_defense: {len(self._team_defense_lookup)} rows")

    def _batch_extract_player_context(self, game_date: date) -> None:
        """Batch extract upcoming_player_game_context for all players."""
        query = f"""
        SELECT
            player_lookup,
            game_date,
            game_id,
            team_abbr,
            opponent_team_abbr,
            home_game,
            back_to_back,
            season_phase,
            days_rest,
            player_status,
            opponent_days_rest
        FROM `{self.project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date = '{game_date}'
        """
        result = self.bq_client.query(query).to_dataframe()
        # Use efficient to_dict instead of iterrows (3x faster)
        if not result.empty:
            for record in result.to_dict('records'):
                self._player_context_lookup[record['player_lookup']] = record
        logger.debug(f"Batch player_context: {len(self._player_context_lookup)} rows")

    def _batch_extract_last_10_games(self, game_date: date, player_lookups: List[str]) -> None:
        """
        Batch extract last 10 games for all players using optimized query.

        v1.4 OPTIMIZATION: Added date range pruning to avoid full table scan.
        Uses 60-day lookback window which covers ~20+ games per player.
        Uses QUALIFY clause for efficient window function filtering.

        Performance: 300-450s → 30-60s (5-10x faster)
        """
        if not player_lookups:
            return

        # OPTIMIZATION: Add date range pruning to avoid full table scan
        # 60 days covers ~20+ games per player (more than enough for last 10)
        lookback_days = 60
        lookback_date = game_date - timedelta(days=lookback_days)

        # Use QUALIFY for efficient window function filtering (no CTE overhead)
        query = f"""
        SELECT
            player_lookup,
            game_date,
            points,
            minutes_played,
            ft_makes,
            fg_attempts,
            paint_attempts,
            mid_range_attempts,
            three_pt_attempts
        FROM `{self.project_id}.nba_analytics.player_game_summary`
        WHERE game_date < '{game_date}'
          AND game_date >= '{lookback_date}'
        QUALIFY ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) <= 10
        ORDER BY player_lookup, game_date DESC
        """
        result = self.bq_client.query(query).to_dataframe()

        # Group by player using efficient groupby
        if not result.empty:
            for player_lookup, group_df in result.groupby('player_lookup'):
                self._last_10_games_lookup[player_lookup] = group_df.to_dict('records')

        logger.debug(f"Batch last_10_games: {len(self._last_10_games_lookup)} players (60-day window)")

    def _batch_extract_season_stats(self, game_date: date, player_lookups: List[str]) -> None:
        """
        Batch extract season stats for all players.

        v1.4 OPTIMIZATION: Added explicit season start date for better partition pruning.
        Uses proper season boundaries (Oct 1 for fall, previous Oct for spring).

        Performance: 200-350s → 50-100s (3-5x faster)
        """
        if not player_lookups:
            return

        season_year = game_date.year if game_date.month >= 10 else game_date.year - 1

        # OPTIMIZATION: Calculate explicit season start for better query pruning
        # NBA season starts in mid-October, use Oct 1 as safe boundary
        season_start = date(season_year, 10, 1)

        query = f"""
        SELECT
            player_lookup,
            AVG(points) AS points_avg_season,
            AVG(minutes_played) AS minutes_avg_season,
            COUNT(*) AS games_played_season
        FROM `{self.project_id}.nba_analytics.player_game_summary`
        WHERE season_year = {season_year}
          AND game_date < '{game_date}'
          AND game_date >= '{season_start}'
        GROUP BY player_lookup
        """
        result = self.bq_client.query(query).to_dataframe()

        # Use efficient to_dict instead of iterrows
        if not result.empty:
            for record in result.to_dict('records'):
                self._season_stats_lookup[record['player_lookup']] = record

        logger.debug(f"Batch season_stats: {len(self._season_stats_lookup)} players (season {season_year})")

    def _batch_extract_team_games(self, game_date: date, team_abbrs: List[str]) -> None:
        """
        Batch extract team season games for win percentage calculation.

        v1.4 OPTIMIZATION: Added season start date for better partition pruning.
        """
        if not team_abbrs:
            return

        season_year = game_date.year if game_date.month >= 10 else game_date.year - 1

        # OPTIMIZATION: Add explicit season start for better query pruning
        season_start = date(season_year, 10, 1)

        query = f"""
        SELECT
            team_abbr,
            game_date,
            win_flag
        FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
        WHERE season_year = {season_year}
          AND game_date < '{game_date}'
          AND game_date >= '{season_start}'
        ORDER BY team_abbr, game_date
        """
        result = self.bq_client.query(query).to_dataframe()

        # Group by team using efficient groupby
        if not result.empty:
            for team_abbr, group_df in result.groupby('team_abbr'):
                self._team_games_lookup[team_abbr] = group_df.to_dict('records')

        logger.debug(f"Batch team_games: {len(self._team_games_lookup)} teams (season {season_year})")

    # ========================================================================
    # PHASE 4 EXTRACTION (PREFERRED)
    # ========================================================================
    
    def extract_phase4_data(self, player_lookup: str, game_date: date,
                            opponent_team_abbr: Optional[str] = None) -> Dict[str, Any]:
        """
        Extract all Phase 4 data for a player.

        Uses batch cache if available (call batch_extract_all_data first for 20x speedup).
        Falls back to per-player queries if cache not populated.

        Queries 4 Phase 4 tables:
        - player_daily_cache (features 0-4, 18-20, 22-23)
        - player_composite_factors (features 5-8)
        - player_shot_zone_analysis (features 18-20)
        - team_defense_zone_analysis (features 13-14)

        Args:
            player_lookup: Player identifier
            game_date: Game date
            opponent_team_abbr: Optional opponent team (from player row)

        Returns:
            Dict with all Phase 4 fields (may have None values)
        """
        phase4_data: Dict[str, Any] = {}

        # Check if batch cache is available for this date
        use_batch = (self._batch_cache_date == game_date)

        if use_batch:
            # Use batch cache (O(1) lookups - no BQ queries!)
            cache_data = self._daily_cache_lookup.get(player_lookup, {})
            phase4_data.update(cache_data)

            composite_data = self._composite_factors_lookup.get(player_lookup, {})
            phase4_data.update(composite_data)

            shot_zone_data = self._shot_zone_lookup.get(player_lookup, {})
            phase4_data.update(shot_zone_data)

            if opponent_team_abbr:
                team_defense_data = self._team_defense_lookup.get(opponent_team_abbr, {})
                phase4_data.update(team_defense_data)
        else:
            # Fall back to per-player queries (slow but works without batch)
            logger.debug(f"Extracting Phase 4 data for {player_lookup} on {game_date} (no batch cache)")

            cache_data = self._query_player_daily_cache(player_lookup, game_date)
            phase4_data.update(cache_data)

            composite_data = self._query_composite_factors(player_lookup, game_date)
            phase4_data.update(composite_data)

            shot_zone_data = self._query_shot_zone_analysis(player_lookup, game_date)
            phase4_data.update(shot_zone_data)

            if opponent_team_abbr:
                team_defense_data = self._query_team_defense(opponent_team_abbr, game_date)
                phase4_data.update(team_defense_data)

        return phase4_data
    
    def _query_player_daily_cache(self, player_lookup: str, game_date: date) -> Dict[str, Any]:
        """Query player_daily_cache table."""
        query = f"""
        SELECT
            -- Features 0-4: Recent Performance
            points_avg_last_5,
            points_avg_last_10,
            points_avg_season,
            points_std_last_10,
            games_in_last_7_days,
            
            -- Features 18-20: Shot Zones (partial)
            paint_rate_last_10,
            three_pt_rate_last_10,
            assisted_rate_last_10,
            
            -- Features 22-23: Team Context
            team_pace_last_10,
            team_off_rating_last_10,
            
            -- Additional context
            minutes_avg_last_10,
            player_age
        FROM `{self.project_id}.nba_precompute.player_daily_cache`
        WHERE player_lookup = '{player_lookup}'
          AND cache_date = '{game_date}'
        """
        
        result: pd.DataFrame = self.bq_client.query(query).to_dataframe()
        
        if result.empty:
            logger.debug(f"No player_daily_cache data for {player_lookup} on {game_date}")
            return {}
        
        data: Dict[str, Any] = result.iloc[0].to_dict()
        logger.debug(f"player_daily_cache: {len(data)} fields retrieved for {player_lookup}")
        return data
    
    def _query_composite_factors(self, player_lookup: str, game_date: date) -> Dict[str, Any]:
        """Query player_composite_factors table."""
        query = f"""
        SELECT
            -- Features 5-8: Composite Factors
            fatigue_score,
            shot_zone_mismatch_score,
            pace_score,
            usage_spike_score
        FROM `{self.project_id}.nba_precompute.player_composite_factors`
        WHERE player_lookup = '{player_lookup}'
          AND game_date = '{game_date}'
        """
        
        result: pd.DataFrame = self.bq_client.query(query).to_dataframe()
        
        if result.empty:
            logger.debug(f"No composite_factors data for {player_lookup} on {game_date}")
            return {}
        
        data: Dict[str, Any] = result.iloc[0].to_dict()
        logger.debug(f"composite_factors: {len(data)} fields retrieved for {player_lookup}")
        return data
    
    def _query_shot_zone_analysis(self, player_lookup: str, game_date: date) -> Dict[str, Any]:
        """Query player_shot_zone_analysis table."""
        query = f"""
        SELECT
            -- Features 18-20: Shot Zones
            paint_rate_last_10,
            mid_range_rate_last_10,
            three_pt_rate_last_10
        FROM `{self.project_id}.nba_precompute.player_shot_zone_analysis`
        WHERE player_lookup = '{player_lookup}'
          AND analysis_date = '{game_date}'
        """
        
        result: pd.DataFrame = self.bq_client.query(query).to_dataframe()
        
        if result.empty:
            logger.debug(f"No shot_zone_analysis data for {player_lookup} on {game_date}")
            return {}
        
        data: Dict[str, Any] = result.iloc[0].to_dict()
        logger.debug(f"shot_zone_analysis: {len(data)} fields retrieved for {player_lookup}")
        return data
    
    def _query_team_defense(self, team_abbr: str, game_date: date) -> Dict[str, Any]:
        """Query team_defense_zone_analysis table."""
        query = f"""
        SELECT
            -- Features 13-14: Opponent Defense
            defensive_rating_last_15 AS opponent_def_rating,
            opponent_pace
        FROM `{self.project_id}.nba_precompute.team_defense_zone_analysis`
        WHERE team_abbr = '{team_abbr}'
          AND analysis_date = '{game_date}'
        """
        
        result: pd.DataFrame = self.bq_client.query(query).to_dataframe()
        
        if result.empty:
            logger.debug(f"No team_defense data for {team_abbr} on {game_date}")
            return {}
        
        data: Dict[str, Any] = result.iloc[0].to_dict()
        logger.debug(f"team_defense: {len(data)} fields retrieved for {team_abbr}")
        return data
    
    # ========================================================================
    # PHASE 3 EXTRACTION (FALLBACK)
    # ========================================================================
    
    def extract_phase3_data(self, player_lookup: str, game_date: date) -> Dict[str, Any]:
        """
        Extract Phase 3 data for a player.

        Uses batch cache if available (call batch_extract_all_data first for 20x speedup).
        Falls back to per-player queries if cache not populated.

        Used as fallback when Phase 4 incomplete, and for calculated features.

        Args:
            player_lookup: Player identifier
            game_date: Game date

        Returns:
            Dict with Phase 3 fields
        """
        phase3_data: Dict[str, Any] = {}

        # Check if batch cache is available for this date
        use_batch = (self._batch_cache_date == game_date)

        if use_batch:
            # Use batch cache (O(1) lookups - no BQ queries!)
            context_data = self._player_context_lookup.get(player_lookup, {})
            phase3_data.update(context_data)

            last_10_games = self._last_10_games_lookup.get(player_lookup, [])
            phase3_data['last_10_games'] = last_10_games

            # Calculate aggregations from games
            if last_10_games:
                points_list = [(g.get('points') or 0) for g in last_10_games]
                phase3_data['points_avg_last_10'] = sum(points_list) / len(points_list)

                if len(last_10_games) >= 5:
                    phase3_data['points_avg_last_5'] = sum(points_list[:5]) / 5

            season_stats = self._season_stats_lookup.get(player_lookup, {})
            phase3_data.update(season_stats)

            team_abbr = context_data.get('team_abbr')
            if team_abbr:
                team_games = self._team_games_lookup.get(team_abbr, [])
                phase3_data['team_season_games'] = team_games
        else:
            # Fall back to per-player queries (slow but works without batch)
            logger.debug(f"Extracting Phase 3 data for {player_lookup} on {game_date} (no batch cache)")

            context_data = self._query_player_context(player_lookup, game_date)
            phase3_data.update(context_data)

            last_10_games = self._query_last_n_games(player_lookup, game_date, 10)
            phase3_data['last_10_games'] = last_10_games

            # Calculate aggregations from games
            if last_10_games:
                phase3_data['points_avg_last_10'] = sum(g['points'] for g in last_10_games) / len(last_10_games)

                if len(last_10_games) >= 5:
                    last_5 = last_10_games[:5]
                    phase3_data['points_avg_last_5'] = sum(g['points'] for g in last_5) / 5

            season_stats = self._query_season_stats(player_lookup, game_date)
            phase3_data.update(season_stats)

            team_abbr = context_data.get('team_abbr')
            if team_abbr:
                season_year = game_date.year if game_date.month >= 10 else game_date.year - 1
                team_games = self._query_team_season_games(team_abbr, season_year, game_date)
                phase3_data['team_season_games'] = team_games

        return phase3_data
    
    def _query_player_context(self, player_lookup: str, game_date: date) -> Dict[str, Any]:
        """Query upcoming_player_game_context."""
        query = f"""
        SELECT
            player_lookup,
            game_date,
            game_id,
            team_abbr,
            opponent_team_abbr,
            
            -- Features 15-17: Game Context
            home_game,
            back_to_back,
            season_phase,
            
            -- For calculated features
            days_rest,
            player_status,
            opponent_days_rest
        FROM `{self.project_id}.nba_analytics.upcoming_player_game_context`
        WHERE player_lookup = '{player_lookup}'
          AND game_date = '{game_date}'
        """
        
        result: pd.DataFrame = self.bq_client.query(query).to_dataframe()
        
        if result.empty:
            logger.warning(f"No upcoming_player_game_context for {player_lookup} on {game_date}")
            return {}
        
        data: Dict[str, Any] = result.iloc[0].to_dict()
        logger.debug(f"player_context: {len(data)} fields retrieved for {player_lookup}")
        return data
    
    def _query_last_n_games(self, player_lookup: str, game_date: date, n: int) -> List[Dict[str, Any]]:
        """Query last N games for a player."""
        query = f"""
        SELECT
            game_date,
            points,
            minutes_played,
            ft_makes,
            fg_attempts,
            paint_attempts,
            mid_range_attempts,
            three_pt_attempts
        FROM `{self.project_id}.nba_analytics.player_game_summary`
        WHERE player_lookup = '{player_lookup}'
          AND game_date < '{game_date}'
        ORDER BY game_date DESC
        LIMIT {n}
        """
        
        result: pd.DataFrame = self.bq_client.query(query).to_dataframe()
        
        if result.empty:
            logger.debug(f"No historical games for {player_lookup} before {game_date}")
            return []
        
        games: List[Dict[str, Any]] = result.to_dict('records')
        logger.debug(f"Retrieved {len(games)} games for {player_lookup}")
        return games
    
    def _query_season_stats(self, player_lookup: str, game_date: date) -> Dict[str, Any]:
        """Query season-level stats."""
        season_year = game_date.year if game_date.month >= 10 else game_date.year - 1
        
        query = f"""
        SELECT
            AVG(points) AS points_avg_season,
            AVG(minutes_played) AS minutes_avg_season,
            COUNT(*) AS games_played_season
        FROM `{self.project_id}.nba_analytics.player_game_summary`
        WHERE player_lookup = '{player_lookup}'
          AND season_year = {season_year}
          AND game_date < '{game_date}'
        """
        
        result: pd.DataFrame = self.bq_client.query(query).to_dataframe()
        
        if result.empty:
            logger.debug(f"No season stats for {player_lookup} in {season_year}")
            return {}
        
        data: Dict[str, Any] = result.iloc[0].to_dict()
        logger.debug(f"season_stats: {data.get('games_played_season', 0)} games for {player_lookup}")
        return data
    
    def _query_team_season_games(self, team_abbr: str, season_year: int, 
                                 game_date: date) -> List[Dict[str, Any]]:
        """Query team's season games for win percentage."""
        query = f"""
        SELECT
            game_date,
            win_flag
        FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
        WHERE team_abbr = '{team_abbr}'
          AND season_year = {season_year}
          AND game_date < '{game_date}'
        ORDER BY game_date
        """
        
        result: pd.DataFrame = self.bq_client.query(query).to_dataframe()
        
        if result.empty:
            logger.debug(f"No team games for {team_abbr} in {season_year}")
            return []
        
        games: List[Dict[str, Any]] = result.to_dict('records')
        logger.debug(f"Retrieved {len(games)} team games for {team_abbr}")
        return games