# predictions/worker/prediction_systems/catboost_v12.py

"""
CatBoost V12 Prediction System - Vegas-Free 50-Feature Model

Session 230: V12 deploys a no-vegas CatBoost model (54 features minus 4 vegas = 50 features).
Validated at 67% avg HR edge 3+ across 4 eval windows (+8.7pp over V9).

Key Differences from V9:
- No vegas features (25-28 excluded) — predictions are independent of market
- 50 features (15 new: fatigue, trends, usage, streaks, structural changes)
- V12 features (39-53) computed at prediction time from UPCG + player_game_summary
- MAE loss function (not quantile)

Feature augmentation at prediction time:
- Features 0-24, 29-38 from ml_feature_store_v2 (skip vegas 25-28)
- Features 39-53 from BigQuery batch queries, cached per game_date

Usage:
    from predictions.worker.prediction_systems.catboost_v12 import CatBoostV12

    system = CatBoostV12()
    result = system.predict(player_lookup, features, betting_line)
"""

import hashlib
import logging
import os
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from predictions.worker.prediction_systems.catboost_v8 import ModelLoadError

logger = logging.getLogger(__name__)

MODEL_BUCKET = "nba-props-platform-models"
MODEL_PREFIX = "catboost/v12"
DEFAULT_MODEL_GCS = f"gs://{MODEL_BUCKET}/{MODEL_PREFIX}/catboost_v12_50f_noveg_train20251102-20260131.cbm"

# V12 No-Vegas feature order (50 features = V12 minus indices 25-28)
# Must match training exactly.
V12_NOVEG_FEATURES = [
    # 0-4: Recent Performance
    "points_avg_last_5",
    "points_avg_last_10",
    "points_avg_season",
    "points_std_last_10",
    "games_in_last_7_days",
    # 5-8: Composite Factors
    "fatigue_score",
    "shot_zone_mismatch_score",
    "pace_score",
    "usage_spike_score",
    # 9-12: Derived Factors
    "rest_advantage",
    "injury_risk",
    "recent_trend",
    "minutes_change",
    # 13-17: Matchup Context
    "opponent_def_rating",
    "opponent_pace",
    "home_away",
    "back_to_back",
    "playoff_game",
    # 18-21: Shot Zones
    "pct_paint",
    "pct_mid_range",
    "pct_three",
    "pct_free_throw",
    # 22-24: Team Context
    "team_pace",
    "team_off_rating",
    "team_win_pct",
    # (vegas 25-28 SKIPPED)
    # 29-30: Opponent History
    "avg_points_vs_opponent",
    "games_vs_opponent",
    # 31-32: Minutes/Efficiency
    "minutes_avg_last_10",
    "ppm_avg_last_10",
    # 33: DNP Risk
    "dnp_rate",
    # 34-36: Player Trajectory
    "pts_slope_10g",
    "pts_vs_season_zscore",
    "breakout_flag",
    # 37-38: V11
    "star_teammates_out",
    "game_total_line",
    # 39-53: V12 augmented features
    "days_rest",
    "minutes_load_last_7d",
    "spread_magnitude",
    "implied_team_total",
    "points_avg_last_3",
    "scoring_trend_slope",
    "deviation_from_avg_last3",
    "consecutive_games_below_avg",
    "teammate_usage_available",
    "usage_rate_last_5",
    "games_since_structural_change",
    "multi_book_line_std",
    "prop_over_streak",
    "prop_under_streak",
    "line_vs_season_avg",
]

assert len(V12_NOVEG_FEATURES) == 50, f"Expected 50 features, got {len(V12_NOVEG_FEATURES)}"


