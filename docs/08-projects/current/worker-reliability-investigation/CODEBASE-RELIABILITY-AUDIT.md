# Codebase Reliability Audit

**Date**: 2026-01-16
**Scope**: All processors, workers, and orchestration services
**Purpose**: Identify silent failure patterns similar to prediction worker bug

---

## Executive Summary

Analyzed 12+ Cloud Run services and 40+ processors for reliability issues. Found several patterns that could lead to silent data loss or incorrect pipeline behavior.

| Severity | Issues Found | Services Affected |
|----------|--------------|-------------------|
| **HIGH** | 2 | Analytics, Precompute |
| **MEDIUM** | 3 | Raw Processor, Orchestration |
| **LOW** | 2 | Various |

---

## Issues Identified

### ISSUE 1: Analytics Service Returns 200 on Partial Failures (HIGH)

**Location**: `data_processors/analytics/main_analytics_service.py:195-200`

**Problem**: The `/process` endpoint returns HTTP 200 even when processors fail:

```python
return jsonify({
    "status": "completed",  # Says "completed" even with failures!
    "source_table": source_table,
    "game_date": game_date,
    "results": results  # Contains "status": "exception" entries
}), 200  # Always 200
```

**Impact**:
- Pub/Sub ACKs the message (no retry)
- Downstream phases receive "success" signal but data may be incomplete
- No alerting on partial failures

**Evidence**: Looking at `results` array - individual processors can have `"status": "exception"` but overall response is 200.

**Fix Required**:
```python
# Count failures
failures = [r for r in results if r['status'] in ('error', 'exception', 'timeout')]
if failures:
    # Return 207 Multi-Status or 500 for critical failures
    return jsonify({
        "status": "partial_failure",
        "failures": len(failures),
        "results": results
    }), 207  # Or 500 if critical processors failed
```

---

### ISSUE 2: Precompute Service Returns 200 on Partial Failures (HIGH)

**Location**: `data_processors/precompute/main_precompute_service.py:146-151`

**Problem**: Same pattern as Analytics - returns 200 even when processors fail.

```python
return jsonify({
    "status": "completed",
    "source_table": source_table,
    "analysis_date": analysis_date,
    "results": results  # May contain failures
}), 200
```

**Impact**: Same as Issue 1. Phase 4 may report "complete" but ML Feature Store could have failed, causing Phase 5 predictions to use stale data.

**Fix Required**: Same pattern as Issue 1.

---

### ISSUE 3: Completion Events Published Without Write Verification (MEDIUM)

**Location**: `data_processors/precompute/precompute_base.py:1842`

**Problem**: `_publish_completion_message(success=True)` is called in `post_process()` after `run()` returns. But `run()` can return True even if some rows failed to write.

```python
def post_process(self) -> None:
    """Post-processing - log summary stats and publish completion message."""
    # ... logging ...
    if self.table_name:
        self._publish_completion_message(success=True)  # Always "success=True"!
```

**Impact**: Downstream services receive completion signals for data that may not have been fully written.

**Pattern**: This is the same bug we fixed in prediction worker - completion published before verifying write success.

**Fix Required**:
```python
def post_process(self) -> None:
    # Only publish if all writes succeeded
    if self.write_success and self.table_name:
        self._publish_completion_message(success=True)
    elif self.table_name:
        self._publish_completion_message(success=False, error="Write failures detected")
```

---

### ISSUE 4: Raw Processor Batch Lock Doesn't Verify Write Success (MEDIUM)

**Location**: `data_processors/raw/main_processor_service.py:776-780`

**Problem**: Batch processors update lock status based on `success` flag, but don't verify BigQuery writes actually committed.

```python
lock_ref.update({
    'status': 'complete' if success else 'failed',
    'completed_at': datetime.now(timezone.utc),
    'stats': batch_processor.get_processor_stats()
})
```

**Impact**: Lock marked "complete" but BigQuery transaction could have failed to commit. Subsequent batch attempts skip processing.

**Fix Required**: Add write verification or retry logic.

---

### ISSUE 5: Phase 4→5 Orchestrator No Validation of Data Freshness (MEDIUM)

**Location**: `orchestration/cloud_functions/phase4_to_phase5/main.py`

**Problem**: Orchestrator triggers Phase 5 when all completion events received, but doesn't verify the data is actually fresh/complete in BigQuery.

**Impact**: If a processor publishes "success" but write failed (Issue 3), predictions run on stale data.

**Fix Required**: Add pre-trigger validation:
```python
def verify_phase4_data_ready(game_date: str) -> bool:
    """Verify Phase 4 tables have fresh data for game_date."""
    # Query BigQuery to confirm ml_feature_store has today's data
    # Query player_daily_cache has today's players
    # etc.
```

