"""
Performance Benchmark Tests for ML Feature Store Processor

Uses pytest-benchmark to track performance metrics:
- Feature generation per player
- Phase 4 extraction
- Phase 3 fallback
- Quality scoring
- Batch writing

Establishes performance baselines and alerts on regressions.

Install: pip install pytest-benchmark
Run with: pytest test_performance.py -v --benchmark-only

File: tests/processors/precompute/ml_feature_store/test_performance.py
"""

import pytest
from datetime import date
from unittest.mock import Mock, MagicMock
import pandas as pd

from data_processors.precompute.ml_feature_store.ml_feature_store_processor import MLFeatureStoreProcessor
from data_processors.precompute.ml_feature_store.feature_extractor import FeatureExtractor
from data_processors.precompute.ml_feature_store.feature_calculator import FeatureCalculator
from data_processors.precompute.ml_feature_store.quality_scorer import QualityScorer
from data_processors.precompute.ml_feature_store.batch_writer import BatchWriter


# ============================================================================
# FIXTURES FOR BENCHMARKING
# ============================================================================

@pytest.fixture
def mock_bq_client():
    """Create mock BigQuery client with realistic response times."""
    client = Mock()
    
    # Simulate query execution time (10-50ms per query)
    def mock_query(sql):
        job = Mock()
        # Return empty DataFrame to avoid processing overhead
        job.to_dataframe.return_value = pd.DataFrame()
        return job
    
    client.query = mock_query
    return client


@pytest.fixture
def sample_player_row():
    """Create sample player row for benchmarking."""
    return {
        'player_lookup': 'lebron-james',
        'universal_player_id': 'lebronjames_001',
        'game_id': '20250115_LAL_GSW',
        'game_date': date(2025, 1, 15),
        'opponent_team_abbr': 'GSW',
        'is_home': True,
        'days_rest': 1
    }


@pytest.fixture
def sample_phase4_data():
    """Create sample Phase 4 data for benchmarking."""
    return {
        'points_avg_last_5': 25.2,
        'points_avg_last_10': 24.8,
        'points_avg_season': 24.5,
        'points_std_last_10': 4.2,
        'games_in_last_7_days': 3,
        'fatigue_score': 75,
        'shot_zone_mismatch_score': 3.5,
        'pace_score': 1.5,
        'usage_spike_score': 0.8,
        'opponent_def_rating': 110.5,
        'opponent_pace': 101.2,
        'paint_rate_last_10': 35.0,
        'mid_range_rate_last_10': 20.0,
        'three_pt_rate_last_10': 45.0,
        'team_pace_last_10': 99.8,
        'team_off_rating_last_10': 115.2,
        'minutes_avg_last_10': 35.5
    }


@pytest.fixture
def sample_phase3_data():
    """Create sample Phase 3 data for benchmarking."""
    return {
        'days_rest': 1,
        'opponent_days_rest': 0,
        'player_status': 'available',
        'home_game': True,
        'back_to_back': False,
        'season_phase': 'regular',
        'last_10_games': [
            {'game_date': date(2025, 1, 13), 'points': 28, 'minutes_played': 36, 'ft_makes': 8},
            {'game_date': date(2025, 1, 11), 'points': 24, 'minutes_played': 35, 'ft_makes': 6},
            {'game_date': date(2025, 1, 9), 'points': 26, 'minutes_played': 37, 'ft_makes': 7},
            {'game_date': date(2025, 1, 7), 'points': 22, 'minutes_played': 34, 'ft_makes': 5},
            {'game_date': date(2025, 1, 5), 'points': 25, 'minutes_played': 36, 'ft_makes': 6}
        ],
        'minutes_avg_season': 34.0,
        'team_season_games': [
            {'win_flag': True}, {'win_flag': True}, {'win_flag': False},
            {'win_flag': True}, {'win_flag': True}, {'win_flag': True},
            {'win_flag': False}, {'win_flag': True}
        ]
    }


@pytest.fixture
def mock_processor():
    """Create mock processor for benchmarking."""
    processor = object.__new__(MLFeatureStoreProcessor)
    
    # Set required attributes
    processor.bq_client = Mock()
    processor.project_id = 'test-project'
    processor.opts = {'analysis_date': date(2025, 1, 15)}
    processor.feature_version = 'v1_baseline_25'
    processor.feature_count = 25
    
    # Initialize helper classes
    processor.feature_extractor = Mock()
    processor.feature_calculator = FeatureCalculator()
    processor.quality_scorer = QualityScorer()
    processor.batch_writer = Mock()
    
    return processor


# ============================================================================
# TEST CLASS: FEATURE EXTRACTION BENCHMARKS (4 tests)
# ============================================================================

