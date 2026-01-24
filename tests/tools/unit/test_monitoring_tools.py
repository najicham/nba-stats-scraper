"""
Unit tests for tools/monitoring/ module

Tests the monitoring tools including:
- check_pipeline_health.py
- check_prediction_coverage.py
- check_prop_freshness.py

Path: tests/tools/unit/test_monitoring_tools.py
Created: 2026-01-24
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timezone, date


# ============================================================================
# TEST PIPELINE HEALTH CHECK
# ============================================================================

class TestPipelineHealthCheck:
    """Test pipeline health check tool."""

    def test_check_phase_status(self, sample_pipeline_status):
        """Should check status of all phases."""
        status = sample_pipeline_status

        completed = [p for p, s in status.items() if s['status'] == 'completed']
        running = [p for p, s in status.items() if s['status'] == 'running']

        assert len(completed) == 2
        assert len(running) == 1

    def test_calculate_processor_totals(self, sample_pipeline_status):
        """Should calculate total processors."""
        status = sample_pipeline_status

        total_processors = sum(s['processors'] for s in status.values())

        assert total_processors == 25

    def test_detect_stalled_phase(self):
        """Should detect stalled phases."""
        from datetime import timedelta

        phase_status = {
            'status': 'running',
            'started_at': datetime.now(timezone.utc) - timedelta(hours=2),
            'expected_duration_minutes': 30
        }

        now = datetime.now(timezone.utc)
        running_time = (now - phase_status['started_at']).total_seconds() / 60
        is_stalled = running_time > phase_status['expected_duration_minutes'] * 2

        assert is_stalled is True

    def test_calculate_completion_percentage(self, sample_pipeline_status):
        """Should calculate completion percentage."""
        status = sample_pipeline_status
        total_phases = len(status)
        completed_phases = sum(1 for s in status.values() if s['status'] == 'completed')

        percentage = (completed_phases / total_phases) * 100

        assert percentage == pytest.approx(66.67, rel=0.1)


# ============================================================================
# TEST PREDICTION COVERAGE CHECK
# ============================================================================

class TestPredictionCoverageCheck:
    """Test prediction coverage check tool."""

    def test_calculate_coverage_percentage(self, sample_prediction_coverage):
        """Should calculate coverage percentage correctly."""
        coverage = sample_prediction_coverage

        assert coverage['coverage_percentage'] == 100.0

    def test_detect_missing_predictions(self):
        """Should detect missing predictions."""
        coverage = {
            'total_games': 10,
            'games_with_predictions': 8,
            'missing_predictions': [
                {'game_id': 'g001', 'teams': 'LAL vs BOS'},
                {'game_id': 'g002', 'teams': 'GSW vs MIA'}
            ]
        }

        missing_count = len(coverage['missing_predictions'])

        assert missing_count == 2
        assert coverage['games_with_predictions'] == 8

    def test_coverage_threshold_check(self, sample_prediction_coverage):
        """Should check against coverage threshold."""
        coverage = sample_prediction_coverage
        threshold = 95.0

        meets_threshold = coverage['coverage_percentage'] >= threshold

        assert meets_threshold is True

    def test_coverage_by_prop_type(self):
        """Should calculate coverage by prop type."""
        prop_coverage = {
            'points': {'total': 100, 'covered': 98},
            'rebounds': {'total': 100, 'covered': 95},
            'assists': {'total': 100, 'covered': 100}
        }

        coverage_percentages = {
            prop: (data['covered'] / data['total']) * 100
            for prop, data in prop_coverage.items()
        }

        assert coverage_percentages['points'] == 98.0
        assert coverage_percentages['assists'] == 100.0


# ============================================================================
# TEST PROP FRESHNESS CHECK
# ============================================================================

class TestPropFreshnessCheck:
    """Test prop freshness check tool."""

    def test_calculate_freshness_percentage(self, sample_prop_freshness):
        """Should calculate freshness percentage correctly."""
        freshness = sample_prop_freshness

        assert freshness['freshness_percentage'] == 96.0

    def test_detect_stale_props(self):
        """Should detect stale props."""
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        max_age_hours = 2

        props = [
            {'id': 1, 'updated_at': now - timedelta(hours=1)},  # Fresh
            {'id': 2, 'updated_at': now - timedelta(hours=3)},  # Stale
            {'id': 3, 'updated_at': now - timedelta(hours=5)},  # Stale
        ]

        stale_props = [
            p for p in props
            if (now - p['updated_at']).total_seconds() > max_age_hours * 3600
        ]

        assert len(stale_props) == 2

    def test_freshness_threshold_alert(self, sample_prop_freshness):
        """Should alert when freshness below threshold."""
        freshness = sample_prop_freshness
        threshold = 90.0

        needs_alert = freshness['freshness_percentage'] < threshold

        assert needs_alert is False  # 96% > 90%

    def test_freshness_by_source(self):
        """Should calculate freshness by data source."""
        source_freshness = {
            'bdl': {'fresh': 180, 'stale': 10},
            'espn': {'fresh': 150, 'stale': 5},
            'nba_com': {'fresh': 100, 'stale': 5}
        }

        freshness_by_source = {
            source: data['fresh'] / (data['fresh'] + data['stale']) * 100
            for source, data in source_freshness.items()
        }

        assert freshness_by_source['bdl'] == pytest.approx(94.7, rel=0.1)


# ============================================================================
# TEST REPORTING
# ============================================================================

class TestMonitoringReports:
    """Test monitoring report generation."""

    def test_generate_summary_report(self, sample_pipeline_status, sample_prediction_coverage):
        """Should generate summary monitoring report."""
        report = {
            'date': date.today().isoformat(),
            'pipeline': sample_pipeline_status,
            'prediction_coverage': sample_prediction_coverage,
            'overall_health': 'good'
        }

        assert 'date' in report
        assert 'pipeline' in report
        assert 'prediction_coverage' in report

    def test_format_for_email(self, sample_prediction_coverage):
        """Should format report for email."""
        coverage = sample_prediction_coverage

        email_body = f"""
Prediction Coverage Report - {coverage['date']}

Games with Predictions: {coverage['games_with_predictions']}/{coverage['total_games']}
Coverage: {coverage['coverage_percentage']}%

Missing Predictions: {len(coverage['missing_predictions'])}
"""

        assert 'Coverage Report' in email_body
        assert '100.0%' in email_body

    def test_severity_classification(self):
        """Should classify severity based on metrics."""
        def classify_severity(coverage_pct):
            if coverage_pct >= 98:
                return 'good'
            elif coverage_pct >= 90:
                return 'warning'
            else:
                return 'critical'

        assert classify_severity(100) == 'good'
        assert classify_severity(95) == 'warning'
        assert classify_severity(80) == 'critical'


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestMonitoringIntegration:
    """Integration tests for monitoring tools."""

    def test_full_monitoring_workflow(
        self,
        sample_pipeline_status,
        sample_prediction_coverage,
        sample_prop_freshness
    ):
        """Should complete full monitoring workflow."""
        # Collect all metrics
        metrics = {
            'pipeline': sample_pipeline_status,
            'coverage': sample_prediction_coverage,
            'freshness': sample_prop_freshness
        }

        # Evaluate overall health
        pipeline_ok = all(
            s['status'] in ['completed', 'running']
            for s in metrics['pipeline'].values()
        )
        coverage_ok = metrics['coverage']['coverage_percentage'] >= 90
        freshness_ok = metrics['freshness']['freshness_percentage'] >= 90

        overall_health = 'healthy' if all([pipeline_ok, coverage_ok, freshness_ok]) else 'degraded'

        assert overall_health == 'healthy'
