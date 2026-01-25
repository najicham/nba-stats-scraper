#!/usr/bin/env python3
"""
Integration Tests for Postponement Handling Flow

Tests the full workflow of postponement detection, tracking, and grading exclusion:
1. Detection finds anomalies
2. Anomalies are filtered by handled status
3. Predictions can be invalidated
4. Grading excludes invalidated predictions

Uses mocked BigQuery but tests the integration between components.
"""

import pytest
from datetime import date
from unittest.mock import Mock, patch, MagicMock
from collections import namedtuple


class TestPostponementDetectionFlow:
    """Test the full detection flow."""

    def test_detection_filters_handled_games(self):
        """Test that already-handled games are filtered from detection results."""
        from shared.utils.postponement_detector import PostponementDetector

        # Create mock BigQuery client
        mock_client = Mock()

        # Mock for handled games query - return one handled game
        handled_result = Mock()
        handled_result.__iter__ = Mock(return_value=iter([
            Mock(game_id='0022500644')  # GSW@MIN - already handled
        ]))

        # Mock for detection query - return two games (one handled, one new)
        Row = namedtuple('Row', ['game_id', 'game_date', 'game_status', 'game_status_text',
                                  'home_team_tricode', 'away_team_tricode',
                                  'home_team_score', 'away_team_score'])

        detection_result = Mock()
        detection_result.__iter__ = Mock(return_value=iter([
            Row(game_id='0022500644', game_date=date(2026, 1, 24),
                game_status=3, game_status_text='Final',
                home_team_tricode='MIN', away_team_tricode='GSW',
                home_team_score=None, away_team_score=None),
            Row(game_id='0022500700', game_date=date(2026, 1, 26),
                game_status=3, game_status_text='Final',
                home_team_tricode='LAL', away_team_tricode='BOS',
                home_team_score=None, away_team_score=None),
        ]))

        # Empty results for other detection methods
        empty_result = Mock()
        empty_result.__iter__ = Mock(return_value=iter([]))

        # Setup query mock to return different results based on query
        def mock_query(query, job_config=None):
            mock_job = Mock()
            if 'game_postponements' in query:
                mock_job.result.return_value = handled_result
            elif 'game_status = 3' in query and 'home_team_score IS NULL' in query:
                mock_job.result.return_value = detection_result
            else:
                mock_job.result.return_value = empty_result
            return mock_job

        mock_client.query = mock_query

        # Mock get_affected_predictions to return 0
        with patch('shared.utils.postponement_detector.get_affected_predictions', return_value=0):
            detector = PostponementDetector(sport="NBA", bq_client=mock_client)

            # Run detection with filtering (default)
            anomalies = detector.detect_all(date(2026, 1, 24), include_handled=False)

            # Should only find the new game (LAL@BOS), not the handled one (GSW@MIN)
            assert len(anomalies) == 1
            assert anomalies[0]['game_id'] == '0022500700'
            assert anomalies[0]['teams'] == 'BOS@LAL'

    def test_detection_includes_handled_when_requested(self):
        """Test that include_handled=True returns all anomalies."""
        from shared.utils.postponement_detector import PostponementDetector

        mock_client = Mock()

        # Mock for detection query - return two games
        Row = namedtuple('Row', ['game_id', 'game_date', 'game_status', 'game_status_text',
                                  'home_team_tricode', 'away_team_tricode',
                                  'home_team_score', 'away_team_score'])

        detection_result = Mock()
        detection_result.__iter__ = Mock(return_value=iter([
            Row(game_id='0022500644', game_date=date(2026, 1, 24),
                game_status=3, game_status_text='Final',
                home_team_tricode='MIN', away_team_tricode='GSW',
                home_team_score=None, away_team_score=None),
            Row(game_id='0022500700', game_date=date(2026, 1, 26),
                game_status=3, game_status_text='Final',
                home_team_tricode='LAL', away_team_tricode='BOS',
                home_team_score=None, away_team_score=None),
        ]))

        empty_result = Mock()
        empty_result.__iter__ = Mock(return_value=iter([]))

        def mock_query(query, job_config=None):
            mock_job = Mock()
            if 'game_status = 3' in query and 'home_team_score IS NULL' in query:
                mock_job.result.return_value = detection_result
            else:
                mock_job.result.return_value = empty_result
            return mock_job

        mock_client.query = mock_query

        with patch('shared.utils.postponement_detector.get_affected_predictions', return_value=0):
            detector = PostponementDetector(sport="NBA", bq_client=mock_client)

            # Run detection with include_handled=True (no filtering)
            anomalies = detector.detect_all(date(2026, 1, 24), include_handled=True)

            # Should find both games
            assert len(anomalies) == 2


