"""
Unit Tests for ExecutionLogger (Phase 5 Worker)

Tests cover:
1. Execution logging (success/failure)
2. Metadata tracking (systems, data quality, performance)
3. Convenience methods (log_success, log_failure)
4. Field validation and formatting
5. BigQuery integration
6. Error handling
"""

import pytest
from datetime import datetime
from unittest.mock import Mock, MagicMock
from predictions.worker.execution_logger import ExecutionLogger


class MockBigQueryClient:
    """Mock BigQuery client for testing"""

    def __init__(self):
        self.inserted_rows = []
        self.insert_errors = []
        self.load_job_result = Mock()

    def insert_rows_json(self, table_id, rows):
        """Mock insert rows"""
        self.inserted_rows.extend(rows)
        return self.insert_errors

    def get_table(self, table_id):
        """Mock get_table for schema retrieval"""
        mock_table = Mock()
        mock_table.schema = []  # Empty schema is fine for testing
        return mock_table

    def load_table_from_json(self, rows, table_id, job_config=None):
        """Mock load_table_from_json for batch loading"""
        self.inserted_rows.extend(rows)
        mock_job = Mock()
        mock_job.result.return_value = None
        return mock_job


class TestExecutionLoggerInit:
    """Test suite for ExecutionLogger initialization"""

    def test_initialization(self):
        """Test that logger initializes correctly"""
        bq_client = MockBigQueryClient()

        logger = ExecutionLogger(bq_client, 'test-project', worker_version='1.0')

        assert logger.bq_client == bq_client
        assert logger.project_id == 'test-project'
        assert logger.worker_version == '1.0'
        assert logger.table_id == 'test-project.nba_predictions.prediction_worker_runs'

    def test_default_worker_version(self):
        """Test that default worker version is set"""
        bq_client = MockBigQueryClient()

        logger = ExecutionLogger(bq_client, 'test-project')

        assert logger.worker_version == '1.0'


class TestLogExecution:
    """Test suite for log_execution method"""

    def test_log_successful_execution(self):
        """Test logging successful execution"""
        bq_client = MockBigQueryClient()
        logger = ExecutionLogger(bq_client, 'test-project')

        logger.log_execution(
            player_lookup='LeBron James',
            universal_player_id='player-123',
            game_date='2024-11-20',
            game_id='game-456',
            line_values_requested=[25.5, 30.5],
            success=True,
            duration_seconds=1.5,
            predictions_generated=2,
            systems_succeeded=['moving_average', 'xgboost_v1'],
            systems_failed=[],
            system_errors={},
            feature_quality_score=0.95,
            historical_games_count=10
        )

        # Should have inserted one row
        assert len(bq_client.inserted_rows) == 1

        row = bq_client.inserted_rows[0]
        assert row['player_lookup'] == 'LeBron James'
        assert row['success'] is True
        assert row['predictions_generated'] == 2
        assert len(row['systems_succeeded']) == 2
        assert len(row['systems_failed']) == 0

    def test_log_failed_execution(self):
        """Test logging failed execution"""
        bq_client = MockBigQueryClient()
        logger = ExecutionLogger(bq_client, 'test-project')

        logger.log_execution(
            player_lookup='Kevin Durant',
            universal_player_id='player-789',
            game_date='2024-11-20',
            game_id='game-456',
            line_values_requested=[28.5],
            success=False,
            duration_seconds=0.5,
            predictions_generated=0,
            error_message='No features available',
            error_type='ValueError',
            systems_attempted=['moving_average'],
            systems_failed=['moving_average']
        )

        assert len(bq_client.inserted_rows) == 1

        row = bq_client.inserted_rows[0]
        assert row['success'] is False
        assert row['predictions_generated'] == 0
        assert row['error_message'] == 'No features available'
        assert row['error_type'] == 'ValueError'

    def test_request_id_generated(self):
        """Test that unique request ID is generated"""
        bq_client = MockBigQueryClient()
        logger = ExecutionLogger(bq_client, 'test-project')

        # Log two executions
        for i in range(2):
            logger.log_execution(
                player_lookup=f'Player {i}',
                universal_player_id=f'player-{i}',
                game_date='2024-11-20',
                game_id='game-456',
                line_values_requested=[25.5],
                success=True,
                duration_seconds=1.0,
                predictions_generated=1
            )

        # Should have two different request IDs
        assert len(bq_client.inserted_rows) == 2
        request_id_1 = bq_client.inserted_rows[0]['request_id']
        request_id_2 = bq_client.inserted_rows[1]['request_id']

        assert request_id_1 != request_id_2

    def test_timestamps_set(self):
        """Test that timestamps are set correctly"""
        bq_client = MockBigQueryClient()
        logger = ExecutionLogger(bq_client, 'test-project')

        logger.log_execution(
            player_lookup='Stephen Curry',
            universal_player_id='player-999',
            game_date='2024-11-20',
            game_id='game-456',
            line_values_requested=[30.5],
            success=True,
            duration_seconds=1.2,
            predictions_generated=1
        )

        row = bq_client.inserted_rows[0]

        assert 'run_date' in row
        assert 'created_at' in row
        assert row['run_date'] is not None
        assert row['created_at'] is not None

    def test_system_errors_json_serialization(self):
        """Test that system_errors dict is JSON serialized"""
        bq_client = MockBigQueryClient()
        logger = ExecutionLogger(bq_client, 'test-project')

        system_errors = {
            'moving_average': 'Insufficient data',
            'xgboost_v1': 'Model not loaded'
        }

        logger.log_execution(
            player_lookup='Giannis Antetokounmpo',
            universal_player_id='player-111',
            game_date='2024-11-20',
            game_id='game-456',
            line_values_requested=[32.5],
            success=False,
            duration_seconds=0.8,
            predictions_generated=0,
            system_errors=system_errors
        )

        row = bq_client.inserted_rows[0]

        # Should be JSON string
        assert isinstance(row['system_errors'], str)
        assert 'moving_average' in row['system_errors']

    def test_default_empty_lists(self):
        """Test that empty lists are used for missing arrays"""
        bq_client = MockBigQueryClient()
        logger = ExecutionLogger(bq_client, 'test-project')

        logger.log_execution(
            player_lookup='Luka Doncic',
            universal_player_id='player-222',
            game_date='2024-11-20',
            game_id='game-456',
            line_values_requested=[29.5],
            success=True,
            duration_seconds=1.1,
            predictions_generated=1
            # Not providing systems_attempted, systems_succeeded, etc.
        )

        row = bq_client.inserted_rows[0]

        # Should have empty lists
        assert row['systems_attempted'] == []
        assert row['systems_succeeded'] == []
        assert row['systems_failed'] == []
        assert row['missing_features'] == []
        assert row['circuits_opened'] == []


