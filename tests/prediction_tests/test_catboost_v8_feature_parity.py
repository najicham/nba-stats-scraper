# tests/prediction_tests/test_catboost_v8_feature_parity.py

"""
CatBoost V8 Feature Parity Tests

Prevention Task #10 from PREVENTION-PLAN.md:
Tests that verify feature parity between training and inference to prevent
bugs like the +29 point inflation bug caused by missing features.

Tests cover:
1. Training feature order matches inference feature order exactly
2. All 33 features are populated at inference time
3. has_vegas_line=1.0 when prop line exists
4. Predictions stay in reasonable range (5-50 points)

Run with: pytest tests/prediction_tests/test_catboost_v8_feature_parity.py -v
"""

import pytest
import numpy as np
import sys
import os
from datetime import date
from typing import Dict, List

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from predictions.worker.prediction_systems.catboost_v8 import (
    CatBoostV8,
    V8_FEATURES,
    classify_fallback_severity,
    get_fallback_details,
    FallbackSeverity,
    CRITICAL_FEATURES,
    MAJOR_FEATURES,
)


# =============================================================================
# TRAINING FEATURES (from ml/train_final_ensemble_v8.py)
# =============================================================================
# These are the features used during model training.
# They must be kept in sync with the training script.

TRAINING_BASE_FEATURES = [
    "points_avg_last_5",
    "points_avg_last_10",
    "points_avg_season",
    "points_std_last_10",
    "games_in_last_7_days",
    "fatigue_score",
    "shot_zone_mismatch_score",
    "pace_score",
    "usage_spike_score",
    "rest_advantage",
    "injury_risk",
    "recent_trend",
    "minutes_change",
    "opponent_def_rating",
    "opponent_pace",
    "home_away",
    "back_to_back",
    "playoff_game",
    "pct_paint",
    "pct_mid_range",
    "pct_three",
    "pct_free_throw",
    "team_pace",
    "team_off_rating",
    "team_win_pct",
]

# Additional features added to base features during training
TRAINING_ADDITIONAL_FEATURES = [
    "vegas_points_line",
    "vegas_opening_line",
    "vegas_line_move",
    "has_vegas_line",
    "avg_points_vs_opponent",
    "games_vs_opponent",
    "minutes_avg_last_10",
    "ppm_avg_last_10",
]

# Complete training feature order (33 features)
TRAINING_FEATURES = TRAINING_BASE_FEATURES + TRAINING_ADDITIONAL_FEATURES

# Note: V8_FEATURES includes 'has_shot_zone_data' (feature #33, index 33)
# which was added after the original v8 training on 2026-01-25.
# The first 33 features must match exactly.
INFERENCE_FEATURES_ORIGINAL_33 = V8_FEATURES[:33]


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def catboost_system():
    """Create CatBoost V8 system (model may not load in test environment)"""
    # Initialize without model - tests focus on feature handling, not predictions
    system = CatBoostV8(use_local=False)
    return system


@pytest.fixture
def complete_feature_dict():
    """
    Complete feature dictionary with all 33 V8 features populated.

    This represents what the ML Feature Store v2 should provide.
    """
    return {
        # Metadata required by CatBoost V8
        'feature_version': 'v2_33features',
        'feature_count': 33,
        'features_array': [0.0] * 33,  # Placeholder
        'player_lookup': 'test-player',

        # Base features (25)
        'points_avg_last_5': 22.5,
        'points_avg_last_10': 21.8,
        'points_avg_season': 20.5,
        'points_std_last_10': 4.2,
        'games_in_last_7_days': 3,
        'fatigue_score': 75.0,
        'shot_zone_mismatch_score': 2.5,
        'pace_score': 0.5,
        'usage_spike_score': 0.0,
        'rest_advantage': 0.0,
        'injury_risk': 0.0,
        'recent_trend': 0.8,
        'minutes_change': 0.0,
        'opponent_def_rating': 112.0,
        'opponent_pace': 100.0,
        'home_away': 1.0,
        'back_to_back': 0.0,
        'playoff_game': 0.0,
        'pct_paint': 42.0,
        'pct_mid_range': 18.0,
        'pct_three': 28.0,
        'pct_free_throw': 12.0,
        'team_pace': 100.5,
        'team_off_rating': 115.0,
        'team_win_pct': 0.55,

        # Vegas features (4)
        'vegas_points_line': 21.5,
        'vegas_opening_line': 20.5,
        'vegas_line_move': 1.0,
        'has_vegas_line': 1.0,

        # Opponent history (2)
        'avg_points_vs_opponent': 23.0,
        'games_vs_opponent': 5.0,

        # Minutes/PPM history (2)
        'minutes_avg_last_10': 32.5,
        'ppm_avg_last_10': 0.65,

        # Shot zone data availability (1) - added 2026-01-25
        'has_shot_zone_data': 1.0,

        # Quality score for confidence calculation
        'feature_quality_score': 85.0,
    }


