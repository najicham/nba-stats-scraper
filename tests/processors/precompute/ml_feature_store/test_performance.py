"""
Performance/Benchmark Tests for ML Feature Store

These tests measure the performance of various operations in the ML Feature Store.
All tests use mocked BigQuery to avoid real database calls and ensure consistent results.

Run with:
    pytest test_performance.py -v --benchmark-only
    pytest test_performance.py -v --benchmark-columns=min,max,mean,stddev

To save and compare benchmarks:
    pytest test_performance.py --benchmark-save=baseline
    pytest test_performance.py --benchmark-compare=baseline

Directory: tests/processors/precompute/ml_feature_store/
"""

import pytest

# Skip all tests in this module - performance benchmarks need specific setup
pytestmark = pytest.mark.skip(reason="Performance benchmarks need pytest-benchmark plugin and specific setup")
from unittest.mock import Mock
import pandas as pd
from datetime import date, datetime

# Import classes we're testing
from data_processors.precompute.ml_feature_store.feature_extractor import FeatureExtractor
from data_processors.precompute.ml_feature_store.feature_calculator import FeatureCalculator
from data_processors.precompute.ml_feature_store.quality_scorer import QualityScorer
from data_processors.precompute.ml_feature_store.batch_writer import BatchWriter
from data_processors.precompute.ml_feature_store.ml_feature_store_processor import MLFeatureStoreProcessor


# ============================================================================
# MOCK FIXTURES
# ============================================================================

@pytest.fixture
def mock_bq_client_with_players():
    """
    Mock BigQuery client that returns realistic player data.
    
    Returns 450 players for a typical game day.
    Prevents "No players found" warnings.
    """
    client = Mock()
    
    # Create 450 players (realistic game day volume)
    players_data = []
    teams = ['LAL', 'GSW', 'BOS', 'MIA', 'PHX', 'DAL', 'MIL', 'DEN', 'PHI', 'BRK']
    
    for i in range(450):
        players_data.append({
            'player_lookup': f'player-{i}',
            'universal_player_id': f'player_{i:03d}_001',
            'game_id': f'game_{i // 15:03d}',
            'game_date': date(2025, 1, 15),
            'opponent_team_abbr': teams[i % len(teams)],
            'is_home': i % 2 == 0,
            'days_rest': (i % 4)
        })
    
    players_df = pd.DataFrame(players_data)
    
    # Configure mock
    mock_result = Mock()
    mock_result.to_dataframe.return_value = players_df
    mock_result.empty = False
    client.query.return_value = mock_result
    
    return client


@pytest.fixture
def mock_bq_client_with_games():
    """
    Mock BigQuery client that returns historical game data.
    
    Returns 10 historical games for a player.
    Prevents "No games found" warnings.
    """
    client = Mock()
    
    # Create 10 historical games
    games_data = []
    for i in range(10):
        games_data.append({
            'game_date': f'2025-01-{15-i:02d}',
            'points': 18 + (i % 12),
            'minutes_played': 28 + (i % 10),
            'ft_makes': 4 + (i % 6),
            'fg_attempts': 12 + (i % 8),
            'paint_attempts': 5 + (i % 5),
            'mid_range_attempts': 3 + (i % 4),
            'three_pt_attempts': 4 + (i % 6)
        })
    
    games_df = pd.DataFrame(games_data)
    
    # Configure mock
    mock_result = Mock()
    mock_result.to_dataframe.return_value = games_df
    mock_result.empty = False
    client.query.return_value = mock_result
    
    return client


