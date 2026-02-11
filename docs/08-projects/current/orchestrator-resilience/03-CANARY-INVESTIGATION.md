# Pipeline Canary Investigation - Why Didn't It Catch the Gap?

**Session 199** | **Date:** 2026-02-11 | **Per Opus Request**

---

## Opus's Question

> The existing canary already checks Phase 3 output. Why didn't it catch the 3-day gap?

**Existing Phase 3 Canary:**
```python
CanaryCheck(
    name="Phase 3 - Analytics",
    query="""
    SELECT COUNT(*) as records, ...
    FROM player_game_summary
    WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    """,
    thresholds={'records': {'min': 40}}  # Should alert if <40 records
)
```

**This already checks Phase 3 output** - same thing the proposed new check would do.

---

## Investigation Findings

### 1. Canary IS Running

**Cloud Scheduler:**
- Job: `nba-pipeline-canary-trigger`
- Schedule: `*/30 * * * *` (every 30 minutes)
- Status: ENABLED ✅
- Last attempt: 2026-02-11T17:00:00Z ✅

**Cloud Run Job:**
- Job: `nba-pipeline-canary`
- Executions: Running every 30 minutes ✅
- Status: All executions show `Completed: False` ❌

### 2. Canary IS Failing (But on Different Check)

**Recent logs:**
```
Container called exit(1).
WARNING: Found 1 canary failures
WARNING:   Error: low_quality_count: 78 > 50 (max)
```

**Issue:** Phase 4 (Precompute) canary is failing on `low_quality_count` threshold.

### 3. Canary Behavior on Failures

**From code analysis (`bin/monitoring/pipeline_canary_queries.py:355-400`):**

```python
def main():
    results = []
    for check in CANARY_CHECKS:
        passed, metrics, error = run_canary_query(client, check)
        results.append((check, passed, metrics, error))  # Collect ALL results

    failures = [r for r in results if not r[1]]

    if failures:
        message = format_canary_results(results)  # All failures
        send_slack_alert(message, channel="#canary-alerts")  # Send to Slack
        return 1  # Exit with failure
```