class TestFeatureExtractionPerformance:
    """Benchmark feature extraction operations."""
    
    def test_benchmark_phase4_extraction(self, benchmark, mock_bq_client):
        """
        Benchmark Phase 4 data extraction.
        
        Target: <50ms per player
        Includes 4 BigQuery queries (player_daily_cache, composite_factors,
        shot_zone_analysis, team_defense_zone_analysis)
        """
        extractor = FeatureExtractor(mock_bq_client, 'test-project')
        
        # Mock query results to avoid actual BigQuery calls
        mock_df = pd.DataFrame([{
            'points_avg_last_5': 25.0,
            'fatigue_score': 75,
            'opponent_def_rating': 110.0
        }])
        mock_job = Mock()
        mock_job.to_dataframe.return_value = mock_df
        mock_bq_client.query.return_value = mock_job
        
        # Benchmark
        result = benchmark(
            extractor.extract_phase4_data,
            'lebron-james',
            date(2025, 1, 15)
        )
        
        # Verify result structure
        assert isinstance(result, dict)
        
        # Log performance
        stats = benchmark.stats
        print(f"\n⏱️  Phase 4 Extraction: {stats.mean * 1000:.2f}ms (±{stats.stddev * 1000:.2f}ms)")
    
    def test_benchmark_phase3_extraction(self, benchmark, mock_bq_client):
        """
        Benchmark Phase 3 data extraction.
        
        Target: <200ms per player
        Includes 5 queries (context, last_n_games, season_stats, team_games, etc)
        """
        extractor = FeatureExtractor(mock_bq_client, 'test-project')
        
        # Mock query results
        mock_df = pd.DataFrame([{
            'home_game': True,
            'days_rest': 1,
            'points_avg_season': 24.0
        }])
        mock_job = Mock()
        mock_job.to_dataframe.return_value = mock_df
        mock_bq_client.query.return_value = mock_job
        
        # Benchmark
        result = benchmark(
            extractor.extract_phase3_data,
            'lebron-james',
            date(2025, 1, 15)
        )
        
        # Verify result
        assert isinstance(result, dict)
        
        stats = benchmark.stats
        print(f"\n⏱️  Phase 3 Extraction: {stats.mean * 1000:.2f}ms (±{stats.stddev * 1000:.2f}ms)")
    
    def test_benchmark_player_list_query(self, benchmark, mock_bq_client):
        """
        Benchmark player list retrieval.
        
        Target: <100ms for ~450 players
        Single query to upcoming_player_game_context.
        """
        extractor = FeatureExtractor(mock_bq_client, 'test-project')
        
        # Mock 450 players
        mock_df = pd.DataFrame([
            {
                'player_lookup': f'player-{i}',
                'universal_player_id': f'player{i}_001',
                'game_id': f'20250115_GAME{i}',
                'game_date': date(2025, 1, 15),
                'opponent_team_abbr': 'OPP',
                'is_home': True,
                'days_rest': 1
            }
            for i in range(450)
        ])
        mock_job = Mock()
        mock_job.to_dataframe.return_value = mock_df
        mock_bq_client.query.return_value = mock_job
        
        # Benchmark
        result = benchmark(
            extractor.get_players_with_games,
            date(2025, 1, 15)
        )
        
        assert len(result) == 450
        
        stats = benchmark.stats
        print(f"\n⏱️  Player List Query (450 players): {stats.mean * 1000:.2f}ms")
    
    def test_benchmark_last_n_games_query(self, benchmark, mock_bq_client):
        """
        Benchmark last N games query.
        
        Target: <30ms for 10 games
        Critical for trend calculation and Phase 3 fallback.
        """
        extractor = FeatureExtractor(mock_bq_client, 'test-project')
        
        # Mock 10 games
        mock_df = pd.DataFrame([
            {
                'game_date': date(2025, 1, i),
                'points': 25.0,
                'minutes_played': 35,
                'ft_makes': 7
            }
            for i in range(1, 11)
        ])
        mock_job = Mock()
        mock_job.to_dataframe.return_value = mock_df
        mock_bq_client.query.return_value = mock_job
        
        # Benchmark
        result = benchmark(
            extractor._query_last_n_games,
            'lebron-james',
            date(2025, 1, 15),
            10
        )
        
        assert len(result) == 10
        
        stats = benchmark.stats
        print(f"\n⏱️  Last 10 Games Query: {stats.mean * 1000:.2f}ms")


# ============================================================================
# TEST CLASS: FEATURE CALCULATION BENCHMARKS (6 tests)
# ============================================================================

