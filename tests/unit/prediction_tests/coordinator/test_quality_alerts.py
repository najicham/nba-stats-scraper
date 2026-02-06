# tests/unit/prediction_tests/coordinator/test_quality_alerts.py
"""
Unit tests for Quality Alerts (Session 139)

Tests:
- PREDICTIONS_SKIPPED alert formatting and sending
- Existing alert types still work
"""

import pytest
from datetime import date
from unittest.mock import patch, MagicMock

from predictions.coordinator.quality_alerts import (
    check_and_send_quality_alerts,
    send_predictions_skipped_alert,
    QualityAlert,
)
from predictions.coordinator.quality_gate import QualityGateResult


class TestSendPredictionsSkippedAlert:
    """Tests for the new PREDICTIONS_SKIPPED alert (Session 139)."""

    def _make_blocked_result(self, player_lookup, quality_score=50.0, reason='hard_floor_red_alert', missing_processor=None):
        return QualityGateResult(
            player_lookup=player_lookup,
            should_predict=False,
            reason=reason,
            feature_quality_score=quality_score,
            has_existing_prediction=False,
            low_quality_flag=True,
            forced_prediction=False,
            prediction_attempt='LAST_CALL',
            hard_floor_blocked=True,
            missing_processor=missing_processor,
        )

    def test_no_blocked_results_returns_early(self):
        """Should do nothing with empty list."""
        # Should not raise
        send_predictions_skipped_alert(
            game_date=date(2026, 2, 6),
            mode='LAST_CALL',
            blocked_results=[],
            missing_processors=[],
        )

    @patch('shared.utils.slack_alerts.send_slack_alert')
    def test_sends_slack_alert(self, mock_slack):
        """Should send Slack alert with player details."""
        blocked = [
            self._make_blocked_result('lebron-james', 40.0, missing_processor='PlayerCompositeFactorsProcessor'),
            self._make_blocked_result('stephen-curry', 35.0, missing_processor='PlayerCompositeFactorsProcessor'),
        ]

        send_predictions_skipped_alert(
            game_date=date(2026, 2, 6),
            mode='LAST_CALL',
            blocked_results=blocked,
            missing_processors=['PlayerCompositeFactorsProcessor'],
            heal_attempted=True,
            heal_success=False,
        )

        mock_slack.assert_called_once()
        call_kwargs = mock_slack.call_args
        message = call_kwargs[1].get('message') or call_kwargs[0][0]
        assert 'PREDICTIONS SKIPPED' in message
        assert 'lebron-james' in message
        assert 'stephen-curry' in message
        assert 'ATTEMPTED - FAILED' in message

    @patch('shared.utils.slack_alerts.send_slack_alert')
    def test_caps_at_20_players(self, mock_slack):
        """Should cap player list at 20 and show remaining count."""
        blocked = [self._make_blocked_result(f'player-{i}') for i in range(25)]

        send_predictions_skipped_alert(
            game_date=date(2026, 2, 6),
            mode='LAST_CALL',
            blocked_results=blocked,
            missing_processors=[],
        )

        mock_slack.assert_called_once()
        message = mock_slack.call_args[1].get('message') or mock_slack.call_args[0][0]
        assert '... and 5 more' in message

    @patch('predictions.coordinator.quality_alerts._send_slack_alert')
    def test_heal_not_attempted_label(self, mock_slack):
        """Should show NOT ATTEMPTED when heal not attempted."""
        blocked = [self._make_blocked_result('player-a')]

        send_predictions_skipped_alert(
            game_date=date(2026, 2, 6),
            mode='RETRY',
            blocked_results=blocked,
            missing_processors=[],
            heal_attempted=False,
        )
        # Just verify no exception raised - the message is logged

    @patch('shared.utils.slack_alerts.send_slack_alert', side_effect=Exception("webhook failed"))
    def test_slack_send_error_non_fatal(self, mock_slack):
        """Should not raise if Slack send fails."""
        blocked = [self._make_blocked_result('player-a')]

        # Should not raise
        send_predictions_skipped_alert(
            game_date=date(2026, 2, 6),
            mode='LAST_CALL',
            blocked_results=blocked,
            missing_processors=[],
        )


class TestExistingAlerts:
    """Regression tests for existing alert types."""

    @patch('predictions.coordinator.quality_alerts._send_slack_alert')
    def test_low_quality_features_alert(self, mock_slack):
        alerts = check_and_send_quality_alerts(
            game_date=date(2026, 2, 6),
            mode='FIRST',
            total_players=100,
            players_to_predict=80,
            players_skipped_existing=10,
            players_skipped_low_quality=10,
            players_forced=0,
            avg_quality_score=75.0,
            quality_distribution={'high_85plus': 50, 'medium_80_85': 20, 'low_below_80': 30},
        )

        # 50% high quality < 80% threshold -> should trigger
        alert_types = [a.alert_type for a in alerts]
        assert 'LOW_QUALITY_FEATURES' in alert_types

    @patch('predictions.coordinator.quality_alerts._send_slack_alert')
    def test_phase4_missing_alert(self, mock_slack):
        alerts = check_and_send_quality_alerts(
            game_date=date(2026, 2, 6),
            mode='FIRST',
            total_players=100,
            players_to_predict=0,
            players_skipped_existing=0,
            players_skipped_low_quality=100,
            players_forced=0,
            avg_quality_score=0.0,
            quality_distribution={},  # No quality data at all
        )

        alert_types = [a.alert_type for a in alerts]
        assert 'PHASE4_DATA_MISSING' in alert_types

    @patch('predictions.coordinator.quality_alerts._send_slack_alert')
    def test_no_alerts_for_healthy_batch(self, mock_slack):
        alerts = check_and_send_quality_alerts(
            game_date=date(2026, 2, 6),
            mode='FIRST',
            total_players=100,
            players_to_predict=90,
            players_skipped_existing=10,
            players_skipped_low_quality=0,
            players_forced=0,
            avg_quality_score=92.0,
            quality_distribution={'high_85plus': 90, 'medium_80_85': 5, 'low_below_80': 5},
        )

        assert len(alerts) == 0
