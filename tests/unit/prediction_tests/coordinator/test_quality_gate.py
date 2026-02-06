# tests/unit/prediction_tests/coordinator/test_quality_gate.py
"""
Unit tests for Quality Gate System (Session 139 Overhaul)

Tests:
- Hard floor: red alerts and matchup_quality < 50% always blocked
- LAST_CALL no longer forces at 0% (now 70%)
- BACKFILL mode parsing and threshold
- Missing processor diagnosis
- No forced_no_features or forced_last_call escape hatches
- Quality distribution tracking
"""

import pytest
from datetime import date
from unittest.mock import MagicMock, patch

from predictions.coordinator.quality_gate import (
    QualityGate,
    QualityGateResult,
    QualityGateSummary,
    PredictionMode,
    QUALITY_THRESHOLDS,
    HARD_FLOOR_MATCHUP_QUALITY,
    HARD_FLOOR_ALERT_LEVELS,
    parse_prediction_mode,
    _diagnose_missing_processor,
)


class TestPredictionMode:
    """Tests for PredictionMode enum and thresholds."""

    def test_backfill_mode_exists(self):
        assert PredictionMode.BACKFILL.value == "BACKFILL"

    def test_last_call_threshold_is_70(self):
        """Session 139: LAST_CALL threshold changed from 0% to 70%."""
        assert QUALITY_THRESHOLDS[PredictionMode.LAST_CALL] == 70.0

    def test_backfill_threshold_is_70(self):
        assert QUALITY_THRESHOLDS[PredictionMode.BACKFILL] == 70.0

    def test_first_threshold(self):
        assert QUALITY_THRESHOLDS[PredictionMode.FIRST] == 85.0

    def test_retry_threshold(self):
        assert QUALITY_THRESHOLDS[PredictionMode.RETRY] == 85.0

    def test_final_retry_threshold(self):
        assert QUALITY_THRESHOLDS[PredictionMode.FINAL_RETRY] == 80.0


class TestParsePredictionMode:
    """Tests for parse_prediction_mode."""

    def test_parse_backfill(self):
        assert parse_prediction_mode("BACKFILL") == PredictionMode.BACKFILL

    def test_parse_backfill_lowercase(self):
        assert parse_prediction_mode("backfill") == PredictionMode.BACKFILL

    def test_parse_last_call(self):
        assert parse_prediction_mode("LAST_CALL") == PredictionMode.LAST_CALL

    def test_parse_legacy_early(self):
        assert parse_prediction_mode("EARLY") == PredictionMode.FIRST

    def test_parse_legacy_overnight(self):
        assert parse_prediction_mode("OVERNIGHT") == PredictionMode.RETRY

    def test_parse_unknown_defaults_retry(self):
        assert parse_prediction_mode("UNKNOWN_MODE") == PredictionMode.RETRY


class TestDiagnoseMissingProcessor:
    """Tests for _diagnose_missing_processor."""

    def test_matchup_zero_returns_composite(self):
        details = {'matchup_quality_pct': 0, 'quality_alert_level': 'red'}
        assert _diagnose_missing_processor(details) == 'PlayerCompositeFactorsProcessor'

    def test_matchup_low_returns_composite(self):
        details = {'matchup_quality_pct': 25, 'quality_alert_level': 'red'}
        assert _diagnose_missing_processor(details) == 'PlayerCompositeFactorsProcessor'

    def test_red_alert_good_matchup_returns_feature_store(self):
        details = {'matchup_quality_pct': 80, 'quality_alert_level': 'red'}
        assert _diagnose_missing_processor(details) == 'MLFeatureStoreProcessor'

    def test_green_alert_good_matchup_returns_none(self):
        details = {'matchup_quality_pct': 90, 'quality_alert_level': 'green'}
        assert _diagnose_missing_processor(details) is None

    def test_yellow_alert_good_matchup_returns_none(self):
        details = {'matchup_quality_pct': 75, 'quality_alert_level': 'yellow'}
        assert _diagnose_missing_processor(details) is None


class TestHardFloor:
    """Tests for the hard floor blocking logic (Session 139 core feature)."""

    def test_hard_floor_constants(self):
        assert HARD_FLOOR_MATCHUP_QUALITY == 50.0
        assert HARD_FLOOR_ALERT_LEVELS == {'red'}


