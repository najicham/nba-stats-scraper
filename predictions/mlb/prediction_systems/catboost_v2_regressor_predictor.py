# predictions/mlb/prediction_systems/catboost_v2_regressor_predictor.py
"""
CatBoost V2 MLB Pitcher Strikeouts Regressor Predictor

CatBoost regressor predicting raw strikeout count for pitcher strikeout props.
Uses the same 40 features as V1 classifier but outputs predicted_K directly
instead of OVER/UNDER probability. Edge is in real K units (predicted - line).

Feature mapping: IDENTICAL to catboost_v1_predictor.py (same 40 features, same order).
Prediction flow: model.predict() -> predicted_K -> edge = predicted_K - line.

System ID: 'catboost_v2_regressor'
"""

import os
import json
import logging
import math
from typing import Dict, Optional
import numpy as np

from predictions.mlb.base_predictor import BaseMLBPredictor
from predictions.mlb.config import get_config

logger = logging.getLogger(__name__)

# Feature order — MUST match training feature order exactly
# IDENTICAL to catboost_v1_predictor.py
CATBOOST_V2_FEATURES = [
    'f00_k_avg_last_3', 'f01_k_avg_last_5', 'f02_k_avg_last_10',
    'f03_k_std_last_10', 'f04_ip_avg_last_5',
    'f05_season_k_per_9', 'f06_season_era', 'f07_season_whip',
    'f08_season_games', 'f09_season_k_total',
    'f10_is_home', 'f15_opponent_team_k_rate', 'f16_ballpark_k_factor',
    'f17_month_of_season', 'f18_days_into_season',
    'f19_season_swstr_pct', 'f19b_season_csw_pct',
    'f20_days_rest', 'f21_games_last_30_days', 'f22_pitch_count_avg',
    'f23_season_ip_total', 'f24_is_postseason',
    'f30_k_avg_vs_line', 'f32_line_level',
    'f40_bp_projection', 'f41_projection_diff', 'f44_over_implied_prob',
    'f50_swstr_pct_last_3', 'f51_fb_velocity_last_3',
    'f52_swstr_trend', 'f53_velocity_change',
    'f65_vs_opp_k_per_9', 'f66_vs_opp_games',
    'f67_season_starts', 'f68_k_per_pitch', 'f69_recent_workload_ratio',
    'f70_o_swing_pct', 'f71_z_contact_pct', 'f72_fip', 'f73_gb_pct',
]

# Raw name -> model feature name mapping
# IDENTICAL to catboost_v1_predictor.py
RAW_TO_MODEL_MAPPING = {
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
    'season_strikeouts': 'f09_season_k_total',
    'is_home': 'f10_is_home',
    'opponent_team_k_rate': 'f15_opponent_team_k_rate',
    'ballpark_k_factor': 'f16_ballpark_k_factor',
    'month_of_season': 'f17_month_of_season',
    'days_into_season': 'f18_days_into_season',
    'season_swstr_pct': 'f19_season_swstr_pct',
    'season_csw_pct': 'f19b_season_csw_pct',
    'days_rest': 'f20_days_rest',
    'games_last_30_days': 'f21_games_last_30_days',
    'pitch_count_avg_last_5': 'f22_pitch_count_avg',
    'season_innings': 'f23_season_ip_total',
    'is_postseason': 'f24_is_postseason',
    'k_avg_vs_line': 'f30_k_avg_vs_line',
    'line_level': 'f32_line_level',
    'strikeouts_line': 'f32_line_level',
    'bp_projection': 'f40_bp_projection',
    'projection_value': 'f40_bp_projection',
    'projection_diff': 'f41_projection_diff',
    'over_implied_prob': 'f44_over_implied_prob',
    'swstr_pct_last_3': 'f50_swstr_pct_last_3',
    'fb_velocity_last_3': 'f51_fb_velocity_last_3',
    'swstr_trend': 'f52_swstr_trend',
    'velocity_change': 'f53_velocity_change',
    'vs_opp_k_per_9': 'f65_vs_opp_k_per_9',
    'vs_opponent_k_per_9': 'f65_vs_opp_k_per_9',
    'vs_opp_games': 'f66_vs_opp_games',
    'vs_opponent_games': 'f66_vs_opp_games',
    'season_starts': 'f67_season_starts',
    'k_per_pitch': 'f68_k_per_pitch',
    'recent_workload_ratio': 'f69_recent_workload_ratio',
    'o_swing_pct': 'f70_o_swing_pct',
    'z_contact_pct': 'f71_z_contact_pct',
    'fip': 'f72_fip',
    'gb_pct': 'f73_gb_pct',
}

# Sigmoid scaling factor for converting edge to p_over
# Calibrated so edge=1.0K maps to ~p_over=0.668, edge=2.0K maps to ~0.802
SIGMOID_SCALE = 0.7