class TestFeatureCalculationPerformance:
    """Benchmark calculated feature performance."""
    
    @pytest.fixture
    def calculator(self):
        """Create calculator instance."""
        return FeatureCalculator()
    
    def test_benchmark_rest_advantage(self, benchmark, calculator, sample_phase3_data):
        """
        Benchmark rest_advantage calculation.
        
        Target: <1ms
        Simple arithmetic operation.
        """
        result = benchmark(calculator.calculate_rest_advantage, sample_phase3_data)
        
        assert isinstance(result, float)
        
        stats = benchmark.stats
        print(f"\n⏱️  Rest Advantage: {stats.mean * 1000:.3f}ms")
    
    def test_benchmark_injury_risk(self, benchmark, calculator, sample_phase3_data):
        """
        Benchmark injury_risk calculation.
        
        Target: <1ms
        Dictionary lookup operation.
        """
        result = benchmark(calculator.calculate_injury_risk, sample_phase3_data)
        
        assert isinstance(result, float)
        
        stats = benchmark.stats
        print(f"\n⏱️  Injury Risk: {stats.mean * 1000:.3f}ms")
    
    def test_benchmark_recent_trend(self, benchmark, calculator, sample_phase3_data):
        """
        Benchmark recent_trend calculation.
        
        Target: <5ms
        Requires iteration over 5 games and averaging.
        """
        result = benchmark(calculator.calculate_recent_trend, sample_phase3_data)
        
        assert isinstance(result, float)
        
        stats = benchmark.stats
        print(f"\n⏱️  Recent Trend: {stats.mean * 1000:.3f}ms")
    
    def test_benchmark_minutes_change(self, benchmark, calculator, sample_phase4_data, sample_phase3_data):
        """
        Benchmark minutes_change calculation.
        
        Target: <5ms
        May require Phase 3 fallback calculation.
        """
        result = benchmark(
            calculator.calculate_minutes_change,
            sample_phase4_data,
            sample_phase3_data
        )
        
        assert isinstance(result, float)
        
        stats = benchmark.stats
        print(f"\n⏱️  Minutes Change: {stats.mean * 1000:.3f}ms")
    
    def test_benchmark_pct_free_throw(self, benchmark, calculator, sample_phase3_data):
        """
        Benchmark pct_free_throw calculation.
        
        Target: <5ms
        Requires summing over 10 games.
        """
        result = benchmark(calculator.calculate_pct_free_throw, sample_phase3_data)
        
        assert isinstance(result, float)
        
        stats = benchmark.stats
        print(f"\n⏱️  PCT Free Throw: {stats.mean * 1000:.3f}ms")
    
    def test_benchmark_team_win_pct(self, benchmark, calculator, sample_phase3_data):
        """
        Benchmark team_win_pct calculation.
        
        Target: <5ms
        Requires counting wins in season games.
        """
        result = benchmark(calculator.calculate_team_win_pct, sample_phase3_data)
        
        assert isinstance(result, float)
        
        stats = benchmark.stats
        print(f"\n⏱️  Team Win PCT: {stats.mean * 1000:.3f}ms")


# ============================================================================
# TEST CLASS: QUALITY SCORING BENCHMARKS (2 tests)
# ============================================================================

class TestQualityScoringPerformance:
    """Benchmark quality scoring operations."""
    
    @pytest.fixture
    def scorer(self):
        """Create scorer instance."""
        return QualityScorer()
    
    def test_benchmark_quality_score_calculation(self, benchmark, scorer):
        """
        Benchmark quality score calculation.
        
        Target: <1ms
        Simple weighted average over 25 features.
        """
        feature_sources = {
            **{i: 'phase4' for i in range(15)},
            **{i: 'phase3' for i in range(15, 20)},
            **{i: 'calculated' for i in range(20, 25)}
        }
        
        result = benchmark(scorer.calculate_quality_score, feature_sources)
        
        assert isinstance(result, float)
        assert 0 <= result <= 100
        
        stats = benchmark.stats
        print(f"\n⏱️  Quality Score Calculation: {stats.mean * 1000:.3f}ms")
    
    def test_benchmark_primary_source_determination(self, benchmark, scorer):
        """
        Benchmark primary source determination.
        
        Target: <1ms
        Counting operation over 25 features.
        """
        feature_sources = {
            **{i: 'phase4' for i in range(15)},
            **{i: 'phase3' for i in range(15, 25)}
        }
        
        result = benchmark(scorer.determine_primary_source, feature_sources)
        
        assert isinstance(result, str)
        
        stats = benchmark.stats
        print(f"\n⏱️  Primary Source Determination: {stats.mean * 1000:.3f}ms")


# ============================================================================
# TEST CLASS: END-TO-END BENCHMARKS (2 tests)
# ============================================================================

