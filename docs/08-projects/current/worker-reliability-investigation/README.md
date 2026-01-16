# Worker Reliability Investigation

**Started**: 2026-01-16
**Status**: In Progress
**Priority**: P1 - Affects prediction coverage

---

## Problem Statement

1-2 workers per batch fail silently, resulting in missing predictions. The stall detection fix (Session 63) works around this by marking batches "complete with partial results," but the root cause is unknown.

---

## Investigation Findings

### Finding 1: Completion Event Published Before Staging Write Success (BUG)

**Location**: `predictions/worker/worker.py:1361-1362`

```python
except Exception as e:
    # ... log error
    # Don't raise - log and continue (graceful degradation)
```

**Impact**: If staging write fails, worker STILL publishes completion event. Coordinator increments progress counter, but no staging table exists.

**Evidence**: Coordinator log shows:
```
❌ Consolidation failed: NotFound: 404 Not found: Table nba-props-platform:nba_predictions._staging_batch_2026_01_16_1768529790_prediction_worker_00035_4xk_0a49f283
```

Worker `0a49f283` published completion but staging table doesn't exist.

### Finding 2: BigQuery Rate Limits on Execution Logger

**Location**: `predictions/worker/execution_logger.py`

**Error**:
```
execution_logger - ERROR - Error logging execution: 403 Exceeded rate limits: too many partitioned table update operations for this table
```

**Impact**: Non-fatal but causes noise. May contribute to worker slowdown under high concurrency.

### Finding 3: Metrics Utility Bug

**Error**:
```
Failed to send prediction_write_duration_seconds metric: 'NoneType' object has no attribute 'seconds'
```

**Location**: `shared/utils/metrics_utils.py`

**Impact**: Non-fatal metrics errors. Doesn't affect predictions but indicates a null reference bug.

### Finding 4: Pub/Sub Configuration

| Setting | Value | Note |
|---------|-------|------|
| ackDeadlineSeconds | 300 | 5 minutes - adequate |
| maxDeliveryAttempts | 5 | Before DLQ |
| Dead Letter Topic | prediction-request-dlq | Exists |

### Finding 5: Historical Stall Patterns

From coordinator logs:
| Batch | Progress | Completion % |
|-------|----------|--------------|
| batch_2026-01-11_1768193582 | 83/121 | 68.6% |
| batch_2026-01-11_1768192848 | 83/121 | 68.6% |
| batch_2026-01-04_1767920815 | 103/178 | 57.9% |
| batch_2025-12-21_1767469120 | 82/135 | 60.7% |

Pattern: 30-40% of workers fail, not "1-2 workers" as initially reported.

---

## Root Causes Identified

### RC1: Silent Staging Write Failures (CONFIRMED → FIXED)

Worker code at line 1361-1362 swallowed staging write exceptions and still published completion.

**Fix Applied** (2026-01-16):
- `write_predictions_to_bigquery()` now returns `bool` (True=success, False=failure)
- `handle_prediction_request()` checks return value
- On failure: returns 500 → triggers Pub/Sub retry → after max retries → DLQ
- Completion event only published on staging write success

### RC2: Potential Race Condition (NEEDS VERIFICATION)

Hypothesis: Coordinator triggers consolidation immediately when last completion event arrives, but BigQuery may not have fully committed the last staging table yet.

**Verification Needed**: Check if staging tables are eventually visible or permanently missing.

### RC3: Worker Timeout/OOM (NEEDS INVESTIGATION)

Workers have 5-minute timeout and 2GB memory. Heavy ML model inference may cause some workers to exceed limits.

---

## Proposed Fixes

### Fix 1: Conditional Completion Event Publishing (HIGH PRIORITY)

```python
# In write_predictions_to_bigquery
if result.success:
    logger.info(...)
    # Track successful write
else:
    logger.error(f"Staging write failed: {result.error_message}")
    return False  # Signal failure to caller

# In handle_prediction_request
write_success = write_predictions_to_bigquery(predictions, batch_id=batch_id)
if write_success:
    publish_completion_event(player_lookup, game_date_str, len(predictions), batch_id=batch_id)
else:
    # Return 500 to trigger Pub/Sub retry
    return ('Staging write failed', 500)
```

### Fix 2: Add Delay Before Consolidation

Add a small delay (5-10 seconds) after receiving last completion event before triggering consolidation, to allow BigQuery to fully commit.

### Fix 3: Verify Staging Tables Before Consolidation

Before MERGE, verify all expected staging tables exist. If any missing, wait and retry.

---

## Validation Plan

### Phase 1: Verify Root Cause
- [ ] Deploy coordinator with extra logging around consolidation
- [ ] Track which specific workers fail (correlate with logs)
- [ ] Monitor dead letter queue for failed messages

### Phase 2: Implement Fix 1
- [ ] Modify worker to only publish completion on staging success
- [ ] Test locally with simulated failures
- [ ] Deploy to staging environment
- [ ] Monitor for 24 hours

