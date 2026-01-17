# predictions/mlb/prediction_systems/v1_baseline_predictor.py
"""
V1 Baseline MLB Pitcher Strikeouts Predictor

XGBoost-based prediction system using 25 core features.
This is the original V1.4 model that serves as the baseline.

Features (25):
- Rolling stats (f00-f04): K averages, std, IP
- Season stats (f05-f09): K/9, ERA, WHIP, games, K total
- Context (f10): Home/away
- Opponent/Ballpark (f15-f18): K rate, park factor, timing
- Workload (f20-f24): Rest, recent games, pitch count, IP total
- Bottom-up (f25-f28, f33): Expected K, lineup matchups

System ID: 'v1_baseline'
"""

import os
import json
import logging
from typing import Dict, List, Optional
from datetime import date
import numpy as np

from predictions.mlb.base_predictor import BaseMLBPredictor
from predictions.mlb.config import get_config

logger = logging.getLogger(__name__)

# Default values for missing features (V1.4 feature set)
FEATURE_DEFAULTS = {
    # Rolling stats (f00-f04)
    'f00_k_avg_last_3': 5.0,
    'f01_k_avg_last_5': 5.0,
    'f02_k_avg_last_10': 5.0,
    'f03_k_std_last_10': 2.0,
    'f04_ip_avg_last_5': 5.5,
    # Season stats (f05-f09)
    'f05_season_k_per_9': 8.5,
    'f06_season_era': 4.0,
    'f07_season_whip': 1.3,
    'f08_season_games': 5,
    'f09_season_k_total': 30,
    # Context (f10)
    'f10_is_home': 0.0,
    # Opponent/Ballpark (f15-f18)
    'f15_opponent_team_k_rate': 0.22,
    'f16_ballpark_k_factor': 1.0,
    'f17_month_of_season': 6,
    'f18_days_into_season': 90,
    # Workload (f20-f24)
    'f20_days_rest': 5,
    'f21_games_last_30_days': 5,
    'f22_pitch_count_avg': 90.0,
    'f23_season_ip_total': 50.0,
    'f24_is_postseason': 0.0,
    # Bottom-up (f25-f28, f33, V1.4)
    'f25_bottom_up_k_expected': 5.0,
    'f26_lineup_k_vs_hand': 0.22,
    'f27_avg_k_vs_opponent': 5.0,
    'f28_games_vs_opponent': 2,
    'f33_lineup_weak_spots': 2,
}

# Mapping from raw feature names to model feature names
RAW_TO_MODEL_MAPPING = {
    # Direct mappings
    'k_avg_last_3': 'f00_k_avg_last_3',
    'k_avg_last_5': 'f01_k_avg_last_5',
    'k_avg_last_10': 'f02_k_avg_last_10',
    'k_std_last_10': 'f03_k_std_last_10',
    'ip_avg_last_5': 'f04_ip_avg_last_5',
    'season_k_per_9': 'f05_season_k_per_9',
    'era_rolling_10': 'f06_season_era',
    'season_era': 'f06_season_era',
    'whip_rolling_10': 'f07_season_whip',
    'season_whip': 'f07_season_whip',
    'season_games_started': 'f08_season_games',
    'games_started': 'f08_season_games',
    'season_strikeouts': 'f09_season_k_total',
    'strikeouts_total': 'f09_season_k_total',
    'is_home': 'f10_is_home',
    'opponent_team_k_rate': 'f15_opponent_team_k_rate',
    'ballpark_k_factor': 'f16_ballpark_k_factor',
    'month_of_season': 'f17_month_of_season',
    'days_into_season': 'f18_days_into_season',
    # Workload
    'days_rest': 'f20_days_rest',
    'games_last_30_days': 'f21_games_last_30_days',
    'pitch_count_avg_last_5': 'f22_pitch_count_avg',
    'pitch_count_avg': 'f22_pitch_count_avg',
    'season_innings': 'f23_season_ip_total',
    'season_ip_total': 'f23_season_ip_total',
    'is_postseason': 'f24_is_postseason',
    # Bottom-up (V1.4)
    'bottom_up_k_expected': 'f25_bottom_up_k_expected',
    'lineup_k_vs_hand': 'f26_lineup_k_vs_hand',
    'avg_k_vs_opponent': 'f27_avg_k_vs_opponent',
    'games_vs_opponent': 'f28_games_vs_opponent',
    'lineup_weak_spots': 'f33_lineup_weak_spots',
}

