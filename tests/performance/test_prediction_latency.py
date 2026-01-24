# tests/performance/test_prediction_latency.py
"""
Performance Tests for Prediction System Latency

Tests the performance of critical prediction operations:
1. Single prediction latency
2. Batch prediction throughput
3. Feature validation speed
4. Confidence calculation performance
5. Recommendation logic speed
6. End-to-end prediction pipeline

Run with:
    pytest test_prediction_latency.py -v --benchmark-only
    pytest test_prediction_latency.py -v --benchmark-columns=min,max,mean,stddev

To save and compare benchmarks:
    pytest test_prediction_latency.py --benchmark-save=baseline
    pytest test_prediction_latency.py --benchmark-compare=baseline
"""

import pytest
import numpy as np
from datetime import date, datetime, timezone
from unittest.mock import Mock, MagicMock, patch
from typing import Dict, Any, List, Tuple
import time




def _get_stats(benchmark):
    """Safely get benchmark stats, returns None if not available."""
    try:
        if hasattr(benchmark, 'stats') and hasattr(benchmark.stats, 'mean'):
            return benchmark.stats
    except Exception:
        pass
    return None

# =============================================================================
# Mock Predictor Classes for Benchmarking
# =============================================================================

class MockMovingAveragePredictor:
    """Mock moving average predictor for benchmarking."""

    def __init__(self, system_id: str = 'moving_average', version: str = '1.0'):
        self.system_id = system_id
        self.system_name = 'Moving Average Baseline'
        self.version = version

    def predict(self, features: Dict[str, Any], player_lookup: str,
                game_date: date, prop_line: float = None) -> Tuple[float, float, str]:
        """Make prediction using weighted moving average."""
        # Extract features
        last_5 = features.get('points_avg_last_5', 20.0)
        last_10 = features.get('points_avg_last_10', 20.0)
        season_avg = features.get('points_avg_season', 20.0)

        # Weighted average (50% last 5, 30% last 10, 20% season)
        prediction = 0.50 * last_5 + 0.30 * last_10 + 0.20 * season_avg

        # Calculate confidence
        volatility = features.get('points_std_last_10', 4.0)
        recent_games = features.get('games_played_last_7_days', 2)
        confidence = self.calculate_confidence(volatility, recent_games)

        # Determine recommendation
        recommendation = 'PASS'
        if prop_line:
            recommendation = self.determine_recommendation(prediction, prop_line, confidence)

        return (prediction, confidence, recommendation)

    def calculate_confidence(self, volatility: float, recent_games: int,
                             data_quality: float = 1.0) -> float:
        """Calculate prediction confidence score."""
        confidence = 0.5

        if volatility > 6.0:
            confidence -= 0.15
        elif volatility > 4.0:
            confidence -= 0.08

        if recent_games >= 3:
            confidence += 0.10
        elif recent_games >= 2:
            confidence += 0.05
        else:
            confidence -= 0.10

        confidence *= data_quality
        return max(0.2, min(0.8, confidence))

    def determine_recommendation(self, predicted: float, prop_line: float,
                                 confidence: float, edge_threshold: float = 2.0) -> str:
        """Determine OVER/UNDER/PASS recommendation."""
        edge = abs(predicted - prop_line)

        if edge <= edge_threshold or confidence <= 0.45:
            return 'PASS'

        return 'OVER' if predicted > prop_line else 'UNDER'

    def validate_features(self, features: Dict[str, Any]) -> bool:
        """Validate feature dictionary."""
        required = ['feature_count', 'feature_version', 'data_source', 'features_array']
        return all(field in features for field in required)


class MockEnsemblePredictor:
    """Mock ensemble predictor combining multiple systems."""

    def __init__(self):
        self.system_id = 'ensemble_v1'
        self.system_name = 'Ensemble V1'
        self.version = '1.0'
        self.weights = {
            'moving_average': 0.40,
            'zone_matchup': 0.35,
            'xgboost': 0.25
        }

    def predict(self, features: Dict[str, Any], player_lookup: str,
                game_date: date, prop_line: float = None) -> Tuple[float, float, str]:
        """Make ensemble prediction combining multiple systems."""
        # Simulate individual system predictions
        ma_pred = 0.50 * features.get('points_avg_last_5', 20) + \
                  0.30 * features.get('points_avg_last_10', 20) + \
                  0.20 * features.get('points_avg_season', 20)

        # Zone matchup simulation
        zone_adjustment = features.get('fatigue_score', 50) / 100 * 2
        zm_pred = ma_pred + zone_adjustment

        # XGBoost simulation
        xgb_pred = ma_pred * 1.02  # Slight adjustment

        # Weighted ensemble
        prediction = (
            self.weights['moving_average'] * ma_pred +
            self.weights['zone_matchup'] * zm_pred +
            self.weights['xgboost'] * xgb_pred
        )

        # Confidence from volatility
        volatility = features.get('points_std_last_10', 4.0)
        confidence = max(0.3, min(0.75, 0.6 - volatility * 0.05))

        # Recommendation
        recommendation = 'PASS'
        if prop_line:
            edge = abs(prediction - prop_line)
            if edge > 2.0 and confidence > 0.45:
                recommendation = 'OVER' if prediction > prop_line else 'UNDER'

        return (prediction, confidence, recommendation)


