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
# Session 444: Reduced from 40 to 36 features (5 dead/duplicate removed)
CATBOOST_V2_FEATURES = [
    'f00_k_avg_last_3', 'f01_k_avg_last_5', 'f02_k_avg_last_10',
    'f03_k_std_last_10', 'f04_ip_avg_last_5',
    'f05_season_k_per_9', 'f06_season_era', 'f07_season_whip',
    'f08_season_games', 'f09_season_k_total',
    'f10_is_home', 'f15_opponent_team_k_rate', 'f16_ballpark_k_factor',
    # f17, f18, f24 REMOVED (dead features — Session 444)
    'f19_season_swstr_pct', 'f19b_season_csw_pct',
    'f20_days_rest', 'f21_games_last_30_days', 'f22_pitch_count_avg',
    'f23_season_ip_total', 'f25_is_day_game',
    'f30_k_avg_vs_line', 'f32_line_level',
    'f40_bp_projection', 'f41_projection_diff', 'f44_over_implied_prob',
    'f50_swstr_pct_last_3', 'f51_fb_velocity_last_3',
    'f52_swstr_trend', 'f53_velocity_change',
    'f65_vs_opp_k_per_9', 'f66_vs_opp_games',
    # f67 REMOVED (duplicate of f08 — Session 444)
    'f68_k_per_pitch',
    # f69 REMOVED (duplicate of f21/6.0 — Session 444)
    'f70_o_swing_pct', 'f71_z_contact_pct', 'f72_fip', 'f73_gb_pct',
]

# Raw name -> model feature name mapping
# Session 444: Removed mappings for dead features (f17, f18, f24, f67, f69)
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
    'season_swstr_pct': 'f19_season_swstr_pct',
    'season_csw_pct': 'f19b_season_csw_pct',
    'days_rest': 'f20_days_rest',
    'games_last_30_days': 'f21_games_last_30_days',
    'pitch_count_avg_last_5': 'f22_pitch_count_avg',
    'season_innings': 'f23_season_ip_total',
    'is_day_game': 'f25_is_day_game',
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
    'k_per_pitch': 'f68_k_per_pitch',
    'o_swing_pct': 'f70_o_swing_pct',
    'z_contact_pct': 'f71_z_contact_pct',
    'fip': 'f72_fip',
    'gb_pct': 'f73_gb_pct',
}

# Sigmoid scale — retained ONLY because the shadow lightgbm_v1 / xgboost_v1
# regressor predictors import it from this module. catboost_v2 itself no longer
# uses it: as of Stage 1.1 its p_over comes from the Poisson tail below.
SIGMOID_SCALE = 0.7

# Model-market blend weight bounds. The blend is `blended = w*model + (1-w)*line`.
# w=1.0 is pure model (the pre-Stage-1.1 behavior, and what a model artifact
# trained before Stage 1.1 gets since it carries no blend_weight). The 0.3 floor
# keeps the model a majority voice per the project spec.
BLEND_WEIGHT_DEFAULT = 1.0
BLEND_WEIGHT_FLOOR = 0.3


def _poisson_cdf(k: int, lam: float) -> float:
    """P(X <= k) for X ~ Poisson(lam), summed iteratively (stdlib only).

    Stable across the strikeout range (k 0-9, lam 0-20): each term is derived
    from the previous via `term *= lam / i`, so there is no factorial or pow
    overflow. Returns 1.0 for a non-positive lambda (degenerate point mass at 0).
    """
    if lam <= 0:
        return 1.0
    term = math.exp(-lam)  # i = 0 term
    cdf = term
    for i in range(1, k + 1):
        term *= lam / i
        cdf += term
    return min(1.0, cdf)


def poisson_p_over(line: float, lam: float) -> float:
    """P(strikeouts > line) for K ~ Poisson(lam = predicted strikeouts).

    K is integer-valued, so `K > line` is `K >= floor(line) + 1` for both
    half-point lines (a 5.5 line) and integer lines (a 6.0 line correctly
    treats K == 6 as a push, not an over). Both reduce to
    `1 - PoissonCDF(floor(line))`. This is the honest, per-pitcher probability
    that replaces the hand-tuned constant `sigmoid(0.7*edge)` — the sigmoid was
    never fit to outcomes and produced a non-monotonic edge->hit-rate curve.
    """
    return max(0.0, min(1.0, 1.0 - _poisson_cdf(math.floor(line), lam)))