@pytest.fixture
def minimal_feature_dict():
    """
    Minimal feature dictionary with only base 25 features.

    This simulates the bug scenario where Vegas/opponent/PPM features are missing.
    """
    return {
        'feature_version': 'v2_33features',
        'feature_count': 33,
        'features_array': [0.0] * 33,
        'player_lookup': 'test-player',

        # Only base features
        'points_avg_last_5': 22.5,
        'points_avg_last_10': 21.8,
        'points_avg_season': 20.5,
        'points_std_last_10': 4.2,
        'games_in_last_7_days': 3,
        'fatigue_score': 75.0,
        'shot_zone_mismatch_score': 2.5,
        'pace_score': 0.5,
        'usage_spike_score': 0.0,
        'rest_advantage': 0.0,
        'injury_risk': 0.0,
        'recent_trend': 0.8,
        'minutes_change': 0.0,
        'opponent_def_rating': 112.0,
        'opponent_pace': 100.0,
        'home_away': 1.0,
        'back_to_back': 0.0,
        'playoff_game': 0.0,
        'pct_paint': 42.0,
        'pct_mid_range': 18.0,
        'pct_three': 28.0,
        'pct_free_throw': 12.0,
        'team_pace': 100.5,
        'team_off_rating': 115.0,
        'team_win_pct': 0.55,

        # Vegas/opponent/PPM features are MISSING

        'feature_quality_score': 70.0,
    }


# =============================================================================
# TEST CLASS 1: Feature Order Parity
# =============================================================================