### Phase 3: Implement Fix 2/3 (if needed)
- [ ] Add consolidation delay
- [ ] Add staging table verification
- [ ] Monitor for improvement

---

## Metrics to Track

| Metric | Current | Target |
|--------|---------|--------|
| Batch completion rate | 60-70% | >95% |
| Workers failing per batch | 30-40% | <5% |
| Consolidation success rate | Unknown | 100% |

---

## Coordinator OOM Analysis

### Evidence

```
2026-01-16 02:32:56 - CRITICAL - WORKER TIMEOUT (pid:6)
2026-01-16 02:32:58 - ERROR - Worker (pid:6) was sent SIGKILL! Perhaps out of memory?
```

### Resource Configuration

| Setting | Value |
|---------|-------|
| Memory | 2Gi |
| CPU | 2 |
| Timeout | 600s |

### Memory Pressure Points

1. **Historical Games Batch Loading** (`/start` endpoint)
   - Loads ~400 players × 30 games × game data into memory
   - Passed to each Pub/Sub message
   - Memory held during entire batch publishing phase

2. **Stall Check Processing** (`/check-stalled` endpoint)
   - Processes multiple stalled batches in a loop
   - Each batch triggers synchronous consolidation
   - Memory not freed between consolidations

3. **Consolidation UNION ALL Query**
   - Builds query string with UNION ALL of all staging tables
   - Large query strings for batches with many workers

### Potential Fixes

1. **Increase coordinator memory to 4Gi** (quick fix)
2. **Process stalled batches with explicit GC between iterations**
3. **Stream historical games instead of batch loading**
4. **Make consolidation async (non-blocking)**

---

## Cloud Scheduler for Stall Checks

### Recommendation: Add Scheduled `/check-stalled` Job

The `/check-stalled` endpoint should be called automatically during prediction hours to catch stalled batches before they age out of the stall window.

### Proposed Configuration

```bash
gcloud scheduler jobs create http prediction-stall-check \
  --location=us-west2 \
  --schedule="*/15 18-23,0-2 * * *" \
  --uri="https://prediction-coordinator-756957797294.us-west2.run.app/check-stalled" \
  --http-method=POST \
  --oidc-service-account-email="scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com" \
  --body='{"stall_threshold_minutes": 10, "min_completion_pct": 95.0}' \
  --headers="Content-Type=application/json" \
  --description="Check for stalled prediction batches every 15 minutes during game hours"
```

### Schedule Breakdown

| Time Range | Reason |
|------------|--------|
| 18-23 (6 PM - 11 PM) | NBA game hours |
| 0-2 (12 AM - 2 AM) | Late games finish |
| */15 | Every 15 minutes |

### Expected Behavior

1. Scheduler calls `/check-stalled` with OIDC auth
2. Coordinator checks all active batches in Firestore
3. Batches stalled >10 minutes with >95% completion get marked complete
4. Consolidation triggers for completed batches
5. No manual intervention needed

### Prerequisites

- [x] `scheduler-orchestration@...` service account has `roles/run.invoker` on coordinator
- [ ] Deploy job after verifying coordinator handles concurrent stall checks safely

### Monitoring

Add alerts for:
- Stalled batches detected (warning)
- Stall check failures (error)
- High stall rate (>10% of batches) - indicates systemic issue

---

## Related Issues

- Session 63: Deployed stall detection fix
- Coordinator OOM: Observed during /check-stalled processing
- Cloud Scheduler: Consider scheduled stall checks

---

## Files Involved

| File | Role |
|------|------|
| `predictions/worker/worker.py` | Worker prediction handler |
| `predictions/worker/batch_staging_writer.py` | Staging table writes |
| `predictions/coordinator/coordinator.py` | Batch orchestration |
| `predictions/coordinator/batch_state_manager.py` | Firestore state |

---

## Deployment Log

### 2026-01-16: Layer 1 Fix + Stall Scheduler

**Worker Deployment:**
- Image: `gcr.io/nba-props-platform/prediction-worker:v36-layer1-fix`
- Revision: `prediction-worker-00036-xhq`
- Changes: Staging write failures now return 500, triggering Pub/Sub retry

**Cloud Scheduler Job Created:**
- Job: `prediction-stall-check`
- Schedule: `*/15 18-23,0-2 * * *` (every 15 min during game hours, PT)
- Endpoint: `POST /check-stalled`
- Body: `{"stall_threshold_minutes": 10, "min_completion_pct": 95.0}`

**Rollback Command (if needed):**
```bash
gcloud run services update-traffic prediction-worker \
  --region us-west2 \
  --to-revisions prediction-worker-00035-4xk=100
```

---

## Deep Dive Documents

- **[SILENT-DATA-LOSS-ANALYSIS.md](./SILENT-DATA-LOSS-ANALYSIS.md)** - Comprehensive multi-layer defense strategy
