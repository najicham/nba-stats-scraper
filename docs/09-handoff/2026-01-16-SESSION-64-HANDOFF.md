# Session 64 Handoff - Pipeline Reliability Fixes

**Date**: 2026-01-16
**Duration**: ~2.5 hours
**Focus**: Silent data loss prevention across pipeline

---

## Executive Summary

Investigated and fixed silent data loss issues across multiple pipeline services. Originally started investigating why "1-2 workers fail per batch" but discovered the actual failure rate was **30-40%** and the root cause was a bug pattern repeated in multiple services.

**Key Discovery**: A systematic bug pattern where services swallow exceptions and return 200/success even when writes fail. This pattern was found in 4+ services, causing silent data loss with no retry opportunity.

---

## Todo List for Next Session

| Priority | ID | Issue | Status | Effort |
|----------|-----|-------|--------|--------|
| ✅ | R-001 | Prediction Worker Silent Data Loss | **FIXED & DEPLOYED** | Done |
| ✅ | R-002 | Analytics Service Returns 200 on Failures | **FIXED & DEPLOYED** | Done |
| ✅ | R-003 | Precompute Service Returns 200 on Failures | **FIXED & DEPLOYED** | Done |
| P1 | R-004 | Precompute Completion Without Write Verification | Open | 1 hour |
| P2 | R-005 | Raw Processor Batch Lock Verification | Open | 1 hour |
| P2 | R-006 | Phase 4→5 Data Freshness Validation | Open | 1 hour |
| P3 | R-007 | End-to-End Data Reconciliation Job | Open | 2-3 hours |
| P3 | R-008 | Pub/Sub Failure Monitoring | Open | 30 min |

---

## What Was Done This Session

### 1. Root Cause Analysis

**Original Problem**: "1-2 workers fail silently per batch"

**Actual Problem**: 30-40% of workers failed silently due to a bug pattern where staging write failures were swallowed and completion events were always published.

**The Bug Pattern** (found in 4 places):
```python
# BAD: Always returns success
try:
    do_work()
except Exception:
    log_error()  # Swallow exception
return 200  # Always success!
```

**The Fix Pattern**:
```python
# GOOD: Propagate failures
try:
    success = do_work()
    if not success:
        return 500  # Trigger retry
except Exception:
    return 500  # Trigger retry
return 200  # Only on actual success
```

### 2. Fixes Deployed

#### R-001: Prediction Worker (DEPLOYED)
- **File**: `predictions/worker/worker.py`
- **Change**: `write_predictions_to_bigquery()` returns `bool`, handler returns 500 on failure
- **Image**: `prediction-worker:v36-layer1-fix`
- **Revision**: `prediction-worker-00036-xhq`

#### R-002: Analytics Service (DEPLOYED)
- **File**: `data_processors/analytics/main_analytics_service.py`
- **Change**: Returns 500 when all processors fail
- **Image**: `nba-phase3-analytics-processors:v2-r002-fix`
- **Revision**: `nba-phase3-analytics-processors-00068-5kh`

#### R-003: Precompute Service (DEPLOYED)
- **File**: `data_processors/precompute/main_precompute_service.py`
- **Change**: Returns 500 when all processors fail
- **Image**: `nba-phase4-precompute-processors:v2-r003-fix`
- **Revision**: `nba-phase4-precompute-processors-00041-c5n`

### 3. Stall Check Scheduler (CREATED)

```bash
gcloud scheduler jobs create http prediction-stall-check \
  --location=us-west2 \
  --schedule="*/15 18-23,0-2 * * *" \
  --uri="https://prediction-coordinator-756957797294.us-west2.run.app/check-stalled" \
  --http-method=POST \
  --oidc-service-account-email="scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com" \
  --body='{"stall_threshold_minutes": 10, "min_completion_pct": 95.0}'
```

---

## Remaining Issues (Detailed)

### R-004: Precompute Completion Without Write Verification (HIGH)

**File**: `data_processors/precompute/precompute_base.py:1842`

**Problem**: `_publish_completion_message(success=True)` is always called regardless of write success.

**Current Code**:
```python
def post_process(self) -> None:
    if self.table_name:
        self._publish_completion_message(success=True)  # Always True!
```

**Proposed Fix**:
```python
def post_process(self) -> None:
    if self.table_name:
        if hasattr(self, 'write_success') and not self.write_success:
            self._publish_completion_message(success=False, error="Write failures detected")
        else:
            self._publish_completion_message(success=True)
```

