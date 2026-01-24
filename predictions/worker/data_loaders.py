# predictions/worker/data_loaders.py

"""
BigQuery Data Loaders for Phase 5 Prediction Worker

Loads data required by prediction systems:
1. Features from ml_feature_store_v2 (ALL systems need this)
2. Historical games from player_game_summary (Similarity system needs this)
3. Game context from upcoming_player_game_context (metadata)

Design:
- Connection pooling via reusable BigQuery client
- Graceful degradation (return None on errors, don't crash)
- Logging for debugging
- Parameter validation

Performance:
- Features query: ~10-20ms per player
- Historical games query: ~50-100ms per player
- Total: ~60-120ms per player (acceptable for 450 players)
"""

from typing import Dict, List, Optional
from google.cloud import bigquery
from google.api_core import exceptions as gcp_exceptions
from google.cloud.exceptions import GoogleCloudError
from datetime import date, datetime
import logging
import os

from shared.utils.query_cache import QueryCache, get_query_cache

logger = logging.getLogger(__name__)

# Query timeout in seconds - prevents worker hangs on slow/stuck queries
# Increased from 30s to 120s (Session 102) to support batch loading for 300-400 players
# Batch loading performance: 118 players = 0.68s, 360 players ≈ 2-3s (linear scaling)
# 120s provides 40-60x safety buffer while enabling massive performance gains
QUERY_TIMEOUT_SECONDS = 120

# Cache TTL settings (in seconds)
# Same-day predictions: short TTL because features may be updated multiple times
# Historical dates: longer TTL since data shouldn't change
FEATURES_CACHE_TTL_SAME_DAY = 300  # 5 minutes for today's date
FEATURES_CACHE_TTL_HISTORICAL = 3600  # 1 hour for historical dates


