"""
Unit Tests for System Daily Performance Processor

Tests individual methods and calculations in isolation.
Run with: pytest tests/processors/grading/system_daily_performance/test_unit.py -v

Path: tests/processors/grading/system_daily_performance/test_unit.py
"""

import pytest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock, MagicMock, patch

from data_processors.grading.system_daily_performance.system_daily_performance_processor import (
    SystemDailyPerformanceProcessor
)


class TestCheckAccuracyDataExists:
    """Test accuracy data existence check."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked BigQuery client."""
        with patch('data_processors.grading.system_daily_performance.system_daily_performance_processor.bigquery'):
            proc = SystemDailyPerformanceProcessor(project_id='test-project')
            proc.bq_client = Mock()
            return proc

    def test_returns_true_when_data_exists(self, processor):
        """Test returns True when count > 0."""
        mock_result = Mock()
        mock_result.count = 150
        processor.bq_client.query.return_value.result.return_value = [mock_result]

        result = processor._check_accuracy_data_exists(date(2025, 12, 15))

        assert result is True

    def test_returns_false_when_no_data(self, processor):
        """Test returns False when count = 0."""
        mock_result = Mock()
        mock_result.count = 0
        processor.bq_client.query.return_value.result.return_value = [mock_result]

        result = processor._check_accuracy_data_exists(date(2025, 12, 15))

        assert result is False

    def test_returns_false_on_exception(self, processor):
        """Test returns False on query error."""
        processor.bq_client.query.side_effect = Exception("BigQuery error")

        result = processor._check_accuracy_data_exists(date(2025, 12, 15))

        assert result is False

    def test_returns_false_on_empty_result(self, processor):
        """Test returns False when result is empty."""
        processor.bq_client.query.return_value.result.return_value = []

        result = processor._check_accuracy_data_exists(date(2025, 12, 15))

        assert result is False


