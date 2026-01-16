# Reliability Issues Tracker

**Created**: 2026-01-16
**Last Updated**: 2026-01-16
**Status**: Active

This document tracks all reliability issues identified in the codebase audit, their status, and implementation details.

---

## Issue Summary

| ID | Title | Severity | Status | Service |
|----|-------|----------|--------|---------|
| R-001 | Prediction Worker Silent Data Loss | HIGH | **FIXED** | prediction-worker |
| R-002 | Analytics Service Returns 200 on Failures | HIGH | **FIXED** | analytics-processors |
| R-003 | Precompute Service Returns 200 on Failures | HIGH | **FIXED** | precompute-processors |
| R-004 | Precompute Completion Without Write Verification | HIGH | **FIXED** | precompute-base |
| R-005 | Raw Processor Batch Lock No Write Verification | MEDIUM | Open | raw-processors |
| R-006 | Phase 4→5 No Data Freshness Validation | MEDIUM | **FIXED** | phase4-to-phase5 |
| R-007 | No End-to-End Data Reconciliation | MEDIUM | Open | pipeline-wide |
| R-008 | Pub/Sub Publish Failures Swallowed | LOW | **FIXED** | precompute-base |

---

## Detailed Issue Descriptions

### R-001: Prediction Worker Silent Data Loss [FIXED]

**Severity**: HIGH
**Status**: FIXED (2026-01-16)
**Service**: `prediction-worker`
**Deployed**: `prediction-worker:v36-layer1-fix` (revision `00036-xhq`)

#### Problem
Workers published completion events even when BigQuery staging writes failed. The coordinator thought workers succeeded, but no staging tables existed. Consolidation failed with "Table not found" errors.

#### Root Cause
```python
# worker.py:1349-1362 (BEFORE)
except Exception as e:
    logger.error(f"Error writing to staging: {e}")
    # Don't raise - log and continue (graceful degradation)  # BUG!

# worker.py:479-486 (BEFORE)
write_predictions_to_bigquery(predictions, batch_id=batch_id)  # No return check
publish_completion_event(...)  # Always executed!
return ('', 204)  # Always success!
```

#### Solution Implemented
```python
# worker.py (AFTER)
def write_predictions_to_bigquery(...) -> bool:
    """Returns True on success, False on failure."""
    if result.success:
        return True
    return False  # Signal failure

# In handle_prediction_request:
write_success = write_predictions_to_bigquery(...)
if not write_success:
    return ('Staging write failed - triggering retry', 500)  # Pub/Sub retries!
publish_completion_event(...)  # Only on success
return ('', 204)
```

#### Verification
- Worker health check passing
- DLQ empty (no immediate failures)
- Next batch will validate fix

---

### R-002: Analytics Service Returns 200 on Failures [FIXED]

**Severity**: HIGH
**Status**: FIXED (2026-01-16)
**Service**: `analytics-processors`
**File**: `data_processors/analytics/main_analytics_service.py`
**Lines**: 195-230

#### Problem
The `/process` endpoint returned HTTP 200 even when individual processors failed with exceptions or errors.

#### Root Cause
```python
# BEFORE (Lines 195-200)
return jsonify({
    "status": "completed",  # Always says "completed"
    "source_table": source_table,
    "game_date": game_date,
    "results": results  # May contain {"status": "exception"} entries
}), 200  # Always 200!
```

#### Impact
- Pub/Sub ACKs the message immediately (no retry opportunity)
- Downstream Phase 4 receives "success" signal
- Phase 4 processors run on incomplete Phase 3 data
- Predictions ultimately use incomplete analytics

#### Solution Implemented
```python
# AFTER - Check for failures and return appropriate status
failures = [r for r in results if r.get('status') in ('error', 'exception', 'timeout')]
successes = [r for r in results if r.get('status') == 'success']

if not successes and failures:
    # All failed - return 500 to trigger Pub/Sub retry
    return jsonify({"status": "failed", ...}), 500

if failures:
    # Partial failure - return 200 but indicate partial status
    return jsonify({"status": "partial_failure", ...}), 200

# All succeeded
return jsonify({"status": "completed", ...}), 200
```

