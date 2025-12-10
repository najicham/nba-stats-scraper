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
from datetime import date, datetime
import logging

logger = logging.getLogger(__name__)


class PredictionDataLoader:
    """Loads data from BigQuery for Phase 5 predictions"""
    
    def __init__(self, project_id: str, location: str = 'us-west2'):
        """
        Initialize data loader

        Args:
            project_id: GCP project ID (e.g., 'nba-props-platform')
            location: BigQuery location (default: us-west2)
        """
        self.project_id = project_id
        self.client = bigquery.Client(project=project_id, location=location)

        logger.info(f"Initialized PredictionDataLoader for project {project_id} in {location}")
    
    # ========================================================================
    # FEATURES LOADING (Required by ALL systems)
    # ========================================================================
    
    def load_features(
        self,
        player_lookup: str,
        game_date: date,
        feature_version: str = 'v1_baseline_25'
    ) -> Optional[Dict]:
        """
        Load 25 features from ml_feature_store_v2
        
        Args:
            player_lookup: Player identifier (e.g., 'lebron-james')
            game_date: Game date (date object)
            feature_version: Feature version (default: 'v1_baseline_25')
        
        Returns:
            Dict with features or None if not found
            
        Example Return:
            {
                'feature_count': 25,
                'feature_version': 'v1_baseline_25',
                'data_source': 'phase4',
                'feature_quality_score': 95.5,
                'points_avg_last_5': 28.4,
                'points_avg_last_10': 27.2,
                # ... 23 more features
            }
        """
        query = """
        SELECT
            features,
            feature_names,
            feature_quality_score,
            data_source,

            -- Completeness metadata (Phase 5)
            expected_games_count,
            actual_games_count,
            completeness_percentage,
            missing_games_count,
            is_production_ready,
            data_quality_issues,
            backfill_bootstrap_mode,
            processing_decision_reason
        FROM `{project}.nba_predictions.ml_feature_store_v2`
        WHERE player_lookup = @player_lookup
          AND game_date = @game_date
          AND feature_version = @feature_version
        LIMIT 1
        """.format(project=self.project_id)
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                bigquery.ScalarQueryParameter("feature_version", "STRING", feature_version)
            ]
        )
        
        try:
            results = self.client.query(query, job_config=job_config).result()
            row = next(results, None)
            
            if row is None:
                logger.warning(f"No features found for {player_lookup} on {game_date}")
                return None
            
            # Convert arrays to dict with named features
            feature_array = row.features
            feature_names = row.feature_names
            
            if len(feature_array) != len(feature_names):
                logger.error(f"Feature array length mismatch: {len(feature_array)} vs {len(feature_names)}")
                return None
            
            # Build feature dict
            features = dict(zip(feature_names, feature_array))

            # Add metadata
            features['feature_count'] = len(feature_array)
            features['feature_version'] = feature_version
            features['data_source'] = row.data_source
            features['feature_quality_score'] = float(row.feature_quality_score)
            features['features_array'] = feature_array  # Keep array for systems that need it

            # Add completeness metadata (Phase 5)
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

            logger.debug(
                f"Loaded {len(feature_names)} features for {player_lookup} "
                f"(completeness: {features['completeness']['completeness_percentage']:.1f}%, "
                f"production_ready: {features['completeness']['is_production_ready']})"
            )
            return features
            
        except Exception as e:
            logger.error(f"Error loading features for {player_lookup}: {e}")
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
        # Query only columns that exist in player_game_summary
        query = """
        WITH recent_games AS (
            SELECT
                game_date,
                opponent_team_abbr,
                points,
                minutes_played
            FROM `{project}.nba_analytics.player_game_summary`
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
        """.format(project=self.project_id)

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                bigquery.ScalarQueryParameter("lookback_days", "INT64", lookback_days),
                bigquery.ScalarQueryParameter("max_games", "INT64", max_games)
            ]
        )

        try:
            results = self.client.query(query, job_config=job_config).result()

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

        except Exception as e:
            logger.error(f"Error loading historical games for {player_lookup}: {e}")
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
        Load game context from upcoming_player_game_context
        
        Provides metadata about the upcoming game (opponent, venue, etc.)
        
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
        query = """
        SELECT
            game_id,
            opponent_team_abbr,
            is_home,
            days_rest,
            back_to_back
        FROM `{project}.nba_analytics.upcoming_player_game_context`
        WHERE player_lookup = @player_lookup
          AND game_date = @game_date
        LIMIT 1
        """.format(project=self.project_id)
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
            ]
        )
        
        try:
            results = self.client.query(query, job_config=job_config).result()
            row = next(results, None)
            
            if row is None:
                logger.warning(f"No game context found for {player_lookup} on {game_date}")
                return None
            
            return {
                'game_id': row.game_id,
                'opponent_team_abbr': row.opponent_team_abbr,
                'is_home': row.is_home,
                'days_rest': row.days_rest,
                'back_to_back': row.back_to_back
            }
            
        except Exception as e:
            logger.error(f"Error loading game context for {player_lookup}: {e}")
            return None
    
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
        reducing data loading time from ~225s to ~3-5s per game date.

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
            FROM `{project}.nba_analytics.player_game_summary`
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
        """.format(project=self.project_id)

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("player_lookups", "STRING", player_lookups),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                bigquery.ScalarQueryParameter("lookback_days", "INT64", lookback_days),
                bigquery.ScalarQueryParameter("max_games", "INT64", max_games)
            ]
        )

        try:
            results = self.client.query(query, job_config=job_config).result()

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
            return player_games

        except Exception as e:
            logger.error(f"Error in batch historical games load: {e}")
            # Fallback to empty results (caller should handle gracefully)
            return {p: [] for p in player_lookups}

    def load_features_batch_for_date(
        self,
        player_lookups: List[str],
        game_date: date,
        feature_version: str = 'v1_baseline_25'
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

        query = """
        SELECT
            player_lookup,
            features,
            feature_names,
            feature_quality_score,
            data_source,
            expected_games_count,
            actual_games_count,
            completeness_percentage,
            missing_games_count,
            is_production_ready,
            data_quality_issues,
            backfill_bootstrap_mode,
            processing_decision_reason
        FROM `{project}.nba_predictions.ml_feature_store_v2`
        WHERE player_lookup IN UNNEST(@player_lookups)
          AND game_date = @game_date
          AND feature_version = @feature_version
        """.format(project=self.project_id)

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("player_lookups", "STRING", player_lookups),
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                bigquery.ScalarQueryParameter("feature_version", "STRING", feature_version)
            ]
        )

        try:
            results = self.client.query(query, job_config=job_config).result()

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

                # Add metadata
                features['feature_count'] = len(feature_array)
                features['feature_version'] = feature_version
                features['data_source'] = row.data_source
                features['feature_quality_score'] = float(row.feature_quality_score)
                features['features_array'] = feature_array

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
            return player_features

        except Exception as e:
            logger.error(f"Error in batch features load: {e}")
            return {}

    def load_features_batch(
        self,
        player_game_pairs: List[tuple],
        feature_version: str = 'v1_baseline_25'
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
    
    def close(self):
        """Close BigQuery client connection"""
        self.client.close()
        logger.info("Closed BigQuery client connection")


# ============================================================================
# FEATURE VALIDATION
# ============================================================================

def validate_features(features: Dict, min_quality_score: float = 70.0) -> tuple:
    """
    Validate features are complete and high quality
    
    Checks:
    1. All required fields present
    2. No null/NaN values
    3. Quality score meets minimum threshold
    4. Values in reasonable ranges
    
    Args:
        features: Feature dictionary from ml_feature_store_v2
        min_quality_score: Minimum acceptable quality score (default: 70)
    
    Returns:
        tuple: (is_valid, list_of_errors)
        
    Example:
        is_valid, errors = validate_features(features)
        if not is_valid:
            logger.error(f"Invalid features: {errors}")
            return []
    """
    errors = []
    
    # Required fields (25 features)
    required_fields = [
        # Recent performance (0-4)
        'points_avg_last_5',
        'points_avg_last_10',
        'points_avg_season',
        'points_std_last_10',
        'games_played_last_7_days',
        
        # Composite factors (5-12)
        'fatigue_score',
        'shot_zone_mismatch_score',
        'pace_score',
        'usage_spike_score',
        'referee_favorability_score',
        'look_ahead_pressure_score',
        'matchup_history_score',
        'momentum_score',
        
        # Matchup context (13-17)
        'opponent_def_rating_last_15',
        'opponent_pace_last_15',
        'is_home',
        'days_rest',
        'back_to_back',
        
        # Shot zones (18-21)
        'paint_rate_last_10',
        'mid_range_rate_last_10',
        'three_pt_rate_last_10',
        'assisted_rate_last_10',
        
        # Team context (22-24)
        'team_pace_last_10',
        'team_off_rating_last_10',
        'usage_rate_last_10',
        
        # Metadata
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
        ('opponent_def_rating_last_15', 95, 125),
        ('usage_rate_last_10', 5, 45),
        ('is_home', 0, 1),
        ('days_rest', 0, 10),
        ('back_to_back', 0, 1)
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
    elif system_id in ['similarity_balanced_v1', 'xgboost_v1']:
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