class TestTrainingInferenceFeatureOrderMatches:
    """
    Test that training and inference use exactly the same feature order.

    This is CRITICAL because CatBoost uses feature indices, not names.
    If the order differs, the model will interpret features incorrectly.
    """

    def test_training_has_33_features(self):
        """Training should use exactly 33 features"""
        assert len(TRAINING_FEATURES) == 33, (
            f"Training uses {len(TRAINING_FEATURES)} features, expected 33"
        )

    def test_inference_has_at_least_33_features(self):
        """Inference V8_FEATURES should have at least 33 features"""
        assert len(V8_FEATURES) >= 33, (
            f"V8_FEATURES has {len(V8_FEATURES)} features, expected at least 33"
        )

    def test_first_33_features_match_exactly(self):
        """First 33 features in V8_FEATURES must match training exactly"""
        for i, (train_feat, infer_feat) in enumerate(zip(TRAINING_FEATURES, INFERENCE_FEATURES_ORIGINAL_33)):
            assert train_feat == infer_feat, (
                f"Feature mismatch at index {i}: "
                f"training has '{train_feat}', inference has '{infer_feat}'"
            )

    def test_base_features_order(self):
        """Base 25 features should be in exact order"""
        for i, feat in enumerate(TRAINING_BASE_FEATURES):
            assert V8_FEATURES[i] == feat, (
                f"Base feature mismatch at index {i}: "
                f"expected '{feat}', got '{V8_FEATURES[i]}'"
            )

    def test_vegas_features_at_correct_indices(self):
        """Vegas features should be at indices 25-28"""
        expected_vegas = ["vegas_points_line", "vegas_opening_line", "vegas_line_move", "has_vegas_line"]
        for i, feat in enumerate(expected_vegas):
            idx = 25 + i
            assert V8_FEATURES[idx] == feat, (
                f"Vegas feature mismatch at index {idx}: "
                f"expected '{feat}', got '{V8_FEATURES[idx]}'"
            )

    def test_opponent_features_at_correct_indices(self):
        """Opponent features should be at indices 29-30"""
        expected_opponent = ["avg_points_vs_opponent", "games_vs_opponent"]
        for i, feat in enumerate(expected_opponent):
            idx = 29 + i
            assert V8_FEATURES[idx] == feat, (
                f"Opponent feature mismatch at index {idx}: "
                f"expected '{feat}', got '{V8_FEATURES[idx]}'"
            )

    def test_minutes_ppm_features_at_correct_indices(self):
        """Minutes/PPM features should be at indices 31-32"""
        expected_ppm = ["minutes_avg_last_10", "ppm_avg_last_10"]
        for i, feat in enumerate(expected_ppm):
            idx = 31 + i
            assert V8_FEATURES[idx] == feat, (
                f"Minutes/PPM feature mismatch at index {idx}: "
                f"expected '{feat}', got '{V8_FEATURES[idx]}'"
            )

    def test_feature_names_no_typos(self):
        """Feature names should not have common typos"""
        for feat in V8_FEATURES:
            # Check for common typos
            assert 'avaerage' not in feat.lower(), f"Typo in feature name: {feat}"
            assert 'oppponent' not in feat.lower(), f"Typo in feature name: {feat}"
            assert 'poitns' not in feat.lower(), f"Typo in feature name: {feat}"
            # Ensure snake_case
            assert feat == feat.lower(), f"Feature name not lowercase: {feat}"
            assert ' ' not in feat, f"Feature name has spaces: {feat}"


# =============================================================================
# TEST CLASS 2: Feature Population at Inference
# =============================================================================

class TestInferenceFeaturesPopulated:
    """
    Test that all 33 features are properly populated at inference time.

    This catches the bug where only 25 features were being loaded,
    causing 8 critical features to use default values.
    """

    def test_all_33_features_present_in_complete_dict(self, complete_feature_dict):
        """Complete feature dict should have all 33 features"""
        for feat in TRAINING_FEATURES:
            assert feat in complete_feature_dict, (
                f"Feature '{feat}' missing from complete feature dictionary"
            )

    def test_all_features_have_values(self, complete_feature_dict):
        """All features should have non-None values"""
        for feat in TRAINING_FEATURES:
            value = complete_feature_dict.get(feat)
            assert value is not None, (
                f"Feature '{feat}' has None value in complete feature dictionary"
            )

    def test_feature_values_are_numeric(self, complete_feature_dict):
        """All feature values should be numeric"""
        for feat in TRAINING_FEATURES:
            value = complete_feature_dict.get(feat)
            assert isinstance(value, (int, float)), (
                f"Feature '{feat}' has non-numeric value: {type(value)}"
            )

    def test_critical_features_populated(self, complete_feature_dict):
        """Critical features (vegas_points_line, has_vegas_line, ppm_avg_last_10) must be present"""
        for feat in CRITICAL_FEATURES:
            assert feat in complete_feature_dict, (
                f"Critical feature '{feat}' missing from feature dictionary"
            )
            assert complete_feature_dict[feat] is not None, (
                f"Critical feature '{feat}' is None"
            )

    def test_detect_missing_v8_features(self, minimal_feature_dict):
        """Should detect when V8-specific features are missing"""
        missing_features = []
        for feat in TRAINING_ADDITIONAL_FEATURES:
            if feat not in minimal_feature_dict or minimal_feature_dict.get(feat) is None:
                missing_features.append(feat)

        # The minimal dict is missing these features intentionally
        assert len(missing_features) == 8, (
            f"Expected 8 missing features, got {len(missing_features)}: {missing_features}"
        )

    def test_feature_version_indicates_33_features(self, complete_feature_dict):
        """Feature version should indicate 33-feature format"""
        version = complete_feature_dict.get('feature_version')
        assert version == 'v2_33features', (
            f"Feature version should be 'v2_33features', got '{version}'"
        )


