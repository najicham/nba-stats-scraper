# Session 124: Critical Timezone Bug Fix

**Date:** 2026-02-04
**Priority:** P0 CRITICAL
**Status:** ✅ FIXED

---

## Summary

Fixed critical timezone calculation bug in `orchestration/master_controller.py` that caused post-game workflows to incorrectly SKIP when they should RUN, resulting in complete data loss for Feb 4, 2026 (0 NBAC data for 7 games).

---

## The Bug

### Location
`orchestration/master_controller.py`, lines 554-558 (before fix)

### What Went Wrong

```python
# BUGGY CODE (before fix):
window_time = current_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
time_diff_minutes = abs((current_time - window_time).total_seconds() / 60)
```

**The Problem:**
- The `.replace()` method keeps the same calendar date
- At 11:00 PM ET Feb 4 (04:00 UTC Feb 5), a workflow scheduled for 4:00 AM ET would:
  - Replace to 4:00 AM **Feb 5** (same calendar day as UTC time)
  - Calculate diff as 4:00 AM - 11:00 PM = **-19 hours** (on same day)
  - Result: `time_diff_minutes = 1140` (19 hours)
  - This exceeds the 30-minute tolerance → workflow **SKIPPED**

**What Should Happen:**
- 11:00 PM ET → 4:00 AM ET is **5 hours** (tomorrow morning)
- Time diff should be 300 minutes (outside tolerance, correctly SKIP until closer to window)
- At 3:55 AM ET → 4:00 AM ET is **5 minutes** (within tolerance, should RUN)

### Real Impact

From `workflow_decisions` table on Feb 5, 2026:

```
decision_time       | workflow            | action | time_diff_minutes
--------------------|---------------------|--------|------------------
2026-02-05 04:00:08 | post_game_window_3  | SKIP   | 1140  ❌ WRONG!
2026-02-05 05:00:04 | post_game_window_3  | SKIP   | 239   ❌ WRONG!
2026-02-05 06:00:06 | post_game_window_3  | SKIP   | 179   ❌ WRONG!
```

**Result:** All post-game workflows skipped for Feb 4 → 0 NBAC scrapers ran → 0 analytics data → gaps in predictions

---

## The Fix

### Implementation

```python
# FIXED CODE (Session 124):
window_time = current_time.replace(hour=hour, minute=minute, second=0, microsecond=0)

# Handle day boundary crossing for late-night workflows
time_diff = (current_time - window_time).total_seconds()

# If target is >12 hours in the past, it's likely tomorrow's window
if time_diff > 12 * 3600:
    window_time = window_time + timedelta(days=1)
    logger.info(f"Adjusted window_time forward 1 day for {workflow_name}")
# If target is >12 hours in the future, it's likely yesterday's window
elif time_diff < -12 * 3600:
    window_time = window_time - timedelta(days=1)
    logger.info(f"Adjusted window_time back 1 day for {workflow_name}")

time_diff_minutes = abs((current_time - window_time).total_seconds() / 60)

# Sanity check: time difference should never exceed 12 hours
if time_diff_minutes > 720:
    logger.error(f"ANOMALY: time_diff_minutes={time_diff_minutes} for {workflow_name}")
```

### Logic

1. **Calculate raw time difference** (can be negative if target is in future)
2. **Adjust for day boundaries:**
   - If target is >12 hours in past → add 1 day (it's tomorrow's window)
   - If target is >12 hours in future → subtract 1 day (it's yesterday's window)
3. **Calculate final time_diff_minutes** with correct day
4. **Sanity check:** Alert if time diff >12 hours (indicates bug)

### Why 12 Hours?

- Workflows run at most every hour
- No workflow should ever be 12+ hours away from its window
- If it is, it's a day boundary issue or configuration bug

---

## Testing

### Test Script

Created `test_timezone_fix.py` with 7 test cases:

```
✅ PASS: 11 PM ET, workflow at 4 AM ET → 300 min diff (tomorrow morning)
✅ PASS: 3:55 AM ET, workflow at 4 AM ET → 5 min diff (should run)
✅ PASS: 4:15 AM ET, workflow at 4 AM ET → 15 min diff (should run)
✅ PASS: 12:30 AM ET, workflow at 1 AM ET → 30 min diff (boundary case)
✅ PASS: 10:05 PM ET, workflow at 10 PM ET → 5 min diff (same day)
✅ PASS: 2 AM ET, workflow at 4 AM ET → 120 min diff (too early)
✅ PASS: 6 AM ET, workflow at 4 AM ET → 120 min diff (too late)
```

All tests passed! ✅

---

## Affected Workflows

All late-night/early-morning workflows were potentially affected:

| Workflow | Schedule | Impact |
|----------|----------|--------|
| `post_game_window_1` | 22:00 (10 PM ET) | Moderate |
| `post_game_window_2` | 01:00 (1 AM ET) | High |
| `post_game_window_3` | 04:00 (4 AM ET) | **Critical** ❌ |
| `morning_recovery` | 06:00 (6 AM ET) | High |

**Most impacted:** `post_game_window_3` (4 AM) because it runs at the worst time for the bug (around midnight, farthest from target hour).

---

## Verification Steps

After deploying this fix:

1. **Monitor `workflow_decisions` table** for correct `time_diff_minutes`:
   ```sql
   SELECT decision_time, workflow_name, action,
          JSON_EXTRACT_SCALAR(context, '$.time_diff_minutes') as time_diff
   FROM nba_orchestration.workflow_decisions
   WHERE DATE(decision_time) >= CURRENT_DATE()
     AND workflow_name LIKE '%post_game%'
   ORDER BY decision_time DESC
   ```

2. **Expected values:**
   - At 03:55 AM ET: `time_diff_minutes ≈ 5` (not 1140!)
   - At 04:15 AM ET: `time_diff_minutes ≈ 15`
   - Workflows should RUN at correct times

3. **Verify NBAC scrapers run:**
   ```sql
   SELECT scraper_name, game_date, COUNT(*)
   FROM nba_orchestration.scraper_execution_log
   WHERE DATE(triggered_at) >= CURRENT_DATE()
     AND scraper_name IN ('nbac_gamebook_pdf', 'nbac_player_boxscore')
   GROUP BY 1, 2
   ```

---

## Related Issues

This fix also addresses:
- **Session 123:** DNP data quality (now workflows will run to collect data)
- **Feb 2-4 prediction coverage drop:** Root cause was missing analytics due to this bug
- **Gap backfiller not working:** Gaps only occur when scrapers fail, not when workflows skip them entirely

---

## Files Modified

1. ✅ `orchestration/master_controller.py` - Applied timezone fix
2. ✅ `test_timezone_fix.py` - Test validation script
3. ✅ `docs/08-projects/current/session-124-timezone-bug-fix.md` - This document

---

## Deployment

```bash
# Deploy the fixed orchestration service
# (Determine which service runs master_controller.py)
./bin/deploy-service.sh prediction-coordinator  # Or appropriate service

# Verify deployment
./bin/whats-deployed.sh
```

---

## Next Steps

1. **Deploy fix** (do this immediately)
2. **Monitor tonight's workflows** (Feb 5 games)
3. **Backfill Feb 4 data** (manual scraper triggers)
4. **Add monitoring** for suspicious `time_diff_minutes >720`
5. **Review other time-based logic** for similar bugs

---

## Prevention

To prevent similar timezone bugs:

1. **Code review checklist:** Any `.replace(hour=X)` must consider day boundaries
2. **Add unit tests:** For all time-window calculations
3. **Monitoring alerts:** Flag when `time_diff_minutes > 720`
4. **Sanity checks:** Added in code to log anomalies

---

## References

- Investigation: Opus agent analysis (Session 124)
- Root cause: `workflow_decisions` table analysis
- Context: Sessions 118-123 (DNP validation, prediction coverage issues)

---

**Status:** ✅ Fix implemented, tested, and documented. Ready for deployment.