class CatBoostV2RegressorPredictor(BaseMLBPredictor):
    """
    CatBoost V2 regressor for pitcher strikeout predictions.

    Unlike V1 (classifier predicting P(OVER)), V2 directly predicts the
    strikeout count. Edge is in real K units: edge = predicted_K - line.

    p_over is derived via sigmoid for backward compatibility with the
    exporter and best-bets pipeline.

    Zero-tolerance for core features (BLOCKED if missing). Statcast features
    (f50-f53) and advanced features (f65-f73) are NaN-tolerant — CatBoost
    handles them natively.
    """

    def __init__(self, model_path: str = None, project_id: str = None):
        super().__init__(system_id='catboost_v2_regressor', project_id=project_id)

        default_model = 'gs://nba-props-platform-ml-models/mlb/catboost_mlb_v2_regressor_40f.cbm'
        self.model_path = model_path or os.environ.get('MLB_CATBOOST_V2_MODEL_PATH', default_model)
        self.model = None
        self.model_metadata = None

    def load_model(self) -> bool:
        """Load CatBoost regressor model from GCS."""
        if self.model is not None:
            return True

        try:
            from catboost import CatBoostRegressor
            from google.cloud import storage

            logger.info(f"[{self.system_id}] Loading model from {self.model_path}")

            if not self.model_path.startswith('gs://'):
                raise ValueError(f"Invalid GCS path: {self.model_path}")

            parts = self.model_path.replace('gs://', '').split('/', 1)
            bucket_name, blob_path = parts[0], parts[1]

            client = storage.Client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(blob_path)

            local_path = '/tmp/mlb_catboost_v2_regressor_model.cbm'
            blob.download_to_filename(local_path)

            self.model = CatBoostRegressor()
            self.model.load_model(local_path)

            # Load metadata
            metadata_blob_path = blob_path.replace('.cbm', '_metadata.json')
            metadata_blob = bucket.blob(metadata_blob_path)
            metadata_local = '/tmp/mlb_catboost_v2_regressor_metadata.json'

            try:
                metadata_blob.download_to_filename(metadata_local)
                with open(metadata_local, 'r') as f:
                    self.model_metadata = json.load(f)
            except Exception as e:
                logger.warning(f"[{self.system_id}] Could not load metadata: {e}")
                self.model_metadata = {}

            logger.info(f"[{self.system_id}] Model loaded. Features: {len(CATBOOST_V2_FEATURES)}")
            return True

        except Exception as e:
            logger.error(f"[{self.system_id}] Failed to load model: {e}", exc_info=True)
            return False

    def prepare_features(self, raw_features: Dict) -> tuple:
        """
        Prepare feature vector from raw features.

        Core features use zero-tolerance. Statcast and advanced features pass NaN
        to CatBoost which handles them natively.
        Returns (feature_vector, default_feature_count, default_features).
        """
        try:
            # Normalize raw feature names to model feature names
            normalized = {}
            for key, value in raw_features.items():
                if key.startswith('f') and len(key) > 2 and key[1:3].isdigit():
                    normalized[key] = value
                elif key in RAW_TO_MODEL_MAPPING:
                    model_key = RAW_TO_MODEL_MAPPING[key]
                    if model_key not in normalized:
                        normalized[model_key] = value

            # Handle boolean conversions
            if 'is_home' in raw_features:
                normalized['f10_is_home'] = 1.0 if raw_features.get('is_home') else 0.0
            if 'is_postseason' in raw_features:
                normalized['f24_is_postseason'] = 1.0 if raw_features.get('is_postseason') else 0.0

            # Build feature vector — track defaults
            # Statcast features (f50-f53) and advanced features are NaN-tolerant:
            # CatBoost handles them natively.
            # Core features still use zero-tolerance.
            NAN_TOLERANT_FEATURES = {
                'f50_swstr_pct_last_3', 'f51_fb_velocity_last_3',
                'f52_swstr_trend', 'f53_velocity_change',
                'f19_season_swstr_pct', 'f19b_season_csw_pct',
                'f65_vs_opp_k_per_9', 'f66_vs_opp_games',
                'f67_season_starts', 'f68_k_per_pitch', 'f69_recent_workload_ratio',
                'f70_o_swing_pct', 'f71_z_contact_pct', 'f72_fip', 'f73_gb_pct',
            }
            feature_vector = []
            default_feature_count = 0
            default_features = []

            for feature_name in CATBOOST_V2_FEATURES:
                value = normalized.get(feature_name)
                if value is None or (isinstance(value, float) and (np.isnan(value) or np.isinf(value))):
                    if feature_name in NAN_TOLERANT_FEATURES:
                        # CatBoost handles NaN natively for these features
                        feature_vector.append(float('nan'))
                        continue
                    default_feature_count += 1
                    default_features.append(feature_name)
                    value = 0.0  # Placeholder — will be BLOCKED anyway
                feature_vector.append(float(value))

            if default_feature_count > 0:
                logger.warning(
                    f"[{self.system_id}] {default_feature_count} features missing: "
                    f"{default_features[:5]}{'...' if len(default_features) > 5 else ''}"
                )

            result = np.array(feature_vector).reshape(1, -1)
            return result, default_feature_count, default_features

        except Exception as e:
            logger.error(f"[{self.system_id}] Error preparing features: {e}", exc_info=True)
            return None, 0, []

    def predict(self, pitcher_lookup: str, features: Dict,
                strikeouts_line: Optional[float] = None) -> Dict:
        """
        Generate strikeout prediction using CatBoost V2 regressor.

        The regressor predicts raw strikeout count (e.g., 6.8). Edge is the
        signed difference: predicted_K - line (positive = OVER, negative = UNDER).
        p_over is derived via sigmoid for backward compatibility.
        """
        if not self.load_model():
            return {
                'pitcher_lookup': pitcher_lookup,
                'predicted_strikeouts': None,
                'confidence': 0.0,
                'recommendation': 'ERROR',
                'system_id': self.system_id,
                'error': 'Failed to load model'
            }

        feature_vector, default_feature_count, default_features = self.prepare_features(features)
        if feature_vector is None:
            return {
                'pitcher_lookup': pitcher_lookup,
                'predicted_strikeouts': None,
                'confidence': 0.0,
                'recommendation': 'ERROR',
                'system_id': self.system_id,
                'default_feature_count': 0,
                'error': 'Failed to prepare features'
            }

        # ZERO TOLERANCE: Block predictions with any missing features
        if default_feature_count > 0:
            logger.info(
                f"[{self.system_id}] BLOCKED {pitcher_lookup}: "
                f"{default_feature_count} missing features ({default_features[:5]})"
            )
            return {
                'pitcher_lookup': pitcher_lookup,
                'predicted_strikeouts': None,
                'confidence': 0.0,
                'recommendation': 'BLOCKED',
                'system_id': self.system_id,
                'default_feature_count': default_feature_count,
                'default_features': default_features,
                'error': f'Blocked: {default_feature_count} features missing'
            }

        try:
            # CatBoost regressor predicts raw strikeout count
            predicted_K = float(self.model.predict(feature_vector)[0])

            # Sanity guard: predicted_K should be non-negative and reasonable
            if predicted_K < 0:
                logger.warning(
                    f"[{self.system_id}] Negative prediction ({predicted_K:.2f}) for "
                    f"{pitcher_lookup}, clamping to 0"
                )
                predicted_K = 0.0
            elif predicted_K > 20:
                logger.warning(
                    f"[{self.system_id}] Unreasonably high prediction ({predicted_K:.2f}) for "
                    f"{pitcher_lookup}, clamping to 20"
                )
                predicted_K = 20.0

            # Edge: signed difference in K units (positive = OVER, negative = UNDER)
            if strikeouts_line is not None:
                edge = predicted_K - strikeouts_line
                recommendation = 'OVER' if edge > 0 else 'UNDER'
            else:
                edge = None
                recommendation = 'NO_LINE'

            # p_over: sigmoid transformation for backward compatibility
            # Maps edge (in K units) to probability-like value [0, 1]
            # edge=0 -> p_over=0.5, edge=+1K -> ~0.668, edge=-1K -> ~0.332
            if edge is not None:
                p_over = 1.0 / (1.0 + math.exp(-edge * SIGMOID_SCALE))
            else:
                p_over = 0.5

            # Confidence from edge magnitude (scaled to 0-100)
            # abs(edge) of 1K -> ~35, 2K -> ~70, 3K -> ~100
            confidence = min(100.0, abs(edge) * 35.0) if edge is not None else 0.0

            # Check red flags
            red_flag_result = self._check_red_flags(features, recommendation)

            if red_flag_result.skip_bet:
                return {
                    'pitcher_lookup': pitcher_lookup,
                    'predicted_strikeouts': round(predicted_K, 2),
                    'confidence': 0.0,
                    'recommendation': 'SKIP',
                    'edge': None,
                    'strikeouts_line': strikeouts_line,
                    'system_id': self.system_id,
                    'red_flags': red_flag_result.flags,
                    'skip_reason': red_flag_result.skip_reason,
                    'default_feature_count': 0,
                    'p_over': round(p_over, 4),
                }

            adjusted_confidence = confidence * red_flag_result.confidence_multiplier

            return {
                'pitcher_lookup': pitcher_lookup,
                'predicted_strikeouts': round(predicted_K, 2),
                'confidence': round(adjusted_confidence, 2),
                'recommendation': recommendation,
                'edge': round(edge, 2) if edge is not None else None,
                'strikeouts_line': strikeouts_line,
                'system_id': self.system_id,
                'model_version': 'catboost_v2_regressor',
                'p_over': round(p_over, 4),
                'red_flags': red_flag_result.flags if red_flag_result.flags else None,
                'default_feature_count': 0,
            }

        except Exception as e:
            logger.error(f"[{self.system_id}] Prediction failed: {e}", exc_info=True)
            return {
                'pitcher_lookup': pitcher_lookup,
                'predicted_strikeouts': None,
                'confidence': 0.0,
                'recommendation': 'ERROR',
                'system_id': self.system_id,
                'default_feature_count': 0,
                'error': str(e)
            }
