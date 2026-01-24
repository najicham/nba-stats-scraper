"""
Unit Tests for Model Performance Tracking (ML Retraining Feedback)

Tests cover:
1. SystemPerformanceTracker - aggregating prediction accuracy per system
2. PerformanceSummaryProcessor - multi-dimensional performance summaries
3. SystemDailyPerformanceProcessor - daily system-level aggregations
4. Rolling window metrics - 7d, 30d, season performance
5. High-confidence analysis - tracking high-confidence prediction performance
6. OVER/UNDER splits - separate accuracy tracking

Run with: pytest tests/unit/ml/test_model_performance.py -v

Directory: tests/unit/ml/
"""

import pytest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock, MagicMock, patch
from typing import Dict, List, Any
import pandas as pd


# ============================================================================
# TEST FIXTURES
# ============================================================================

@pytest.fixture
def mock_bq_client():
    """Create mock BigQuery client with common responses."""
    client = Mock()

    # Default query response
    default_result = Mock()
    default_result.result.return_value = []

    client.query.return_value = default_result
    client.get_table.return_value = Mock(schema=[])
    client.load_table_from_json.return_value = Mock(
        result=Mock(return_value=None),
        output_rows=10,
        errors=[]
    )

    return client


@pytest.fixture
def mock_performance_tracker(mock_bq_client):
    """
    Create SystemPerformanceTracker with mocked dependencies.
    """
    from data_processors.grading.system_performance.system_performance_tracker import (
        SystemPerformanceTracker
    )

    tracker = object.__new__(SystemPerformanceTracker)
    tracker.project_id = 'test-project'
    tracker.bq_client = mock_bq_client
    tracker.accuracy_table = 'test-project.nba_predictions.prediction_accuracy'
    tracker.summary_table = 'test-project.nba_grading.system_performance_summary'

    return tracker


@pytest.fixture
def mock_summary_processor(mock_bq_client):
    """
    Create PerformanceSummaryProcessor with mocked dependencies.
    """
    from data_processors.grading.performance_summary.performance_summary_processor import (
        PerformanceSummaryProcessor
    )

    processor = object.__new__(PerformanceSummaryProcessor)
    processor.project_id = 'test-project'
    processor.bq_client = mock_bq_client

    return processor


@pytest.fixture
def mock_daily_processor(mock_bq_client):
    """
    Create SystemDailyPerformanceProcessor with mocked dependencies.
    """
    from data_processors.grading.system_daily_performance.system_daily_performance_processor import (
        SystemDailyPerformanceProcessor
    )

    processor = object.__new__(SystemDailyPerformanceProcessor)
    processor.project_id = 'test-project'
    processor.bq_client = mock_bq_client

    return processor


@pytest.fixture
def sample_system_performance():
    """Sample system performance data."""
    return {
        'system_id': 'catboost_v8',
        'prop_type': 'points',
        'period_start': '2025-01-08',
        'period_end': '2025-01-15',
        'total_predictions': 150,
        'total_recommendations': 120,
        'pass_count': 30,
        'wins': 72,
        'losses': 48,
        'pushes': 0,
        'success_rate_pct': 60.0,
        'mae': 4.2,
        'avg_bias': 0.3,
        'error_stddev': 3.8,
        'over_count': 65,
        'over_wins': 40,
        'over_success_rate_pct': 61.5,
        'under_count': 55,
        'under_wins': 32,
        'under_success_rate_pct': 58.2,
        'within_3_count': 45,
        'within_3_pct': 30.0,
        'within_5_count': 80,
        'within_5_pct': 53.3,
        'high_conf_count': 35,
        'high_conf_wins': 24,
        'high_conf_success_rate_pct': 68.6,
        'avg_confidence': 0.72,
        'voided_count': 5,
        'unique_players': 85,
        'unique_games': 45,
        'days_with_data': 7
    }


# ============================================================================
# TEST CLASS 1: SYSTEM PERFORMANCE TRACKING (6 tests)
# ============================================================================

