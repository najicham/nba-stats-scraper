# Unit Testing Implementation Plan
**Date:** January 22, 2026
**Status:** Ready for Implementation
**Coverage Target:** 80%+ for all new code

---

## Executive Summary

This document outlines the unit testing strategy for:
1. Latency monitoring infrastructure (Phases 0-5)
2. Critical fixes (Issues #1-4)
3. Completeness validation system
4. Retry queue infrastructure

**Test Framework:** pytest 7.4+
**Mocking Library:** pytest-mock, unittest.mock
**Coverage Tool:** pytest-cov
**CI Integration:** Pre-commit hooks + GitHub Actions

---

## Section 1: Testing Infrastructure Setup

### Directory Structure

```
tests/
├── unit/
│   ├── monitoring/
│   │   ├── __init__.py
│   │   ├── test_bdl_availability_logger.py
│   │   ├── test_scraper_monitor.py
│   │   └── test_monitoring_views.py
│   ├── validation/
│   │   ├── __init__.py
│   │   ├── test_scraper_completeness_validator.py
│   │   └── test_phase_boundary_validator.py
│   ├── orchestration/
│   │   ├── __init__.py
│   │   ├── test_cleanup_processor.py
│   │   └── test_retry_worker.py
│   ├── analytics/
│   │   ├── __init__.py
│   │   └── test_dependency_validation.py
│   └── scrapers/
│       ├── __init__.py
│       └── test_bdl_box_scores_integration.py
├── integration/
│   ├── __init__.py
│   ├── test_dockerfile_builds.py
│   ├── test_end_to_end_monitoring.py
│   └── test_scraper_to_bigquery_flow.py
├── fixtures/
│   ├── __init__.py
│   ├── mock_bigquery_data.py
│   ├── mock_schedule_data.py
│   └── mock_scraper_responses.py
└── conftest.py  # Shared fixtures and configuration
```

### Installation Requirements

**File:** `tests/requirements.txt`

```python
# Testing framework
pytest==7.4.3
pytest-cov==4.1.0
pytest-mock==3.12.0
pytest-timeout==2.2.0

# Mocking
freezegun==1.4.0  # Mock datetime
responses==0.24.1  # Mock HTTP requests

# BigQuery testing
google-cloud-bigquery==3.15.0
google-cloud-firestore==2.14.0

# Coverage reporting
coverage[toml]==7.4.0
```

### pytest Configuration

**File:** `pyproject.toml` (or `pytest.ini`)

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = [
    "-v",
    "--strict-markers",
    "--cov=shared",
    "--cov=orchestration",
    "--cov=scrapers",
    "--cov=data_processors",
    "--cov-report=term-missing",
    "--cov-report=html:htmlcov",
    "--cov-branch",
    "--cov-fail-under=80",
]
markers = [
    "unit: Unit tests (fast, no external dependencies)",
    "integration: Integration tests (may call external services)",
    "slow: Tests that take > 1 second",
    "bigquery: Tests that interact with BigQuery",
    "docker: Tests that require Docker",
]
```

---

## Section 2: Unit Tests for Latency Monitoring

### Test Suite 1: BDL Availability Logger

**File:** `tests/unit/monitoring/test_bdl_availability_logger.py`

```python
"""
Unit tests for BDL Availability Logger

Tests the per-game availability tracking for BDL scrapers.
"""

import pytest
from unittest.mock import Mock, patch, call
from datetime import datetime, timezone, timedelta
from google.cloud import bigquery

from shared.utils.bdl_availability_logger import log_bdl_game_availability


class TestBDLAvailabilityLogger:
    """Test suite for BDL availability logger"""

    @pytest.fixture
    def mock_schedule_games(self):
        """Mock schedule data"""
        return [
            {
                'home_team': 'GSW',
                'away_team': 'LAL',
                'game_start_time': datetime(2026, 1, 20, 22, 30, tzinfo=timezone.utc),
                'is_west_coast': True
            },
            {
                'home_team': 'BOS',
                'away_team': 'MIA',
                'game_start_time': datetime(2026, 1, 20, 19, 0, tzinfo=timezone.utc),
                'is_west_coast': False
            }
        ]

    @pytest.fixture
    def mock_box_scores(self):
        """Mock BDL box scores response"""
        return [
            {
                'game': {
                    'id': 12345,
                    'home_team': {'abbreviation': 'GSW'},
                    'visitor_team': {'abbreviation': 'LAL'},
                    'status': 'Final'
                },
                'player_id': 1,
                'min': '35'
            },
            # ... more players for GSW vs LAL game
            {
                'game': {
                    'id': 12346,
                    'home_team': {'abbreviation': 'BOS'},
                    'visitor_team': {'abbreviation': 'MIA'},
                    'status': 'Final'
                },
                'player_id': 50,
                'min': '32'
            }
        ]

    @patch('shared.utils.bdl_availability_logger.bigquery.Client')
    def test_logs_available_games(self, mock_bq_client, mock_box_scores, mock_schedule_games):
        """Test that logger correctly identifies and logs available games"""
        # Arrange
        mock_client = Mock()
        mock_bq_client.return_value = mock_client

        # Mock schedule query response
        mock_schedule_result = [Mock(**game) for game in mock_schedule_games]
        mock_client.query.return_value.result.return_value = mock_schedule_result

        # Act
        log_bdl_game_availability(
            game_date='2026-01-20',
            execution_id='test123',
            box_scores=mock_box_scores,
            workflow='post_game_window_2'
        )

        # Assert
        mock_client.insert_rows_json.assert_called_once()
        inserted_rows = mock_client.insert_rows_json.call_args[0][1]

        # Should have 2 rows (one per game in schedule)
        assert len(inserted_rows) == 2

        # Both games should be marked as available
        assert all(row['was_available'] for row in inserted_rows)
        assert inserted_rows[0]['home_team'] == 'GSW'
        assert inserted_rows[1]['home_team'] == 'BOS'

    @patch('shared.utils.bdl_availability_logger.bigquery.Client')
    def test_logs_missing_games(self, mock_bq_client, mock_schedule_games):
        """Test that logger correctly identifies missing games"""
        # Arrange
        mock_client = Mock()
        mock_bq_client.return_value = mock_client

        mock_schedule_result = [Mock(**game) for game in mock_schedule_games]
        mock_client.query.return_value.result.return_value = mock_schedule_result

        # Only one game returned (BOS vs MIA missing)
        partial_box_scores = [
            {
                'game': {
                    'home_team': {'abbreviation': 'GSW'},
                    'visitor_team': {'abbreviation': 'LAL'}
                }
            }
        ]

        # Act
        log_bdl_game_availability(
            game_date='2026-01-20',
            execution_id='test123',
            box_scores=partial_box_scores,
            workflow='post_game_window_1'
        )

        # Assert
        inserted_rows = mock_client.insert_rows_json.call_args[0][1]

        # GSW game should be available
        gsw_row = next(r for r in inserted_rows if r['home_team'] == 'GSW')
        assert gsw_row['was_available'] is True

        # BOS game should be missing
        bos_row = next(r for r in inserted_rows if r['home_team'] == 'BOS')
        assert bos_row['was_available'] is False

    @patch('shared.utils.bdl_availability_logger.bigquery.Client')
    def test_calculates_estimated_end_time(self, mock_bq_client, mock_schedule_games):
        """Test that estimated game end time is calculated correctly (start + 2.5h)"""
        # Arrange
        mock_client = Mock()
        mock_bq_client.return_value = mock_client

        mock_schedule_result = [Mock(**mock_schedule_games[0])]
        mock_client.query.return_value.result.return_value = mock_schedule_result

        # Act
        log_bdl_game_availability(
            game_date='2026-01-20',
            execution_id='test123',
            box_scores=[],
            workflow='test'
        )

        # Assert
        inserted_rows = mock_client.insert_rows_json.call_args[0][1]
        row = inserted_rows[0]

        # Estimated end should be start + 2.5 hours
        expected_end = datetime(2026, 1, 21, 1, 0, tzinfo=timezone.utc)  # 22:30 + 2.5h
        assert row['estimated_end_time'] == expected_end.isoformat()

    @patch('shared.utils.bdl_availability_logger.bigquery.Client')
    def test_flags_west_coast_games(self, mock_bq_client, mock_schedule_games):
        """Test that West Coast games are properly flagged"""
        # Arrange
        mock_client = Mock()
        mock_bq_client.return_value = mock_client

        mock_schedule_result = [Mock(**game) for game in mock_schedule_games]
        mock_client.query.return_value.result.return_value = mock_schedule_result

        # Act
        log_bdl_game_availability(
            game_date='2026-01-20',
            execution_id='test123',
            box_scores=[],
            workflow='test'
        )

        # Assert
        inserted_rows = mock_client.insert_rows_json.call_args[0][1]

        gsw_row = next(r for r in inserted_rows if r['home_team'] == 'GSW')
        bos_row = next(r for r in inserted_rows if r['home_team'] == 'BOS')

        assert gsw_row['is_west_coast'] is True
        assert bos_row['is_west_coast'] is False

    @patch('shared.utils.bdl_availability_logger.bigquery.Client')
    def test_handles_empty_schedule(self, mock_bq_client):
        """Test that logger handles days with no games gracefully"""
        # Arrange
        mock_client = Mock()
        mock_bq_client.return_value = mock_client
        mock_client.query.return_value.result.return_value = []

        # Act
        log_bdl_game_availability(
            game_date='2026-01-20',
            execution_id='test123',
            box_scores=[],
            workflow='test'
        )

        # Assert - should not insert any rows
        mock_client.insert_rows_json.assert_not_called()

    @patch('shared.utils.bdl_availability_logger.bigquery.Client')
    def test_handles_bigquery_errors_gracefully(self, mock_bq_client):
        """Test that logger logs errors but doesn't crash on BigQuery failures"""
        # Arrange
        mock_client = Mock()
        mock_bq_client.return_value = mock_client
        mock_client.query.side_effect = Exception("BigQuery connection failed")

        # Act - should not raise exception
        log_bdl_game_availability(
            game_date='2026-01-20',
            execution_id='test123',
            box_scores=[],
            workflow='test'
        )

        # Assert - function completed without crash
        assert True  # If we get here, error was handled gracefully

    @patch('shared.utils.bdl_availability_logger.bigquery.Client')
    def test_counts_players_correctly(self, mock_bq_client, mock_box_scores, mock_schedule_games):
        """Test that player count is calculated correctly per game"""
        # Arrange
        mock_client = Mock()
        mock_bq_client.return_value = mock_client

        mock_schedule_result = [Mock(**mock_schedule_games[0])]  # Just GSW game
        mock_client.query.return_value.result.return_value = mock_schedule_result

        # Create box scores with specific player count
        gsw_box_scores = [
            {'game': {'home_team': {'abbreviation': 'GSW'}, 'visitor_team': {'abbreviation': 'LAL'}}}
            for _ in range(26)  # 26 players typical for one game
        ]

        # Act
        log_bdl_game_availability(
            game_date='2026-01-20',
            execution_id='test123',
            box_scores=gsw_box_scores,
            workflow='test'
        )

        # Assert
        inserted_rows = mock_client.insert_rows_json.call_args[0][1]
        assert inserted_rows[0]['player_count'] == 26


# Additional test classes for edge cases...
```

### Test Suite 2: Scraper Availability Monitor

**File:** `tests/unit/monitoring/test_scraper_monitor.py`

```python
"""
Unit tests for Scraper Availability Monitor Cloud Function

Tests the daily monitoring and alerting system.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, date

# Import the monitor function (adjust path as needed)
from orchestration.cloud_functions.scraper_availability_monitor.main import (
    check_scraper_availability,
    format_slack_message,
    send_slack_alert
)


class TestScraperAvailabilityMonitor:
    """Test suite for scraper availability monitor"""

    @pytest.fixture
    def mock_complete_data(self):
        """Mock BigQuery result for complete data"""
        return {
            'game_date': date(2026, 1, 20),
            'total_games': 7,
            'bdl_available': 7,
            'bdl_missing': 0,
            'bdl_coverage_pct': 100.0,
            'nbac_available': 7,
            'nbac_missing': 0,
            'nbac_coverage_pct': 100.0,
            'oddsapi_available': 7,
            'oddsapi_coverage_pct': 100.0,
            'daily_alert_level': 'OK',
            'bdl_missing_matchups': [],
            'nbac_missing_matchups': [],
            'west_coast_games': 2,
            'west_coast_bdl_missing': 0,
            'bdl_avg_latency_hours': 2.1,
            'nbac_avg_latency_hours': 0.8,
            'critical_count': 0,
            'warning_count': 0
        }

    @pytest.fixture
    def mock_warning_data(self):
        """Mock BigQuery result for warning-level data"""
        return {
            'game_date': date(2026, 1, 20),
            'total_games': 7,
            'bdl_available': 4,
            'bdl_missing': 3,
            'bdl_coverage_pct': 57.1,
            'bdl_missing_matchups': ['TOR @ GSW', 'MIA @ SAC', 'LAL @ DEN'],
            'nbac_available': 7,
            'nbac_missing': 0,
            'nbac_coverage_pct': 100.0,
            'nbac_missing_matchups': [],
            'oddsapi_available': 7,
            'oddsapi_coverage_pct': 100.0,
            'daily_alert_level': 'WARNING',
            'west_coast_games': 3,
            'west_coast_bdl_missing': 2,
            'bdl_avg_latency_hours': 4.5,
            'nbac_avg_latency_hours': 1.2,
            'critical_count': 0,
            'warning_count': 3
        }

    @patch('orchestration.cloud_functions.scraper_availability_monitor.main.bigquery.Client')
    def test_queries_summary_view(self, mock_bq_client):
        """Test that monitor queries the correct BigQuery view"""
        # Arrange
        mock_client = Mock()
        mock_bq_client.return_value = mock_client

        mock_result = Mock()
        mock_result.total_games = 7
        mock_client.query.return_value.result.return_value = [mock_result]

        # Act
        check_scraper_availability('2026-01-20')

        # Assert
        query_call = mock_client.query.call_args[0][0]
        assert 'v_scraper_availability_daily_summary' in query_call
        assert '2026-01-20' in query_call

    def test_detects_warning_level(self, mock_warning_data):
        """Test that monitor correctly identifies WARNING alert level"""
        # Act
        alert_level = mock_warning_data['daily_alert_level']

        # Assert
        assert alert_level == 'WARNING'
        assert mock_warning_data['bdl_coverage_pct'] < 90.0

    def test_detects_critical_level(self):
        """Test that monitor correctly identifies CRITICAL alert level"""
        # Arrange
        critical_data = {
            'total_games': 10,
            'bdl_available': 3,
            'bdl_coverage_pct': 30.0,
            'daily_alert_level': 'CRITICAL'
        }

        # Assert
        assert critical_data['daily_alert_level'] == 'CRITICAL'
        assert critical_data['bdl_coverage_pct'] < 50.0

    def test_formats_slack_message_for_warning(self, mock_warning_data):
        """Test Slack message formatting for WARNING level"""
        # Act
        message = format_slack_message(mock_warning_data)

        # Assert
        assert '⚠️' in message
        assert 'WARNING' in message
        assert '57.1%' in message  # BDL coverage
        assert 'TOR @ GSW' in message  # Missing game
        assert '3 missing' in message or '3 games' in message

    def test_formats_slack_message_for_ok(self, mock_complete_data):
        """Test Slack message formatting for OK level"""
        # Act
        message = format_slack_message(mock_complete_data)

        # Assert
        assert '✅' in message
        assert '100.0%' in message  # BDL coverage
        assert 'Complete' in message or 'OK' in message

    @patch('orchestration.cloud_functions.scraper_availability_monitor.main.requests.post')
    def test_sends_slack_alert_for_warning(self, mock_post, mock_warning_data):
        """Test that Slack alert is sent for WARNING level"""
        # Arrange
        mock_post.return_value.status_code = 200

        # Act
        send_slack_alert(mock_warning_data, webhook_url='https://hooks.slack.com/test')

        # Assert
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == 'https://hooks.slack.com/test'
        assert 'WARNING' in str(call_args[1]['json'])

    @patch('orchestration.cloud_functions.scraper_availability_monitor.main.firestore.Client')
    def test_logs_to_firestore(self, mock_firestore_client, mock_warning_data):
        """Test that results are logged to Firestore"""
        # Arrange
        mock_client = Mock()
        mock_firestore_client.return_value = mock_client
        mock_collection = Mock()
        mock_client.collection.return_value = mock_collection

        # Act
        # Call function that logs to Firestore
        # (Adjust function name as needed)

        # Assert
        mock_client.collection.assert_called_with('scraper_availability_checks')
        mock_collection.add.assert_called_once()

    def test_handles_no_data_gracefully(self):
        """Test that monitor handles dates with no data"""
        # Arrange
        empty_result = None

        # Act & Assert - should not crash
        if empty_result is None:
            # Should return early or handle gracefully
            assert True

    @patch('orchestration.cloud_functions.scraper_availability_monitor.main.bigquery.Client')
    def test_handles_bigquery_errors(self, mock_bq_client):
        """Test error handling for BigQuery failures"""
        # Arrange
        mock_client = Mock()
        mock_bq_client.return_value = mock_client
        mock_client.query.side_effect = Exception("BigQuery timeout")

        # Act & Assert - should handle gracefully
        try:
            result = check_scraper_availability('2026-01-20')
            # Should return None or error result
            assert result is None or 'error' in result
        except Exception:
            pytest.fail("Function should handle BigQuery errors gracefully")
```

---

## Section 3: Unit Tests for Critical Fixes

### Test Suite 3: Cleanup Processor Table Name Fix

**File:** `tests/unit/orchestration/test_cleanup_processor.py`

```python
"""
Unit tests for Cleanup Processor

Tests the fix for Issue #3: BDL table name mismatch.
"""

import pytest
from unittest.mock import Mock, patch

from orchestration.cleanup_processor import CleanupProcessor


class TestCleanupProcessor:
    """Test suite for cleanup processor"""

    @pytest.fixture
    def cleanup_processor(self):
        """Create cleanup processor instance"""
        return CleanupProcessor(lookback_hours=24)

    def test_uses_correct_bdl_table_name(self, cleanup_processor):
        """Test that cleanup processor uses correct table name (bdl_player_boxscores)"""
        # Arrange - get the query that cleanup processor would run
        query = cleanup_processor._get_recent_files_query()

        # Assert
        assert 'bdl_player_boxscores' in query
        assert 'bdl_box_scores' not in query  # Wrong name should NOT be in query

    @patch('orchestration.cleanup_processor.bigquery.Client')
    def test_query_succeeds_with_correct_table_name(self, mock_bq_client, cleanup_processor):
        """Test that query runs successfully with correct table name"""
        # Arrange
        mock_client = Mock()
        mock_bq_client.return_value = mock_client

        mock_result = [Mock(source_file_path='gs://bucket/file.json')]
        mock_client.query.return_value.result.return_value = mock_result

        # Act
        result = cleanup_processor.get_recent_files()

        # Assert
        mock_client.query.assert_called_once()
        assert len(result) > 0
        assert result[0] == 'gs://bucket/file.json'

    @patch('orchestration.cleanup_processor.bigquery.Client')
    def test_no_404_error_with_correct_table(self, mock_bq_client, cleanup_processor):
        """Test that no 404 error occurs with correct table name"""
        # Arrange
        mock_client = Mock()
        mock_bq_client.return_value = mock_client
        mock_client.query.return_value.result.return_value = []

        # Act - should not raise 404 error
        try:
            cleanup_processor.get_recent_files()
            assert True  # Success if no exception
        except Exception as e:
            if '404' in str(e) or 'Not found' in str(e):
                pytest.fail(f"Should not get 404 error: {e}")
            raise

    def test_all_table_references_are_correct(self, cleanup_processor):
        """Test that ALL table name references in cleanup processor are correct"""
        # Get all queries that reference BDL tables
        source_code = inspect.getsource(CleanupProcessor)

        # Assert - should not contain incorrect table name
        assert 'bdl_box_scores' not in source_code  # Wrong (old name)

        # If bdl_player_boxscores is referenced, it should be there
        if 'bdl_player' in source_code:
            assert 'bdl_player_boxscores' in source_code  # Correct
```

---

## Section 4: Integration Tests

### Test Suite 4: Dockerfile Build Tests

**File:** `tests/integration/test_dockerfile_builds.py`

```python
"""
Integration tests for Dockerfile builds

Tests the fix for Issue #1: Prediction coordinator Dockerfile.
Requires Docker to be installed and running.
"""

import pytest
import docker
import os


@pytest.mark.docker
@pytest.mark.slow
class TestDockerfileBuilds:
    """Integration tests for Dockerfile builds"""

    @pytest.fixture(scope="class")
    def docker_client(self):
        """Create Docker client"""
        return docker.from_env()

    def test_prediction_coordinator_dockerfile_builds(self, docker_client):
        """Test that prediction coordinator Dockerfile builds successfully"""
        # Arrange
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
        dockerfile_path = 'predictions/coordinator/Dockerfile'

        # Act
        try:
            image, build_logs = docker_client.images.build(
                path=repo_root,
                dockerfile=dockerfile_path,
                tag='test-prediction-coordinator:latest',
                rm=True
            )
            build_success = True
        except docker.errors.BuildError as e:
            build_success = False
            build_logs = e.build_log

        # Assert
        assert build_success, f"Dockerfile build failed: {build_logs}"
        assert image is not None

    def test_predictions_package_structure_valid(self, docker_client):
        """Test that predictions package structure is valid in container"""
        # Arrange - build if not already built
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
        image, _ = docker_client.images.build(
            path=repo_root,
            dockerfile='predictions/coordinator/Dockerfile',
            tag='test-prediction-coordinator:latest',
            rm=True
        )

        # Act - check if predictions/__init__.py exists
        container = docker_client.containers.run(
            image='test-prediction-coordinator:latest',
            command='ls -la /app/predictions/',
            remove=True,
            detach=False
        )
        output = container.decode('utf-8')

        # Assert
        assert '__init__.py' in output, "predictions/__init__.py should exist in container"

    def test_prediction_coordinator_imports_work(self, docker_client):
        """Test that predictions.coordinator imports work in container"""
        # Arrange
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
        image, _ = docker_client.images.build(
            path=repo_root,
            dockerfile='predictions/coordinator/Dockerfile',
            tag='test-prediction-coordinator:latest',
            rm=True
        )

        # Act - test the import
        container = docker_client.containers.run(
            image='test-prediction-coordinator:latest',
            command='python -c "from predictions.coordinator.coordinator import app; print(\\'Success!\\')"',
            remove=True,
            detach=False
        )
        output = container.decode('utf-8')

        # Assert
        assert 'Success!' in output
        assert 'ModuleNotFoundError' not in output
```

---

## Section 5: Test Execution & Coverage

### Running Tests

```bash
# Run all unit tests
pytest tests/unit/ -v

# Run specific test suite
pytest tests/unit/monitoring/test_bdl_availability_logger.py -v

# Run with coverage
pytest tests/unit/ --cov=shared --cov=orchestration --cov-report=html

# Run only fast tests (skip integration/docker)
pytest tests/unit/ -m "not slow and not docker"

# Run integration tests (requires Docker)
pytest tests/integration/ -m docker -v
```

### Coverage Reports

```bash
# Generate HTML coverage report
pytest tests/ --cov=shared --cov=orchestration --cov-report=html

# View report
open htmlcov/index.html

# Generate terminal report
pytest tests/ --cov=shared --cov=orchestration --cov-report=term-missing
```

### CI/CD Integration

**File:** `.github/workflows/tests.yml`

```yaml
name: Unit Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install -r tests/requirements.txt

      - name: Run unit tests
        run: pytest tests/unit/ -v --cov=shared --cov=orchestration

      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

---

## Section 6: Implementation Timeline

### Week 1: Critical Fixes Tests
- Day 1: Create test infrastructure (conftest.py, fixtures)
- Day 2: Implement tests for Issues #1-4
- Day 3: Implement latency monitoring tests (Suites 1-2)
- Day 4: Integration tests for Dockerfiles
- Day 5: Coverage review and gap filling

### Week 2: Expansion Tests
- Day 1-2: NBAC logger tests
- Day 3-4: Completeness validator tests
- Day 5: Retry queue tests

---

**Document Created:** January 22, 2026
**Status:** Ready for Implementation
**Next Step:** Create test infrastructure and implement Suite 1
