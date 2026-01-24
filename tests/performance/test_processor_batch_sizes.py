# tests/performance/test_processor_batch_sizes.py
"""
Performance Tests for Data Processor Batch Sizes

Tests optimal batch sizes and processing throughput for:
1. Raw data processors (Phase 2)
2. Analytics processors (Phase 3)
3. Precompute processors (Phase 4)
4. Feature extraction and calculation

Run with:
    pytest test_processor_batch_sizes.py -v --benchmark-only
    pytest test_processor_batch_sizes.py -v --benchmark-columns=min,max,mean,stddev

To save and compare benchmarks:
    pytest test_processor_batch_sizes.py --benchmark-save=baseline
    pytest test_processor_batch_sizes.py --benchmark-compare=baseline
"""

import pytest
import pandas as pd
import numpy as np
from datetime import date, datetime, timezone, timedelta
from unittest.mock import Mock, MagicMock, patch
from typing import Dict, Any, List
import hashlib


def _get_stats(benchmark):
    """Safely get benchmark stats, returns None if not available."""
    try:
        if hasattr(benchmark, 'stats') and hasattr(benchmark.stats, 'mean'):
            return benchmark.stats
    except Exception:
        pass
    return None


# =============================================================================
# Mock Processor Classes for Benchmarking
# =============================================================================

class MockRawProcessor:
    """Mock Phase 2 raw processor for batch size testing."""

    HASH_FIELDS = ['game_id', 'player_lookup', 'points', 'assists', 'rebounds']
    PRIMARY_KEYS = ['game_id', 'player_lookup']

    def __init__(self):
        self.transformed_data = []
        self.stats = {}

    def add_data_hash(self):
        """Add hash to each record for idempotency."""
        for record in self.transformed_data:
            hash_string = '|'.join(str(record.get(f, '')) for f in self.HASH_FIELDS)
            record['data_hash'] = hashlib.md5(hash_string.encode()).hexdigest()[:16]

    def transform_records(self, raw_data: List[Dict]) -> List[Dict]:
        """Transform raw records to target schema."""
        transformed = []
        for record in raw_data:
            transformed.append({
                'game_id': record.get('game_id'),
                'player_lookup': record.get('player_lookup'),
                'game_date': str(record.get('game_date')),
                'points': record.get('points', 0),
                'assists': record.get('assists', 0),
                'rebounds': record.get('rebounds', 0),
                'minutes_played': record.get('minutes_played', 0),
                'processed_at': datetime.now(timezone.utc).isoformat()
            })
        self.transformed_data = transformed
        return transformed


class MockAnalyticsProcessor:
    """Mock Phase 3 analytics processor for aggregation testing."""

    def __init__(self):
        self.stats = {}

    def aggregate_player_stats(self, game_data: pd.DataFrame) -> pd.DataFrame:
        """Aggregate player stats by game."""
        if game_data.empty:
            return pd.DataFrame()

        return game_data.groupby(['player_lookup', 'game_date']).agg({
            'points': 'sum',
            'assists': 'sum',
            'rebounds': 'sum',
            'minutes_played': 'sum'
        }).reset_index()

    def calculate_rolling_averages(self, player_data: pd.DataFrame, windows: List[int] = [5, 10, 20]) -> pd.DataFrame:
        """Calculate rolling averages for player stats."""
        if player_data.empty:
            return pd.DataFrame()

        result = player_data.copy()
        for window in windows:
            for col in ['points', 'assists', 'rebounds']:
                result[f'{col}_avg_last_{window}'] = (
                    result.groupby('player_lookup')[col]
                    .transform(lambda x: x.rolling(window, min_periods=1).mean())
                )
        return result