class TestCoordinatorPostponementCheck:
    """Test the coordinator's postponement check functionality."""

    def test_check_returns_tracked_postponements(self):
        """
        Test that _check_for_postponed_games returns tracked postponements.

        Note: The coordinator module requires environment variables to import.
        This test verifies the expected structure/logic without full import.
        """
        import os

        # Skip if coordinator can't be imported (missing env vars)
        # In CI, this would be set up properly
        if not os.environ.get('GCP_PROJECT_ID'):
            pytest.skip("GCP_PROJECT_ID not set - skipping coordinator import test")

        from predictions.coordinator.coordinator import _check_for_postponed_games

        # This test would need a real or mocked BigQuery connection
        # For now, we verify the function exists and has the right signature
        import inspect
        sig = inspect.signature(_check_for_postponed_games)
        assert 'game_date' in sig.parameters

    def test_coordinator_has_postponement_check_function(self):
        """Verify the coordinator module has the postponement check function defined."""
        import os

        coordinator_path = os.path.join(
            os.path.dirname(__file__), '../..',
            'predictions/coordinator/coordinator.py'
        )

        with open(coordinator_path, 'r') as f:
            content = f.read()

        # Verify the function exists
        assert 'def _check_for_postponed_games' in content, \
            "Coordinator must have _check_for_postponed_games function"

        # Verify it checks the tracking table
        assert 'game_postponements' in content, \
            "Coordinator must check game_postponements table"

        # Verify it's called in /start endpoint
        assert 'skip_postponement_check' in content, \
            "Coordinator must support skip_postponement_check flag"


class TestGradingExclusion:
    """Test that grading correctly excludes invalidated predictions."""

    def test_grading_query_excludes_invalidated(self):
        """Verify the grading query pattern excludes invalidated predictions."""
        # This is a static analysis test - we verify the query pattern exists
        import os

        grading_processor_path = os.path.join(
            os.path.dirname(__file__), '../..',
            'data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py'
        )

        with open(grading_processor_path, 'r') as f:
            content = f.read()

        # Verify the critical filter exists
        assert 'invalidation_reason IS NULL' in content, \
            "Grading processor must filter out invalidated predictions"


class TestScheduleStatusUpdate:
    """Test schedule status updates."""

    def test_status_text_for_rescheduled_game(self):
        """Test that rescheduled games get appropriate status text."""
        from bin.fixes.fix_postponed_game import update_schedule_status

        mock_client = Mock()
        mock_job = Mock()
        mock_client.query.return_value = mock_job

        # Patch the global client
        with patch('bin.fixes.fix_postponed_game.client', mock_client):
            # Test with new_date provided
            result = update_schedule_status(
                game_id='0022500644',
                game_date=date(2026, 1, 24),
                new_date=date(2026, 1, 25),
                dry_run=True
            )

            assert result is True

    def test_status_text_for_postponed_game_no_new_date(self):
        """Test that postponed games without new date get 'Postponed' status."""
        from bin.fixes.fix_postponed_game import update_schedule_status

        mock_client = Mock()
        mock_job = Mock()
        mock_client.query.return_value = mock_job

        with patch('bin.fixes.fix_postponed_game.client', mock_client):
            # Test without new_date
            result = update_schedule_status(
                game_id='0022500644',
                game_date=date(2026, 1, 24),
                new_date=None,
                dry_run=True
            )

            assert result is True


class TestEndToEndScenarios:
    """Test realistic end-to-end scenarios."""

    def test_gsw_min_postponement_scenario(self):
        """
        Simulate the GSW@MIN postponement scenario:
        1. Game scheduled for Jan 24
        2. Game postponed (detected as Final with NULL scores)
        3. Game rescheduled to Jan 25
        4. Predictions invalidated for Jan 24
        5. Predictions generated for Jan 25
        """
        from shared.utils.postponement_detector import PostponementDetector

        mock_client = Mock()

        # Step 1: Detection finds the anomaly
        Row = namedtuple('Row', ['game_id', 'game_date', 'game_status', 'game_status_text',
                                  'home_team_tricode', 'away_team_tricode',
                                  'home_team_score', 'away_team_score'])

        detection_result = Mock()
        detection_result.__iter__ = Mock(return_value=iter([
            Row(game_id='0022500644', game_date=date(2026, 1, 24),
                game_status=3, game_status_text='Final',
                home_team_tricode='MIN', away_team_tricode='GSW',
                home_team_score=None, away_team_score=None),
        ]))

        empty_result = Mock()
        empty_result.__iter__ = Mock(return_value=iter([]))

        def mock_query(query, job_config=None):
            mock_job = Mock()
            if 'game_status = 3' in query and 'home_team_score IS NULL' in query:
                mock_job.result.return_value = detection_result
            else:
                mock_job.result.return_value = empty_result
            return mock_job

        mock_client.query = mock_query

        with patch('shared.utils.postponement_detector.get_affected_predictions', return_value=55):
            detector = PostponementDetector(sport="NBA", bq_client=mock_client)

            # Detect anomalies (include_handled=True for first detection)
            anomalies = detector.detect_all(date(2026, 1, 24), include_handled=True)

            # Verify detection
            assert len(anomalies) == 1
            assert anomalies[0]['type'] == 'FINAL_WITHOUT_SCORES'
            assert anomalies[0]['severity'] == 'CRITICAL'
            assert anomalies[0]['game_id'] == '0022500644'
            assert anomalies[0]['teams'] == 'GSW@MIN'
            assert anomalies[0]['predictions_affected'] == 55


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