# =============================================================================
# TEST CLASS 3: has_vegas_line Flag Correctness
# =============================================================================

class TestHasVegasLineCorrect:
    """
    Test that has_vegas_line flag is correctly set.

    has_vegas_line should be:
    - 1.0 when vegas_points_line is provided (real prop line exists)
    - 0.0 when vegas_points_line is missing/None (no prop line)

    Getting this wrong causes major prediction errors.
    """

    def test_has_vegas_line_is_1_when_line_exists(self, catboost_system, complete_feature_dict):
        """has_vegas_line should be 1.0 when vegas_points_line is present"""
        # The complete dict has vegas_points_line = 21.5
        vector = catboost_system._prepare_feature_vector(
            features=complete_feature_dict,
            vegas_line=None,  # Use value from features dict
            vegas_opening=None,
            opponent_avg=None,
            games_vs_opponent=0,
            minutes_avg_last_10=None,
            ppm_avg_last_10=None,
        )

        # has_vegas_line is at index 28
        has_vegas_line_index = 28
        assert vector is not None, "Feature vector preparation failed"
        assert vector[0, has_vegas_line_index] == 1.0, (
            f"has_vegas_line should be 1.0 when vegas_points_line exists, "
            f"got {vector[0, has_vegas_line_index]}"
        )

    def test_has_vegas_line_is_0_when_no_line(self, catboost_system, minimal_feature_dict):
        """has_vegas_line should be 0.0 when vegas_points_line is missing"""
        # The minimal dict has no vegas_points_line
        vector = catboost_system._prepare_feature_vector(
            features=minimal_feature_dict,
            vegas_line=None,
            vegas_opening=None,
            opponent_avg=None,
            games_vs_opponent=0,
            minutes_avg_last_10=None,
            ppm_avg_last_10=None,
        )

        has_vegas_line_index = 28
        assert vector is not None, "Feature vector preparation failed"
        assert vector[0, has_vegas_line_index] == 0.0, (
            f"has_vegas_line should be 0.0 when vegas_points_line missing, "
            f"got {vector[0, has_vegas_line_index]}"
        )

    def test_has_vegas_line_uses_param_over_dict(self, catboost_system, minimal_feature_dict):
        """vegas_line parameter should take precedence over features dict"""
        # Pass vegas_line explicitly
        vector = catboost_system._prepare_feature_vector(
            features=minimal_feature_dict,
            vegas_line=25.5,  # Explicitly provided
            vegas_opening=24.5,
            opponent_avg=None,
            games_vs_opponent=0,
            minutes_avg_last_10=None,
            ppm_avg_last_10=None,
        )

        has_vegas_line_index = 28
        vegas_line_index = 25
        assert vector is not None, "Feature vector preparation failed"
        assert vector[0, has_vegas_line_index] == 1.0, (
            "has_vegas_line should be 1.0 when vegas_line param is provided"
        )
        assert vector[0, vegas_line_index] == 25.5, (
            "vegas_points_line should use the provided value"
        )


# =============================================================================
# TEST CLASS 4: Prediction Reasonable Range
# =============================================================================

