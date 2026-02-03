# Alert Investigation - Feb 3, 2026

**Date:** 2026-02-03
**Status:** RESOLVED
**Session:** Opus Investigation

---

## Summary

Investigated Slack alerts about auth errors and HTTP 400s. Found and fixed several infrastructure issues.

---

## Alerts Received

1. **"NBA Pipeline Auth Errors Detected"** - nba-phase2-raw-processors
2. **"NBA Scrapers - HTTP Errors Detected"** - nba-scrapers (400 errors)

---

## Root Cause Analysis

### Issue 1: "Auth Errors" - Actually Instance Availability

**Finding:** NOT actual auth errors. The metric name is misleading.

**Real Issue:** Cloud Run instances unavailable during burst activity at 04:00 UTC.

```
The request was aborted because there was no available instance
```

**Root Cause:**
- Phase 2 max instances: 5
- Container concurrency: 10
- Max capacity: 50 requests
- Burst activity exceeded capacity (~20+ dropped requests)

**Fix Applied:**
```bash
gcloud run services update nba-phase2-raw-processors \
  --region=us-west2 \
  --max-instances=10
```

**New Capacity:** 100 concurrent requests

---

### Issue 2: Schedule Status Not Updating

**Finding:** 3 of 4 Feb 2 games showed "Scheduled" status even though games were Final.

| Game | Live Status | Schedule Status |
|------|-------------|-----------------|
| NOP @ CHA | Final | Final |
| HOU @ IND | Final | Scheduled |
| MIN @ MEM | Final | Scheduled |
| PHI @ LAC | In Progress | Scheduled |

**Root Cause:**
The `fix-stale-schedule` job uses this condition:
```sql
WHERE game_date < CURRENT_DATE('America/New_York')
```

At 11:24 PM ET on Feb 2, `CURRENT_DATE` is still Feb 2, so Feb 2 games don't qualify for fixing.

**Fix Applied:**
Created new hourly scheduler job for overnight:
```bash
gcloud scheduler jobs create http fix-stale-schedule-late-night \
  --schedule="0 1-6 * * *" \
  --time-zone="America/New_York" \
  --uri="https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/fix-stale-schedule"
```

This runs hourly from 1 AM - 6 AM ET to catch late-finishing games.

---

### Issue 3: BigQuery JSON NULL Error

**Error:**
```
Only optional fields can be set to NULL. Field: line_values_requested; Value: NULL
```

**Location:** `predictions/worker/execution_logger.py`

**Root Cause:**
REPEATED fields (arrays) in BigQuery cannot be NULL - must be empty array `[]`.
The sanitization only happened in the error handler, not before adding to buffer.

**Fix Applied:**
Added pre-buffer sanitization in `_add_to_buffer()`:
```python
# Sanitize REPEATED fields BEFORE adding to buffer
log_entry['line_values_requested'] = log_entry.get('line_values_requested') or []
log_entry['systems_attempted'] = log_entry.get('systems_attempted') or []
# ... etc
```

---

### Issue 4: Transient Scraper Errors (No Fix Needed)

These resolved automatically:

| Error | Count | Cause |
|-------|-------|-------|
| Missing game_id | 3 | Malformed trigger |
| Low event count | 4 | Games in progress |
| 403 Forbidden | 2 | NBA.com rate limiting |
| Game not found | 2 | BigDataBall data not ready |

---

## Changes Made

### 1. Infrastructure

| Change | Before | After |
|--------|--------|-------|
| Phase 2 max instances | 5 | 10 |
| Late-night schedule fix | Every 4 hours | Hourly 1-6 AM ET |

### 2. Code Fix

**File:** `predictions/worker/execution_logger.py`

Added REPEATED field sanitization before buffering (lines 194-200):
```python
# Sanitize REPEATED fields BEFORE adding to buffer
log_entry['line_values_requested'] = log_entry.get('line_values_requested') or []
log_entry['systems_attempted'] = log_entry.get('systems_attempted') or []
log_entry['systems_succeeded'] = log_entry.get('systems_succeeded') or []
log_entry['systems_failed'] = log_entry.get('systems_failed') or []
log_entry['missing_features'] = log_entry.get('missing_features') or []
log_entry['circuits_opened'] = log_entry.get('circuits_opened') or []
```

---

## Scheduler Jobs

### New Job Created

| Job Name | Schedule | Purpose |
|----------|----------|---------|
| `fix-stale-schedule-late-night` | `0 1-6 * * *` (ET) | Hourly overnight schedule fix |

### Existing Jobs

| Job Name | Schedule | Purpose |
|----------|----------|---------|
| `fix-stale-schedule` | `0 */4 * * *` (UTC) | Every 4 hours schedule fix |
| `daily-schedule-locker` | `0 10 * * *` (UTC) | Daily schedule generation |

---

## Verification

### Check Instance Scaling
```bash
gcloud run services describe nba-phase2-raw-processors \
  --region=us-west2 \
  --format="value(spec.template.metadata.annotations['autoscaling.knative.dev/maxScale'])"
# Expected: 10
```

### Check Schedule Fix Jobs
```bash
gcloud scheduler jobs list --location=us-west2 | grep schedule
```

### Check Game Status Updates
```bash
bq query --use_legacy_sql=false "
SELECT game_id, game_status
FROM nba_reference.nba_schedule
WHERE game_date = '2026-02-02'"
```

---

## Deployment Required

The execution_logger.py fix requires redeployment of prediction-worker:
```bash
./bin/deploy-service.sh prediction-worker
```

---

## Lessons Learned

1. **Alert naming can be misleading** - "Auth Errors" was actually instance availability
2. **Timezone-aware queries need careful testing** - The `CURRENT_DATE('America/New_York')` edge case
3. **BigQuery REPEATED fields** - Always sanitize to empty array, never NULL
4. **Late-night operations** - Need more frequent monitoring during overnight hours

---

## Related Documents

- `docs/02-operations/troubleshooting-matrix.md`
- `docs/02-operations/session-learnings.md`
- `scrapers/routes/schedule_fix.py`

---

**Document Created:** 2026-02-03 04:25 UTC
**Author:** Claude Opus 4.5
