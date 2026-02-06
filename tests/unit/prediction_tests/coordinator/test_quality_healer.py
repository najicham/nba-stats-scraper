# tests/unit/prediction_tests/coordinator/test_quality_healer.py
"""
Unit tests for QualityHealer (Session 139)

Tests:
- Heal attempt triggers Phase 4 processors
- Max 1 heal attempt per batch (Firestore dedup)
- Non-fatal on failure
- Firestore tracking
"""

import pytest
from datetime import date
from unittest.mock import MagicMock, patch, PropertyMock

from predictions.coordinator.quality_healer import (
    QualityHealer,
    HealResult,
    MAX_HEAL_ATTEMPTS_PER_BATCH,
    HEAL_TIMEOUT_SECONDS,
)


class TestHealResult:
    """Tests for HealResult dataclass."""

    def test_default_values(self):
        result = HealResult(attempted=True, success=True, processors_triggered=['A'])
        assert result.error is None
        assert result.elapsed_seconds == 0.0


class TestQualityHealer:
    """Tests for QualityHealer."""

    @pytest.fixture
    def healer(self):
        healer = QualityHealer(project_id='test-project')
        # Mock Firestore
        mock_fs = MagicMock()
        healer._firestore_client = mock_fs
        return healer

    def test_no_processors_returns_not_attempted(self, healer):
        result = healer.attempt_heal(
            game_date=date(2026, 2, 6),
            batch_id='batch_123',
            missing_processors=[],
        )
        assert result.attempted is False
        assert result.success is False

    def test_already_healed_returns_not_attempted(self, healer):
        # Mock Firestore doc exists with attempt_count >= 1
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {'attempt_count': 1}
        healer._firestore_client.collection.return_value.document.return_value.get.return_value = mock_doc

        result = healer.attempt_heal(
            game_date=date(2026, 2, 6),
            batch_id='batch_123',
            missing_processors=['PlayerCompositeFactorsProcessor'],
        )
        assert result.attempted is False
        assert 'Already healed' in result.error

    @patch('predictions.coordinator.quality_healer.QualityHealer._trigger_phase4_processors')
    def test_successful_heal(self, mock_trigger, healer):
        # Mock Firestore: no prior attempt
        mock_doc = MagicMock()
        mock_doc.exists = False
        healer._firestore_client.collection.return_value.document.return_value.get.return_value = mock_doc

        mock_trigger.return_value = True

        result = healer.attempt_heal(
            game_date=date(2026, 2, 6),
            batch_id='batch_123',
            missing_processors=['PlayerCompositeFactorsProcessor'],
        )

        assert result.attempted is True
        assert result.success is True
        assert 'PlayerCompositeFactorsProcessor' in result.processors_triggered

        # Should have triggered Phase 4 twice: once for missing processor, once for MLFeatureStore
        assert mock_trigger.call_count == 2

    @patch('predictions.coordinator.quality_healer.QualityHealer._trigger_phase4_processors')
    def test_failed_heal(self, mock_trigger, healer):
        # Mock Firestore: no prior attempt
        mock_doc = MagicMock()
        mock_doc.exists = False
        healer._firestore_client.collection.return_value.document.return_value.get.return_value = mock_doc

        mock_trigger.return_value = False

        result = healer.attempt_heal(
            game_date=date(2026, 2, 6),
            batch_id='batch_123',
            missing_processors=['PlayerCompositeFactorsProcessor'],
        )

        assert result.attempted is True
        assert result.success is False

    @patch('predictions.coordinator.quality_healer.QualityHealer._trigger_phase4_processors')
    def test_heal_exception_non_fatal(self, mock_trigger, healer):
        # Mock Firestore: no prior attempt
        mock_doc = MagicMock()
        mock_doc.exists = False
        healer._firestore_client.collection.return_value.document.return_value.get.return_value = mock_doc

        mock_trigger.side_effect = Exception("Connection refused")

        result = healer.attempt_heal(
            game_date=date(2026, 2, 6),
            batch_id='batch_123',
            missing_processors=['PlayerCompositeFactorsProcessor'],
        )

        assert result.attempted is True
        assert result.success is False
        assert 'Connection refused' in result.error

    @patch('predictions.coordinator.quality_healer.QualityHealer._trigger_phase4_processors')
    def test_ml_feature_store_not_double_triggered(self, mock_trigger, healer):
        """If MLFeatureStoreProcessor is already in the list, don't trigger twice."""
        mock_doc = MagicMock()
        mock_doc.exists = False
        healer._firestore_client.collection.return_value.document.return_value.get.return_value = mock_doc

        mock_trigger.return_value = True

        result = healer.attempt_heal(
            game_date=date(2026, 2, 6),
            batch_id='batch_123',
            missing_processors=['MLFeatureStoreProcessor'],
        )

        assert result.success is True
        # Should only trigger once since MLFeatureStoreProcessor is already in the list
        assert mock_trigger.call_count == 1

    def test_firestore_check_failure_allows_heal(self, healer):
        """If Firestore check fails, allow the heal attempt."""
        healer._firestore_client.collection.return_value.document.return_value.get.side_effect = Exception("Firestore down")

        # Should not raise, should return False from _already_healed
        assert healer._already_healed('batch_123') is False


class TestQualityHealerConstants:
    """Tests for module-level constants."""

    def test_max_attempts_is_one(self):
        assert MAX_HEAL_ATTEMPTS_PER_BATCH == 1

    def test_timeout_is_300(self):
        assert HEAL_TIMEOUT_SECONDS == 300
