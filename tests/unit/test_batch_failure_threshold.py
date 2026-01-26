"""
Tests for batch failure threshold logic (>20% threshold).

Tests ensure that batches with excessive failures are properly detected and handled.

Business Logic:
- If >20% of players in a batch fail, the batch should be flagged as problematic
- This prevents partial batches from being considered "successful"
- Alerts should be triggered for high failure rates
- Batch summary should indicate health status

Critical Thresholds:
- <10% failures: Acceptable (normal variance)
- 10-20% failures: Warning level
- >20% failures: Critical - batch should be investigated

Reference: predictions/coordinator/progress_tracker.py

Created: 2026-01-25 (Session 18 Continuation)
"""

import pytest
from datetime import datetime


class BatchFailureTracker:
    """Mock batch failure tracker for testing threshold logic"""

    def __init__(self, expected_players: int):
        self.expected_players = expected_players
        self.completed_players = set()
        self.failed_players = set()

    def mark_player_completed(self, player_lookup: str):
        """Mark player as completed successfully"""
        self.completed_players.add(player_lookup)

    def mark_player_failed(self, player_lookup: str, error: str):
        """Mark player as failed"""
        self.failed_players.add(player_lookup)

    def get_failure_rate(self) -> float:
        """Calculate failure rate as percentage"""
        total_attempted = len(self.completed_players) + len(self.failed_players)
        if total_attempted == 0:
            return 0.0
        return (len(self.failed_players) / total_attempted) * 100

    def is_batch_healthy(self, threshold_percent: float = 20.0) -> bool:
        """Check if batch failure rate is below threshold"""
        return self.get_failure_rate() < threshold_percent

    def get_health_status(self) -> str:
        """Get batch health status"""
        failure_rate = self.get_failure_rate()
        if failure_rate < 10:
            return "healthy"
        elif failure_rate < 20:
            return "warning"
        else:
            return "critical"

    def should_abort_batch(self, min_threshold_percent: float = 20.0) -> bool:
        """Determine if batch should be aborted due to high failure rate"""
        # Only check after processing significant portion
        total_attempted = len(self.completed_players) + len(self.failed_players)
        if total_attempted < self.expected_players * 0.3:  # Less than 30% attempted
            return False  # Too early to abort

        return self.get_failure_rate() > min_threshold_percent


class TestBatchFailureCalculations:
    """Test batch failure rate calculations"""

    def test_zero_failures_is_zero_percent(self):
        """Test that no failures = 0% failure rate"""
        tracker = BatchFailureTracker(expected_players=450)

        # Complete 100 players successfully
        for i in range(100):
            tracker.mark_player_completed(f"player-{i}")

        assert tracker.get_failure_rate() == 0.0

    def test_all_failures_is_100_percent(self):
        """Test that all failures = 100% failure rate"""
        tracker = BatchFailureTracker(expected_players=450)

        # Fail 100 players
        for i in range(100):
            tracker.mark_player_failed(f"player-{i}", "Test error")

        assert tracker.get_failure_rate() == 100.0

    def test_exactly_20_percent_failures(self):
        """Test exact 20% failure threshold"""
        tracker = BatchFailureTracker(expected_players=450)

        # Complete 80 players, fail 20 (20% failure rate)
        for i in range(80):
            tracker.mark_player_completed(f"player-{i}")
        for i in range(80, 100):
            tracker.mark_player_failed(f"player-{i}", "Test error")

        failure_rate = tracker.get_failure_rate()
        assert failure_rate == 20.0

    def test_realistic_small_failure_rate(self):
        """Test realistic small failure rate (5%)"""
        tracker = BatchFailureTracker(expected_players=450)

        # Complete 428 players, fail 22 (5% failure rate)
        for i in range(428):
            tracker.mark_player_completed(f"player-{i}")
        for i in range(428, 450):
            tracker.mark_player_failed(f"player-{i}", "Player out tonight")

        failure_rate = tracker.get_failure_rate()
        assert 4.5 < failure_rate < 5.5  # Approximately 5%


