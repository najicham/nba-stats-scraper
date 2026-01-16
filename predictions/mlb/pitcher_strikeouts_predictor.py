# predictions/mlb/pitcher_strikeouts_predictor.py
"""
MLB Pitcher Strikeouts Predictor

XGBoost-based prediction system for pitcher strikeout totals.
Loads trained model from GCS and generates predictions using features
from mlb_analytics.pitcher_game_summary.

Supports dynamic feature loading from model metadata to handle multiple
model versions (V1.4, V1.6, etc.) with different feature sets.
"""

import os
import json
import logging
from typing import Dict, List, Optional, Tuple
from datetime import date, datetime
import numpy as np

logger = logging.getLogger(__name__)

# Default values for missing features (comprehensive for all model versions)
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
    # Season swing metrics (f19, V1.6+)
    'f19_season_swstr_pct': 0.11,
    'f19b_season_csw_pct': 0.30,
    'f19c_season_chase_pct': 0.28,
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
    # Line-relative (f30-f32, V1.6+)
    'f30_k_avg_vs_line': 0.0,
    'f31_projected_vs_line': 0.0,
    'f32_line_level': 5.5,
    # BettingPros (f40-f44, V1.6+)
    'f40_bp_projection': 5.0,
    'f41_projection_diff': 0.0,
    'f42_perf_last_5_pct': 0.5,
    'f43_perf_last_10_pct': 0.5,
    'f44_over_implied_prob': 0.5,
    # Rolling Statcast (f50-f53, V1.6+)
    'f50_swstr_pct_last_3': 0.11,
    'f51_fb_velocity_last_3': 93.0,
    'f52_swstr_trend': 0.0,
    'f53_velocity_change': 0.0,
}

# Mapping from raw feature names to model feature names
# (allows features from different sources to map to same model feature)
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
    # Season swing metrics (V1.6+)
    'season_swstr_pct': 'f19_season_swstr_pct',
    'swstr_pct_season_prior': 'f19_season_swstr_pct',
    'season_csw_pct': 'f19b_season_csw_pct',
    'season_chase_pct': 'f19c_season_chase_pct',
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
    # Line-relative (V1.6+)
    'k_avg_vs_line': 'f30_k_avg_vs_line',
    'projected_vs_line': 'f31_projected_vs_line',
    'line_level': 'f32_line_level',
    'strikeouts_line': 'f32_line_level',
    # BettingPros (V1.6+)
    'bp_projection': 'f40_bp_projection',
    'projection_value': 'f40_bp_projection',
    'projection_diff': 'f41_projection_diff',
    'perf_last_5_pct': 'f42_perf_last_5_pct',
    'perf_last_10_pct': 'f43_perf_last_10_pct',
    'over_implied_prob': 'f44_over_implied_prob',
    # Rolling Statcast (V1.6+)
    'swstr_pct_last_3': 'f50_swstr_pct_last_3',
    'fb_velocity_last_3': 'f51_fb_velocity_last_3',
    'swstr_trend': 'f52_swstr_trend',
    'velocity_change': 'f53_velocity_change',
}

# Legacy fallback for V1.4 models
FEATURE_ORDER_V1_4 = [
    'f00_k_avg_last_3', 'f01_k_avg_last_5', 'f02_k_avg_last_10', 'f03_k_std_last_10', 'f04_ip_avg_last_5',
    'f05_season_k_per_9', 'f06_season_era', 'f07_season_whip', 'f08_season_games', 'f09_season_k_total',
    'f10_is_home', 'f15_opponent_team_k_rate', 'f16_ballpark_k_factor', 'f17_month_of_season', 'f18_days_into_season',
    'f20_days_rest', 'f21_games_last_30_days', 'f22_pitch_count_avg', 'f23_season_ip_total', 'f24_is_postseason',
    'f25_bottom_up_k_expected', 'f26_lineup_k_vs_hand', 'f27_avg_k_vs_opponent', 'f28_games_vs_opponent', 'f33_lineup_weak_spots',
]


class RedFlagResult:
    """Result of red flag evaluation"""
    def __init__(
        self,
        skip_bet: bool = False,
        confidence_multiplier: float = 1.0,
        flags: list = None,
        skip_reason: str = None
    ):
        self.skip_bet = skip_bet
        self.confidence_multiplier = confidence_multiplier
        self.flags = flags or []
        self.skip_reason = skip_reason