#### Deployment Required
Service needs redeployment to pick up changes.

---

### R-003: Precompute Service Returns 200 on Failures [FIXED]

**Severity**: HIGH
**Status**: FIXED (2026-01-16)
**Service**: `precompute-processors`
**File**: `data_processors/precompute/main_precompute_service.py`
**Lines**: 146-180

#### Problem
Same pattern as R-002. Returned 200 even when processors failed.

#### Root Cause
```python
# BEFORE (Lines 146-151)
return jsonify({
    "status": "completed",
    "source_table": source_table,
    "analysis_date": analysis_date,
    "results": results
}), 200
```

#### Impact
- Phase 4 completion events sent even on failures
- Phase 4→5 orchestrator triggers predictions
- Predictions run with stale/incomplete ML features

#### Solution Implemented
Same pattern as R-002 - check for failures and return 500 if all failed.

#### Deployment Required
Service needs redeployment to pick up changes.

---

### R-004: Precompute Completion Without Write Verification [FIXED]

**Severity**: HIGH
**Status**: FIXED (2026-01-15)
**Service**: `precompute-base`
**File**: `data_processors/precompute/precompute_base.py`
**Lines**: 220-222, 1389-1390, 1848-1859

#### Problem
`_publish_completion_message(success=True)` was always called with `success=True` in `post_process()`, regardless of whether writes actually succeeded. Specifically, when BigQuery writes failed due to streaming buffer conflicts, the rows were skipped but completion was still published as success.

#### Root Cause
```python
# Line 1842 (BEFORE)
def post_process(self) -> None:
    """Post-processing - log summary stats and publish completion message."""
    # ... logging ...
    if self.table_name:
        self._publish_completion_message(success=True)  # Always True!
```

The streaming buffer failure path at line 1385 returned early without raising an exception, so `post_process()` still published success=True.

#### Impact
This is the SAME BUG PATTERN as R-001:
- Processor runs, write blocked by streaming buffer
- `rows_skipped` set but no exception raised
- Completion published as "success"
- Phase 4→5 orchestrator receives "success"
- Predictions triggered on incomplete data

#### Solution Implemented
1. Added `self.write_success = True` flag in `__init__()` (line 220-222)
2. Set `self.write_success = False` when streaming buffer blocks writes (line 1389-1390)
3. Check `write_success` in `post_process()` before publishing (lines 1848-1859)

```python
# __init__ (line 220-222)
# Write success tracking (R-004: verify writes before publishing completion)
self.write_success = True

# save_precompute streaming buffer handler (line 1389-1390)
if "streaming buffer" in str(load_e).lower():
    # ... existing logging ...
    # R-004: Mark write as failed to prevent incorrect success completion message
    self.write_success = False
    return

# post_process (lines 1848-1859)
if self.table_name:
    # R-004: Verify write success before publishing completion
    if hasattr(self, 'write_success') and not self.write_success:
        logger.warning(f"⚠️ Publishing completion with success=False due to write failure")
        self._publish_completion_message(
            success=False,
            error=f"Write failures detected: {self.stats.get('rows_skipped', 0)} rows skipped"
        )
    else:
        self._publish_completion_message(success=True)
```

#### Verification
- After deployment, monitor logs for `"Publishing completion with success=False"` warnings
- DLQ should receive messages for failed writes instead of silent data loss

---

### R-005: Raw Processor Batch Lock No Write Verification

**Severity**: MEDIUM
**Status**: Open
**Service**: `raw-processors`
**File**: `data_processors/raw/main_processor_service.py`
**Lines**: 776-780

#### Problem
Batch processors (ESPN rosters, BR rosters, OddsAPI) update Firestore lock status based on processor's `success` flag, but don't verify BigQuery writes actually committed.

#### Current Code
```python
# Lines 776-780
lock_ref.update({
    'status': 'complete' if success else 'failed',
    'completed_at': datetime.now(timezone.utc),
    'stats': batch_processor.get_processor_stats()
})
```

