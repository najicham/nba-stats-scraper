"""shared.observability.metrics — Cloud Monitoring custom metrics emitter.

One emitter, one metric type, every phase processor calls it. The unified
observability layer that replaces ~10 standalone monitoring CFs (each with
its own scheduler, alert format, lookback window).

Custom metric types:

    custom.googleapis.com/nba_pipeline/phase_completion
        Gauge per (phase, output_type, status, sport).
        Emitted by reconciler + by each phase processor at run-end.

    custom.googleapis.com/nba_pipeline/phase_latency_ms
        Distribution per (phase, sport).
        Emitted by phase processors at run-end with elapsed_ms.

    custom.googleapis.com/nba_pipeline/halt_state_age_hours
        Gauge per (sport).
        Emitted by halt_state_writer; alert fires if > 36h.

Failure mode: fail-open. If Cloud Monitoring is unreachable, log and return —
processors must not crash because telemetry is degraded.

Created: 2026-05-09 (pipeline-state-redesign Phase D).
"""

import enum
import logging
import os
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
METRIC_DOMAIN = 'custom.googleapis.com/nba_pipeline'

_monitoring_client = None


class MetricKind(enum.Enum):
    """Mirror of the Cloud Monitoring MetricKind enum we use."""
    GAUGE = 'GAUGE'
    CUMULATIVE = 'CUMULATIVE'


def _get_monitoring_client():
    """Lazy-init Cloud Monitoring client. Returns None if SDK unavailable."""
    global _monitoring_client
    if _monitoring_client is not None:
        return _monitoring_client
    try:
        from google.cloud import monitoring_v3
        _monitoring_client = monitoring_v3.MetricServiceClient()
        return _monitoring_client
    except Exception as e:
        logger.warning(f"monitoring_v3 not available, metrics will be no-op: {e}")
        return None


def emit_metric(
    metric_name: str,
    value: float,
    labels: Optional[Dict[str, str]] = None,
    kind: MetricKind = MetricKind.GAUGE,
) -> None:
    """Emit a single custom metric to Cloud Monitoring. Fail-open.

    Args:
        metric_name: short name appended to METRIC_DOMAIN.
            Example: 'phase_completion' → 'custom.googleapis.com/nba_pipeline/phase_completion'
        value: numeric value (cast to float).
        labels: dict of label key→value strings (e.g. {'phase': 'phase3_analytics', 'sport': 'nba'}).
        kind: GAUGE for current state; CUMULATIVE for monotonic counters.
    """
    client = _get_monitoring_client()
    if client is None:
        return  # fail-open: no client, no telemetry, no crash

    try:
        from google.cloud import monitoring_v3
        from google.protobuf import timestamp_pb2

        labels = labels or {}

        series = monitoring_v3.TimeSeries()
        series.metric.type = f'{METRIC_DOMAIN}/{metric_name}'
        for k, v in labels.items():
            series.metric.labels[k] = str(v)
        series.resource.type = 'global'
        series.resource.labels['project_id'] = PROJECT_ID

        now_seconds = int(time.time())
        ts = monitoring_v3.TimeInterval()
        ts.end_time = timestamp_pb2.Timestamp(seconds=now_seconds)
        if kind == MetricKind.CUMULATIVE:
            ts.start_time = timestamp_pb2.Timestamp(seconds=now_seconds - 60)

        point = monitoring_v3.Point()
        point.interval = ts
        point.value.double_value = float(value)
        series.points = [point]

        client.create_time_series(
            name=f'projects/{PROJECT_ID}',
            time_series=[series],
        )
    except Exception as e:
        # Telemetry failure must never crash the caller.
        logger.warning(f"emit_metric failed (non-fatal): {metric_name}={value} err={e}")


def emit_phase_completion(
    phase: str,
    output_type: str,
    status: str,
    sport: str = 'nba',
    row_count: Optional[int] = None,
) -> None:
    """Convenience wrapper for the phase_completion metric.

    Called by each phase processor at run-end and by phase_completion_reconciler.
    """
    labels = {
        'phase': phase,
        'output_type': output_type,
        'status': status,
        'sport': sport,
    }
    # Encode status as the metric value for graphing convenience:
    #   COMPLETE = 1, EMPTY_OK = 1 (both healthy), EXPECTED/RUNNING = 0.5,
    #   DEGRADED = 0.25, FAILED = 0
    status_value = {
        'COMPLETE': 1.0,
        'EMPTY_OK': 1.0,
        'RUNNING': 0.5,
        'EXPECTED': 0.5,
        'DEGRADED': 0.25,
        'FAILED': 0.0,
    }.get(status, 0.0)

    emit_metric(
        metric_name='phase_completion',
        value=status_value,
        labels=labels,
        kind=MetricKind.GAUGE,
    )

    if row_count is not None:
        emit_metric(
            metric_name='phase_row_count',
            value=float(row_count),
            labels=labels,
            kind=MetricKind.GAUGE,
        )