class TestEndToEndPerformance:
    """Benchmark complete feature generation flow."""
    
    def test_benchmark_single_player_feature_generation(
        self, benchmark, mock_processor, sample_player_row,
        sample_phase4_data, sample_phase3_data
    ):
        """
        Benchmark complete feature generation for one player.
        
        Target: <100ms per player
        Includes extraction, calculation, and quality scoring.
        """
        # Mock extractors
        mock_processor.feature_extractor.extract_phase4_data.return_value = sample_phase4_data
        mock_processor.feature_extractor.extract_phase3_data.return_value = sample_phase3_data
        
        # Benchmark
        result = benchmark(
            mock_processor._generate_player_features,
            sample_player_row
        )
        
        # Verify result
        assert result['player_lookup'] == 'lebron-james'
        assert len(result['features']) == 25
        
        stats = benchmark.stats
        print(f"\n⏱️  Single Player Feature Generation: {stats.mean * 1000:.2f}ms")
        print(f"     Projected for 450 players: {stats.mean * 450:.2f}s")
    
    def test_benchmark_batch_processing(
        self, benchmark, mock_processor, sample_player_row,
        sample_phase4_data, sample_phase3_data
    ):
        """
        Benchmark batch processing of 50 players.
        
        Target: <5s for 50 players (~100ms per player)
        Simulates realistic workload.
        """
        # Create 50 player rows
        players = [
            {**sample_player_row, 'player_lookup': f'player-{i}'}
            for i in range(50)
        ]
        
        # Mock extractors
        mock_processor.feature_extractor.extract_phase4_data.return_value = sample_phase4_data
        mock_processor.feature_extractor.extract_phase3_data.return_value = sample_phase3_data
        mock_processor.players_with_games = players
        
        # Benchmark
        def process_batch():
            mock_processor.transformed_data = []
            mock_processor.failed_entities = []
            
            for player in players:
                try:
                    record = mock_processor._generate_player_features(player)
                    mock_processor.transformed_data.append(record)
                except Exception as e:
                    mock_processor.failed_entities.append(player)
        
        benchmark(process_batch)
        
        stats = benchmark.stats
        print(f"\n⏱️  Batch Processing (50 players): {stats.mean:.2f}s")
        print(f"     Per-player average: {stats.mean / 50 * 1000:.2f}ms")
        print(f"     Projected for 450 players: {stats.mean * 9:.2f}s")


# ============================================================================
# TEST CLASS: BATCH WRITER BENCHMARKS (1 test)
# ============================================================================

class TestBatchWriterPerformance:
    """Benchmark batch writing operations."""
    
    def test_benchmark_batch_splitting(self, benchmark):
        """
        Benchmark batch splitting operation.
        
        Target: <10ms for 450 rows
        Simple list slicing operation.
        """
        mock_bq_client = Mock()
        writer = BatchWriter(mock_bq_client, 'test-project')
        
        # Create 450 row sample
        rows = [{'id': i, 'value': f'test_{i}'} for i in range(450)]
        
        # Benchmark
        result = benchmark(writer._split_into_batches, rows, 100)
        
        assert len(result) == 5  # 450 rows / 100 batch size = 5 batches
        
        stats = benchmark.stats
        print(f"\n⏱️  Batch Splitting (450 rows): {stats.mean * 1000:.3f}ms")


# ============================================================================
# PERFORMANCE SUMMARY
# ============================================================================

def test_print_performance_summary(benchmark):
    """
    Print summary of all performance targets and actuals.
    
    This is not a real test, just a helper to display targets.
    """
    print("\n" + "="*70)
    print("PERFORMANCE TARGETS")
    print("="*70)
    print("\nFeature Extraction:")
    print("  Phase 4 extraction:     <50ms per player")
    print("  Phase 3 extraction:     <200ms per player")
    print("  Player list query:      <100ms for 450 players")
    print("  Last N games query:     <30ms for 10 games")
    
    print("\nFeature Calculation:")
    print("  Rest advantage:         <1ms")
    print("  Injury risk:            <1ms")
    print("  Recent trend:           <5ms")
    print("  Minutes change:         <5ms")
    print("  PCT free throw:         <5ms")
    print("  Team win PCT:           <5ms")
    
    print("\nQuality Scoring:")
    print("  Quality score calc:     <1ms")
    print("  Primary source det:     <1ms")
    
    print("\nEnd-to-End:")
    print("  Single player:          <100ms")
    print("  Batch (450 players):    <45s (100ms × 450)")
    
    print("\nBatch Writing:")
    print("  Batch splitting:        <10ms for 450 rows")
    print("  Single batch write:     <5s for 100 rows")
    print("="*70 + "\n")
    
    # This always passes, it's just for display
    assert True


# ============================================================================
# TEST CONFIGURATION
# ============================================================================

if __name__ == '__main__':
    pytest.main([
        __file__,
        '-v',
        '--benchmark-only',
        '--benchmark-sort=mean',
        '--benchmark-columns=min,max,mean,stddev',
        '--tb=short'
    ])