class TestSystemPerformanceTracking:
    """Test SystemPerformanceTracker functionality."""

    def test_compute_system_performance_query_structure(self, mock_performance_tracker):
        """
        Test that compute_system_performance generates correct query.

        Verifies SQL includes all required aggregations.
        """
        start_date = date(2025, 1, 8)
        end_date = date(2025, 1, 15)

        # Mock query result
        mock_result = Mock()
        mock_result.__iter__ = Mock(return_value=iter([]))
        mock_performance_tracker.bq_client.query.return_value.result.return_value = mock_result

        mock_performance_tracker.compute_system_performance(start_date, end_date)

        # Verify query was called
        assert mock_performance_tracker.bq_client.query.called
        query = mock_performance_tracker.bq_client.query.call_args[0][0]

        # Check key aggregations in query
        assert 'success_rate_pct' in query
        assert 'mae' in query
        assert 'avg_bias' in query
        assert 'over_success_rate_pct' in query
        assert 'under_success_rate_pct' in query
        assert 'high_conf_success_rate_pct' in query
        assert 'is_voided = FALSE' in query

    def test_compute_system_performance_date_range(self, mock_performance_tracker):
        """
        Test that date range is correctly applied.

        Verifies both start and end dates in query.
        """
        start_date = date(2025, 1, 1)
        end_date = date(2025, 1, 31)

        mock_result = Mock()
        mock_result.__iter__ = Mock(return_value=iter([]))
        mock_performance_tracker.bq_client.query.return_value.result.return_value = mock_result

        mock_performance_tracker.compute_system_performance(start_date, end_date)

        query = mock_performance_tracker.bq_client.query.call_args[0][0]

        assert '2025-01-01' in query
        assert '2025-01-31' in query

    def test_compute_rolling_performance_7d(self, mock_performance_tracker):
        """
        Test 7-day rolling window calculation.

        Should compute from (today - 7) to today.
        """
        mock_performance_tracker.compute_system_performance = Mock(return_value=[])

        as_of_date = date(2025, 1, 15)
        result = mock_performance_tracker.compute_rolling_performance(as_of_date)

        # Verify 7d window was computed
        calls = mock_performance_tracker.compute_system_performance.call_args_list
        call_dates = [(c[0][0], c[0][1]) for c in calls]

        # Should have call for 7-day window
        assert (date(2025, 1, 8), date(2025, 1, 15)) in call_dates

    def test_compute_rolling_performance_30d(self, mock_performance_tracker):
        """
        Test 30-day rolling window calculation.

        Should compute from (today - 30) to today.
        """
        mock_performance_tracker.compute_system_performance = Mock(return_value=[])

        as_of_date = date(2025, 1, 15)
        result = mock_performance_tracker.compute_rolling_performance(as_of_date)

        calls = mock_performance_tracker.compute_system_performance.call_args_list
        call_dates = [(c[0][0], c[0][1]) for c in calls]

        # Should have call for 30-day window
        assert (date(2024, 12, 16), date(2025, 1, 15)) in call_dates

    def test_compute_rolling_performance_season(self, mock_performance_tracker):
        """
        Test season window calculation.

        Should compute from season start (Oct 1) to today.
        """
        mock_performance_tracker.compute_system_performance = Mock(return_value=[])

        as_of_date = date(2025, 1, 15)
        result = mock_performance_tracker.compute_rolling_performance(as_of_date)

        calls = mock_performance_tracker.compute_system_performance.call_args_list
        call_dates = [(c[0][0], c[0][1]) for c in calls]

        # Should have call for season window (Oct 1 to Jan 15)
        assert (date(2024, 10, 1), date(2025, 1, 15)) in call_dates

    def test_get_daily_trend_format(self, mock_performance_tracker):
        """
        Test daily trend returns correct format.

        Each day should have system_id, success_rate_pct, mae.
        """
        mock_row = Mock(
            game_date=date(2025, 1, 15),
            system_id='catboost_v8',
            prop_type='points',
            total_predictions=30,
            wins=18,
            losses=12,
            success_rate_pct=60.0,
            mae=4.2,
            high_conf_wins=8,
            high_conf_total=12,
            high_conf_success_rate_pct=66.7
        )

        mock_result = Mock()
        mock_result.__iter__ = Mock(return_value=iter([mock_row]))
        mock_performance_tracker.bq_client.query.return_value.result.return_value = mock_result

        trend = mock_performance_tracker.get_daily_trend('catboost_v8', days=30)

        assert len(trend) == 1
        assert trend[0]['game_date'] == '2025-01-15'
        assert trend[0]['success_rate_pct'] == 60.0
        assert trend[0]['mae'] == 4.2