class PredictionDataLoader:
    """Loads data from BigQuery for Phase 5 predictions"""

    def __init__(self, project_id: str, location: str = 'us-west2', dataset_prefix: str = ''):
        """
        Initialize data loader

        Args:
            project_id: GCP project ID (e.g., 'nba-props-platform')
            location: BigQuery location (default: us-west2)
            dataset_prefix: Optional dataset prefix for test isolation (e.g., "test")
        """
        self.project_id = project_id
        self.dataset_prefix = dataset_prefix
        self.client = bigquery.Client(project=project_id, location=location)

        # Construct dataset names with optional prefix
        self.predictions_dataset = f"{dataset_prefix}_nba_predictions" if dataset_prefix else "nba_predictions"
        self.analytics_dataset = f"{dataset_prefix}_nba_analytics" if dataset_prefix else "nba_analytics"
        self.precompute_dataset = f"{dataset_prefix}_nba_precompute" if dataset_prefix else "nba_precompute"

        # Instance-level cache for historical games (keyed by game_date)
        # First request for a game_date batch-loads all players, subsequent requests use cache
        # This provides ~50x speedup (1 query vs 450 queries)
        self._historical_games_cache: Dict[date, Dict[str, List[Dict]]] = {}

        # Instance-level cache for features (keyed by game_date)
        # First request for a game_date batch-loads all players, subsequent requests use cache
        # This provides ~7-8x speedup (15s → 2s for 150 players)
        self._features_cache: Dict[date, Dict[str, Dict]] = {}

        # Cache timestamps for TTL management
        # Same-day predictions use short TTL (5 min) to pick up new features
        # Historical dates use longer TTL (1 hour) since data is stable
        self._features_cache_timestamps: Dict[date, datetime] = {}

        # Instance-level cache for game context (keyed by game_date)
        # First request for a game_date batch-loads all players, subsequent requests use cache
        # This provides ~10x speedup (8-12s → <1s for 150 players)
        self._game_context_cache: Dict[date, Dict[str, Dict]] = {}

        # Query-level cache for BigQuery results (shared across instances via singleton)
        # Provides caching for expensive queries that don't change frequently
        # Uses TTL based on data freshness (shorter for same-day, longer for historical)
        self._query_cache = get_query_cache(
            default_ttl_seconds=FEATURES_CACHE_TTL_HISTORICAL,
            max_size=5000,  # Limit memory usage
            name="prediction_data_loader"
        )

        logger.info(f"Initialized PredictionDataLoader for project {project_id} in {location} (dataset_prefix: {dataset_prefix or 'production'})")

    def invalidate_features_cache(self, game_date: Optional[date] = None) -> int:
        """
        Invalidate features cache for a specific date or all dates.

        Useful for forcing a refresh when features have been updated in BigQuery.

        Args:
            game_date: Date to invalidate. If None, clears entire cache.

        Returns:
            Number of cache entries cleared
        """
        if game_date is None:
            count = len(self._features_cache)
            self._features_cache.clear()
            self._features_cache_timestamps.clear()
            logger.info(f"Cleared entire features cache ({count} entries)")
            return count
        else:
            if game_date in self._features_cache:
                del self._features_cache[game_date]
                if game_date in self._features_cache_timestamps:
                    del self._features_cache_timestamps[game_date]
                logger.info(f"Invalidated features cache for {game_date}")
                return 1
            return 0

    # ========================================================================
    # FEATURES LOADING (Required by ALL systems)
    # ========================================================================
    
    def load_features(
        self,
        player_lookup: str,
        game_date: date,
        feature_version: str = 'v2_33features'
    ) -> Optional[Dict]:
        """
        Load 33 features from ml_feature_store_v2 with intelligent caching

        Performance optimization: First request for a game_date batch-loads ALL players
        in ONE query (~2s), subsequent requests use cache (~instant). Provides ~7-8x speedup
        over sequential per-player queries (15s → 2s for 150 players).

        Args:
            player_lookup: Player identifier (e.g., 'lebron-james')
            game_date: Game date (date object)
            feature_version: Feature version (default: 'v2_33features')

        Returns:
            Dict with features or None if not found

        Example Return:
            {
                'feature_count': 33,
                'feature_version': 'v2_33features',
                'data_source': 'phase4',
                'feature_quality_score': 95.5,
                'points_avg_last_5': 28.4,
                'points_avg_last_10': 27.2,
                # ... 23 more features
            }
        """
        # Check cache first (7-8x speedup via batch loading)
        if game_date in self._features_cache:
            # Check if cache is stale
            cache_timestamp = self._features_cache_timestamps.get(game_date)
            is_stale = False

            if cache_timestamp:
                cache_age_seconds = (datetime.now() - cache_timestamp).total_seconds()
                # Use short TTL for same-day, longer for historical
                ttl = FEATURES_CACHE_TTL_SAME_DAY if game_date >= date.today() else FEATURES_CACHE_TTL_HISTORICAL
                is_stale = cache_age_seconds > ttl

                if is_stale:
                    logger.info(f"Cache expired for {game_date} (age: {cache_age_seconds:.0f}s > TTL: {ttl}s)")
                    del self._features_cache[game_date]
                    del self._features_cache_timestamps[game_date]

            if not is_stale:
                cached = self._features_cache[game_date].get(player_lookup)
                if cached:
                    logger.debug(f"Cache hit for {player_lookup} features")
                    return cached
                # Player not in cache - might not have features, return None
                logger.debug(f"Cache miss for {player_lookup} (date cached but player not found)")
                return None

        # Cache miss for date (or expired) - batch load all players for this game_date
        try:
            # Get all player_lookups with games on this date
            all_players = self._get_players_for_date(game_date)
            if all_players:
                logger.info(f"Batch loading features for {len(all_players)} players on {game_date}")
                batch_result = self.load_features_batch_for_date(all_players, game_date, feature_version)
                self._features_cache[game_date] = batch_result
                self._features_cache_timestamps[game_date] = datetime.now()
                # Return from cache
                return batch_result.get(player_lookup)
            else:
                # No players found for this date - cache empty dict with short TTL
                # Use short TTL so we retry if features become available
                self._features_cache[game_date] = {}
                self._features_cache_timestamps[game_date] = datetime.now()
                logger.warning(f"No players found for {game_date}")
                return None
        except gcp_exceptions.BadRequest as e:
            logger.error(f"BigQuery syntax error in batch features load for {game_date}: {e}")
            return None
        except gcp_exceptions.NotFound as e:
            logger.error(f"BigQuery table not found in batch features load for {game_date}: {e}")
            return None
        except (gcp_exceptions.ServiceUnavailable, gcp_exceptions.DeadlineExceeded) as e:
            logger.error(f"BigQuery timeout/unavailable in batch features load for {game_date}: {e}")
            return None
        except GoogleCloudError as e:
            logger.error(f"GCP error in batch features load for {game_date}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in batch features load for {game_date}: {type(e).__name__}: {e}", exc_info=True)
            return None
    
    # ========================================================================
    # HISTORICAL GAMES LOADING (Required by Similarity system)
    # ========================================================================
    
    def load_historical_games(
        self,
        player_lookup: str,
        game_date: date,
        lookback_days: int = 90,
        max_games: int = 30
    ) -> List[Dict]:
        """
        Load historical games for similarity matching

        Uses instance-level caching with batch loading for ~50x speedup.
        First call for a game_date batch-loads all players, subsequent calls use cache.

        Queries player_game_summary for recent games and calculates context:
        - opponent_tier: Categorized from opponent (defaults to average since rating not available)
        - recent_form: Hot/normal/cold based on rolling average

        Args:
            player_lookup: Player identifier
            game_date: Current game date (to filter history before this)
            lookback_days: How far back to look (default 90 days)
            max_games: Maximum games to return (default 30)

        Returns:
            List of historical games with context

        Example Return:
            [
                {
                    'game_date': '2024-11-05',
                    'opponent_team_abbr': 'GSW',
                    'opponent_tier': 'tier_2_average',
                    'days_rest': 1,
                    'is_home': True,
                    'recent_form': 'normal',
                    'points': 28,
                    'minutes_played': 35
                },
                # ... more games
            ]
        """
        # Check cache first (50x speedup via batch loading)
        if game_date in self._historical_games_cache:
            cached = self._historical_games_cache[game_date].get(player_lookup, [])
            if cached:
                logger.debug(f"Cache hit for {player_lookup} historical games")
                return cached
            # Player not in cache - might not have games, fall through to query

        # Try batch loading all players for this game_date (first request populates cache)
        if game_date not in self._historical_games_cache:
            try:
                # Get all player_lookups with games on this date from feature store
                all_players = self._get_players_for_date(game_date)
                if all_players:
                    logger.info(f"Batch loading historical games for {len(all_players)} players on {game_date}")
                    batch_result = self.load_historical_games_batch(all_players, game_date, lookback_days, max_games)
                    self._historical_games_cache[game_date] = batch_result
                    # Return from cache
                    return batch_result.get(player_lookup, [])
            except (gcp_exceptions.BadRequest, gcp_exceptions.NotFound) as e:
                logger.warning(f"Batch load query error, falling back to individual query: {e}")
                # Fall through to individual query
            except (gcp_exceptions.ServiceUnavailable, gcp_exceptions.DeadlineExceeded) as e:
                logger.warning(f"Batch load timeout/unavailable, falling back to individual query: {e}")
                # Fall through to individual query
            except GoogleCloudError as e:
                logger.warning(f"Batch load GCP error, falling back to individual query: {e}")
                # Fall through to individual query
            except Exception as e:
                logger.warning(f"Batch load unexpected error, falling back to individual query: {type(e).__name__}: {e}")
                # Fall through to individual query
        # Query only columns that exist in player_game_summary
        query = """
        WITH recent_games AS (
            SELECT
                game_date,
                opponent_team_abbr,
                points,
                minutes_played
            FROM `{project}.{analytics_dataset}.player_game_summary`
            WHERE player_lookup = @player_lookup
              AND game_date < @game_date
              AND game_date >= DATE_SUB(@game_date, INTERVAL @lookback_days DAY)
            ORDER BY game_date DESC
            LIMIT @max_games
        ),
        games_with_lag AS (
            SELECT
                game_date,
                opponent_team_abbr,
                points,
                minutes_played,
                LAG(game_date) OVER (ORDER BY game_date DESC) as next_game_date
            FROM recent_games
        )
        SELECT
            game_date,
            opponent_team_abbr,
            points,
            minutes_played,
            DATE_DIFF(next_game_date, game_date, DAY) as days_until_next
        FROM games_with_lag
        ORDER BY game_date DESC
        """.format(project=self.project_id, analytics_dataset=self.analytics_dataset)

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                bigquery.ScalarQueryParameter("lookback_days", "INT64", lookback_days),
                bigquery.ScalarQueryParameter("max_games", "INT64", max_games)
            ]
        )

        try:
            results = self.client.query(query, job_config=job_config).result(timeout=QUERY_TIMEOUT_SECONDS)

            historical_games = []
            all_points = []

            # First pass: collect all data
            rows_list = list(results)
            for row in rows_list:
                if row.points is not None:
                    all_points.append(float(row.points))

            # Calculate season average from available data
            season_avg = sum(all_points) / len(all_points) if all_points else 20.0

            # Second pass: build game records
            for i, row in enumerate(rows_list):
                # Calculate recent form from last 5 games
                recent_points = all_points[max(0, i-5):i] if i > 0 else []
                recent_avg = sum(recent_points) / len(recent_points) if recent_points else season_avg
                recent_form = self._calculate_recent_form(recent_avg, season_avg)

                # days_rest is approximated from gap to next game
                days_rest = row.days_until_next if row.days_until_next else 1

                game = {
                    'game_date': row.game_date.isoformat(),
                    'opponent_team_abbr': row.opponent_team_abbr,
                    'opponent_tier': 'tier_2_average',  # Default - no defense rating available
                    'days_rest': min(days_rest, 7),  # Cap at 7 days
                    'is_home': True,  # Default - not available in table
                    'recent_form': recent_form,
                    'points': float(row.points) if row.points else 0.0,
                    'minutes_played': float(row.minutes_played) if row.minutes_played else 0.0
                }
                historical_games.append(game)

            logger.info(f"Loaded {len(historical_games)} historical games for {player_lookup}")
            return historical_games

        except gcp_exceptions.BadRequest as e:
            logger.error(f"BigQuery syntax error loading historical games for {player_lookup}: {e}")
            return []
        except gcp_exceptions.NotFound as e:
            logger.error(f"BigQuery table not found loading historical games for {player_lookup}: {e}")
            return []
        except (gcp_exceptions.ServiceUnavailable, gcp_exceptions.DeadlineExceeded) as e:
            logger.error(f"BigQuery timeout/unavailable loading historical games for {player_lookup}: {e}")
            return []
        except GoogleCloudError as e:
            logger.error(f"GCP error loading historical games for {player_lookup}: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error loading historical games for {player_lookup}: {type(e).__name__}: {e}", exc_info=True)
            return []
    
    def _calculate_opponent_tier(self, def_rating: Optional[float]) -> str:
        """
        Categorize opponent into defensive tiers
        
        Args:
            def_rating: Opponent's defensive rating (100-120 range, 110 = average)
        
        Returns:
            'tier_1_elite', 'tier_2_average', or 'tier_3_weak'
        """
        if def_rating is None:
            return 'tier_2_average'  # Default to average if unknown
        
        if def_rating < 110:
            return 'tier_1_elite'
        elif def_rating < 115:
            return 'tier_2_average'
        else:
            return 'tier_3_weak'
    
    def _calculate_recent_form(
        self,
        points_last_5: Optional[float],
        points_season: Optional[float]
    ) -> str:
        """
        Categorize player's recent form
        
        Args:
            points_last_5: Points per game last 5 games
            points_season: Points per game season average
        
        Returns:
            'hot', 'normal', or 'cold'
        """
        if points_last_5 is None or points_season is None:
            return 'normal'  # Default if data missing
        
        diff = points_last_5 - points_season
        
        if diff >= 3:
            return 'hot'
        elif diff <= -3:
            return 'cold'
        else:
            return 'normal'
    
    # ========================================================================
    # GAME CONTEXT LOADING (Optional metadata)
    # ========================================================================
    
    def load_game_context(
        self,
        player_lookup: str,
        game_date: date
    ) -> Optional[Dict]:
        """
        Load game context from upcoming_player_game_context with intelligent caching

        PERFORMANCE OPTIMIZATION: On first request for a game_date, batch-loads ALL players
        for that date in ONE query (8-12s → <1s for 150 players). Subsequent requests for
        the same date use the cache, providing ~10x overall speedup.

        Args:
            player_lookup: Player identifier
            game_date: Game date

        Returns:
            Dict with game context or None if not found

        Example Return:
            {
                'game_id': '20241108_LAL_GSW',
                'opponent_team_abbr': 'GSW',
                'is_home': True,
                'days_rest': 1,
                'back_to_back': False
            }
        """
        # Check cache first
        if game_date in self._game_context_cache:
            cached_context = self._game_context_cache[game_date].get(player_lookup)
            if cached_context is not None:
                logger.debug(f"Cache HIT: Game context for {player_lookup} on {game_date}")
                return cached_context
            else:
                logger.debug(f"Cache MISS: {player_lookup} not in cached date {game_date}")
                return None

        # Cache MISS for this date - batch load ALL players for this date
        logger.info(f"Game context cache MISS for date {game_date} - batch loading all players")

        # Batch load game context for all players on this date
        batch_context = self.load_game_context_batch(game_date)

        # Store in cache
        self._game_context_cache[game_date] = batch_context
        logger.info(f"Cached game context for {len(batch_context)} players on {game_date}")

        # Return context for requested player
        context = batch_context.get(player_lookup)
        if context is None:
            logger.warning(f"Player {player_lookup} not found in batch results for {game_date}")

        return context

    def load_game_context_batch(
        self,
        game_date: date
    ) -> Dict[str, Dict]:
        """
        Load game context for ALL players on a single date in ONE query (batch optimization)

        This replaces 150+ sequential queries with a single batch query,
        reducing game context loading time from ~8-12s to <1s per game date.

        Args:
            game_date: Date to load game context for

        Returns:
            Dict mapping player_lookup to game context dict
        """
        query = """
        SELECT
            player_lookup,
            game_id,
            opponent_team_abbr,
            is_home,
            days_rest,
            back_to_back
        FROM `{project}.{analytics_dataset}.upcoming_player_game_context`
        WHERE game_date = @game_date
        """.format(project=self.project_id, analytics_dataset=self.analytics_dataset)

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
            ]
        )

        try:
            results = self.client.query(query, job_config=job_config).result(timeout=QUERY_TIMEOUT_SECONDS)

            player_contexts: Dict[str, Dict] = {}

            for row in results:
                player_contexts[row.player_lookup] = {
                    'game_id': row.game_id,
                    'opponent_team_abbr': row.opponent_team_abbr,
                    'is_home': row.is_home,
                    'days_rest': row.days_rest,
                    'back_to_back': row.back_to_back
                }

            logger.info(f"Batch loaded game context for {len(player_contexts)} players on {game_date}")
            return player_contexts

        except gcp_exceptions.BadRequest as e:
            logger.error(f"BigQuery syntax error in batch game context load: {e}")
            return {}
        except gcp_exceptions.NotFound as e:
            logger.error(f"BigQuery table not found in batch game context load: {e}")
            return {}
        except (gcp_exceptions.ServiceUnavailable, gcp_exceptions.DeadlineExceeded) as e:
            logger.error(f"BigQuery timeout/unavailable in batch game context load: {e}")
            return {}
        except GoogleCloudError as e:
            logger.error(f"GCP error in batch game context load: {e}")
            return {}
        except Exception as e:
            logger.error(f"Unexpected error in batch game context load: {type(e).__name__}: {e}", exc_info=True)
            return {}
    
    # ========================================================================
    # BATCH LOADING (Optimized - 10-40x speedup)
    # ========================================================================

    def load_historical_games_batch(
        self,
        player_lookups: List[str],
        game_date: date,
        lookback_days: int = 90,
        max_games: int = 30
    ) -> Dict[str, List[Dict]]:
        """
        Load historical games for ALL players in ONE query (batch optimization)

        This replaces 150 sequential queries with a single batch query,
        reducing data loading time from ~225s to ~0.68s per game date.

        VERIFIED PERFORMANCE (Dec 31, 2025):
        - Expected: 50x speedup (225s → 3-5s)
        - Actual: 331x speedup (225s → 0.68s)
        - Tested with 118 players, all received pre-loaded data in <1 second

        Args:
            player_lookups: List of player identifiers
            game_date: Current game date (to filter history before this)
            lookback_days: How far back to look (default 90 days)
            max_games: Maximum games per player (default 30)

        Returns:
            Dict mapping player_lookup to list of historical games
        """
        if not player_lookups:
            return {}

        # Generate cache key for this batch query
        # Sort player_lookups for consistent cache key
        sorted_players = sorted(player_lookups)
        cache_key = self._query_cache.generate_key(
            query_template="historical_games_batch",
            params={
                "players_hash": hash(tuple(sorted_players)),
                "game_date": game_date,
                "lookback_days": lookback_days,
                "max_games": max_games,
                "dataset": self.analytics_dataset
            },
            prefix="hist_games"
        )

        # Check cache first
        cached_result = self._query_cache.get(cache_key)
        if cached_result is not None:
            logger.info(f"Query cache HIT for historical games batch on {game_date}")
            return cached_result

        # Cache miss - execute query
        logger.debug(f"Query cache MISS for historical games batch on {game_date}")

        # Batch query for all players at once using UNNEST
        query = """
        WITH recent_games AS (
            SELECT
                player_lookup,
                game_date,
                opponent_team_abbr,
                points,
                minutes_played,
                ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) as game_rank
            FROM `{project}.{analytics_dataset}.player_game_summary`
            WHERE player_lookup IN UNNEST(@player_lookups)
              AND game_date < @game_date
              AND game_date >= DATE_SUB(@game_date, INTERVAL @lookback_days DAY)
        ),
        limited_games AS (
            SELECT *
            FROM recent_games
            WHERE game_rank <= @max_games
        ),
        games_with_lag AS (
            SELECT
                player_lookup,
                game_date,
                opponent_team_abbr,
                points,
                minutes_played,
                game_rank,
                LAG(game_date) OVER (PARTITION BY player_lookup ORDER BY game_date DESC) as next_game_date
            FROM limited_games
        )
        SELECT
            player_lookup,
            game_date,
            opponent_team_abbr,
            points,
            minutes_played,
            game_rank,
            DATE_DIFF(next_game_date, game_date, DAY) as days_until_next
        FROM games_with_lag
        ORDER BY player_lookup, game_date DESC
        """.format(project=self.project_id, analytics_dataset=self.analytics_dataset)

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("player_lookups", "STRING", player_lookups),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                bigquery.ScalarQueryParameter("lookback_days", "INT64", lookback_days),
                bigquery.ScalarQueryParameter("max_games", "INT64", max_games)
            ]
        )

        try:
            results = self.client.query(query, job_config=job_config).result(timeout=QUERY_TIMEOUT_SECONDS)

            # Group results by player and calculate derived fields
            player_games: Dict[str, List[Dict]] = {p: [] for p in player_lookups}
            player_points: Dict[str, List[float]] = {p: [] for p in player_lookups}

            # First pass: collect all rows grouped by player
            rows_by_player: Dict[str, list] = {p: [] for p in player_lookups}
            for row in results:
                if row.player_lookup in rows_by_player:
                    rows_by_player[row.player_lookup].append(row)
                    if row.points is not None:
                        player_points[row.player_lookup].append(float(row.points))

            # Second pass: build game records with context
            for player_lookup, rows in rows_by_player.items():
                all_points = player_points.get(player_lookup, [])
                season_avg = sum(all_points) / len(all_points) if all_points else 20.0

                for i, row in enumerate(rows):
                    # Calculate recent form from last 5 games
                    recent_points = all_points[max(0, i-5):i] if i > 0 else []
                    recent_avg = sum(recent_points) / len(recent_points) if recent_points else season_avg
                    recent_form = self._calculate_recent_form(recent_avg, season_avg)

                    days_rest = row.days_until_next if row.days_until_next else 1

                    game = {
                        'game_date': row.game_date.isoformat(),
                        'opponent_team_abbr': row.opponent_team_abbr,
                        'opponent_tier': 'tier_2_average',
                        'days_rest': min(days_rest, 7),
                        'is_home': True,
                        'recent_form': recent_form,
                        'points': float(row.points) if row.points else 0.0,
                        'minutes_played': float(row.minutes_played) if row.minutes_played else 0.0
                    }
                    player_games[player_lookup].append(game)

            total_games = sum(len(games) for games in player_games.values())
            logger.info(f"Batch loaded {total_games} historical games for {len(player_lookups)} players")

            # Cache the result with TTL based on data freshness
            # Historical data uses longer TTL since it doesn't change
            cache_ttl = self._query_cache.get_ttl_for_date(game_date)
            self._query_cache.set(cache_key, player_games, ttl_seconds=cache_ttl)

            return player_games

        except gcp_exceptions.BadRequest as e:
            logger.error(f"BigQuery syntax error in batch historical games load: {e}")
            return {p: [] for p in player_lookups}
        except gcp_exceptions.NotFound as e:
            logger.error(f"BigQuery table not found in batch historical games load: {e}")
            return {p: [] for p in player_lookups}
        except (gcp_exceptions.ServiceUnavailable, gcp_exceptions.DeadlineExceeded) as e:
            logger.error(f"BigQuery timeout/unavailable in batch historical games load: {e}")
            return {p: [] for p in player_lookups}
        except GoogleCloudError as e:
            logger.error(f"GCP error in batch historical games load: {e}")
            return {p: [] for p in player_lookups}
        except Exception as e:
            logger.error(f"Unexpected error in batch historical games load: {type(e).__name__}: {e}", exc_info=True)
            # Fallback to empty results (caller should handle gracefully)
            return {p: [] for p in player_lookups}

    def load_features_batch_for_date(
        self,
        player_lookups: List[str],
        game_date: date,
        feature_version: str = 'v2_33features'
    ) -> Dict[str, Dict]:
        """
        Load features for ALL players on a single date in ONE query (batch optimization)

        This replaces 150 sequential queries with a single batch query,
        reducing feature loading time from ~15s to ~2s per game date.

        Args:
            player_lookups: List of player identifiers
            game_date: Game date
            feature_version: Feature version

        Returns:
            Dict mapping player_lookup to features dict
        """
        if not player_lookups:
            return {}

        # Generate cache key for this batch query
        sorted_players = sorted(player_lookups)
        cache_key = self._query_cache.generate_key(
            query_template="features_batch_for_date",
            params={
                "players_hash": hash(tuple(sorted_players)),
                "game_date": game_date,
                "feature_version": feature_version,
                "dataset": self.predictions_dataset
            },
            prefix="features"
        )

        # Check cache first
        cached_result = self._query_cache.get(cache_key)
        if cached_result is not None:
            logger.info(f"Query cache HIT for features batch on {game_date}")
            return cached_result

        # Cache miss - execute query
        logger.debug(f"Query cache MISS for features batch on {game_date}")

        query = """
        SELECT
            player_lookup,
            features,
            feature_names,
            feature_quality_score,
            data_source,
            days_rest,
            is_home,
            expected_games_count,
            actual_games_count,
            completeness_percentage,
            missing_games_count,
            is_production_ready,
            data_quality_issues,
            backfill_bootstrap_mode,
            processing_decision_reason
        FROM `{project}.{predictions_dataset}.ml_feature_store_v2`
        WHERE player_lookup IN UNNEST(@player_lookups)
          AND game_date = @game_date
          AND feature_version = @feature_version
        """.format(project=self.project_id, predictions_dataset=self.predictions_dataset)

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("player_lookups", "STRING", player_lookups),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                bigquery.ScalarQueryParameter("feature_version", "STRING", feature_version)
            ]
        )

        try:
            results = self.client.query(query, job_config=job_config).result(timeout=QUERY_TIMEOUT_SECONDS)

            player_features: Dict[str, Dict] = {}

            for row in results:
                # Convert arrays to dict with named features
                feature_array = row.features
                feature_names = row.feature_names

                if len(feature_array) != len(feature_names):
                    logger.warning(f"Feature array length mismatch for {row.player_lookup}")
                    continue

                # Build feature dict
                features = dict(zip(feature_names, feature_array))

                # Add feature name aliases for backward compatibility with prediction systems
                # Some systems expect different names than what ml_feature_store_v2 provides
                FEATURE_ALIASES = {
                    # Feature store name -> Alternative names systems might use
                    'games_in_last_7_days': ['games_played_last_7_days'],
                    'opponent_def_rating': ['opponent_def_rating_last_15'],
                    'opponent_pace': ['opponent_pace_last_15'],
                    'home_away': ['is_home'],
                    'pct_paint': ['paint_rate_last_10'],
                    'pct_mid_range': ['mid_range_rate_last_10'],
                    'pct_three': ['three_pt_rate_last_10'],
                    'pct_free_throw': ['assisted_rate_last_10'],
                    'team_pace': ['team_pace_last_10'],
                    'team_off_rating': ['team_off_rating_last_10'],
                    'team_win_pct': ['usage_rate_last_10'],
                }
                for source_name, aliases in FEATURE_ALIASES.items():
                    if source_name in features:
                        for alias in aliases:
                            features[alias] = features[source_name]

                # Add metadata
                features['feature_count'] = len(feature_array)
                features['feature_version'] = feature_version
                features['data_source'] = row.data_source
                features['feature_quality_score'] = float(row.feature_quality_score)
                features['features_array'] = feature_array

                # Add row-level fields that prediction systems need
                features['days_rest'] = int(row.days_rest) if row.days_rest is not None else 1

                # Add completeness metadata
                features['completeness'] = {
                    'expected_games_count': row.expected_games_count,
                    'actual_games_count': row.actual_games_count,
                    'completeness_percentage': float(row.completeness_percentage) if row.completeness_percentage else 0.0,
                    'missing_games_count': row.missing_games_count,
                    'is_production_ready': row.is_production_ready or False,
                    'data_quality_issues': row.data_quality_issues or [],
                    'backfill_bootstrap_mode': row.backfill_bootstrap_mode or False,
                    'processing_decision_reason': row.processing_decision_reason
                }

                player_features[row.player_lookup] = features

            logger.info(f"Batch loaded features for {len(player_features)}/{len(player_lookups)} players")

            # Cache the result with TTL based on data freshness
            # Same-day data uses shorter TTL (may be updated), historical uses longer
            cache_ttl = self._query_cache.get_ttl_for_date(game_date)
            self._query_cache.set(cache_key, player_features, ttl_seconds=cache_ttl)

            return player_features

        except gcp_exceptions.BadRequest as e:
            logger.error(f"BigQuery syntax error in batch features load: {e}")
            return {}
        except gcp_exceptions.NotFound as e:
            logger.error(f"BigQuery table not found in batch features load: {e}")
            return {}
        except (gcp_exceptions.ServiceUnavailable, gcp_exceptions.DeadlineExceeded) as e:
            logger.error(f"BigQuery timeout/unavailable in batch features load: {e}")
            return {}
        except GoogleCloudError as e:
            logger.error(f"GCP error in batch features load: {e}")
            return {}
        except Exception as e:
            logger.error(f"Unexpected error in batch features load: {type(e).__name__}: {e}", exc_info=True)
            return {}

    def load_features_batch(
        self,
        player_game_pairs: List[tuple],
        feature_version: str = 'v2_33features'
    ) -> Dict[tuple, Dict]:
        """
        Load features for multiple players at once (legacy interface)

        Note: For single-date batch loading, use load_features_batch_for_date()
        which is more efficient.

        Args:
            player_game_pairs: List of (player_lookup, game_date) tuples
            feature_version: Feature version

        Returns:
            Dict mapping (player_lookup, game_date) to features
        """
        if not player_game_pairs:
            return {}

        # Group by game_date for efficient batch queries
        by_date: Dict[date, List[str]] = {}
        for player_lookup, gd in player_game_pairs:
            if gd not in by_date:
                by_date[gd] = []
            by_date[gd].append(player_lookup)

        # Load each date as a batch
        results = {}
        for gd, players in by_date.items():
            date_features = self.load_features_batch_for_date(players, gd, feature_version)
            for player_lookup, features in date_features.items():
                results[(player_lookup, gd)] = features

        return results

    def _get_players_for_date(self, game_date: date) -> List[str]:
        """
        Get all player_lookups that have games on the given date.

        Used by batch loading optimization to determine which players to load.

        Args:
            game_date: Date to query

        Returns:
            List of player_lookup strings
        """
        query = """
        SELECT DISTINCT player_lookup
        FROM `{project}.{predictions_dataset}.ml_feature_store_v2`
        WHERE game_date = @game_date
        """.format(project=self.project_id, predictions_dataset=self.predictions_dataset)

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
            ]
        )

        try:
            results = self.client.query(query, job_config=job_config).result(timeout=QUERY_TIMEOUT_SECONDS)
            players = [row.player_lookup for row in results]
            logger.debug(f"Found {len(players)} players for {game_date}")
            return players
        except gcp_exceptions.BadRequest as e:
            logger.warning(f"BigQuery syntax error getting players for date: {e}")
            return []
        except gcp_exceptions.NotFound as e:
            logger.warning(f"BigQuery table not found getting players for date: {e}")
            return []
        except (gcp_exceptions.ServiceUnavailable, gcp_exceptions.DeadlineExceeded) as e:
            logger.warning(f"BigQuery timeout/unavailable getting players for date: {e}")
            return []
        except GoogleCloudError as e:
            logger.warning(f"GCP error getting players for date: {e}")
            return []
        except Exception as e:
            logger.warning(f"Unexpected error getting players for date: {type(e).__name__}: {e}")
            return []

    def close(self):
        """Close BigQuery client connection"""
        self.client.close()
        logger.info("Closed BigQuery client connection")

    def get_query_cache_stats(self) -> Dict:
        """
        Get query cache statistics for monitoring.

        Returns cache hit/miss rates, size, and other metrics useful for
        understanding cache effectiveness.

        Returns:
            Dict with cache statistics
        """
        return self._query_cache.get_stats()

    def clear_query_cache(self) -> int:
        """
        Clear the query cache.

        Useful when you want to force fresh data from BigQuery.

        Returns:
            Number of entries cleared
        """
        return self._query_cache.clear()


