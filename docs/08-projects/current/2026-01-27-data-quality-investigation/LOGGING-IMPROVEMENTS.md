# Logging Improvements for Post-Mortem Diagnosis

**Created:** 2026-01-27
**Status:** In Progress
**Purpose:** Enable effective post-mortem diagnosis of pipeline failures

## Executive Summary

Current logging makes it hard to answer critical questions during failures:
- **Why did player stats run before team stats?** (no timing logs)
- **Why did MERGE fall back to DELETE+INSERT?** (error not captured)
- **Why did coordinator time out?** (no progress logging)
- **When exactly did betting lines arrive vs Phase 3 run?** (timing unclear)

This document outlines improvements to structured logging to enable faster diagnosis and root cause analysis.

---

## Current State Analysis

### Existing Logging Infrastructure

**Good:**
1. **Structured logging foundation exists** (`shared/utils/structured_logging.py`)
   - JSON-formatted logs with queryable fields
   - Context propagation via thread-local storage
   - Convenience functions for common events
   - Cloud Logging integration

2. **Pipeline event logging** (`shared/utils/pipeline_logger.py`)
   - Comprehensive event tracking to BigQuery
   - Batched writes (50x quota reduction)
   - Auto-retry queue integration
   - Processor start/complete/error tracking

3. **Scraper logging** (`shared/utils/scraper_logging.py`)
   - START/END event tracking
   - Duration and record count tracking
   - Context manager support

**Gaps:**
1. **Missing timing correlation**
   - No logs showing when processors started relative to each other
   - No dependency resolution timing (when did upstream data become available?)
   - No phase transition timing (when did Phase 2→3 trigger occur?)

2. **Missing error context**
   - MERGE fallback reasons not logged (streaming buffer? syntax error?)
   - Dependency check failures lack detail (which table? how stale?)
   - No differentiation between expected vs unexpected failures

3. **Missing progress tracking**
   - Orchestrators don't log progress (5/14 processors complete)
   - No timeout warnings before actual timeout
   - No "stuck processor" detection logs

4. **Inconsistent adoption**
   - Analytics processors use basic logging, not structured logging
   - Orchestrators have minimal timing logs
   - BigQuery save operations lack detailed error logging

---

## Logging Improvement Plan

### Phase 1: Add Timing Correlation (High Priority)

**Goal:** Answer "Why did X run before Y?" and "When did data become available?"

#### 1.1 Processor Start with Dependency Status
**File:** `data_processors/analytics/analytics_base.py`
**Location:** Line 228 (after dependency check)

```python
# After dependency check completes
if hasattr(self, 'get_dependencies'):
    logger.info("processor_started", extra={
        "event": "processor_started",
        "processor": self.processor_name,
        "game_date": str(analysis_date),
        "start_time": datetime.utcnow().isoformat(),
        "dependencies_status": {
            dep_table: dep_check['details'][dep_table]['status']
            for dep_table in dep_check.get('details', {})
        },
        "dependency_check_seconds": dep_check_seconds,
        "all_dependencies_ready": dep_check['all_critical_present']
    })
```

**Query to find it:**
```sql
SELECT
  timestamp,
  jsonPayload.processor,
  jsonPayload.game_date,
  jsonPayload.dependencies_status
FROM `nba-props-platform.logs`
WHERE jsonPayload.event = "processor_started"
  AND jsonPayload.game_date = "2026-01-27"
ORDER BY timestamp
```

#### 1.2 Phase Completion Timing
**File:** `data_processors/analytics/analytics_base.py`
**Location:** Line 605 (after save_analytics)

```python
# After successful save
logger.info("phase_timing", extra={
    "event": "phase_timing",
    "phase": "phase_3",
    "processor": self.processor_name,
    "game_date": str(analysis_date),
    "completed_at": datetime.utcnow().isoformat(),
    "duration_seconds": total_seconds,
    "records_processed": self.stats.get('rows_processed', 0),
    "extract_time": extract_seconds,
    "transform_time": transform_seconds,
    "save_time": save_seconds
})
```

**Correlation query:**
```sql
-- Find all Phase 3 processors for a date, ordered by completion
SELECT
  timestamp,
  jsonPayload.processor,
  jsonPayload.duration_seconds,
  jsonPayload.records_processed
FROM `nba-props-platform.logs`
WHERE jsonPayload.event = "phase_timing"
  AND jsonPayload.phase = "phase_3"
  AND jsonPayload.game_date = "2026-01-27"
ORDER BY timestamp
```