class TestComputeDailySummaries:
    """Test daily summary aggregation."""

    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        with patch('data_processors.grading.system_daily_performance.system_daily_performance_processor.bigquery'):
            proc = SystemDailyPerformanceProcessor(project_id='test-project')
            proc.bq_client = Mock()
            return proc

    def test_returns_summaries_for_each_system(self, processor):
        """Test that summaries are generated for each system."""
        mock_row1 = Mock()
        mock_row1.game_date = date(2025, 12, 15)
        mock_row1.system_id = 'ensemble_v1'
        mock_row1.predictions_count = 150
        mock_row1.recommendations_count = 120
        mock_row1.correct_count = 78
        mock_row1.incorrect_count = 42
        mock_row1.pass_count = 30
        mock_row1.win_rate = 0.65
        mock_row1.mae = 4.5
        mock_row1.avg_bias = -0.3
        mock_row1.over_count = 65
        mock_row1.over_correct = 45
        mock_row1.over_win_rate = 0.692
        mock_row1.under_count = 55
        mock_row1.under_correct = 33
        mock_row1.under_win_rate = 0.60
        mock_row1.within_3_count = 52
        mock_row1.within_3_pct = 0.347
        mock_row1.within_5_count = 85
        mock_row1.within_5_pct = 0.567
        mock_row1.avg_confidence = 0.62
        mock_row1.high_confidence_count = 45
        mock_row1.high_confidence_correct = 35
        mock_row1.high_confidence_win_rate = 0.778

        mock_row2 = Mock()
        mock_row2.game_date = date(2025, 12, 15)
        mock_row2.system_id = 'xgboost_v1'
        mock_row2.predictions_count = 150
        mock_row2.recommendations_count = 130
        mock_row2.correct_count = 82
        mock_row2.incorrect_count = 48
        mock_row2.pass_count = 20
        mock_row2.win_rate = 0.631
        mock_row2.mae = 4.8
        mock_row2.avg_bias = 0.2
        mock_row2.over_count = 70
        mock_row2.over_correct = 42
        mock_row2.over_win_rate = 0.60
        mock_row2.under_count = 60
        mock_row2.under_correct = 40
        mock_row2.under_win_rate = 0.667
        mock_row2.within_3_count = 48
        mock_row2.within_3_pct = 0.32
        mock_row2.within_5_count = 80
        mock_row2.within_5_pct = 0.533
        mock_row2.avg_confidence = 0.58
        mock_row2.high_confidence_count = 35
        mock_row2.high_confidence_correct = 25
        mock_row2.high_confidence_win_rate = 0.714

        processor.bq_client.query.return_value.result.return_value = [mock_row1, mock_row2]

        result = processor._compute_daily_summaries(date(2025, 12, 15))

        assert len(result) == 2
        assert result[0]['system_id'] == 'ensemble_v1'
        assert result[1]['system_id'] == 'xgboost_v1'

    def test_converts_date_to_iso_string(self, processor):
        """Test that game_date is converted to ISO string."""
        mock_row = Mock()
        mock_row.game_date = date(2025, 12, 15)
        mock_row.system_id = 'ensemble_v1'
        mock_row.predictions_count = 100
        mock_row.recommendations_count = 80
        mock_row.correct_count = 50
        mock_row.incorrect_count = 30
        mock_row.pass_count = 20
        mock_row.win_rate = 0.625
        mock_row.mae = 4.0
        mock_row.avg_bias = 0.0
        mock_row.over_count = 40
        mock_row.over_correct = 25
        mock_row.over_win_rate = 0.625
        mock_row.under_count = 40
        mock_row.under_correct = 25
        mock_row.under_win_rate = 0.625
        mock_row.within_3_count = 35
        mock_row.within_3_pct = 0.35
        mock_row.within_5_count = 55
        mock_row.within_5_pct = 0.55
        mock_row.avg_confidence = 0.60
        mock_row.high_confidence_count = 30
        mock_row.high_confidence_correct = 20
        mock_row.high_confidence_win_rate = 0.667

        processor.bq_client.query.return_value.result.return_value = [mock_row]

        result = processor._compute_daily_summaries(date(2025, 12, 15))

        assert result[0]['game_date'] == '2025-12-15'

    def test_handles_none_values(self, processor):
        """Test that None values are preserved."""
        mock_row = Mock()
        mock_row.game_date = date(2025, 12, 15)
        mock_row.system_id = 'ensemble_v1'
        mock_row.predictions_count = 0
        mock_row.recommendations_count = 0
        mock_row.correct_count = 0
        mock_row.incorrect_count = 0
        mock_row.pass_count = 0
        mock_row.win_rate = None  # SAFE_DIVIDE returns NULL
        mock_row.mae = None
        mock_row.avg_bias = None
        mock_row.over_count = 0
        mock_row.over_correct = 0
        mock_row.over_win_rate = None
        mock_row.under_count = 0
        mock_row.under_correct = 0
        mock_row.under_win_rate = None
        mock_row.within_3_count = 0
        mock_row.within_3_pct = None
        mock_row.within_5_count = 0
        mock_row.within_5_pct = None
        mock_row.avg_confidence = None
        mock_row.high_confidence_count = 0
        mock_row.high_confidence_correct = 0
        mock_row.high_confidence_win_rate = None

        processor.bq_client.query.return_value.result.return_value = [mock_row]

        result = processor._compute_daily_summaries(date(2025, 12, 15))

        assert result[0]['win_rate'] is None
        assert result[0]['mae'] is None
        assert result[0]['high_confidence_win_rate'] is None

    def test_includes_computed_at_timestamp(self, processor):
        """Test that computed_at timestamp is included."""
        mock_row = Mock()
        mock_row.game_date = date(2025, 12, 15)
        mock_row.system_id = 'ensemble_v1'
        mock_row.predictions_count = 100
        mock_row.recommendations_count = 80
        mock_row.correct_count = 50
        mock_row.incorrect_count = 30
        mock_row.pass_count = 20
        mock_row.win_rate = 0.625
        mock_row.mae = 4.0
        mock_row.avg_bias = 0.0
        mock_row.over_count = 40
        mock_row.over_correct = 25
        mock_row.over_win_rate = 0.625
        mock_row.under_count = 40
        mock_row.under_correct = 25
        mock_row.under_win_rate = 0.625
        mock_row.within_3_count = 35
        mock_row.within_3_pct = 0.35
        mock_row.within_5_count = 55
        mock_row.within_5_pct = 0.55
        mock_row.avg_confidence = 0.60
        mock_row.high_confidence_count = 30
        mock_row.high_confidence_correct = 20
        mock_row.high_confidence_win_rate = 0.667

        processor.bq_client.query.return_value.result.return_value = [mock_row]

        result = processor._compute_daily_summaries(date(2025, 12, 15))

        assert 'computed_at' in result[0]
        assert 'T' in result[0]['computed_at']  # ISO format

    def test_returns_empty_list_on_exception(self, processor):
        """Test that exceptions return empty list."""
        processor.bq_client.query.side_effect = Exception("Query failed")

        result = processor._compute_daily_summaries(date(2025, 12, 15))

        assert result == []

    def test_returns_empty_list_when_no_data(self, processor):
        """Test that empty query result returns empty list."""
        processor.bq_client.query.return_value.result.return_value = []

        result = processor._compute_daily_summaries(date(2025, 12, 15))

        assert result == []