# V1.4 feature order (25 features)
FEATURE_ORDER_V1_4 = [
    'f00_k_avg_last_3', 'f01_k_avg_last_5', 'f02_k_avg_last_10', 'f03_k_std_last_10', 'f04_ip_avg_last_5',
    'f05_season_k_per_9', 'f06_season_era', 'f07_season_whip', 'f08_season_games', 'f09_season_k_total',
    'f10_is_home', 'f15_opponent_team_k_rate', 'f16_ballpark_k_factor', 'f17_month_of_season', 'f18_days_into_season',
    'f20_days_rest', 'f21_games_last_30_days', 'f22_pitch_count_avg', 'f23_season_ip_total', 'f24_is_postseason',
    'f25_bottom_up_k_expected', 'f26_lineup_k_vs_hand', 'f27_avg_k_vs_opponent', 'f28_games_vs_opponent', 'f33_lineup_weak_spots',
]


class V1BaselinePredictor(BaseMLBPredictor):
    """
    V1 Baseline XGBoost predictor for pitcher strikeouts

    Uses 25 core features from V1.4 model.
    Default model: mlb_pitcher_strikeouts_v1_4features_20260114_142456.json
    """

    def __init__(
        self,
        model_path: str = None,
        project_id: str = None
    ):
        """
        Initialize V1 baseline predictor

        Args:
            model_path: GCS path to model (default: V1.4 model)
            project_id: GCP project ID
        """
        super().__init__(system_id='v1_baseline', project_id=project_id)

        # Default to V1.4 model
        default_model = 'gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_4features_20260114_142456.json'
        self.model_path = model_path or os.environ.get('MLB_V1_MODEL_PATH', default_model)
        self.model = None
        self.model_metadata = None
        self.feature_order = None

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

            logger.info(f"[{self.system_id}] Loading model from {self.model_path}")

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

            local_path = '/tmp/mlb_v1_baseline_model.json'
            blob.download_to_filename(local_path)

            # Load model
            self.model = xgb.Booster()
            self.model.load_model(local_path)

            # Load metadata
            metadata_path = self.model_path.replace('.json', '_metadata.json')
            metadata_blob_path = blob_path.replace('.json', '_metadata.json')
            metadata_blob = bucket.blob(metadata_blob_path)

            metadata_local = '/tmp/mlb_v1_baseline_metadata.json'
            metadata_blob.download_to_filename(metadata_local)

            with open(metadata_local, 'r') as f:
                self.model_metadata = json.load(f)

            # Extract feature order from metadata (supports both 'features' and 'feature_names' keys)
            self.feature_order = self.model_metadata.get('features') or self.model_metadata.get('feature_names')
            if not self.feature_order:
                logger.warning(f"[{self.system_id}] No feature order in metadata, using V1.4 fallback")
                self.feature_order = FEATURE_ORDER_V1_4

            logger.info(f"[{self.system_id}] Model loaded successfully. MAE: {self.model_metadata.get('test_mae', 'N/A')}")
            logger.info(f"[{self.system_id}] Feature count: {len(self.feature_order)}")
            return True

        except Exception as e:
            logger.error(f"[{self.system_id}] Failed to load model: {e}")
            return False

    def prepare_features(self, raw_features: Dict) -> Optional[np.ndarray]:
        """
        Prepare feature vector from raw features for V1 model

        Args:
            raw_features: Dict with feature values (can use raw names or model names)

        Returns:
            np.ndarray: Feature vector or None if invalid
        """
        if not self.feature_order:
            logger.error(f"[{self.system_id}] Model not loaded - no feature_order available")
            return None

        try:
            # First, normalize raw_features to model feature names
            normalized_features = {}

            for key, value in raw_features.items():
                # Check if it's already a model feature name
                if key.startswith('f') and len(key) > 2 and key[1:3].isdigit():
                    normalized_features[key] = value
                # Otherwise, try to map it using RAW_TO_MODEL_MAPPING
                elif key in RAW_TO_MODEL_MAPPING:
                    model_key = RAW_TO_MODEL_MAPPING[key]
                    # Don't overwrite if already set (prefer explicit model names)
                    if model_key not in normalized_features:
                        normalized_features[model_key] = value

            # Handle special boolean conversions
            if 'is_home' in raw_features:
                normalized_features['f10_is_home'] = 1.0 if raw_features.get('is_home') else 0.0
            if 'is_postseason' in raw_features:
                normalized_features['f24_is_postseason'] = 1.0 if raw_features.get('is_postseason') else 0.0

            # Handle fallback mappings for V1.4 features
            if 'f25_bottom_up_k_expected' not in normalized_features:
                # Use k_avg_last_5 as fallback for bottom_up_k_expected
                fallback = raw_features.get('bottom_up_k_expected') or raw_features.get('k_avg_last_5')
                if fallback:
                    normalized_features['f25_bottom_up_k_expected'] = fallback

            # Handle ERA/WHIP that can come from rolling or season
            if 'f06_season_era' not in normalized_features:
                era = raw_features.get('era_rolling_10') or raw_features.get('season_era')
                if era is not None:
                    normalized_features['f06_season_era'] = era
            if 'f07_season_whip' not in normalized_features:
                whip = raw_features.get('whip_rolling_10') or raw_features.get('season_whip')
                if whip is not None:
                    normalized_features['f07_season_whip'] = whip

            # Build feature vector in exact order from model metadata
            feature_vector = []
            for feature_name in self.feature_order:
                value = normalized_features.get(feature_name)
                if value is None:
                    value = FEATURE_DEFAULTS.get(feature_name, 0.0)
                feature_vector.append(float(value))

            result = np.array(feature_vector).reshape(1, -1)

            # Validate
            if np.any(np.isnan(result)) or np.any(np.isinf(result)):
                logger.warning(f"[{self.system_id}] Feature vector contains NaN or Inf values")
                # Replace with defaults
                for i, val in enumerate(result[0]):
                    if np.isnan(val) or np.isinf(val):
                        result[0][i] = FEATURE_DEFAULTS.get(self.feature_order[i], 0.0)

            return result

        except Exception as e:
            logger.error(f"[{self.system_id}] Error preparing features: {e}")
            return None

    def predict(
        self,
        pitcher_lookup: str,
        features: Dict,
        strikeouts_line: Optional[float] = None
    ) -> Dict:
        """
        Generate strikeout prediction for a pitcher using V1 baseline model

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
                'system_id': self.system_id,
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
                'system_id': self.system_id,
                'error': 'Failed to prepare features'
            }

        # Make prediction
        try:
            import xgboost as xgb
            dmatrix = xgb.DMatrix(feature_vector, feature_names=self.feature_order)
            raw_prediction = float(self.model.predict(dmatrix)[0])

            # V1 is a regressor (outputs strikeout count directly)
            predicted_strikeouts = raw_prediction

            # Clamp to reasonable range (0-20 strikeouts)
            predicted_strikeouts = max(0, min(20, predicted_strikeouts))

            # Calculate base confidence
            confidence = self._calculate_confidence(features, feature_vector)

            # Generate initial recommendation
            recommendation = self._generate_recommendation(
                predicted_strikeouts,
                strikeouts_line,
                confidence
            )

        except Exception as e:
            logger.error(f"[{self.system_id}] Prediction failed: {e}")
            return {
                'pitcher_lookup': pitcher_lookup,
                'predicted_strikeouts': None,
                'confidence': 0.0,
                'recommendation': 'ERROR',
                'system_id': self.system_id,
                'error': str(e)
            }

        # Check red flags
        red_flag_result = self._check_red_flags(features, recommendation)

        # If hard skip, return SKIP recommendation
        if red_flag_result.skip_bet:
            return {
                'pitcher_lookup': pitcher_lookup,
                'predicted_strikeouts': round(predicted_strikeouts, 2),
                'confidence': 0.0,
                'recommendation': 'SKIP',
                'edge': None,
                'strikeouts_line': strikeouts_line,
                'model_version': self.model_metadata.get('model_id', 'unknown') if self.model_metadata else 'unknown',
                'system_id': self.system_id,
                'model_mae': self.model_metadata.get('test_mae') if self.model_metadata else None,
                'red_flags': red_flag_result.flags,
                'skip_reason': red_flag_result.skip_reason
            }

        # Apply confidence multiplier from soft red flags
        adjusted_confidence = confidence * red_flag_result.confidence_multiplier

        # Re-generate recommendation with adjusted confidence
        final_recommendation = self._generate_recommendation(
            predicted_strikeouts,
            strikeouts_line,
            adjusted_confidence
        )

        # Calculate edge if line provided
        edge = None
        if strikeouts_line is not None:
            edge = predicted_strikeouts - strikeouts_line

        return {
            'pitcher_lookup': pitcher_lookup,
            'predicted_strikeouts': round(predicted_strikeouts, 2),
            'confidence': round(adjusted_confidence, 2),
            'base_confidence': round(confidence, 2),
            'recommendation': final_recommendation,
            'edge': round(edge, 2) if edge is not None else None,
            'strikeouts_line': strikeouts_line,
            'model_version': self.model_metadata.get('model_id', 'unknown') if self.model_metadata else 'unknown',
            'system_id': self.system_id,
            'model_mae': self.model_metadata.get('test_mae') if self.model_metadata else None,
            'red_flags': red_flag_result.flags if red_flag_result.flags else None,
            'confidence_multiplier': round(red_flag_result.confidence_multiplier, 2) if red_flag_result.confidence_multiplier < 1.0 else None
        }