**Key points:**
1. ✅ Runs ALL checks (doesn't stop at first failure)
2. ✅ Collects ALL failures
3. ✅ Sends Slack alert with all failures to `#canary-alerts`
4. ✅ Returns exit code 1 if any failures

**This means the canary SHOULD have alerted if Phase 3 failed.**

---

## Critical Questions

### Q1: Did Phase 3 Check Actually Fail During Feb 9-11?

**Need to verify:** Did the Phase 3 canary check fail, or did it pass because of a logic gap?

**Possible scenarios:**

**A. Phase 3 check failed and alerted (but we missed it)**
- Alerts went to #canary-alerts
- Mixed with Phase 4 alerts (low_quality_count)
- Overlooked in noise

**B. Phase 3 check passed on stale data**
- Query checks `DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)`
- On Feb 10, checks Feb 9 data
- If Phase 3 didn't run Feb 9, there's 0 records
- But maybe there was data from Feb 8 that satisfied the check?
  - No - query filters by exact date

**C. Phase 3 check passed because games weren't "Final"**
- No threshold violation if 0 scheduled games
- Need to verify game schedule for Feb 9-11

### Q2: What's the Alert Fatigue Situation?

**Phase 4 is alerting every 30 minutes:**
```
low_quality_count: 78 > 50 (max)
```

**If Phase 4 alerts constantly:**
- #canary-alerts channel gets 48 alerts/day
- Phase 3 alert buried in noise
- Alert fatigue → alerts ignored

---

## Root Cause Hypotheses

### Hypothesis 1: Alert Fatigue (LIKELY)

**Evidence:**
- Phase 4 failing constantly (78 > 50 low_quality players)
- 48 alerts/day to #canary-alerts
- Phase 3 alert (if it fired) buried in noise

**Fix:** Tune Phase 4 thresholds or separate alert channels

### Hypothesis 2: No Games Scheduled (POSSIBLE)

**Evidence:**
- Feb 9-11 might have had no/few games
- Canary threshold `records >= 40` only applies if games exist
- Need to check NBA schedule for those dates

**Fix:** Add "expected games" check (schedule vs actual)

### Hypothesis 3: Canary Logic Gap (UNLIKELY)

**Evidence:**
- Code looks correct (checks all, alerts all)
- Query logic is straightforward

**Fix:** N/A - code is fine

---

## Recommendations (Per Opus)

### 1. Investigate Why Existing Canary Didn't Alert (10 min)

**Check Slack #canary-alerts for Feb 9-11:**
```bash
# Check if Phase 3 alerts were sent
# Search #canary-alerts channel for "Phase 3" during Feb 9-11
```

**Check game schedule for Feb 9-11:**
```sql
SELECT game_date, COUNT(*) as games
FROM nba_raw.nbac_schedule
WHERE game_date BETWEEN '2026-02-09' AND '2026-02-11'
  AND game_status_text = 'Final'
GROUP BY game_date
```

**Check if Phase 3 data exists from before the gap:**
```sql
SELECT game_date, COUNT(*) as records
FROM nba_analytics.player_game_summary
WHERE game_date BETWEEN '2026-02-08' AND '2026-02-11'
GROUP BY game_date
ORDER BY game_date
```

### 2. Fix the Existing Canary (Don't Add New One)

**Options:**

**A. Tune Phase 4 thresholds** (if alert fatigue is the issue)
```python
# Increase threshold or remove check temporarily
'low_quality_count': {'max': 100}  # Was 50
```

**B. Add expected games check** (if "no games" is the issue)
```python
CanaryCheck(
    name="Phase 3 - Analytics vs Schedule",
    query="""
    WITH scheduled AS (
      SELECT COUNT(*) as expected
      FROM nba_raw.nbac_schedule
      WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
        AND game_status_text = 'Final'
    ),
    actual AS (
      SELECT COUNT(DISTINCT game_id) as actual_games
      FROM nba_analytics.player_game_summary
      WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
    )
    SELECT s.expected, a.actual_games,
           CASE WHEN s.expected > 0 AND a.actual_games = 0 THEN 1 ELSE 0 END as gap_detected
    FROM scheduled s CROSS JOIN actual a
    """,
    thresholds={'gap_detected': {'max': 0}}  # Alert if games scheduled but no analytics
)
```

**C. Separate alert channels** (if noise is the issue)
```python
# Critical alerts (Phase 3 failures)
send_slack_alert(message, channel="#critical-pipeline-alerts")

# Warning alerts (Phase 4 quality issues)
send_slack_alert(message, channel="#pipeline-warnings")
```

### 3. Implement Layer 1 Only (Checkpoint Logging)

**Approved as-is:**
- 20 minutes
- No new canary logic
- Valuable for diagnostics

### 4. Increase Canary Frequency to 15 Min

**Approved:**
```bash
gcloud scheduler jobs update nba-pipeline-canary-trigger \
  --schedule="*/15 * * * *" \
  --location=us-west2
```

---

## Revised Implementation Plan

### Phase 1: Investigate (10 min)

- [ ] Check #canary-alerts for Phase 3 failures Feb 9-11
- [ ] Check game schedule for Feb 9-11 (were there games?)
- [ ] Check player_game_summary data for Feb 8-11 (when did gap start?)
- [ ] Determine root cause (alert fatigue vs no games vs logic gap)

### Phase 2: Fix Existing Canary (15 min)

**If alert fatigue:**
- [ ] Tune Phase 4 thresholds or separate channels

**If "no games" logic gap:**
- [ ] Add expected games check (schedule vs actual)

**If logic gap:**
- [ ] Fix query logic (unlikely)

### Phase 3: Layer 1 Logging (20 min)

**Unchanged from plan:**
- [ ] Add checkpoint logging to orchestrator
- [ ] Deploy

### Phase 4: Increase Frequency (5 min)

- [ ] Update scheduler to 15-min intervals

**Total: 50 minutes** (down from 85 minutes)

---

## Key Insight (Per Opus)

> "Before adding a new canary, figure out why the existing one didn't fire. If it's a date logic issue, fix the existing canary. If it's a scheduler issue, no amount of new code will help."

**This is exactly right.** Adding a second Phase 3 output check would be redundant if the existing check has a fixable gap.

---

## Questions to Answer

1. **Did Phase 3 canary alert during Feb 9-11?**
   - Check #canary-alerts Slack history

2. **Were there games scheduled on Feb 9-11?**
   - Query nba_schedule table

3. **When did the player_game_summary gap actually start?**
   - Query analytics table for Feb 8-11

4. **Is Phase 4 alert fatigue masking Phase 3 alerts?**
   - Check alert frequency and #canary-alerts channel

---

## Next Steps

**Don't implement new canary code yet.** Instead:

1. Answer the 4 questions above (10 min investigation)
2. Fix the existing canary based on findings (15 min)
3. Implement Layer 1 logging (20 min)
4. Increase canary frequency (5 min)

**Total: 50 minutes**

**This avoids:**
- Redundant code
- Maintenance burden
- Potential for drift between two Phase 3 checks

**This ensures:**
- Existing canary works correctly
- Root cause is understood
- Future gaps are caught by fixed canary

---

## Status

⏳ **Awaiting investigation results** before finalizing implementation plan