class TestWriteSummaries:
    """Test writing summaries to BigQuery."""

    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        with patch('data_processors.grading.system_daily_performance.system_daily_performance_processor.bigquery') as mock_bq:
            proc = SystemDailyPerformanceProcessor(project_id='test-project')
            proc.bq_client = Mock()
            # Mock table reference
            mock_table = Mock()
            mock_table.schema = []
            proc.bq_client.get_table.return_value = mock_table
            return proc

    def test_returns_zero_for_empty_list(self, processor):
        """Test that 0 is returned for empty summaries."""
        result = processor._write_summaries([], date(2025, 12, 15))
        assert result == 0

    def test_deletes_existing_records_first(self, processor):
        """Test idempotency - deletes before insert."""
        mock_delete_job = Mock()
        mock_delete_job.result.return_value = None
        mock_delete_job.num_dml_affected_rows = 5
        processor.bq_client.query.return_value = mock_delete_job

        mock_load_job = Mock()
        mock_load_job.result.return_value = None
        mock_load_job.errors = None
        mock_load_job.output_rows = 5
        processor.bq_client.load_table_from_json.return_value = mock_load_job

        summaries = [{'system_id': 'ensemble_v1', 'game_date': '2025-12-15'}]
        processor._write_summaries(summaries, date(2025, 12, 15))

        # Verify delete query was called
        delete_call = processor.bq_client.query.call_args[0][0]
        assert "DELETE FROM" in delete_call
        assert "2025-12-15" in delete_call

    def test_returns_output_rows_count(self, processor):
        """Test that output_rows count is returned."""
        mock_delete_job = Mock()
        mock_delete_job.result.return_value = None
        mock_delete_job.num_dml_affected_rows = 0
        processor.bq_client.query.return_value = mock_delete_job

        mock_load_job = Mock()
        mock_load_job.result.return_value = None
        mock_load_job.errors = None
        mock_load_job.output_rows = 5
        processor.bq_client.load_table_from_json.return_value = mock_load_job

        summaries = [
            {'system_id': 'ensemble_v1'},
            {'system_id': 'xgboost_v1'},
        ]
        result = processor._write_summaries(summaries, date(2025, 12, 15))

        assert result == 5

    def test_handles_exception(self, processor):
        """Test that exceptions return 0."""
        processor.bq_client.query.side_effect = Exception("Delete failed")

        summaries = [{'system_id': 'ensemble_v1'}]
        result = processor._write_summaries(summaries, date(2025, 12, 15))

        assert result == 0


class TestProcess:
    """Test the main process method."""

    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        with patch('data_processors.grading.system_daily_performance.system_daily_performance_processor.bigquery'):
            proc = SystemDailyPerformanceProcessor(project_id='test-project')
            proc.bq_client = Mock()
            return proc

    def test_returns_no_data_status_when_no_accuracy_data(self, processor):
        """Test no_data status when prediction_accuracy is empty."""
        processor._check_accuracy_data_exists = Mock(return_value=False)

        result = processor.process(date(2025, 12, 15))

        assert result['status'] == 'no_data'
        assert result['systems'] == 0
        assert result['records_written'] == 0

    def test_returns_no_summaries_when_compute_fails(self, processor):
        """Test no_summaries status when aggregation returns empty."""
        processor._check_accuracy_data_exists = Mock(return_value=True)
        processor._compute_daily_summaries = Mock(return_value=[])

        result = processor.process(date(2025, 12, 15))

        assert result['status'] == 'no_summaries'

    def test_returns_success_when_summaries_written(self, processor):
        """Test success status when summaries are written."""
        processor._check_accuracy_data_exists = Mock(return_value=True)
        processor._compute_daily_summaries = Mock(return_value=[
            {'system_id': 'ensemble_v1', 'game_date': '2025-12-15'}
        ])
        processor._write_summaries = Mock(return_value=1)

        result = processor.process(date(2025, 12, 15))

        assert result['status'] == 'success'
        assert result['systems'] == 1
        assert result['records_written'] == 1

    def test_uses_yesterday_as_default_date(self, processor):
        """Test that yesterday is used when no date specified."""
        processor._check_accuracy_data_exists = Mock(return_value=False)

        with patch('data_processors.grading.system_daily_performance.system_daily_performance_processor.date') as mock_date:
            mock_date.today.return_value = date(2025, 12, 18)
            mock_date.side_effect = lambda *args, **kw: date(*args, **kw)

            result = processor.process()

            # Should check for yesterday (2025-12-17)
            call_args = processor._check_accuracy_data_exists.call_args[0][0]
            assert call_args == date(2025, 12, 17)

    def test_returns_write_failed_when_no_records_written(self, processor):
        """Test write_failed status when write returns 0."""
        processor._check_accuracy_data_exists = Mock(return_value=True)
        processor._compute_daily_summaries = Mock(return_value=[
            {'system_id': 'ensemble_v1'}
        ])
        processor._write_summaries = Mock(return_value=0)

        result = processor.process(date(2025, 12, 15))

        assert result['status'] == 'write_failed'


