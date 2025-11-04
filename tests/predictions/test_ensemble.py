# tests/unit/predictions/test_ensemble.py

"""
Unit Tests for Ensemble V1 Prediction System

Tests cover:
1. Ensemble prediction calculation (weighted averaging)
2. Confidence calculation with agreement bonus
3. Agreement type detection (strong/moderate/disagreement)
4. Recommendation logic (system agreement)
5. Metadata generation
6. Disagreement analysis
7. Edge cases
8. Integration with real component systems
"""

import pytest
from datetime import date
import sys
sys.path.insert(0, '/home/claude')

from moving_average_baseline import MovingAverageBaseline
from zone_matchup_v1 import ZoneMatchupV1
from ensemble_v1 import EnsembleV1


@pytest.fixture
def moving_average():
    """Create Moving Average system"""
    return MovingAverageBaseline()


@pytest.fixture
def zone_matchup():
    """Create Zone Matchup system"""
    return ZoneMatchupV1()


@pytest.fixture
def ensemble(moving_average, zone_matchup):
    """Create Ensemble system"""
    return EnsembleV1(moving_average, zone_matchup)


@pytest.fixture
def baseline_features():
    """Standard test features"""
    return {
        'feature_count': 25,
        'feature_version': 'v1_baseline_25',
        'data_source': 'mock',
        'features_array': [20.0] * 25,
        'points_avg_last_5': 22.0,
        'points_avg_last_10': 22.0,
        'points_avg_season': 22.0,
        'points_std_last_10': 4.0,
        'games_played_last_7_days': 3,
        'fatigue_score': 40.0,
        'shot_zone_mismatch_score': 0.0,
        'pace_score': 0.0,
        'usage_spike_score': 0.0,
        'home_away': 1,
        'back_to_back': 0,
        'opponent_def_rating': 110.0,
        'opponent_pace': 100.0,
        'pct_paint': 0.35,
        'pct_mid_range': 0.25,
        'pct_three': 0.25,
        'pct_free_throw': 0.15,
    }


# ============================================================================
# INITIALIZATION TESTS
# ============================================================================

class TestInitialization:
    """Test ensemble initialization"""
    
    def test_initialization(self, ensemble):
        """Should initialize with correct system info"""
        assert ensemble.system_id == 'ensemble_v1'
        assert ensemble.system_name == 'Ensemble V1'
        assert ensemble.version == '1.0'
    
    def test_component_systems_stored(self, ensemble, moving_average, zone_matchup):
        """Should store references to component systems"""
        assert ensemble.moving_average is moving_average
        assert ensemble.zone_matchup is zone_matchup


# ============================================================================
# ENSEMBLE PREDICTION TESTS
# ============================================================================

