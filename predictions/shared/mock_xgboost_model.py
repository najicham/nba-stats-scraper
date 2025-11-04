# predictions/shared/mock_xgboost_model.py

"""
Mock XGBoost Model for Testing

Simulates a trained XGBoost model for testing Phase 5 predictions
without requiring actual training data.

This mock model:
- Uses simple heuristics to generate realistic predictions
- Maintains consistency with input features
- Simulates feature importance
- Can be swapped for real model later

Version: 1.0
"""

import numpy as np
from typing import List, Dict, Optional


class MockXGBoostModel:
    """
    Mock XGBoost model that simulates trained ML behavior
    
    This is NOT a real ML model - it uses heuristics to generate
    predictions that look like they came from XGBoost.
    
    When Phase 5 deploys to production with real training data,
    swap this for actual XGBoost model loading.
    """
    
    def __init__(self, seed: Optional[int] = None):
        """
        Initialize mock model
        
        Args:
            seed: Random seed for reproducibility
        """
        if seed is not None:
            np.random.seed(seed)
        
        self.seed = seed
        self.model_version = 'mock_v1'
        self.n_features = 25
        
        # Simulate learned feature importance (from specs)
        self.feature_importance = self._get_feature_importance()
        
        # Learned "optimal" weights (simulated)
        self.feature_weights = self._get_feature_weights()
    
    def predict(self, features: np.ndarray) -> np.ndarray:
        """
        Make prediction on feature array
        
        Args:
            features: Feature array of shape (n_samples, 25) or (25,)
        
        Returns:
            np.ndarray: Predictions (shape: n_samples,)
        """
        # Handle single sample
        if features.ndim == 1:
            features = features.reshape(1, -1)
        
        # Validate shape
        if features.shape[1] != self.n_features:
            raise ValueError(f"Expected {self.n_features} features, got {features.shape[1]}")
        
        predictions = []
        
        for feature_vector in features:
            pred = self._predict_single(feature_vector)
            predictions.append(pred)
        
        return np.array(predictions)
    
    def _predict_single(self, features: np.ndarray) -> float:
        """
        Predict for a single feature vector
        
        Simulates XGBoost by:
        1. Starting with recent performance baseline
        2. Applying learned adjustments based on other features
        3. Adding some variance to simulate model uncertainty
        
        Args:
            features: Single feature vector (25 features)
        
        Returns:
            float: Predicted points
        """
        # Extract key features (indices match feature order)
        points_last_5 = features[0]
        points_last_10 = features[1]
        points_season = features[2]
        points_std = features[3]
        minutes = features[4]
        
        fatigue = features[5]
        zone_mismatch = features[6]
        pace = features[7]
        usage_spike = features[8]
        
        opp_def_rating = features[13]
        opp_pace = features[14]
        is_home = features[15]
        days_rest = features[16]
        back_to_back = features[17]
        
        paint_rate = features[18]
        three_rate = features[20]
        
        team_pace = features[22]
        usage_rate = features[24]
        
        # === STEP 1: Baseline (weighted recent performance) ===
        # XGBoost learns that recent form matters most
        baseline = (
            points_last_5 * 0.35 +
            points_last_10 * 0.40 +
            points_season * 0.25
        )
        
        # === STEP 2: Feature-Based Adjustments ===
        # Simulate what XGBoost learned from training data
        
        # Fatigue impact (non-linear learned pattern)
        if fatigue < 50:
            fatigue_adj = -2.5  # Heavy fatigue
        elif fatigue < 70:
            fatigue_adj = -1.0  # Moderate fatigue
        elif fatigue > 85:
            fatigue_adj = 0.5   # Well-rested boost
        else:
            fatigue_adj = 0.0   # Neutral
        
        # Zone matchup (learned interaction)
        zone_adj = zone_mismatch * 0.35
        
        # Pace interaction (learned that volume scorers benefit more)
        if usage_rate > 28:  # High usage
            pace_adj = pace * 0.12
        else:  # Lower usage
            pace_adj = pace * 0.08
        
        # Usage spike (learned non-linear effect)
        if abs(usage_spike) > 5:
            usage_adj = usage_spike * 0.35  # Strong signal
        else:
            usage_adj = usage_spike * 0.25  # Weak signal
        
        # Opponent defense (learned that elite defense matters)
        if opp_def_rating < 108:  # Elite defense
            def_adj = -1.5
        elif opp_def_rating > 118:  # Weak defense
            def_adj = 1.0
        else:
            def_adj = 0.0
        
        # Back-to-back (learned from historical patterns)
        if back_to_back:
            b2b_adj = -2.2
        else:
            b2b_adj = 0.0
        
        # Venue (learned home court advantage)
        venue_adj = 1.0 if is_home else -0.6
        
        # Minutes played (more minutes = more points, learned correlation)
        if minutes > 36:
            minutes_adj = 0.8
        elif minutes < 25:
            minutes_adj = -1.2
        else:
            minutes_adj = 0.0
        
        # Shot profile interaction (learned that paint-heavy helps vs weak interior)
        if paint_rate > 45 and opp_def_rating > 115:
            shot_adj = 0.8  # Paint scorer vs weak interior
        elif three_rate > 40 and opp_def_rating < 110:
            shot_adj = -0.5  # Perimeter vs elite perimeter
        else:
            shot_adj = 0.0
        
        # === STEP 3: Combine All Adjustments ===
        total_adj = (
            fatigue_adj +
            zone_adj +
            pace_adj +
            usage_adj +
            def_adj +
            b2b_adj +
            venue_adj +
            minutes_adj +
            shot_adj
        )
        
        predicted = baseline + total_adj
        
        # === STEP 4: Add Model Variance ===
        # Real XGBoost has prediction uncertainty
        # Add small random variance to simulate this
        variance = np.random.normal(0, 0.3)  # Small variance
        predicted += variance
        
        # === STEP 5: Clamp to Reasonable Range ===
        predicted = max(0, min(60, predicted))
        
        return predicted
    
    def _get_feature_importance(self) -> Dict[int, float]:
        """
        Simulate feature importance learned by XGBoost
        
        Based on algorithm specs, the most important features are:
        - Recent performance (features 0-2): 14%
        - Shot zone mismatch (feature 6): 11%
        - Pace (feature 7): 6%
        - Opponent defense (feature 13): 8%
        - Usage rate (feature 24): 7%
        
        Returns:
            dict: Feature index → importance (0-1)
        """
        # Initialize all features with low importance
        importance = {i: 0.01 for i in range(self.n_features)}
        
        # High importance features
        importance[0] = 0.14   # points_avg_last_5
        importance[1] = 0.12   # points_avg_last_10
        importance[2] = 0.08   # points_avg_season
        importance[6] = 0.11   # shot_zone_mismatch_score
        importance[7] = 0.06   # pace_score
        importance[13] = 0.08  # opponent_def_rating
        importance[5] = 0.05   # fatigue_score
        importance[24] = 0.07  # usage_rate
        importance[4] = 0.04   # minutes
        importance[17] = 0.03  # back_to_back
        importance[15] = 0.02  # is_home
        
        # Remaining features have 0.01 each (already set)
        
        return importance
    
    def _get_feature_weights(self) -> Dict[int, float]:
        """
        Simulate learned feature weights
        
        Returns:
            dict: Feature index → weight
        """
        return {
            0: 0.35,   # points_last_5
            1: 0.40,   # points_last_10
            2: 0.25,   # points_season
            5: 0.02,   # fatigue
            6: 0.35,   # zone_mismatch
            7: 0.10,   # pace
            8: 0.30,   # usage_spike
            13: 0.05,  # opp_def
            15: 0.50,  # is_home
            17: -2.2,  # back_to_back
        }
    
    def get_feature_importance(self) -> Dict[int, float]:
        """
        Get feature importance scores
        
        Returns:
            dict: Feature index → importance
        """
        return self.feature_importance
    
    def get_model_metadata(self) -> Dict:
        """
        Get model metadata
        
        Returns:
            dict: Model information
        """
        return {
            'model_type': 'mock_xgboost',
            'model_version': self.model_version,
            'n_features': self.n_features,
            'is_mock': True,
            'note': 'This is a mock model for testing. Replace with real XGBoost in production.'
        }


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def load_mock_model(seed: Optional[int] = None) -> MockXGBoostModel:
    """
    Load mock XGBoost model
    
    Args:
        seed: Random seed for reproducibility
    
    Returns:
        MockXGBoostModel: Loaded mock model
    """
    return MockXGBoostModel(seed=seed)