class TestLogSuccessConvenience:
    """Test suite for log_success convenience method"""

    def test_log_success_basic(self):
        """Test basic log_success call"""
        bq_client = MockBigQueryClient()
        logger = ExecutionLogger(bq_client, 'test-project')

        logger.log_success(
            player_lookup='Jayson Tatum',
            universal_player_id='player-333',
            game_date='2024-11-20',
            game_id='game-456',
            line_values=[26.5],
            duration_seconds=1.3,
            predictions_generated=1,
            systems_succeeded=['moving_average', 'xgboost_v1', 'ensemble_v1'],
            systems_failed=['zone_matchup_v1', 'similarity_balanced_v1'],
            system_errors={
                'zone_matchup_v1': 'No matchup data',
                'similarity_balanced_v1': 'No historical games'
            },
            feature_quality_score=0.88,
            historical_games_count=8,
            performance_breakdown={
                'data_load': 0.3,
                'prediction_compute': 0.8,
                'write_bigquery': 0.1,
                'pubsub_publish': 0.1
            }
        )

        assert len(bq_client.inserted_rows) == 1

        row = bq_client.inserted_rows[0]
        assert row['success'] is True
        assert row['predictions_generated'] == 1
        assert len(row['systems_succeeded']) == 3
        assert len(row['systems_failed']) == 2
        assert row['feature_quality_score'] == 0.88
        assert row['data_load_seconds'] == 0.3
        assert row['prediction_compute_seconds'] == 0.8

    def test_log_success_all_systems_attempted(self):
        """Test that log_success sets all 5 systems as attempted"""
        bq_client = MockBigQueryClient()
        logger = ExecutionLogger(bq_client, 'test-project')

        logger.log_success(
            player_lookup='Joel Embiid',
            universal_player_id='player-444',
            game_date='2024-11-20',
            game_id='game-456',
            line_values=[31.5],
            duration_seconds=1.4,
            predictions_generated=1,
            systems_succeeded=['moving_average'],
            systems_failed=[],
            system_errors={},
            feature_quality_score=0.92,
            historical_games_count=12,
            performance_breakdown={}
        )

        row = bq_client.inserted_rows[0]

        # All 5 systems should be in attempted list
        expected_systems = [
            'moving_average',
            'zone_matchup_v1',
            'similarity_balanced_v1',
            'xgboost_v1',
            'ensemble_v1'
        ]

        assert row['systems_attempted'] == expected_systems