@pytest.fixture
def mock_bq_client_smart():
    """
    Smart mock that returns different data based on query type.
    
    Examines SQL query and returns appropriate mock data.
    Most realistic approach for complex tests.
    """
    client = Mock()
    
    def smart_query_response(sql_query):
        """Return different mock data based on query."""
        mock_result = Mock()
        
        if 'upcoming_player_game_context' in sql_query:
            # Return player list
            players_data = [{'player_lookup': f'player-{i}', 'game_id': f'g{i}'} for i in range(450)]
            mock_result.to_dataframe.return_value = pd.DataFrame(players_data)
            mock_result.empty = False
            
        elif 'player_game_summary' in sql_query and 'LIMIT' in sql_query:
            # Return last N games
            games_data = [{'game_date': f'2025-01-{15-i:02d}', 'points': 20 + i} for i in range(10)]
            mock_result.to_dataframe.return_value = pd.DataFrame(games_data)
            mock_result.empty = False
            
        elif 'player_daily_cache' in sql_query:
            # Return Phase 4 cache data
            cache_data = pd.DataFrame([{
                'points_avg_last_5': 22.5,
                'points_avg_last_10': 23.1,
                'minutes_avg_last_10': 33.2,
                'points_avg_season': 22.8,
                'points_std_last_10': 4.5,
                'games_in_last_7_days': 3,
                'paint_rate_last_10': 32.0,
                'three_pt_rate_last_10': 35.0,
                'assisted_rate_last_10': 45.0,
                'team_pace_last_10': 99.5,
                'team_off_rating_last_10': 112.3,
                'player_age': 39
            }])
            mock_result.to_dataframe.return_value = cache_data
            mock_result.empty = False
            
        elif 'player_composite_factors' in sql_query:
            # Return composite factors
            composite_data = pd.DataFrame([{
                'fatigue_score': 65.0,
                'shot_zone_mismatch_score': 2.5,
                'pace_score': 1.2,
                'usage_spike_score': 0.8,
                'opponent_team_abbr': 'GSW'
            }])
            mock_result.to_dataframe.return_value = composite_data
            mock_result.empty = False
            
        else:
            # Unknown query - return empty
            mock_result.to_dataframe.return_value = pd.DataFrame()
            mock_result.empty = True
        
        return mock_result
    
    client.query = Mock(side_effect=smart_query_response)
    return client


@pytest.fixture
def sample_phase3_data():
    """Sample Phase 3 data for testing."""
    return {
        'days_rest': 2,
        'opponent_days_rest': 1,
        'player_status': 'available',
        'home_game': True,
        'back_to_back': False,
        'last_10_games': [
            {'points': 25, 'minutes_played': 35, 'ft_makes': 7},
            {'points': 22, 'minutes_played': 33, 'ft_makes': 5},
            {'points': 28, 'minutes_played': 37, 'ft_makes': 8},
            {'points': 20, 'minutes_played': 32, 'ft_makes': 4},
            {'points': 24, 'minutes_played': 34, 'ft_makes': 6},
        ],
        'team_season_games': [
            {'win_flag': True}, {'win_flag': True}, {'win_flag': False},
            {'win_flag': True}, {'win_flag': False}
        ]
    }


@pytest.fixture
def sample_phase4_data():
    """Sample Phase 4 data for testing."""
    return {
        'points_avg_last_5': 22.5,
        'points_avg_last_10': 23.1,
        'minutes_avg_last_10': 33.2,
        'points_avg_season': 22.8
    }


# ============================================================================
# FEATURE EXTRACTION PERFORMANCE TESTS
# ============================================================================

