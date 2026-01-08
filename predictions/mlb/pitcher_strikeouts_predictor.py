# predictions/mlb/pitcher_strikeouts_predictor.py
"""
MLB Pitcher Strikeouts Predictor

XGBoost-based prediction system for pitcher strikeout totals.
Loads trained model from GCS and generates predictions using features
from mlb_analytics.pitcher_game_summary.

Model: mlb_pitcher_strikeouts_v1
MAE: 1.71 (11% better than 1.92 baseline)
Features: 19 (rolling stats, season stats, game context)
"""

import os
import json
import logging
from typing import Dict, List, Optional, Tuple
from datetime import date, datetime
import numpy as np

logger = logging.getLogger(__name__)

# Feature order must match training exactly
FEATURE_ORDER = [
    'f00_k_avg_last_3',
    'f01_k_avg_last_5',
    'f02_k_avg_last_10',
    'f03_k_std_last_10',
    'f04_ip_avg_last_5',
    'f05_season_k_per_9',
    'f06_season_era',
    'f07_season_whip',
    'f08_season_games',
    'f09_season_k_total',
    'f10_is_home',
    'f20_days_rest',
    'f21_games_last_30_days',
    'f22_pitch_count_avg',
    'f23_season_ip_total',
    'f24_is_postseason',
    'f25_bottom_up_k_expected',
    'f26_lineup_k_vs_hand',
    'f33_lineup_weak_spots',
]

# Default values for missing features (from training script)
FEATURE_DEFAULTS = {
    'f00_k_avg_last_3': 5.0,
    'f01_k_avg_last_5': 5.0,
    'f02_k_avg_last_10': 5.0,
    'f03_k_std_last_10': 2.0,
    'f04_ip_avg_last_5': 5.5,
    'f05_season_k_per_9': 8.5,
    'f06_season_era': 4.0,
    'f07_season_whip': 1.3,
    'f08_season_games': 5,
    'f09_season_k_total': 30,
    'f10_is_home': 0.0,
    'f20_days_rest': 5,
    'f21_games_last_30_days': 5,
    'f22_pitch_count_avg': 90.0,
    'f23_season_ip_total': 50.0,
    'f24_is_postseason': 0.0,
    'f25_bottom_up_k_expected': 5.0,
    'f26_lineup_k_vs_hand': 0.22,
    'f33_lineup_weak_spots': 2,
}