#### 1.3 Orchestrator Progress Logging
**File:** `orchestration/cloud_functions/phase2_to_phase3/main.py`
**Location:** After each processor completion update

```python
# After updating Firestore completion state
logger.info("orchestrator_progress", extra={
    "event": "orchestrator_progress",
    "phase": "phase_2_to_3",
    "game_date": game_date,
    "completed_count": len(completed_processors),
    "expected_count": EXPECTED_PROCESSOR_COUNT,
    "completion_pct": len(completed_processors) / EXPECTED_PROCESSOR_COUNT * 100,
    "recently_completed": processor_name,
    "missing_processors": list(EXPECTED_PROCESSOR_SET - set(completed_processors)),
    "elapsed_minutes": (datetime.utcnow() - phase_start_time).total_seconds() / 60,
    "will_trigger_next_phase": len(completed_processors) == EXPECTED_PROCESSOR_COUNT
})
```

**Timeout warning:**
```python
# Before timeout deadline (e.g., at 25 minutes if deadline is 30)
if elapsed_minutes > (PHASE2_COMPLETION_TIMEOUT_MINUTES * 0.8):
    logger.warning("orchestrator_deadline_warning", extra={
        "event": "orchestrator_deadline_warning",
        "phase": "phase_2_to_3",
        "game_date": game_date,
        "elapsed_minutes": elapsed_minutes,
        "deadline_minutes": PHASE2_COMPLETION_TIMEOUT_MINUTES,
        "remaining_minutes": PHASE2_COMPLETION_TIMEOUT_MINUTES - elapsed_minutes,
        "missing_processors": list(EXPECTED_PROCESSOR_SET - set(completed_processors))
    })
```

---

### Phase 2: Add Error Context (High Priority)

**Goal:** Answer "Why did this fail?" with full context

#### 2.1 MERGE Fallback Logging
**File:** `data_processors/analytics/operations/bigquery_save_ops.py`
**Location:** Line 476 (MERGE error handler), Line 591 (DELETE streaming buffer error)

**Already implemented** (line 482-496) but enhance with structured logging:

```python
# In _save_with_proper_merge exception handler
logger.error("merge_fallback", extra={
    "event": "merge_fallback",
    "processor": self.__class__.__name__,
    "table": table_id,
    "reason": "syntax_error" if "syntax error" in error_msg.lower() else "unknown",
    "error_message": error_msg[:500],
    "rows_affected": len(rows),
    "primary_keys": primary_keys,
    "update_fields_count": len(update_fields),
    "fallback_strategy": "DELETE_INSERT",
    "will_retry": False
})
```

**In _save_with_delete_insert streaming buffer handler:**

```python
# Line 591 - already raises StreamingBufferActiveError, add log:
logger.warning("streaming_buffer_active", extra={
    "event": "streaming_buffer_active",
    "processor": self.__class__.__name__,
    "table": table_id,
    "operation": "DELETE",
    "game_dates": game_dates,
    "records_affected": len(rows),
    "will_retry": True,
    "retry_behavior": "Next trigger will process after buffer flushes (90 min max)"
})
```

**Query for MERGE fallbacks:**
```sql
SELECT
  timestamp,
  jsonPayload.processor,
  jsonPayload.reason,
  jsonPayload.error_message
FROM `nba-props-platform.logs`
WHERE jsonPayload.event = "merge_fallback"
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
```

#### 2.2 Dependency Check Detail Logging
**File:** `data_processors/analytics/analytics_base.py`
**Location:** Line 329 (dependency failure handler)

```python
# Enhanced dependency failure logging
logger.error("dependency_check_failed", extra={
    "event": "dependency_check_failed",
    "processor": self.processor_name,
    "game_date": str(analysis_date),
    "missing_critical": dep_check['missing'],
    "stale_fail": dep_check.get('stale_fail', []),
    "dependency_details": {
        table: {
            "status": details.get('status'),
            "last_update": details.get('last_update'),
            "expected_update": details.get('expected_update'),
            "staleness_hours": details.get('staleness_hours')
        }
        for table, details in dep_check.get('details', {}).items()
        if details.get('status') != 'available'
    }
})
```