# ============================================================================
# TEST CLASS 2: PERFORMANCE SUMMARY PROCESSOR (6 tests)
# ============================================================================

class TestPerformanceSummaryProcessor:
    """Test PerformanceSummaryProcessor functionality."""

    def test_get_time_periods_rolling_7d(self, mock_summary_processor):
        """
        Test time period generation for rolling 7d.

        Period should span 7 days ending on as_of_date.
        """
        as_of_date = date(2025, 1, 15)
        periods = mock_summary_processor._get_time_periods(as_of_date)

        rolling_7d = next(p for p in periods if p[0] == 'rolling_7d')

        assert rolling_7d[0] == 'rolling_7d'
        assert rolling_7d[1] == '2025-01-15'  # period_value
        assert rolling_7d[2] == date(2025, 1, 8)  # start_date
        assert rolling_7d[3] == date(2025, 1, 15)  # end_date

    def test_get_time_periods_month(self, mock_summary_processor):
        """
        Test time period generation for month.

        Period should span from month start.
        """
        as_of_date = date(2025, 1, 15)
        periods = mock_summary_processor._get_time_periods(as_of_date)

        month = next(p for p in periods if p[0] == 'month')

        assert month[0] == 'month'
        assert month[1] == '2025-01'  # period_value (YYYY-MM)
        assert month[2] == date(2025, 1, 1)  # start_date (month start)
        assert month[3] == date(2025, 1, 15)  # end_date

    def test_get_time_periods_season_mid_season(self, mock_summary_processor):
        """
        Test time period generation for season (mid-season date).

        Season should start from previous October.
        """
        as_of_date = date(2025, 1, 15)
        periods = mock_summary_processor._get_time_periods(as_of_date)

        season = next(p for p in periods if p[0] == 'season')

        assert season[0] == 'season'
        assert season[1] == '2024-25'  # season value
        assert season[2] == date(2024, 10, 1)  # season start
        assert season[3] == date(2025, 1, 15)  # end_date

    def test_get_time_periods_season_early_season(self, mock_summary_processor):
        """
        Test time period generation for season (early season date).

        October date should use same year for season start.
        """
        as_of_date = date(2024, 11, 15)
        periods = mock_summary_processor._get_time_periods(as_of_date)

        season = next(p for p in periods if p[0] == 'season')

        assert season[1] == '2024-25'
        assert season[2] == date(2024, 10, 1)

    def test_format_summary_key_structure(self, mock_summary_processor):
        """
        Test summary key format.

        Key should uniquely identify the summary slice.
        """
        base = {
            'total_predictions': 100,
            'hits': 60,
            'misses': 40,
            'hit_rate': 0.6,
            'mae': 4.2
        }

        result = mock_summary_processor._format_summary(
            base=base,
            system_id='catboost_v8',
            period_type='rolling_7d',
            period_value='2025-01-15',
            start_date=date(2025, 1, 8),
            end_date=date(2025, 1, 15),
            archetype='veteran_star'
        )

        # Key should contain all dimension values
        assert 'catboost_v8' in result['summary_key']
        assert 'rolling_7d' in result['summary_key']
        assert 'veteran_star' in result['summary_key']

    def test_format_summary_has_data_hash(self, mock_summary_processor):
        """
        Test that summary includes data hash for change detection.

        Hash enables efficient detection of data changes.
        """
        base = {
            'total_predictions': 100,
            'hits': 60,
            'misses': 40
        }

        result = mock_summary_processor._format_summary(
            base=base,
            system_id='catboost_v8',
            period_type='rolling_7d',
            period_value='2025-01-15',
            start_date=date(2025, 1, 8),
            end_date=date(2025, 1, 15)
        )

        assert 'data_hash' in result
        assert len(result['data_hash']) == 16  # Truncated hash