class PitcherStrikeoutsPredictor:
    """
    XGBoost-based pitcher strikeouts predictor

    Usage:
        predictor = PitcherStrikeoutsPredictor()
        prediction = predictor.predict(pitcher_lookup, game_date, features)

    Champion-Challenger Model Selection:
        Set MLB_PITCHER_STRIKEOUTS_MODEL_PATH environment variable to switch models.

        V1.4 (champion): mlb_pitcher_strikeouts_v1_4features_20260114_142456.json
        V1.6 (challenger): mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json

        Example:
            export MLB_PITCHER_STRIKEOUTS_MODEL_PATH=gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json

    Red Flag System (v1.0):
        Hard Skip: First start of season, very low IP average (bullpen/opener proxy)
        Soft Reduce: Early season, inconsistent, short rest, high workload, SwStr% trend
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
        # Support environment variable for champion-challenger switching
        # V1.6 (champion): mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json - 60% win rate in shadow testing
        # V1.4 (previous champion): mlb_pitcher_strikeouts_v1_4features_20260114_142456.json
        default_model = 'gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json'
        self.model_path = model_path or os.environ.get('MLB_PITCHER_STRIKEOUTS_MODEL_PATH', default_model)
        self.model = None
        self.model_metadata = None
        self.feature_order = None  # Loaded dynamically from model metadata
        self._bq_client = None

    def _get_bq_client(self):
        """Lazy-load BigQuery client"""
        if self._bq_client is None:
            from google.cloud import bigquery
            self._bq_client = bigquery.Client(project=self.project_id)
        return self._bq_client

    _il_cache = None  # Class-level cache for IL status
    _il_cache_date = None

    def _get_current_il_pitchers(self) -> set:
        """
        Get set of pitcher_lookup values currently on IL.
        Caches result for the day to avoid repeated queries.

        Returns:
            set: pitcher_lookup values on IL
        """
        from datetime import date as date_type

        today = date_type.today()

        # Return cached if same day
        if (PitcherStrikeoutsPredictor._il_cache is not None and
            PitcherStrikeoutsPredictor._il_cache_date == today):
            return PitcherStrikeoutsPredictor._il_cache

        try:
            client = self._get_bq_client()
            query = """
            SELECT DISTINCT REPLACE(player_lookup, '_', '') as player_lookup
            FROM `nba-props-platform.mlb_raw.bdl_injuries`
            WHERE snapshot_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
              AND is_pitcher = TRUE
              AND injury_status IN ('10-Day-IL', '15-Day-IL', '60-Day-IL', 'Out')
            """
            result = client.query(query).result()
            il_pitchers = {row.player_lookup for row in result}

            # Cache result
            PitcherStrikeoutsPredictor._il_cache = il_pitchers
            PitcherStrikeoutsPredictor._il_cache_date = today

            logger.info(f"Loaded {len(il_pitchers)} pitchers on IL")
            return il_pitchers

        except Exception as e:
            logger.warning(f"Failed to load IL status: {e}")
            return set()

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

            # Extract feature order from metadata (supports both 'features' and 'feature_names' keys)
            self.feature_order = self.model_metadata.get('features') or self.model_metadata.get('feature_names')
            if not self.feature_order:
                logger.warning("No feature order in metadata, using V1.4 fallback")
                self.feature_order = FEATURE_ORDER_V1_4

            logger.info(f"Model loaded successfully. MAE: {self.model_metadata.get('test_mae', 'N/A')}")
            logger.info(f"Feature count: {len(self.feature_order)}")
            return True

        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            return False

    def prepare_features(self, raw_features: Dict) -> Optional[np.ndarray]:
        """
        Prepare feature vector from raw features

        Dynamically maps raw feature names to model features based on the
        feature_order loaded from model metadata. Supports both V1.4 and V1.6 models.

        Args:
            raw_features: Dict with feature values (can use raw names or model names)

        Returns:
            np.ndarray: Feature vector or None if invalid
        """
        if not self.feature_order:
            logger.error("Model not loaded - no feature_order available")
            return None

        try:
            # First, normalize raw_features to model feature names
            # This handles cases where input uses raw names (k_avg_last_3)
            # or already uses model names (f00_k_avg_last_3)
            normalized_features = {}

            for key, value in raw_features.items():
                # Check if it's already a model feature name
                if key.startswith('f') and key[1:3].isdigit():
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
                logger.warning("Feature vector contains NaN or Inf values")
                # Replace with defaults
                for i, val in enumerate(result[0]):
                    if np.isnan(val) or np.isinf(val):
                        result[0][i] = FEATURE_DEFAULTS.get(self.feature_order[i], 0.0)

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
            dmatrix = xgb.DMatrix(feature_vector, feature_names=self.feature_order)
            raw_prediction = float(self.model.predict(dmatrix)[0])

            # Check if this is a classifier model (outputs probability of OVER)
            is_classifier = self.model_metadata and self.model_metadata.get('model_type') == 'classifier'

            if is_classifier:
                # Classifier output is probability of OVER (0-1)
                over_probability = raw_prediction

                # Convert probability to estimated strikeouts for comparison
                # If prob > 0.5, estimate line + small edge; if < 0.5, estimate line - small edge
                edge_estimate = (over_probability - 0.5) * 2  # Scale -0.5 to 0.5 -> -1 to 1
                if strikeouts_line is not None:
                    predicted_strikeouts = strikeouts_line + edge_estimate
                else:
                    # Fallback: use k_avg_last_5 as baseline
                    baseline = features.get('k_avg_last_5', 5.0) or 5.0
                    predicted_strikeouts = baseline + edge_estimate

                # Confidence for classifier: distance from 0.5 (max at 0 or 1)
                # Scale to 0-100 to match regressor confidence scale
                # prob=0.5 -> conf=0, prob=0.65 -> conf=60, prob=0.75 -> conf=100
                raw_confidence = abs(over_probability - 0.5) * 2  # 0-1
                confidence = min(100, raw_confidence * 200)  # Scale: 0.5 prob diff = 100 conf

                # Direct recommendation from probability
                # Use thresholds that correspond to ~60 confidence (prob > 0.65 or < 0.35)
                if over_probability >= 0.53:
                    recommendation = 'OVER'
                elif over_probability <= 0.47:
                    recommendation = 'UNDER'
                else:
                    recommendation = 'PASS'

                logger.debug(f"Classifier: prob={over_probability:.3f}, est_K={predicted_strikeouts:.1f}, conf={confidence:.1f}")

            else:
                # Regressor output is predicted strikeout count
                predicted_strikeouts = raw_prediction

                # Clamp to reasonable range (0-20 strikeouts)
                predicted_strikeouts = max(0, min(20, predicted_strikeouts))

                # Calculate base confidence for regressor
                confidence = self._calculate_confidence(features, feature_vector)

                # Generate initial recommendation
                recommendation = self._generate_recommendation(
                    predicted_strikeouts,
                    strikeouts_line,
                    confidence
                )

        except Exception as e:
            logger.error(f"Prediction failed: {e}")
            return {
                'pitcher_lookup': pitcher_lookup,
                'predicted_strikeouts': None,
                'confidence': 0.0,
                'recommendation': 'ERROR',
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
            'model_mae': self.model_metadata.get('test_mae') if self.model_metadata else None,
            'red_flags': red_flag_result.flags if red_flag_result.flags else None,
            'confidence_multiplier': round(red_flag_result.confidence_multiplier, 2) if red_flag_result.confidence_multiplier < 1.0 else None
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

    def _check_red_flags(
        self,
        features: Dict,
        recommendation: str = None
    ) -> RedFlagResult:
        """
        Check for red flags that should skip or reduce confidence in a bet.

        RED FLAG SYSTEM v1.0
        ====================

        HARD SKIP (do not bet):
        - First start of season: No historical data, unpredictable
        - Very low IP avg (<4.0): Likely bullpen game or opener
        - MLB debut (career starts < 3): Too little data

        SOFT REDUCE (reduce confidence):
        - Early season (starts < 3): Limited recent data → 0.7x
        - Very inconsistent (k_std > 4): High variance → 0.8x
        - Short rest (<4 days): Fatigue risk for OVER → 0.7x on OVER
        - High recent workload (>6 games/30d): Fatigue → 0.85x on OVER
        - Very high K std (>5): Extreme variance → 0.6x

        Future (need more data):
        - IL return detection (need injuries data)
        - Velocity drop >2.5 mph (need per-game velocity)
        - Line moved >1.5 K (need opening line data)

        Args:
            features: Feature dict from pitcher_game_summary
            recommendation: 'OVER' or 'UNDER' (affects some rules)

        Returns:
            RedFlagResult with skip_bet, confidence_multiplier, flags
        """
        flags = []
        skip_bet = False
        skip_reason = None
        confidence_multiplier = 1.0

        # =============================================================
        # HARD SKIP RULES
        # =============================================================

        # 0. Currently on IL - shouldn't have props but check anyway
        pitcher_lookup = features.get('player_lookup', '')
        # Normalize name format (remove underscores for matching)
        pitcher_normalized = pitcher_lookup.replace('_', '').lower()
        il_pitchers = self._get_current_il_pitchers()
        if pitcher_normalized in il_pitchers:
            skip_bet = True
            skip_reason = "Pitcher currently on IL"
            flags.append("SKIP: Currently on IL")
            return RedFlagResult(skip_bet, confidence_multiplier, flags, skip_reason)

        # 1. First start of season - no data to predict with
        is_first_start = features.get('is_first_start', False)
        season_games = features.get('season_games_started', 0)

        if is_first_start or season_games == 0:
            skip_bet = True
            skip_reason = "First start of season - no historical data"
            flags.append("SKIP: First start of season")
            return RedFlagResult(skip_bet, confidence_multiplier, flags, skip_reason)

        # 2. Very low IP average - likely bullpen/opener
        ip_avg = features.get('ip_avg_last_5', 5.5)
        if ip_avg is not None and ip_avg < 4.0:
            skip_bet = True
            skip_reason = f"Low IP avg ({ip_avg:.1f}) - likely bullpen/opener"
            flags.append(f"SKIP: Low IP avg ({ip_avg:.1f})")
            return RedFlagResult(skip_bet, confidence_multiplier, flags, skip_reason)

        # 3. MLB debut / very few career starts
        rolling_games = features.get('rolling_stats_games', 0)
        if rolling_games is not None and rolling_games < 2:
            skip_bet = True
            skip_reason = f"Only {rolling_games} career starts - too little data"
            flags.append(f"SKIP: Only {rolling_games} career starts")
            return RedFlagResult(skip_bet, confidence_multiplier, flags, skip_reason)

        # =============================================================
        # SOFT REDUCE RULES (cumulative)
        # =============================================================

        # 4. Early season (first 3 starts)
        if season_games < 3:
            confidence_multiplier *= 0.7
            flags.append(f"REDUCE: Early season ({season_games} starts)")

        # 5. Very inconsistent pitcher (high K std dev)
        # BACKTEST FINDING: k_std > 4 → 34.4% OVER hit rate vs 62.5% UNDER!
        k_std = features.get('k_std_last_10', 2.0)
        if k_std is not None:
            if k_std > 4:
                if recommendation == 'OVER':
                    # High variance + OVER = very bad (34.4% hit rate in backtest)
                    confidence_multiplier *= 0.4
                    flags.append(f"REDUCE: High variance ({k_std:.1f}) strongly favors UNDER")
                elif recommendation == 'UNDER':
                    # High variance + UNDER = good (62.5% hit rate in backtest)
                    confidence_multiplier *= 1.1  # Slight boost
                    flags.append(f"BOOST: High variance ({k_std:.1f}) favors UNDER")

        # 6. Short rest (affects OVER bets more)
        days_rest = features.get('days_rest', 5)
        if days_rest is not None and days_rest < 4 and recommendation == 'OVER':
            confidence_multiplier *= 0.7
            flags.append(f"REDUCE: Short rest ({days_rest}d) for OVER bet")

        # 7. High recent workload (affects OVER bets)
        games_30d = features.get('games_last_30_days', 5)
        if games_30d is not None and games_30d > 6 and recommendation == 'OVER':
            confidence_multiplier *= 0.85
            flags.append(f"REDUCE: High workload ({games_30d} games in 30d)")

        # 8. SwStr% directional signal (BACKTEST VALIDATED)
        # high_swstr (>12%): 55.8% OVER vs 41.1% UNDER → Lean OVER
        # low_swstr (<8%): 47.5% OVER vs 49.7% UNDER → Lean UNDER
        swstr = features.get('season_swstr_pct')
        if swstr is not None:
            if swstr > 0.12:
                # Elite stuff - favors OVER
                if recommendation == 'OVER':
                    confidence_multiplier *= 1.1
                    flags.append(f"BOOST: Elite SwStr% ({swstr:.1%}) favors OVER")
                elif recommendation == 'UNDER':
                    confidence_multiplier *= 0.8
                    flags.append(f"REDUCE: Elite SwStr% ({swstr:.1%}) - avoid UNDER")
            elif swstr < 0.08:
                # Weak stuff - favors UNDER
                if recommendation == 'OVER':
                    confidence_multiplier *= 0.85
                    flags.append(f"REDUCE: Low SwStr% ({swstr:.1%}) - lean UNDER")
                elif recommendation == 'UNDER':
                    confidence_multiplier *= 1.05
                    flags.append(f"SLIGHT BOOST: Low SwStr% ({swstr:.1%})")

        # 9. SwStr% Trend Signal (BACKTEST VALIDATED - Session 57)
        # Hot streak (+3%): 54.6% OVER hit rate (381 games) → Lean OVER
        # Cold streak (-3%): 49.8% UNDER hit rate (315 games) → Lean UNDER
        swstr_trend = features.get('swstr_trend')  # recent_swstr - season_swstr
        if swstr_trend is not None:
            if swstr_trend > 0.03:
                # Hot streak - recent SwStr% 3%+ above season baseline
                if recommendation == 'OVER':
                    confidence_multiplier *= 1.08
                    flags.append(f"BOOST: Hot streak (SwStr% +{swstr_trend:.1%}) favors OVER")
                elif recommendation == 'UNDER':
                    confidence_multiplier *= 0.92
                    flags.append(f"REDUCE: Hot streak (SwStr% +{swstr_trend:.1%}) - avoid UNDER")
            elif swstr_trend < -0.03:
                # Cold streak - recent SwStr% 3%+ below season baseline
                if recommendation == 'OVER':
                    confidence_multiplier *= 0.92
                    flags.append(f"REDUCE: Cold streak (SwStr% {swstr_trend:.1%}) - lean UNDER")
                elif recommendation == 'UNDER':
                    confidence_multiplier *= 1.05
                    flags.append(f"SLIGHT BOOST: Cold streak (SwStr% {swstr_trend:.1%})")

        # Minimum multiplier
        confidence_multiplier = max(0.3, confidence_multiplier)

        return RedFlagResult(skip_bet, confidence_multiplier, flags, skip_reason)

    def load_pitcher_features(
        self,
        pitcher_lookup: str,
        game_date: date
    ) -> Optional[Dict]:
        """
        Load features for a pitcher from BigQuery

        Joins:
        - pitcher_game_summary: Core rolling stats and season stats
        - pitcher_rolling_statcast: SwStr% and velocity trends (V1.6)
        - bp_pitcher_props: BettingPros projections for game date (V1.6)

        Args:
            pitcher_lookup: Pitcher identifier
            game_date: Game date

        Returns:
            dict: Features or None if not found
        """
        client = self._get_bq_client()

        # Query with JOINs for V1.6 features
        query = f"""
        WITH base_features AS (
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

                -- V1.4 features (opponent/ballpark context)
                opponent_team_k_rate,
                ballpark_k_factor,
                month_of_season,
                days_into_season,
                vs_opponent_k_per_9 as avg_k_vs_opponent,
                vs_opponent_games as games_vs_opponent,

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
        ),
        -- V1.6: Rolling Statcast features (most recent before game_date)
        statcast_features AS (
            SELECT
                player_lookup,
                swstr_pct_last_3,
                fb_velocity_last_3,
                swstr_pct_last_5,
                swstr_pct_season_prior
            FROM `{self.project_id}.mlb_analytics.pitcher_rolling_statcast`
            WHERE player_lookup = @pitcher_lookup
              AND game_date < @game_date
            ORDER BY game_date DESC
            LIMIT 1
        ),
        -- V1.6: BettingPros projections for game date
        bp_features AS (
            SELECT
                player_lookup,
                projection_value as bp_projection,
                over_line as bp_over_line,
                -- Calculate performance percentages
                SAFE_DIVIDE(perf_last_5_over, perf_last_5_over + perf_last_5_under) as perf_last_5_pct,
                SAFE_DIVIDE(perf_last_10_over, perf_last_10_over + perf_last_10_under) as perf_last_10_pct
            FROM `{self.project_id}.mlb_raw.bp_pitcher_props`
            WHERE player_lookup = @pitcher_lookup
              AND game_date = @game_date
              AND market_name = 'pitcher-strikeouts'
            LIMIT 1
        )
        SELECT
            b.*,
            -- Rolling Statcast (f50-f53)
            s.swstr_pct_last_3,
            s.fb_velocity_last_3,
            -- SwStr% trend: recent vs season baseline
            COALESCE(s.swstr_pct_last_3 - s.swstr_pct_season_prior, 0) as swstr_trend,
            COALESCE(s.fb_velocity_last_3, 0) as velocity_last_3,
            -- BettingPros (f40-f44)
            bp.bp_projection,
            COALESCE(bp.bp_projection - bp.bp_over_line, 0) as projection_diff,
            bp.perf_last_5_pct,
            bp.perf_last_10_pct,
            bp.bp_over_line as strikeouts_line
        FROM base_features b
        LEFT JOIN statcast_features s ON b.player_lookup = s.player_lookup
        LEFT JOIN bp_features bp ON b.player_lookup = bp.player_lookup
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

        Joins V1.6 features:
        - pitcher_game_summary: Core rolling stats
        - pitcher_rolling_statcast: SwStr% and velocity trends
        - bp_pitcher_props: BettingPros projections for game date

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
            pitcher_filter = "AND pgs.player_lookup IN UNNEST(@pitcher_lookups)"
        else:
            pitcher_filter = ""

        query = f"""
        WITH latest_features AS (
            SELECT
                pgs.player_lookup,
                pgs.game_date as feature_date,
                pgs.team_abbr,
                pgs.opponent_team_abbr,
                pgs.is_home,
                pgs.is_postseason,
                pgs.days_rest,
                pgs.k_avg_last_3,
                pgs.k_avg_last_5,
                pgs.k_avg_last_10,
                pgs.k_std_last_10,
                pgs.ip_avg_last_5,
                pgs.season_k_per_9,
                pgs.era_rolling_10,
                pgs.whip_rolling_10,
                pgs.season_games_started,
                pgs.season_strikeouts,
                pgs.season_innings,
                -- V1.4 features
                pgs.opponent_team_k_rate,
                pgs.ballpark_k_factor,
                pgs.month_of_season,
                pgs.days_into_season,
                pgs.vs_opponent_k_per_9 as avg_k_vs_opponent,
                pgs.vs_opponent_games as games_vs_opponent,
                -- Workload
                pgs.games_last_30_days,
                pgs.pitch_count_avg_last_5,
                pgs.data_completeness_score,
                pgs.rolling_stats_games,
                ROW_NUMBER() OVER (PARTITION BY pgs.player_lookup ORDER BY pgs.game_date DESC) as rn
            FROM `{self.project_id}.mlb_analytics.pitcher_game_summary` pgs
            WHERE pgs.game_date < @game_date
              AND pgs.game_date >= DATE_SUB(@game_date, INTERVAL 30 DAY)
              AND pgs.rolling_stats_games >= 3
              {pitcher_filter}
        ),
        -- V1.6: Rolling Statcast features (most recent before game_date)
        statcast_latest AS (
            SELECT
                player_lookup,
                swstr_pct_last_3,
                fb_velocity_last_3,
                swstr_pct_last_5,
                swstr_pct_season_prior,
                ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) as rn
            FROM `{self.project_id}.mlb_analytics.pitcher_rolling_statcast`
            WHERE game_date < @game_date
        ),
        -- V1.6: BettingPros projections for game date
        bp_features AS (
            SELECT
                player_lookup,
                projection_value as bp_projection,
                over_line as bp_over_line,
                -- Calculate performance percentages
                SAFE_DIVIDE(perf_last_5_over, perf_last_5_over + perf_last_5_under) as perf_last_5_pct,
                SAFE_DIVIDE(perf_last_10_over, perf_last_10_over + perf_last_10_under) as perf_last_10_pct
            FROM `{self.project_id}.mlb_raw.bp_pitcher_props`
            WHERE game_date = @game_date
              AND market_name = 'pitcher-strikeouts'
        )
        SELECT
            lf.*,
            -- Rolling Statcast (f50-f53)
            s.swstr_pct_last_3,
            s.fb_velocity_last_3,
            COALESCE(s.swstr_pct_last_3 - s.swstr_pct_season_prior, 0) as swstr_trend,
            COALESCE(s.fb_velocity_last_3, 0) as velocity_last_3,
            -- BettingPros (f40-f44)
            bp.bp_projection,
            COALESCE(bp.bp_projection - bp.bp_over_line, 0) as projection_diff,
            bp.perf_last_5_pct,
            bp.perf_last_10_pct,
            bp.bp_over_line as strikeouts_line
        FROM latest_features lf
        LEFT JOIN statcast_latest s ON lf.player_lookup = s.player_lookup AND s.rn = 1
        LEFT JOIN bp_features bp ON lf.player_lookup = bp.player_lookup
        WHERE lf.rn = 1
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
                # Use strikeouts_line from BettingPros if available
                line = features.get('strikeouts_line')
                prediction = self.predict(
                    pitcher_lookup=features['player_lookup'],
                    features=features,
                    strikeouts_line=line
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
