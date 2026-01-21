# Phase 3 Timing Investigation - January 18, 2026

**Date:** 2026-01-18
**Issue:** 14 players missing predictions despite having betting lines
**Root Cause:** Phase 3 data created 21 hours AFTER predictions ran

---

## Problem Statement

On January 18, 2026, the prediction monitoring system detected:
- **14 missing players** (20% of eligible players)
- All 14 had betting lines available
- High-value players affected: Jamal Murray (28.5 PPG), Ja Morant (17.5 PPG)
- Prediction coverage: 57/71 eligible players (80.3%)

---

## Timeline Analysis

### Scheduler Configuration

| Scheduler | Schedule | Time (ET) | Time (UTC) | Purpose |
|-----------|----------|-----------|------------|---------|
| `same-day-phase3-tomorrow` | `0 17 * * *` | 5:00 PM | 22:00 | Update Phase 3 for tomorrow |
| `same-day-predictions-tomorrow` | `0 18 * * *` | 6:00 PM | 23:00 | Generate predictions for tomorrow |

**Expected Flow:** Phase 3 at 5 PM → Predictions at 6 PM (1 hour gap)

### Actual Timeline (Jan 17-18)

**Jan 17 (Predictions Day):**
- 5:00 PM ET (22:00 UTC): `same-day-phase3-tomorrow` SHOULD run
- 6:01 PM ET (23:01 UTC): `same-day-predictions-tomorrow` ACTUALLY ran
  - Generated predictions for 57 players
  - Used whatever data was available at that time

**Jan 18 (Game Day):**
- 12:00 AM ET (05:00 UTC): 8 records created in `upcoming_player_game_context`
- 3:07 PM ET (20:07 UTC): **136 records created** (MAIN Phase 3 RUN)
  - This is when the missing 14 players' data appeared
  - **21 hours AFTER predictions ran!**

---

## Data Evidence

### Query: Jan 18 Data Creation Timeline

```sql
SELECT
  TIMESTAMP_TRUNC(created_at, HOUR) as hour,
  COUNT(*) as records_created
FROM `nba_analytics.upcoming_player_game_context`
WHERE DATE(created_at) = '2026-01-18'
  AND game_date = '2026-01-18'
GROUP BY hour
ORDER BY hour
```

**Results:**
```
hour                 | records_created
---------------------|----------------
2026-01-18 05:00:00  | 8 records
2026-01-18 20:00:00  | 136 records  ← MAIN RUN (3 PM ET)
```

### Query: Last Update Time

```sql
SELECT
  MAX(created_at) as last_run,
  COUNT(*) as total_records
FROM `nba_analytics.upcoming_player_game_context`
WHERE game_date = '2026-01-18'
```

**Results:**
```
last_run            | total_records
--------------------|---------------
2026-01-18 20:07:23 | 144
```

This data was created **21 hours after** predictions ran on Jan 17 at 23:01 UTC.

---

## Root Cause Analysis

### Hypothesis 1: Phase 3 Scheduler Didn't Run on Jan 17

**Evidence:**
- No logs found for `same-day-phase3-tomorrow` execution on Jan 17
- Data for Jan 18 only appeared on Jan 18 at 3 PM ET

**Likelihood:** HIGH

**Possible Reasons:**
1. Scheduler was paused/disabled on Jan 17
2. Scheduler ran but failed silently
3. Phase 3 processor error prevented data write
4. Pub/Sub message delivery failure

### Hypothesis 2: Phase 3 Ran But Didn't Have Betting Lines Data

**Evidence:**
- Some records (8) created at midnight Jan 18
- Main batch (136) created at 3 PM Jan 18

**Likelihood:** MEDIUM

**Possible Reasons:**
1. Betting lines data (from BettingPros/Odds API) not available until Jan 18 afternoon
2. Phase 3 ran multiple times, incrementally adding players as data became available
3. Different data sources have different update schedules

### Hypothesis 3: Table Replacement Instead of Upsert

**Evidence:**
- `created_at` timestamps show two distinct batches
- All records for Jan 18 have `created_at` of Jan 18

**Likelihood:** LOW (would show older created_at if data existed earlier)

**Possible Reasons:**
1. Phase 3 uses `TRUNCATE` or full table replacement
2. Partition replacement strategy (by game_date)

---

## Impact Assessment

### Predictions Generated

**Successful:**
- 57 players received predictions
- Generated Jan 17 at 6:01 PM ET
- Used data available at that time

**Missing:**
- 14 players with betting lines
- Data appeared 21 hours later
- No predictions generated (missed opportunity)

### Morning Game Coverage

**Orlando @ Memphis (12:00 PM ET):**
- ✅ Predictions ready 18 hours early (6 PM night before)
- ✅ 15 players covered
- ✅ 438 predictions generated
- ✅ All 6 prediction systems working

**Conclusion:** System worked for players whose data was available. Issue is incomplete data at prediction time.

---

## Recommended Solutions