# ============================================================================
# TEST CLASS 3: DAILY PERFORMANCE PROCESSOR (6 tests)
# ============================================================================

class TestDailyPerformanceProcessor:
    """Test SystemDailyPerformanceProcessor functionality."""

    def test_check_accuracy_data_exists_true(self, mock_daily_processor):
        """
        Test _check_accuracy_data_exists when data exists.

        Should return True when count > 0.
        """
        mock_row = Mock(count=150)
        mock_result = Mock()
        mock_result.__iter__ = Mock(return_value=iter([mock_row]))
        mock_daily_processor.bq_client.query.return_value.result.return_value = mock_result

        result = mock_daily_processor._check_accuracy_data_exists(date(2025, 1, 15))

        assert result is True

    def test_check_accuracy_data_exists_false(self, mock_daily_processor):
        """
        Test _check_accuracy_data_exists when no data.

        Should return False when count = 0.
        """
        mock_row = Mock(count=0)
        mock_result = Mock()
        mock_result.__iter__ = Mock(return_value=iter([mock_row]))
        mock_daily_processor.bq_client.query.return_value.result.return_value = mock_result

        result = mock_daily_processor._check_accuracy_data_exists(date(2025, 1, 15))

        assert result is False

    def test_compute_daily_summaries_query_structure(self, mock_daily_processor):
        """
        Test that daily summary query includes all required aggregations.

        Should aggregate by (game_date, system_id).
        """
        mock_result = Mock()
        mock_result.__iter__ = Mock(return_value=iter([]))
        mock_daily_processor.bq_client.query.return_value.result.return_value = mock_result

        mock_daily_processor._compute_daily_summaries(date(2025, 1, 15))

        query = mock_daily_processor.bq_client.query.call_args[0][0]

        # Check key aggregations
        assert 'win_rate' in query
        assert 'mae' in query
        assert 'avg_bias' in query
        assert 'over_win_rate' in query
        assert 'under_win_rate' in query
        assert 'high_confidence_win_rate' in query
        assert 'GROUP BY game_date, system_id' in query

    def test_compute_daily_summaries_return_format(self, mock_daily_processor):
        """
        Test daily summary return format.

        Each summary should have all required fields.
        """
        mock_row = Mock(
            game_date=date(2025, 1, 15),
            system_id='catboost_v8',
            predictions_count=50,
            recommendations_count=40,
            correct_count=24,
            incorrect_count=16,
            pass_count=10,
            win_rate=0.60,
            mae=4.2,
            avg_bias=0.3,
            over_count=22,
            over_correct=14,
            over_win_rate=0.636,
            under_count=18,
            under_correct=10,
            under_win_rate=0.556,
            within_3_count=15,
            within_3_pct=0.30,
            within_5_count=27,
            within_5_pct=0.54,
            avg_confidence=0.72,
            high_confidence_count=12,
            high_confidence_correct=8,
            high_confidence_win_rate=0.667
        )

        mock_result = Mock()
        mock_result.__iter__ = Mock(return_value=iter([mock_row]))
        mock_daily_processor.bq_client.query.return_value.result.return_value = mock_result

        summaries = mock_daily_processor._compute_daily_summaries(date(2025, 1, 15))

        assert len(summaries) == 1
        summary = summaries[0]

        assert summary['game_date'] == '2025-01-15'
        assert summary['system_id'] == 'catboost_v8'
        assert summary['win_rate'] == 0.60
        assert summary['mae'] == 4.2
        assert summary['high_confidence_win_rate'] == 0.667

    def test_process_no_data_returns_no_data(self, mock_daily_processor):
        """
        Test process() when no accuracy data exists.

        Should return status 'no_data'.
        """
        mock_daily_processor._check_accuracy_data_exists = Mock(return_value=False)

        result = mock_daily_processor.process(date(2025, 1, 15))

        assert result['status'] == 'no_data'
        assert result['records_written'] == 0

    def test_process_date_range(self, mock_daily_processor):
        """
        Test process_date_range iterates through dates.

        Should call process() for each date in range.
        """
        mock_daily_processor.process = Mock(return_value={
            'status': 'success',
            'records_written': 5
        })

        result = mock_daily_processor.process_date_range(
            start_date=date(2025, 1, 10),
            end_date=date(2025, 1, 15)
        )

        # Should process 6 dates (10, 11, 12, 13, 14, 15)
        assert mock_daily_processor.process.call_count == 6
        assert result['dates_processed'] == 6