class TestFeatureExtractionPerformance:
    """Test performance of data extraction operations."""
    
    def test_benchmark_phase4_extraction(self, benchmark, mock_bq_client_smart):
        """Benchmark Phase 4 data extraction."""
        extractor = FeatureExtractor(mock_bq_client_smart, 'test-project')
        
        result = benchmark(extractor.extract_phase4_data, 'lebron-james', date(2025, 1, 15))
        
        # Verify we got some data back
        assert isinstance(result, dict)
        
        # Print performance
        print(f"\n⏱️  Phase 4 Extraction: {benchmark.stats.mean * 1000:.2f}ms (±{benchmark.stats.stddev * 1000:.2f}ms)")
    
    def test_benchmark_phase3_extraction(self, benchmark, mock_bq_client_smart):
        """Benchmark Phase 3 data extraction."""
        extractor = FeatureExtractor(mock_bq_client_smart, 'test-project')
        
        result = benchmark(extractor.extract_phase3_data, 'lebron-james', date(2025, 1, 15))
        
        # Verify we got some data back
        assert isinstance(result, dict)
        
        # Print performance
        print(f"\n⏱️  Phase 3 Extraction: {benchmark.stats.mean * 1000:.2f}ms (±{benchmark.stats.stddev * 1000:.2f}ms)")
    
    def test_benchmark_player_list_query(self, benchmark, mock_bq_client_with_players):
        """Benchmark getting list of players with games."""
        extractor = FeatureExtractor(mock_bq_client_with_players, 'test-project')
        
        result = benchmark(extractor.get_players_with_games, date(2025, 1, 15))
        
        # Verify we got 450 players
        assert len(result) == 450
        
        # Print performance
        print(f"\n⏱️  Player List Query: {benchmark.stats.mean * 1000:.2f}ms")
    
    def test_benchmark_last_n_games_query(self, benchmark, mock_bq_client_with_games):
        """Benchmark querying last N games for a player."""
        extractor = FeatureExtractor(mock_bq_client_with_games, 'test-project')
        
        result = benchmark(extractor._query_last_n_games, 'lebron-james', date(2025, 1, 15), 10)
        
        # Verify we got 10 games
        assert len(result) == 10
        
        # Print performance
        print(f"\n⏱️  Last N Games Query: {benchmark.stats.mean * 1000:.2f}ms")


# ============================================================================
# FEATURE CALCULATION PERFORMANCE TESTS
# ============================================================================

class TestFeatureCalculationPerformance:
    """Test performance of feature calculation operations."""
    
    def test_benchmark_rest_advantage(self, benchmark, sample_phase3_data):
        """Benchmark rest advantage calculation."""
        calculator = FeatureCalculator()
        
        result = benchmark(calculator.calculate_rest_advantage, sample_phase3_data)
        
        # Verify result
        assert isinstance(result, float)
        assert -2.0 <= result <= 2.0
        
        # Print performance
        print(f"\n⏱️  Rest Advantage: {benchmark.stats.mean * 1000:.3f}ms")
    
    def test_benchmark_injury_risk(self, benchmark, sample_phase3_data):
        """Benchmark injury risk calculation."""
        calculator = FeatureCalculator()
        
        result = benchmark(calculator.calculate_injury_risk, sample_phase3_data)
        
        # Verify result
        assert isinstance(result, float)
        assert 0.0 <= result <= 3.0
        
        # Print performance
        print(f"\n⏱️  Injury Risk: {benchmark.stats.mean * 1000:.3f}ms")
    
    def test_benchmark_recent_trend(self, benchmark, sample_phase3_data):
        """Benchmark recent trend calculation."""
        calculator = FeatureCalculator()
        
        result = benchmark(calculator.calculate_recent_trend, sample_phase3_data)
        
        # Verify result
        assert isinstance(result, float)
        assert -2.0 <= result <= 2.0
        
        # Print performance
        print(f"\n⏱️  Recent Trend: {benchmark.stats.mean * 1000:.3f}ms")
    
    def test_benchmark_minutes_change(self, benchmark, sample_phase4_data, sample_phase3_data):
        """Benchmark minutes change calculation."""
        calculator = FeatureCalculator()
        
        result = benchmark(calculator.calculate_minutes_change, sample_phase4_data, sample_phase3_data)
        
        # Verify result
        assert isinstance(result, float)
        assert -2.0 <= result <= 2.0
        
        # Print performance
        print(f"\n⏱️  Minutes Change: {benchmark.stats.mean * 1000:.3f}ms")
    
    def test_benchmark_pct_free_throw(self, benchmark, sample_phase3_data):
        """Benchmark free throw percentage calculation."""
        calculator = FeatureCalculator()
        
        result = benchmark(calculator.calculate_pct_free_throw, sample_phase3_data)
        
        # Verify result
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0
        
        # Print performance
        print(f"\n⏱️  PCT Free Throw: {benchmark.stats.mean * 1000:.3f}ms")
    
    def test_benchmark_team_win_pct(self, benchmark, sample_phase3_data):
        """Benchmark team win percentage calculation."""
        calculator = FeatureCalculator()
        
        result = benchmark(calculator.calculate_team_win_pct, sample_phase3_data)
        
        # Verify result
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0
        
        # Print performance
        print(f"\n⏱️  Team Win PCT: {benchmark.stats.mean * 1000:.3f}ms")