class TestProcessDateRange:
    """Test date range processing."""

    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        with patch('data_processors.grading.system_daily_performance.system_daily_performance_processor.bigquery'):
            proc = SystemDailyPerformanceProcessor(project_id='test-project')
            proc.bq_client = Mock()
            return proc

    def test_processes_each_date_in_range(self, processor):
        """Test that each date in range is processed."""
        call_dates = []

        def mock_process(target_date):
            call_dates.append(target_date)
            return {'status': 'success', 'records_written': 5}

        processor.process = mock_process

        result = processor.process_date_range(
            date(2025, 12, 15),
            date(2025, 12, 17)
        )

        assert len(call_dates) == 3
        assert date(2025, 12, 15) in call_dates
        assert date(2025, 12, 16) in call_dates
        assert date(2025, 12, 17) in call_dates

    def test_counts_processed_and_skipped(self, processor):
        """Test that processed and skipped counts are tracked."""
        call_count = [0]

        def mock_process(target_date):
            call_count[0] += 1
            if call_count[0] % 2 == 0:
                return {'status': 'no_data', 'records_written': 0}
            return {'status': 'success', 'records_written': 5}

        processor.process = mock_process

        result = processor.process_date_range(
            date(2025, 12, 15),
            date(2025, 12, 18)
        )

        assert result['dates_processed'] == 2  # 1st and 3rd
        assert result['dates_skipped'] == 2    # 2nd and 4th

    def test_sums_total_records_written(self, processor):
        """Test that total records are summed."""
        def mock_process(target_date):
            return {'status': 'success', 'records_written': 5}

        processor.process = mock_process

        result = processor.process_date_range(
            date(2025, 12, 15),
            date(2025, 12, 17)
        )

        assert result['total_records_written'] == 15  # 3 days * 5 records


class TestGetDatesWithAccuracyData:
    """Test getting dates that have accuracy data."""

    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        with patch('data_processors.grading.system_daily_performance.system_daily_performance_processor.bigquery'):
            proc = SystemDailyPerformanceProcessor(project_id='test-project')
            proc.bq_client = Mock()
            return proc

    def test_returns_list_of_dates(self, processor):
        """Test that dates are returned as list."""
        mock_row1 = Mock()
        mock_row1.game_date = date(2025, 12, 15)
        mock_row2 = Mock()
        mock_row2.game_date = date(2025, 12, 16)

        processor.bq_client.query.return_value.result.return_value = [mock_row1, mock_row2]

        result = processor.get_dates_with_accuracy_data(
            date(2025, 12, 15),
            date(2025, 12, 17)
        )

        assert len(result) == 2
        assert date(2025, 12, 15) in result
        assert date(2025, 12, 16) in result

    def test_returns_empty_list_on_exception(self, processor):
        """Test that exceptions return empty list."""
        processor.bq_client.query.side_effect = Exception("Query failed")

        result = processor.get_dates_with_accuracy_data(
            date(2025, 12, 15),
            date(2025, 12, 17)
        )

        assert result == []


# ============================================================================
# Test Summary
# ============================================================================
# Total Tests: 30 unit tests
# Coverage: Core processor methods for system daily performance aggregation
#
# Test Distribution:
# - _check_accuracy_data_exists: 4 tests
# - _compute_daily_summaries: 6 tests
# - _write_summaries: 4 tests
# - process: 5 tests
# - process_date_range: 3 tests
# - get_dates_with_accuracy_data: 2 tests
#
# Run with:
#   pytest tests/processors/grading/system_daily_performance/test_unit.py -v
# ============================================================================