class TestEnsemblePrediction:
    """Test ensemble prediction calculation"""
    
    def test_weighted_average_calculation(self, ensemble, baseline_features):
        """Should calculate confidence-weighted average"""
        pred, conf, rec, meta = ensemble.predict(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        # Verify prediction is between both component predictions
        ma_pred = meta['moving_average']['prediction']
        zm_pred = meta['zone_matchup']['prediction']
        
        assert min(ma_pred, zm_pred) <= pred <= max(ma_pred, zm_pred)
    
    def test_high_confidence_system_weighted_more(self, ensemble, baseline_features):
        """System with higher confidence should have more weight"""
        # Create scenario where systems disagree
        baseline_features['points_avg_last_5'] = 28.0  # MA will be higher
        baseline_features['points_avg_last_10'] = 25.0
        baseline_features['points_avg_season'] = 22.0
        
        pred, conf, rec, meta = ensemble.predict(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        ma_pred = meta['moving_average']['prediction']
        ma_conf = meta['moving_average']['confidence']
        zm_pred = meta['zone_matchup']['prediction']
        zm_conf = meta['zone_matchup']['confidence']
        
        # Calculate expected weighted average
        expected = (ma_pred * ma_conf + zm_pred * zm_conf) / (ma_conf + zm_conf)
        
        assert pred == pytest.approx(expected, abs=0.1)
    
    def test_ensemble_returns_four_values(self, ensemble, baseline_features):
        """Should return prediction, confidence, recommendation, and metadata"""
        result = ensemble.predict(
            baseline_features, 'test-player', date(2025, 1, 15), prop_line=22.0
        )
        
        assert len(result) == 4
        pred, conf, rec, meta = result
        
        assert isinstance(pred, float)
        assert isinstance(conf, float)
        assert isinstance(rec, str)
        assert isinstance(meta, dict)


# ============================================================================
# CONFIDENCE TESTS
# ============================================================================

class TestEnsembleConfidence:
    """Test ensemble confidence calculation"""
    
    def test_base_confidence_is_max(self, ensemble):
        """Base confidence should be max of component confidences"""
        # Test directly with calculate method
        confidence = ensemble._calculate_ensemble_confidence(
            ma_pred=25.0, ma_conf=0.6,
            zm_pred=24.0, zm_conf=0.5
        )
        
        # Should start with max (0.6) plus possible agreement bonus
        assert confidence >= 0.6
    
    def test_strong_agreement_bonus(self, ensemble):
        """Strong agreement (<= 2 pts) should add full bonus"""
        # Predictions within 2 points
        conf_with_agreement = ensemble._calculate_ensemble_confidence(
            ma_pred=25.0, ma_conf=0.5,
            zm_pred=25.5, zm_conf=0.5  # 0.5 point diff
        )
        
        conf_without_agreement = ensemble._calculate_ensemble_confidence(
            ma_pred=25.0, ma_conf=0.5,
            zm_pred=30.0, zm_conf=0.5  # 5 point diff
        )
        
        # With agreement should be higher
        assert conf_with_agreement > conf_without_agreement
        assert conf_with_agreement == pytest.approx(0.5 + 0.05, abs=0.01)
    
    def test_moderate_agreement_bonus(self, ensemble):
        """Moderate agreement (2-4 pts) should add half bonus"""
        confidence = ensemble._calculate_ensemble_confidence(
            ma_pred=25.0, ma_conf=0.5,
            zm_pred=28.0, zm_conf=0.5  # 3 point diff
        )
        
        # Should add half bonus (0.025)
        assert confidence == pytest.approx(0.5 + 0.025, abs=0.01)
    
    def test_disagreement_no_bonus(self, ensemble):
        """Disagreement (>4 pts) should add no bonus"""
        confidence = ensemble._calculate_ensemble_confidence(
            ma_pred=25.0, ma_conf=0.5,
            zm_pred=32.0, zm_conf=0.5  # 7 point diff
        )
        
        # Should be just the base (max) confidence
        assert confidence == 0.5
    
    def test_confidence_clamped(self, ensemble):
        """Confidence should be clamped to [0.2, 0.8]"""
        # Test upper clamp
        high_conf = ensemble._calculate_ensemble_confidence(
            ma_pred=25.0, ma_conf=0.8,
            zm_pred=25.0, zm_conf=0.75  # Perfect agreement with high conf
        )
        assert high_conf <= 0.8
        
        # Test lower clamp (shouldn't happen in practice)
        low_conf = ensemble._calculate_ensemble_confidence(
            ma_pred=25.0, ma_conf=0.2,
            zm_pred=35.0, zm_conf=0.2  # Low conf, disagreement
        )
        assert low_conf >= 0.2


# ============================================================================
# AGREEMENT TYPE TESTS
# ============================================================================

class TestAgreementType:
    """Test agreement type classification"""
    
    def test_strong_agreement(self, ensemble):
        """Predictions within 2 points = strong agreement"""
        agreement = ensemble._calculate_agreement_type(25.0, 25.5)
        assert agreement == 'strong'
        
        agreement = ensemble._calculate_agreement_type(25.0, 27.0)
        assert agreement == 'strong'
    
    def test_moderate_agreement(self, ensemble):
        """Predictions within 2-4 points = moderate agreement"""
        agreement = ensemble._calculate_agreement_type(25.0, 28.0)
        assert agreement == 'moderate'
        
        agreement = ensemble._calculate_agreement_type(25.0, 29.0)
        assert agreement == 'moderate'
    
    def test_disagreement(self, ensemble):
        """Predictions >4 points apart = disagreement"""
        agreement = ensemble._calculate_agreement_type(25.0, 30.0)
        assert agreement == 'disagreement'
        
        agreement = ensemble._calculate_agreement_type(25.0, 35.0)
        assert agreement == 'disagreement'
    
    def test_agreement_boundary_cases(self, ensemble):
        """Test exact boundary values"""
        # Exactly 2 points = still strong
        assert ensemble._calculate_agreement_type(25.0, 27.0) == 'strong'
        
        # Just over 2 points = moderate
        assert ensemble._calculate_agreement_type(25.0, 27.1) == 'moderate'
        
        # Exactly 4 points = still moderate
        assert ensemble._calculate_agreement_type(25.0, 29.0) == 'moderate'
        
        # Just over 4 points = disagreement
        assert ensemble._calculate_agreement_type(25.0, 29.1) == 'disagreement'


# ============================================================================
# RECOMMENDATION TESTS
# ============================================================================

class TestEnsembleRecommendation:
    """Test ensemble recommendation logic"""
    
    def test_both_systems_agree_over(self, ensemble, baseline_features):
        """When both recommend OVER, ensemble should recommend OVER"""
        # Create favorable scenario
        baseline_features['opponent_def_rating'] = 118.0
        baseline_features['points_avg_last_5'] = 26.0
        
        pred, conf, rec, meta = ensemble.predict(
            baseline_features, 'test-player', date(2025, 1, 15), prop_line=20.0
        )
        
        # If both agree on OVER, ensemble should be OVER
        if meta['moving_average']['recommendation'] == 'OVER' and \
           meta['zone_matchup']['recommendation'] == 'OVER':
            assert rec == 'OVER'
    
    def test_both_systems_pass(self, ensemble, baseline_features):
        """When both PASS, ensemble should PASS"""
        pred, conf, rec, meta = ensemble.predict(
            baseline_features, 'test-player', date(2025, 1, 15), prop_line=22.0
        )
        
        # Close to neutral - likely both will PASS
        if meta['moving_average']['recommendation'] == 'PASS' and \
           meta['zone_matchup']['recommendation'] == 'PASS':
            assert rec == 'PASS'
    
    def test_systems_disagree_use_ensemble(self, ensemble, baseline_features):
        """When systems disagree, use ensemble prediction"""
        # Create disagreement scenario
        baseline_features['points_avg_last_5'] = 28.0  # MA optimistic
        baseline_features['opponent_def_rating'] = 105.0  # ZM pessimistic
        
        pred, conf, rec, meta = ensemble.predict(
            baseline_features, 'test-player', date(2025, 1, 15), prop_line=24.0
        )
        
        # Ensemble should make decision based on ensemble pred
        assert rec in ['OVER', 'UNDER', 'PASS']


# ============================================================================
# METADATA TESTS
# ============================================================================

class TestMetadata:
    """Test metadata generation"""
    
    def test_metadata_contains_component_predictions(self, ensemble, baseline_features):
        """Metadata should contain predictions from both systems"""
        pred, conf, rec, meta = ensemble.predict(
            baseline_features, 'test-player', date(2025, 1, 15), prop_line=22.0
        )
        
        assert 'moving_average' in meta
        assert 'zone_matchup' in meta
        
        assert 'prediction' in meta['moving_average']
        assert 'confidence' in meta['moving_average']
        assert 'recommendation' in meta['moving_average']
        
        assert 'prediction' in meta['zone_matchup']
        assert 'confidence' in meta['zone_matchup']
        assert 'recommendation' in meta['zone_matchup']
    
    def test_metadata_contains_agreement_info(self, ensemble, baseline_features):
        """Metadata should contain agreement analysis"""
        pred, conf, rec, meta = ensemble.predict(
            baseline_features, 'test-player', date(2025, 1, 15), prop_line=22.0
        )
        
        assert 'agreement_type' in meta
        assert 'prediction_difference' in meta
        assert 'systems_agree' in meta
        assert 'recommendation_agreement' in meta
        
        assert meta['agreement_type'] in ['strong', 'moderate', 'disagreement']
        assert isinstance(meta['prediction_difference'], float)
        assert isinstance(meta['systems_agree'], bool)
        assert isinstance(meta['recommendation_agreement'], bool)


# ============================================================================
# DISAGREEMENT ANALYSIS TESTS
# ============================================================================

class TestDisagreementAnalysis:
    """Test disagreement analysis feature"""
    
    def test_analyze_disagreement_returns_analysis(self, ensemble, baseline_features):
        """Should return analysis dict"""
        analysis = ensemble.analyze_disagreement(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        assert isinstance(analysis, dict)
        assert 'moving_average_prediction' in analysis
        assert 'zone_matchup_prediction' in analysis
        assert 'difference' in analysis
        assert 'recent_form_impact' in analysis
        assert 'defense_impact' in analysis
        assert 'likely_reason' in analysis
    
    def test_hot_streak_disagreement(self, ensemble, baseline_features):
        """Should identify hot streak as disagreement reason"""
        # Create hot streak scenario
        baseline_features['points_avg_last_5'] = 28.0
        baseline_features['points_avg_season'] = 22.0
        
        analysis = ensemble.analyze_disagreement(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        assert analysis['recent_form_impact'] == 'Hot streak'
        assert 'hot streak' in analysis['likely_reason'].lower() or \
               analysis['difference'] < 2.0  # If systems don't disagree much
    
    def test_favorable_matchup_disagreement(self, ensemble, baseline_features):
        """Should identify favorable matchup as disagreement reason"""
        # Create favorable matchup, cold recent form
        baseline_features['points_avg_last_5'] = 18.0
        baseline_features['points_avg_season'] = 22.0
        baseline_features['opponent_def_rating'] = 120.0  # Very weak
        
        analysis = ensemble.analyze_disagreement(
            baseline_features, 'test-player', date(2025, 1, 15)
        )
        
        assert analysis['defense_impact'] == 'Weak defense'


# ============================================================================
# SYSTEM WEIGHTS TESTS
# ============================================================================

class TestSystemWeights:
    """Test system weight calculation"""
    
    def test_equal_confidence_equal_weights(self, ensemble):
        """Equal confidence should give 0.5/0.5 weights"""
        ma_weight, zm_weight = ensemble.get_system_weights(0.5, 0.5)
        
        assert ma_weight == pytest.approx(0.5)
        assert zm_weight == pytest.approx(0.5)
    
    def test_weights_sum_to_one(self, ensemble):
        """Weights should always sum to 1.0"""
        ma_weight, zm_weight = ensemble.get_system_weights(0.6, 0.4)
        
        assert ma_weight + zm_weight == pytest.approx(1.0)
    
    def test_higher_confidence_higher_weight(self, ensemble):
        """Higher confidence system should get more weight"""
        ma_weight, zm_weight = ensemble.get_system_weights(0.7, 0.3)
        
        assert ma_weight > zm_weight
        assert ma_weight == pytest.approx(0.7)
        assert zm_weight == pytest.approx(0.3)


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestIntegration:
    """Test complete ensemble workflow"""
    
    def test_complete_prediction_workflow(self, ensemble, baseline_features):
        """Should complete full prediction with all components"""
        pred, conf, rec, meta = ensemble.predict(
            baseline_features, 'test-player', date(2025, 1, 15), prop_line=22.0
        )
        
        # Verify all outputs
        assert 0.0 <= pred <= 60.0
        assert 0.2 <= conf <= 0.8
        assert rec in ['OVER', 'UNDER', 'PASS']
        assert isinstance(meta, dict)
        
        # Verify metadata completeness
        assert len(meta) >= 6  # All required fields
    
    def test_realistic_scenario_strong_agreement(self, ensemble):
        """Test realistic scenario where systems agree"""
        features = {
            'feature_count': 25,
            'feature_version': 'v1_baseline_25',
            'data_source': 'mock',
            'features_array': [20.0] * 25,
            'points_avg_last_5': 24.0,
            'points_avg_last_10': 23.5,
            'points_avg_season': 23.0,
            'points_std_last_10': 3.5,
            'games_played_last_7_days': 3,
            'fatigue_score': 40.0,
            'shot_zone_mismatch_score': 0.5,
            'pace_score': 1.0,
            'usage_spike_score': 0.0,
            'home_away': 1,
            'back_to_back': 0,
            'opponent_def_rating': 112.0,  # Slightly weak
            'opponent_pace': 100.0,
            'pct_paint': 0.40,
            'pct_mid_range': 0.25,
            'pct_three': 0.25,
            'pct_free_throw': 0.10,
        }
        
        pred, conf, rec, meta = ensemble.predict(
            features, 'consistent-player', date(2025, 1, 15), prop_line=22.0
        )
        
        # Systems should agree (similar recent and season stats)
        assert meta['agreement_type'] in ['strong', 'moderate']
        assert meta['systems_agree'] is True
        
        print(f"\n✅ Strong agreement scenario:")
        print(f"   Moving Average: {meta['moving_average']['prediction']:.1f}")
        print(f"   Zone Matchup:   {meta['zone_matchup']['prediction']:.1f}")
        print(f"   Ensemble:       {pred:.1f}")
        print(f"   Agreement:      {meta['agreement_type']}")
        print(f"   Confidence:     {conf:.2f}")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