#### Impact
- Lock marked "complete"
- BigQuery transaction could have failed to commit
- Subsequent Pub/Sub messages for same batch are skipped
- Data remains incomplete with no retry

#### Proposed Fix
Add verification query after marking complete:
```python
if success:
    # Verify data actually exists in BigQuery
    verification_passed = batch_processor.verify_write_success()
    lock_ref.update({
        'status': 'complete' if verification_passed else 'unverified',
        'completed_at': datetime.now(timezone.utc),
        'stats': batch_processor.get_processor_stats(),
        'verified': verification_passed
    })
    if not verification_passed:
        logger.warning(f"Batch marked complete but verification failed - may need manual review")
```

---

### R-006: Phase 4→5 No Data Freshness Validation [FIXED]

**Severity**: MEDIUM
**Status**: FIXED (2026-01-15)
**Service**: `phase4-to-phase5`
**File**: `orchestration/cloud_functions/phase4_to_phase5/main.py`

#### Problem
Orchestrator triggered Phase 5 when all completion events were received, but didn't verify the data actually existed in BigQuery. This was a belt-and-suspenders check to catch cases where R-004 might not have caught failures.

#### Impact
- If a processor published "success" but write failed
- Or if data was stale from a previous run
- Predictions would run on incorrect/missing data

#### Solution Implemented
Added `verify_phase4_data_ready()` function that queries BigQuery to confirm all required Phase 4 tables have data for the game date before triggering predictions.

Key features:
1. Verifies 5 required Phase 4 tables have data
2. Returns row counts for each table
3. Sends Slack alert if data is missing
4. Still triggers predictions (same as timeout behavior) but with visibility

```python
# Added to trigger_phase5()
is_ready, missing_tables, table_counts = verify_phase4_data_ready(game_date)
if not is_ready:
    logger.warning(f"R-006: Data freshness check FAILED for {game_date}")
    send_data_freshness_alert(game_date, missing_tables, table_counts)

# Verification results included in trigger message
message = {
    ...
    'data_freshness_verified': is_ready,
    'missing_tables': missing_tables if not is_ready else [],
    'table_row_counts': table_counts
}
```

#### Verification
- Monitor Cloud Function logs for `R-006:` prefixed messages
- Slack alerts will be sent if data freshness checks fail
- Trigger messages now include `data_freshness_verified` field

---

### R-007: No End-to-End Data Reconciliation

**Severity**: MEDIUM
**Status**: Open
**Service**: Pipeline-wide

#### Problem
No daily job verifies data completeness across all pipeline phases. If Phase 2 partially fails, all downstream phases run on incomplete data with no detection.

#### Impact
- Silent data gaps accumulate over time
- Prediction quality degrades without obvious cause
- Issues only discovered during manual audits

#### Proposed Solution
Create a Cloud Function or Cloud Run job that runs daily:

```python
def daily_pipeline_reconciliation():
    """
    Verify data completeness across all pipeline phases.
    Run daily at 6 AM ET (after overnight processing).
    """
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

    # Phase 1: Check games scraped
    games_expected = get_games_from_schedule(yesterday)

    # Phase 2: Check raw data
    boxscores_actual = query_bdl_boxscores_count(yesterday)

    # Phase 3: Check analytics
    player_summaries = query_player_game_summary_count(yesterday)

    # Phase 4: Check precompute
    ml_features = query_ml_feature_store_count(yesterday)

    # Phase 5: Check predictions
    predictions = query_predictions_count(yesterday)

    # Compare and alert on gaps
    gaps = []
    if boxscores_actual < games_expected * 10:  # ~10 players per game minimum
        gaps.append(f"Phase 2: {boxscores_actual} boxscores < expected")
    # ... more checks ...

    if gaps:
        send_reconciliation_alert(yesterday, gaps)
```

---

### R-008: Pub/Sub Publish Failures Swallowed [FIXED]