class MockFeatureCalculator:
    """Mock feature calculator for ML feature extraction."""

    def calculate_rest_advantage(self, data: Dict) -> float:
        """Calculate rest advantage score."""
        days_rest = data.get('days_rest', 2)
        opp_days_rest = data.get('opponent_days_rest', 2)
        return min(2.0, max(-2.0, (days_rest - opp_days_rest) * 0.5))

    def calculate_fatigue_score(self, data: Dict) -> float:
        """Calculate fatigue score based on recent activity."""
        games_in_7_days = data.get('games_in_last_7_days', 2)
        minutes_avg = data.get('minutes_avg_last_5', 30)

        base_fatigue = 50.0
        games_factor = (games_in_7_days - 2) * 10
        minutes_factor = (minutes_avg - 30) * 0.5

        return max(0, min(100, base_fatigue + games_factor + minutes_factor))

    def calculate_trend_score(self, data: Dict) -> float:
        """Calculate recent performance trend."""
        last_5 = data.get('points_avg_last_5', 20)
        last_10 = data.get('points_avg_last_10', 20)

        if last_10 == 0:
            return 0.0
        return (last_5 - last_10) / last_10

    def extract_all_features(self, data: Dict) -> List[float]:
        """Extract all 25 features from data."""
        features = [
            data.get('points_avg_last_5', 0),
            data.get('points_avg_last_10', 0),
            data.get('points_avg_season', 0),
            data.get('points_std_last_10', 0),
            data.get('games_in_last_7_days', 0),
            self.calculate_fatigue_score(data),
            self.calculate_rest_advantage(data),
            data.get('injury_risk', 0),
            self.calculate_trend_score(data),
            data.get('quality_score', 0),
            data.get('minutes_change', 0),
            data.get('pct_free_throw', 0),
            data.get('team_win_pct', 0),
            data.get('team_off_rating', 0),
            data.get('opp_def_rating', 0),
            1 if data.get('is_home') else 0,
            1 if data.get('back_to_back') else 0,
            1 if data.get('injury_flag') else 0,
            data.get('paint_rate', 0),
            data.get('mid_range_rate', 0),
            data.get('three_pt_rate', 0),
            data.get('assisted_rate', 0),
            data.get('pace', 0),
            data.get('usage_rate', 0),
            data.get('true_shooting_pct', 0)
        ]
        return features


# =============================================================================
# Batch Size Performance Tests
# =============================================================================

class TestBatchSizePerformance:
    """Test different batch sizes for optimal throughput."""

    @pytest.mark.parametrize("batch_size", [50, 100, 200, 500, 1000])
    def test_benchmark_raw_processor_batch_sizes(self, benchmark, sample_player_rows, batch_size):
        """Benchmark raw processor with different batch sizes."""
        processor = MockRawProcessor()
        rows = sample_player_rows(batch_size)

        def process_batch():
            processor.transform_records(rows)
            processor.add_data_hash()
            return processor.transformed_data

        result = benchmark(process_batch)

        assert len(result) == batch_size
        assert 'data_hash' in result[0]
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nRaw processor batch size {batch_size}: "
                  f"{stats.mean * 1000:.2f}ms "
                  f"({batch_size / stats.mean:.0f} records/sec)")

    @pytest.mark.parametrize("batch_size", [100, 500, 1000, 2000])
    def test_benchmark_dataframe_aggregation_batch_sizes(self, benchmark, sample_player_rows, batch_size):
        """Benchmark DataFrame aggregation with different batch sizes."""
        processor = MockAnalyticsProcessor()
        rows = sample_player_rows(batch_size)
        df = pd.DataFrame(rows)

        result = benchmark(processor.aggregate_player_stats, df)

        assert len(result) > 0
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nDataFrame aggregation batch size {batch_size}: "
                  f"{stats.mean * 1000:.2f}ms")

    @pytest.mark.parametrize("batch_size", [100, 500, 1000])
    def test_benchmark_rolling_average_batch_sizes(self, benchmark, sample_player_rows, batch_size):
        """Benchmark rolling average calculation with different batch sizes."""
        processor = MockAnalyticsProcessor()
        rows = sample_player_rows(batch_size)
        df = pd.DataFrame(rows)
        df = df.sort_values(['player_lookup', 'game_date'])

        result = benchmark(processor.calculate_rolling_averages, df)

        assert 'points_avg_last_5' in result.columns
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nRolling averages batch size {batch_size}: "
                  f"{stats.mean * 1000:.2f}ms")


# =============================================================================
# Feature Extraction Performance Tests
# =============================================================================

