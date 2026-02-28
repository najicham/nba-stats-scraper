# File: data_processors/precompute/ml_feature_store/feature_extractor.py
"""
Feature Extractor - Query Phase 3/4 Tables

Extracts raw data from:
- Phase 4 (preferred): player_daily_cache, player_composite_factors,
                       player_shot_zone_analysis, team_defense_zone_analysis
- Phase 3 (fallback): player_game_summary, upcoming_player_game_context,
                      team_offense_game_summary, team_defense_game_summary

Version: 1.8 (Session 143: Per-query timing, date-bounded CTEs, query timeouts)
"""

import logging
import statistics
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

        # Cache miss tracking (Session 146)
        self._cache_miss_players: set = set()

        # V8 Model Features (added Jan 2026)
        self._vegas_lines_lookup: Dict[str, Dict] = {}
        self._opponent_history_lookup: Dict[str, Dict] = {}
        self._minutes_ppm_lookup: Dict[str, Dict] = {}

        # Historical Completeness Tracking (Data Cascade Architecture - Jan 2026)
        # Tracks total games available per player for bootstrap detection
        self._total_games_available_lookup: Dict[str, int] = {}

        # V12 Feature Store Extension: rolling stats for scoring trends/usage
        self._player_rolling_stats_lookup: Dict[str, Dict] = {}

        # Feature 47: teammate_usage_available — freed usage from injured teammates
        self._teammate_usage_lookup: Dict[str, float] = {}

        # Feature 50: multi_book_line_std — line disagreement across sportsbooks
        self._multi_book_std_lookup: Dict[str, float] = {}

        # Feature 54: prop_line_delta — line change from previous game (Session 294)
        self._prop_line_delta_lookup: Dict[str, float] = {}

        # Features 55-56: V16 prop line history (Session 356)
        self._v16_line_history_lookup: Dict[str, Dict] = {}

        # Features 57-59: V17 opportunity risk (Session 360)
        self._v17_opportunity_risk_lookup: Dict[str, Dict] = {}

        # Data Provenance Tracking (Session 99 - Feb 2026)
        # Track which sources were used and why fallbacks occurred
        self._fallback_reasons: List[str] = []
        self._matchup_data_available: bool = True  # False if composite factors missing for exact date
        self._composite_factors_source: str = 'none'  # 'exact_date', 'fallback', 'none'

    def _safe_query(self, query: str, query_name: str = "query",
                     timeout: int = 120) -> pd.DataFrame:
        """
        Execute BigQuery query with error handling and timeout.

        Args:
            query: SQL query to execute
            query_name: Descriptive name for logging
            timeout: Maximum seconds to wait for query results (default 120s)

        Returns:
            DataFrame with results, or empty DataFrame on error

        Raises:
            GoogleAPIError: Re-raises after logging if query fails
        """
        from google.api_core.exceptions import GoogleAPIError
        try:
            job = self.bq_client.query(query)
            return job.result(timeout=timeout).to_dataframe()
        except GoogleAPIError as e:
            logger.error(f"BigQuery query failed [{query_name}]: {e}")
            logger.debug(f"Failed query:\n{query[:500]}...")
            raise
        except TimeoutError:
            logger.error(f"BigQuery query timed out after {timeout}s [{query_name}]")
            logger.debug(f"Timed out query:\n{query[:500]}...")
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
            #
            # NOTE: Using <= here is CORRECT because:
            # 1. LAG() gives us the PREVIOUS row's game_date (the game before target)
            # 2. days_since_last = target_date - previous_date (correct calculation)
            # 3. We need the target date in the CTE to calculate its LAG value
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
                pgs.team_abbr,  -- v3.5: Add team_abbr for team_win_pct calculation
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
            # Session 195: Apply coordinator filters to reduce wasted computation (63% → ~10%)
            # Only process players who could potentially receive predictions based on
            # minutes threshold, injury status, and production readiness.
            #
            # These filters MUST match coordinator's player_loader.py filters (lines 322-324):
            # 1. (avg_minutes >= 15 OR has_prop_line = TRUE) - skip bench players without lines
            # 2. (status NOT IN ('OUT', 'DOUBTFUL')) - skip injured players
            # 3. (is_production_ready = TRUE OR has_prop_line = TRUE) - skip incomplete data
            query = f"""
            SELECT
                player_lookup,
                universal_player_id,
                game_id,
                game_date,
                team_abbr,  -- v3.5: Add team_abbr for team_win_pct calculation
                opponent_team_abbr,
                home_game AS is_home,
                days_rest,
                COALESCE(has_prop_line, FALSE) AS has_prop_line,  -- v3.2: Track if player has betting line
                current_points_line  -- v3.2: Pass through for estimated lines
            FROM `{self.project_id}.nba_analytics.upcoming_player_game_context`
            WHERE game_date = '{game_date}'
              -- Session 195 optimization: Apply coordinator filters early (reduce ~80 → ~30 players)
              AND (COALESCE(avg_minutes_per_game_last_7, 0) >= 15 OR has_prop_line = TRUE)
              AND (player_status IS NULL OR player_status NOT IN ('OUT', 'DOUBTFUL'))
              AND (is_production_ready = TRUE OR has_prop_line = TRUE)
            ORDER BY player_lookup
            """
            logger.info(
                f"Querying coordinator-eligible players for {game_date} "
                f"(filters: minutes>=15 OR has_line, NOT out/doubtful, production_ready OR has_line)"
            )

        result: pd.DataFrame = self._safe_query(query, f"get_players_with_games({game_date})")

        if result.empty:
            logger.warning(f"No players found with games on {game_date}")
            return []

        logger.info(f"Found {len(result)} players with games on {game_date}" +
                   (" [BACKFILL MODE]" if backfill_mode else ""))

        # Session 195: Log filter effectiveness (coordinator-eligible vs total roster)
        if not use_backfill_query:
            # Query total roster for comparison (only in real-time mode)
            try:
                total_query = f"""
                SELECT COUNT(*) as total_players
                FROM `{self.project_id}.nba_analytics.upcoming_player_game_context`
                WHERE game_date = '{game_date}'
                """
                total_result = self._safe_query(total_query, f"get_total_players({game_date})")
                if not total_result.empty:
                    total_players = int(total_result.iloc[0]['total_players'])
                    filtered_count = total_players - len(result)
                    if filtered_count > 0:
                        logger.info(
                            f"📊 Phase 4 optimization: Filtered {filtered_count}/{total_players} players "
                            f"({100*filtered_count/total_players:.0f}% reduction) - "
                            f"processing {len(result)} coordinator-eligible players"
                        )
            except Exception as e:
                logger.debug(f"Could not query total roster count: {e}")

        return result.to_dict('records')

    # ========================================================================
    # BATCH EXTRACTION (20x SPEEDUP FOR BACKFILL)
    # ========================================================================

    def batch_extract_all_data(self, game_date: date, players_with_games: List[Dict[str, Any]],
                               backfill_mode: bool = False) -> None:
        """
        Batch extract all Phase 3/4 data for a game date.

        Call this ONCE at the start of processing a day. Subsequent calls to
        extract_phase4_data() and extract_phase3_data() will use cached data.

        Performance: 8 queries run in PARALLEL using ThreadPoolExecutor
        v1.4: Now runs all batch extractions concurrently for ~3x speedup
        v1.7 (Session 62): Added backfill_mode parameter for Vegas line extraction
            from raw betting tables instead of Phase 3 (fixes 43% → 95%+ coverage)

        Args:
            game_date: Date to extract data for
            players_with_games: List of player dicts (from get_players_with_games)
            backfill_mode: If True, use raw betting tables for Vegas lines instead of Phase 3
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

        # Per-query timing tracker (Session 143)
        query_timings = {}

        def timed_task(name, fn):
            """Wrapper that times each extraction task."""
            def wrapper():
                t0 = time.time()
                fn()
                elapsed = time.time() - t0
                query_timings[name] = elapsed
                logger.info(f"[QUERY_TIMING] {name}: {elapsed:.1f}s")
            return wrapper

        # Run ALL 11 batch extractions in PARALLEL using ThreadPoolExecutor
        # Each query is independent and can run concurrently
        # V8 Model: Added vegas_lines, opponent_history, minutes_ppm (Jan 2026)
        # v1.7 (Session 62): Pass backfill_mode to vegas_lines for raw table joins
        extraction_tasks = [
            ('daily_cache', timed_task('daily_cache', lambda: self._batch_extract_daily_cache(game_date))),
            ('composite_factors', timed_task('composite_factors', lambda: self._batch_extract_composite_factors(game_date))),
            ('shot_zone', timed_task('shot_zone', lambda: self._batch_extract_shot_zone(game_date))),
            ('team_defense', timed_task('team_defense', lambda: self._batch_extract_team_defense(game_date, all_opponents))),
            ('player_context', timed_task('player_context', lambda: self._batch_extract_player_context(game_date))),
            ('last_10_games', timed_task('last_10_games', lambda: self._batch_extract_last_10_games(game_date, all_players))),
            ('season_stats', timed_task('season_stats', lambda: self._batch_extract_season_stats(game_date, all_players))),
            ('team_games', timed_task('team_games', lambda: self._batch_extract_team_games(game_date, all_teams))),
            # V8 Model Features (Jan 2026)
            # v1.7: backfill_mode joins raw betting tables for higher coverage
            ('vegas_lines', timed_task('vegas_lines', lambda: self._batch_extract_vegas_lines(game_date, all_players, backfill_mode))),
            ('opponent_history', timed_task('opponent_history', lambda: self._batch_extract_opponent_history(game_date, players_with_games))),
            ('minutes_ppm', timed_task('minutes_ppm', lambda: self._batch_extract_minutes_ppm(game_date, all_players))),
            # V12 Feature Store Extension
            ('rolling_stats', timed_task('rolling_stats', lambda: self._batch_extract_player_rolling_stats(game_date))),
            # Feature 47: teammate_usage_available
            ('teammate_usage', timed_task('teammate_usage', lambda: self._batch_extract_teammate_usage(game_date))),
            # Feature 50: multi_book_line_std
            ('multi_book_std', timed_task('multi_book_std', lambda: self._batch_extract_multi_book_line_std(game_date))),
            # Feature 54: prop_line_delta (Session 294)
            ('prop_line_delta', timed_task('prop_line_delta', lambda: self._batch_extract_prop_line_delta(game_date))),
            # Features 55-56: V16 prop line history (Session 356)
            ('v16_line_history', timed_task('v16_line_history', lambda: self._batch_extract_v16_line_history(game_date))),
            # Features 57-59: V17 opportunity risk (Session 360)
            ('v17_opportunity_risk', timed_task('v17_opportunity_risk', lambda: self._batch_extract_v17_opportunity_risk(game_date))),
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

                with ThreadPoolExecutor(max_workers=12) as executor:
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

        # Log per-query timing breakdown (Session 143)
        if query_timings:
            sorted_timings = sorted(query_timings.items(), key=lambda x: x[1], reverse=True)
            timing_str = ", ".join(f"{name}={t:.1f}s" for name, t in sorted_timings)
            logger.info(f"[QUERY_TIMING_BREAKDOWN] {timing_str}")
            slowest_name, slowest_time = sorted_timings[0]
            if slowest_time > 30:
                logger.warning(f"[SLOW_QUERY] {slowest_name} took {slowest_time:.1f}s (>{30}s threshold)")

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
        # V12 rolling stats
        self._player_rolling_stats_lookup = {}
        # Feature 47/50/54/55-56/57-59
        self._teammate_usage_lookup = {}
        self._multi_book_std_lookup = {}
        self._prop_line_delta_lookup = {}
        self._v16_line_history_lookup = {}
        self._v17_opportunity_risk_lookup = {}
        # Historical Completeness Tracking
        self._total_games_available_lookup = {}

    def _batch_extract_daily_cache(self, game_date: date) -> None:
        """
        Batch extract player_daily_cache for all players.

        Session 290 Fix: Exact-date-only query. No fallback window.
        If a player doesn't have cache data for this exact date, they won't be
        in the lookup. The per-player extraction chain handles the gap:
        extract_phase4_data → _compute_cache_fields_from_games (from last 10 games)
        → default (source='default', blocked by zero tolerance).

        Previous bug: All-or-nothing fallback masked missing data as source='phase4',
        bypassing quality scoring. Exact-date-only ensures proper source tracking.
        """
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
        result = self._safe_query(query, "batch_extract_daily_cache")

        # Use efficient to_dict instead of iterrows (3x faster)
        if not result.empty:
            for record in result.to_dict('records'):
                self._daily_cache_lookup[record['player_lookup']] = record
        logger.debug(f"Batch daily_cache: {len(self._daily_cache_lookup)} rows")

    def _batch_extract_composite_factors(self, game_date: date) -> None:
        """
        Batch extract player_composite_factors for all players.

        Session 291 Fix: Exact-date-only query. No fallback window.
        If a player doesn't have composite factors for this exact date, they won't
        be in the lookup → feature stays NULL → quality scorer catches it.

        Previous bug: All-or-nothing fallback masked missing data as source='phase4',
        bypassing quality scoring. Exact-date-only ensures proper source tracking.
        Matchup-specific factors (pace_score, shot_zone_mismatch) are opponent-dependent
        and MUST NOT use wrong-opponent data anyway.
        """
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
        result = self._safe_query(query, "batch_extract_composite_factors")

        if not result.empty:
            self._composite_factors_source = 'exact_date'
            self._matchup_data_available = True
            for record in result.to_dict('records'):
                self._composite_factors_lookup[record['player_lookup']] = record
        else:
            self._composite_factors_source = 'none'
            self._matchup_data_available = False

        logger.debug(f"Batch composite_factors: {len(self._composite_factors_lookup)} rows")

    def _batch_extract_shot_zone(self, game_date: date) -> None:
        """
        Batch extract player_shot_zone_analysis for all players.

        Session 290 Fix: Exact-date-only query. No fallback window.
        If a player doesn't have shot zone data for this exact date, they won't
        be in the lookup → feature stays NULL → quality scorer catches it.

        Previous bug: All-or-nothing fallback masked missing data as source='phase4',
        bypassing quality scoring. Exact-date-only ensures proper source tracking.
        """
        query = f"""
        SELECT
            player_lookup,
            paint_rate_last_10,
            mid_range_rate_last_10,
            three_pt_rate_last_10
        FROM `{self.project_id}.nba_precompute.player_shot_zone_analysis`
        WHERE analysis_date = '{game_date}'
        """
        result = self._safe_query(query, "batch_extract_shot_zone")

        # Use efficient to_dict instead of iterrows (3x faster)
        if not result.empty:
            for record in result.to_dict('records'):
                self._shot_zone_lookup[record['player_lookup']] = record
        logger.debug(f"Batch shot_zone: {len(self._shot_zone_lookup)} rows")

    def _batch_extract_team_defense(self, game_date: date, team_abbrs: List[str]) -> None:
        """
        Batch extract team_defense_zone_analysis for all opponent teams.

        Session 290 Fix: Exact-date-only query. No fallback window.
        If a team doesn't have defense data for this exact date, they won't
        be in the lookup → feature stays NULL → quality scorer catches it.

        Previous bug: All-or-nothing fallback masked missing data as source='phase4',
        bypassing quality scoring. Exact-date-only ensures proper source tracking.
        """
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
        result = self._safe_query(query, "batch_extract_team_defense")

        # Use efficient to_dict instead of iterrows (3x faster)
        if not result.empty:
            for record in result.to_dict('records'):
                self._team_defense_lookup[record['team_abbr']] = record
        logger.debug(f"Batch team_defense: {len(self._team_defense_lookup)} rows")

    def _batch_extract_player_context(self, game_date: date) -> None:
        """Batch extract upcoming_player_game_context for all players.

        V12 Extension: Also fetches minutes_in_last_7_days, game_spread,
        prop_over_streak, prop_under_streak for V12 features 39-53.
        """
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
            opponent_days_rest,
            games_in_last_7_days,
            star_teammates_out,
            game_total,
            minutes_in_last_7_days,
            game_spread,
            prop_over_streak,
            prop_under_streak
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

        # v1.6 FIX: Use CTE to get true total_games_available for bootstrap detection.
        # v1.7 FIX (Session 143): Add 365-day lower bound to avoid full table scan.
        # Bootstrap detection only needs to know if player has >= 10 games within a year.
        # Players with 10+ games in the last year are never bootstrap candidates.
        query = f"""
        WITH total_games_per_player AS (
            -- Count games within 1 year for bootstrap detection (Session 143: added date bound)
            -- 10 games in a year is more than enough to avoid bootstrap mode
            SELECT
                player_lookup,
                COUNT(*) as total_games_available
            FROM `{self.project_id}.nba_analytics.player_game_summary`
            WHERE game_date < '{game_date}'
              AND game_date >= DATE_SUB('{game_date}', INTERVAL 365 DAY)
            GROUP BY player_lookup
        ),
        last_10_games AS (
            -- Use 60-day window for efficient retrieval of recent games
            -- Session 156: Added usage_rate, assisted_fg_makes, fg_makes, team_abbr
            -- for complete cache miss fallback computation
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
                is_dnp,  -- v3.1: Added for dnp_rate feature calculation
                usage_rate,  -- Session 156: for player_usage_rate_season fallback
                assisted_fg_makes,  -- Session 156: for assisted_rate_last_10 fallback
                fg_makes,  -- Session 156: for assisted_rate_last_10 fallback
                team_abbr,  -- Session 156: for team lookups in fallback
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
            l.is_dnp,  -- v3.1: Added for dnp_rate feature calculation
            l.usage_rate,
            l.assisted_fg_makes,
            l.fg_makes,
            l.team_abbr,
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

    def _compute_cache_fields_from_games(self, player_lookup: str, game_date: date) -> Dict[str, Any]:
        """Compute daily_cache equivalent fields from last_10_games data (Session 144).

        When PlayerDailyCacheProcessor doesn't have an entry for a player (it only
        caches players with TODAY's games, not all season players), compute the
        same rolling stats from the already-extracted last_10_games data.

        Returns dict matching daily_cache schema fields, or empty dict if no data.
        """
        games = self._last_10_games_lookup.get(player_lookup, [])
        if not games:
            return {}

        # Filter out DNP games for stat calculations (same as cache processor)
        played_games = [g for g in games if not g.get('is_dnp', False) and g.get('minutes_played', 0) > 0]
        if not played_games:
            return {}

        # Last 5 and last 10 played games
        last_5 = played_games[:5]
        last_10 = played_games[:10]

        points_l5 = [g['points'] for g in last_5 if g.get('points') is not None]
        points_l10 = [g['points'] for g in last_10 if g.get('points') is not None]
        minutes_l10 = [g['minutes_played'] for g in last_10 if g.get('minutes_played') is not None]

        result = {}

        if points_l5:
            result['points_avg_last_5'] = sum(points_l5) / len(points_l5)
        if points_l10:
            result['points_avg_last_10'] = sum(points_l10) / len(points_l10)
            if len(points_l10) >= 2:
                result['points_std_last_10'] = statistics.stdev(points_l10)
            else:
                result['points_std_last_10'] = 0.0
        if minutes_l10:
            result['minutes_avg_last_10'] = sum(minutes_l10) / len(minutes_l10)

        # Helper to normalize game dates (handles Timestamp and date objects)
        def _normalize_date(gd):
            if gd is not None and hasattr(gd, 'date'):
                return gd.date()  # Convert pandas Timestamp to date
            return gd

        # Games in last 7 and 14 days (handle date/Timestamp types from BigQuery)
        seven_days_ago = game_date - timedelta(days=7)
        fourteen_days_ago = game_date - timedelta(days=14)
        games_in_7d = 0
        games_in_14d = 0
        minutes_in_7d = 0.0
        minutes_in_14d = 0.0
        for g in played_games:
            gd = _normalize_date(g.get('game_date'))
            if gd is not None:
                mins = float(g.get('minutes_played', 0) or 0)
                if gd >= seven_days_ago:
                    games_in_7d += 1
                    minutes_in_7d += mins
                if gd >= fourteen_days_ago:
                    games_in_14d += 1
                    minutes_in_14d += mins
        result['games_in_last_7_days'] = games_in_7d
        result['games_in_last_14_days'] = games_in_14d
        result['minutes_in_last_7_days'] = minutes_in_7d
        result['minutes_in_last_14_days'] = minutes_in_14d

        # Back-to-backs in last 14 days: count pairs of games on consecutive days
        recent_dates = sorted([
            _normalize_date(g.get('game_date'))
            for g in played_games
            if _normalize_date(g.get('game_date')) is not None
               and _normalize_date(g.get('game_date')) >= fourteen_days_ago
        ])
        b2b_count = 0
        for i in range(1, len(recent_dates)):
            if (recent_dates[i] - recent_dates[i - 1]).days == 1:
                b2b_count += 1
        result['back_to_backs_last_14_days'] = b2b_count

        # Assisted rate: sum(assisted_fg_makes) / sum(fg_makes) from last 10
        total_assisted = sum(g.get('assisted_fg_makes', 0) or 0 for g in last_10)
        total_fgm = sum(g.get('fg_makes', 0) or 0 for g in last_10)
        if total_fgm > 0:
            result['assisted_rate_last_10'] = total_assisted / total_fgm

        # PPM avg last 10: sum(points) / sum(minutes)
        total_pts = sum(g.get('points', 0) or 0 for g in last_10)
        total_mins = sum(g.get('minutes_played', 0) or 0 for g in last_10)
        if total_mins > 0:
            result['ppm_avg_last_10'] = total_pts / total_mins

        # Player usage rate season: avg(usage_rate) from season stats lookup or games
        season = self._season_stats_lookup.get(player_lookup, {})
        if season.get('points_avg_season') is not None:
            result['points_avg_season'] = season['points_avg_season']

        # Usage rate from games data (fallback for player_usage_rate_season)
        usage_rates = [g.get('usage_rate') for g in played_games if g.get('usage_rate') is not None]
        if usage_rates:
            result['player_usage_rate_season'] = sum(usage_rates) / len(usage_rates)

        # Shot zone percentages from game data (paint, mid, three, FT)
        total_paint = sum(g.get('paint_attempts', 0) or 0 for g in last_10)
        total_mid = sum(g.get('mid_range_attempts', 0) or 0 for g in last_10)
        total_three = sum(g.get('three_pt_attempts', 0) or 0 for g in last_10)
        total_fg = sum(g.get('fg_attempts', 0) or 0 for g in last_10)

        if total_fg > 0:
            result['paint_rate_last_10'] = total_paint / total_fg
            result['three_pt_rate_last_10'] = total_three / total_fg
            result['mid_range_rate_last_10'] = total_mid / total_fg

        # Team context: pace and offensive rating from team_games_lookup
        # Get player's team from player_context_lookup or last_10_games
        player_context = self._player_context_lookup.get(player_lookup, {})
        team_abbr = player_context.get('team_abbr')
        # Session 156: Also try team_abbr from the games data if context is missing
        if not team_abbr and played_games:
            team_abbr = played_games[0].get('team_abbr')
        if team_abbr:
            team_games = self._team_games_lookup.get(team_abbr, [])
            # Use last 10 team games (sorted by game_date ascending, take last 10)
            recent_team_games = team_games[-10:] if len(team_games) >= 10 else team_games
            if recent_team_games:
                pace_values = [g['pace'] for g in recent_team_games if g.get('pace') is not None]
                rating_values = [g['offensive_rating'] for g in recent_team_games if g.get('offensive_rating') is not None]
                if pace_values:
                    result['team_pace_last_10'] = sum(pace_values) / len(pace_values)
                if rating_values:
                    result['team_off_rating_last_10'] = sum(rating_values) / len(rating_values)

        return result

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
            win_flag,
            pace,
            offensive_rating
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

    def _batch_extract_vegas_lines(self, game_date: date, player_lookups: List[str],
                                     backfill_mode: bool = False) -> None:
        """
        Batch extract Vegas betting lines for all players.

        Features extracted:
        - vegas_points_line: Current points line from Phase 3 or raw tables
        - vegas_opening_line: Opening line from Phase 3 or raw tables
        - vegas_line_move: Line movement (pre-calculated in Phase 3, or 0 for backfill)
        - has_vegas_line: Boolean flag (1.0 = real line, 0.0 = no line)

        Source:
        - Production mode: upcoming_player_game_context (Phase 3 analytics)
        - Backfill mode (v1.7, Session 62): odds_api_player_points_props (raw tables)

        ARCHITECTURE NOTE (Session 59 fix):
        Previously queried bettingpros_player_points_props directly, which caused
        missing Vegas data when bettingpros scraper was down (Oct-Nov 2025).

        Now reads from Phase 3 which implements the correct cascade:
        1. odds_api_player_points_props (primary - DraftKings/FanDuel)
        2. bettingpros_player_points_props (fallback)

        This follows the Phase 3 → Phase 4 architecture pattern and ensures
        Vegas data is available as long as ANY source has it.

        BACKFILL MODE FIX (Session 62):
        In backfill mode, get_players_with_games() returns ALL players from
        player_game_summary (not just those with props). But Phase 3 only has
        Vegas lines for "expected" players, causing 43% coverage instead of 99%.

        Solution: For backfill mode, query raw betting tables directly to get
        Vegas lines for all players who have them, regardless of whether they
        were in the "expected" roster.
        """
        if not player_lookups:
            return

        # SESSION 76 FIX: Always use raw betting tables for Vegas lines
        # Root cause: Phase 3 (upcoming_player_game_context) only has lines for ~50% of players
        # (only those expected to play), while raw tables have 95%+ coverage.
        #
        # Previous behavior (Sessions 59-62):
        # - Production mode: Used Phase 3 → 42% coverage
        # - Backfill mode: Used raw tables → 95% coverage
        #
        # New behavior (Session 76+):
        # - ALL modes: Use raw betting tables → 95% coverage
        #
        # Cascade order:
        # 1. odds_api_player_points_props (primary - DraftKings)
        # 2. bettingpros_player_points_props (fallback, must filter market_type='points')
        query = f"""
        WITH odds_api_lines AS (
            -- Primary source: Odds API (DraftKings preferred)
            SELECT DISTINCT
                player_lookup,
                FIRST_VALUE(points_line) OVER (
                    PARTITION BY player_lookup
                    ORDER BY
                        CASE WHEN bookmaker = 'draftkings' THEN 0 ELSE 1 END,
                        snapshot_timestamp DESC
                ) as vegas_points_line,
                FIRST_VALUE(points_line) OVER (
                    PARTITION BY player_lookup
                    ORDER BY
                        CASE WHEN bookmaker = 'draftkings' THEN 0 ELSE 1 END,
                        snapshot_timestamp ASC
                ) as vegas_opening_line
            FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
            WHERE game_date = '{game_date}'
              AND points_line IS NOT NULL
              AND points_line > 0
        ),
        bettingpros_lines AS (
            -- Fallback source: BettingPros (only if Odds API doesn't have player)
            SELECT DISTINCT
                player_lookup,
                FIRST_VALUE(points_line) OVER (
                    PARTITION BY player_lookup
                    ORDER BY created_at DESC
                ) as vegas_points_line,
                FIRST_VALUE(opening_line) OVER (
                    PARTITION BY player_lookup
                    ORDER BY created_at DESC
                ) as vegas_opening_line
            FROM `{self.project_id}.nba_raw.bettingpros_player_points_props`
            WHERE game_date = '{game_date}'
              AND market_type = 'points'  -- CRITICAL: filter to points only!
              AND points_line IS NOT NULL
              AND points_line > 0
        ),
        combined AS (
            -- Use Odds API first, fall back to BettingPros
            -- Session 152: Track which source provided the line
            SELECT
                COALESCE(oa.player_lookup, bp.player_lookup) as player_lookup,
                COALESCE(oa.vegas_points_line, bp.vegas_points_line) as vegas_points_line,
                COALESCE(oa.vegas_opening_line, bp.vegas_opening_line, oa.vegas_points_line, bp.vegas_points_line) as vegas_opening_line,
                CASE
                    WHEN oa.player_lookup IS NOT NULL AND bp.player_lookup IS NOT NULL THEN 'both'
                    WHEN oa.player_lookup IS NOT NULL THEN 'odds_api'
                    WHEN bp.player_lookup IS NOT NULL THEN 'bettingpros'
                END as vegas_line_source
            FROM odds_api_lines oa
            FULL OUTER JOIN bettingpros_lines bp USING (player_lookup)
        )
        SELECT
            player_lookup,
            vegas_points_line,
            vegas_opening_line,
            vegas_points_line - vegas_opening_line as vegas_line_move,
            1.0 as has_vegas_line,
            vegas_line_source
        FROM combined
        WHERE vegas_points_line IS NOT NULL
        """
        logger.info(f"Extracting Vegas lines from raw betting tables for {game_date} (Session 76 fix: always use raw tables)")

        result = self._safe_query(query, "batch_extract_vegas_lines")

        if not result.empty:
            for record in result.to_dict('records'):
                # Convert Decimal types to float for consistency
                record['vegas_points_line'] = float(record['vegas_points_line']) if record['vegas_points_line'] else 0.0
                record['vegas_opening_line'] = float(record['vegas_opening_line']) if record['vegas_opening_line'] else record['vegas_points_line']
                record['vegas_line_move'] = float(record['vegas_line_move']) if record['vegas_line_move'] else 0.0
                record['has_vegas_line'] = float(record['has_vegas_line'])
                self._vegas_lines_lookup[record['player_lookup']] = record

        logger.debug(f"Batch vegas_lines: {len(self._vegas_lines_lookup)} players (from raw betting tables)")

    def _batch_extract_opponent_history(self, game_date: date, players_with_games: List[Dict]) -> None:
        """
        Batch extract player performance vs specific opponent.

        Features extracted:
        - avg_points_vs_opponent: Average points scored vs this opponent (last 1 year)
        - games_vs_opponent: Number of games played vs this opponent

        Source: player_game_summary (Phase 3)

        v1.8 (Session 143): Reduced lookback from 3 years to 1 year for performance.
        NBA rosters change significantly year-over-year, so recent matchups are more
        relevant anyway. This reduces BigQuery scan volume significantly.
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
            AND g.game_date >= DATE_SUB('{game_date}', INTERVAL 1 YEAR)
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

    def get_star_teammates_out(self, player_lookup: str) -> Optional[float]:
        """Get star_teammates_out count from player context cache."""
        context = self._player_context_lookup.get(player_lookup, {})
        return context.get('star_teammates_out')

    def get_game_total(self, player_lookup: str) -> Optional[float]:
        """Get game total line from player context cache."""
        context = self._player_context_lookup.get(player_lookup, {})
        return context.get('game_total')

    def get_days_rest_float(self, player_lookup: str) -> Optional[float]:
        """Get days_rest as float from player context cache."""
        context = self._player_context_lookup.get(player_lookup, {})
        val = context.get('days_rest')
        return float(val) if val is not None else None

    def get_minutes_load_last_7d(self, player_lookup: str) -> Optional[float]:
        """Get minutes_in_last_7_days from player context cache."""
        context = self._player_context_lookup.get(player_lookup, {})
        val = context.get('minutes_in_last_7_days')
        return float(val) if val is not None else None

    def get_game_spread(self, player_lookup: str) -> Optional[float]:
        """Get game_spread from player context cache."""
        context = self._player_context_lookup.get(player_lookup, {})
        val = context.get('game_spread')
        return float(val) if val is not None else None

    def get_prop_streaks(self, player_lookup: str) -> Dict:
        """Get prop_over_streak and prop_under_streak from player context cache."""
        context = self._player_context_lookup.get(player_lookup, {})
        return {
            'prop_over_streak': context.get('prop_over_streak'),
            'prop_under_streak': context.get('prop_under_streak'),
        }

    def get_player_rolling_stats(self, player_lookup: str) -> Dict:
        """Get cached V12 rolling stats for a player."""
        return self._player_rolling_stats_lookup.get(player_lookup, {})

    def get_teammate_usage_available(self, player_lookup: str) -> Optional[float]:
        """Get total freed usage from OUT/DOUBTFUL teammates (feature 47)."""
        return self._teammate_usage_lookup.get(player_lookup)

    def get_multi_book_line_std(self, player_lookup: str) -> Optional[float]:
        """Get std dev of player points prop line across sportsbooks (feature 50)."""
        return self._multi_book_std_lookup.get(player_lookup)

    def get_prop_line_delta(self, player_lookup: str) -> Optional[float]:
        """Get prop line delta from previous game (feature 54, Session 294)."""
        return self._prop_line_delta_lookup.get(player_lookup)

    def get_v16_line_history(self, player_lookup: str) -> Dict:
        """Get V16 prop line history features (features 55-56, Session 356).

        Returns dict with:
            over_rate_last_10: fraction of last 10 games where actual > prop_line
            margin_vs_line_avg_last_5: mean(actual - prop_line) over last 5 games
        """
        return self._v16_line_history_lookup.get(player_lookup, {})

    def get_v17_opportunity_risk(self, player_lookup: str) -> Dict:
        """Get V17 opportunity risk features (features 57-59, Session 360).

        Returns dict with:
            blowout_minutes_risk: fraction of team's L10 games with 15+ margin
            minutes_volatility_last_10: stdev of player minutes over L10
        Note: opponent_pace_mismatch is computed in the processor from existing features.
        """
        return self._v17_opportunity_risk_lookup.get(player_lookup, {})

    # ========================================================================
    # V12 ROLLING STATS EXTRACTION
    # ========================================================================

    def _batch_extract_player_rolling_stats(self, game_date: date) -> None:
        """
        Batch extract rolling stats for V12 features (scoring trends, usage, structural changes).

        Queries player_game_summary for the last 60 days and computes per-player:
        - points_avg_last_3: ultra-short scoring average
        - scoring_trend_slope: OLS slope over last 7 games
        - deviation_from_avg_last3: z-score of L3 avg vs 60-day avg
        - consecutive_games_below_avg: cold streak counter
        - usage_rate_last_5: recent usage rate average
        - games_since_structural_change: games since team trade or long gap

        Stores results in _player_rolling_stats_lookup dict.
        """
        import numpy as np

        lookback_date = game_date - timedelta(days=60)

        query = f"""
        SELECT
            player_lookup,
            game_date,
            points,
            usage_rate,
            team_abbr
        FROM `{self.project_id}.nba_analytics.player_game_summary`
        WHERE game_date >= '{lookback_date}'
          AND game_date < '{game_date}'
          AND points IS NOT NULL
          AND minutes_played > 0
        ORDER BY player_lookup, game_date
        """
        result = self._safe_query(query, "batch_extract_rolling_stats")

        if result.empty:
            logger.warning(f"No rolling stats data found for {game_date}")
            return

        for player_lookup, group_df in result.groupby('player_lookup'):
            games = group_df.to_dict('records')
            if not games:
                continue

            points_list = [float(g['points']) for g in games if g.get('points') is not None]
            if not points_list:
                continue

            # points_avg_last_3
            last_3 = points_list[-3:] if len(points_list) >= 3 else points_list
            points_avg_last_3 = sum(last_3) / len(last_3)

            # scoring_trend_slope: OLS on last 7, need at least 4
            recent_7 = points_list[-7:] if len(points_list) >= 4 else None
            if recent_7 is not None and len(recent_7) >= 4:
                n = len(recent_7)
                x = np.arange(1, n + 1, dtype=float)
                y = np.array(recent_7, dtype=float)
                sum_x = x.sum()
                sum_y = y.sum()
                sum_xy = (x * y).sum()
                sum_x2 = (x * x).sum()
                denom = n * sum_x2 - sum_x * sum_x
                scoring_trend_slope = float((n * sum_xy - sum_x * sum_y) / denom) if denom != 0 else 0.0
            else:
                scoring_trend_slope = 0.0

            # deviation_from_avg_last3: z-score
            season_avg = sum(points_list) / len(points_list)
            if len(points_list) >= 2:
                season_std = (sum((p - season_avg) ** 2 for p in points_list) / (len(points_list) - 1)) ** 0.5
            else:
                season_std = 5.0
            if season_std > 0:
                deviation_from_avg_last3 = (points_avg_last_3 - season_avg) / season_std
            else:
                deviation_from_avg_last3 = 0.0

            # consecutive_games_below_avg
            consecutive_below = 0
            for pts in reversed(points_list):
                if pts < season_avg:
                    consecutive_below += 1
                else:
                    break

            # usage_rate_last_5
            usage_rates = [float(g['usage_rate']) for g in games if g.get('usage_rate') is not None]
            if len(usage_rates) >= 3:
                usage_rate_last_5 = sum(usage_rates[-5:]) / len(usage_rates[-5:])
            else:
                usage_rate_last_5 = 20.0

            # games_since_structural_change: detect team change or 14+ day gap
            games_since_change = min(float(len(games)), 30.0)
            for i in range(len(games) - 1, 0, -1):
                curr_team = games[i].get('team_abbr')
                prev_team = games[i - 1].get('team_abbr')
                curr_date = games[i].get('game_date')
                prev_date = games[i - 1].get('game_date')

                # Team trade detection
                if curr_team != prev_team:
                    games_since_change = float(len(games) - 1 - i)
                    break

                # Long gap detection (14+ days = ASB or injury return)
                if curr_date is not None and prev_date is not None:
                    # Handle Timestamp vs date
                    if hasattr(curr_date, 'date'):
                        curr_date = curr_date.date()
                    if hasattr(prev_date, 'date'):
                        prev_date = prev_date.date()
                    try:
                        gap = (curr_date - prev_date).days
                        if gap > 14:
                            games_since_change = float(len(games) - 1 - i)
                            break
                    except (TypeError, AttributeError):
                        pass

            self._player_rolling_stats_lookup[player_lookup] = {
                'points_avg_last_3': points_avg_last_3,
                'scoring_trend_slope': scoring_trend_slope,
                'deviation_from_avg_last3': deviation_from_avg_last3,
                'consecutive_games_below_avg': float(consecutive_below),
                'usage_rate_last_5': usage_rate_last_5,
                'games_since_structural_change': games_since_change,
            }

        logger.debug(f"Batch rolling_stats: {len(self._player_rolling_stats_lookup)} players")

    # ========================================================================
    # FEATURE 47: TEAMMATE USAGE AVAILABLE (Session 287)
    # ========================================================================

    def _batch_extract_teammate_usage(self, game_date: date) -> None:
        """Batch extract freed usage from OUT/DOUBTFUL teammates (feature 47).

        For each team with injured players on game_date, sums the recent usage_rate
        of OUT/DOUBTFUL players. Each remaining player on that team gets this value,
        representing how much "freed" offensive opportunity is available.

        Sources:
        - nba_raw.nbac_injury_report: OUT/DOUBTFUL players for game_date
        - nba_analytics.player_game_summary: Recent usage_rate for injured players
        """
        query = f"""
        WITH injured_players AS (
            SELECT DISTINCT
                ir.player_lookup,
                ir.team
            FROM `{self.project_id}.nba_raw.nbac_injury_report` ir
            WHERE ir.report_date = '{game_date}'
              AND LOWER(ir.injury_status) IN ('out', 'doubtful')
              AND ir.player_lookup IS NOT NULL
        ),
        injured_usage AS (
            SELECT
                ip.player_lookup,
                ip.team,
                AVG(pgs.usage_rate) as avg_usage_rate
            FROM injured_players ip
            JOIN `{self.project_id}.nba_analytics.player_game_summary` pgs
                ON ip.player_lookup = pgs.player_lookup
            WHERE pgs.game_date >= DATE_SUB('{game_date}', INTERVAL 30 DAY)
              AND pgs.game_date < '{game_date}'
              AND pgs.usage_rate IS NOT NULL
              AND pgs.minutes_played > 10
            GROUP BY ip.player_lookup, ip.team
        ),
        team_freed_usage AS (
            SELECT
                team,
                SUM(avg_usage_rate) as total_freed_usage
            FROM injured_usage
            GROUP BY team
        )
        SELECT
            upcg.player_lookup,
            tfu.total_freed_usage
        FROM `{self.project_id}.nba_analytics.upcoming_player_game_context` upcg
        JOIN team_freed_usage tfu
            ON upcg.team_abbr = tfu.team
        WHERE upcg.game_date = '{game_date}'
          AND upcg.player_lookup NOT IN (
              SELECT player_lookup FROM injured_players
          )
        """
        result = self._safe_query(query, "batch_extract_teammate_usage")

        if not result.empty:
            for record in result.to_dict('records'):
                val = record.get('total_freed_usage')
                if val is not None:
                    self._teammate_usage_lookup[record['player_lookup']] = float(val)

        logger.debug(f"Batch teammate_usage: {len(self._teammate_usage_lookup)} players")

    # ========================================================================
    # FEATURE 50: MULTI-BOOK LINE STD (Session 287)
    # ========================================================================

    def _batch_extract_multi_book_line_std(self, game_date: date) -> None:
        """Batch extract std dev of player points prop lines across sportsbooks (feature 50).

        Computes STDDEV(points_line) grouped by player, requiring at least 2 distinct
        bookmakers. High std = books disagree on the line (potential edge signal).

        Source: nba_raw.odds_api_player_points_props
        """
        query = f"""
        WITH latest_per_book AS (
            SELECT
                player_lookup,
                bookmaker,
                points_line,
                ROW_NUMBER() OVER (
                    PARTITION BY player_lookup, bookmaker
                    ORDER BY snapshot_timestamp DESC
                ) as rn
            FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
            WHERE game_date = '{game_date}'
              AND points_line IS NOT NULL
              AND points_line > 0
        )
        SELECT
            player_lookup,
            STDDEV(points_line) as line_std,
            COUNT(DISTINCT bookmaker) as book_count
        FROM latest_per_book
        WHERE rn = 1
        GROUP BY player_lookup
        HAVING COUNT(DISTINCT bookmaker) >= 2
        """
        result = self._safe_query(query, "batch_extract_multi_book_line_std")

        if not result.empty:
            for record in result.to_dict('records'):
                val = record.get('line_std')
                if val is not None:
                    self._multi_book_std_lookup[record['player_lookup']] = float(val)

        logger.debug(f"Batch multi_book_std: {len(self._multi_book_std_lookup)} players")

    def _batch_extract_prop_line_delta(self, game_date: date) -> None:
        """Batch extract prop line delta from previous game (feature 54, Session 294).

        Computes the difference between today's consensus points line and the player's
        most recent previous game's consensus line. A negative delta (line dropped)
        indicates the market reacted to a bad game — OVER bets on these players hit
        at 79.0% (N=81). A positive delta (line jumped) after a big game creates
        poor OVER value (28.6% HR).

        Source: nba_raw.odds_api_player_points_props
        """
        query = f"""
        WITH daily_consensus AS (
            -- Get consensus (median) line per player per game date
            SELECT
                player_lookup,
                game_date,
                APPROX_QUANTILES(points_line, 2)[OFFSET(1)] as consensus_line
            FROM (
                SELECT
                    player_lookup,
                    game_date,
                    bookmaker,
                    points_line,
                    ROW_NUMBER() OVER (
                        PARTITION BY player_lookup, game_date, bookmaker
                        ORDER BY snapshot_timestamp DESC
                    ) as rn
                FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
                WHERE game_date >= DATE_SUB('{game_date}', INTERVAL 14 DAY)
                  AND game_date <= '{game_date}'
                  AND points_line IS NOT NULL
                  AND points_line > 0
            )
            WHERE rn = 1
            GROUP BY player_lookup, game_date
            HAVING COUNT(DISTINCT bookmaker) >= 1
        ),
        with_prev AS (
            SELECT
                player_lookup,
                game_date,
                consensus_line,
                LAG(consensus_line) OVER (
                    PARTITION BY player_lookup ORDER BY game_date
                ) as prev_consensus_line
            FROM daily_consensus
        )
        SELECT
            player_lookup,
            consensus_line - prev_consensus_line as line_delta
        FROM with_prev
        WHERE game_date = '{game_date}'
          AND prev_consensus_line IS NOT NULL
        """
        result = self._safe_query(query, "batch_extract_prop_line_delta")

        if not result.empty:
            for record in result.to_dict('records'):
                val = record.get('line_delta')
                if val is not None:
                    self._prop_line_delta_lookup[record['player_lookup']] = round(float(val), 1)

        logger.debug(f"Batch prop_line_delta: {len(self._prop_line_delta_lookup)} players")

    def _batch_extract_v16_line_history(self, game_date: date) -> None:
        """Batch extract V16 prop line history features (features 55-56, Session 356).

        Computes per-player rolling stats from actual points vs prop line:
        - over_rate_last_10: fraction of last 10 games where actual > prop_line
        - margin_vs_line_avg_last_5: mean(actual - prop_line) over last 5 games

        Source: player_game_summary (actual points) + prediction_accuracy (graded prop lines)
        No leakage: only uses games strictly BEFORE game_date.
        """
        query = f"""
        WITH player_line_history AS (
            SELECT
                pgs.player_lookup,
                pgs.game_date,
                pgs.points AS actual_points,
                pa.line_value AS prop_line,
                ROW_NUMBER() OVER (
                    PARTITION BY pgs.player_lookup
                    ORDER BY pgs.game_date DESC
                ) AS games_ago
            FROM `{self.project_id}.nba_analytics.player_game_summary` pgs
            INNER JOIN `{self.project_id}.nba_predictions.prediction_accuracy` pa
                ON pa.player_lookup = pgs.player_lookup
                AND pa.game_date = pgs.game_date
            WHERE pa.line_value > 0
                AND pgs.points IS NOT NULL
                AND pgs.game_date < '{game_date}'
                AND pgs.game_date >= DATE_SUB('{game_date}', INTERVAL 60 DAY)
        )
        SELECT
            player_lookup,
            -- over_rate_last_10: fraction of last 10 where actual > line
            SAFE_DIVIDE(
                COUNTIF(actual_points > prop_line AND games_ago <= 10),
                COUNTIF(games_ago <= 10)
            ) AS over_rate_last_10,
            -- margin_vs_line_avg_last_5: mean(actual - line) over last 5
            AVG(CASE WHEN games_ago <= 5 THEN actual_points - prop_line END) AS margin_vs_line_avg_last_5,
            -- Track coverage for logging
            COUNTIF(games_ago <= 10) AS games_with_line_last_10,
            COUNTIF(games_ago <= 5) AS games_with_line_last_5
        FROM player_line_history
        WHERE games_ago <= 10
        GROUP BY player_lookup
        """
        result = self._safe_query(query, "batch_extract_v16_line_history")

        over_rate_count = 0
        margin_count = 0

        if not result.empty:
            for record in result.to_dict('records'):
                player = record['player_lookup']
                entry = {}
                # over_rate_last_10: need at least 10 games for full window
                # But allow partial (5+ games) for broader coverage
                or_val = record.get('over_rate_last_10')
                games_10 = record.get('games_with_line_last_10', 0)
                if or_val is not None and games_10 >= 5:
                    entry['over_rate_last_10'] = round(float(or_val), 9)
                    over_rate_count += 1

                # margin_vs_line_avg_last_5: need at least 3 games
                ma_val = record.get('margin_vs_line_avg_last_5')
                games_5 = record.get('games_with_line_last_5', 0)
                if ma_val is not None and games_5 >= 3:
                    entry['margin_vs_line_avg_last_5'] = round(float(ma_val), 9)
                    margin_count += 1

                if entry:
                    self._v16_line_history_lookup[player] = entry

        logger.info(
            f"Batch V16 line history: {len(self._v16_line_history_lookup)} players "
            f"(over_rate={over_rate_count}, margin={margin_count})"
        )

    def _batch_extract_v17_opportunity_risk(self, game_date: date) -> None:
        """Batch extract V17 opportunity risk features (features 57-58, Session 360).

        Computes per-player:
        - blowout_minutes_risk: fraction of team's L10 games with margin >= 15
        - minutes_volatility_last_10: stdev of player minutes over L10 games

        Note: opponent_pace_mismatch (feature 59) is computed in the processor
        from existing features 22 (team_pace) and 14 (opponent_pace).

        Source: team_offense_game_summary (margins), player_game_summary (minutes)
        No leakage: only uses games strictly BEFORE game_date.
        """
        query = f"""
        WITH team_margins AS (
            -- Team blowout rate: fraction of L10 games with margin >= 15
            SELECT
                team_abbr,
                SAFE_DIVIDE(
                    COUNTIF(ABS(margin_of_victory) >= 15),
                    COUNT(*)
                ) AS blowout_minutes_risk
            FROM (
                SELECT
                    team_abbr,
                    margin_of_victory,
                    ROW_NUMBER() OVER (
                        PARTITION BY team_abbr ORDER BY game_date DESC
                    ) AS rn
                FROM `{self.project_id}.nba_analytics.team_offense_game_summary`
                WHERE game_date < '{game_date}'
                  AND game_date >= DATE_SUB('{game_date}', INTERVAL 60 DAY)
            )
            WHERE rn <= 10
            GROUP BY team_abbr
        ),
        player_minutes_vol AS (
            -- Player minutes volatility: stdev of minutes in L10 games
            SELECT
                player_lookup,
                team_abbr,
                STDDEV_SAMP(minutes_played) AS minutes_volatility_last_10
            FROM (
                SELECT
                    player_lookup,
                    team_abbr,
                    minutes_played,
                    ROW_NUMBER() OVER (
                        PARTITION BY player_lookup ORDER BY game_date DESC
                    ) AS rn
                FROM `{self.project_id}.nba_analytics.player_game_summary`
                WHERE game_date < '{game_date}'
                  AND game_date >= DATE_SUB('{game_date}', INTERVAL 60 DAY)
                  AND minutes_played > 0
            )
            WHERE rn <= 10
            GROUP BY player_lookup, team_abbr
            HAVING COUNT(*) >= 3  -- Need at least 3 games for stdev
        )
        SELECT
            pmv.player_lookup,
            COALESCE(tm.blowout_minutes_risk, 0.2) AS blowout_minutes_risk,
            pmv.minutes_volatility_last_10
        FROM player_minutes_vol pmv
        LEFT JOIN team_margins tm ON pmv.team_abbr = tm.team_abbr
        """
        result = self._safe_query(query, "batch_extract_v17_opportunity_risk")

        blowout_count = 0
        vol_count = 0

        if not result.empty:
            for record in result.to_dict('records'):
                player = record['player_lookup']
                entry = {}

                br_val = record.get('blowout_minutes_risk')
                if br_val is not None:
                    entry['blowout_minutes_risk'] = round(float(br_val), 4)
                    blowout_count += 1

                mv_val = record.get('minutes_volatility_last_10')
                if mv_val is not None:
                    entry['minutes_volatility_last_10'] = round(float(mv_val), 2)
                    vol_count += 1

                if entry:
                    self._v17_opportunity_risk_lookup[player] = entry

        logger.info(
            f"Batch V17 opportunity risk: {len(self._v17_opportunity_risk_lookup)} players "
            f"(blowout={blowout_count}, volatility={vol_count})"
        )

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

            # Session 144: When daily_cache misses a player, compute from last_10_games
            # This fixes the ~13% default rate caused by PlayerDailyCacheProcessor
            # only caching players with games TODAY (not all active season players)
            if not cache_data and player_lookup in self._last_10_games_lookup:
                computed = self._compute_cache_fields_from_games(player_lookup, game_date)
                if computed:
                    phase4_data.update(computed)
                    self._cache_miss_players.add(player_lookup)  # Session 146: Track cache misses
                    logger.debug(f"{player_lookup}: Computed cache fields from last_10_games (cache miss fallback)")

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

    def was_cache_miss(self, player_lookup: str) -> bool:
        """Check if a player's daily cache data was computed via fallback (Session 146)."""
        return player_lookup in self._cache_miss_players

    def get_cache_miss_summary(self) -> Dict[str, Any]:
        """Get summary of cache misses for current batch (Session 146)."""
        total_players = len(self._daily_cache_lookup) + len(self._cache_miss_players)
        return {
            'cache_hit_count': len(self._daily_cache_lookup),
            'cache_miss_count': len(self._cache_miss_players),
            'cache_miss_players': sorted(self._cache_miss_players),
            'cache_miss_rate': len(self._cache_miss_players) / total_players if total_players > 0 else 0.0,
        }

    def get_data_provenance(self) -> Dict[str, Any]:
        """
        Get data provenance summary for the current batch extraction.

        Returns metadata about what data sources were used and any fallbacks.
        This should be stored with each feature record for audit trail.

        Returns:
            Dict with provenance metadata:
            - composite_factors_source: 'exact_date', 'partial_fallback', 'none'
            - matchup_data_available: True if matchup-specific factors are valid
            - fallback_reasons: List of reasons why fallbacks were used
        """
        return {
            'composite_factors_source': self._composite_factors_source,
            'matchup_data_available': self._matchup_data_available,
            'fallback_reasons': self._fallback_reasons.copy(),
            'matchup_data_status': 'COMPLETE' if self._matchup_data_available else 'MATCHUP_UNAVAILABLE'
        }

    def get_player_data_provenance(self, player_lookup: str) -> Dict[str, Any]:
        """
        Get per-player data provenance.

        Returns:
            Dict with player-specific provenance:
            - composite_source: Where composite factors came from
            - matchup_valid: Whether matchup-specific factors are valid
            - fallback_reason: Why fallback was used (if any)
        """
        composite_data = self._composite_factors_lookup.get(player_lookup, {})
        return {
            'composite_source': composite_data.get('_source', 'none'),
            'matchup_valid': composite_data.get('_matchup_valid', False),
            'fallback_reason': composite_data.get('_fallback_reason'),
        }

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
            # FIX (Session 113): Filter out DNPs (NULL points) BEFORE taking windows
            # Bug was: (g.get('points') or 0) converted NULL to 0, polluting averages
            # For star players with DNPs (Kawhi, Jokic), this caused 10-20 pt errors
            # IMPROVED FIX (Session 113 follow-up): Match player_daily_cache logic
            # - Include 0-point games if player actually played (minutes not NULL)
            # - Exclude unmarked DNPs (points=0, minutes=NULL) found in Oct 23-31 data
            if last_10_games:
                # Filter DNPs: include if points not NULL AND (minutes not NULL OR points > 0)
                played_games = [g for g in last_10_games
                                if g.get('points') is not None
                                and (g.get('minutes_played') is not None or g.get('points') > 0)]

                if played_games:
                    points_list = [g.get('points') for g in played_games]

                    # L10: Use up to 10 actual games
                    if len(played_games) >= 10:
                        phase3_data['points_avg_last_10'] = sum(points_list[:10]) / 10
                    elif len(played_games) > 0:
                        phase3_data['points_avg_last_10'] = sum(points_list) / len(played_games)

                    # L5: Use up to 5 actual games
                    if len(played_games) >= 5:
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
            # FIX (Session 113): Filter out DNPs (NULL points) BEFORE taking windows
            # IMPROVED FIX (Session 113 follow-up): Match player_daily_cache logic
            # - Include 0-point games if player actually played (minutes not NULL)
            # - Exclude unmarked DNPs (points=0, minutes=NULL) found in Oct 23-31 data
            if last_10_games:
                # Filter DNPs: include if points not NULL AND (minutes not NULL OR points > 0)
                played_games = [g for g in last_10_games
                                if g.get('points') is not None
                                and (g.get('minutes_played') is not None or g.get('points') > 0)]

                if played_games:
                    # L10: Use up to 10 actual games
                    if len(played_games) >= 10:
                        phase3_data['points_avg_last_10'] = sum(g['points'] for g in played_games[:10]) / 10
                    elif len(played_games) > 0:
                        phase3_data['points_avg_last_10'] = sum(g['points'] for g in played_games) / len(played_games)

                    # L5: Use up to 5 actual games
                    if len(played_games) >= 5:
                        phase3_data['points_avg_last_5'] = sum(g['points'] for g in played_games[:5]) / 5

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
            opponent_days_rest,
            games_in_last_7_days
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