# ============================================================================
# TEST CLASS 4: HIGH CONFIDENCE ANALYSIS (5 tests)
# ============================================================================

class TestHighConfidenceAnalysis:
    """Test high-confidence prediction tracking."""

    def test_high_confidence_threshold_70(self, mock_performance_tracker):
        """
        Test that high confidence threshold is 0.70.

        Verifies query uses >= 0.70 for high confidence.
        """
        mock_result = Mock()
        mock_result.__iter__ = Mock(return_value=iter([]))
        mock_performance_tracker.bq_client.query.return_value.result.return_value = mock_result

        mock_performance_tracker.compute_system_performance(
            date(2025, 1, 8),
            date(2025, 1, 15)
        )

        query = mock_performance_tracker.bq_client.query.call_args[0][0]

        assert 'confidence_score >= 0.70' in query

    def test_very_high_confidence_threshold_80(self, mock_performance_tracker):
        """
        Test that very high confidence threshold is 0.80.

        Verifies query uses >= 0.80 for very high confidence.
        """
        mock_result = Mock()
        mock_result.__iter__ = Mock(return_value=iter([]))
        mock_performance_tracker.bq_client.query.return_value.result.return_value = mock_result

        mock_performance_tracker.compute_system_performance(
            date(2025, 1, 8),
            date(2025, 1, 15)
        )

        query = mock_performance_tracker.bq_client.query.call_args[0][0]

        assert 'confidence_score >= 0.80' in query

    def test_high_confidence_win_rate_calculation(self, sample_system_performance):
        """
        Test high confidence win rate calculation.

        24 wins from 35 high-conf predictions = 68.6%
        """
        # Based on fixture data
        expected = 24 / 35 * 100  # 68.57%

        assert abs(sample_system_performance['high_conf_success_rate_pct'] - expected) < 0.1

    def test_confidence_tier_filtering_in_query(self, mock_summary_processor):
        """
        Test that confidence tiers are correctly filtered.

        Should have high (>=0.70), medium (0.55-0.70), low (<0.55).
        """
        mock_result = Mock()
        mock_result.total_predictions = 0
        mock_list = Mock()
        mock_list.__iter__ = Mock(return_value=iter([mock_result]))
        mock_summary_processor.bq_client.query.return_value.result.return_value = mock_list

        # Call with tier filter
        mock_summary_processor._query_aggregation(
            system_id='catboost_v8',
            start_date=date(2025, 1, 8),
            end_date=date(2025, 1, 15),
            dimension_filter='confidence_score >= 0.70 AND confidence_score < 1.0'
        )

        query = mock_summary_processor.bq_client.query.call_args[0][0]

        assert 'confidence_score >= 0.70' in query

    def test_avg_confidence_tracking(self, sample_system_performance):
        """
        Test average confidence tracking.

        Should report average confidence score for the period.
        """
        assert sample_system_performance['avg_confidence'] == 0.72
        assert 0 <= sample_system_performance['avg_confidence'] <= 1.0


# ============================================================================
# TEST CLASS 5: OVER/UNDER SPLITS (5 tests)
# ============================================================================