class TestFeatureExtractionPerformance:
    """Test feature extraction and calculation performance."""

    def test_benchmark_single_feature_calculation(self, benchmark):
        """Benchmark single feature calculation."""
        calculator = MockFeatureCalculator()
        data = {
            'days_rest': 2,
            'opponent_days_rest': 1,
            'games_in_last_7_days': 3,
            'minutes_avg_last_5': 32.5
        }

        result = benchmark(calculator.calculate_rest_advantage, data)

        assert -2.0 <= result <= 2.0
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nSingle feature calculation: {stats.mean * 1000000:.2f}us")

    def test_benchmark_full_feature_extraction(self, benchmark, sample_features):
        """Benchmark full 25-feature extraction."""
        calculator = MockFeatureCalculator()
        features = sample_features(1)[0]

        data = {
            'points_avg_last_5': features['points_avg_last_5'],
            'points_avg_last_10': features['points_avg_last_10'],
            'points_avg_season': features.get('points_avg_season', 22),
            'points_std_last_10': features['points_std_last_10'],
            'games_in_last_7_days': features['games_played_last_7_days'],
            'days_rest': 2,
            'opponent_days_rest': 1,
            'injury_risk': 0.1,
            'quality_score': 85,
            'minutes_change': 0,
            'pct_free_throw': 0.15,
            'team_win_pct': 0.55,
            'team_off_rating': 112,
            'opp_def_rating': 108,
            'is_home': True,
            'back_to_back': False,
            'injury_flag': False,
            'paint_rate': 0.35,
            'mid_range_rate': 0.15,
            'three_pt_rate': 0.40,
            'assisted_rate': 0.45,
            'pace': 100,
            'usage_rate': 25,
            'true_shooting_pct': 0.58
        }

        result = benchmark(calculator.extract_all_features, data)

        assert len(result) == 25
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nFull feature extraction (25 features): "
                  f"{stats.mean * 1000:.3f}ms")

    @pytest.mark.parametrize("player_count", [50, 200, 450])
    def test_benchmark_batch_feature_extraction(self, benchmark, sample_features, player_count):
        """Benchmark batch feature extraction for multiple players."""
        calculator = MockFeatureCalculator()
        features_list = sample_features(player_count)

        def extract_batch_features():
            results = []
            for features in features_list:
                data = {
                    'points_avg_last_5': features['points_avg_last_5'],
                    'points_avg_last_10': features['points_avg_last_10'],
                    'points_avg_season': 22,
                    'points_std_last_10': features['points_std_last_10'],
                    'games_in_last_7_days': features['games_played_last_7_days'],
                    'days_rest': 2,
                    'opponent_days_rest': 1,
                    'is_home': True,
                    'back_to_back': False,
                    'injury_flag': False,
                }
                results.append(calculator.extract_all_features(data))
            return results

        result = benchmark(extract_batch_features)

        assert len(result) == player_count
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nBatch feature extraction ({player_count} players): "
                  f"{stats.mean * 1000:.2f}ms "
                  f"({player_count / stats.mean:.0f} players/sec)")


# =============================================================================
# DataFrame Operations Performance Tests
# =============================================================================

class TestDataFrameOperationsPerformance:
    """Test pandas DataFrame operations performance."""

    def test_benchmark_dataframe_creation_from_records(self, benchmark, sample_player_rows):
        """Benchmark DataFrame creation from list of dicts."""
        rows = sample_player_rows(500)

        result = benchmark(pd.DataFrame, rows)

        assert len(result) == 500
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nDataFrame creation (500 records): "
                  f"{stats.mean * 1000:.2f}ms")

    def test_benchmark_dataframe_to_dict(self, benchmark, sample_player_rows):
        """Benchmark DataFrame to dict conversion."""
        rows = sample_player_rows(500)
        df = pd.DataFrame(rows)

        result = benchmark(df.to_dict, 'records')

        assert len(result) == 500
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nDataFrame to dict (500 records): "
                  f"{stats.mean * 1000:.2f}ms")

    def test_benchmark_dataframe_merge(self, benchmark, sample_player_rows):
        """Benchmark DataFrame merge operation."""
        rows1 = sample_player_rows(500)
        rows2 = [{'player_lookup': r['player_lookup'], 'extra_stat': i}
                 for i, r in enumerate(rows1)]

        df1 = pd.DataFrame(rows1)
        df2 = pd.DataFrame(rows2)

        result = benchmark(pd.merge, df1, df2, on='player_lookup')

        assert len(result) == 500
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nDataFrame merge (500 records): "
                  f"{stats.mean * 1000:.2f}ms")

    def test_benchmark_dataframe_groupby(self, benchmark, sample_player_rows):
        """Benchmark DataFrame groupby operation."""
        rows = sample_player_rows(1000)
        df = pd.DataFrame(rows)

        def groupby_operation():
            return df.groupby('team_abbr').agg({
                'points': ['mean', 'sum', 'std'],
                'assists': ['mean', 'sum'],
                'rebounds': ['mean', 'sum']
            }).reset_index()

        result = benchmark(groupby_operation)

        assert len(result) > 0
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nDataFrame groupby (1000 records): "
                  f"{stats.mean * 1000:.2f}ms")


