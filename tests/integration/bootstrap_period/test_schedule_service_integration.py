"""
Integration Tests for Schedule Service Season Date Retrieval

These tests require BigQuery access and actual schedule data.
Mark tests with @pytest.mark.integration to skip in CI/CD if needed.
"""

import pytest
from datetime import date

from shared.utils.schedule.service import NBAScheduleService
from shared.utils.schedule.database_reader import ScheduleDatabaseReader
from shared.config.nba_season_dates import get_season_start_date


@pytest.mark.integration
class TestScheduleDatabaseReader:
    """Test schedule database reader with actual database."""

    @pytest.fixture
    def db_reader(self):
        """Create database reader instance."""
        return ScheduleDatabaseReader(
            project_id='nba-props-platform',
            table_name='nba_reference.nba_schedule'
        )

    def test_get_season_start_date_2024(self, db_reader):
        """Test retrieving 2024 season start date from database."""
        result = db_reader.get_season_start_date(2024)

        # Should return a string in YYYY-MM-DD format
        assert result is not None, "Should find 2024 season in database"
        assert isinstance(result, str)
        assert result == '2024-10-22', "2024 season starts Oct 22"

    def test_get_season_start_date_2023(self, db_reader):
        """Test retrieving 2023 season start date from database."""
        result = db_reader.get_season_start_date(2023)

        assert result is not None
        assert result == '2023-10-24', "2023 season starts Oct 24"

    def test_get_season_start_date_2022(self, db_reader):
        """Test retrieving 2022 season start date from database."""
        result = db_reader.get_season_start_date(2022)

        assert result is not None
        assert result == '2022-10-18', "2022 season starts Oct 18"

    def test_get_season_start_date_2021_epoch(self, db_reader):
        """Test retrieving 2021 epoch season start date from database."""
        result = db_reader.get_season_start_date(2021)

        assert result is not None
        assert result == '2021-10-19', "2021 season (epoch) starts Oct 19"

    def test_get_season_start_date_future_season(self, db_reader):
        """Test that future season returns None (not in database yet)."""
        result = db_reader.get_season_start_date(2030)

        # Should return None since future season not in database
        assert result is None


@pytest.mark.integration
class TestScheduleService:
    """Test schedule service with actual database and GCS."""

    @pytest.fixture
    def schedule_service(self):
        """Create schedule service instance."""
        return NBAScheduleService(
            bucket_name='nba-scraped-data',
            use_database=True
        )

    def test_get_season_start_date_2024(self, schedule_service):
        """Test retrieving 2024 season start via schedule service."""
        result = schedule_service.get_season_start_date(2024)

        assert result is not None
        assert result == '2024-10-22'

    def test_get_season_start_date_2023(self, schedule_service):
        """Test retrieving 2023 season start via schedule service."""
        result = schedule_service.get_season_start_date(2023)

        assert result is not None
        assert result == '2023-10-24'

    def test_season_dates_match_database(self, schedule_service, db_reader):
        """Test that service and database return same dates."""
        for season in [2021, 2022, 2023, 2024]:
            service_result = schedule_service.get_season_start_date(season)
            db_result = db_reader.get_season_start_date(season)

            assert service_result == db_result, \
                f"Service and database should match for season {season}"


@pytest.mark.integration
class TestSeasonDatesConfigIntegration:
    """Test nba_season_dates config with actual schedule service."""

    def test_get_season_start_date_uses_schedule_service(self):
        """Test that config correctly uses schedule service."""
        # This will actually query the schedule service
        result_2024 = get_season_start_date(2024)
        result_2023 = get_season_start_date(2023)

        # Should get accurate dates from database
        assert result_2024 == date(2024, 10, 22)
        assert result_2023 == date(2023, 10, 24)

    def test_fallback_still_works_when_service_disabled(self):
        """Test that fallback works when schedule service disabled."""
        # Disable schedule service
        result = get_season_start_date(2024, use_schedule_service=False)

        # Should still get correct date from hardcoded fallback
        assert result == date(2024, 10, 22)

    def test_all_known_seasons_retrievable(self):
        """Test that all known seasons can be retrieved."""
        known_seasons = {
            2024: date(2024, 10, 22),
            2023: date(2023, 10, 24),
            2022: date(2022, 10, 18),
            2021: date(2021, 10, 19),
        }

        for season_year, expected_date in known_seasons.items():
            result = get_season_start_date(season_year)
            assert result == expected_date, \
                f"Season {season_year} should start on {expected_date}"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-m', 'integration'])