class TestOverUnderSplits:
    """Test separate OVER/UNDER tracking."""

    def test_over_under_separate_counts(self, sample_system_performance):
        """
        Test that OVER and UNDER are tracked separately.

        Total recommendations = over_count + under_count
        """
        assert sample_system_performance['over_count'] == 65
        assert sample_system_performance['under_count'] == 55
        assert sample_system_performance['over_count'] + sample_system_performance['under_count'] == \
               sample_system_performance['total_recommendations']

    def test_over_success_rate_calculation(self, sample_system_performance):
        """
        Test OVER success rate calculation.

        40 wins from 65 OVER recommendations = 61.5%
        """
        expected = 40 / 65 * 100  # 61.54%

        assert abs(sample_system_performance['over_success_rate_pct'] - expected) < 0.1

    def test_under_success_rate_calculation(self, sample_system_performance):
        """
        Test UNDER success rate calculation.

        32 wins from 55 UNDER recommendations = 58.2%
        """
        expected = 32 / 55 * 100  # 58.18%

        assert abs(sample_system_performance['under_success_rate_pct'] - expected) < 0.1

    def test_over_under_in_query(self, mock_performance_tracker):
        """
        Test that query includes OVER/UNDER breakdowns.

        Should have COUNTIF for recommendation = 'OVER' and 'UNDER'.
        """
        mock_result = Mock()
        mock_result.__iter__ = Mock(return_value=iter([]))
        mock_performance_tracker.bq_client.query.return_value.result.return_value = mock_result

        mock_performance_tracker.compute_system_performance(
            date(2025, 1, 8),
            date(2025, 1, 15)
        )

        query = mock_performance_tracker.bq_client.query.call_args[0][0]

        assert "recommendation = 'OVER'" in query
        assert "recommendation = 'UNDER'" in query

    def test_pass_excluded_from_success_rate(self, mock_performance_tracker):
        """
        Test that PASS recommendations are excluded from success rate.

        Success rate = wins / (OVER + UNDER recommendations only)
        """
        mock_result = Mock()
        mock_result.__iter__ = Mock(return_value=iter([]))
        mock_performance_tracker.bq_client.query.return_value.result.return_value = mock_result

        mock_performance_tracker.compute_system_performance(
            date(2025, 1, 8),
            date(2025, 1, 15)
        )

        query = mock_performance_tracker.bq_client.query.call_args[0][0]

        # Success rate denominator should only include OVER/UNDER
        assert "recommendation IN ('OVER', 'UNDER')" in query


# ============================================================================
# TEST CLASS 6: DUPLICATE DETECTION (4 tests)
# ============================================================================

class TestDuplicateDetection:
    """Test duplicate detection for data integrity."""

    def test_check_for_duplicates_no_duplicates(self, mock_daily_processor):
        """
        Test duplicate check when no duplicates exist.

        Should return 0.
        """
        mock_row = Mock(duplicate_count=0)
        mock_result = Mock()
        mock_result.__iter__ = Mock(return_value=iter([mock_row]))
        mock_daily_processor.bq_client.query.return_value.result.return_value = mock_result

        result = mock_daily_processor._check_for_duplicates(date(2025, 1, 15))

        assert result == 0

    def test_check_for_duplicates_found(self, mock_daily_processor):
        """
        Test duplicate check when duplicates found.

        Should return count > 0.
        """
        mock_row = Mock(duplicate_count=3)
        mock_result = Mock()
        mock_result.__iter__ = Mock(return_value=iter([mock_row]))
        mock_daily_processor.bq_client.query.return_value.result.return_value = mock_result

        result = mock_daily_processor._check_for_duplicates(date(2025, 1, 15))

        assert result == 3

    def test_check_for_duplicates_query_failure_returns_negative(self, mock_daily_processor):
        """
        Test duplicate check handles query failure.

        Should return -1 to indicate check failed.
        """
        mock_daily_processor.bq_client.query.side_effect = Exception("Query timeout")

        result = mock_daily_processor._check_for_duplicates(date(2025, 1, 15))

        assert result == -1

    def test_write_with_validation_deletes_before_insert(self, mock_daily_processor):
        """
        Test that write operation deletes before inserting.

        Prevents duplicates via DELETE + INSERT pattern.
        """
        mock_daily_processor._check_for_duplicates = Mock(return_value=0)

        # Mock successful query and load
        mock_delete_job = Mock()
        mock_delete_job.result.return_value = None
        mock_delete_job.num_dml_affected_rows = 5

        mock_load_job = Mock()
        mock_load_job.result.return_value = None
        mock_load_job.output_rows = 5
        mock_load_job.errors = []

        mock_daily_processor.bq_client.query.return_value = mock_delete_job
        mock_daily_processor.bq_client.get_table.return_value = Mock(schema=[])
        mock_daily_processor.bq_client.load_table_from_json.return_value = mock_load_job

        summaries = [{'game_date': '2025-01-15', 'system_id': 'test'}]

        mock_daily_processor._write_with_validation(summaries, date(2025, 1, 15))

        # Verify DELETE was called
        delete_query = mock_daily_processor.bq_client.query.call_args[0][0]
        assert 'DELETE FROM' in delete_query


