# Result Pattern Migration Guide
**Created:** January 21, 2026
**Status:** Week 1 P0-1 Implementation
**Progress:** bigquery_utils ✅ | pubsub_client 🟡 | other files 🔜

---

## Overview

The Result pattern eliminates silent failures by providing structured error information. Instead of returning empty values (`[]`, `False`, `None`, `0`) on errors, functions return `Result` objects with detailed error context.

## Migration Status

### ✅ Completed

**bigquery_utils (6 functions)**
- `execute_bigquery()` → `execute_bigquery_v2()`
- `insert_bigquery_rows()` → `insert_bigquery_rows_v2()`
- `get_table_row_count()` → `get_table_row_count_v2()`
- `execute_bigquery_with_params()` → `execute_bigquery_with_params_v2()`
- `update_bigquery_rows()` → `update_bigquery_rows_v2()`
- `table_exists()` → `table_exists_v2()`

**Status:** Full v2 implementation with tests ✅
**Files:** `shared/utils/bigquery_utils_v2.py`, `tests/unit/utils/test_bigquery_utils_v2.py`

**Logging Enhanced:**
- Added `exc_info=True` to all exception handlers
- Stack traces now captured for debugging

### 🟡 In Progress

**pubsub_client.py (4 patterns)**
- `publish_message()` - Line 62-64 ✅ (exc_info added)
- `subscribe_to_messages()` handler - Needs Result pattern
- `subscribe_to_messages()` main - Needs Result pattern
- `create_subscription()` - Needs Result pattern

**Status:** Logging enhanced, Result pattern migration pending

### 🔜 Pending Migration

High-priority files from agent analysis:

1. **bin/backfill/verify_phase2_for_phase3.py** (2 functions)
   - `get_dates_with_data()` - Returns `set()` on error
   - `get_expected_game_dates()` - Silent fallback

2. **predictions/coordinator/distributed_lock.py** (1 function)
   - `_try_acquire()` - Returns `False`, loses error context

3. **predictions/coordinator/batch_staging_writer.py** (3 functions)
   - `write_to_staging()` - Partial Result implementation
   - `_check_for_duplicates()` - Returns `-1` on error
   - `consolidate_batch()` - Partial Result implementation

4. **predictions/coordinator/batch_state_manager.py** (1 pattern)
   - Non-atomic read-after-write race condition

5. **predictions/coordinator/missing_prediction_detector.py** (2 functions)
   - `detect_missing_predictions()` - Inconsistent error format
   - `_calculate_summary_stats()` - Silent failure

6. **predictions/coordinator/shared/backfill/checkpoint.py** (2 functions)
   - `_load_state()` - Returns default on corruption
   - `_save_state()` - Silent write failure

7. **shared/utils/metrics_utils.py** (2 functions)
   - `send_metric()` - Returns `False` on error
   - `create_metric_descriptor()` - Returns `False` on error

8. **shared/utils/player_name_resolver.py** (2 functions)
   - `resolve_to_nba_name()` - Returns original name on error
   - `is_valid_nba_player()` - Silent failure

---

## Migration Pattern

### Before (Silent Failure)
```python
def execute_bigquery(query: str) -> List[Dict]:
    try:
        results = client.query(query).result()
        return [dict(row) for row in results]
    except Exception as e:
        logger.error(f"Query failed: {e}")
        return []  # Silent failure - caller can't tell error vs empty
```

**Problem:** Caller sees `[]` for both "no data" and "error occurred"

### After (Result Pattern)
```python
from shared.utils.result import Result, ErrorType, classify_exception

def execute_bigquery_v2(query: str) -> Result[List[Dict]]:
    try:
        results = client.query(query).result()
        return Result.success([dict(row) for row in results])
    except NotFound as e:
        return Result.failure(
            error_type=ErrorType.PERMANENT,
            message="Table not found",
            exception=e,
            details={"query": query[:200]}
        )
    except Exception as e:
        return Result.failure(
            error_type=classify_exception(e),
            message=f"Query failed: {str(e)[:100]}",
            exception=e
        )
```

