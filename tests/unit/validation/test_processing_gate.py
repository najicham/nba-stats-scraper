"""
Unit Tests for ProcessingGate

Tests the unified processing gate that prevents cascade contamination
by checking completeness before allowing processing.

Created: 2026-01-26
"""

import pytest
from datetime import date, datetime, timedelta
from unittest.mock import Mock, patch

from shared.validation.processing_gate import (
    ProcessingGate,
    GateStatus,
    GateResult,
    ProcessingBlockedError
)


class TestProcessingGate:
    """Test suite for ProcessingGate."""

    @pytest.fixture
    def mock_bq_client(self):
        """Mock BigQuery client."""
        return Mock()

    @pytest.fixture
    def mock_completeness_checker(self):
        """Mock CompletenessChecker."""
        return Mock()

    @pytest.fixture
    def gate(self, mock_bq_client, mock_completeness_checker):
        """Create ProcessingGate with mocked dependencies."""
        with patch('shared.validation.processing_gate.CompletenessChecker',
                   return_value=mock_completeness_checker):
            gate = ProcessingGate(
                bq_client=mock_bq_client,
                project_id='test-project',
                min_completeness=0.8,
                grace_period_hours=36,
                window_completeness_threshold=0.7
            )
            return gate

    def test_check_can_process_proceed(self, gate, mock_completeness_checker):
        """Test gate returns PROCEED for 100% complete data."""
        # Mock 100% completeness
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
                'actual_count': 10,
                'completeness_pct': 100.0,
                'is_complete': True,
                'dnp_count': 0
            }
        }

        result = gate.check_can_process(
            processor_name='TestProcessor',
            game_date=date(2026, 1, 26),
            entity_ids=['player1', 'player2'],
            window_size=10
        )

        assert result.status == GateStatus.PROCEED
        assert result.can_proceed is True
        assert result.quality_score == 1.0
        assert result.completeness_pct == 100.0
        assert len(result.missing_items) == 0

    def test_check_can_process_proceed_with_warning(self, gate, mock_completeness_checker):
        """Test gate returns PROCEED_WITH_WARNING for 80-99% complete data."""
        # Mock 85% completeness (above min threshold)
        mock_completeness_checker.check_completeness_batch.return_value = {
            'player1': {
                'expected_count': 10,
                'actual_count': 9,
                'completeness_pct': 90.0,
                'is_complete': False,
                'dnp_count': 0
            },
            'player2': {
                'expected_count': 10,
                'actual_count': 8,
                'completeness_pct': 80.0,
                'is_complete': False,
                'dnp_count': 0
            }
        }

        result = gate.check_can_process(
            processor_name='TestProcessor',
            game_date=date(2026, 1, 26),
            entity_ids=['player1', 'player2'],
            window_size=10
        )

        assert result.status == GateStatus.PROCEED_WITH_WARNING
        assert result.can_proceed is True
        assert result.quality_score == 0.85  # Average of 90% and 80%
        assert result.completeness_pct == 85.0
        assert len(result.missing_items) == 2

    def test_check_can_process_wait(self, gate, mock_completeness_checker):
        """Test gate returns WAIT for incomplete data within grace period."""
        # Mock 70% completeness for recent game (within grace period)
        mock_completeness_checker.check_completeness_batch.return_value = {
            'player1': {
                'expected_count': 10,
                'actual_count': 7,
                'completeness_pct': 70.0,
                'is_complete': False,
                'dnp_count': 0
            }
        }

        # Test with recent date (within 36 hour grace period)
        recent_date = date.today() - timedelta(hours=12)

        result = gate.check_can_process(
            processor_name='TestProcessor',
            game_date=recent_date,
            entity_ids=['player1'],
            window_size=10
        )

        assert result.status == GateStatus.WAIT
        assert result.can_proceed is False

    def test_check_can_process_fail(self, gate, mock_completeness_checker):
        """Test gate returns FAIL for incomplete data past grace period."""
        # Mock 70% completeness for old game (past grace period)
        mock_completeness_checker.check_completeness_batch.return_value = {
            'player1': {
                'expected_count': 10,
                'actual_count': 7,
                'completeness_pct': 70.0,
                'is_complete': False,
                'dnp_count': 0
            }
        }

        # Test with old date (past grace period)
        old_date = date.today() - timedelta(days=5)

        result = gate.check_can_process(
            processor_name='TestProcessor',
            game_date=old_date,
            entity_ids=['player1'],
            window_size=10
        )

        assert result.status == GateStatus.FAIL
        assert result.can_proceed is False
        assert result.quality_score < 0.8

    def test_check_can_process_with_override(self, gate, mock_completeness_checker):
        """Test gate can be bypassed with allow_override."""
        # Don't even mock completeness checker - should not be called

        result = gate.check_can_process(
            processor_name='TestProcessor',
            game_date=date(2026, 1, 26),
            entity_ids=['player1'],
            window_size=10,
            allow_override=True
        )

        assert result.status == GateStatus.PROCEED
        assert result.can_proceed is True
        assert result.quality_metadata['gate_status'] == 'bypassed'
        mock_completeness_checker.check_completeness_batch.assert_not_called()

    def test_check_can_process_error_handling(self, gate, mock_completeness_checker):
        """Test gate handles completeness check errors gracefully."""
        # Mock completeness checker raising error
        mock_completeness_checker.check_completeness_batch.side_effect = \
            Exception("BigQuery timeout")

        result = gate.check_can_process(
            processor_name='TestProcessor',
            game_date=date(2026, 1, 26),
            entity_ids=['player1'],
            window_size=10
        )

        assert result.status == GateStatus.FAIL
        assert result.can_proceed is False
        assert 'error' in result.message.lower()
        assert result.quality_score == 0.0

    def test_check_can_process_with_dnp_awareness(self, gate, mock_completeness_checker):
        """Test gate respects DNP-aware completeness."""
        # Mock completeness with DNP games excluded
        mock_completeness_checker.check_completeness_batch.return_value = {
            'player1': {
                'expected_count': 10,
                'actual_count': 8,
                'completeness_pct': 100.0,  # 100% after DNP adjustment
                'is_complete': True,
                'dnp_count': 2,  # 2 games were DNP
                'gap_classification': 'NO_GAP'
            }
        }

        result = gate.check_can_process(
            processor_name='TestProcessor',
            game_date=date(2026, 1, 26),
            entity_ids=['player1'],
            window_size=10
        )

        assert result.status == GateStatus.PROCEED
        assert result.can_proceed is True
        assert result.quality_score == 1.0

    def test_determine_gate_status_thresholds(self, gate):
        """Test gate status determination logic."""
        # 100% complete -> PROCEED
        status = gate._determine_gate_status(1.0, hours_since_game=48)
        assert status == GateStatus.PROCEED

        # 90% complete, past grace -> PROCEED_WITH_WARNING
        status = gate._determine_gate_status(0.9, hours_since_game=48)
        assert status == GateStatus.PROCEED_WITH_WARNING

        # 70% complete, within grace -> WAIT
        status = gate._determine_gate_status(0.7, hours_since_game=12)
        assert status == GateStatus.WAIT

        # 70% complete, past grace -> FAIL
        status = gate._determine_gate_status(0.7, hours_since_game=48)
        assert status == GateStatus.FAIL

    def test_determine_processing_context(self, gate):
        """Test processing context determination."""
        game_date = date(2026, 1, 20)

        # Recent (< 48 hours) -> daily
        context = gate._determine_processing_context(game_date, hours_since_game=24)
        assert context == 'daily'

        # 3 days ago -> cascade
        context = gate._determine_processing_context(game_date, hours_since_game=72)
        assert context == 'cascade'

        # 10 days ago -> backfill
        context = gate._determine_processing_context(game_date, hours_since_game=240)
        assert context == 'backfill'

    def test_quality_metadata_structure(self, gate, mock_completeness_checker):
        """Test quality metadata structure in result."""
        mock_completeness_checker.check_completeness_batch.return_value = {
            'player1': {
                'expected_count': 10,
                'actual_count': 10,
                'completeness_pct': 100.0,
                'is_complete': True,
                'dnp_count': 0
            }
        }

        result = gate.check_can_process(
            processor_name='TestProcessor',
            game_date=date(2026, 1, 26),
            entity_ids=['player1'],
            window_size=10
        )

        metadata = result.quality_metadata
        assert 'gate_status' in metadata
        assert 'gate_timestamp' in metadata
        assert 'gate_processor' in metadata
        assert 'quality_score' in metadata
        assert 'completeness_pct' in metadata
        assert 'window_size' in metadata
        assert 'window_type' in metadata
        assert 'processing_context' in metadata

        assert metadata['gate_status'] == 'proceed'
        assert metadata['gate_processor'] == 'TestProcessor'
        assert metadata['window_size'] == 10


class TestProcessingBlockedError:
    """Test ProcessingBlockedError exception."""

    def test_exception_with_gate_result(self):
        """Test exception carries gate result."""
        gate_result = GateResult(
            status=GateStatus.FAIL,
            can_proceed=False,
            quality_score=0.5,
            message="Insufficient data",
            completeness_pct=50.0,
            expected_count=10,
            actual_count=5
        )

        error = ProcessingBlockedError("Processing blocked", gate_result=gate_result)

        assert error.message == "Processing blocked"
        assert error.gate_result == gate_result
        assert error.gate_result.status == GateStatus.FAIL

    def test_exception_without_gate_result(self):
        """Test exception can be raised without gate result."""
        error = ProcessingBlockedError("Processing blocked")

        assert error.message == "Processing blocked"
        assert error.gate_result is None