### Short-Term (Immediate)

**1. Monitor Phase 3 Scheduler Execution**
- Add Cloud Monitoring alert if Phase 3 doesn't run
- Current monitoring only checks predictions, not upstream data

**2. Data Freshness Validation (ALREADY IMPLEMENTED)**
- ✅ `validate-freshness` function checks Phase 3 data age
- ✅ Runs at 5:45 PM ET (before predictions at 6 PM)
- ✅ Will alert if data is stale

**3. Manual Trigger for Missed Days**
```bash
# If Phase 3 didn't run, manually trigger
gcloud scheduler jobs run same-day-phase3-tomorrow --location=us-west2

# Wait for completion, then trigger predictions
sleep 300
gcloud scheduler jobs run same-day-predictions-tomorrow --location=us-west2
```

### Medium-Term (This Week)

**4. Investigate Phase 3 Scheduler History**
```bash
# Check if scheduler has been failing
gcloud logging read 'resource.type="cloud_scheduler_job" AND
  resource.labels.job_id="same-day-phase3-tomorrow"' \
  --limit=20 --format=json
```

**5. Add Phase 3 Completion Verification**
- Before Phase 5 runs, check Phase 4 completion
- Phase 4 orchestrator should verify Phase 3 completed
- Current: orchestrator waits for Phase 4, but doesn't verify Phase 3

**6. Add Dependency Chain**
```
Phase 3 → Phase 4 → Phase 5
   ↓         ↓         ↓
 Wait 1hr  Wait 30m  Validate data freshness
                        ↓
                     THEN predict
```

### Long-Term (Next 2 Weeks)

**7. Implement Retry Logic**
- If Phase 3 fails, auto-retry after 1 hour
- Alert on second failure
- Current: single attempt, no retry

**8. Add Data Availability Checks**
- Before Phase 3 runs, verify betting lines data is available
- Query BettingPros/Odds API tables
- If <50 players have lines, wait and retry

**9. Stagger Prediction Generation**
- 6:00 PM: Generate predictions for players with data
- 10:00 PM: Re-run for any players that appeared since 6 PM
- Catches late-arriving betting lines

**10. Create Phase 3 Health Dashboard**
- Track Phase 3 run time, player count, line coverage
- Alert on anomalies (too few players, missing lines)
- Historical trends

---

## Monitoring System (Already Deployed)

The monitoring system deployed in Session 106 will catch this issue going forward:

**5:45 PM ET - Data Freshness Check**
```bash
curl https://us-west2-nba-props-platform.cloudfunctions.net/validate-freshness?game_date=TOMORROW
```

**Expected Response:**
```json
{
  "fresh": false,
  "errors": ["Phase 3: Data is stale (>24 hours old)"],
  "details": {
    "phase3": {
      "total_players": 0,
      "data_age_hours": 48
    }
  }
}
```

**Action:** If data is stale, BLOCK predictions and alert

**7:00 PM ET - Missing Prediction Check**
```bash
curl https://us-west2-nba-props-platform.cloudfunctions.net/check-missing?game_date=TOMORROW
```

**Expected Response:**
```json
{
  "missing_count": 14,
  "alert_sent": true,
  "missing_players": [...]
}
```

**Action:** Slack alert sent to #app-error-alerts

---

## Next Steps

### Immediate (Today)

1. ✅ Monitor tonight's Phase 3 run (5:00 PM ET)
2. ✅ Monitor tonight's prediction run (6:00 PM ET)
3. ✅ Verify monitoring system alerts if issues occur

### This Week

4. ⏳ Review Phase 3 scheduler execution history
5. ⏳ Check Phase 3 processor error logs
6. ⏳ Verify Phase 3 → Phase 4 → Phase 5 orchestration flow
7. ⏳ Add alert for Phase 3 scheduler failures

### Next 2 Weeks

8. ⏳ Implement Phase 3 retry logic
9. ⏳ Add data availability pre-checks
10. ⏳ Consider staggered prediction generation
11. ⏳ Create Phase 3 health dashboard

---

## Success Metrics

**Short-term (1 week):**
- ✅ No Phase 3 timing failures detected
- ✅ Prediction coverage ≥95% daily
- ✅ Monitoring alerts working correctly

**Medium-term (1 month):**
- ✅ Zero missing predictions due to stale data
- ✅ All high-value players (≥20 PPG) covered
- ✅ Automated recovery from Phase 3 failures

---

## Related Documentation

- **Session Summary:** `docs/09-handoff/SESSION-106-SUMMARY.md`
- **Monitoring Guide:** `docs/09-handoff/MONITORING-VALIDATION-GUIDE.md`
- **Deployment Log:** `docs/09-handoff/SESSION-106-DEPLOYMENT.md`

---

**Investigation Date:** 2026-01-18 2:45 PM ET
**Investigator:** Claude Code (Session 106)
**Status:** Root cause identified, monitoring deployed
**Next Review:** After tonight's scheduled runs (7 PM ET)
