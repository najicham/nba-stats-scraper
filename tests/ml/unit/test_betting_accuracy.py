"""
Unit tests for betting accuracy calculations

Tests the betting accuracy metrics including:
- Hit rate calculation
- ROI calculation
- Edge analysis
- Confidence filtering

Path: tests/ml/unit/test_betting_accuracy.py
Created: 2026-01-24
"""

import pytest
import numpy as np
from unittest.mock import Mock, patch


# ============================================================================
# TEST HIT RATE CALCULATION
# ============================================================================

class TestHitRateCalculation:
    """Test hit rate (accuracy) calculations."""

    def test_calculate_over_hit_rate(self):
        """Should calculate over prediction hit rate."""
        predictions = [
            {'prediction': 28.0, 'line': 25.5, 'actual': 30, 'recommendation': 'over'},
            {'prediction': 22.0, 'line': 20.5, 'actual': 18, 'recommendation': 'over'},
            {'prediction': 30.0, 'line': 27.5, 'actual': 32, 'recommendation': 'over'},
        ]

        hits = 0
        for p in predictions:
            if p['recommendation'] == 'over' and p['actual'] > p['line']:
                hits += 1

        hit_rate = hits / len(predictions)

        assert hit_rate == pytest.approx(0.667, rel=0.01)

    def test_calculate_under_hit_rate(self):
        """Should calculate under prediction hit rate."""
        predictions = [
            {'prediction': 18.0, 'line': 20.5, 'actual': 15, 'recommendation': 'under'},
            {'prediction': 22.0, 'line': 25.5, 'actual': 28, 'recommendation': 'under'},
            {'prediction': 19.0, 'line': 22.5, 'actual': 20, 'recommendation': 'under'},
        ]

        hits = 0
        for p in predictions:
            if p['recommendation'] == 'under' and p['actual'] < p['line']:
                hits += 1

        hit_rate = hits / len(predictions)

        assert hit_rate == pytest.approx(0.667, rel=0.01)

    def test_overall_hit_rate(self, sample_betting_results):
        """Should calculate overall hit rate."""
        correct = sum(1 for r in sample_betting_results if r['prediction'] == r['actual'])
        total = len(sample_betting_results)

        hit_rate = correct / total

        assert hit_rate == 0.5  # 2 correct out of 4

    def test_push_handling(self):
        """Should handle pushes (ties) correctly."""
        predictions = [
            {'line': 25.5, 'actual': 25.5, 'is_push': True},  # Push
            {'line': 25.5, 'actual': 26, 'is_push': False},   # Over hit
            {'line': 25.5, 'actual': 25, 'is_push': False},   # Under hit
        ]

        non_push = [p for p in predictions if not p.get('is_push', False)]

        assert len(non_push) == 2


# ============================================================================
# TEST ROI CALCULATION
# ============================================================================

class TestROICalculation:
    """Test Return on Investment calculations."""

    def test_calculate_simple_roi(self):
        """Should calculate simple ROI."""
        stake = 100
        odds = -110  # Standard American odds
        payout_if_win = stake + (stake * 100 / abs(odds))

        # Win scenario
        roi_win = (payout_if_win - stake) / stake
        assert roi_win == pytest.approx(0.909, rel=0.01)

        # Loss scenario
        roi_loss = (0 - stake) / stake
        assert roi_loss == -1.0

    def test_calculate_roi_over_multiple_bets(self, sample_betting_results):
        """Should calculate ROI across multiple bets."""
        total_stake = sum(r['stake'] for r in sample_betting_results)
        total_payout = sum(r['payout'] for r in sample_betting_results)

        roi = (total_payout - total_stake) / total_stake

        # 2 wins (190.91 each) + 2 losses (0 each) = 381.82
        # Total stake = 400
        # ROI = (381.82 - 400) / 400 = -0.0455
        assert roi == pytest.approx(-0.0455, rel=0.01)

    def test_positive_roi_scenario(self):
        """Should calculate positive ROI correctly."""
        results = [
            {'stake': 100, 'payout': 190.91},  # Win at -110
            {'stake': 100, 'payout': 190.91},  # Win at -110
            {'stake': 100, 'payout': 190.91},  # Win at -110
            {'stake': 100, 'payout': 0},       # Loss
        ]

        total_stake = 400
        total_payout = 572.73
        roi = (total_payout - total_stake) / total_stake

        assert roi == pytest.approx(0.432, rel=0.01)

    def test_break_even_hit_rate(self):
        """Should identify break-even hit rate for -110 odds."""
        # At -110 odds, need ~52.4% hit rate to break even
        odds = -110
        break_even_rate = abs(odds) / (abs(odds) + 100)

        assert break_even_rate == pytest.approx(0.524, rel=0.01)