class TestPredictionReasonableRange:
    """
    Test that predictions stay in a reasonable range.

    NBA player points typically range from 0-60, with most predictions
    in the 5-50 range. Predictions outside this range likely indicate
    a bug (like the +29 point inflation bug).
    """

    def test_prediction_clamped_to_0_60(self, catboost_system, complete_feature_dict):
        """Predictions should be clamped to 0-60 range"""
        # Note: Model may not be loaded in test env, but we test the clamping logic
        result = catboost_system.predict(
            player_lookup='test-player',
            features=complete_feature_dict,
            betting_line=21.5,
        )

        predicted = result.get('predicted_points')
        if predicted is not None:  # Only test if prediction succeeded
            assert 0 <= predicted <= 60, (
                f"Prediction {predicted} outside 0-60 range"
            )

    def test_fallback_prediction_reasonable(self, catboost_system, minimal_feature_dict):
        """Fallback predictions (when model not loaded) should be reasonable"""
        # Force fallback by not loading model
        system = CatBoostV8(use_local=False)
        system.model = None  # Ensure fallback is used

        result = system._fallback_prediction(
            player_lookup='test-player',
            features=minimal_feature_dict,
            betting_line=21.5,
        )

        predicted = result.get('predicted_points')
        assert predicted is not None, "Fallback should return a prediction"
        assert 0 <= predicted <= 60, (
            f"Fallback prediction {predicted} outside 0-60 range"
        )

    def test_fallback_uses_weighted_average(self, catboost_system):
        """Fallback should use weighted average of recent performance"""
        features = {
            'points_avg_last_5': 25.0,
            'points_avg_last_10': 23.0,
            'points_avg_season': 22.0,
        }

        system = CatBoostV8(use_local=False)
        system.model = None

        result = system._fallback_prediction('test-player', features, 24.0)

        # Expected: 0.4 * 25.0 + 0.35 * 23.0 + 0.25 * 22.0 = 23.55
        expected = 0.4 * 25.0 + 0.35 * 23.0 + 0.25 * 22.0
        assert abs(result['predicted_points'] - expected) < 0.01, (
            f"Fallback should be {expected:.2f}, got {result['predicted_points']}"
        )


# =============================================================================
# TEST CLASS 5: Fallback Severity Classification
# =============================================================================

class TestFallbackSeverityClassification:
    """
    Test the fallback severity classification system.

    This ensures loud failures for critical missing features.
    """

    def test_no_fallbacks_returns_none_severity(self):
        """No fallbacks should return NONE severity"""
        severity = classify_fallback_severity([])
        assert severity == FallbackSeverity.NONE

    def test_minor_feature_fallback(self):
        """Minor feature missing should return MINOR severity"""
        severity = classify_fallback_severity(['games_vs_opponent'])
        assert severity == FallbackSeverity.MINOR

    def test_major_feature_fallback(self):
        """Major feature missing should return MAJOR severity"""
        severity = classify_fallback_severity(['minutes_avg_last_10'])
        assert severity == FallbackSeverity.MAJOR

        severity = classify_fallback_severity(['avg_points_vs_opponent'])
        assert severity == FallbackSeverity.MAJOR

    def test_critical_feature_fallback(self):
        """Critical feature missing should return CRITICAL severity"""
        severity = classify_fallback_severity(['vegas_points_line'])
        assert severity == FallbackSeverity.CRITICAL

        severity = classify_fallback_severity(['has_vegas_line'])
        assert severity == FallbackSeverity.CRITICAL

        severity = classify_fallback_severity(['ppm_avg_last_10'])
        assert severity == FallbackSeverity.CRITICAL

    def test_mixed_severity_returns_highest(self):
        """Mixed severity should return the highest severity level"""
        # Minor + Major = Major
        severity = classify_fallback_severity(['games_vs_opponent', 'minutes_avg_last_10'])
        assert severity == FallbackSeverity.MAJOR

        # Minor + Major + Critical = Critical
        severity = classify_fallback_severity(['games_vs_opponent', 'minutes_avg_last_10', 'vegas_points_line'])
        assert severity == FallbackSeverity.CRITICAL

    def test_get_fallback_details(self):
        """get_fallback_details should categorize features correctly"""
        details = get_fallback_details(['vegas_points_line', 'minutes_avg_last_10', 'games_vs_opponent'])

        assert details['severity'] == 'critical'
        assert details['total_fallbacks'] == 3
        assert 'vegas_points_line' in details['critical_features']
        assert 'minutes_avg_last_10' in details['major_features']
        assert 'games_vs_opponent' in details['minor_features']


