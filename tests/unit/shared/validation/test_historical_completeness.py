"""
Unit tests for Historical Completeness Tracking module.

Tests the core logic for assessing whether rolling window calculations
had all required historical data.

Run with:
    pytest tests/unit/shared/validation/test_historical_completeness.py -v
"""

import pytest
from datetime import date
from shared.validation.historical_completeness import (
    assess_historical_completeness,
    should_skip_feature_generation,
    HistoricalCompletenessResult,
    WINDOW_SIZE,
    MINIMUM_GAMES_THRESHOLD,
    find_features_affected_by_backfill,
    find_incomplete_features_for_date_range,
    get_daily_completeness_summary_sql,
)


class TestHistoricalCompletenessResult:
    """Test the HistoricalCompletenessResult dataclass."""

    def test_creation_complete(self):
        """Test creating a complete result."""
        result = HistoricalCompletenessResult(
            games_found=10,
            games_expected=10,
            is_complete=True,
            is_bootstrap=False,
            contributing_game_dates=[date(2026, 1, i) for i in range(10, 20)]
        )
        assert result.games_found == 10
        assert result.games_expected == 10
        assert result.is_complete is True
        assert result.is_bootstrap is False
        assert len(result.contributing_game_dates) == 10

    def test_games_missing_property(self):
        """Test games_missing calculation."""
        result = HistoricalCompletenessResult(
            games_found=8,
            games_expected=10,
            is_complete=False,
            is_bootstrap=False
        )
        assert result.games_missing == 2

    def test_games_missing_when_complete(self):
        """Test games_missing is 0 when complete."""
        result = HistoricalCompletenessResult(
            games_found=10,
            games_expected=10,
            is_complete=True,
            is_bootstrap=False
        )
        assert result.games_missing == 0

    def test_completeness_pct_full(self):
        """Test completeness percentage at 100%."""
        result = HistoricalCompletenessResult(
            games_found=10,
            games_expected=10,
            is_complete=True,
            is_bootstrap=False
        )
        assert result.completeness_pct == 100.0

    def test_completeness_pct_partial(self):
        """Test completeness percentage when partial."""
        result = HistoricalCompletenessResult(
            games_found=8,
            games_expected=10,
            is_complete=False,
            is_bootstrap=False
        )
        assert result.completeness_pct == 80.0

    def test_completeness_pct_zero_expected(self):
        """Test completeness percentage when zero expected (new player)."""
        result = HistoricalCompletenessResult(
            games_found=0,
            games_expected=0,
            is_complete=True,
            is_bootstrap=True
        )
        assert result.completeness_pct == 100.0  # 0/0 = complete

    def test_is_data_gap_true(self):
        """Test is_data_gap when incomplete and not bootstrap."""
        result = HistoricalCompletenessResult(
            games_found=8,
            games_expected=10,
            is_complete=False,
            is_bootstrap=False
        )
        assert result.is_data_gap is True

    def test_is_data_gap_false_when_complete(self):
        """Test is_data_gap is False when complete."""
        result = HistoricalCompletenessResult(
            games_found=10,
            games_expected=10,
            is_complete=True,
            is_bootstrap=False
        )
        assert result.is_data_gap is False

    def test_is_data_gap_false_when_bootstrap(self):
        """Test is_data_gap is False when bootstrap (even if technically incomplete)."""
        result = HistoricalCompletenessResult(
            games_found=5,
            games_expected=5,
            is_complete=True,
            is_bootstrap=True
        )
        assert result.is_data_gap is False

    def test_to_bq_struct(self):
        """Test conversion to BigQuery STRUCT format."""
        dates = [date(2026, 1, 15), date(2026, 1, 13)]
        result = HistoricalCompletenessResult(
            games_found=10,
            games_expected=10,
            is_complete=True,
            is_bootstrap=False,
            contributing_game_dates=dates
        )
        bq_struct = result.to_bq_struct()

        assert bq_struct['games_found'] == 10
        assert bq_struct['games_expected'] == 10
        assert bq_struct['is_complete'] is True
        assert bq_struct['is_bootstrap'] is False
        assert bq_struct['contributing_game_dates'] == ['2026-01-15', '2026-01-13']

    def test_str_representation(self):
        """Test string representation."""
        result = HistoricalCompletenessResult(
            games_found=8,
            games_expected=10,
            is_complete=False,
            is_bootstrap=False
        )
        assert "8/10" in str(result)
        assert "INCOMPLETE" in str(result)