def _compute_file_sha256(file_path: str) -> str:
    """Compute SHA256 hash of a model file for integrity verification."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()[:16]


class V12FeatureAugmenter:
    """
    Batch-loads V12 augmentation features (indices 39-53) from BigQuery.

    Caches per game_date to avoid redundant queries across players on the same date.
    Queries UPCG and player_game_summary for the 15 new V12 features.
    """

    def __init__(self, project_id: str):
        self._project_id = project_id
        self._cache: Dict[str, Dict[str, Dict[str, float]]] = {}  # date -> player -> features
        self._cache_date: Optional[str] = None

    def get_v12_features(
        self,
        player_lookup: str,
        game_date: date,
        features_dict: Dict[str, float],
        line_value: Optional[float] = None,
    ) -> Dict[str, float]:
        """
        Get V12 augmentation features for a player.

        Args:
            player_lookup: Player identifier
            game_date: Game date
            features_dict: Existing feature store features (for season_avg, etc.)
            line_value: Betting line value (for line_vs_season_avg)

        Returns:
            Dict of V12 feature name -> value (indices 39-53)
        """
        date_str = str(game_date)

        # Load batch data for this date if not cached
        if self._cache_date != date_str:
            self._load_batch_data(game_date)
            self._cache_date = date_str

        player_features = self._cache.get(date_str, {}).get(player_lookup, {})

        # Compute derived features that need both store + augmented data
        season_avg = features_dict.get('points_avg_season', 10.0)

        # line_vs_season_avg: use betting line (from coordinator) minus season avg
        if line_value is not None and line_value > 0:
            line_vs_season_avg = float(line_value) - float(season_avg)
        else:
            line_vs_season_avg = 0.0

        # Merge with defaults for any missing features
        from shared.ml.feature_contract import FEATURE_DEFAULTS

        result = {
            'days_rest': player_features.get('days_rest', FEATURE_DEFAULTS.get('days_rest', 1.0)),
            'minutes_load_last_7d': player_features.get('minutes_load_last_7d', FEATURE_DEFAULTS.get('minutes_load_last_7d', 80.0)),
            'spread_magnitude': player_features.get('spread_magnitude', FEATURE_DEFAULTS.get('spread_magnitude', 5.0)),
            'implied_team_total': player_features.get('implied_team_total', FEATURE_DEFAULTS.get('implied_team_total', 112.0)),
            'points_avg_last_3': player_features.get('points_avg_last_3', FEATURE_DEFAULTS.get('points_avg_last_3', 10.0)),
            'scoring_trend_slope': player_features.get('scoring_trend_slope', FEATURE_DEFAULTS.get('scoring_trend_slope', 0.0)),
            'deviation_from_avg_last3': player_features.get('deviation_from_avg_last3', FEATURE_DEFAULTS.get('deviation_from_avg_last3', 0.0)),
            'consecutive_games_below_avg': player_features.get('consecutive_games_below_avg', FEATURE_DEFAULTS.get('consecutive_games_below_avg', 0.0)),
            'teammate_usage_available': 0.0,  # Dead feature (always 0)
            'usage_rate_last_5': player_features.get('usage_rate_last_5', FEATURE_DEFAULTS.get('usage_rate_last_5', 20.0)),
            'games_since_structural_change': player_features.get('games_since_structural_change', FEATURE_DEFAULTS.get('games_since_structural_change', 30.0)),
            'multi_book_line_std': 0.5,  # Dead feature (default 0.5)
            'prop_over_streak': player_features.get('prop_over_streak', 0.0),
            'prop_under_streak': player_features.get('prop_under_streak', 0.0),
            'line_vs_season_avg': line_vs_season_avg,
        }
        return result

    def _load_batch_data(self, game_date: date):
        """Load UPCG + player stats data for all players on a game date."""
        from shared.clients import get_bigquery_client

        date_str = str(game_date)
        client = get_bigquery_client(self._project_id)

        # Initialize cache for this date
        self._cache[date_str] = {}

        # Clear old dates from cache (keep only current)
        old_dates = [d for d in self._cache if d != date_str]
        for d in old_dates:
            del self._cache[d]

        load_start = time.time()

        # Query 1: UPCG data (days_rest, minutes_load, spread, total, streaks)
        try:
            self._load_upcg_data(client, game_date, date_str)
        except Exception as e:
            logger.warning(f"V12 UPCG query failed for {date_str}: {e}")

        # Query 2: Player stats (scoring trends, usage, structural changes)
        try:
            self._load_stats_data(client, game_date, date_str)
        except Exception as e:
            logger.warning(f"V12 stats query failed for {date_str}: {e}")

        load_duration = time.time() - load_start
        player_count = len(self._cache.get(date_str, {}))
        logger.info(f"V12 augmentation loaded for {date_str}: {player_count} players in {load_duration:.2f}s")

    def _load_upcg_data(self, client, game_date: date, date_str: str):
        """Load UPCG features: days_rest, minutes_load, spread/total, streaks."""
        query = f"""
        SELECT
            player_lookup,
            COALESCE(days_rest, 1) as days_rest,
            COALESCE(minutes_in_last_7_days, 80.0) as minutes_load_last_7d,
            COALESCE(game_spread, 0.0) as game_spread,
            COALESCE(game_total, 224.0) as game_total,
            COALESCE(home_game, FALSE) as home_game,
            COALESCE(prop_over_streak, 0) as prop_over_streak,
            COALESCE(prop_under_streak, 0) as prop_under_streak
        FROM `{self._project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date = '{date_str}'
        """
        rows = client.query(query).result()

        for row in rows:
            player = row['player_lookup']
            spread = float(row['game_spread'])
            total = float(row['game_total'])
            is_home = bool(row['home_game'])

            if is_home:
                implied_tt = (total - spread) / 2.0
            else:
                implied_tt = (total + spread) / 2.0

            if player not in self._cache[date_str]:
                self._cache[date_str][player] = {}

            self._cache[date_str][player].update({
                'days_rest': float(row['days_rest']),
                'minutes_load_last_7d': float(row['minutes_load_last_7d']),
                'spread_magnitude': abs(spread),
                'implied_team_total': implied_tt,
                'prop_over_streak': float(row['prop_over_streak']),
                'prop_under_streak': float(row['prop_under_streak']),
            })

    def _load_stats_data(self, client, game_date: date, date_str: str):
        """Load player stats features: scoring trends, usage, structural changes."""
        lookback_date = (game_date - timedelta(days=60)).isoformat()

        query = f"""
        WITH target_players AS (
            SELECT DISTINCT player_lookup
            FROM `{self._project_id}.nba_analytics.upcoming_player_game_context`
            WHERE game_date = '{date_str}'
        ),
        all_games AS (
            SELECT
                pgs.player_lookup,
                pgs.game_date,
                pgs.points,
                pgs.usage_rate,
                pgs.team_abbr
            FROM `{self._project_id}.nba_analytics.player_game_summary` pgs
            JOIN target_players tp ON pgs.player_lookup = tp.player_lookup
            WHERE pgs.game_date BETWEEN '{lookback_date}' AND '{date_str}'
              AND pgs.points IS NOT NULL
              AND pgs.minutes_played > 0
            ORDER BY pgs.player_lookup, pgs.game_date
        ),
        season_stats AS (
            SELECT
                player_lookup,
                AVG(points) as season_avg,
                STDDEV(points) as season_std
            FROM all_games
            GROUP BY player_lookup
        ),
        per_game AS (
            SELECT
                ag.player_lookup,
                ag.game_date,
                ag.points,
                ag.usage_rate,
                ag.team_abbr,
                ss.season_avg,
                ss.season_std,
                LAG(ag.game_date) OVER (PARTITION BY ag.player_lookup ORDER BY ag.game_date) as prev_game_date,
                LAG(ag.team_abbr) OVER (PARTITION BY ag.player_lookup ORDER BY ag.game_date) as prev_team_abbr,
                ARRAY_AGG(ag.points) OVER (
                    PARTITION BY ag.player_lookup ORDER BY ag.game_date
                    ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
                ) as prev_points,
                ARRAY_AGG(ag.usage_rate) OVER (
                    PARTITION BY ag.player_lookup ORDER BY ag.game_date
                    ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
                ) as prev_usage_rates
            FROM all_games ag
            JOIN season_stats ss ON ag.player_lookup = ss.player_lookup
        )
        SELECT *
        FROM per_game
        WHERE game_date = '{date_str}'
        """
        rows = client.query(query).result()

        for row in rows:
            player = row['player_lookup']
            prev_points = list(row['prev_points']) if row['prev_points'] else []
            prev_usage = list(row['prev_usage_rates']) if row['prev_usage_rates'] else []
            season_avg = float(row['season_avg']) if row['season_avg'] is not None else 10.0
            season_std = float(row['season_std']) if row['season_std'] is not None and row['season_std'] > 0 else 5.0

            # points_avg_last_3
            if len(prev_points) >= 2:
                last_3 = prev_points[-3:] if len(prev_points) >= 3 else prev_points
                points_avg_last_3 = float(np.mean(last_3))
            else:
                points_avg_last_3 = season_avg

            # scoring_trend_slope: OLS on last 7, need at least 4
            recent_7 = prev_points[-7:] if len(prev_points) >= 4 else None
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

            # deviation_from_avg_last3
            deviation_from_avg_last3 = (points_avg_last_3 - season_avg) / season_std

            # consecutive_games_below_avg
            consecutive_below = 0
            for pts in reversed(prev_points):
                if pts < season_avg:
                    consecutive_below += 1
                else:
                    break

            # usage_rate_last_5
            valid_usage = [u for u in prev_usage if u is not None]
            if len(valid_usage) >= 3:
                usage_rate_last_5 = float(np.mean(valid_usage[-5:]))
            else:
                usage_rate_last_5 = 20.0

            # games_since_structural_change
            games_since_change = 30.0
            prev_date = row['prev_game_date']
            prev_team = row['prev_team_abbr']
            current_team = row['team_abbr']

            if prev_date is not None and prev_team is not None:
                days_gap = (game_date - prev_date).days if hasattr(prev_date, 'days') else (game_date - prev_date.date() if hasattr(prev_date, 'date') else 30)
                try:
                    days_gap = (game_date - prev_date).days
                except TypeError:
                    from datetime import datetime as dt
                    if hasattr(prev_date, 'date'):
                        days_gap = (game_date - prev_date.date()).days
                    else:
                        days_gap = (game_date - dt.strptime(str(prev_date), '%Y-%m-%d').date()).days

                if current_team != prev_team:
                    games_since_change = 0.0
                elif days_gap > 14:
                    games_since_change = 0.0
                else:
                    games_since_change = min(float(len(prev_points)), 30.0)

            if player not in self._cache[date_str]:
                self._cache[date_str][player] = {}

            self._cache[date_str][player].update({
                'points_avg_last_3': points_avg_last_3,
                'scoring_trend_slope': scoring_trend_slope,
                'deviation_from_avg_last3': float(deviation_from_avg_last3),
                'consecutive_games_below_avg': float(consecutive_below),
                'usage_rate_last_5': usage_rate_last_5,
                'games_since_structural_change': float(games_since_change),
            })


class CatBoostV12:
    """
    CatBoost V12 - Vegas-Free 50-Feature Model

    Independent of market lines, generates predictions using player performance,
    matchup context, and augmented features. Builds its own 50-feature vector
    from the feature store (35 features) + batch-loaded V12 features (15 features).
    """

    SYSTEM_ID = "catboost_v12"
    FEATURE_COUNT = 50

    def __init__(self, model_path: Optional[str] = None):
        self.model = None
        self._model_path = None
        self._model_file_name = None
        self._model_sha256 = None
        self._model_version = None
        self._augmenter: Optional[V12FeatureAugmenter] = None

        if model_path:
            self._load_model_from_path(model_path)
        else:
            self._load_model_from_default_location()

    @property
    def system_id(self) -> str:
        return self.SYSTEM_ID

    @property
    def model_version(self) -> str:
        return self._model_version or "v12_unknown"

    def _get_augmenter(self) -> V12FeatureAugmenter:
        """Lazy-load the feature augmenter."""
        if self._augmenter is None:
            from shared.config.gcp_config import get_project_id
            self._augmenter = V12FeatureAugmenter(get_project_id())
        return self._augmenter

    def _load_model_from_default_location(self):
        """Load V12 model: env var first, then local, then default GCS."""
        import catboost as cb

        # Priority 1: CATBOOST_V12_MODEL_PATH env var
        env_path = os.environ.get('CATBOOST_V12_MODEL_PATH')
        if env_path:
            logger.info(f"Loading CatBoost V12 from env var: {env_path}")
            self._load_model_from_path(env_path)
            return

        # Priority 2: Local models directory
        models_dir = Path(__file__).parent.parent.parent.parent / "models"
        model_files = list(models_dir.glob("catboost_v9_50f_noveg*.cbm")) + \
                      list(models_dir.glob("catboost_v12*.cbm"))

        if model_files:
            model_path = sorted(model_files)[-1]
            logger.info(f"Loading CatBoost V12 from local: {model_path}")
            self.model = cb.CatBoostRegressor()
            self.model.load_model(str(model_path))
            self._model_path = str(model_path)
            self._model_file_name = model_path.name
            self._model_sha256 = _compute_file_sha256(str(model_path))
            self._model_version = f"v12_{model_path.stem.split('train')[-1]}" if 'train' in model_path.stem else "v12_local"
            logger.info(
                f"CatBoost V12 loaded: file={self._model_file_name} "
                f"version={self._model_version} sha256={self._model_sha256}"
            )
            return

        # Priority 3: Default GCS path
        logger.info(f"No env var or local V12 model, loading from default GCS: {DEFAULT_MODEL_GCS}")
        self._load_model_from_path(DEFAULT_MODEL_GCS)

    def _load_model_from_path(self, model_path: str):
        """Load V12 model from explicit path (local or GCS)."""
        import catboost as cb

        logger.info(f"Loading CatBoost V12 from: {model_path}")

        if model_path.startswith("gs://"):
            from shared.clients import get_storage_client
            parts = model_path.replace("gs://", "").split("/", 1)
            bucket_name, blob_path = parts[0], parts[1]

            client = get_storage_client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(blob_path)
            local_path = "/tmp/catboost_v12.cbm"
            blob.download_to_filename(local_path)
            logger.info(f"Downloaded V12 model from GCS to {local_path}")

            self.model = cb.CatBoostRegressor()
            self.model.load_model(local_path)
            self._model_file_name = Path(blob_path).name
            self._model_sha256 = _compute_file_sha256(local_path)
        else:
            self.model = cb.CatBoostRegressor()
            self.model.load_model(model_path)
            self._model_file_name = Path(model_path).name
            self._model_sha256 = _compute_file_sha256(model_path)

        self._model_path = model_path
        # Derive version from filename
        stem = Path(self._model_file_name).stem
        if 'train' in stem:
            self._model_version = f"v12_{stem.split('train')[-1]}"
        else:
            self._model_version = f"v12_{stem}"

        logger.info(
            f"CatBoost V12 loaded: file={self._model_file_name} "
            f"version={self._model_version} sha256={self._model_sha256}"
        )

    def predict(
        self,
        player_lookup: str,
        features: Dict,
        betting_line: Optional[float] = None,
        game_date: Optional[date] = None,
        **kwargs,
    ) -> Dict:
        """
        Generate prediction using CatBoost V12 model.

        Args:
            player_lookup: Player identifier
            features: Feature store features dict (with feature arrays)
            betting_line: Current over/under line
            game_date: Game date (for V12 augmentation queries)

        Returns:
            Dict with predicted_points, confidence_score, recommendation, metadata
        """
        if self.model is None:
            raise ModelLoadError("CatBoost V12 model is not loaded")

        # Build 50-feature vector
        feature_vector = self._prepare_feature_vector(
            player_lookup=player_lookup,
            features=features,
            betting_line=betting_line,
            game_date=game_date,
        )

        if feature_vector is None:
            return self._fallback_prediction(player_lookup, features, betting_line)

        # Make prediction
        try:
            raw_prediction = float(self.model.predict(feature_vector)[0])
        except Exception as e:
            logger.error(f"CatBoost V12 prediction failed: {e}", exc_info=True)
            return self._fallback_prediction(player_lookup, features, betting_line)

        # Clamp to reasonable range
        predicted_points = max(0, min(60, raw_prediction))

        # Calculate confidence
        confidence = self._calculate_confidence(features)

        # Generate recommendation
        recommendation = self._generate_recommendation(
            predicted_points, betting_line, confidence
        )

        # Warnings
        warnings = []
        if features.get('early_season_flag'):
            warnings.append('EARLY_SEASON')
        if features.get('feature_quality_score', 100) < 70:
            warnings.append('LOW_QUALITY_SCORE')

        return {
            'system_id': self.SYSTEM_ID,
            'model_version': self._model_version,
            'predicted_points': round(predicted_points, 2),
            'confidence_score': round(confidence, 2),
            'recommendation': recommendation,
            'model_type': 'catboost_v12_noveg',
            'feature_count': self.FEATURE_COUNT,
            'feature_version': features.get('feature_version'),
            'feature_quality_score': features.get('feature_quality_score'),
            'feature_data_source': features.get('data_source'),
            'early_season_flag': features.get('early_season_flag', False),
            'prediction_error_code': None,
            'prediction_warnings': warnings if warnings else None,
            'raw_confidence_score': round(confidence / 100, 3),
            'calibration_method': 'none',
            'metadata': {
                'model_version': self._model_version,
                'system_id': self.SYSTEM_ID,
                'model_file_name': self._model_file_name,
                'model_sha256': self._model_sha256,
            },
        }

    def _prepare_feature_vector(
        self,
        player_lookup: str,
        features: Dict,
        betting_line: Optional[float],
        game_date: Optional[date],
    ) -> Optional[np.ndarray]:
        """Build 50-feature vector from feature store + V12 augmentation."""
        try:
            # Extract base features from feature store (by name, not position)
            season_avg = features.get('points_avg_season', 10.0)

            # Get V12 augmented features
            v12_features = {}
            if game_date is not None:
                try:
                    augmenter = self._get_augmenter()
                    v12_features = augmenter.get_v12_features(
                        player_lookup=player_lookup,
                        game_date=game_date,
                        features_dict=features,
                        line_value=betting_line,
                    )
                except Exception as e:
                    logger.warning(f"V12 augmentation failed for {player_lookup}: {e}")

            # If no augmentation, compute line_vs_season_avg directly
            if 'line_vs_season_avg' not in v12_features:
                if betting_line is not None and betting_line > 0:
                    v12_features['line_vs_season_avg'] = float(betting_line) - float(season_avg)
                else:
                    v12_features['line_vs_season_avg'] = 0.0

            # Merge all feature sources into one dict
            all_features = {}

            # Feature store features (by name)
            for name in V12_NOVEG_FEATURES[:35]:  # 0-24 + 29-38 (35 features from store)
                val = features.get(name)
                if val is not None:
                    all_features[name] = float(val)
                # Shot zone features can be NaN (CatBoost handles natively)
                elif name in ('pct_paint', 'pct_mid_range', 'pct_three'):
                    all_features[name] = np.nan

            # V12 augmented features (indices 39-53)
            all_features.update(v12_features)

            # Build vector in exact order
            from shared.ml.feature_contract import FEATURE_DEFAULTS
            vector = []
            for name in V12_NOVEG_FEATURES:
                if name in all_features and all_features[name] is not None:
                    vector.append(float(all_features[name]))
                elif name in ('pct_paint', 'pct_mid_range', 'pct_three'):
                    vector.append(np.nan)  # CatBoost handles NaN natively
                elif name in FEATURE_DEFAULTS and FEATURE_DEFAULTS[name] is not None:
                    vector.append(float(FEATURE_DEFAULTS[name]))
                else:
                    vector.append(np.nan)

            vector = np.array(vector).reshape(1, -1)

            if vector.shape[1] != self.FEATURE_COUNT:
                logger.error(f"V12 feature vector has {vector.shape[1]} features, expected {self.FEATURE_COUNT}")
                return None

            return vector

        except Exception as e:
            logger.error(f"Error preparing V12 feature vector: {e}", exc_info=True)
            return None

    def _calculate_confidence(self, features: Dict) -> float:
        """Calculate confidence score for V12 prediction."""
        confidence = 75.0

        quality = features.get('feature_quality_score', 80)
        if quality >= 90:
            confidence += 10
        elif quality >= 80:
            confidence += 7
        elif quality >= 70:
            confidence += 5
        else:
            confidence += 2

        std_dev = features.get('points_std_last_10', 5)
        if std_dev < 4:
            confidence += 10
        elif std_dev < 6:
            confidence += 7
        elif std_dev < 8:
            confidence += 5
        else:
            confidence += 2

        return max(0, min(100, confidence))

    def _generate_recommendation(
        self,
        predicted_points: float,
        betting_line: Optional[float],
        confidence: float,
    ) -> str:
        """Generate betting recommendation."""
        if betting_line is None:
            return 'NO_LINE'
        if confidence < 60:
            return 'PASS'

        edge = predicted_points - betting_line
        min_edge = 1.0

        if edge >= min_edge:
            return 'OVER'
        elif edge <= -min_edge:
            return 'UNDER'
        else:
            return 'PASS'

    def _fallback_prediction(
        self,
        player_lookup: str,
        features: Dict,
        betting_line: Optional[float],
    ) -> Dict:
        """Fallback for feature/prediction failures."""
        logger.warning(f"V12 FALLBACK for {player_lookup}")

        season_avg = features.get('points_avg_season', 10.0)
        last_5 = features.get('points_avg_last_5', season_avg)
        last_10 = features.get('points_avg_last_10', season_avg)
        predicted = 0.4 * last_5 + 0.35 * last_10 + 0.25 * season_avg

        return {
            'system_id': self.SYSTEM_ID,
            'model_version': self._model_version or 'v12_unknown',
            'predicted_points': round(predicted, 2),
            'confidence_score': 50.0,
            'recommendation': 'PASS',
            'model_type': 'fallback',
            'feature_count': self.FEATURE_COUNT,
            'feature_version': features.get('feature_version'),
            'feature_quality_score': features.get('feature_quality_score'),
            'feature_data_source': features.get('data_source'),
            'early_season_flag': features.get('early_season_flag', False),
            'prediction_error_code': 'V12_FALLBACK',
            'prediction_warnings': ['FALLBACK_USED'],
            'raw_confidence_score': 0.5,
            'calibration_method': 'none',
            'metadata': {
                'model_version': self._model_version or 'v12_unknown',
                'system_id': self.SYSTEM_ID,
                'model_file_name': self._model_file_name,
                'model_sha256': self._model_sha256,
            },
        }

    def get_model_info(self) -> Dict:
        """Return V12 model information for health checks."""
        return {
            "system_id": self.SYSTEM_ID,
            "model_version": self._model_version,
            "model_path": self._model_path or 'unknown',
            "model_file_name": self._model_file_name,
            "model_sha256": self._model_sha256,
            "feature_count": self.FEATURE_COUNT,
            "status": "loaded" if self.model is not None else "not_loaded",
        }