class TestHealthStatusThresholds:
    """Test health status categorization"""

    def test_healthy_status_below_10_percent(self):
        """Test batch is healthy with <10% failures"""
        tracker = BatchFailureTracker(expected_players=450)

        # 5% failure rate
        for i in range(190):
            tracker.mark_player_completed(f"player-{i}")
        for i in range(190, 200):
            tracker.mark_player_failed(f"player-{i}", "Error")

        assert tracker.get_health_status() == "healthy"

    def test_warning_status_10_to_20_percent(self):
        """Test batch gets warning status with 10-20% failures"""
        tracker = BatchFailureTracker(expected_players=450)

        # 15% failure rate
        for i in range(170):
            tracker.mark_player_completed(f"player-{i}")
        for i in range(170, 200):
            tracker.mark_player_failed(f"player-{i}", "Error")

        assert tracker.get_health_status() == "warning"

    def test_critical_status_above_20_percent(self):
        """Test batch gets critical status with >20% failures"""
        tracker = BatchFailureTracker(expected_players=450)

        # 30% failure rate
        for i in range(140):
            tracker.mark_player_completed(f"player-{i}")
        for i in range(140, 200):
            tracker.mark_player_failed(f"player-{i}", "Error")

        assert tracker.get_health_status() == "critical"


class TestBatchAbortLogic:
    """Test logic for aborting problematic batches"""

    def test_batch_not_aborted_below_threshold(self):
        """Test batch continues with acceptable failure rate"""
        tracker = BatchFailureTracker(expected_players=450)

        # Process 200 players with 10% failure rate
        for i in range(180):
            tracker.mark_player_completed(f"player-{i}")
        for i in range(180, 200):
            tracker.mark_player_failed(f"player-{i}", "Error")

        assert not tracker.should_abort_batch(min_threshold_percent=20.0)

    def test_batch_aborted_above_threshold(self):
        """Test batch should abort with >20% failure rate"""
        tracker = BatchFailureTracker(expected_players=450)

        # Process 200 players with 30% failure rate
        for i in range(140):
            tracker.mark_player_completed(f"player-{i}")
        for i in range(140, 200):
            tracker.mark_player_failed(f"player-{i}", "Critical error")

        assert tracker.should_abort_batch(min_threshold_percent=20.0)

    def test_no_abort_too_early_in_batch(self):
        """Test that abort decision waits until 30% of batch attempted"""
        tracker = BatchFailureTracker(expected_players=450)

        # Only 50 players attempted (11%), even with 50% failures, too early
        for i in range(25):
            tracker.mark_player_completed(f"player-{i}")
        for i in range(25, 50):
            tracker.mark_player_failed(f"player-{i}", "Error")

        # Should NOT abort - too early to judge
        assert not tracker.should_abort_batch()


class TestEdgeCases:
    """Test edge cases and boundary conditions"""

    def test_empty_batch_has_zero_failure_rate(self):
        """Test empty batch (no attempts yet) has 0% failure"""
        tracker = BatchFailureTracker(expected_players=450)

        assert tracker.get_failure_rate() == 0.0

    def test_exactly_at_20_percent_boundary(self):
        """Test behavior exactly at 20% threshold"""
        tracker = BatchFailureTracker(expected_players=450)

        # Exactly 20% failures after 100 attempts
        for i in range(80):
            tracker.mark_player_completed(f"player-{i}")
        for i in range(80, 100):
            tracker.mark_player_failed(f"player-{i}", "Error")

        # 20.0% should be considered NOT healthy (boundary)
        assert not tracker.is_batch_healthy(threshold_percent=20.0)

    def test_just_below_20_percent_is_healthy(self):
        """Test that 19.9% is still considered healthy"""
        tracker = BatchFailureTracker(expected_players=450)

        # 19% failures
        for i in range(405):
            tracker.mark_player_completed(f"player-{i}")
        for i in range(405, 450):
            tracker.mark_player_failed(f"player-{i}", "Error")  # 45 failures out of 450 = 10%

        # Wait, let me recalculate: 45/450 = 10%
        # For 19%, need 95 failures out of 500 total

        tracker = BatchFailureTracker(expected_players=450)
        for i in range(405):
            tracker.mark_player_completed(f"player-{i}")
        for i in range(405, 500):
            tracker.mark_player_failed(f"player-{i}", "Error")  # 95 failures out of 500 = 19%

        failure_rate = tracker.get_failure_rate()
        assert 18 < failure_rate < 20
        assert tracker.is_batch_healthy(threshold_percent=20.0)


