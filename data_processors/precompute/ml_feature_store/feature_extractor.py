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

        # V8 Model Features (added Jan 2026)
        self._vegas_lines_lookup: Dict[str, Dict] = {}
        self._opponent_history_lookup: Dict[str, Dict] = {}
        self._minutes_ppm_lookup: Dict[str, Dict] = {}

        # Historical Completeness Tracking (Data Cascade Architecture - Jan 2026)
        # Tracks total games available per player for bootstrap detection
        self._total_games_available_lookup: Dict[str, int] = {}

    def _safe_query(self, query: str, query_name: str = "query") -> pd.DataFrame:
        """
        Execute BigQuery query with error handling.

        Args:
            query: SQL query to execute
            query_name: Descriptive name for logging

        Returns:
            DataFrame with results, or empty DataFrame on error

        Raises:
            GoogleAPIError: Re-raises after logging if query fails
        """
        from google.api_core.exceptions import GoogleAPIError
        try:
            return self.bq_client.query(query).to_dataframe()
        except GoogleAPIError as e:
            logger.error(f"BigQuery query failed [{query_name}]: {e}")
            logger.debug(f"Failed query:\n{query[:500]}...")
            raise
    
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

        v3.4 CHANGE (Same-Day Fix):
        For same-day/future dates, ALWAYS use upcoming_player_game_context
        regardless of backfill_mode. player_game_summary won't have data for
        games that haven't been played yet.

        Args:
            game_date: Date to query
            backfill_mode: If True, use actual played data instead of expected

        Returns:
            List of dicts with player_lookup, game_id, opponent, has_prop_line, etc.
        """
        # v3.4: Determine if this is a same-day/future date (games not yet played)
        from datetime import datetime
        try:
            from zoneinfo import ZoneInfo
            today_et = datetime.now(ZoneInfo('America/New_York')).date()
        except ImportError:
            import pytz
            today_et = datetime.now(pytz.timezone('America/New_York')).date()

        is_future_or_today = game_date >= today_et

        # For future/same-day dates, ALWAYS use upcoming_player_game_context
        # regardless of backfill_mode, since player_game_summary won't have data
        use_backfill_query = backfill_mode and not is_future_or_today

        if backfill_mode and is_future_or_today:
            logger.info(f"[SAME-DAY FIX] backfill_mode=True but date {game_date} >= today {today_et}, using upcoming_player_game_context")

        if use_backfill_query:
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
            logger.info(f"[BACKFILL MODE - HISTORICAL] Querying actual played roster for {game_date}")
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

        result: pd.DataFrame = self._safe_query(query, f"get_players_with_games({game_date})")

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

        # Run ALL 11 batch extractions in PARALLEL using ThreadPoolExecutor
        # Each query is independent and can run concurrently
        # V8 Model: Added vegas_lines, opponent_history, minutes_ppm (Jan 2026)
        extraction_tasks = [
            ('daily_cache', lambda: self._batch_extract_daily_cache(game_date)),
            ('composite_factors', lambda: self._batch_extract_composite_factors(game_date)),
            ('shot_zone', lambda: self._batch_extract_shot_zone(game_date)),
            ('team_defense', lambda: self._batch_extract_team_defense(game_date, all_opponents)),
            ('player_context', lambda: self._batch_extract_player_context(game_date)),
            ('last_10_games', lambda: self._batch_extract_last_10_games(game_date, all_players)),
            ('season_stats', lambda: self._batch_extract_season_stats(game_date, all_players)),
            ('team_games', lambda: self._batch_extract_team_games(game_date, all_teams)),
            # V8 Model Features (Jan 2026)
            ('vegas_lines', lambda: self._batch_extract_vegas_lines(game_date, all_players)),
            ('opponent_history', lambda: self._batch_extract_opponent_history(game_date, players_with_games)),
            ('minutes_ppm', lambda: self._batch_extract_minutes_ppm(game_date, all_players)),
        ]

        # Auto-retry logic for transient network/BigQuery errors
        max_retries = 3
        retry_delays = [30, 60, 120]  # seconds between retries
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                # Clear cache before each attempt (in case partial data was written)
                if attempt > 0:
                    self._clear_batch_cache()
                    self._batch_cache_date = game_date

                with ThreadPoolExecutor(max_workers=11) as executor:
                    futures = {executor.submit(task[1]): task[0] for task in extraction_tasks}
                    for future in as_completed(futures):
                        task_name = futures[future]
                        try:
                            future.result()
                        except Exception as e:
                            logger.error(f"Batch extraction failed for {task_name}: {e}")
                            raise

                # Success - break out of retry loop
                if attempt > 0:
                    logger.info(f"Batch extraction succeeded on retry attempt {attempt}")
                break

            except Exception as e:
                last_error = e
                error_str = str(e).lower()

                # Check if error is retryable (transient network/timeout issues)
                is_retryable = any(keyword in error_str for keyword in [
                    'timeout', 'timed out', 'connection', 'reset', 'refused',
                    'unavailable', 'deadline', 'retryerror', 'httpsconnectionpool'
                ])

                if is_retryable and attempt < max_retries:
                    delay = retry_delays[attempt]
                    logger.warning(
                        f"Batch extraction failed with retryable error (attempt {attempt + 1}/{max_retries + 1}). "
                        f"Retrying in {delay}s... Error: {e}"
                    )
                    time.sleep(delay)
                else:
                    # Non-retryable error or max retries exceeded
                    if attempt >= max_retries:
                        logger.error(f"Batch extraction failed after {max_retries + 1} attempts. Giving up.")
                    raise

        elapsed = time.time() - start_time
        logger.info(
            f"Batch extraction complete in {elapsed:.1f}s: "
            f"{len(self._daily_cache_lookup)} daily_cache, "
            f"{len(self._composite_factors_lookup)} composite, "
            f"{len(self._shot_zone_lookup)} shot_zone, "
            f"{len(self._team_defense_lookup)} team_defense, "
            f"{len(self._player_context_lookup)} player_context, "
            f"{len(self._last_10_games_lookup)} last_10_games, "
            f"{len(self._vegas_lines_lookup)} vegas, "
            f"{len(self._opponent_history_lookup)} opponent_hist, "
            f"{len(self._minutes_ppm_lookup)} mins_ppm"
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
        # V8 Model Features
        self._vegas_lines_lookup = {}
        self._opponent_history_lookup = {}
        self._minutes_ppm_lookup = {}
        # Historical Completeness Tracking
        self._total_games_available_lookup = {}

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
        result = self._safe_query(query, "batch_extract")
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
        result = self._safe_query(query, "batch_extract")
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
        result = self._safe_query(query, "batch_extract")
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
        result = self._safe_query(query, "batch_extract")
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
        result = self._safe_query(query, "batch_extract")
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

        v1.5 (Jan 2026): Added total_games_available tracking for historical completeness.
        This enables bootstrap detection (player has fewer games than window size).

        v1.6 (Jan 23, 2026): BUGFIX - total_games_available now counts ALL historical games,
        not just games within the 60-day window. This fixes incorrect bootstrap detection
        for players with games older than 60 days. Uses CTE to separate the efficient
        last-10 retrieval (60-day window) from the total game count (no date limit).

        Performance: 300-450s → 30-60s (5-10x faster)
        """
        if not player_lookups:
            return

        # OPTIMIZATION: Add date range pruning to avoid full table scan
        # 60 days covers ~20+ games per player (more than enough for last 10)
        lookback_days = 60
        lookback_date = game_date - timedelta(days=lookback_days)

        # v1.6 FIX: Use CTE to get true total_games_available (no date limit)
        # while still using 60-day window for efficient last-10 retrieval.
        # This prevents incorrect bootstrap detection for players with older games.
        query = f"""
        WITH total_games_per_player AS (
            -- Count ALL historical games (no date limit) for accurate bootstrap detection
            SELECT
                player_lookup,
                COUNT(*) as total_games_available
            FROM `{self.project_id}.nba_analytics.player_game_summary`
            WHERE game_date < '{game_date}'
            GROUP BY player_lookup
        ),
        last_10_games AS (
            -- Use 60-day window for efficient retrieval of recent games
            SELECT
                player_lookup,
                game_date,
                points,
                minutes_played,
                ft_makes,
                fg_attempts,
                paint_attempts,
                mid_range_attempts,
                three_pt_attempts,
                ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) as rn
            FROM `{self.project_id}.nba_analytics.player_game_summary`
            WHERE game_date < '{game_date}'
              AND game_date >= '{lookback_date}'
        )
        SELECT
            l.player_lookup,
            l.game_date,
            l.points,
            l.minutes_played,
            l.ft_makes,
            l.fg_attempts,
            l.paint_attempts,
            l.mid_range_attempts,
            l.three_pt_attempts,
            t.total_games_available
        FROM last_10_games l
        JOIN total_games_per_player t ON l.player_lookup = t.player_lookup
        WHERE l.rn <= 10
        ORDER BY l.player_lookup, l.game_date DESC
        """
        result = self._safe_query(query, "batch_extract")

        # Group by player using efficient groupby
        if not result.empty:
            for player_lookup, group_df in result.groupby('player_lookup'):
                games = group_df.to_dict('records')
                self._last_10_games_lookup[player_lookup] = games
                # Store total games available (same value for all rows of same player)
                if games:
                    self._total_games_available_lookup[player_lookup] = int(games[0].get('total_games_available', len(games)))

        logger.debug(f"Batch last_10_games: {len(self._last_10_games_lookup)} players (60-day window, full history for totals)")

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
        result = self._safe_query(query, "batch_extract")

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
        result = self._safe_query(query, "batch_extract")

        # Group by team using efficient groupby
        if not result.empty:
            for team_abbr, group_df in result.groupby('team_abbr'):
                self._team_games_lookup[team_abbr] = group_df.to_dict('records')

        logger.debug(f"Batch team_games: {len(self._team_games_lookup)} teams (season {season_year})")

    # ========================================================================
    # V8 MODEL FEATURE EXTRACTION (Jan 2026)
    # ========================================================================

    def _batch_extract_vegas_lines(self, game_date: date, player_lookups: List[str]) -> None:
        """
        Batch extract Vegas betting lines for all players.

        Features extracted:
        - vegas_points_line: Current consensus points line
        - vegas_opening_line: Opening line
        - vegas_line_move: Line movement (current - opening)
        - has_vegas_line: Boolean flag

        Source: bettingpros_player_points_props (Phase 2 raw data)
        """
        if not player_lookups:
            return

        query = f"""
        SELECT
            player_lookup,
            AVG(points_line) as vegas_points_line,
            AVG(opening_line) as vegas_opening_line,
            1.0 as has_vegas_line
        FROM `{self.project_id}.nba_raw.bettingpros_player_points_props`
        WHERE game_date = '{game_date}'
          AND bet_side = 'over'
          AND points_line IS NOT NULL
          AND is_active = TRUE
        GROUP BY player_lookup
        """
        result = self._safe_query(query, "batch_extract")

        if not result.empty:
            for record in result.to_dict('records'):
                # Calculate line move
                record['vegas_line_move'] = (
                    (record['vegas_points_line'] or 0) -
                    (record['vegas_opening_line'] or record['vegas_points_line'] or 0)
                )
                self._vegas_lines_lookup[record['player_lookup']] = record

        logger.debug(f"Batch vegas_lines: {len(self._vegas_lines_lookup)} players")

    def _batch_extract_opponent_history(self, game_date: date, players_with_games: List[Dict]) -> None:
        """
        Batch extract player performance vs specific opponent.

        Features extracted:
        - avg_points_vs_opponent: Average points scored vs this opponent (last 3 years)
        - games_vs_opponent: Number of games played vs this opponent

        Source: player_game_summary (Phase 3)
        """
        if not players_with_games:
            return

        # Build player/opponent pairs
        pairs = [
            (p['player_lookup'], p.get('opponent_team_abbr'))
            for p in players_with_games
            if p.get('opponent_team_abbr')
        ]
        if not pairs:
            return

        # Use UNNEST for efficient batch query
        pairs_json = ', '.join([
            f"STRUCT('{p}' AS player_lookup, '{o}' AS opponent)"
            for p, o in pairs
        ])

        query = f"""
        WITH pairs AS (
            SELECT * FROM UNNEST([{pairs_json}])
        )
        SELECT
            p.player_lookup,
            p.opponent,
            COUNT(g.game_date) as games_vs_opponent,
            AVG(g.points) as avg_points_vs_opponent
        FROM pairs p
        LEFT JOIN `{self.project_id}.nba_analytics.player_game_summary` g
            ON p.player_lookup = g.player_lookup
            AND g.opponent_team_abbr = p.opponent
            AND g.game_date < '{game_date}'
            AND g.game_date >= DATE_SUB('{game_date}', INTERVAL 3 YEAR)
        GROUP BY p.player_lookup, p.opponent
        """
        result = self._safe_query(query, "batch_extract")

        if not result.empty:
            for record in result.to_dict('records'):
                key = f"{record['player_lookup']}_{record['opponent']}"
                self._opponent_history_lookup[key] = record

        logger.debug(f"Batch opponent_history: {len(self._opponent_history_lookup)} player-opponent pairs")

    def _batch_extract_minutes_ppm(self, game_date: date, player_lookups: List[str]) -> None:
        """
        Batch extract minutes and points-per-minute for all players.

        Features extracted:
        - minutes_avg_last_10: Average minutes played (last ~10 games / 30 days)
        - ppm_avg_last_10: Points per minute (last ~10 games / 30 days)

        Source: player_game_summary (Phase 3)
        Note: Uses 30-day window as approximation for last 10 games

        These features have HIGH importance in V8 model:
        - ppm_avg_last_10: 14.6% importance (captures efficiency trends)
        - minutes_avg_last_10: 10.9% importance (captures coach rotation decisions)
        """
        if not player_lookups:
            return

        query = f"""
        SELECT
            player_lookup,
            AVG(minutes_played) as minutes_avg_last_10,
            AVG(SAFE_DIVIDE(points, NULLIF(minutes_played, 0))) as ppm_avg_last_10
        FROM `{self.project_id}.nba_analytics.player_game_summary`
        WHERE game_date < '{game_date}'
          AND game_date >= DATE_SUB('{game_date}', INTERVAL 30 DAY)
          AND minutes_played > 0
        GROUP BY player_lookup
        """
        result = self._safe_query(query, "batch_extract")

        if not result.empty:
            for record in result.to_dict('records'):
                self._minutes_ppm_lookup[record['player_lookup']] = record

        logger.debug(f"Batch minutes_ppm: {len(self._minutes_ppm_lookup)} players")

    def get_vegas_lines(self, player_lookup: str) -> Dict:
        """Get cached Vegas lines for a player."""
        return self._vegas_lines_lookup.get(player_lookup, {})

    def get_opponent_history(self, player_lookup: str, opponent: str) -> Dict:
        """Get cached opponent history for a player-opponent pair."""
        key = f"{player_lookup}_{opponent}"
        return self._opponent_history_lookup.get(key, {})

    def get_minutes_ppm(self, player_lookup: str) -> Dict:
        """Get cached minutes/PPM data for a player."""
        return self._minutes_ppm_lookup.get(player_lookup, {})

    # ========================================================================
    # HISTORICAL COMPLETENESS TRACKING (Data Cascade Architecture - Jan 2026)
    # ========================================================================

    def get_historical_completeness_data(self, player_lookup: str) -> Dict[str, Any]:
        """
        Get historical completeness data for a player.

        Used to build the historical_completeness STRUCT for the feature record.
        Tracks whether rolling window calculations had all required data.

        Args:
            player_lookup: Player identifier

        Returns:
            Dict with:
                - games_found: Number of games actually retrieved
                - games_available: Total games available in lookback window
                - contributing_game_dates: List of date objects for cascade detection
        """
        last_10_games = self._last_10_games_lookup.get(player_lookup, [])
        games_found = len(last_10_games)

        # Get total games available (for bootstrap detection)
        # If not in lookup, use games_found as fallback
        games_available = self._total_games_available_lookup.get(player_lookup, games_found)

        # Extract contributing game dates for cascade detection
        contributing_game_dates = []
        for game in last_10_games:
            game_date = game.get('game_date')
            if game_date is not None:
                # Handle both date objects and strings
                if isinstance(game_date, str):
                    from datetime import datetime
                    try:
                        game_date = datetime.strptime(game_date, '%Y-%m-%d').date()
                    except ValueError:
                        continue
                contributing_game_dates.append(game_date)

        return {
            'games_found': games_found,
            'games_available': games_available,
            'contributing_game_dates': contributing_game_dates
        }

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
        
        result: pd.DataFrame = self._safe_query(query, "feature_extract")
        
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
        
        result: pd.DataFrame = self._safe_query(query, "feature_extract")
        
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
        
        result: pd.DataFrame = self._safe_query(query, "feature_extract")
        
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
        
        result: pd.DataFrame = self._safe_query(query, "feature_extract")
        
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
        
        result: pd.DataFrame = self._safe_query(query, "feature_extract")
        
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
        
        result: pd.DataFrame = self._safe_query(query, "feature_extract")
        
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
        
        result: pd.DataFrame = self._safe_query(query, "feature_extract")
        
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
        
        result: pd.DataFrame = self._safe_query(query, "feature_extract")
        
        if result.empty:
            logger.debug(f"No team games for {team_abbr} in {season_year}")
            return []
        
        games: List[Dict[str, Any]] = result.to_dict('records')
        logger.debug(f"Retrieved {len(games)} team games for {team_abbr}")
        return games