# ============================================================================
# QUALITY SCORING PERFORMANCE TESTS
# ============================================================================

class TestQualityScoringPerformance:
    """Test performance of quality scoring operations."""
    
    def test_benchmark_quality_score_calculation(self, benchmark):
        """Benchmark quality score calculation."""
        scorer = QualityScorer()
        
        # Create feature sources (19 Phase 4 + 6 calculated)
        feature_sources = {
            **{i: 'phase4' for i in range(19)},
            **{i: 'calculated' for i in range(19, 25)}
        }
        
        result = benchmark(scorer.calculate_quality_score, feature_sources)
        
        # Verify result
        assert isinstance(result, float)
        assert 0.0 <= result <= 100.0
        
        # Print performance
        print(f"\n⏱️  Quality Score Calculation: {benchmark.stats.mean * 1000:.3f}ms")
    
    def test_benchmark_primary_source_determination(self, benchmark):
        """Benchmark primary source determination."""
        scorer = QualityScorer()
        
        # Create feature sources
        feature_sources = {
            **{i: 'phase4' for i in range(19)},
            **{i: 'calculated' for i in range(19, 25)}
        }
        
        result = benchmark(scorer.determine_primary_source, feature_sources)
        
        # Verify result
        assert result in ['phase4', 'phase3', 'calculated', 'mixed', 'default']
        
        # Print performance
        print(f"\n⏱️  Primary Source Determination: {benchmark.stats.mean * 1000:.3f}ms")


# ============================================================================
# END-TO-END PERFORMANCE TESTS
# ============================================================================

