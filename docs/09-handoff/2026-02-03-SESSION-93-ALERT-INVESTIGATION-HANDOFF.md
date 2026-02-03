# Session 93 Handoff - Alert Investigation

**Date:** 2026-02-03
**Time:** ~9:30 PM PT (05:30 UTC)
**Model:** Claude Opus 4.5

---

## Session Summary

Investigated Slack alerts about "Auth Errors" and HTTP 400s. Found these were actually instance availability issues and transient scraper errors during late-night game processing. Applied infrastructure and code fixes.

---

## Alerts Investigated

| Alert | Actual Cause | Status |
|-------|--------------|--------|
| "Auth Errors Detected" (Phase 2) | Instance availability + email config warnings | Fixed |
| "HTTP 400 Errors" (Scrapers) | Transient scraper errors during game processing | Self-resolved |
| "Analytics Player Count Gaps" | Stale alert - data now shows 37/37 players | OK |

---

## Fixes Applied

### 1. Phase 2 Max Instances (Infrastructure)

**Change:** 5 → 10 max instances

```bash
gcloud run services update nba-phase2-raw-processors \
  --region=us-west2 --max-instances=10
```

**Why:** Burst activity at 04:00 UTC exceeded capacity (50 requests). Now supports 100.

---

### 2. Late-Night Schedule Fix (Scheduler)

**New Job:** `fix-stale-schedule-late-night`
- **Schedule:** `0 1-6 * * *` (hourly 1-6 AM ET)
- **Purpose:** Fix stale game statuses faster for late-finishing games

**Issue Found:** The existing `fix-stale-schedule` (every 4 hours) uses:
```sql
WHERE game_date < CURRENT_DATE('America/New_York')
```
This doesn't work until after midnight ET, leaving late games stuck as "Scheduled".

---

### 3. Execution Logger NULL Fix (Code)

**File:** `predictions/worker/execution_logger.py`
**Commit:** `41bc42f4`
**Deployed:** `prediction-worker-00088-bxm`

**Issue:** BigQuery REPEATED fields cannot be NULL, only empty arrays. The sanitization only happened in the error handler, causing failures on first flush attempt.

**Fix:** Added pre-buffer sanitization in `_add_to_buffer()`:
```python
log_entry['line_values_requested'] = log_entry.get('line_values_requested') or []
log_entry['systems_attempted'] = log_entry.get('systems_attempted') or []
# ... etc for all REPEATED fields
```

---

## Email Alerting Warnings (Not Fixed - Intentional)

The "Auth Errors" metric also captures email alerting config warnings:
```
ModuleNotFoundError: No module named 'boto3'
ValueError: Email alerting requires: BREVO_SMTP_USERNAME, BREVO_FROM_EMAIL
```

**Recommendation:** Leave as-is. These are harmless - email alerting is optional and falls back to Slack. The warnings only appear during instance startup.

---

## Feb 2 Game Status

| Game | Schedule Status | Analytics |
|------|-----------------|-----------|
| NOP @ CHA | Final | 37 players |
| HOU @ IND | Scheduled* | 35 players |
| MIN @ MEM | Scheduled* | 37 players |
| PHI @ LAC | Scheduled* | 25 players |

*Will auto-fix at 1 AM ET when new hourly scheduler runs.

---

## Files Changed

| File | Change |
|------|--------|
| `predictions/worker/execution_logger.py` | REPEATED field sanitization |
| `docs/08-projects/current/2026-02-03-alert-investigation/README.md` | Investigation notes |

---

## Deployments

| Service | Revision | Commit |
|---------|----------|--------|
| nba-phase2-raw-processors | 00133-jxw | (config change only) |
| prediction-worker | 00088-bxm | 41bc42f4 |

---

## Scheduler Jobs

| Job | Schedule | Status |
|-----|----------|--------|
| `fix-stale-schedule` | Every 4 hours (UTC) | Existing |
| `fix-stale-schedule-late-night` | Hourly 1-6 AM ET | **NEW** |

---

## Verification Commands

```bash
# Check Phase 2 scaling
gcloud run services describe nba-phase2-raw-processors --region=us-west2 \
  --format="value(spec.template.metadata.annotations['autoscaling.knative.dev/maxScale'])"
# Expected: 10

# Check prediction-worker commit
gcloud run services describe prediction-worker --region=us-west2 \
  --format="value(metadata.labels.commit-sha)"
# Expected: 41bc42f4

# Check late-night scheduler
gcloud scheduler jobs list --location=us-west2 | grep late-night
# Expected: fix-stale-schedule-late-night

# Check game statuses (after 1 AM ET)
bq query --use_legacy_sql=false "
SELECT game_id, game_status FROM nba_reference.nba_schedule
WHERE game_date = '2026-02-02'"
# Expected: All status = 3 (Final)
```

---

## Root Causes Identified

1. **"Auth Errors" metric is misleading** - counts all stderr output, not just auth issues
2. **Schedule fix timing** - `CURRENT_DATE` edge case at night doesn't catch same-day games
3. **BigQuery REPEATED fields** - must always be arrays, never NULL
4. **Instance scaling** - 5 max instances insufficient for burst activity

---

## Recommendations for Future

1. **Rename alert** - "Auth Errors" should be "Stderr Output" or more specific
2. **Add instance metrics** - Alert on "no available instance" specifically
3. **Consider fixing schedule logic** - Check if game_date <= CURRENT_DATE and game started 4+ hours ago

---

## Known Issues (Not Fixed This Session)

- Email alerting not configured (boto3, Brevo credentials) - **Intentional, using Slack instead**
- PHI @ LAC game still in progress at session end - **Normal, late West Coast game**

---

## Next Session Checklist

1. Verify game statuses updated after 1 AM ET
2. Monitor for recurring "Auth Errors" alerts
3. Check prediction-worker logs for any NULL-related errors

---

**Session 93 Complete**