**Query for dependency failures:**
```sql
SELECT
  timestamp,
  jsonPayload.processor,
  jsonPayload.missing_critical,
  jsonPayload.dependency_details
FROM `nba-props-platform.logs`
WHERE jsonPayload.event = "dependency_check_failed"
  AND jsonPayload.game_date = "2026-01-27"
```

---

### Phase 3: Add Progress Tracking (Medium Priority)

**Goal:** Detect stuck processors and timeouts before they happen

#### 3.1 Long-Running Processor Warnings
**File:** `data_processors/analytics/analytics_base.py`
**Location:** In run() method, add periodic heartbeat logging

```python
# After heartbeat.start() (line 262)
# Add progress logging every 60 seconds for long-running processors
import threading

def log_progress():
    while not self._stop_progress_logging.is_set():
        time.sleep(60)  # Log every minute
        elapsed = self.get_elapsed_seconds("total")
        logger.info("processor_progress", extra={
            "event": "processor_progress",
            "processor": self.processor_name,
            "game_date": str(data_date),
            "elapsed_seconds": elapsed,
            "current_step": self._get_current_step(),
            "stats": {
                "extract_time": self.stats.get('extract_time'),
                "transform_time": self.stats.get('transform_time'),
                "save_time": self.stats.get('save_time'),
                "rows_processed": self.stats.get('rows_processed', 0)
            }
        })

self._stop_progress_logging = threading.Event()
self._progress_thread = threading.Thread(target=log_progress, daemon=True)
self._progress_thread.start()
```

#### 3.2 Orchestrator Stuck Detection
**File:** `orchestration/cloud_functions/phase2_to_phase3/main.py`
**Location:** In periodic check function

```python
# Check for processors that haven't completed in expected time
expected_duration_minutes = 5  # Most processors complete in < 5 min
stuck_processors = []

for proc in EXPECTED_PROCESSORS:
    if proc not in completed_processors:
        # Check when it started (from pipeline_event_log)
        start_time = get_processor_start_time(proc, game_date)
        if start_time and (datetime.utcnow() - start_time).total_seconds() / 60 > expected_duration_minutes:
            stuck_processors.append({
                "processor": proc,
                "started_at": start_time.isoformat(),
                "elapsed_minutes": (datetime.utcnow() - start_time).total_seconds() / 60
            })

if stuck_processors:
    logger.warning("stuck_processors_detected", extra={
        "event": "stuck_processors_detected",
        "game_date": game_date,
        "stuck_processors": stuck_processors,
        "threshold_minutes": expected_duration_minutes
    })
```

---

### Phase 4: Log Analysis Queries (Implementation Aid)

**Goal:** Quick queries for common debugging scenarios

#### 4.1 Processing Order for a Date
```sql
-- See exact order processors ran for a game_date
SELECT
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', timestamp) as time,
  jsonPayload.processor,
  jsonPayload.duration_seconds,
  jsonPayload.records_processed,
  jsonPayload.dependencies_status
FROM `nba-props-platform.logs`
WHERE jsonPayload.event IN ("processor_started", "phase_timing")
  AND jsonPayload.game_date = @game_date
ORDER BY timestamp
```

#### 4.2 All Errors in Last 24h
```sql
-- Find all errors with context
SELECT
  timestamp,
  jsonPayload.processor,
  jsonPayload.event,
  jsonPayload.error_message,
  jsonPayload.reason,
  jsonPayload.game_date
FROM `nba-props-platform.logs`
WHERE jsonPayload.event IN ("merge_fallback", "dependency_check_failed", "streaming_buffer_active", "error")
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
ORDER BY timestamp DESC
```

#### 4.3 Timing Correlation Across Phases
```sql
-- See Phase 2→3→4 timing for a date
WITH phase2_complete AS (
  SELECT
    MIN(timestamp) as phase2_done,
    jsonPayload.game_date
  FROM `nba-props-platform.logs`
  WHERE jsonPayload.event = "orchestrator_progress"
    AND jsonPayload.will_trigger_next_phase = true
    AND jsonPayload.game_date = @game_date
  GROUP BY jsonPayload.game_date
),
phase3_complete AS (
  SELECT
    MAX(timestamp) as phase3_done,
    jsonPayload.game_date
  FROM `nba-props-platform.logs`
  WHERE jsonPayload.event = "phase_timing"
    AND jsonPayload.phase = "phase_3"
    AND jsonPayload.game_date = @game_date
  GROUP BY jsonPayload.game_date
)
SELECT
  p2.game_date,
  p2.phase2_done,
  p3.phase3_done,
  TIMESTAMP_DIFF(p3.phase3_done, p2.phase2_done, SECOND) as gap_seconds
FROM phase2_complete p2
LEFT JOIN phase3_complete p3 ON p2.game_date = p3.game_date
```