class TestLogFailureConvenience:
    """Test suite for log_failure convenience method"""

    def test_log_failure_basic(self):
        """Test basic log_failure call"""
        bq_client = MockBigQueryClient()
        logger = ExecutionLogger(bq_client, 'test-project')

        logger.log_failure(
            player_lookup='Nikola Jokic',
            universal_player_id='player-555',
            game_date='2024-11-20',
            game_id='game-456',
            line_values=[27.5],
            duration_seconds=0.5,
            error_message='No features available for player',
            error_type='ValueError',
            skip_reason='no_features'
        )

        assert len(bq_client.inserted_rows) == 1

        row = bq_client.inserted_rows[0]
        assert row['success'] is False
        assert row['predictions_generated'] == 0
        assert row['error_message'] == 'No features available for player'
        assert row['error_type'] == 'ValueError'
        assert row['skip_reason'] == 'no_features'

    def test_log_failure_with_circuit_breaker(self):
        """Test log_failure with circuit breaker triggered"""
        bq_client = MockBigQueryClient()
        logger = ExecutionLogger(bq_client, 'test-project')

        logger.log_failure(
            player_lookup='Damian Lillard',
            universal_player_id='player-666',
            game_date='2024-11-20',
            game_id='game-456',
            line_values=[28.5],
            duration_seconds=0.2,
            error_message='All systems failed',
            error_type='RuntimeError',
            systems_attempted=['moving_average', 'xgboost_v1'],
            systems_failed=['moving_average', 'xgboost_v1'],
            circuit_breaker_triggered=True,
            circuits_opened=['moving_average', 'xgboost_v1']
        )

        row = bq_client.inserted_rows[0]
        assert row['circuit_breaker_triggered'] is True
        assert len(row['circuits_opened']) == 2
        assert 'moving_average' in row['circuits_opened']

    def test_log_failure_systems_empty_by_default(self):
        """Test that systems lists are empty by default in log_failure"""
        bq_client = MockBigQueryClient()
        logger = ExecutionLogger(bq_client, 'test-project')

        logger.log_failure(
            player_lookup='Devin Booker',
            universal_player_id='player-777',
            game_date='2024-11-20',
            game_id='game-456',
            line_values=[29.5],
            duration_seconds=0.3,
            error_message='Feature validation failed',
            error_type='ValueError'
        )

        row = bq_client.inserted_rows[0]
        assert row['systems_succeeded'] == []
        assert row['systems_failed'] == []


class TestPerformanceBreakdown:
    """Test suite for performance breakdown tracking"""

    def test_performance_breakdown_all_fields(self):
        """Test that all performance fields are logged"""
        bq_client = MockBigQueryClient()
        logger = ExecutionLogger(bq_client, 'test-project')

        logger.log_execution(
            player_lookup='Jimmy Butler',
            universal_player_id='player-888',
            game_date='2024-11-20',
            game_id='game-456',
            line_values_requested=[24.5],
            success=True,
            duration_seconds=2.5,
            predictions_generated=1,
            data_load_seconds=0.5,
            prediction_compute_seconds=1.5,
            write_bigquery_seconds=0.3,
            pubsub_publish_seconds=0.2
        )

        row = bq_client.inserted_rows[0]

        assert row['data_load_seconds'] == 0.5
        assert row['prediction_compute_seconds'] == 1.5
        assert row['write_bigquery_seconds'] == 0.3
        assert row['pubsub_publish_seconds'] == 0.2

        # Total should match duration (approximately)
        total = (row['data_load_seconds'] +
                 row['prediction_compute_seconds'] +
                 row['write_bigquery_seconds'] +
                 row['pubsub_publish_seconds'])

        assert abs(total - row['duration_seconds']) < 0.1


class TestDataQualityTracking:
    """Test suite for data quality tracking"""

    def test_feature_quality_score(self):
        """Test feature quality score logging"""
        bq_client = MockBigQueryClient()
        logger = ExecutionLogger(bq_client, 'test-project')

        logger.log_execution(
            player_lookup='Anthony Davis',
            universal_player_id='player-999',
            game_date='2024-11-20',
            game_id='game-456',
            line_values_requested=[27.5],
            success=True,
            duration_seconds=1.2,
            predictions_generated=1,
            feature_quality_score=0.75,
            missing_features=['rest_days', 'matchup_factor']
        )

        row = bq_client.inserted_rows[0]

        assert row['feature_quality_score'] == 0.75
        assert len(row['missing_features']) == 2
        assert 'rest_days' in row['missing_features']

    def test_historical_games_count(self):
        """Test historical games count logging"""
        bq_client = MockBigQueryClient()
        logger = ExecutionLogger(bq_client, 'test-project')

        logger.log_execution(
            player_lookup='Kawhi Leonard',
            universal_player_id='player-1010',
            game_date='2024-11-20',
            game_id='game-456',
            line_values_requested=[26.5],
            success=True,
            duration_seconds=1.3,
            predictions_generated=1,
            historical_games_count=15
        )

        row = bq_client.inserted_rows[0]

        assert row['historical_games_count'] == 15


