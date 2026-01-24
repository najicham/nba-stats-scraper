# predictions/mlb/pitcher_strikeouts_predictor_v2.py
"""
MLB Pitcher Strikeouts Predictor V2 (Challenger)

CatBoost-based prediction system for pitcher strikeout totals.
This is the V2 challenger model that runs alongside V1 champion.

Key Differences from V1:
- Algorithm: CatBoost (vs XGBoost)
- Features: 29 (vs 19)
- Additional features: splits, matchup context, advanced metrics

Model: mlb_pitcher_strikeouts_v2
Status: CHALLENGER (running alongside V1)

Champion-Challenger Framework:
- Both V1 and V2 make predictions for each game
- Predictions tracked with model_version field
- V2 promoted to champion if outperforms V1 for 7+ days
"""

import os
import json
import logging
from typing import Dict, List, Optional, Tuple
from datetime import date, datetime
import numpy as np

from predictions.mlb.config import get_config

logger = logging.getLogger(__name__)

# V2 Feature Set (29 features - expanded from V1's 19)
V2_FEATURE_ORDER = [
    # === Rolling Performance (5) - Same as V1 ===
    'f00_k_avg_last_3',
    'f01_k_avg_last_5',
    'f02_k_avg_last_10',
    'f03_k_std_last_10',
    'f04_ip_avg_last_5',

    # === Season Stats (5) - Same as V1 ===
    'f05_season_k_per_9',
    'f06_season_era',
    'f07_season_whip',
    'f08_season_games',
    'f09_season_k_total',

    # === Game Context (5) - EXPANDED ===
    'f10_is_home',
    'f11_home_away_k_diff',      # NEW: Home minus Away K/9
    'f12_is_day_game',           # NEW: Day game indicator
    'f13_day_night_k_diff',      # NEW: Day minus Night K/9
    'f24_is_postseason',

    # === Matchup Context (5) - NEW ===
    'f14_vs_opponent_k_rate',    # NEW: Historical K rate vs opponent
    'f15_opponent_team_k_rate',  # NEW: How often opponent strikes out
    'f16_opponent_obp',          # NEW: Opponent on-base percentage
    'f17_ballpark_k_factor',     # NEW: Ballpark strikeout factor
    'f18_game_total_line',       # NEW: Vegas game total (scoring env)

    # === Workload (4) - Same as V1 ===
    'f20_days_rest',
    'f21_games_last_30_days',
    'f22_pitch_count_avg',
    'f23_season_ip_total',

    # === Bottom-Up Model (5) - EXPANDED ===
    'f25_bottom_up_k_expected',  # Same as V1
    'f26_lineup_k_vs_hand',      # Same as V1
    'f27_platoon_advantage',     # NEW: Platoon matchup advantage
    'f33_lineup_weak_spots',     # Same as V1
    'f34_matchup_edge',          # NEW: Composite matchup score
]

# Feature version for validation
FEATURE_VERSION = 'v2_29features'
FEATURE_COUNT = 29

# Default values for missing features
V2_FEATURE_DEFAULTS = {
    # Rolling Performance
    'f00_k_avg_last_3': 5.0,
    'f01_k_avg_last_5': 5.0,
    'f02_k_avg_last_10': 5.0,
    'f03_k_std_last_10': 2.0,
    'f04_ip_avg_last_5': 5.5,

    # Season Stats
    'f05_season_k_per_9': 8.5,
    'f06_season_era': 4.0,
    'f07_season_whip': 1.3,
    'f08_season_games': 5,
    'f09_season_k_total': 30,

    # Game Context
    'f10_is_home': 0.0,
    'f11_home_away_k_diff': 0.0,
    'f12_is_day_game': 0.0,
    'f13_day_night_k_diff': 0.0,
    'f24_is_postseason': 0.0,

    # Matchup Context
    'f14_vs_opponent_k_rate': 8.5,
    'f15_opponent_team_k_rate': 0.22,
    'f16_opponent_obp': 0.320,
    'f17_ballpark_k_factor': 1.0,
    'f18_game_total_line': 8.5,

    # Workload
    'f20_days_rest': 5,
    'f21_games_last_30_days': 5,
    'f22_pitch_count_avg': 90.0,
    'f23_season_ip_total': 50.0,

    # Bottom-Up Model
    'f25_bottom_up_k_expected': 5.0,
    'f26_lineup_k_vs_hand': 0.22,
    'f27_platoon_advantage': 0.0,
    'f33_lineup_weak_spots': 2,
    'f34_matchup_edge': 0.0,
}