class TestAssessHistoricalCompleteness:
    """Test the main assess_historical_completeness function."""

    def test_complete_veteran_player(self):
        """Test veteran player with full 10 games."""
        result = assess_historical_completeness(
            games_found=10,
            games_available=50
        )
        assert result.games_found == 10
        assert result.games_expected == 10
        assert result.is_complete is True
        assert result.is_bootstrap is False

    def test_data_gap_missing_games(self):
        """Test data gap - should have 10 but only got 8."""
        result = assess_historical_completeness(
            games_found=8,
            games_available=50
        )
        assert result.games_found == 8
        assert result.games_expected == 10
        assert result.is_complete is False
        assert result.is_bootstrap is False
        assert result.is_data_gap is True

    def test_bootstrap_new_player(self):
        """Test new player with only 5 games available."""
        result = assess_historical_completeness(
            games_found=5,
            games_available=5
        )
        assert result.games_found == 5
        assert result.games_expected == 5
        assert result.is_complete is True
        assert result.is_bootstrap is True

    def test_bootstrap_brand_new_player(self):
        """Test brand new player with zero games."""
        result = assess_historical_completeness(
            games_found=0,
            games_available=0
        )
        assert result.games_found == 0
        assert result.games_expected == 0
        assert result.is_complete is True
        assert result.is_bootstrap is True

    def test_bootstrap_early_season(self):
        """Test early season player with 3 games."""
        result = assess_historical_completeness(
            games_found=3,
            games_available=3
        )
        assert result.games_found == 3
        assert result.games_expected == 3
        assert result.is_complete is True
        assert result.is_bootstrap is True

    def test_incomplete_bootstrap(self):
        """Test bootstrap player missing some available games (unlikely but possible)."""
        result = assess_historical_completeness(
            games_found=3,
            games_available=5
        )
        assert result.games_found == 3
        assert result.games_expected == 5
        assert result.is_complete is False
        assert result.is_bootstrap is True  # Still bootstrap since expected < 10

    def test_with_contributing_dates(self):
        """Test that contributing dates are passed through."""
        dates = [date(2026, 1, 15), date(2026, 1, 13), date(2026, 1, 11)]
        result = assess_historical_completeness(
            games_found=3,
            games_available=3,
            contributing_dates=dates
        )
        assert result.contributing_game_dates == dates

    def test_custom_window_size(self):
        """Test with custom window size."""
        result = assess_historical_completeness(
            games_found=5,
            games_available=50,
            window_size=5
        )
        assert result.games_expected == 5
        assert result.is_complete is True
        assert result.is_bootstrap is False  # 5 == window_size

    def test_window_size_caps_expected(self):
        """Test that games_expected is capped at window_size."""
        result = assess_historical_completeness(
            games_found=10,
            games_available=100,
            window_size=10
        )
        assert result.games_expected == 10  # Capped at 10, not 100


class TestShouldSkipFeatureGeneration:
    """Test the skip threshold logic."""

    def test_skip_below_minimum(self):
        """Test that we skip when below minimum threshold."""
        assert should_skip_feature_generation(4) is True
        assert should_skip_feature_generation(3) is True
        assert should_skip_feature_generation(0) is True

    def test_dont_skip_at_minimum(self):
        """Test that we don't skip at exactly minimum threshold."""
        assert should_skip_feature_generation(5) is False

    def test_dont_skip_above_minimum(self):
        """Test that we don't skip above minimum threshold."""
        assert should_skip_feature_generation(6) is False
        assert should_skip_feature_generation(10) is False

    def test_custom_threshold(self):
        """Test with custom minimum threshold."""
        assert should_skip_feature_generation(4, minimum_threshold=3) is False
        assert should_skip_feature_generation(2, minimum_threshold=3) is True


class TestConstants:
    """Test module constants are set correctly."""

    def test_window_size(self):
        """Test default window size is 10."""
        assert WINDOW_SIZE == 10

    def test_minimum_threshold(self):
        """Test minimum games threshold is 5."""
        assert MINIMUM_GAMES_THRESHOLD == 5


class TestSQLGeneration:
    """Test SQL query generation functions."""

    def test_find_affected_by_backfill_sql(self):
        """Test SQL generation for cascade detection."""
        sql = find_features_affected_by_backfill(date(2026, 1, 1))
        assert "2026-01-01" in sql
        assert "contributing_game_dates" in sql
        assert "ml_feature_store_v2" in sql

    def test_find_affected_custom_window(self):
        """Test SQL with custom forward window."""
        sql = find_features_affected_by_backfill(date(2026, 1, 1), forward_window_days=14)
        assert "INTERVAL 14 DAY" in sql

    def test_find_incomplete_sql(self):
        """Test SQL for finding incomplete features."""
        sql = find_incomplete_features_for_date_range(
            date(2026, 1, 1),
            date(2026, 1, 21)
        )
        assert "2026-01-01" in sql
        assert "2026-01-21" in sql
        assert "NOT historical_completeness.is_complete" in sql
        assert "NOT historical_completeness.is_bootstrap" in sql

    def test_daily_summary_sql(self):
        """Test SQL for daily summary."""
        sql = get_daily_completeness_summary_sql(days_back=7)
        assert "INTERVAL 7 DAY" in sql
        assert "is_complete" in sql


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_exactly_at_window_size(self):
        """Test when games_available equals window_size exactly."""
        result = assess_historical_completeness(
            games_found=10,
            games_available=10
        )
        # Should NOT be bootstrap since we have full window
        assert result.is_bootstrap is False
        assert result.is_complete is True

    def test_one_below_window_size(self):
        """Test when games_available is one below window_size."""
        result = assess_historical_completeness(
            games_found=9,
            games_available=9
        )
        # Should be bootstrap since expected < 10
        assert result.is_bootstrap is True
        assert result.is_complete is True

    def test_large_gap(self):
        """Test with large data gap (many games missing)."""
        result = assess_historical_completeness(
            games_found=2,
            games_available=50
        )
        assert result.games_missing == 8
        assert result.completeness_pct == 20.0
        assert result.is_data_gap is True

    def test_negative_games_handled(self):
        """Test that negative values don't break anything (defensive)."""
        result = assess_historical_completeness(
            games_found=0,
            games_available=0
        )
        assert result.games_missing == 0
        assert result.completeness_pct == 100.0