class MockXGBoostPredictor:
    """Mock XGBoost predictor for benchmarking."""

    def __init__(self):
        self.system_id = 'xgboost_v1'
        self.system_name = 'XGBoost V1'
        self.version = '1.0'
        # Simulated model coefficients
        self._coefficients = np.random.randn(25) * 0.1

    def predict(self, features: Dict[str, Any], player_lookup: str,
                game_date: date, prop_line: float = None) -> Tuple[float, float, str]:
        """Make prediction using simulated XGBoost model."""
        # Extract feature array
        feature_array = features.get('features_array', [20.0] * 25)

        # Simulated model inference
        base_prediction = np.dot(feature_array[:len(self._coefficients)],
                                 self._coefficients)
        prediction = 20.0 + base_prediction  # Base points + adjustment

        # Confidence based on prediction certainty
        confidence = min(0.75, max(0.3, 0.5 + abs(base_prediction) * 0.1))

        # Recommendation
        recommendation = 'PASS'
        if prop_line:
            edge = abs(prediction - prop_line)
            if edge > 2.0 and confidence > 0.45:
                recommendation = 'OVER' if prediction > prop_line else 'UNDER'

        return (prediction, confidence, recommendation)


# =============================================================================
# Single Prediction Latency Tests
# =============================================================================

class TestSinglePredictionLatency:
    """Test latency of single predictions."""

    def test_benchmark_moving_average_prediction(self, benchmark, sample_features):
        """Benchmark single moving average prediction."""
        predictor = MockMovingAveragePredictor()
        features = sample_features(1)[0]

        result = benchmark(
            predictor.predict,
            features,
            'lebron-james',
            date(2025, 1, 15),
            25.5
        )

        prediction, confidence, recommendation = result
        assert 10 <= prediction <= 50
        assert 0.2 <= confidence <= 0.8
        assert recommendation in ['OVER', 'UNDER', 'PASS']

        stats = _get_stats(benchmark)
        if stats:
            print(f"\nMoving Average single prediction: "
                  f"{stats.mean * 1000000:.2f}us")

    def test_benchmark_ensemble_prediction(self, benchmark, sample_features):
        """Benchmark single ensemble prediction."""
        predictor = MockEnsemblePredictor()
        features = sample_features(1)[0]

        result = benchmark(
            predictor.predict,
            features,
            'lebron-james',
            date(2025, 1, 15),
            25.5
        )

        prediction, confidence, recommendation = result
        assert 10 <= prediction <= 50

        stats = _get_stats(benchmark)
        if stats:
            print(f"\nEnsemble single prediction: "
                  f"{stats.mean * 1000000:.2f}us")

    def test_benchmark_xgboost_prediction(self, benchmark, sample_features):
        """Benchmark single XGBoost prediction."""
        predictor = MockXGBoostPredictor()
        features = sample_features(1)[0]

        result = benchmark(
            predictor.predict,
            features,
            'lebron-james',
            date(2025, 1, 15),
            25.5
        )

        prediction, confidence, recommendation = result
        assert prediction is not None

        stats = _get_stats(benchmark)
        if stats:
            print(f"\nXGBoost single prediction: "
                  f"{stats.mean * 1000000:.2f}us")


# =============================================================================
# Batch Prediction Throughput Tests
# =============================================================================