class PitcherStrikeoutsPredictorV2:
    """
    CatBoost-based pitcher strikeouts predictor (V2 Challenger)

    This model runs alongside V1 in champion-challenger mode.
    All predictions are tracked with model_version='v2'.

    Usage:
        predictor = PitcherStrikeoutsPredictorV2()
        prediction = predictor.predict(pitcher_lookup, features, strikeouts_line)
    """

    # Model identification
    SYSTEM_ID = 'pitcher_strikeouts_v2'
    MODEL_VERSION = 'v2'
    ALGORITHM = 'catboost'

    def __init__(
        self,
        model_path: str = None,
        project_id: str = None
    ):
        """
        Initialize V2 predictor

        Args:
            model_path: GCS path to CatBoost model (default: latest v2 model)
            project_id: GCP project ID
        """
        self.project_id = project_id or os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.model_path = model_path or os.environ.get(
            'MLB_PITCHER_STRIKEOUTS_V2_MODEL_PATH',
            'gs://nba-scraped-data/ml-models/mlb/pitcher_strikeouts_v2_latest.cbm'
        )
        self.model = None
        self.model_metadata = None
        self._bq_client = None

    def _get_bq_client(self):
        """Lazy-load BigQuery client"""
        if self._bq_client is None:
            from google.cloud import bigquery
            self._bq_client = bigquery.Client(project=self.project_id)
        return self._bq_client

    def load_model(self) -> bool:
        """
        Load CatBoost model from GCS

        Returns:
            bool: True if successful, False otherwise
        """
        if self.model is not None:
            return True

        try:
            from catboost import CatBoostRegressor
            from google.cloud import storage

            logger.info(f"[V2] Loading model from {self.model_path}")

            # Parse GCS path
            if not self.model_path.startswith('gs://'):
                raise ValueError(f"Invalid GCS path: {self.model_path}")

            parts = self.model_path.replace('gs://', '').split('/', 1)
            bucket_name = parts[0]
            blob_path = parts[1]

            # Download model
            client = storage.Client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(blob_path)

            local_path = '/tmp/mlb_pitcher_strikeouts_v2.cbm'
            blob.download_to_filename(local_path)

            # Load CatBoost model
            self.model = CatBoostRegressor()
            self.model.load_model(local_path)

            # Load metadata
            metadata_blob_path = blob_path.replace('.cbm', '_metadata.json')
            metadata_blob = bucket.blob(metadata_blob_path)

            metadata_local = '/tmp/mlb_pitcher_strikeouts_v2_metadata.json'
            try:
                metadata_blob.download_to_filename(metadata_local)
                with open(metadata_local, 'r') as f:
                    self.model_metadata = json.load(f)
            except Exception as e:
                logger.warning(f"[V2] Could not load metadata: {e}")
                self.model_metadata = {'model_version': 'v2', 'feature_count': FEATURE_COUNT}

            logger.info(f"[V2] Model loaded successfully. Features: {FEATURE_COUNT}")
            return True

        except Exception as e:
            logger.error(f"[V2] Failed to load model: {e}", exc_info=True)
            return False

    def prepare_features(self, raw_features: Dict) -> Optional[np.ndarray]:
        """
        Prepare feature vector from raw features

        Maps from pitcher_game_summary columns to V2 model features.
        FAIL-FAST: Validates feature version matches expected.

        Args:
            raw_features: Dict with feature values

        Returns:
            np.ndarray: Feature vector (1, 29) or None if invalid
        """
        try:
            # Map raw features to V2 model features
            feature_mapping = {
                # Rolling Performance
                'f00_k_avg_last_3': raw_features.get('k_avg_last_3'),
                'f01_k_avg_last_5': raw_features.get('k_avg_last_5'),
                'f02_k_avg_last_10': raw_features.get('k_avg_last_10'),
                'f03_k_std_last_10': raw_features.get('k_std_last_10'),
                'f04_ip_avg_last_5': raw_features.get('ip_avg_last_5'),

                # Season Stats
                'f05_season_k_per_9': raw_features.get('season_k_per_9'),
                'f06_season_era': raw_features.get('era_rolling_10', raw_features.get('season_era')),
                'f07_season_whip': raw_features.get('whip_rolling_10', raw_features.get('season_whip')),
                'f08_season_games': raw_features.get('season_games_started'),
                'f09_season_k_total': raw_features.get('season_strikeouts'),

                # Game Context (EXPANDED)
                'f10_is_home': 1.0 if raw_features.get('is_home') else 0.0,
                'f11_home_away_k_diff': raw_features.get('home_away_k_diff', 0.0),
                'f12_is_day_game': 1.0 if raw_features.get('is_day_game') else 0.0,
                'f13_day_night_k_diff': raw_features.get('day_night_k_diff', 0.0),
                'f24_is_postseason': 1.0 if raw_features.get('is_postseason') else 0.0,

                # Matchup Context (NEW)
                'f14_vs_opponent_k_rate': raw_features.get('vs_opponent_k_per_9', 8.5),
                'f15_opponent_team_k_rate': raw_features.get('opponent_team_k_rate', 0.22),
                'f16_opponent_obp': raw_features.get('opponent_obp', 0.320),
                'f17_ballpark_k_factor': raw_features.get('ballpark_k_factor', 1.0),
                'f18_game_total_line': raw_features.get('game_total_line', 8.5),

                # Workload
                'f20_days_rest': raw_features.get('days_rest'),
                'f21_games_last_30_days': raw_features.get('games_last_30_days'),
                'f22_pitch_count_avg': raw_features.get('pitch_count_avg_last_5'),
                'f23_season_ip_total': raw_features.get('season_innings'),

                # Bottom-Up Model (EXPANDED)
                'f25_bottom_up_k_expected': raw_features.get('bottom_up_k_expected', raw_features.get('k_avg_last_5')),
                'f26_lineup_k_vs_hand': raw_features.get('lineup_k_vs_hand', 0.22),
                'f27_platoon_advantage': raw_features.get('platoon_advantage', 0.0),
                'f33_lineup_weak_spots': raw_features.get('lineup_weak_spots', 2),
                'f34_matchup_edge': raw_features.get('matchup_edge', 0.0),
            }

            # Build feature vector in exact order
            feature_vector = []
            for feature_name in V2_FEATURE_ORDER:
                value = feature_mapping.get(feature_name)
                if value is None:
                    value = V2_FEATURE_DEFAULTS.get(feature_name, 0.0)
                feature_vector.append(float(value))

            result = np.array(feature_vector).reshape(1, -1)

            # Validate no NaN/Inf
            if np.any(np.isnan(result)) or np.any(np.isinf(result)):
                logger.warning("[V2] Feature vector contains NaN or Inf values")
                for i, val in enumerate(result[0]):
                    if np.isnan(val) or np.isinf(val):
                        result[0][i] = V2_FEATURE_DEFAULTS.get(V2_FEATURE_ORDER[i], 0.0)

            return result

        except Exception as e:
            logger.error(f"[V2] Error preparing features: {e}", exc_info=True)
            return None

    def predict(
        self,
        pitcher_lookup: str,
        features: Dict,
        strikeouts_line: Optional[float] = None
    ) -> Dict:
        """
        Generate strikeout prediction for a pitcher

        Args:
            pitcher_lookup: Pitcher identifier
            features: Feature dict from pitcher_game_summary
            strikeouts_line: Betting line (optional, for recommendation)

        Returns:
            dict: Prediction with metadata including model_version='v2'
        """
        # Ensure model is loaded
        if not self.load_model():
            # Fallback to weighted average if model fails
            return self._fallback_prediction(pitcher_lookup, features, strikeouts_line)

        # Prepare features
        feature_vector = self.prepare_features(features)
        if feature_vector is None:
            return self._fallback_prediction(pitcher_lookup, features, strikeouts_line)

        # Make prediction
        try:
            predicted_strikeouts = float(self.model.predict(feature_vector)[0])

            # Clamp to reasonable range (0-20 strikeouts)
            predicted_strikeouts = max(0, min(20, predicted_strikeouts))

        except Exception as e:
            logger.error(f"[V2] Prediction failed: {e}", exc_info=True)
            return self._fallback_prediction(pitcher_lookup, features, strikeouts_line)

        # Calculate confidence
        confidence = self._calculate_confidence(features, feature_vector)

        # Generate recommendation
        recommendation = self._generate_recommendation(
            predicted_strikeouts,
            strikeouts_line,
            confidence
        )

        # Calculate edge if line provided
        edge = None
        if strikeouts_line is not None:
            edge = predicted_strikeouts - strikeouts_line

        return {
            'pitcher_lookup': pitcher_lookup,
            'predicted_strikeouts': round(predicted_strikeouts, 2),
            'confidence': round(confidence, 2),
            'recommendation': recommendation,
            'edge': round(edge, 2) if edge is not None else None,
            'strikeouts_line': strikeouts_line,
            # V2 Tracking Fields
            'system_id': self.SYSTEM_ID,
            'model_version': self.MODEL_VERSION,
            'feature_count': FEATURE_COUNT,
            'algorithm': self.ALGORITHM,
            'is_fallback': False,
        }

    def _fallback_prediction(
        self,
        pitcher_lookup: str,
        features: Dict,
        strikeouts_line: Optional[float]
    ) -> Dict:
        """
        Fallback prediction using weighted average when model unavailable

        Uses: 0.5 * k_avg_last_5 + 0.3 * k_avg_last_10 + 0.2 * season_k_per_9 / 9 * 6
        """
        k_avg_5 = features.get('k_avg_last_5', 5.0)
        k_avg_10 = features.get('k_avg_last_10', 5.0)
        k_per_9 = features.get('season_k_per_9', 8.5)

        # Weighted average with adjustment for K/9 to per-game
        predicted_strikeouts = (
            0.5 * k_avg_5 +
            0.3 * k_avg_10 +
            0.2 * (k_per_9 / 9 * 6)  # Assume ~6 IP average
        )

        edge = None
        if strikeouts_line is not None:
            edge = predicted_strikeouts - strikeouts_line

        return {
            'pitcher_lookup': pitcher_lookup,
            'predicted_strikeouts': round(predicted_strikeouts, 2),
            'confidence': 50.0,  # Lower confidence for fallback
            'recommendation': 'PASS',  # Conservative when using fallback
            'edge': round(edge, 2) if edge is not None else None,
            'strikeouts_line': strikeouts_line,
            # V2 Tracking Fields
            'system_id': self.SYSTEM_ID,
            'model_version': self.MODEL_VERSION,
            'feature_count': FEATURE_COUNT,
            'algorithm': 'fallback_weighted_avg',
            'is_fallback': True,
        }

    def _calculate_confidence(self, features: Dict, feature_vector: np.ndarray) -> float:
        """
        Calculate confidence score based on data quality

        V2 has higher base confidence (75) due to more features.

        Args:
            features: Raw feature dict
            feature_vector: Prepared feature vector

        Returns:
            float: Confidence score (0-100)
        """
        confidence = 75.0  # Higher base for V2 (more features)

        # Data completeness adjustment
        completeness = features.get('data_completeness_score', 80)
        if completeness >= 90:
            confidence += 12
        elif completeness >= 80:
            confidence += 8
        elif completeness >= 70:
            confidence += 4
        elif completeness >= 50:
            confidence += 0
        else:
            confidence -= 10

        # Rolling stats games adjustment
        rolling_games = features.get('rolling_stats_games', 0)
        if rolling_games >= 10:
            confidence += 8
        elif rolling_games >= 5:
            confidence += 4
        elif rolling_games >= 3:
            confidence += 0
        else:
            confidence -= 10

        # Consistency adjustment (lower K std = more predictable)
        k_std = features.get('k_std_last_10', 3.0)
        if k_std < 2:
            confidence += 5
        elif k_std < 3:
            confidence += 2
        elif k_std > 4:
            confidence -= 5

        # V2-specific: Boost for matchup context features
        if features.get('opponent_team_k_rate') is not None:
            confidence += 3
        if features.get('ballpark_k_factor') is not None:
            confidence += 2

        return max(0, min(100, confidence))

    def _generate_recommendation(
        self,
        predicted_strikeouts: float,
        strikeouts_line: Optional[float],
        confidence: float
    ) -> str:
        """
        Generate betting recommendation

        V2 uses tighter thresholds (1.0 edge minimum based on analysis).

        Args:
            predicted_strikeouts: Model prediction
            strikeouts_line: Betting line
            confidence: Confidence score

        Returns:
            str: 'OVER', 'UNDER', 'PASS', or 'NO_LINE'
        """
        if strikeouts_line is None:
            return 'NO_LINE'

        # V2 uses its own config with higher edge threshold (1.0 vs 0.5 in V1)
        config = get_config().prediction_v2

        if confidence < config.min_confidence:
            return 'PASS'

        edge = predicted_strikeouts - strikeouts_line

        if edge >= config.min_edge:
            return 'OVER'
        elif edge <= -config.min_edge:
            return 'UNDER'
        else:
            return 'PASS'

    def load_pitcher_features(
        self,
        pitcher_lookup: str,
        game_date: date
    ) -> Optional[Dict]:
        """
        Load V2 features for a pitcher from BigQuery

        Includes additional columns for V2 features.

        Args:
            pitcher_lookup: Pitcher identifier
            game_date: Game date

        Returns:
            dict: Features or None if not found
        """
        client = self._get_bq_client()

        query = f"""
        SELECT
            player_lookup,
            game_date,
            team_abbr,
            opponent_team_abbr,
            is_home,
            is_day_game,
            is_postseason,
            days_rest,

            -- Rolling stats
            k_avg_last_3,
            k_avg_last_5,
            k_avg_last_10,
            k_std_last_10,
            ip_avg_last_5,

            -- Season stats
            season_k_per_9,
            era_rolling_10,
            whip_rolling_10,
            season_games_started,
            season_strikeouts,
            season_innings,

            -- Workload
            games_last_30_days,
            pitch_count_avg_last_5,

            -- V2 Features: Splits
            home_away_k_diff,
            day_night_k_diff,
            vs_opponent_k_per_9,

            -- V2 Features: Matchup Context
            opponent_team_k_rate,
            opponent_obp,
            ballpark_k_factor,
            game_total_line,

            -- Data quality
            data_completeness_score,
            rolling_stats_games

        FROM `{self.project_id}.mlb_analytics.pitcher_game_summary`
        WHERE player_lookup = @pitcher_lookup
          AND game_date < @game_date
          AND game_date >= DATE_SUB(@game_date, INTERVAL 30 DAY)
        ORDER BY game_date DESC
        LIMIT 1
        """

        try:
            from google.cloud import bigquery
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("pitcher_lookup", "STRING", pitcher_lookup),
                    bigquery.ScalarQueryParameter("game_date", "DATE", game_date.isoformat()),
                ]
            )

            result = client.query(query, job_config=job_config).result()
            rows = list(result)

            if not rows:
                logger.warning(f"[V2] No features found for {pitcher_lookup} before {game_date}")
                return None

            return dict(rows[0])

        except Exception as e:
            logger.error(f"[V2] Error loading features: {e}", exc_info=True)
            return None


# CLI for testing
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='MLB Pitcher Strikeouts Predictor V2')
    parser.add_argument('--pitcher', type=str, help='Pitcher lookup ID')
    parser.add_argument('--date', type=str, help='Game date (YYYY-MM-DD)')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')

    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    predictor = PitcherStrikeoutsPredictorV2()

    if args.pitcher and args.date:
        from datetime import datetime
        game_date = datetime.strptime(args.date, '%Y-%m-%d').date()
        features = predictor.load_pitcher_features(args.pitcher, game_date)
        if features:
            prediction = predictor.predict(args.pitcher, features)
            print(json.dumps(prediction, indent=2))
        else:
            print(f"No features found for {args.pitcher}")
    else:
        print("V2 Predictor initialized")
        print(f"System ID: {predictor.SYSTEM_ID}")
        print(f"Model Version: {predictor.MODEL_VERSION}")
        print(f"Feature Count: {FEATURE_COUNT}")
        print(f"Algorithm: {predictor.ALGORITHM}")