class PitcherStrikeoutsPredictor:
    """
    XGBoost-based pitcher strikeouts predictor

    Usage:
        predictor = PitcherStrikeoutsPredictor()
        prediction = predictor.predict(pitcher_lookup, game_date, features)
    """

    def __init__(
        self,
        model_path: str = None,
        project_id: str = None
    ):
        """
        Initialize predictor

        Args:
            model_path: GCS path to model (default: latest v1 model)
            project_id: GCP project ID
        """
        self.project_id = project_id or os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.model_path = model_path or 'gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_20260107.json'
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
        Load XGBoost model from GCS

        Returns:
            bool: True if successful
        """
        if self.model is not None:
            return True

        try:
            import xgboost as xgb
            from google.cloud import storage

            logger.info(f"Loading model from {self.model_path}")

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

            local_path = '/tmp/mlb_pitcher_strikeouts_model.json'
            blob.download_to_filename(local_path)

            # Load model
            self.model = xgb.Booster()
            self.model.load_model(local_path)

            # Load metadata
            metadata_path = self.model_path.replace('.json', '_metadata.json')
            metadata_blob_path = blob_path.replace('.json', '_metadata.json')
            metadata_blob = bucket.blob(metadata_blob_path)

            metadata_local = '/tmp/mlb_pitcher_strikeouts_metadata.json'
            metadata_blob.download_to_filename(metadata_local)

            with open(metadata_local, 'r') as f:
                self.model_metadata = json.load(f)

            logger.info(f"Model loaded successfully. MAE: {self.model_metadata.get('test_mae', 'N/A')}")
            return True

        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            return False

    def prepare_features(self, raw_features: Dict) -> Optional[np.ndarray]:
        """
        Prepare feature vector from raw features

        Maps from pitcher_game_summary columns to model features.

        Args:
            raw_features: Dict with feature values

        Returns:
            np.ndarray: Feature vector (1, 19) or None if invalid
        """
        try:
            # Map raw features to model features
            feature_mapping = {
                'f00_k_avg_last_3': raw_features.get('k_avg_last_3'),
                'f01_k_avg_last_5': raw_features.get('k_avg_last_5'),
                'f02_k_avg_last_10': raw_features.get('k_avg_last_10'),
                'f03_k_std_last_10': raw_features.get('k_std_last_10'),
                'f04_ip_avg_last_5': raw_features.get('ip_avg_last_5'),
                'f05_season_k_per_9': raw_features.get('season_k_per_9'),
                'f06_season_era': raw_features.get('era_rolling_10', raw_features.get('season_era')),
                'f07_season_whip': raw_features.get('whip_rolling_10', raw_features.get('season_whip')),
                'f08_season_games': raw_features.get('season_games_started'),
                'f09_season_k_total': raw_features.get('season_strikeouts'),
                'f10_is_home': 1.0 if raw_features.get('is_home') else 0.0,
                'f20_days_rest': raw_features.get('days_rest'),
                'f21_games_last_30_days': raw_features.get('games_last_30_days'),
                'f22_pitch_count_avg': raw_features.get('pitch_count_avg_last_5'),
                'f23_season_ip_total': raw_features.get('season_innings'),
                'f24_is_postseason': 1.0 if raw_features.get('is_postseason') else 0.0,
                'f25_bottom_up_k_expected': raw_features.get('bottom_up_k_expected', raw_features.get('k_avg_last_5')),
                'f26_lineup_k_vs_hand': raw_features.get('lineup_k_vs_hand', 0.22),
                'f33_lineup_weak_spots': raw_features.get('lineup_weak_spots', 2),
            }

            # Build feature vector in exact order
            feature_vector = []
            for feature_name in FEATURE_ORDER:
                value = feature_mapping.get(feature_name)
                if value is None:
                    value = FEATURE_DEFAULTS.get(feature_name, 0.0)
                feature_vector.append(float(value))

            result = np.array(feature_vector).reshape(1, -1)

            # Validate
            if np.any(np.isnan(result)) or np.any(np.isinf(result)):
                logger.warning("Feature vector contains NaN or Inf values")
                # Replace with defaults
                for i, val in enumerate(result[0]):
                    if np.isnan(val) or np.isinf(val):
                        result[0][i] = FEATURE_DEFAULTS.get(FEATURE_ORDER[i], 0.0)

            return result

        except Exception as e:
            logger.error(f"Error preparing features: {e}")
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
            dict: Prediction with metadata
        """
        # Ensure model is loaded
        if not self.load_model():
            return {
                'pitcher_lookup': pitcher_lookup,
                'predicted_strikeouts': None,
                'confidence': 0.0,
                'recommendation': 'ERROR',
                'error': 'Failed to load model'
            }

        # Prepare features
        feature_vector = self.prepare_features(features)
        if feature_vector is None:
            return {
                'pitcher_lookup': pitcher_lookup,
                'predicted_strikeouts': None,
                'confidence': 0.0,
                'recommendation': 'ERROR',
                'error': 'Failed to prepare features'
            }

        # Make prediction
        try:
            import xgboost as xgb
            dmatrix = xgb.DMatrix(feature_vector, feature_names=FEATURE_ORDER)
            predicted_strikeouts = float(self.model.predict(dmatrix)[0])

            # Clamp to reasonable range (0-20 strikeouts)
            predicted_strikeouts = max(0, min(20, predicted_strikeouts))

        except Exception as e:
            logger.error(f"Prediction failed: {e}")
            return {
                'pitcher_lookup': pitcher_lookup,
                'predicted_strikeouts': None,
                'confidence': 0.0,
                'recommendation': 'ERROR',
                'error': str(e)
            }

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
            'model_version': self.model_metadata.get('model_id', 'unknown') if self.model_metadata else 'unknown',
            'model_mae': self.model_metadata.get('test_mae') if self.model_metadata else None
        }

    def _calculate_confidence(self, features: Dict, feature_vector: np.ndarray) -> float:
        """
        Calculate confidence score based on data quality

        Args:
            features: Raw feature dict
            feature_vector: Prepared feature vector

        Returns:
            float: Confidence score (0-100)
        """
        confidence = 70.0  # Base ML confidence

        # Data completeness adjustment
        completeness = features.get('data_completeness_score', 80)
        if completeness >= 90:
            confidence += 15
        elif completeness >= 80:
            confidence += 10
        elif completeness >= 70:
            confidence += 5
        elif completeness >= 50:
            confidence += 0
        else:
            confidence -= 10

        # Rolling stats games adjustment
        rolling_games = features.get('rolling_stats_games', 0)
        if rolling_games >= 10:
            confidence += 10
        elif rolling_games >= 5:
            confidence += 5
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

        return max(0, min(100, confidence))

    def _generate_recommendation(
        self,
        predicted_strikeouts: float,
        strikeouts_line: Optional[float],
        confidence: float
    ) -> str:
        """
        Generate betting recommendation

        Args:
            predicted_strikeouts: Model prediction
            strikeouts_line: Betting line
            confidence: Confidence score

        Returns:
            str: 'OVER', 'UNDER', 'PASS', or 'NO_LINE'
        """
        if strikeouts_line is None:
            return 'NO_LINE'

        if confidence < 60:
            return 'PASS'

        edge = predicted_strikeouts - strikeouts_line

        # Minimum edge threshold (0.5 K for strikeouts)
        min_edge = 0.5

        if edge >= min_edge:
            return 'OVER'
        elif edge <= -min_edge:
            return 'UNDER'
        else:
            return 'PASS'

    def load_pitcher_features(
        self,
        pitcher_lookup: str,
        game_date: date
    ) -> Optional[Dict]:
        """
        Load features for a pitcher from BigQuery

        Args:
            pitcher_lookup: Pitcher identifier
            game_date: Game date

        Returns:
            dict: Features or None if not found
        """
        client = self._get_bq_client()

        # Query the most recent features before game_date
        query = f"""
        SELECT
            player_lookup,
            game_date,
            team_abbr,
            opponent_team_abbr,
            is_home,
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
                logger.warning(f"No features found for {pitcher_lookup} before {game_date}")
                return None

            row = rows[0]
            return dict(row)

        except Exception as e:
            logger.error(f"Error loading features: {e}")
            return None

    def batch_predict(
        self,
        game_date: date,
        pitcher_lookups: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        Generate predictions for multiple pitchers

        Args:
            game_date: Game date
            pitcher_lookups: List of pitcher lookups (or None for all starting pitchers)

        Returns:
            list: List of predictions
        """
        predictions = []

        # Load all pitcher features for the date
        client = self._get_bq_client()

        if pitcher_lookups:
            pitcher_filter = "AND player_lookup IN UNNEST(@pitcher_lookups)"
        else:
            pitcher_filter = ""

        query = f"""
        WITH latest_features AS (
            SELECT
                player_lookup,
                game_date as feature_date,
                team_abbr,
                opponent_team_abbr,
                is_home,
                is_postseason,
                days_rest,
                k_avg_last_3,
                k_avg_last_5,
                k_avg_last_10,
                k_std_last_10,
                ip_avg_last_5,
                season_k_per_9,
                era_rolling_10,
                whip_rolling_10,
                season_games_started,
                season_strikeouts,
                season_innings,
                games_last_30_days,
                pitch_count_avg_last_5,
                data_completeness_score,
                rolling_stats_games,
                ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) as rn
            FROM `{self.project_id}.mlb_analytics.pitcher_game_summary`
            WHERE game_date < @game_date
              AND game_date >= DATE_SUB(@game_date, INTERVAL 30 DAY)
              AND rolling_stats_games >= 3
              {pitcher_filter}
        )
        SELECT * FROM latest_features WHERE rn = 1
        """

        try:
            from google.cloud import bigquery

            params = [
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date.isoformat()),
            ]
            if pitcher_lookups:
                params.append(
                    bigquery.ArrayQueryParameter("pitcher_lookups", "STRING", pitcher_lookups)
                )

            job_config = bigquery.QueryJobConfig(query_parameters=params)
            result = client.query(query, job_config=job_config).result()

            for row in result:
                features = dict(row)
                prediction = self.predict(
                    pitcher_lookup=features['player_lookup'],
                    features=features,
                    strikeouts_line=None  # Would need to join with props data
                )
                prediction['game_date'] = game_date.isoformat()
                prediction['team_abbr'] = features.get('team_abbr')
                prediction['opponent_team_abbr'] = features.get('opponent_team_abbr')
                predictions.append(prediction)

            logger.info(f"Generated {len(predictions)} predictions for {game_date}")
            return predictions

        except Exception as e:
            logger.error(f"Batch prediction failed: {e}")
            return []