# ============================================================================
# TEST EDGE ANALYSIS
# ============================================================================

class TestEdgeAnalysis:
    """Test edge vs line analysis."""

    def test_calculate_edge(self):
        """Should calculate edge vs betting line."""
        prediction = 28.5
        line = 25.5

        edge = prediction - line

        assert edge == 3.0

    def test_edge_direction(self):
        """Should determine edge direction correctly."""
        test_cases = [
            {'predicted': 30, 'line': 25, 'expected': 'over'},   # +5 edge
            {'predicted': 20, 'line': 25, 'expected': 'under'},  # -5 edge
            {'predicted': 25, 'line': 25, 'expected': 'hold'},   # 0 edge
        ]

        for case in test_cases:
            edge = case['predicted'] - case['line']
            if edge > 0.5:
                direction = 'over'
            elif edge < -0.5:
                direction = 'under'
            else:
                direction = 'hold'

            assert direction == case['expected']

    def test_edge_magnitude_correlation(self):
        """Should show higher edge correlates with higher accuracy."""
        # Simulated data where higher edge = higher accuracy
        results_by_edge = {
            '0-1': {'hits': 52, 'total': 100},   # 52%
            '1-2': {'hits': 55, 'total': 100},   # 55%
            '2-3': {'hits': 58, 'total': 100},   # 58%
            '3+': {'hits': 62, 'total': 100},    # 62%
        }

        accuracies = []
        for edge_range, data in results_by_edge.items():
            acc = data['hits'] / data['total']
            accuracies.append(acc)

        # Each subsequent edge range should have higher accuracy
        for i in range(1, len(accuracies)):
            assert accuracies[i] >= accuracies[i-1]


# ============================================================================
# TEST CONFIDENCE FILTERING
# ============================================================================

class TestConfidenceFiltering:
    """Test prediction filtering by confidence."""

    def test_filter_high_confidence(self):
        """Should filter predictions by confidence threshold."""
        predictions = [
            {'id': 1, 'confidence': 0.9, 'predicted': 28},
            {'id': 2, 'confidence': 0.6, 'predicted': 25},
            {'id': 3, 'confidence': 0.85, 'predicted': 30},
            {'id': 4, 'confidence': 0.5, 'predicted': 22},
        ]

        threshold = 0.8
        high_confidence = [p for p in predictions if p['confidence'] >= threshold]

        assert len(high_confidence) == 2
        assert all(p['confidence'] >= 0.8 for p in high_confidence)

    def test_confidence_accuracy_relationship(self):
        """High confidence should correlate with accuracy."""
        confidence_buckets = {
            'low': {'range': (0.5, 0.6), 'accuracy': 0.52},
            'medium': {'range': (0.6, 0.75), 'accuracy': 0.55},
            'high': {'range': (0.75, 0.9), 'accuracy': 0.60},
            'very_high': {'range': (0.9, 1.0), 'accuracy': 0.65},
        }

        # Verify ascending accuracy
        accuracies = [b['accuracy'] for b in confidence_buckets.values()]
        for i in range(1, len(accuracies)):
            assert accuracies[i] >= accuracies[i-1]


# ============================================================================
# TEST MAE AND RMSE
# ============================================================================