class TestErrorHandling:
    """Test suite for error handling"""

    def test_bigquery_insert_error_handled_gracefully(self):
        """Test that BigQuery insert errors are handled gracefully"""
        bq_client = MockBigQueryClient()
        bq_client.insert_errors = ['Some error occurred']

        logger = ExecutionLogger(bq_client, 'test-project')

        # Should not raise exception
        try:
            logger.log_execution(
                player_lookup='Trae Young',
                universal_player_id='player-1111',
                game_date='2024-11-20',
                game_id='game-456',
                line_values_requested=[28.5],
                success=True,
                duration_seconds=1.0,
                predictions_generated=1
            )
            assert True  # Success - no exception raised
        except Exception:
            pytest.fail("Should handle BigQuery errors gracefully")

    def test_exception_during_logging_handled(self):
        """Test that exceptions during logging are caught"""
        bq_client = Mock()
        bq_client.insert_rows_json.side_effect = Exception("BigQuery unavailable")

        logger = ExecutionLogger(bq_client, 'test-project')

        # Should not raise exception
        try:
            logger.log_execution(
                player_lookup='Kyrie Irving',
                universal_player_id='player-1212',
                game_date='2024-11-20',
                game_id='game-456',
                line_values_requested=[27.5],
                success=True,
                duration_seconds=1.1,
                predictions_generated=1
            )
            assert True  # Success - exception was caught
        except Exception:
            pytest.fail("Should catch and handle logging exceptions")


class TestWorkerVersion:
    """Test suite for worker version tracking"""

    def test_worker_version_logged(self):
        """Test that worker version is logged"""
        bq_client = MockBigQueryClient()
        logger = ExecutionLogger(bq_client, 'test-project', worker_version='2.1')

        logger.log_execution(
            player_lookup='Paul George',
            universal_player_id='player-1313',
            game_date='2024-11-20',
            game_id='game-456',
            line_values_requested=[24.5],
            success=True,
            duration_seconds=1.0,
            predictions_generated=1
        )

        row = bq_client.inserted_rows[0]

        assert row['worker_version'] == '2.1'


class TestIntegration:
    """Integration tests for realistic scenarios"""

    def test_successful_prediction_with_partial_failures(self):
        """Test successful prediction with some systems failing"""
        bq_client = MockBigQueryClient()
        logger = ExecutionLogger(bq_client, 'test-project')

        logger.log_success(
            player_lookup='Jaylen Brown',
            universal_player_id='player-1414',
            game_date='2024-11-20',
            game_id='game-456',
            line_values=[25.5, 30.5],
            duration_seconds=2.1,
            predictions_generated=2,
            systems_succeeded=['moving_average', 'xgboost_v1', 'ensemble_v1'],
            systems_failed=['zone_matchup_v1', 'similarity_balanced_v1'],
            system_errors={
                'zone_matchup_v1': 'No zone matchup data available',
                'similarity_balanced_v1': 'Insufficient historical games'
            },
            feature_quality_score=0.82,
            historical_games_count=7,
            performance_breakdown={
                'data_load': 0.4,
                'prediction_compute': 1.3,
                'write_bigquery': 0.2,
                'pubsub_publish': 0.2
            }
        )

        row = bq_client.inserted_rows[0]

        # Verify comprehensive logging
        assert row['success'] is True
        assert row['predictions_generated'] == 2
        assert len(row['systems_succeeded']) == 3
        assert len(row['systems_failed']) == 2
        assert 'zone_matchup_v1' in row['system_errors']
        assert row['feature_quality_score'] == 0.82

    def test_complete_failure_scenario(self):
        """Test complete failure with all systems failed"""
        bq_client = MockBigQueryClient()
        logger = ExecutionLogger(bq_client, 'test-project')

        logger.log_failure(
            player_lookup='Donovan Mitchell',
            universal_player_id='player-1515',
            game_date='2024-11-20',
            game_id='game-456',
            line_values=[27.5],
            duration_seconds=0.8,
            error_message='All prediction systems failed',
            error_type='RuntimeError',
            systems_attempted=[
                'moving_average',
                'zone_matchup_v1',
                'similarity_balanced_v1',
                'xgboost_v1',
                'ensemble_v1'
            ],
            systems_failed=[
                'moving_average',
                'zone_matchup_v1',
                'similarity_balanced_v1',
                'xgboost_v1',
                'ensemble_v1'
            ],
            circuit_breaker_triggered=True,
            circuits_opened=['moving_average', 'xgboost_v1']
        )

        row = bq_client.inserted_rows[0]

        assert row['success'] is False
        assert row['predictions_generated'] == 0
        assert len(row['systems_failed']) == 5
        assert row['circuit_breaker_triggered'] is True
        assert len(row['circuits_opened']) == 2


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