#### 4.4 Orchestrator Progress Timeline
```sql
-- See orchestrator progress over time
SELECT
  FORMAT_TIMESTAMP('%H:%M:%S', timestamp) as time,
  jsonPayload.completed_count,
  jsonPayload.expected_count,
  jsonPayload.completion_pct,
  jsonPayload.recently_completed,
  jsonPayload.missing_processors
FROM `nba-props-platform.logs`
WHERE jsonPayload.event = "orchestrator_progress"
  AND jsonPayload.game_date = @game_date
ORDER BY timestamp
```

---

## Implementation Priority

### Immediate (This Session)
1. ✅ **Create this plan document**
2. **Add MERGE fallback structured logging** (Phase 2.1)
   - File: `bigquery_save_ops.py`
   - Impact: Immediate visibility into why MERGEs fail
3. **Add streaming buffer logging** (Phase 2.1)
   - File: `bigquery_save_ops.py`
   - Impact: Understand DELETE failures

### High Priority (Next Session)
4. **Add processor start logging with dependencies** (Phase 1.1)
   - File: `analytics_base.py`
   - Impact: Answer "why did X run before Y?"
5. **Add phase timing logs** (Phase 1.2)
   - File: `analytics_base.py`
   - Impact: Timing correlation across processors

### Medium Priority (Future)
6. **Add orchestrator progress logging** (Phase 1.3)
   - Files: `phase2_to_phase3/main.py`, etc.
   - Impact: Timeout debugging
7. **Add long-running processor warnings** (Phase 3.1)
   - File: `analytics_base.py`
   - Impact: Detect stuck processors early

---

## Success Metrics

After implementation, we should be able to answer:

1. **Processing Order**
   - ✅ Query shows exact order processors started for a date
   - ✅ Query shows dependency readiness at start time
   - ✅ Query shows gaps between phase completions

2. **Error Diagnosis**
   - ✅ MERGE fallback reason logged with context
   - ✅ Streaming buffer conflicts logged with retry guidance
   - ✅ Dependency failures include table staleness details

3. **Timeout Prevention**
   - ✅ Orchestrator logs progress every processor completion
   - ✅ Warning logs at 80% of timeout deadline
   - ✅ Stuck processor detection for long-running jobs

---

## Configuration

**Environment Variables** (for gradual rollout):

```bash
# Enable structured logging (default: true in production)
ENABLE_STRUCTURED_LOGGING=true

# Enable progress logging for processors > N seconds (default: 120)
PROCESSOR_PROGRESS_LOG_THRESHOLD_SECONDS=120

# Enable orchestrator progress logging (default: true)
ENABLE_ORCHESTRATOR_PROGRESS_LOGS=true
```

---

## Testing Plan

1. **Local Testing**
   - Run processor with `ENABLE_STRUCTURED_LOGGING=true`
   - Verify JSON logs appear in Cloud Logging
   - Verify fields are queryable

2. **Production Validation**
   - Deploy to dev environment first
   - Run backfill job to generate logs
   - Validate queries return expected data
   - Monitor for any performance impact (should be negligible)

3. **Post-Deployment Validation**
   - Wait for next failure incident
   - Use new queries to diagnose root cause
   - Document actual time saved vs previous diagnosis approach

---

## Related Documents

- [Data Quality Investigation (2026-01-27)](./README.md)
- [Pipeline Event Logger](../../../shared/utils/pipeline_logger.py)
- [Structured Logging](../../../shared/utils/structured_logging.py)
- [BigQuery Save Operations](../../../data_processors/analytics/operations/bigquery_save_ops.py)

---

**Next Steps:**
1. Implement Phase 2.1 (MERGE fallback logging) - IMMEDIATE
2. Implement Phase 1.1-1.2 (timing logs) - HIGH PRIORITY
3. Create saved queries in BigQuery for common debugging scenarios
4. Update runbooks to reference these new logs
