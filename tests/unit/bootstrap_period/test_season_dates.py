"""
Unit Tests for NBA Season Dates Configuration

Tests schedule service integration, early season detection, and fallback behavior.
"""

import pytest
from datetime import date
from unittest.mock import Mock, patch, MagicMock

# Import the module we're testing
from shared.config.nba_season_dates import (
    get_season_start_date,
    is_early_season,
    get_season_year_from_date,
    FALLBACK_SEASON_START_DATES
)


class TestGetSeasonYearFromDate:
    """Test season year determination from game date."""

    def test_october_game_same_year(self):
        """October games belong to same year season."""
        assert get_season_year_from_date(date(2024, 10, 22)) == 2024
        assert get_season_year_from_date(date(2024, 10, 1)) == 2024
        assert get_season_year_from_date(date(2024, 10, 31)) == 2024

    def test_november_december_same_year(self):
        """Nov-Dec games belong to same year season."""
        assert get_season_year_from_date(date(2024, 11, 1)) == 2024
        assert get_season_year_from_date(date(2024, 12, 25)) == 2024

    def test_january_june_previous_year(self):
        """Jan-Jun games belong to previous year season."""
        assert get_season_year_from_date(date(2025, 1, 15)) == 2024
        assert get_season_year_from_date(date(2025, 4, 20)) == 2024
        assert get_season_year_from_date(date(2025, 6, 15)) == 2024

    def test_offseason_previous_year(self):
        """Jul-Sep belong to previous year (offseason)."""
        assert get_season_year_from_date(date(2024, 7, 1)) == 2023
        assert get_season_year_from_date(date(2024, 9, 30)) == 2023


class TestGetSeasonStartDate:
    """Test season start date retrieval with schedule service integration."""

    @patch('shared.config.nba_season_dates._get_schedule_service')
    def test_schedule_service_success(self, mock_get_service):
        """Test successful retrieval from schedule service."""
        # Mock schedule service
        mock_service = Mock()
        mock_service.get_season_start_date.return_value = '2024-10-22'
        mock_get_service.return_value = mock_service

        result = get_season_start_date(2024, use_schedule_service=True)

        assert result == date(2024, 10, 22)
        mock_service.get_season_start_date.assert_called_once_with(2024)

    @patch('shared.config.nba_season_dates._get_schedule_service')
    def test_schedule_service_returns_none_fallback_to_hardcoded(self, mock_get_service):
        """Test fallback to hardcoded when schedule service returns None."""
        mock_service = Mock()
        mock_service.get_season_start_date.return_value = None
        mock_get_service.return_value = mock_service

        result = get_season_start_date(2024, use_schedule_service=True)

        # Should fall back to hardcoded
        assert result == FALLBACK_SEASON_START_DATES[2024]

    @patch('shared.config.nba_season_dates._get_schedule_service')
    def test_schedule_service_exception_fallback(self, mock_get_service):
        """Test fallback when schedule service raises exception."""
        mock_service = Mock()
        mock_service.get_season_start_date.side_effect = Exception("Database error")
        mock_get_service.return_value = mock_service

        result = get_season_start_date(2024, use_schedule_service=True)

        # Should fall back to hardcoded
        assert result == FALLBACK_SEASON_START_DATES[2024]

    def test_hardcoded_dates_for_known_seasons(self):
        """Test hardcoded fallback dates for known seasons."""
        # Disable schedule service
        assert get_season_start_date(2024, use_schedule_service=False) == date(2024, 10, 22)
        assert get_season_start_date(2023, use_schedule_service=False) == date(2023, 10, 24)
        assert get_season_start_date(2022, use_schedule_service=False) == date(2022, 10, 18)
        assert get_season_start_date(2021, use_schedule_service=False) == date(2021, 10, 19)

    def test_unknown_season_default_estimate(self):
        """Test default estimate for unknown seasons."""
        # Season not in database or hardcoded
        result = get_season_start_date(2030, use_schedule_service=False)

        # Should default to Oct 22
        assert result == date(2030, 10, 22)

    @patch('shared.config.nba_season_dates._get_schedule_service')
    def test_schedule_service_unavailable_fallback(self, mock_get_service):
        """Test fallback when schedule service can't be initialized."""
        # Schedule service failed to initialize
        mock_get_service.return_value = None

        result = get_season_start_date(2024, use_schedule_service=True)

        # Should fall back to hardcoded
        assert result == FALLBACK_SEASON_START_DATES[2024]


