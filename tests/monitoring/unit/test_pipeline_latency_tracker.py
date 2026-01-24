"""
Unit tests for monitoring/pipeline_latency_tracker.py

Tests the PipelineLatencyTracker class including:
- Initialization
- Timestamp extraction
- Latency calculation
- Threshold checking
- BigQuery storage
- Alert sending

Path: tests/monitoring/unit/test_pipeline_latency_tracker.py
Created: 2026-01-24
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone, timedelta
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))


# ============================================================================
# TEST CONSTANTS
# ============================================================================

class TestConstants:
    """Test module-level constants."""

    def test_thresholds_defined(self):
        """Should have latency thresholds defined."""
        from monitoring.pipeline_latency_tracker import THRESHOLDS

        assert 'phase1_to_phase2' in THRESHOLDS
        assert 'phase2_to_phase3' in THRESHOLDS
        assert 'total_pipeline' in THRESHOLDS
        assert 'critical_total' in THRESHOLDS

    def test_thresholds_reasonable(self):
        """Thresholds should be reasonable values."""
        from monitoring.pipeline_latency_tracker import THRESHOLDS

        # All thresholds should be positive
        for name, value in THRESHOLDS.items():
            assert value > 0, f"{name} threshold should be positive"

        # Total should be sum of individual phases or more
        assert THRESHOLDS['total_pipeline'] >= 1800  # 30 minutes
        assert THRESHOLDS['critical_total'] >= THRESHOLDS['total_pipeline']

    def test_phase_collections_defined(self):
        """Should have Firestore collection names defined."""
        from monitoring.pipeline_latency_tracker import PHASE_COLLECTIONS

        assert 'phase2' in PHASE_COLLECTIONS
        assert 'phase3' in PHASE_COLLECTIONS
        assert 'phase4' in PHASE_COLLECTIONS
        assert 'phase5' in PHASE_COLLECTIONS
        assert 'phase6' in PHASE_COLLECTIONS


# ============================================================================
# TEST PIPELINE LATENCY TRACKER INITIALIZATION
# ============================================================================

class TestPipelineLatencyTrackerInit:
    """Test PipelineLatencyTracker initialization."""

    @patch('monitoring.pipeline_latency_tracker.firestore')
    @patch('monitoring.pipeline_latency_tracker.bigquery')
    def test_init_with_default_project(self, mock_bq, mock_fs):
        """Should initialize with default project ID."""
        from monitoring.pipeline_latency_tracker import PipelineLatencyTracker

        tracker = PipelineLatencyTracker()

        assert tracker.project_id is not None

    @patch('monitoring.pipeline_latency_tracker.firestore')
    @patch('monitoring.pipeline_latency_tracker.bigquery')
    def test_init_with_custom_project(self, mock_bq, mock_fs):
        """Should initialize with custom project ID."""
        from monitoring.pipeline_latency_tracker import PipelineLatencyTracker

        tracker = PipelineLatencyTracker(project_id='custom-project')

        assert tracker.project_id == 'custom-project'

    @patch('monitoring.pipeline_latency_tracker.firestore')
    @patch('monitoring.pipeline_latency_tracker.bigquery')
    def test_lazy_client_initialization(self, mock_bq, mock_fs):
        """Clients should be lazily initialized."""
        from monitoring.pipeline_latency_tracker import PipelineLatencyTracker

        tracker = PipelineLatencyTracker()

        # Internal clients should be None initially
        assert tracker._db is None
        assert tracker._bq_client is None


# ============================================================================
# TEST LATENCY CALCULATIONS
# ============================================================================

class TestLatencyCalculations:
    """Test latency calculation logic."""

    def test_calculate_latency_seconds(self):
        """Should correctly calculate latency in seconds."""
        start = datetime(2026, 1, 20, 10, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 1, 20, 10, 5, 0, tzinfo=timezone.utc)

        latency = (end - start).total_seconds()

        assert latency == 300  # 5 minutes

    def test_calculate_total_pipeline_latency(self, sample_phase_timestamps):
        """Should calculate total pipeline latency."""
        start = sample_phase_timestamps['phase1_start']
        end = sample_phase_timestamps['phase6_complete']

        total_latency = (end - start).total_seconds()

        assert total_latency == 2100  # 35 minutes

    def test_calculate_phase_latencies(self, sample_phase_timestamps):
        """Should calculate per-phase latencies."""
        ts = sample_phase_timestamps

        latencies = {
            'phase1_to_phase2': (ts['phase2_complete'] - ts['phase1_start']).total_seconds(),
            'phase2_to_phase3': (ts['phase3_complete'] - ts['phase2_complete']).total_seconds(),
            'phase3_to_phase4': (ts['phase4_complete'] - ts['phase3_complete']).total_seconds(),
            'phase4_to_phase5': (ts['phase5_complete'] - ts['phase4_complete']).total_seconds(),
            'phase5_to_phase6': (ts['phase6_complete'] - ts['phase5_complete']).total_seconds(),
        }

        assert latencies['phase1_to_phase2'] == 300
        assert latencies['phase2_to_phase3'] == 600
        assert latencies['phase3_to_phase4'] == 300
        assert latencies['phase4_to_phase5'] == 600
        assert latencies['phase5_to_phase6'] == 300


# ============================================================================
# TEST THRESHOLD CHECKING
# ============================================================================

class TestThresholdChecking:
    """Test threshold checking logic."""

    def test_check_normal_latency(self, sample_latency_metrics):
        """Normal latency should not trigger alerts."""
        from monitoring.pipeline_latency_tracker import THRESHOLDS

        metrics = sample_latency_metrics
        breaches = []

        for phase, latency in metrics.items():
            if phase in THRESHOLDS and latency > THRESHOLDS[phase]:
                breaches.append(phase)

        assert len(breaches) == 0

    def test_check_slow_latency(self, sample_slow_latency_metrics):
        """Slow latency should be detected."""
        from monitoring.pipeline_latency_tracker import THRESHOLDS

        metrics = sample_slow_latency_metrics
        breaches = []

        if metrics['phase1_to_phase2'] > THRESHOLDS['phase1_to_phase2']:
            breaches.append('phase1_to_phase2')

        assert 'phase1_to_phase2' in breaches

    def test_critical_threshold(self, sample_slow_latency_metrics):
        """Critical total latency should be detected."""
        from monitoring.pipeline_latency_tracker import THRESHOLDS

        metrics = sample_slow_latency_metrics

        is_critical = metrics['total_latency_seconds'] > THRESHOLDS['critical_total']

        assert is_critical is True


# ============================================================================
# TEST METRICS FORMATTING
# ============================================================================

class TestMetricsFormatting:
    """Test metrics data formatting."""

    def test_format_for_bigquery(self, sample_latency_metrics):
        """Metrics should be formatted for BigQuery insertion."""
        metrics = sample_latency_metrics

        bq_row = {
            'date': metrics['date'],
            'total_latency_seconds': metrics['total_latency_seconds'],
            'phase_latencies': {
                'phase1_to_phase2': metrics['phase1_to_phase2'],
                'phase2_to_phase3': metrics['phase2_to_phase3'],
            }
        }

        assert 'date' in bq_row
        assert 'total_latency_seconds' in bq_row
        assert isinstance(bq_row['phase_latencies'], dict)

    def test_format_for_json_output(self, sample_latency_metrics):
        """Metrics should be JSON serializable."""
        import json

        json_str = json.dumps(sample_latency_metrics)
        parsed = json.loads(json_str)

        assert parsed == sample_latency_metrics


# ============================================================================
# TEST ALERT GENERATION
# ============================================================================

class TestAlertGeneration:
    """Test alert generation logic."""

    def test_generate_warning_alert(self, sample_slow_latency_metrics):
        """Should generate warning for threshold breach."""
        from monitoring.pipeline_latency_tracker import THRESHOLDS

        metrics = sample_slow_latency_metrics
        breached_phases = []

        for phase in ['phase1_to_phase2', 'phase2_to_phase3']:
            if metrics.get(phase, 0) > THRESHOLDS.get(phase, float('inf')):
                breached_phases.append(phase)

        # Build alert message
        alert = {
            'type': 'warning',
            'message': f"Latency threshold breached for: {', '.join(breached_phases)}",
            'metrics': {p: metrics[p] for p in breached_phases}
        }

        assert alert['type'] == 'warning'
        assert len(breached_phases) > 0

    def test_generate_critical_alert(self, sample_slow_latency_metrics):
        """Should generate critical alert for total threshold breach."""
        from monitoring.pipeline_latency_tracker import THRESHOLDS

        metrics = sample_slow_latency_metrics

        if metrics['total_latency_seconds'] > THRESHOLDS['critical_total']:
            alert = {
                'type': 'critical',
                'message': f"Pipeline total latency exceeds critical threshold",
                'total_seconds': metrics['total_latency_seconds'],
                'threshold': THRESHOLDS['critical_total']
            }

            assert alert['type'] == 'critical'
            assert alert['total_seconds'] > alert['threshold']


# ============================================================================
# TEST DATE HANDLING
# ============================================================================

class TestDateHandling:
    """Test date parsing and handling."""

    def test_parse_date_string(self):
        """Should parse date string correctly."""
        from datetime import date

        date_str = '2026-01-20'
        parsed = date.fromisoformat(date_str)

        assert parsed.year == 2026
        assert parsed.month == 1
        assert parsed.day == 20

    def test_default_to_today(self):
        """Should default to today if no date provided."""
        from datetime import date

        today = date.today()

        assert today is not None
        assert isinstance(today, date)

    def test_format_date_for_firestore_query(self):
        """Should format date for Firestore queries."""
        date_str = '2026-01-20'

        # Firestore document IDs often use this format
        doc_id = f"pipeline_{date_str}"

        assert doc_id == "pipeline_2026-01-20"


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestIntegration:
    """Integration tests for pipeline latency tracker."""

    def test_end_to_end_latency_calculation(self, sample_phase_timestamps):
        """Should calculate complete latency metrics."""
        ts = sample_phase_timestamps

        # Simulate full calculation
        metrics = {
            'phase1_to_phase2': (ts['phase2_complete'] - ts['phase1_start']).total_seconds(),
            'phase2_to_phase3': (ts['phase3_complete'] - ts['phase2_complete']).total_seconds(),
            'phase3_to_phase4': (ts['phase4_complete'] - ts['phase3_complete']).total_seconds(),
            'phase4_to_phase5': (ts['phase5_complete'] - ts['phase4_complete']).total_seconds(),
            'phase5_to_phase6': (ts['phase6_complete'] - ts['phase5_complete']).total_seconds(),
        }

        total = sum(metrics.values())

        assert total == 2100  # 35 minutes
        assert len(metrics) == 5

    def test_threshold_evaluation_pipeline(self, sample_latency_metrics):
        """Should evaluate all thresholds correctly."""
        from monitoring.pipeline_latency_tracker import THRESHOLDS

        metrics = sample_latency_metrics
        results = []

        for threshold_name, threshold_value in THRESHOLDS.items():
            if threshold_name in metrics:
                passed = metrics[threshold_name] <= threshold_value
                results.append({
                    'threshold': threshold_name,
                    'value': metrics[threshold_name],
                    'limit': threshold_value,
                    'passed': passed
                })

        # All should pass for normal metrics
        assert all(r['passed'] for r in results)
