"""
Unit Tests for WindowCompletenessValidator

Tests the rolling window completeness validator that prevents
contaminated statistics from incomplete data.

Created: 2026-01-26
"""

import pytest
from datetime import date
from unittest.mock import Mock

from shared.validation.window_completeness import (
    WindowCompletenessValidator,
    WindowResult
)


class TestWindowCompletenessValidator:
    """Test suite for WindowCompletenessValidator."""

    @pytest.fixture
    def mock_completeness_checker(self):
        """Mock CompletenessChecker."""
        return Mock()

    @pytest.fixture
    def validator(self, mock_completeness_checker):
        """Create WindowCompletenessValidator with mocked checker."""
        return WindowCompletenessValidator(
            completeness_checker=mock_completeness_checker,
            compute_threshold=0.7
        )

    def test_check_player_windows_complete(self, validator, mock_completeness_checker):
        """Test checking complete windows returns 'compute' recommendation."""
        # Mock 100% completeness for all windows
        mock_completeness_checker.check_completeness_batch.return_value = {
            'player1': {
                'expected_count': 10,
                'actual_count': 10,
                'completeness_pct': 100.0,
                'is_complete': True,
                'dnp_count': 0,
                'gap_classification': 'NO_GAP'
            }
        }

        results = validator.check_player_windows(
            player_id='player1',
            game_date=date(2026, 1, 26),
            window_sizes=[5, 10, 15, 20]
        )

        assert len(results) == 4
        for window_size, result in results.items():
            assert result.is_complete is True
            assert result.completeness_ratio == 1.0
            assert result.recommendation == 'compute'
            assert result.games_available == 10
            assert result.games_required == 10

    def test_check_player_windows_partial(self, validator, mock_completeness_checker):
        """Test partial completeness returns 'compute_with_flag'."""
        # Mock 80% completeness
        mock_completeness_checker.check_completeness_batch.return_value = {
            'player1': {
                'expected_count': 10,
                'actual_count': 8,
                'completeness_pct': 80.0,
                'is_complete': False,
                'dnp_count': 0,
                'gap_classification': 'DATA_GAP'
            }
        }

        results = validator.check_player_windows(
            player_id='player1',
            game_date=date(2026, 1, 26),
            window_sizes=[10]
        )

        result = results[10]
        assert result.is_complete is False
        assert result.completeness_ratio == 0.8
        assert result.recommendation == 'compute_with_flag'
        assert result.games_available == 8
        assert result.games_required == 10

    def test_check_player_windows_incomplete(self, validator, mock_completeness_checker):
        """Test incomplete windows return 'skip' recommendation."""
        # Mock 60% completeness (below 70% threshold)
        mock_completeness_checker.check_completeness_batch.return_value = {
            'player1': {
                'expected_count': 10,
                'actual_count': 6,
                'completeness_pct': 60.0,
                'is_complete': False,
                'dnp_count': 0,
                'gap_classification': 'DATA_GAP'
            }
        }

        results = validator.check_player_windows(
            player_id='player1',
            game_date=date(2026, 1, 26),
            window_sizes=[10]
        )

        result = results[10]
        assert result.is_complete is False
        assert result.completeness_ratio == 0.6
        assert result.recommendation == 'skip'  # Below threshold

    def test_check_player_windows_with_dnp(self, validator, mock_completeness_checker):
        """Test DNP games are correctly excluded from expected count."""
        # Mock completeness with DNP games
        mock_completeness_checker.check_completeness_batch.return_value = {
            'player1': {
                'expected_count': 10,
                'actual_count': 8,
                'completeness_pct': 100.0,  # 100% after DNP adjustment
                'is_complete': True,
                'dnp_count': 2,  # 2 DNP games
                'gap_classification': 'NO_GAP'
            }
        }

        results = validator.check_player_windows(
            player_id='player1',
            game_date=date(2026, 1, 26),
            window_sizes=[10]
        )

        result = results[10]
        assert result.is_complete is True
        assert result.completeness_ratio == 1.0
        assert result.recommendation == 'compute'
        assert result.dnp_count == 2
        assert result.games_required == 8  # 10 - 2 DNP

    def test_check_player_windows_no_data(self, validator, mock_completeness_checker):
        """Test player with no data returns skip."""
        # Mock empty results
        mock_completeness_checker.check_completeness_batch.return_value = {}

        results = validator.check_player_windows(
            player_id='player1',
            game_date=date(2026, 1, 26),
            window_sizes=[10]
        )

        result = results[10]
        assert result.is_complete is False
        assert result.completeness_ratio == 0.0
        assert result.recommendation == 'skip'
        assert result.games_available == 0

    def test_get_computable_players(self, validator, mock_completeness_checker):
        """Test partitioning players into computable vs skip."""
        # Mock mixed completeness
        mock_completeness_checker.check_completeness_batch.return_value = {
            'player1': {
                'expected_count': 10,
                'actual_count': 10,
                'completeness_pct': 100.0,
                'is_complete': True,
                'dnp_count': 0
            },
            'player2': {
                'expected_count': 10,
                'actual_count': 8,
                'completeness_pct': 80.0,
                'is_complete': False,
                'dnp_count': 0
            },
            'player3': {
                'expected_count': 10,
                'actual_count': 6,
                'completeness_pct': 60.0,
                'is_complete': False,
                'dnp_count': 0
            }
        }

        computable, skip = validator.get_computable_players(
            player_ids=['player1', 'player2', 'player3'],
            game_date=date(2026, 1, 26),
            window_size=10
        )

        assert len(computable) == 2  # player1 (100%) and player2 (80%)
        assert 'player1' in computable
        assert 'player2' in computable
        assert len(skip) == 1  # player3 (60% below threshold)
        assert 'player3' in skip

    def test_get_computable_players_error_handling(self, validator, mock_completeness_checker):
        """Test error handling in get_computable_players."""
        # Mock error
        mock_completeness_checker.check_completeness_batch.side_effect = \
            Exception("BigQuery error")

        computable, skip = validator.get_computable_players(
            player_ids=['player1', 'player2'],
            game_date=date(2026, 1, 26),
            window_size=10
        )

        # On error, all players should be skipped (safe default)
        assert len(computable) == 0
        assert len(skip) == 2

    def test_get_window_quality_summary(self, validator):
        """Test quality summary generation."""
        window_results = {
            5: WindowResult(
                is_complete=True,
                completeness_ratio=1.0,
                games_available=5,
                games_required=5,
                recommendation='compute',
                dnp_count=0
            ),
            10: WindowResult(
                is_complete=False,
                completeness_ratio=0.8,
                games_available=8,
                games_required=10,
                recommendation='compute_with_flag',
                dnp_count=1
            ),
            15: WindowResult(
                is_complete=False,
                completeness_ratio=0.6,
                games_available=9,
                games_required=15,
                recommendation='skip',
                dnp_count=2
            )
        }

        summary = validator.get_window_quality_summary(window_results)

        assert summary['min_completeness'] == 0.6
        assert summary['max_completeness'] == 1.0
        assert summary['avg_completeness'] == pytest.approx((1.0 + 0.8 + 0.6) / 3)
        assert summary['computable_windows'] == 2  # 5 and 10
        assert summary['total_windows'] == 3
        assert summary['all_complete'] is False
        assert summary['dnp_games'] == 3  # 0 + 1 + 2

    def test_get_window_quality_summary_empty(self, validator):
        """Test quality summary with no windows."""
        summary = validator.get_window_quality_summary({})

        assert summary['min_completeness'] == 0.0
        assert summary['max_completeness'] == 0.0
        assert summary['avg_completeness'] == 0.0
        assert summary['computable_windows'] == 0
        assert summary['total_windows'] == 0
        assert summary['all_complete'] is False

    def test_should_compute_window(self, validator, mock_completeness_checker):
        """Test quick check if window should be computed."""
        # Mock 80% completeness
        mock_completeness_checker.check_completeness_batch.return_value = {
            'player1': {
                'expected_count': 10,
                'actual_count': 8,
                'completeness_pct': 80.0,
                'is_complete': False,
                'dnp_count': 0,
                'gap_classification': 'DATA_GAP'
            }
        }

        should_compute, result = validator.should_compute_window(
            player_id='player1',
            game_date=date(2026, 1, 26),
            window_size=10
        )

        assert should_compute is True
        assert result.completeness_ratio == 0.8
        assert result.recommendation == 'compute_with_flag'

    def test_should_compute_window_skip(self, validator, mock_completeness_checker):
        """Test should_compute_window returns False for incomplete windows."""
        # Mock 60% completeness (below threshold)
        mock_completeness_checker.check_completeness_batch.return_value = {
            'player1': {
                'expected_count': 10,
                'actual_count': 6,
                'completeness_pct': 60.0,
                'is_complete': False,
                'dnp_count': 0,
                'gap_classification': 'DATA_GAP'
            }
        }

        should_compute, result = validator.should_compute_window(
            player_id='player1',
            game_date=date(2026, 1, 26),
            window_size=10
        )

        assert should_compute is False
        assert result.recommendation == 'skip'

    def test_threshold_boundary(self, validator, mock_completeness_checker):
        """Test threshold boundary at exactly 70%."""
        # Mock exactly 70% completeness
        mock_completeness_checker.check_completeness_batch.return_value = {
            'player1': {
                'expected_count': 10,
                'actual_count': 7,
                'completeness_pct': 70.0,
                'is_complete': False,
                'dnp_count': 0
            }
        }

        results = validator.check_player_windows(
            player_id='player1',
            game_date=date(2026, 1, 26),
            window_sizes=[10]
        )

        result = results[10]
        # At exactly threshold, should compute with flag
        assert result.recommendation in ['compute_with_flag', 'compute']


class TestWindowResult:
    """Test WindowResult dataclass."""

    def test_window_result_creation(self):
        """Test creating WindowResult."""
        result = WindowResult(
            is_complete=True,
            completeness_ratio=1.0,
            games_available=10,
            games_required=10,
            recommendation='compute',
            dnp_count=0,
            gap_classification='NO_GAP'
        )

        assert result.is_complete is True
        assert result.completeness_ratio == 1.0
        assert result.games_available == 10
        assert result.games_required == 10
        assert result.recommendation == 'compute'
        assert result.dnp_count == 0
        assert result.gap_classification == 'NO_GAP'

    def test_window_result_defaults(self):
        """Test WindowResult with default values."""
        result = WindowResult(
            is_complete=False,
            completeness_ratio=0.8,
            games_available=8,
            games_required=10,
            recommendation='compute_with_flag'
        )

        assert result.dnp_count == 0  # Default
        assert result.gap_classification == 'NO_GAP'  # Default
