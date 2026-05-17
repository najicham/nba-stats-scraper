"""
Monitoring and observability utilities for the NBA Stats Scraper pipeline.

This package provides real-time monitoring capabilities including:
- Processor heartbeat system for stuck/stale processor detection
- Auto-recovery mechanisms for failed processors
- Pipeline health monitoring

processor_heartbeat is exposed lazily via PEP 562 __getattr__ so that
importing sibling submodules (e.g. shared.monitoring.bias_decay_thresholds)
does not pull in google-cloud-firestore / google-cloud-storage. Direct
submodule imports (from shared.monitoring.processor_heartbeat import …)
still work and load Firestore eagerly, as intended for consumers that
actually use heartbeats.
"""

_HEARTBEAT_NAMES = {
    "ProcessorHeartbeat",
    "HeartbeatMonitor",
    "ProcessorState",
    "HeartbeatConfig",
}

__all__ = sorted(_HEARTBEAT_NAMES)


def __getattr__(name):
    if name in _HEARTBEAT_NAMES:
        from shared.monitoring import processor_heartbeat
        return getattr(processor_heartbeat, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