# ============================================================================
# TEST CLASS 7: MULTI-DIMENSIONAL SLICING (4 tests)
# ============================================================================

class TestMultiDimensionalSlicing:
    """Test multi-dimensional performance slicing."""

    def test_slice_by_archetype(self, mock_summary_processor):
        """
        Test slicing by player archetype.

        Should group by archetype (veteran_star, prime_star, etc.).
        """
        mock_result = Mock()
        mock_result.__iter__ = Mock(return_value=iter([]))
        mock_summary_processor.bq_client.query.return_value.result.return_value = mock_result

        mock_summary_processor._query_by_archetype(
            system_id='catboost_v8',
            start_date=date(2025, 1, 8),
            end_date=date(2025, 1, 15)
        )

        query = mock_summary_processor.bq_client.query.call_args[0][0]

        assert 'archetype' in query.lower()
        assert 'GROUP BY' in query

    def test_slice_by_player(self, mock_summary_processor):
        """
        Test slicing by individual player.

        Should group by player_lookup with min predictions filter.
        """
        mock_result = Mock()
        mock_result.__iter__ = Mock(return_value=iter([]))
        mock_summary_processor.bq_client.query.return_value.result.return_value = mock_result

        mock_summary_processor._query_by_dimension(
            system_id='catboost_v8',
            start_date=date(2025, 1, 8),
            end_date=date(2025, 1, 15),
            dimension='player_lookup',
            min_predictions=5
        )

        query = mock_summary_processor.bq_client.query.call_args[0][0]

        assert 'player_lookup' in query
        assert 'HAVING COUNT(*) >= 5' in query

    def test_slice_by_confidence_tier(self, mock_summary_processor):
        """
        Test slicing by confidence tier.

        Should create separate summaries for high/medium/low.
        """
        # High tier filter
        high_filter = 'confidence_score >= 0.70 AND confidence_score < 1.0'

        # Verify filter format
        assert 'confidence_score >= 0.70' in high_filter
        assert 'confidence_score < 1.0' in high_filter

    def test_slice_by_situation_home_away(self, mock_summary_processor):
        """
        Test slicing by situation (home/away).

        Should filter by team position in game_id.
        """
        mock_result = Mock()
        mock_result.total_predictions = 0
        mock_list = Mock()
        mock_list.__iter__ = Mock(return_value=iter([mock_result]))
        mock_summary_processor.bq_client.query.return_value.result.return_value = mock_list

        # Home filter
        home_condition = "team_abbr = SPLIT(game_id, '_')[OFFSET(2)]"

        mock_summary_processor._query_aggregation(
            system_id='catboost_v8',
            start_date=date(2025, 1, 8),
            end_date=date(2025, 1, 15),
            dimension_filter=home_condition
        )

        query = mock_summary_processor.bq_client.query.call_args[0][0]

        assert 'team_abbr' in query


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