# ============================================================================
# FEATURE VALIDATION
# ============================================================================

def validate_features(features: Dict, min_quality_score: float = None) -> tuple:
    """
    Validate features are complete and high quality

    Checks:
    1. All required fields present
    2. No null/NaN values
    3. Quality score meets minimum threshold
    4. Values in reasonable ranges

    Args:
        features: Feature dictionary from ml_feature_store_v2
        min_quality_score: Minimum acceptable quality score.
            Default reads from PREDICTION_MIN_QUALITY_THRESHOLD env var (70.0 if not set).
            Worker.py typically passes 50.0 for more lenient validation with confidence tracking.

    Note: The threshold difference (50 vs 70) is intentional:
        - 70: Default for strict validation (data quality checks)
        - 50: Used in worker for predictions (allows more through, tracks confidence)
    
    Returns:
        tuple: (is_valid, list_of_errors)
        
    Example:
        is_valid, errors = validate_features(features)
        if not is_valid:
            logger.error(f"Invalid features: {errors}")
            return []
    """
    # Apply default if not specified
    if min_quality_score is None:
        min_quality_score = float(os.environ.get('PREDICTION_MIN_QUALITY_THRESHOLD', '70.0'))

    errors = []

    # Required fields (25 features) - matches ml_feature_store_v2 schema
    required_fields = [
        # Recent performance (0-4)
        'points_avg_last_5',
        'points_avg_last_10',
        'points_avg_season',
        'points_std_last_10',
        'games_in_last_7_days',

        # Composite factors (5-8)
        'fatigue_score',
        'shot_zone_mismatch_score',
        'pace_score',
        'usage_spike_score',

        # Derived factors (9-12)
        'rest_advantage',
        'injury_risk',
        'recent_trend',
        'minutes_change',

        # Matchup context (13-17)
        'opponent_def_rating',
        'opponent_pace',
        'home_away',
        'back_to_back',
        'playoff_game',

        # Shot zones (18-21)
        'pct_paint',
        'pct_mid_range',
        'pct_three',
        'pct_free_throw',

        # Team context (22-24)
        'team_pace',
        'team_off_rating',
        'team_win_pct',

        # Metadata (from row, not feature array)
        'feature_quality_score'
    ]
    
    # Check 1: All required fields present
    missing_fields = [f for f in required_fields if f not in features]
    if missing_fields:
        errors.append(f"Missing fields: {', '.join(missing_fields)}")
        return False, errors
    
    # Check 2: Quality score threshold
    quality_score = features.get('feature_quality_score', 0)
    if quality_score < min_quality_score:
        errors.append(f"Quality score {quality_score} below threshold {min_quality_score}")
        return False, errors
    
    # Check 3: No null or NaN values in critical fields
    for field in required_fields[:-1]:  # Skip quality_score
        value = features[field]
        if value is None:
            errors.append(f"{field} is None")
        elif isinstance(value, float) and value != value:  # NaN check
            errors.append(f"{field} is NaN")
    
    if errors:
        return False, errors
    
    # Check 4: Values in reasonable ranges
    range_checks = [
        ('points_avg_season', 0, 60),
        ('points_avg_last_5', 0, 80),
        ('points_avg_last_10', 0, 80),
        ('fatigue_score', 0, 100),
        ('opponent_def_rating', 95, 125),
        ('home_away', 0, 1),
        ('back_to_back', 0, 1),
        ('playoff_game', 0, 1),
    ]
    
    for field, min_val, max_val in range_checks:
        value = features.get(field)
        if value is not None and (value < min_val or value > max_val):
            errors.append(f"{field}={value} outside range [{min_val}, {max_val}]")
    
    if errors:
        return False, errors
    
    return True, []


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def normalize_confidence(confidence: float, system_id: str) -> float:
    """
    Normalize confidence to 0-1 scale for BigQuery

    Different systems use different confidence scales:
    - Moving Average, Zone Matchup, Ensemble: 0.0-1.0 scale (native)
    - Similarity, XGBoost: 0-100 scale (needs division)

    Args:
        confidence: Raw confidence from system
        system_id: System identifier

    Returns:
        float: Confidence on 0-1 scale
    """
    if system_id in ['moving_average', 'zone_matchup_v1', 'ensemble_v1']:
        # Already 0-1 scale, keep as-is
        return confidence
    elif system_id in ['similarity_balanced_v1', 'xgboost_v1', 'catboost_v8']:
        # Convert 0-100 to 0-1
        return confidence / 100.0
    else:
        # Default: assume 0-1 scale
        logger.warning(f"Unknown system_id {system_id}, assuming 0-1 scale")
        return confidence


def validate_date(date_str: str) -> bool:
    """
    Validate date string is in ISO format (YYYY-MM-DD)
    
    Args:
        date_str: Date string to validate
    
    Returns:
        True if valid, False otherwise
    """
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
        return True
    except ValueError:
        return False