class TestBatchPredictionThroughput:
    """Test throughput for batch predictions."""

    @pytest.mark.parametrize("batch_size", [50, 100, 200, 450])
    def test_benchmark_moving_average_batch(self, benchmark, sample_features,
                                            sample_prop_lines, batch_size):
        """Benchmark batch moving average predictions."""
        predictor = MockMovingAveragePredictor()
        features_list = sample_features(batch_size)
        prop_lines = sample_prop_lines(batch_size)

        def predict_batch():
            results = []
            for i, features in enumerate(features_list):
                result = predictor.predict(
                    features,
                    features['player_lookup'],
                    date(2025, 1, 15),
                    prop_lines[i]
                )
                results.append(result)
            return results

        result = benchmark(predict_batch)

        assert len(result) == batch_size
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nMoving Average batch ({batch_size}): "
                  f"{stats.mean * 1000:.2f}ms "
                  f"({batch_size / stats.mean:.0f} predictions/sec)")

    @pytest.mark.parametrize("batch_size", [50, 100, 200, 450])
    def test_benchmark_ensemble_batch(self, benchmark, sample_features,
                                      sample_prop_lines, batch_size):
        """Benchmark batch ensemble predictions."""
        predictor = MockEnsemblePredictor()
        features_list = sample_features(batch_size)
        prop_lines = sample_prop_lines(batch_size)

        def predict_batch():
            results = []
            for i, features in enumerate(features_list):
                result = predictor.predict(
                    features,
                    features['player_lookup'],
                    date(2025, 1, 15),
                    prop_lines[i]
                )
                results.append(result)
            return results

        result = benchmark(predict_batch)

        assert len(result) == batch_size
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nEnsemble batch ({batch_size}): "
                  f"{stats.mean * 1000:.2f}ms "
                  f"({batch_size / stats.mean:.0f} predictions/sec)")


# =============================================================================
# Feature Validation Performance Tests
# =============================================================================

class TestFeatureValidationPerformance:
    """Test feature validation speed."""

    def test_benchmark_single_feature_validation(self, benchmark, sample_features):
        """Benchmark single feature validation."""
        predictor = MockMovingAveragePredictor()
        features = sample_features(1)[0]

        result = benchmark(predictor.validate_features, features)

        assert result is True
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nSingle feature validation: "
                  f"{stats.mean * 1000000:.2f}us")

    def test_benchmark_batch_feature_validation(self, benchmark, sample_features):
        """Benchmark batch feature validation."""
        predictor = MockMovingAveragePredictor()
        features_list = sample_features(450)

        def validate_batch():
            return [predictor.validate_features(f) for f in features_list]

        result = benchmark(validate_batch)

        assert all(result)
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nBatch feature validation (450): "
                  f"{stats.mean * 1000:.2f}ms")


# =============================================================================
# Confidence Calculation Performance Tests
# =============================================================================

class TestConfidenceCalculationPerformance:
    """Test confidence calculation performance."""

    def test_benchmark_confidence_calculation(self, benchmark):
        """Benchmark confidence calculation."""
        predictor = MockMovingAveragePredictor()

        result = benchmark(
            predictor.calculate_confidence,
            volatility=4.5,
            recent_games=3,
            data_quality=0.95
        )

        assert 0.2 <= result <= 0.8
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nConfidence calculation: "
                  f"{stats.mean * 1000000:.2f}us")

    def test_benchmark_batch_confidence_calculation(self, benchmark):
        """Benchmark batch confidence calculation."""
        predictor = MockMovingAveragePredictor()

        # Various volatility/games combinations
        test_cases = [
            (3.0 + (i % 5), 1 + (i % 4), 0.8 + (i % 20) * 0.01)
            for i in range(450)
        ]

        def calculate_batch():
            return [
                predictor.calculate_confidence(vol, games, quality)
                for vol, games, quality in test_cases
            ]

        result = benchmark(calculate_batch)

        assert len(result) == 450
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nBatch confidence calculation (450): "
                  f"{stats.mean * 1000:.2f}ms")


# =============================================================================
# Recommendation Logic Performance Tests
# =============================================================================

class TestRecommendationLogicPerformance:
    """Test recommendation logic performance."""

    def test_benchmark_single_recommendation(self, benchmark):
        """Benchmark single recommendation determination."""
        predictor = MockMovingAveragePredictor()

        result = benchmark(
            predictor.determine_recommendation,
            predicted=27.5,
            prop_line=25.0,
            confidence=0.55,
            edge_threshold=2.0
        )

        assert result in ['OVER', 'UNDER', 'PASS']
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nSingle recommendation: "
                  f"{stats.mean * 1000000:.2f}us")

    def test_benchmark_batch_recommendation(self, benchmark):
        """Benchmark batch recommendation determination."""
        predictor = MockMovingAveragePredictor()

        # Generate test cases
        test_cases = [
            (20 + (i % 20), 22.5, 0.4 + (i % 40) * 0.01)
            for i in range(450)
        ]

        def determine_batch():
            return [
                predictor.determine_recommendation(pred, line, conf)
                for pred, line, conf in test_cases
            ]

        result = benchmark(determine_batch)

        assert len(result) == 450
        assert all(r in ['OVER', 'UNDER', 'PASS'] for r in result)
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nBatch recommendation (450): "
                  f"{stats.mean * 1000:.2f}ms")