Also add `self.write_success = True` in `__init__` and set to `False` on write exceptions.

### R-005: Raw Processor Batch Lock Verification (MEDIUM)

**File**: `data_processors/raw/main_processor_service.py:776-780`

**Problem**: Batch lock marked "complete" without verifying BigQuery writes committed.

### R-006: Phase 4→5 Data Freshness Validation (MEDIUM)

**File**: `orchestration/cloud_functions/phase4_to_phase5/main.py`

**Problem**: Phase 5 triggered based on completion events, not actual data presence.

### R-007: End-to-End Data Reconciliation Job (MEDIUM)

**Problem**: No daily job verifies data completeness across pipeline phases.

### R-008: Pub/Sub Failure Monitoring (LOW)

**File**: `data_processors/precompute/precompute_base.py:1925-1927`

**Problem**: Pub/Sub publish failures logged but not monitored.

---

## Commits Made

```
fa939e9 docs(handoff): Session 64 - Pipeline reliability fixes
3673f67 fix(reliability): Return 500 on processor failures for Pub/Sub retry
c65ccaf fix(worker): Return 500 on staging write failure to trigger Pub/Sub retry
```

---

## Rollback Commands

```bash
# R-001: Prediction Worker
gcloud run services update-traffic prediction-worker \
  --region us-west2 \
  --to-revisions prediction-worker-00035-4xk=100

# R-002: Analytics Processors
gcloud run services update-traffic nba-phase3-analytics-processors \
  --region us-west2 \
  --to-revisions nba-phase3-analytics-processors-00067-xxx=100

# R-003: Precompute Processors
gcloud run services update-traffic nba-phase4-precompute-processors \
  --region us-west2 \
  --to-revisions nba-phase4-precompute-processors-00040-xxx=100
```

---

## Monitoring Points

### What to Watch For (Next 24 Hours)

1. **DLQ Messages**:
   ```bash
   gcloud pubsub subscriptions pull prediction-request-dlq-sub --limit=10 --auto-ack
   ```
   - Should see failed messages here instead of silent loss

2. **Worker Logs** - Search for:
   - `STAGING WRITE FAILED` - Staging failures being detected
   - `returning 500` - Proper error responses

3. **Analytics/Precompute Logs** - Search for:
   - `ALL.*processors failed` - 500 being returned correctly
   - `PARTIAL FAILURE` - Partial failures being logged

4. **Cloud Scheduler**:
   - Check `prediction-stall-check` job execution history
   - Runs every 15 min during 6 PM - 2 AM PT

### Expected Behavior Changes

| Scenario | Before | After |
|----------|--------|-------|
| Staging write fails | 204 → data lost | 500 → retry → DLQ |
| All processors fail | 200 → silent | 500 → retry |
| Batch stalls | Manual intervention | Auto-recovery via scheduler |

---

## Documentation Created

```
docs/08-projects/current/worker-reliability-investigation/
├── README.md                        # Project overview (updated)
├── RELIABILITY-ISSUES-TRACKER.md    # Master issue tracker
├── CODEBASE-RELIABILITY-AUDIT.md    # Full audit report
└── SILENT-DATA-LOSS-ANALYSIS.md     # Deep dive on R-001
```

---

## Quick Start for Next Session

```bash
# 1. Check current status
gcloud logging read 'resource.type="cloud_run_revision" AND (severity=ERROR OR severity=WARNING)' --limit=20 --format='table(timestamp,resource.labels.service_name,textPayload)'

# 2. Check DLQ
gcloud pubsub subscriptions pull prediction-request-dlq-sub --limit=5 --auto-ack

# 3. Continue with R-004
# File: data_processors/precompute/precompute_base.py
# Search for: post_process, _publish_completion_message, write_success
```

---

## Questions for Next Session

1. Should we continue with R-004? (Same bug pattern, HIGH priority)
2. Any issues observed overnight from today's deployments?
3. Should we implement R-007 (daily reconciliation) as a safety net?

---

## Session Notes

- Coordinator OOM issue identified (Session 63) but not fixed - needs memory increase or streaming
- Original "1-2 workers fail per batch" was actually 30-40% failure rate
- The stall detection workaround from Session 63 is now automated via Cloud Scheduler
- MLB services (mlb-phase3-analytics-processors, mlb-phase4-precompute-processors) share same code - may need same fixes if experiencing issues