# =============================================================================
# TEST CLASS 6: Feature Vector Preparation
# =============================================================================

class TestFeatureVectorPreparation:
    """
    Test feature vector preparation for model input.
    """

    def test_feature_vector_has_correct_shape(self, catboost_system, complete_feature_dict):
        """Feature vector should have shape (1, 34) for 34-feature model"""
        vector = catboost_system._prepare_feature_vector(
            features=complete_feature_dict,
            vegas_line=None,
            vegas_opening=None,
            opponent_avg=None,
            games_vs_opponent=0,
            minutes_avg_last_10=None,
            ppm_avg_last_10=None,
        )

        assert vector is not None, "Feature vector should not be None"
        assert vector.shape == (1, 34), (
            f"Expected shape (1, 34), got {vector.shape}"
        )

    def test_feature_vector_preserves_order(self, catboost_system, complete_feature_dict):
        """Feature vector should preserve exact feature order"""
        vector = catboost_system._prepare_feature_vector(
            features=complete_feature_dict,
            vegas_line=None,
            vegas_opening=None,
            opponent_avg=None,
            games_vs_opponent=0,
            minutes_avg_last_10=None,
            ppm_avg_last_10=None,
        )

        assert vector is not None

        # Check a few key positions
        assert vector[0, 0] == complete_feature_dict['points_avg_last_5']  # Index 0
        assert vector[0, 2] == complete_feature_dict['points_avg_season']  # Index 2
        assert vector[0, 25] == complete_feature_dict['vegas_points_line']  # Index 25
        assert vector[0, 28] == complete_feature_dict['has_vegas_line']  # Index 28

    def test_shot_zone_features_handle_nan(self, catboost_system):
        """Shot zone features (18-20) should allow NaN values"""
        features = {
            'feature_version': 'v2_33features',
            'feature_count': 33,
            'features_array': [0.0] * 33,
            'points_avg_last_5': 20.0,
            'points_avg_last_10': 20.0,
            'points_avg_season': 20.0,
            # Shot zone features explicitly None
            'pct_paint': None,
            'pct_mid_range': None,
            'pct_three': None,
            'has_shot_zone_data': 0.0,  # Indicates missing
        }

        vector = catboost_system._prepare_feature_vector(
            features=features,
            vegas_line=None,
            vegas_opening=None,
            opponent_avg=None,
            games_vs_opponent=0,
            minutes_avg_last_10=None,
            ppm_avg_last_10=None,
        )

        assert vector is not None, "Should allow NaN in shot zone features"
        # Shot zone features at indices 18, 19, 20
        assert np.isnan(vector[0, 18]), "pct_paint should be NaN when None"
        assert np.isnan(vector[0, 19]), "pct_mid_range should be NaN when None"
        assert np.isnan(vector[0, 20]), "pct_three should be NaN when None"


# =============================================================================
# TEST CLASS 7: Model Contract Validation (if available)
# =============================================================================

class TestModelContractValidation:
    """
    Test model contract validation for V8 features.

    Model contracts define expected feature properties and should be
    validated during inference to catch data issues early.
    """

    def test_critical_features_defined(self):
        """CRITICAL_FEATURES should contain the most important features"""
        assert 'vegas_points_line' in CRITICAL_FEATURES
        assert 'has_vegas_line' in CRITICAL_FEATURES
        assert 'ppm_avg_last_10' in CRITICAL_FEATURES

    def test_major_features_defined(self):
        """MAJOR_FEATURES should contain important features"""
        assert 'avg_points_vs_opponent' in MAJOR_FEATURES
        assert 'minutes_avg_last_10' in MAJOR_FEATURES

    def test_no_overlap_between_severity_categories(self):
        """Feature severity categories should not overlap"""
        overlap = CRITICAL_FEATURES & MAJOR_FEATURES
        assert len(overlap) == 0, (
            f"Features should not be in multiple severity categories: {overlap}"
        )


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