class TestQualityGateApply:
    """Tests for QualityGate.apply_quality_gate with mocked BigQuery."""

    @pytest.fixture
    def gate(self):
        """Create a QualityGate with mocked BQ client."""
        gate = QualityGate(project_id='test-project', dataset_prefix='test_')
        gate._bq_client = MagicMock()
        return gate

    def _mock_quality_gate(self, gate, existing_preds, quality_scores, quality_details):
        """Helper to mock both get_existing_predictions and get_feature_quality_scores."""
        gate.get_existing_predictions = MagicMock(return_value=existing_preds)
        gate.get_feature_quality_scores = MagicMock(return_value=quality_scores)
        gate._quality_details = quality_details

    def test_hard_floor_blocks_red_alert_in_last_call(self, gate):
        """Session 139: Red alerts blocked even in LAST_CALL mode."""
        players = ['player-a']
        self._mock_quality_gate(
            gate,
            existing_preds={},
            quality_scores={'player-a': 75.0},
            quality_details={'player-a': {
                'is_quality_ready': False,
                'quality_alert_level': 'red',
                'matchup_quality_pct': 0,
            }},
        )

        results, summary = gate.apply_quality_gate(date(2026, 2, 6), players, PredictionMode.LAST_CALL)

        assert len(results) == 1
        assert results[0].should_predict is False
        assert results[0].hard_floor_blocked is True
        assert results[0].reason == 'hard_floor_red_alert'
        assert summary.players_hard_blocked == 1
        assert summary.players_to_predict == 0

    def test_hard_floor_blocks_low_matchup_in_last_call(self, gate):
        """Session 139: matchup_quality < 50% blocked even in LAST_CALL mode."""
        players = ['player-a']
        self._mock_quality_gate(
            gate,
            existing_preds={},
            quality_scores={'player-a': 80.0},
            quality_details={'player-a': {
                'is_quality_ready': False,
                'quality_alert_level': 'yellow',
                'matchup_quality_pct': 30,
            }},
        )

        results, summary = gate.apply_quality_gate(date(2026, 2, 6), players, PredictionMode.LAST_CALL)

        assert results[0].should_predict is False
        assert results[0].hard_floor_blocked is True
        assert 'hard_floor_matchup' in results[0].reason

    def test_hard_floor_blocks_no_features(self, gate):
        """Session 139: No features = hard blocked (no more LAST_CALL forcing)."""
        players = ['player-a']
        self._mock_quality_gate(
            gate,
            existing_preds={},
            quality_scores={},  # No feature data
            quality_details={},
        )

        results, summary = gate.apply_quality_gate(date(2026, 2, 6), players, PredictionMode.LAST_CALL)

        assert results[0].should_predict is False
        assert results[0].hard_floor_blocked is True
        assert results[0].reason == 'no_features_available'

    def test_last_call_no_longer_forces_low_quality(self, gate):
        """Session 139: LAST_CALL with quality < 70% is NOT forced anymore."""
        players = ['player-a']
        self._mock_quality_gate(
            gate,
            existing_preds={},
            quality_scores={'player-a': 60.0},
            quality_details={'player-a': {
                'is_quality_ready': False,
                'quality_alert_level': 'yellow',
                'matchup_quality_pct': 65,
            }},
        )

        results, summary = gate.apply_quality_gate(date(2026, 2, 6), players, PredictionMode.LAST_CALL)

        # Quality 60% < threshold 70% -> should NOT predict
        assert results[0].should_predict is False
        assert results[0].forced_prediction is False
        assert 'quality_below_threshold' in results[0].reason

    def test_last_call_allows_quality_above_70(self, gate):
        """LAST_CALL allows predictions with quality >= 70% and good matchup."""
        players = ['player-a']
        self._mock_quality_gate(
            gate,
            existing_preds={},
            quality_scores={'player-a': 75.0},
            quality_details={'player-a': {
                'is_quality_ready': True,
                'quality_alert_level': 'yellow',
                'matchup_quality_pct': 70,
            }},
        )

        results, summary = gate.apply_quality_gate(date(2026, 2, 6), players, PredictionMode.LAST_CALL)

        assert results[0].should_predict is True
        assert results[0].reason == 'quality_sufficient'

    def test_existing_prediction_skipped(self, gate):
        """Existing predictions are always skipped."""
        players = ['player-a']
        self._mock_quality_gate(
            gate,
            existing_preds={'player-a': True},
            quality_scores={'player-a': 90.0},
            quality_details={'player-a': {
                'is_quality_ready': True,
                'quality_alert_level': 'green',
                'matchup_quality_pct': 100,
            }},
        )

        results, summary = gate.apply_quality_gate(date(2026, 2, 6), players, PredictionMode.FIRST)

        assert results[0].should_predict is False
        assert results[0].reason == 'already_has_prediction'
        assert summary.players_skipped_existing == 1

    def test_high_quality_passes_first_mode(self, gate):
        """High quality passes in FIRST mode."""
        players = ['player-a']
        self._mock_quality_gate(
            gate,
            existing_preds={},
            quality_scores={'player-a': 90.0},
            quality_details={'player-a': {
                'is_quality_ready': True,
                'quality_alert_level': 'green',
                'matchup_quality_pct': 95,
            }},
        )

        results, summary = gate.apply_quality_gate(date(2026, 2, 6), players, PredictionMode.FIRST)

        assert results[0].should_predict is True
        assert results[0].low_quality_flag is False
        assert results[0].forced_prediction is False

    def test_below_threshold_skipped_in_first_mode(self, gate):
        """Quality below 85% is skipped in FIRST mode."""
        players = ['player-a']
        self._mock_quality_gate(
            gate,
            existing_preds={},
            quality_scores={'player-a': 80.0},
            quality_details={'player-a': {
                'is_quality_ready': True,
                'quality_alert_level': 'green',
                'matchup_quality_pct': 90,
            }},
        )

        results, summary = gate.apply_quality_gate(date(2026, 2, 6), players, PredictionMode.FIRST)

        assert results[0].should_predict is False
        assert 'quality_below_threshold' in results[0].reason

    def test_mixed_batch_summary(self, gate):
        """Test summary stats for a mixed batch of players."""
        players = ['good', 'existing', 'red_alert', 'low_quality']
        self._mock_quality_gate(
            gate,
            existing_preds={'existing': True},
            quality_scores={
                'good': 90.0,
                'existing': 90.0,
                'red_alert': 50.0,
                'low_quality': 70.0,
            },
            quality_details={
                'good': {'is_quality_ready': True, 'quality_alert_level': 'green', 'matchup_quality_pct': 95},
                'existing': {'is_quality_ready': True, 'quality_alert_level': 'green', 'matchup_quality_pct': 95},
                'red_alert': {'is_quality_ready': False, 'quality_alert_level': 'red', 'matchup_quality_pct': 10},
                'low_quality': {'is_quality_ready': False, 'quality_alert_level': 'yellow', 'matchup_quality_pct': 80},
            },
        )

        results, summary = gate.apply_quality_gate(date(2026, 2, 6), players, PredictionMode.FIRST)

        assert summary.total_players == 4
        assert summary.players_to_predict == 1  # good
        assert summary.players_skipped_existing == 1  # existing
        assert summary.players_hard_blocked == 1  # red_alert
        # low_quality: 70% < 85% threshold -> skipped
        assert summary.players_skipped_low_quality == 2  # red_alert + low_quality

    def test_missing_processor_diagnosed_in_summary(self, gate):
        """Summary includes diagnosed missing processors."""
        players = ['player-a', 'player-b']
        self._mock_quality_gate(
            gate,
            existing_preds={},
            quality_scores={'player-a': 40.0, 'player-b': 40.0},
            quality_details={
                'player-a': {'is_quality_ready': False, 'quality_alert_level': 'red', 'matchup_quality_pct': 0},
                'player-b': {'is_quality_ready': False, 'quality_alert_level': 'red', 'matchup_quality_pct': 0},
            },
        )

        results, summary = gate.apply_quality_gate(date(2026, 2, 6), players, PredictionMode.RETRY)

        assert 'PlayerCompositeFactorsProcessor' in summary.missing_processors
        assert summary.players_hard_blocked == 2

    def test_backfill_mode_threshold(self, gate):
        """BACKFILL mode uses 70% threshold."""
        players = ['player-a']
        self._mock_quality_gate(
            gate,
            existing_preds={},
            quality_scores={'player-a': 72.0},
            quality_details={'player-a': {
                'is_quality_ready': True,
                'quality_alert_level': 'green',
                'matchup_quality_pct': 80,
            }},
        )

        results, summary = gate.apply_quality_gate(date(2026, 2, 6), players, PredictionMode.BACKFILL)

        assert results[0].should_predict is True
        assert results[0].reason == 'quality_sufficient'

    def test_no_forced_predictions_counter(self, gate):
        """Session 139: forced counter should always be 0 (no more forcing)."""
        players = ['player-a']
        self._mock_quality_gate(
            gate,
            existing_preds={},
            quality_scores={'player-a': 90.0},
            quality_details={'player-a': {
                'is_quality_ready': True,
                'quality_alert_level': 'green',
                'matchup_quality_pct': 95,
            }},
        )

        results, summary = gate.apply_quality_gate(date(2026, 2, 6), players, PredictionMode.LAST_CALL)

        assert summary.players_forced == 0


class TestQualityGateResultDataclass:
    """Tests for QualityGateResult default values."""

    def test_hard_floor_blocked_default(self):
        result = QualityGateResult(
            player_lookup='test',
            should_predict=True,
            reason='test',
            feature_quality_score=90.0,
            has_existing_prediction=False,
            low_quality_flag=False,
            forced_prediction=False,
            prediction_attempt='FIRST',
        )
        assert result.hard_floor_blocked is False
        assert result.missing_processor is None


class TestQualityGateSummaryDataclass:
    """Tests for QualityGateSummary default values."""

    def test_new_fields_default(self):
        summary = QualityGateSummary(
            total_players=10,
            players_to_predict=8,
            players_skipped_existing=1,
            players_skipped_low_quality=1,
            players_forced=0,
            avg_quality_score=85.0,
            quality_distribution={'high_85plus': 8, 'medium_80_85': 1, 'low_below_80': 1},
        )
        assert summary.players_hard_blocked == 0
        assert summary.missing_processors == []