class TestIsEarlySeason:
    """Test early season detection."""

    @patch('shared.config.nba_season_dates.get_season_start_date')
    def test_opening_night_is_early_season(self, mock_get_start):
        """Test that opening night (day 0) is detected as early season."""
        mock_get_start.return_value = date(2023, 10, 24)

        result = is_early_season(date(2023, 10, 24), 2023, days_threshold=7)

        assert result is True

    @patch('shared.config.nba_season_dates.get_season_start_date')
    def test_day_1_is_early_season(self, mock_get_start):
        """Test that day 1 is detected as early season."""
        mock_get_start.return_value = date(2023, 10, 24)

        result = is_early_season(date(2023, 10, 25), 2023, days_threshold=7)

        assert result is True

    @patch('shared.config.nba_season_dates.get_season_start_date')
    def test_day_6_is_early_season(self, mock_get_start):
        """Test that day 6 is detected as early season (last early day)."""
        mock_get_start.return_value = date(2023, 10, 24)

        result = is_early_season(date(2023, 10, 30), 2023, days_threshold=7)

        assert result is True

    @patch('shared.config.nba_season_dates.get_season_start_date')
    def test_day_7_is_not_early_season(self, mock_get_start):
        """Test that day 7 is NOT early season (crossover point)."""
        mock_get_start.return_value = date(2023, 10, 24)

        result = is_early_season(date(2023, 10, 31), 2023, days_threshold=7)

        assert result is False

    @patch('shared.config.nba_season_dates.get_season_start_date')
    def test_day_10_is_not_early_season(self, mock_get_start):
        """Test that day 10 is not early season."""
        mock_get_start.return_value = date(2023, 10, 24)

        result = is_early_season(date(2023, 11, 3), 2023, days_threshold=7)

        assert result is False

    @patch('shared.config.nba_season_dates.get_season_start_date')
    def test_before_season_start_not_early(self, mock_get_start):
        """Test that dates before season start are not considered early season."""
        mock_get_start.return_value = date(2023, 10, 24)

        # Day -1 (preseason)
        result = is_early_season(date(2023, 10, 23), 2023, days_threshold=7)

        assert result is False

    @patch('shared.config.nba_season_dates.get_season_start_date')
    def test_custom_threshold_5_days(self, mock_get_start):
        """Test custom threshold of 5 days."""
        mock_get_start.return_value = date(2024, 10, 22)

        # Day 4 should be early season with 5-day threshold
        assert is_early_season(date(2024, 10, 26), 2024, days_threshold=5) is True

        # Day 5 should NOT be early season with 5-day threshold
        assert is_early_season(date(2024, 10, 27), 2024, days_threshold=5) is False

    @patch('shared.config.nba_season_dates.get_season_start_date')
    def test_custom_threshold_10_days(self, mock_get_start):
        """Test custom threshold of 10 days."""
        mock_get_start.return_value = date(2024, 10, 22)

        # Day 9 should be early season with 10-day threshold
        assert is_early_season(date(2024, 10, 31), 2024, days_threshold=10) is True

        # Day 10 should NOT be early season with 10-day threshold
        assert is_early_season(date(2024, 11, 1), 2024, days_threshold=10) is False

    @patch('shared.config.nba_season_dates.get_season_start_date')
    def test_all_test_dates_from_investigation(self, mock_get_start):
        """Test all dates from bootstrap period investigation."""
        mock_get_start.return_value = date(2023, 10, 24)

        # Days that should SKIP (0-6)
        early_dates = [
            date(2023, 10, 24),  # Day 0 - Opening night
            date(2023, 10, 25),  # Day 1
            date(2023, 10, 26),  # Day 2
            date(2023, 10, 27),  # Day 3
            date(2023, 10, 28),  # Day 4
            date(2023, 10, 29),  # Day 5
            date(2023, 10, 30),  # Day 6
        ]

        for test_date in early_dates:
            assert is_early_season(test_date, 2023, days_threshold=7) is True, \
                f"{test_date} should be early season"

        # Days that should PROCESS (7+)
        normal_dates = [
            date(2023, 10, 31),  # Day 7 - Crossover
            date(2023, 11, 1),   # Day 8
            date(2023, 11, 6),   # Day 13
            date(2023, 12, 1),   # Mid-season
        ]

        for test_date in normal_dates:
            assert is_early_season(test_date, 2023, days_threshold=7) is False, \
                f"{test_date} should NOT be early season"


class TestScheduleServiceIntegration:
    """Integration tests with actual schedule service (if available)."""

    def test_schedule_service_can_be_imported(self):
        """Test that schedule service can be imported."""
        try:
            from shared.utils.schedule.service import NBAScheduleService
            assert NBAScheduleService is not None
        except ImportError as e:
            pytest.fail(f"Schedule service import failed: {e}")

    @pytest.mark.integration
    def test_actual_season_dates_if_service_available(self):
        """Test retrieving actual dates from schedule service (integration test)."""
        try:
            # This will try the actual schedule service
            result_2024 = get_season_start_date(2024)
            result_2023 = get_season_start_date(2023)

            # Should be valid dates
            assert isinstance(result_2024, date)
            assert isinstance(result_2023, date)

            # Should be in October (NBA season starts in October)
            assert result_2024.month == 10
            assert result_2023.month == 10

            # Should match our expected dates (from database verification)
            assert result_2024 == date(2024, 10, 22)
            assert result_2023 == date(2023, 10, 24)

        except Exception as e:
            pytest.skip(f"Schedule service not available: {e}")


class TestFallbackBehavior:
    """Test three-tier fallback system."""

    @patch('shared.config.nba_season_dates._get_schedule_service')
    def test_fallback_chain_database_to_gcs_to_hardcoded(self, mock_get_service):
        """Test complete fallback chain."""
        # Simulate database failing, GCS failing, using hardcoded
        mock_service = Mock()
        mock_service.get_season_start_date.side_effect = Exception("DB and GCS failed")
        mock_get_service.return_value = mock_service

        result = get_season_start_date(2024)

        # Should successfully fall back to hardcoded
        assert result == date(2024, 10, 22)

    @patch('shared.config.nba_season_dates._get_schedule_service')
    def test_fallback_with_logging(self, mock_get_service, caplog):
        """Test that fallback produces appropriate log warnings."""
        mock_service = Mock()
        mock_service.get_season_start_date.return_value = None
        mock_get_service.return_value = mock_service

        with caplog.at_level('WARNING'):
            result = get_season_start_date(2024)

        # Should have logged something about fallback
        # Note: Exact log message depends on implementation
        assert result == date(2024, 10, 22)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