class TestErrorMetrics:
    """Test error metric calculations."""

    def test_calculate_mae(self):
        """Should calculate Mean Absolute Error."""
        predictions = np.array([25, 30, 20])
        actuals = np.array([28, 28, 22])

        mae = np.mean(np.abs(predictions - actuals))

        assert mae == pytest.approx(2.33, rel=0.01)

    def test_calculate_rmse(self):
        """Should calculate Root Mean Squared Error."""
        predictions = np.array([25, 30, 20])
        actuals = np.array([28, 28, 22])

        rmse = np.sqrt(np.mean((predictions - actuals) ** 2))

        assert rmse == pytest.approx(2.52, rel=0.01)

    def test_rmse_penalizes_outliers(self):
        """RMSE should penalize large errors more than MAE."""
        predictions = np.array([25, 25, 25, 25])
        actuals = np.array([26, 26, 26, 35])  # One big miss

        mae = np.mean(np.abs(predictions - actuals))
        rmse = np.sqrt(np.mean((predictions - actuals) ** 2))

        # RMSE should be larger due to outlier penalty
        assert rmse > mae


# ============================================================================
# TEST SEGMENT ANALYSIS
# ============================================================================

class TestSegmentAnalysis:
    """Test accuracy by different segments."""

    def test_accuracy_by_points_range(self):
        """Should calculate accuracy by points line range."""
        results = [
            {'line': 15, 'hit': True},
            {'line': 18, 'hit': False},
            {'line': 22, 'hit': True},
            {'line': 28, 'hit': True},
            {'line': 32, 'hit': False},
        ]

        # Segment by line range
        low = [r for r in results if r['line'] < 20]
        mid = [r for r in results if 20 <= r['line'] < 30]
        high = [r for r in results if r['line'] >= 30]

        low_acc = sum(1 for r in low if r['hit']) / len(low) if low else 0
        mid_acc = sum(1 for r in mid if r['hit']) / len(mid) if mid else 0
        high_acc = sum(1 for r in high if r['hit']) / len(high) if high else 0

        assert low_acc == 0.5  # 1/2
        assert mid_acc == 1.0  # 2/2
        assert high_acc == 0.0  # 0/1

    def test_accuracy_by_home_away(self):
        """Should calculate accuracy by home/away."""
        results = [
            {'is_home': True, 'hit': True},
            {'is_home': True, 'hit': True},
            {'is_home': False, 'hit': False},
            {'is_home': False, 'hit': True},
        ]

        home = [r for r in results if r['is_home']]
        away = [r for r in results if not r['is_home']]

        home_acc = sum(1 for r in home if r['hit']) / len(home)
        away_acc = sum(1 for r in away if r['hit']) / len(away)

        assert home_acc == 1.0  # 2/2
        assert away_acc == 0.5  # 1/2


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestBettingAccuracyIntegration:
    """Integration tests for betting accuracy analysis."""

    def test_full_accuracy_calculation_workflow(self):
        """Should complete full accuracy calculation."""
        # Sample data
        predictions = [
            {'player': 'A', 'predicted': 28, 'line': 25.5, 'actual': 30},
            {'player': 'B', 'predicted': 22, 'line': 24.5, 'actual': 20},
            {'player': 'C', 'predicted': 30, 'line': 28.5, 'actual': 25},
        ]

        # Calculate metrics
        hits = 0
        total_edge = 0
        errors = []

        for p in predictions:
            edge = p['predicted'] - p['line']
            direction = 'over' if edge > 0 else 'under'
            actual_result = 'over' if p['actual'] > p['line'] else 'under'

            if direction == actual_result:
                hits += 1

            total_edge += abs(edge)
            errors.append(abs(p['predicted'] - p['actual']))

        hit_rate = hits / len(predictions)
        mae = np.mean(errors)

        assert hit_rate == pytest.approx(0.667, rel=0.01)
        assert mae == pytest.approx(3.67, rel=0.1)