class TestEndToEndPerformance:
    """Test end-to-end performance scenarios."""
    
    def test_benchmark_single_player_feature_generation(self, benchmark):
        """Benchmark generating features for a single player."""
        # Create processor with mocked dependencies
        processor = MLFeatureStoreProcessor.__new__(MLFeatureStoreProcessor)
        processor.source_metadata = {}  # Required for v4.0 dependency tracking
        processor.bq_client = Mock()
        processor.project_id = 'test-project'
        processor.feature_version = 'v1_baseline_25'
        processor.feature_count = 25
        
        # Mock helper classes
        processor.feature_extractor = Mock()
        processor.feature_calculator = Mock()
        processor.quality_scorer = Mock()
        
        # Mock data returns
        processor.feature_extractor.extract_phase4_data.return_value = {
            'points_avg_last_5': 22.5,
            'points_avg_last_10': 23.1
        }
        processor.feature_extractor.extract_phase3_data.return_value = {
            'days_rest': 2,
            'opponent_days_rest': 1
        }
        
        # Mock feature extraction
        processor._extract_all_features = Mock(return_value=(
            [0.0] * 25,
            {i: 'phase4' for i in range(25)}
        ))
        
        processor.quality_scorer.calculate_quality_score.return_value = 95.0
        processor.quality_scorer.determine_primary_source.return_value = 'phase4'
        
        # Mock calculated features
        processor.feature_calculator.calculate_rest_advantage.return_value = 1.0
        processor.feature_calculator.calculate_injury_risk.return_value = 0.0
        processor.feature_calculator.calculate_recent_trend.return_value = 0.0
        processor.feature_calculator.calculate_minutes_change.return_value = 0.0
        processor.feature_calculator.calculate_pct_free_throw.return_value = 0.15
        processor.feature_calculator.calculate_team_win_pct.return_value = 0.55
        
        # Mock source tracking
        processor.build_source_tracking_fields = Mock(return_value={
            'source_daily_cache_last_updated': datetime.now().isoformat(),
            'source_daily_cache_rows_found': 1,
            'source_daily_cache_completeness_pct': 100.0,
            'source_composite_last_updated': datetime.now().isoformat(),
            'source_composite_rows_found': 1,
            'source_composite_completeness_pct': 100.0,
            'source_shot_zones_last_updated': datetime.now().isoformat(),
            'source_shot_zones_rows_found': 1,
            'source_shot_zones_completeness_pct': 100.0,
            'source_team_defense_last_updated': datetime.now().isoformat(),
            'source_team_defense_rows_found': 1,
            'source_team_defense_completeness_pct': 100.0
        })
        
        # Sample player row
        player_row = {
            'player_lookup': 'lebron-james',
            'universal_player_id': 'jamesle01_001',
            'game_id': '20250115_LAL_GSW',
            'opponent_team_abbr': 'GSW',
            'is_home': True,
            'days_rest': 2
        }
        
        # Benchmark
        result = benchmark(processor._generate_player_features, player_row)
        
        # Verify result
        assert 'player_lookup' in result
        assert 'features' in result
        
        # Print performance
        print(f"\n⏱️  Single Player Feature Generation: {benchmark.stats.mean * 1000:.2f}ms")
    
    def test_benchmark_batch_processing(self, benchmark, mock_bq_client_with_players):
        """Benchmark processing a batch of 50 players."""
        # This is a simplified batch processing test
        extractor = FeatureExtractor(mock_bq_client_with_players, 'test-project')
        calculator = FeatureCalculator()
        
        def process_batch():
            # Get players
            players = extractor.get_players_with_games(date(2025, 1, 15))[:50]
            
            # Process each player (simplified)
            results = []
            for player in players:
                # Simulate feature calculation
                rest_adv = calculator.calculate_rest_advantage({'days_rest': 2, 'opponent_days_rest': 1})
                injury = calculator.calculate_injury_risk({'player_status': 'available'})
                results.append({'player': player, 'rest': rest_adv, 'injury': injury})
            
            return results
        
        result = benchmark(process_batch)
        
        # Verify we processed 50 players
        assert len(result) == 50
        
        # Print performance
        print(f"\n⏱️  Batch Processing (50 players): {benchmark.stats.mean:.2f}s")


# ============================================================================
# BATCH WRITER PERFORMANCE TESTS
# ============================================================================

class TestBatchWriterPerformance:
    """Test performance of batch writing operations."""
    
    def test_benchmark_batch_splitting(self, benchmark):
        """Benchmark splitting rows into batches."""
        writer = BatchWriter(Mock(), 'test-project')
        
        # Create 450 rows
        rows = [{'player': f'player-{i}', 'data': i} for i in range(450)]
        
        result = benchmark(writer._split_into_batches, rows, batch_size=100)
        
        # Verify we got 5 batches (100 + 100 + 100 + 100 + 50)
        assert len(result) == 5
        assert len(result[0]) == 100
        assert len(result[4]) == 50
        
        # Print performance
        print(f"\n⏱️  Batch Splitting (450 rows): {benchmark.stats.mean * 1000:.3f}ms")


# ============================================================================
# SUMMARY TEST
# ============================================================================

def test_print_performance_summary():
    """Print performance test summary."""
    print("\n" + "="*70)
    print("PERFORMANCE TEST SUMMARY")
    print("="*70)
    print("\nAll performance benchmarks completed!")
    print("Review the timing information above for performance metrics.")
    print("\nTo compare against baseline:")
    print("  pytest test_performance.py --benchmark-save=baseline")
    print("  pytest test_performance.py --benchmark-compare=baseline")
    print("="*70)


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--benchmark-only'])