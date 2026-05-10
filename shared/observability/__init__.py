"""Observability layer for the NBA stats pipeline.

Exposes a single metrics emitter (`emit_metric`) used by every phase
processor + Cloud Function to write custom metrics to Cloud Monitoring.
The emitter is fail-open: if Cloud Monitoring is unreachable, it logs and
returns rather than crashing the caller.

Pipeline-state-redesign Phase D.
"""

from .metrics import emit_metric, emit_phase_completion, MetricKind

__all__ = ['emit_metric', 'emit_phase_completion', 'MetricKind']