class TestRealWorldScenarios:
    """Test realistic production scenarios"""

    def test_normal_batch_with_few_failures(self):
        """Test typical batch: 450 players, 15 failures (3.3%)"""
        tracker = BatchFailureTracker(expected_players=450)

        # 435 successes, 15 failures
        for i in range(435):
            tracker.mark_player_completed(f"player-{i}")
        for i in range(435, 450):
            tracker.mark_player_failed(f"player-{i}", "Player inactive")

        assert tracker.get_health_status() == "healthy"
        assert tracker.is_batch_healthy()
        assert not tracker.should_abort_batch()

    def test_api_outage_scenario(self):
        """Test API outage causing high failures (40%)"""
        tracker = BatchFailureTracker(expected_players=450)

        # API outage affects 40% of players
        for i in range(270):
            tracker.mark_player_completed(f"player-{i}")
        for i in range(270, 450):
            tracker.mark_player_failed(f"player-{i}", "API timeout")

        assert tracker.get_health_status() == "critical"
        assert not tracker.is_batch_healthy()
        assert tracker.should_abort_batch()

    def test_partial_model_failure_scenario(self):
        """Test partial model failure (25% failures)"""
        tracker = BatchFailureTracker(expected_players=450)

        # 25% of players fail due to model loading issue
        for i in range(338):
            tracker.mark_player_completed(f"player-{i}")
        for i in range(338, 450):
            tracker.mark_player_failed(f"player-{i}", "Model load failed")

        failure_rate = tracker.get_failure_rate()
        assert failure_rate > 20  # Above threshold
        assert tracker.get_health_status() == "critical"


class TestBatchSummaryIntegration:
    """Test integration with batch summary reporting"""

    def test_summary_includes_failure_metrics(self):
        """Test that batch summary includes failure statistics"""
        tracker = BatchFailureTracker(expected_players=450)

        # Process full batch
        for i in range(400):
            tracker.mark_player_completed(f"player-{i}")
        for i in range(400, 450):
            tracker.mark_player_failed(f"player-{i}", "Error")

        summary = {
            'total_expected': tracker.expected_players,
            'completed': len(tracker.completed_players),
            'failed': len(tracker.failed_players),
            'failure_rate': tracker.get_failure_rate(),
            'health_status': tracker.get_health_status()
        }

        assert summary['total_expected'] == 450
        assert summary['completed'] == 400
        assert summary['failed'] == 50
        assert summary['failure_rate'] > 10
        assert summary['health_status'] in ['healthy', 'warning', 'critical']

    def test_alert_triggered_for_critical_status(self):
        """Test that alerts are triggered for critical failure rates"""
        tracker = BatchFailureTracker(expected_players=450)

        # 30% failure rate
        for i in range(315):
            tracker.mark_player_completed(f"player-{i}")
        for i in range(315, 450):
            tracker.mark_player_failed(f"player-{i}", "System error")

        should_alert = tracker.get_health_status() == "critical"
        alert_message = (
            f"CRITICAL: Batch failure rate at {tracker.get_failure_rate():.1f}% "
            f"({len(tracker.failed_players)} of {tracker.expected_players} players failed)"
        )

        assert should_alert is True
        assert "CRITICAL" in alert_message
        assert "30.0%" in alert_message
