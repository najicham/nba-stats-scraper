# Resilience Pattern Gaps - January 2026

**Created:** 2026-01-24
**Status:** In Progress
**Priority:** P1
**Estimated Hours:** 12-16h

---

## Executive Summary

The codebase has **strong resilience patterns** across 3 layers:
- Circuit breakers (processor, external service, system-level)
- Retry logic with jitter
- Connection pooling

However, **5 processors lack upstream data checks** which can cause retry storms when upstream data is unavailable.

---

## Current Resilience Patterns (Strong)

### Circuit Breakers

| Layer | Location | Status |
|-------|----------|--------|
| Processor-level | `shared/processors/patterns/circuit_breaker_mixin.py` | Strong |
| External Service | `shared/utils/external_service_circuit_breaker.py` | Strong |
| System (ML models) | `predictions/worker/system_circuit_breaker.py` | Strong |

### Retry Logic

| Pattern | Location | Status |
|---------|----------|--------|
| Decorrelated Jitter | `shared/utils/retry_with_jitter.py` | Strong |
| HTTP Retries | `shared/clients/http_pool.py` | Strong |
| BigQuery Retries | `shared/utils/bigquery_retry.py` | Strong |

### Connection Pooling

| Service | Location | Status |
|---------|----------|--------|
| HTTP | `shared/clients/http_pool.py` | Strong |
| BigQuery | `shared/clients/bigquery_pool.py` | Strong |
| GCS | `shared/clients/storage_client.py` | Strong |

---

## Gap #1: Missing Upstream Data Checks (P1)

### Problem
Circuit breaker retries blindly without checking if upstream data exists.
Result: Retry storms (Jan 16 incident: 7,139 runs, 71% failure rate)

### Processors WITH Upstream Checks (5)
- `player_game_summary_processor.py`
- `team_defense_game_summary_processor.py`
- `team_offense_game_summary_processor.py`
- `upcoming_team_game_context_processor.py`
- `defense_zone_analytics_processor.py`

### Processors MISSING Upstream Checks (5)

| Processor | Priority | Upstream Dependency |
|-----------|----------|---------------------|
| `upcoming_player_game_context_processor.py` | P1 | player_game_summary + betting lines |
| `async_upcoming_player_game_context_processor.py` | P1 | Same as above |
| `roster_history_processor.py` | P2 | roster tables |
| `batter_game_summary_processor.py` (MLB) | P2 | MLB boxscores |
| `pitcher_game_summary_processor.py` (MLB) | P2 | MLB boxscores |

### Implementation Template

```python
def get_upstream_data_check_query(self) -> Optional[str]:
    """Check if upstream data exists before circuit breaker retries."""
    return f"""
    SELECT
      CASE
        WHEN EXISTS (
          SELECT 1 FROM `{self.project_id}.{self.upstream_dataset}.{self.upstream_table}`
          WHERE game_date = '{self.target_date}'
          AND processed_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 4 HOUR)
        ) THEN TRUE
        ELSE FALSE
      END as data_available
    """
```

### Action Items
- [ ] Add upstream check to `upcoming_player_game_context_processor.py`
- [ ] Add upstream check to `async_upcoming_player_game_context_processor.py`
- [ ] Add upstream check to `roster_history_processor.py`
- [ ] Add upstream check to MLB processors

**Estimated Time:** 4 hours

---

## Gap #2: No Processor-Level Timeout (P2)

### Problem
Individual operations have timeouts but no overall processor timeout.
A processor could hang indefinitely if a thread/async operation stalls.

### Current Timeouts
- HTTP requests: 30 seconds
- BigQuery queries: 120 seconds
- No processor-level wrapper

### Solution

