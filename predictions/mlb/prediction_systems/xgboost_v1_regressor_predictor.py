# predictions/mlb/prediction_systems/xgboost_v1_regressor_predictor.py
"""
XGBoost V1 MLB Pitcher Strikeouts Regressor Predictor

Same 36-feature contract as CatBoost V2 regressor. Predicts raw strikeout
count. Edge is in real K units (predicted - line).

System ID: 'xgboost_v1_regressor'
"""

import os
import json
import logging
import math
from typing import Dict, Optional
import numpy as np

from predictions.mlb.base_predictor import BaseMLBPredictor
from predictions.mlb.prediction_systems.catboost_v2_regressor_predictor import (
    CATBOOST_V2_FEATURES as FEATURE_ORDER,
    RAW_TO_MODEL_MAPPING,
    SIGMOID_SCALE,
)

logger = logging.getLogger(__name__)


class XGBoostV1RegressorPredictor(BaseMLBPredictor):
    """XGBoost V1 regressor for pitcher strikeout predictions.

    Uses identical feature contract as CatBoost V2 regressor (36 features).
    XGBoost handles NaN natively for NaN-tolerant features.
    """

    def __init__(self, model_path: str = None, project_id: str = None):
        super().__init__(system_id='xgboost_v1_regressor', project_id=project_id)

        default_model = 'gs://nba-props-platform-ml-models/mlb/xgboost_mlb_v1_regressor_36f.json'
        self.model_path = model_path or os.environ.get('MLB_XGBOOST_V1_MODEL_PATH', default_model)
        self.model = None
        self.model_metadata = None

    def load_model(self) -> bool:
        """Load XGBoost model from GCS."""
        if self.model is not None:
            return True

        try:
            import xgboost as xgb
            from google.cloud import storage

            logger.info(f"[{self.system_id}] Loading model from {self.model_path}")

            if not self.model_path.startswith('gs://'):
                raise ValueError(f"Invalid GCS path: {self.model_path}")

            parts = self.model_path.replace('gs://', '').split('/', 1)
            bucket_name, blob_path = parts[0], parts[1]

            client = storage.Client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(blob_path)

            local_path = '/tmp/mlb_xgboost_v1_regressor_model.json'
            blob.download_to_filename(local_path)

            self.model = xgb.Booster()
            self.model.load_model(local_path)

            # Load metadata
            metadata_blob_path = blob_path.replace('.json', '_metadata.json')
            metadata_blob = bucket.blob(metadata_blob_path)
            metadata_local = '/tmp/mlb_xgboost_v1_regressor_metadata.json'

            try:
                metadata_blob.download_to_filename(metadata_local)
                with open(metadata_local, 'r') as f:
                    self.model_metadata = json.load(f)
            except Exception as e:
                logger.warning(f"[{self.system_id}] Could not load metadata: {e}")
                self.model_metadata = {}

            logger.info(f"[{self.system_id}] Model loaded. Features: {len(FEATURE_ORDER)}")
            return True

        except Exception as e:
            logger.error(f"[{self.system_id}] Failed to load model: {e}", exc_info=True)
            return False

    def prepare_features(self, raw_features: Dict) -> tuple:
        """Prepare feature vector from raw features.

        Same logic as CatBoost V2 — shared feature contract.
        Returns (feature_vector, default_feature_count, default_features).
        """
        try:
            normalized = {}
            for key, value in raw_features.items():
                if key.startswith('f') and len(key) > 2 and key[1:3].isdigit():
                    normalized[key] = value
                elif key in RAW_TO_MODEL_MAPPING:
                    model_key = RAW_TO_MODEL_MAPPING[key]
                    if model_key not in normalized:
                        normalized[model_key] = value

            if 'is_home' in raw_features:
                normalized['f10_is_home'] = 1.0 if raw_features.get('is_home') else 0.0
            if 'is_day_game' in raw_features:
                normalized['f25_is_day_game'] = 1.0 if raw_features.get('is_day_game') else 0.0

            NAN_TOLERANT_FEATURES = {
                'f25_is_day_game',
                'f50_swstr_pct_last_3', 'f51_fb_velocity_last_3',
                'f52_swstr_trend', 'f53_velocity_change',
                'f19_season_swstr_pct', 'f19b_season_csw_pct',
                'f65_vs_opp_k_per_9', 'f66_vs_opp_games',
                'f68_k_per_pitch',
                'f70_o_swing_pct', 'f71_z_contact_pct', 'f72_fip', 'f73_gb_pct',
            }
            feature_vector = []
            default_feature_count = 0
            default_features = []

            for feature_name in FEATURE_ORDER:
                value = normalized.get(feature_name)
                if value is None or (isinstance(value, float) and (np.isnan(value) or np.isinf(value))):
                    if feature_name in NAN_TOLERANT_FEATURES:
                        feature_vector.append(float('nan'))
                        continue
                    default_feature_count += 1
                    default_features.append(feature_name)
                    value = 0.0
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
        """Generate strikeout prediction using XGBoost V1 regressor."""
        import xgboost as xgb

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
            dmatrix = xgb.DMatrix(feature_vector, feature_names=FEATURE_ORDER)
            predicted_K = float(self.model.predict(dmatrix)[0])
            predicted_K = max(0.0, min(20.0, predicted_K))

            if strikeouts_line is not None:
                edge = predicted_K - strikeouts_line
                recommendation = 'OVER' if edge > 0 else 'UNDER'
            else:
                edge = None
                recommendation = 'NO_LINE'

            if edge is not None:
                p_over = 1.0 / (1.0 + math.exp(-edge * SIGMOID_SCALE))
            else:
                p_over = 0.5

            confidence = min(100.0, abs(edge) * 35.0) if edge is not None else 0.0
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
                'model_version': 'xgboost_v1_regressor',
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