**Severity**: LOW
**Status**: FIXED (2026-01-15)
**Service**: `precompute-base`
**File**: `data_processors/precompute/precompute_base.py`
**Lines**: 1942-1958

#### Problem
Pub/Sub publish failures were logged as warnings but had no alerting, causing silent pipeline stalls.

```python
# BEFORE
except Exception as e:
    logger.warning(f"Failed to publish completion message: {e}")
    # Don't fail the whole processor if Pub/Sub publishing fails
```

#### Impact
- Downstream phases never trigger
- Current run marked as success
- Pipeline stalls silently with no visibility

#### Solution Implemented
Added notification system alert for Pub/Sub failures. The behavior of not failing the processor is preserved (correct - prevents data loss), but now there's visibility via Slack alerts.

```python
# AFTER
except Exception as e:
    logger.warning(f"Failed to publish completion message: {e}")
    # R-008: Add monitoring for Pub/Sub failures
    try:
        notify_warning(
            title=f"R-008: Pub/Sub Publish Failed - {self.__class__.__name__}",
            message="Failed to publish Phase 4 completion. Downstream may not trigger.",
            details={
                'processor': self.__class__.__name__,
                'topic': 'nba-phase4-precompute-complete',
                'table': self.table_name,
                'error': str(e)
            }
        )
    except Exception as notify_err:
        logger.debug(f"Could not send notification: {notify_err}")
```

#### Verification
- Monitor Slack for `R-008: Pub/Sub Publish Failed` warnings
- Logs will show both the warning and notification attempt

Create alert on metric threshold.

---

## Implementation Priority

### Phase 1: Immediate (This Session) - COMPLETE
- [x] R-001: Prediction Worker Silent Data Loss - **FIXED & DEPLOYED**
- [x] R-002: Analytics Service Returns 200 on Failures - **FIXED** (needs deploy)
- [x] R-003: Precompute Service Returns 200 on Failures - **FIXED** (needs deploy)

### Phase 2: Short-term (Next Session)
- [ ] R-004: Precompute Completion Without Write Verification
- [ ] R-006: Phase 4→5 No Data Freshness Validation

### Phase 3: Medium-term (Future)
- [ ] R-005: Raw Processor Batch Lock Verification
- [ ] R-007: End-to-End Data Reconciliation
- [ ] R-008: Pub/Sub Failure Monitoring

---

## Deployment Status

| Service | Image | Fix | Deployed | Revision |
|---------|-------|-----|----------|----------|
| prediction-worker | v36-layer1-fix | R-001 | ✅ Yes | 00036-xhq |
| nba-phase3-analytics-processors | v2-r002-fix | R-002 | ✅ Yes | 00068-5kh |
| nba-phase4-precompute-processors | v2-r003-fix | R-003 | ✅ Yes | 00041-c5n |

### Rollback Commands (if needed)
```bash
# R-001 Rollback
gcloud run services update-traffic prediction-worker --region us-west2 --to-revisions prediction-worker-00035-4xk=100

# R-002 Rollback
gcloud run services update-traffic nba-phase3-analytics-processors --region us-west2 --to-revisions nba-phase3-analytics-processors-00067-xxx=100

# R-003 Rollback
gcloud run services update-traffic nba-phase4-precompute-processors --region us-west2 --to-revisions nba-phase4-precompute-processors-00040-xxx=100
```

---

## Verification Checklist

After implementing fixes, verify:

- [ ] Unit tests pass for error scenarios
- [ ] Integration tests verify retry behavior
- [ ] Logs show correct error messages
- [ ] Metrics/alerts fire on failures
- [ ] DLQ receives failed messages
- [ ] End-to-end pipeline runs successfully

---

## Related Documents

- [README.md](./README.md) - Project overview
- [SILENT-DATA-LOSS-ANALYSIS.md](./SILENT-DATA-LOSS-ANALYSIS.md) - Deep dive on R-001
- [CODEBASE-RELIABILITY-AUDIT.md](./CODEBASE-RELIABILITY-AUDIT.md) - Full audit report