# =============================================================================
# End-to-End Pipeline Performance Tests
# =============================================================================

class TestEndToEndPipelinePerformance:
    """Test end-to-end prediction pipeline performance."""

    def test_benchmark_full_prediction_pipeline(self, benchmark, sample_features):
        """Benchmark full prediction pipeline for a single player."""
        predictor = MockEnsemblePredictor()
        features = sample_features(1)[0]

        def full_pipeline():
            # 1. Validate features
            valid = 'features_array' in features

            # 2. Make prediction
            prediction, confidence, recommendation = predictor.predict(
                features,
                features['player_lookup'],
                date(2025, 1, 15),
                25.5
            )

            # 3. Format result
            return {
                'player_lookup': features['player_lookup'],
                'game_date': str(date(2025, 1, 15)),
                'prop_line': 25.5,
                'prediction': round(prediction, 2),
                'confidence': round(confidence, 3),
                'recommendation': recommendation,
                'system_id': predictor.system_id,
                'generated_at': datetime.now(timezone.utc).isoformat()
            }

        result = benchmark(full_pipeline)

        assert 'prediction' in result
        assert 'confidence' in result
        assert 'recommendation' in result
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nFull prediction pipeline: "
                  f"{stats.mean * 1000000:.2f}us")

    def test_benchmark_game_day_predictions(self, benchmark, sample_features):
        """Benchmark predictions for a full game day (~450 players)."""
        predictor = MockEnsemblePredictor()
        features_list = sample_features(450)

        def game_day_predictions():
            results = []
            for features in features_list:
                prediction, confidence, recommendation = predictor.predict(
                    features,
                    features['player_lookup'],
                    date(2025, 1, 15),
                    22.5  # Default line
                )
                results.append({
                    'player': features['player_lookup'],
                    'prediction': prediction,
                    'confidence': confidence,
                    'recommendation': recommendation
                })
            return results

        result = benchmark(game_day_predictions)

        assert len(result) == 450
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nGame day predictions (450 players): "
                  f"{stats.mean * 1000:.2f}ms "
                  f"({450 / stats.mean:.0f} predictions/sec)")


# =============================================================================
# Latency Thresholds Tests
# =============================================================================

class TestLatencyThresholds:
    """Verify predictions meet latency requirements."""

    def test_single_prediction_under_1ms(self, sample_features):
        """Verify single prediction completes under 1ms."""
        predictor = MockEnsemblePredictor()
        features = sample_features(1)[0]

        times = []
        for _ in range(100):
            start = time.perf_counter()
            predictor.predict(features, 'test-player', date(2025, 1, 15), 25.5)
            elapsed = (time.perf_counter() - start) * 1000  # ms
            times.append(elapsed)

        avg_time = sum(times) / len(times)
        p99_time = sorted(times)[98]

        print(f"\nSingle prediction latency:")
        print(f"  Average: {avg_time:.3f}ms")
        print(f"  P99: {p99_time:.3f}ms")

        assert avg_time < 1.0, f"Average latency {avg_time:.3f}ms exceeds 1ms"
        assert p99_time < 5.0, f"P99 latency {p99_time:.3f}ms exceeds 5ms"

    def test_batch_predictions_under_500ms(self, sample_features):
        """Verify 450 predictions complete under 500ms."""
        predictor = MockEnsemblePredictor()
        features_list = sample_features(450)

        times = []
        for _ in range(10):
            start = time.perf_counter()
            for features in features_list:
                predictor.predict(features, 'test-player', date(2025, 1, 15), 25.5)
            elapsed = (time.perf_counter() - start) * 1000  # ms
            times.append(elapsed)

        avg_time = sum(times) / len(times)

        print(f"\nBatch prediction (450) latency:")
        print(f"  Average: {avg_time:.2f}ms")
        print(f"  Throughput: {450 / (avg_time / 1000):.0f} predictions/sec")

        assert avg_time < 500, f"Batch latency {avg_time:.2f}ms exceeds 500ms"


# =============================================================================
# Summary Test
# =============================================================================

def test_print_prediction_latency_summary():
    """Print prediction latency test summary."""
    print("\n" + "=" * 70)
    print("PREDICTION LATENCY TEST SUMMARY")
    print("=" * 70)
    print("\nAll prediction latency benchmarks completed!")
    print("Review the timing information above for performance metrics.")
    print("\nLatency Targets:")
    print("  - Single prediction: < 1ms (target: 100-500us)")
    print("  - Batch (450 players): < 500ms (target: 100-200ms)")
    print("  - Feature validation: < 100us per validation")
    print("  - Full game day: < 1 second for all predictions")
    print("=" * 70)


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--benchmark-only'])