---

### ISSUE 6: No End-to-End Data Reconciliation (MEDIUM)

**Problem**: No daily job verifies data completeness across all pipeline phases.

**Current State**:
- Phase 2 raw processors write to BigQuery
- Phase 3 analytics depends on Phase 2
- Phase 4 precompute depends on Phase 3
- Phase 5 predictions depends on Phase 4

If Phase 2 partially fails, all downstream phases may run on incomplete data with no detection.

**Fix Required**: Daily reconciliation job that:
1. Gets expected data (games scheduled, players expected)
2. Queries each phase's output tables
3. Compares and alerts on gaps

---

### ISSUE 7: Pub/Sub Message Publishing Failures Swallowed (LOW)

**Location**: `data_processors/precompute/precompute_base.py:1926`

```python
except Exception as e:
    logger.warning(f"Failed to publish completion message: {e}")
    # Don't fail the whole processor if Pub/Sub publishing fails
```

**Impact**: If completion event fails to publish, downstream phases never trigger. But current run succeeds.

**Assessment**: This is intentional - Pub/Sub failures shouldn't cause data processing to fail. However, it could cause pipeline stalls.

**Recommendation**: Add monitoring for Pub/Sub publish failures. Alert if pattern emerges.

---

### ISSUE 8: Notification Failures Don't Affect Processing (LOW)

**Location**: Multiple services wrap `notify_*` calls in try/except.

**Assessment**: This is correct behavior. Notification failures shouldn't affect data processing.

---

## Services Analysis Summary

| Service | Error Handling | Completion Events | Risk Level |
|---------|---------------|-------------------|------------|
| **Prediction Worker** | FIXED | FIXED | Low |
| **Prediction Coordinator** | Good | Good | Low |
| **Raw Processor** | Good | N/A | Low |
| **Analytics Service** | Returns 200 on failures | Per-processor | **HIGH** |
| **Precompute Service** | Returns 200 on failures | Per-processor | **HIGH** |
| **Phase 4→5 Orchestrator** | Good | N/A | Medium |
| **Grading Service** | Unknown | Unknown | Unknown |

---

## Recommended Actions

### Immediate (P1)

1. **Fix Analytics Service** - Return non-200 on processor failures
2. **Fix Precompute Service** - Same pattern

### Short-term (P2)

3. **Add write verification** to precompute base class
4. **Add pre-trigger validation** to Phase 4→5 orchestrator

### Medium-term (P3)

5. **Create daily reconciliation job** - Cross-phase data verification
6. **Add Pub/Sub failure monitoring** - Alert on publish failures

---

## Code Patterns to Avoid

### Bad: Swallow Exception and Return Success
```python
try:
    write_to_bigquery(data)
except Exception as e:
    logger.error(f"Write failed: {e}")
    # DON'T return 200 here!
return jsonify({"status": "success"}), 200
```

### Good: Propagate Failures
```python
try:
    success = write_to_bigquery(data)
    if not success:
        return jsonify({"status": "error"}), 500
except Exception as e:
    logger.error(f"Write failed: {e}")
    return jsonify({"status": "error", "message": str(e)}), 500
return jsonify({"status": "success"}), 200
```

### Bad: Publish Completion Before Verification
```python
def process():
    write_to_bigquery(data)  # May fail silently
    publish_completion_event()  # Always runs!
```

### Good: Conditional Completion Publishing
```python
def process():
    success = write_to_bigquery(data)
    if success:
        publish_completion_event()
    else:
        return error_response()
```

---

## Testing Recommendations

1. **Unit tests** for error propagation - verify 500 returned on failures
2. **Integration tests** for completion event timing
3. **Chaos testing** - inject BigQuery failures, verify behavior
4. **End-to-end validation** - run full pipeline and verify data completeness

---

## Appendix: Files Reviewed

| File | Lines | Findings |
|------|-------|----------|
| `predictions/worker/worker.py` | 1400+ | FIXED |
| `predictions/coordinator/coordinator.py` | 1100+ | Good |
| `data_processors/raw/main_processor_service.py` | 1000+ | Issue 4 |
| `data_processors/analytics/main_analytics_service.py` | 350+ | Issue 1 |
| `data_processors/precompute/main_precompute_service.py` | 300+ | Issue 2 |
| `data_processors/precompute/precompute_base.py` | 1900+ | Issue 3, 7 |
| `orchestration/cloud_functions/phase4_to_phase5/main.py` | 200+ | Issue 5 |
