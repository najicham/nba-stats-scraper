"""
Unit tests for CompletenessChecker service.

Tests completeness calculation logic without requiring BigQuery connection.
"""

import pytest
from datetime import date, datetime, timezone, timedelta
from unittest.mock import Mock, MagicMock
import pandas as pd

from shared.utils.completeness_checker import CompletenessChecker


class TestCompletenessChecker:
    """Test CompletenessChecker service."""

    @pytest.fixture
    def mock_bq_client(self):
        """Mock BigQuery client."""
        client = Mock()
        client.project = 'test-project'
        return client

    @pytest.fixture
    def checker(self, mock_bq_client):
        """Create CompletenessChecker with mock client."""
        return CompletenessChecker(mock_bq_client, 'test-project')

    # ================================================================
    # Bootstrap Mode Detection Tests
    # ================================================================

    def test_bootstrap_mode_day_0(self, checker):
        """Day 0 of season should be bootstrap mode."""
        season_start = date(2024, 10, 22)
        analysis_date = date(2024, 10, 22)  # Same day

        assert checker.is_bootstrap_mode(analysis_date, season_start, bootstrap_days=30)

    def test_bootstrap_mode_day_29(self, checker):
        """Day 29 should still be bootstrap mode."""
        season_start = date(2024, 10, 22)
        analysis_date = date(2024, 11, 20)  # 29 days later

        assert checker.is_bootstrap_mode(analysis_date, season_start, bootstrap_days=30)

    def test_bootstrap_mode_day_30(self, checker):
        """Day 30 should NOT be bootstrap mode."""
        season_start = date(2024, 10, 22)
        analysis_date = date(2024, 11, 21)  # 30 days later

        assert not checker.is_bootstrap_mode(analysis_date, season_start, bootstrap_days=30)

    def test_bootstrap_mode_day_60(self, checker):
        """Day 60 should NOT be bootstrap mode."""
        season_start = date(2024, 10, 22)
        analysis_date = date(2024, 12, 21)  # 60 days later

        assert not checker.is_bootstrap_mode(analysis_date, season_start, bootstrap_days=30)

    def test_bootstrap_mode_custom_days(self, checker):
        """Test custom bootstrap days."""
        season_start = date(2024, 10, 22)
        analysis_date = date(2024, 11, 6)  # 15 days later

        # 15 days with 10-day bootstrap: NOT bootstrap
        assert not checker.is_bootstrap_mode(analysis_date, season_start, bootstrap_days=10)

        # 15 days with 20-day bootstrap: IS bootstrap
        assert checker.is_bootstrap_mode(analysis_date, season_start, bootstrap_days=20)

    # ================================================================
    # Season Boundary Detection Tests
    # ================================================================

    def test_season_boundary_october(self, checker):
        """October dates should be season boundary."""
        assert checker.is_season_boundary(date(2024, 10, 1))
        assert checker.is_season_boundary(date(2024, 10, 15))
        assert checker.is_season_boundary(date(2024, 10, 31))

    def test_season_boundary_november(self, checker):
        """November dates should be season boundary."""
        assert checker.is_season_boundary(date(2024, 11, 1))
        assert checker.is_season_boundary(date(2024, 11, 15))
        assert checker.is_season_boundary(date(2024, 11, 30))

    def test_season_boundary_april(self, checker):
        """April dates should be season boundary."""
        assert checker.is_season_boundary(date(2024, 4, 1))
        assert checker.is_season_boundary(date(2024, 4, 15))
        assert checker.is_season_boundary(date(2024, 4, 30))

    def test_not_season_boundary_december(self, checker):
        """December dates should NOT be season boundary."""
        assert not checker.is_season_boundary(date(2024, 12, 1))
        assert not checker.is_season_boundary(date(2024, 12, 25))

    def test_not_season_boundary_january(self, checker):
        """January dates should NOT be season boundary."""
        assert not checker.is_season_boundary(date(2024, 1, 15))

    def test_not_season_boundary_march(self, checker):
        """March dates should NOT be season boundary."""
        assert not checker.is_season_boundary(date(2024, 3, 15))

    # ================================================================
    # Backfill Progress Tests
    # ================================================================

    def test_backfill_progress_day_5(self, checker):
        """Day 5: Too early for alerts."""
        season_start = date(2024, 10, 22)
        analysis_date = date(2024, 10, 27)  # Day 5

        result = checker.calculate_backfill_progress(
            analysis_date, season_start, avg_completeness=20.0
        )

        assert result['days_since_start'] == 5
        assert result['avg_completeness'] == 20.0
        assert result['expected_threshold'] == 0.0
        assert result['alert_level'] == 'ok'

    def test_backfill_progress_day_10_on_track(self, checker):
        """Day 10: On track (30% expected, have 35%)."""
        season_start = date(2024, 10, 22)
        analysis_date = date(2024, 11, 1)  # Day 10

        result = checker.calculate_backfill_progress(
            analysis_date, season_start, avg_completeness=35.0
        )

        assert result['days_since_start'] == 10
        assert result['expected_threshold'] == 30.0
        assert result['alert_level'] == 'ok'  # 35% > 30%

    def test_backfill_progress_day_10_behind(self, checker):
        """Day 10: Behind schedule (30% expected, have 20%)."""
        season_start = date(2024, 10, 22)
        analysis_date = date(2024, 11, 1)  # Day 10

        result = checker.calculate_backfill_progress(
            analysis_date, season_start, avg_completeness=20.0
        )

        assert result['days_since_start'] == 10
        assert result['expected_threshold'] == 30.0
        assert result['alert_level'] == 'info'  # 20% < 30%

    def test_backfill_progress_day_20_on_track(self, checker):
        """Day 20: On track (80% expected, have 85%)."""
        season_start = date(2024, 10, 22)
        analysis_date = date(2024, 11, 11)  # Day 20

        result = checker.calculate_backfill_progress(
            analysis_date, season_start, avg_completeness=85.0
        )

        assert result['days_since_start'] == 20
        assert result['expected_threshold'] == 80.0
        assert result['alert_level'] == 'ok'  # 85% > 80%

    def test_backfill_progress_day_20_behind(self, checker):
        """Day 20: Behind schedule (80% expected, have 60%)."""
        season_start = date(2024, 10, 22)
        analysis_date = date(2024, 11, 11)  # Day 20

        result = checker.calculate_backfill_progress(
            analysis_date, season_start, avg_completeness=60.0
        )

        assert result['days_since_start'] == 20
        assert result['expected_threshold'] == 80.0
        assert result['alert_level'] == 'warning'  # 60% < 80%

    def test_backfill_progress_day_30_on_track(self, checker):
        """Day 30: On track (95% expected, have 98%)."""
        season_start = date(2024, 10, 22)
        analysis_date = date(2024, 11, 21)  # Day 30

        result = checker.calculate_backfill_progress(
            analysis_date, season_start, avg_completeness=98.0
        )

        assert result['days_since_start'] == 30
        assert result['expected_threshold'] == 95.0
        assert result['alert_level'] == 'ok'  # 98% > 95%

    def test_backfill_progress_day_30_behind(self, checker):
        """Day 30: Behind schedule (95% expected, have 70%)."""
        season_start = date(2024, 10, 22)
        analysis_date = date(2024, 11, 21)  # Day 30

        result = checker.calculate_backfill_progress(
            analysis_date, season_start, avg_completeness=70.0
        )

        assert result['days_since_start'] == 30
        assert result['expected_threshold'] == 95.0
        assert result['alert_level'] == 'critical'  # 70% < 95%

    def test_backfill_progress_day_40(self, checker):
        """Day 40: Still expect 95%."""
        season_start = date(2024, 10, 22)
        analysis_date = date(2024, 12, 1)  # Day 40

        result = checker.calculate_backfill_progress(
            analysis_date, season_start, avg_completeness=92.0
        )

        assert result['days_since_start'] == 40
        assert result['expected_threshold'] == 95.0
        assert result['alert_level'] == 'critical'  # 92% < 95%

    # ================================================================
    # Completeness Calculation Tests (With Mocked Queries)
    # ================================================================

    def test_completeness_batch_all_complete(self, checker, mock_bq_client):
        """Test completeness when all teams have complete data."""
        # Mock query results
        expected_df = pd.DataFrame({
            'entity_id': ['LAL', 'GSW', 'BOS'],
            'count': [17, 16, 18]
        })
        actual_df = pd.DataFrame({
            'entity_id': ['LAL', 'GSW', 'BOS'],
            'count': [17, 16, 18]
        })

        mock_query = Mock()
        mock_query.to_dataframe.side_effect = [expected_df, actual_df]
        mock_bq_client.query.return_value = mock_query

        results = checker.check_completeness_batch(
            entity_ids=['LAL', 'GSW', 'BOS'],
            entity_type='team',
            analysis_date=date(2024, 11, 22),
            upstream_table='nba_analytics.team_defense_game_summary',
            upstream_entity_field='defending_team_abbr',
            lookback_window=15,
            window_type='games',
            season_start_date=date(2024, 10, 22)
        )

        # Verify all teams complete
        assert results['LAL']['completeness_pct'] == 100.0
        assert results['LAL']['is_production_ready'] == True
        assert results['LAL']['missing_count'] == 0

        assert results['GSW']['completeness_pct'] == 100.0
        assert results['BOS']['completeness_pct'] == 100.0

    def test_completeness_batch_partial_data(self, checker, mock_bq_client):
        """Test completeness when some teams have incomplete data."""
        # Mock query results
        expected_df = pd.DataFrame({
            'entity_id': ['LAL', 'GSW', 'BOS'],
            'count': [15, 15, 15]
        })
        actual_df = pd.DataFrame({
            'entity_id': ['LAL', 'GSW', 'BOS'],
            'count': [15, 10, 5]  # LAL complete, GSW partial, BOS very partial
        })

        mock_query = Mock()
        mock_query.to_dataframe.side_effect = [expected_df, actual_df]
        mock_bq_client.query.return_value = mock_query

        results = checker.check_completeness_batch(
            entity_ids=['LAL', 'GSW', 'BOS'],
            entity_type='team',
            analysis_date=date(2024, 11, 22),
            upstream_table='nba_analytics.team_defense_game_summary',
            upstream_entity_field='defending_team_abbr',
            lookback_window=15,
            window_type='games',
            season_start_date=date(2024, 10, 22)
        )

        # LAL: Complete
        assert results['LAL']['completeness_pct'] == 100.0
        assert results['LAL']['is_production_ready'] == True
        assert results['LAL']['missing_count'] == 0

        # GSW: 10/15 = 66.7%
        assert results['GSW']['completeness_pct'] == 66.7
        assert results['GSW']['is_production_ready'] == False  # < 90%
        assert results['GSW']['missing_count'] == 5

        # BOS: 5/15 = 33.3%
        assert results['BOS']['completeness_pct'] == 33.3
        assert results['BOS']['is_production_ready'] == False
        assert results['BOS']['missing_count'] == 10

    def test_completeness_batch_missing_entity(self, checker, mock_bq_client):
        """Test completeness when entity completely missing from upstream."""
        # Mock query results
        expected_df = pd.DataFrame({
            'entity_id': ['LAL', 'GSW'],
            'count': [15, 15]
        })
        actual_df = pd.DataFrame({
            'entity_id': ['LAL'],  # GSW missing entirely
            'count': [15]
        })

        mock_query = Mock()
        mock_query.to_dataframe.side_effect = [expected_df, actual_df]
        mock_bq_client.query.return_value = mock_query

        results = checker.check_completeness_batch(
            entity_ids=['LAL', 'GSW'],
            entity_type='team',
            analysis_date=date(2024, 11, 22),
            upstream_table='nba_analytics.team_defense_game_summary',
            upstream_entity_field='defending_team_abbr',
            lookback_window=15,
            window_type='games',
            season_start_date=date(2024, 10, 22)
        )

        # LAL: Complete
        assert results['LAL']['completeness_pct'] == 100.0

        # GSW: 0/15 = 0%
        assert results['GSW']['completeness_pct'] == 0.0
        assert results['GSW']['is_production_ready'] == False
        assert results['GSW']['missing_count'] == 15


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