class CatBoostV2RegressorPredictor(BaseMLBPredictor):
    """
    CatBoost V2 regressor for pitcher strikeout predictions.

    Unlike V1 (classifier predicting P(OVER)), V2 directly predicts the
    strikeout count. Edge is in real K units: edge = blended_K - line.

    Stage 1.1: the raw model output is blended with the market line
    (`blended = w*model + (1-w)*line`, w from model metadata) and p_over is
    the honest Poisson tail `P(K > line)` rather than a hand-tuned sigmoid.

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
            if 'is_day_game' in raw_features:
                normalized['f25_is_day_game'] = 1.0 if raw_features.get('is_day_game') else 0.0

            # Build feature vector — track defaults
            # Statcast features (f50-f53) and advanced features are NaN-tolerant:
            # CatBoost handles them natively.
            # Core features still use zero-tolerance.
            NAN_TOLERANT_FEATURES = {
                'f25_is_day_game',
                'f50_swstr_pct_last_3', 'f51_fb_velocity_last_3',
                'f52_swstr_trend', 'f53_velocity_change',
                'f19_season_swstr_pct', 'f19b_season_csw_pct',
                'f65_vs_opp_k_per_9', 'f66_vs_opp_games',
                'f68_k_per_pitch',
                'f70_o_swing_pct', 'f71_z_contact_pct', 'f72_fip', 'f73_gb_pct',
                # BettingPros projection — NULL when bp_pitcher_props has no 2026 data;
                # oddsa_pitcher_props has no projection equivalent so we pass NaN.
                'f40_bp_projection',
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

    def _get_blend_weight(self) -> float:
        """Resolve the model-market blend weight `w` for `w*model + (1-w)*line`.

        Priority: MLB_BLEND_WEIGHT env override > model metadata `blend_weight`
        (fit walk-forward at training time by train_regressor_v2.fit_blend_weight)
        > 1.0 (no blend). Clamped to [BLEND_WEIGHT_FLOOR, 1.0]. The env var is
        the only lever to activate or disable the blend without a retrain, so it
        doubles as an incident rollback (set 1.0 to revert to the pure model).
        """
        raw = os.environ.get('MLB_BLEND_WEIGHT')
        if raw is None:
            raw = (self.model_metadata or {}).get('blend_weight')
        if raw is None:
            return BLEND_WEIGHT_DEFAULT
        try:
            w = float(raw)
        except (TypeError, ValueError):
            logger.warning(
                f"[{self.system_id}] Invalid blend_weight {raw!r}; "
                f"falling back to {BLEND_WEIGHT_DEFAULT} (no blend)"
            )
            return BLEND_WEIGHT_DEFAULT
        return max(BLEND_WEIGHT_FLOOR, min(1.0, w))

    def predict(self, pitcher_lookup: str, features: Dict,
                strikeouts_line: Optional[float] = None) -> Dict:
        """
        Generate strikeout prediction using CatBoost V2 regressor.

        The regressor predicts a raw strikeout count (e.g. 6.8). That output is
        blended with the market line (`blended = w*model + (1-w)*line`) and the
        reported prediction, edge, and p_over are all derived from the blend:
        edge = blended_K - line (positive = OVER) and p_over = P(K > line) under
        K ~ Poisson(blended_K).
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

            # Model-market blend (Stage 1.1). Bates-Granger: the model and the
            # market line make decorrelated errors of near-equal size, so a
            # convex blend lowers MAE. `w` is fit walk-forward at training time
            # (train_regressor_v2.fit_blend_weight) and stored in metadata;
            # w=1.0 (no blend) for a model artifact that predates Stage 1.1.
            # The blend shrinks edge by factor w (blended_K - line = w*(model -
            # line)), which mechanically suppresses small-divergence picks.
            blend_weight = self._get_blend_weight()

            if strikeouts_line is not None:
                blended_K = (
                    blend_weight * predicted_K
                    + (1.0 - blend_weight) * strikeouts_line
                )
                # Edge: signed difference in K units (positive = OVER, negative = UNDER)
                edge = blended_K - strikeouts_line
                recommendation = 'OVER' if edge > 0 else 'UNDER'
                # Honest P(over): K ~ Poisson(lambda = blended_K), so
                # P(K > line) = 1 - PoissonCDF(floor(line), lambda). Replaces the
                # constant sigmoid whose edge->hit-rate curve was non-monotonic.
                p_over = poisson_p_over(strikeouts_line, blended_K)
            else:
                blended_K = predicted_K
                edge = None
                recommendation = 'NO_LINE'
                p_over = 0.5

            # Confidence from edge magnitude (scaled to 0-100)
            # abs(edge) of 1K -> ~35, 2K -> ~70, 3K -> ~100
            confidence = min(100.0, abs(edge) * 35.0) if edge is not None else 0.0

            # Check red flags
            red_flag_result = self._check_red_flags(features, recommendation)

            if red_flag_result.skip_bet:
                return {
                    'pitcher_lookup': pitcher_lookup,
                    'predicted_strikeouts': round(blended_K, 2),
                    'confidence': 0.0,
                    'recommendation': 'SKIP',
                    'edge': None,
                    'strikeouts_line': strikeouts_line,
                    'system_id': self.system_id,
                    'red_flags': red_flag_result.flags,
                    'skip_reason': red_flag_result.skip_reason,
                    'default_feature_count': 0,
                    'p_over': round(p_over, 4),
                    'blend_weight': round(blend_weight, 4),
                }

            adjusted_confidence = confidence * red_flag_result.confidence_multiplier

            return {
                'pitcher_lookup': pitcher_lookup,
                'predicted_strikeouts': round(blended_K, 2),
                'confidence': round(adjusted_confidence, 2),
                'recommendation': recommendation,
                'edge': round(edge, 2) if edge is not None else None,
                'strikeouts_line': strikeouts_line,
                'system_id': self.system_id,
                'model_version': 'catboost_v2_regressor',
                'p_over': round(p_over, 4),
                'blend_weight': round(blend_weight, 4),
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