```python
# shared/processors/patterns/timeout_wrapper.py (NEW)
import signal
from functools import wraps

def processor_timeout(seconds: int = 600):
    """Wrap processor run() with overall timeout."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            def handler(signum, frame):
                raise TimeoutError(f"Processor exceeded {seconds}s timeout")

            signal.signal(signal.SIGALRM, handler)
            signal.alarm(seconds)
            try:
                return func(*args, **kwargs)
            finally:
                signal.alarm(0)
        return wrapper
    return decorator
```

### Action Items
- [ ] Create processor timeout wrapper
- [ ] Apply to AnalyticsProcessorBase
- [ ] Apply to PrecomputeProcessorBase
- [ ] Add timeout configuration per processor

**Estimated Time:** 4 hours

---

## Gap #3: Circuit Breaker Metrics Dashboard (P2)

### Problem
Circuit breaker events are logged and written to BigQuery, but no easy way to visualize current state.

### Current Monitoring
- Logs circuit breaker open/close events
- Writes to `nba_orchestration.circuit_breaker_state`
- No dashboard or quick query

### Solution: Create Circuit Breaker Dashboard View

```sql
-- schemas/views/v_circuit_breaker_status.sql (NEW)
CREATE OR REPLACE VIEW `nba_orchestration.v_circuit_breaker_status` AS
SELECT
  processor_name,
  state,
  failure_count,
  opened_at,
  TIMESTAMP_DIFF(
    COALESCE(closed_at, CURRENT_TIMESTAMP()),
    opened_at,
    MINUTE
  ) as open_duration_minutes,
  last_failure_reason,
  COUNT(*) OVER (PARTITION BY processor_name) as total_opens_24h
FROM `nba_orchestration.circuit_breaker_state`
WHERE updated_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
ORDER BY opened_at DESC;
```

### Action Items
- [ ] Create circuit breaker status view
- [ ] Add to daily health check
- [ ] Create Slack alert for prolonged open state

**Estimated Time:** 2 hours

---

## Gap #4: MLB Processors Lack Standard Patterns (P3)

### Problem
MLB processors don't use same resilience patterns as NBA.

### Missing Patterns in MLB

| Processor | CircuitBreaker | UpstreamCheck | Heartbeat |
|-----------|----------------|---------------|-----------|
| `batter_game_summary_processor.py` | No | No | Unknown |
| `pitcher_game_summary_processor.py` | No | No | Unknown |

### Action Items
- [ ] Add CircuitBreakerMixin to MLB processors
- [ ] Add upstream data checks
- [ ] Verify heartbeat integration

**Estimated Time:** 4 hours

---

## Gap #5: Heartbeat Firestore Fallback (P3)

### Problem
Heartbeat system requires Firestore. If Firestore unavailable, processor appears stuck immediately.

### Solution
Add fallback to Cloud Logging timestamps and optional GCS heartbeat file.

### Action Items
- [ ] Add Cloud Logging fallback for heartbeat
- [ ] Add GCS heartbeat file option
- [ ] Test failover behavior

**Estimated Time:** 4 hours

---

## Implementation Schedule

### Week 1
- [ ] Add upstream checks to NBA processors (2h)
- [ ] Create circuit breaker status view (2h)

### Week 2
- [ ] Add upstream checks to MLB processors (2h)
- [ ] Create processor timeout wrapper (4h)

### Week 3
- [ ] Add MLB resilience patterns (4h)
- [ ] Heartbeat fallback (4h)

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Processors with upstream checks | 5/10 | 10/10 |
| Processors with timeout wrapper | 0 | All |
| Circuit breaker visibility | Logs only | Dashboard |
| MLB resilience parity | 0% | 100% |

---

## Related Documentation

- Morning improvements: `/docs/09-handoff/2026-01-24-SESSION12-MORNING-IMPROVEMENTS.md`
- Main improvement plan: `../SESSION-12-AFTERNOON-IMPROVEMENT-PLAN.md`
- Circuit breaker config: `/shared/config/circuit_breaker_config.py`

---

**Created:** 2026-01-24
**Last Updated:** 2026-01-24
