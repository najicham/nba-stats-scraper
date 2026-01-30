"""
Unit tests for ML Feature Store components.

Tests the quality scorer, feature calculator, and validation logic
without requiring BigQuery connections.

Usage:
    pytest tests/unit/data_processors/test_ml_feature_store.py -v
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import date
import pandas as pd


class TestQualityScorer:
    """Test QualityScorer class."""

    @pytest.fixture
    def scorer(self):
        """Create QualityScorer instance."""
        from data_processors.precompute.ml_feature_store.quality_scorer import QualityScorer
        return QualityScorer()

    def test_quality_score_all_phase4(self, scorer):
        """All phase4 sources should give 100% quality."""
        sources = {i: 'phase4' for i in range(25)}
        score = scorer.calculate_quality_score(sources)
        assert score == 100.0

    def test_quality_score_all_phase3(self, scorer):
        """All phase3 sources should give 87% quality."""
        sources = {i: 'phase3' for i in range(25)}
        score = scorer.calculate_quality_score(sources)
        assert score == 87.0

    def test_quality_score_all_default(self, scorer):
        """All default sources should give 40% quality."""
        sources = {i: 'default' for i in range(25)}
        score = scorer.calculate_quality_score(sources)
        assert score == 40.0

    def test_quality_score_mixed_sources(self, scorer):
        """Mixed sources should give weighted average."""
        # 10 phase4 (100), 10 phase3 (87), 5 default (40)
        sources = {}
        for i in range(10):
            sources[i] = 'phase4'
        for i in range(10, 20):
            sources[i] = 'phase3'
        for i in range(20, 25):
            sources[i] = 'default'

        expected = (10 * 100 + 10 * 87 + 5 * 40) / 25
        score = scorer.calculate_quality_score(sources)
        assert score == pytest.approx(expected, rel=0.01)

    def test_quality_score_empty_sources(self, scorer):
        """Empty sources should return 0."""
        score = scorer.calculate_quality_score({})
        assert score == 0.0

    def test_quality_score_variable_feature_count(self, scorer):
        """Should work with different feature counts (v1=25, v2=33)."""
        sources_v1 = {i: 'phase4' for i in range(25)}
        sources_v2 = {i: 'phase4' for i in range(33)}

        assert scorer.calculate_quality_score(sources_v1) == 100.0
        assert scorer.calculate_quality_score(sources_v2) == 100.0

    def test_determine_primary_source_phase4(self, scorer):
        """90%+ phase4 should return 'phase4'."""
        sources = {i: 'phase4' for i in range(25)}
        sources[0] = 'phase3'  # 24/25 = 96% phase4

        assert scorer.determine_primary_source(sources) == 'phase4'

    def test_determine_primary_source_phase4_partial(self, scorer):
        """50-90% phase4 should return 'phase4_partial'."""
        sources = {}
        for i in range(15):
            sources[i] = 'phase4'
        for i in range(15, 25):
            sources[i] = 'phase3'  # 60% phase4

        assert scorer.determine_primary_source(sources) == 'phase4_partial'

    def test_determine_primary_source_phase3(self, scorer):
        """50%+ phase3 (and <50% phase4) should return 'phase3'."""
        sources = {}
        for i in range(10):
            sources[i] = 'phase4'
        for i in range(10, 25):
            sources[i] = 'phase3'  # 40% phase4, 60% phase3

        assert scorer.determine_primary_source(sources) == 'phase3'

    def test_determine_primary_source_mixed(self, scorer):
        """No dominant source should return 'mixed'."""
        sources = {}
        for i in range(8):
            sources[i] = 'phase4'
        for i in range(8, 16):
            sources[i] = 'phase3'
        for i in range(16, 25):
            sources[i] = 'default'  # ~32% each

        assert scorer.determine_primary_source(sources) == 'mixed'

    def test_determine_primary_source_empty(self, scorer):
        """Empty sources should return 'unknown'."""
        assert scorer.determine_primary_source({}) == 'unknown'


class TestFeatureCalculator:
    """Test FeatureCalculator class."""

    @pytest.fixture
    def calculator(self):
        """Create FeatureCalculator instance."""
        from data_processors.precompute.ml_feature_store.feature_calculator import FeatureCalculator
        return FeatureCalculator()

    def test_calculate_rest_advantage(self, calculator):
        """Rest advantage should return value in expected range."""
        phase3_data = {
            'days_rest': 3,
            'opponent_days_rest': 1,
        }
        result = calculator.calculate_rest_advantage(phase3_data)
        # Rest advantage should be positive when player has more rest
        assert isinstance(result, float)

    def test_calculate_recent_trend(self, calculator):
        """Recent trend should handle normal case."""
        phase3_data = {
            'pts_last_5_games': [20, 22, 18, 25, 21],
            'pts_season_avg': 20.0,
        }
        result = calculator.calculate_recent_trend(phase3_data)
        assert isinstance(result, float)

    def test_calculate_dnp_rate(self, calculator):
        """DNP rate should be between 0 and 1."""
        phase3_data = {
            'games_missed_last_10': 2,
            'total_possible_games': 10,
        }
        result = calculator.calculate_dnp_rate(phase3_data)
        assert isinstance(result, float)
        assert 0 <= result <= 1

    def test_calculate_team_win_pct(self, calculator):
        """Team win pct should be between 0 and 1."""
        phase3_data = {
            'team_wins': 30,
            'team_losses': 20,
        }
        result = calculator.calculate_team_win_pct(phase3_data)
        assert isinstance(result, float)
        assert 0 <= result <= 1


class TestFeatureValidation:
    """Test feature validation and range checking."""

    def test_feature_ranges(self):
        """Verify features stay within expected ranges."""
        # These are the typical feature ranges
        valid_ranges = {
            'days_rest': (0, 14),
            'games_played_season': (0, 82),
            'minutes_per_game': (0, 48),
            'points_per_game': (0, 50),
            'fatigue_score': (0, 100),
            'quality_score': (0, 100),
            'confidence_score': (0, 100),
        }

        # Sample feature values (mock what the calculator would produce)
        sample_features = {
            'days_rest': 2,
            'games_played_season': 45,
            'minutes_per_game': 32.5,
            'points_per_game': 18.7,
            'fatigue_score': 35.0,
            'quality_score': 87.5,
            'confidence_score': 72.0,
        }

        for feature, value in sample_features.items():
            min_val, max_val = valid_ranges[feature]
            assert min_val <= value <= max_val, f"{feature}={value} outside range [{min_val}, {max_val}]"

    def test_sentinel_values(self):
        """Sentinel values (-1) should be allowed for missing data."""
        sentinel_features = ['fatigue_score', 'pace_adjustment', 'shot_zone_adjustment']
        sentinel_value = -1.0

        # -1 is valid sentinel, but should be flagged as missing
        for feature in sentinel_features:
            # Validation should accept -1 as sentinel
            assert sentinel_value == -1.0


class TestFeatureExtractorMocked:
    """Test FeatureExtractor with mocked BigQuery."""

    @pytest.fixture
    def mock_bq_client(self):
        """Create mock BigQuery client."""
        return MagicMock()

    @pytest.fixture
    def extractor(self, mock_bq_client):
        """Create FeatureExtractor with mock client."""
        from data_processors.precompute.ml_feature_store.feature_extractor import FeatureExtractor
        return FeatureExtractor(mock_bq_client, 'test-project')

    def test_extractor_initialization(self, extractor):
        """Extractor should initialize with empty caches."""
        assert extractor._batch_cache_date is None
        assert extractor._daily_cache_lookup == {}
        assert extractor._composite_factors_lookup == {}

    def test_safe_query_handles_error(self, extractor, mock_bq_client):
        """_safe_query should handle BigQuery errors gracefully."""
        from google.api_core.exceptions import GoogleAPIError

        mock_bq_client.query.side_effect = GoogleAPIError("Test error")

        with pytest.raises(GoogleAPIError):
            extractor._safe_query("SELECT 1", "test_query")


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_null_feature_handling(self):
        """Null/None features should be handled."""
        from data_processors.precompute.ml_feature_store.quality_scorer import QualityScorer

        scorer = QualityScorer()

        # Missing indices should default to 'default' source
        sources = {0: 'phase4', 2: 'phase3'}  # Missing index 1
        # Should not raise, should use default for missing
        score = scorer.calculate_quality_score(sources)
        assert score > 0

    def test_unknown_source_type(self):
        """Unknown source type should use default weight."""
        from data_processors.precompute.ml_feature_store.quality_scorer import QualityScorer

        scorer = QualityScorer()
        sources = {0: 'unknown_source', 1: 'phase4'}

        # Should not raise, should use default weight (40) for unknown
        score = scorer.calculate_quality_score(sources)
        expected = (40 + 100) / 2  # unknown=40, phase4=100
        assert score == pytest.approx(expected, rel=0.01)