def create_feature_vector(features_dict: Dict) -> np.ndarray:
    """
    Create feature vector array from features dictionary
    
    Features must be in exact order:
    0. points_avg_last_5
    1. points_avg_last_10
    2. points_avg_season
    3. points_std_last_10
    4. minutes_avg_last_10
    5. fatigue_score
    6. shot_zone_mismatch_score
    7. pace_score
    8. usage_spike_score
    9. referee_favorability_score
    10. look_ahead_pressure_score
    11. matchup_history_score
    12. momentum_score
    13. opponent_def_rating_last_15
    14. opponent_pace_last_15
    15. is_home
    16. days_rest
    17. back_to_back
    18. paint_rate_last_10
    19. mid_range_rate_last_10
    20. three_pt_rate_last_10
    21. assisted_rate_last_10
    22. team_pace_last_10
    23. team_off_rating_last_10
    24. usage_rate_last_10
    
    Args:
        features_dict: Dictionary with feature names and values
    
    Returns:
        np.ndarray: Feature vector (shape: 25,)
    """
    feature_order = [
        'points_avg_last_5',
        'points_avg_last_10',
        'points_avg_season',
        'points_std_last_10',
        'minutes_avg_last_10',
        'fatigue_score',
        'shot_zone_mismatch_score',
        'pace_score',
        'usage_spike_score',
        'referee_favorability_score',
        'look_ahead_pressure_score',
        'matchup_history_score',
        'momentum_score',
        'opponent_def_rating_last_15',
        'opponent_pace_last_15',
        'is_home',
        'days_rest',
        'back_to_back',
        'paint_rate_last_10',
        'mid_range_rate_last_10',
        'three_pt_rate_last_10',
        'assisted_rate_last_10',
        'team_pace_last_10',
        'team_off_rating_last_10',
        'usage_rate_last_10'
    ]
    
    feature_vector = []
    
    for feature_name in feature_order:
        value = features_dict.get(feature_name, 0.0)
        feature_vector.append(value)
    
    return np.array(feature_vector)