### Usage
```python
# Old way
results = execute_bigquery(query)
if not results:  # Ambiguous: error or no data?
    ...

# New way
result = execute_bigquery_v2(query)
if result.is_success:
    process_data(result.data)
elif result.is_retryable:
    # Transient error, schedule retry
    schedule_retry()
else:
    # Permanent error, alert
    send_alert(f"Query failed: {result.error.message}")
    logger.error(f"Error details: {result.error.to_dict()}")
```

---

## Quick Enhancement (Before Full Migration)

For files not yet migrated to Result pattern, add `exc_info=True` for better debugging:

```python
# Before
except Exception as e:
    logger.error(f"Failed: {e}")
    return False

# After
except Exception as e:
    logger.error(f"Failed: {e}", exc_info=True)  # ← Add this
    return False
```

**Impact:** Captures full stack traces without code restructuring

---

## Error Classification Guide

### Permanent Errors (won't be fixed by retry)
- `NotFound` - Table/resource doesn't exist
- `Forbidden`/`Unauthorized` - Permission denied
- `BadRequest` - Invalid syntax/input
- `ValueError`, `TypeError`, `KeyError` - Logic errors

### Transient Errors (may succeed on retry)
- `Timeout`, `DeadlineExceeded` - Operation took too long
- `ServiceUnavailable`, `Unavailable` - Service down
- `TooManyRequests`, `ResourceExhausted` - Rate limited
- `ConnectionError` - Network issues

### Unknown Errors
- Default classification when type can't be determined
- Treat as transient for safety (allow retry)

---

## Migration Priority

### Week 1 (Current)
- ✅ BigQuery utilities (CRITICAL - 8 patterns)
- ✅ Enhanced logging (`exc_info=True`)
- 🟡 Pub/Sub client (CRITICAL - 4 patterns)

### Week 2 (Recommended)
- Backfill verification (2 patterns)
- Distributed lock (1 pattern)
- Batch staging writer (3 patterns)

### Week 3 (Recommended)
- Batch state manager (1 pattern)
- Missing prediction detector (2 patterns)
- Checkpoint manager (2 patterns)

### Week 4 (Nice to have)
- Metrics utils (2 patterns)
- Player name resolver (2 patterns)

---

## Testing Strategy

### Unit Tests
```python
def test_success_case():
    result = function_v2("valid_input")
    assert result.is_success
    assert result.data == expected_data
    assert result.error is None

def test_permanent_failure():
    result = function_v2("missing_resource")
    assert result.is_failure
    assert result.error.type == ErrorType.PERMANENT
    assert not result.is_retryable

def test_transient_failure():
    result = function_v2("timeout_scenario")
    assert result.is_failure
    assert result.error.type == ErrorType.TRANSIENT
    assert result.is_retryable
```

### Integration Tests
- Verify error classification matches expected behavior
- Test retry logic with transient errors
- Validate alert routing with permanent errors

---

## Benefits

### Before Migration
- ❌ Silent failures hide problems
- ❌ Can't distinguish error types
- ❌ No retry guidance
- ❌ Limited debugging context
- ❌ Monitoring gaps

### After Migration
- ✅ All failures are visible
- ✅ Error types guide retry logic
- ✅ Structured error information
- ✅ Stack traces captured
- ✅ Monitorable error patterns

---

## References

- Result pattern implementation: `shared/utils/result.py`
- BigQuery v2 utilities: `shared/utils/bigquery_utils_v2.py`
- Unit test examples: `tests/unit/utils/test_bigquery_utils_v2.py`
- Agent findings: `docs/08-projects/current/week-1-improvements/AGENT-STUDY-WEEK1-2026-01-21.md`

---

**Next Steps:**
1. Complete pub/sub Result pattern migration
2. Migrate high-priority backfill and lock files
3. Add comprehensive test coverage
4. Update monitoring to track error types
5. Document retry strategies in runbooks