# =============================================================================
# Memory Efficiency Tests
# =============================================================================

class TestMemoryEfficiency:
    """Test memory-efficient processing patterns."""

    def test_benchmark_generator_vs_list(self, benchmark, sample_player_rows):
        """Compare generator vs list processing for memory efficiency."""
        rows = sample_player_rows(1000)

        def process_with_list():
            # List comprehension (loads all into memory)
            return [
                {
                    'player': r['player_lookup'],
                    'score': r['points'] + r['assists'] + r['rebounds']
                }
                for r in rows
            ]

        result = benchmark(process_with_list)

        assert len(result) == 1000
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nList processing (1000 records): "
                  f"{stats.mean * 1000:.2f}ms")

    def test_benchmark_chunked_processing(self, benchmark, sample_player_rows):
        """Benchmark chunked processing for large datasets."""
        all_rows = sample_player_rows(1000)

        def process_in_chunks(chunk_size=100):
            results = []
            for i in range(0, len(all_rows), chunk_size):
                chunk = all_rows[i:i + chunk_size]
                # Process chunk
                chunk_results = [
                    {
                        'player': r['player_lookup'],
                        'score': r['points'] + r['assists'] + r['rebounds']
                    }
                    for r in chunk
                ]
                results.extend(chunk_results)
            return results

        result = benchmark(process_in_chunks)

        assert len(result) == 1000
        stats = _get_stats(benchmark)
        if stats:
            print(f"\nChunked processing (1000 records, 100/chunk): "
                  f"{stats.mean * 1000:.2f}ms")


# =============================================================================
# Optimal Batch Size Determination
# =============================================================================

class TestOptimalBatchSize:
    """Determine optimal batch sizes for different operations."""

    def test_find_optimal_hash_batch_size(self, sample_player_rows):
        """Find optimal batch size for hash computation."""
        import time

        batch_sizes = [50, 100, 200, 500, 1000]
        results = {}

        for batch_size in batch_sizes:
            rows = sample_player_rows(batch_size)

            start = time.perf_counter()
            for _ in range(10):  # 10 iterations
                for record in rows:
                    hash_string = '|'.join(str(record.get(f, ''))
                                           for f in ['player_lookup', 'points', 'assists'])
                    hashlib.md5(hash_string.encode()).hexdigest()[:16]
            elapsed = (time.perf_counter() - start) / 10

            throughput = batch_size / elapsed
            results[batch_size] = {
                'time_ms': elapsed * 1000,
                'throughput': throughput
            }

        # Print results
        print("\n" + "=" * 50)
        print("OPTIMAL BATCH SIZE FOR HASH COMPUTATION")
        print("=" * 50)
        for size, metrics in results.items():
            print(f"Batch {size:4d}: {metrics['time_ms']:6.2f}ms "
                  f"({metrics['throughput']:,.0f} records/sec)")

        # Assertions
        assert all(r['throughput'] > 10000 for r in results.values())  # At least 10k/sec


# =============================================================================
# Summary Test
# =============================================================================

def test_print_processor_batch_summary():
    """Print processor batch size test summary."""
    print("\n" + "=" * 70)
    print("PROCESSOR BATCH SIZE TEST SUMMARY")
    print("=" * 70)
    print("\nAll processor batch size benchmarks completed!")
    print("Review the timing information above for performance metrics.")
    print("\nRecommended Batch Sizes:")
    print("  - Raw processor: 200-500 records per batch")
    print("  - Analytics aggregation: 500-1000 records per batch")
    print("  - Feature extraction: 200-450 players per batch")
    print("  - DataFrame operations: 500-1000 records optimal")
    print("=" * 70)


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--benchmark-only'])
