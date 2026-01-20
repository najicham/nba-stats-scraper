# Grading Coverage Alert - Deployment Complete ✅

**Deployed:** 2026-01-18 17:54 UTC
**Revision:** nba-grading-alerts-00005-swh  
**Service:** nba-grading-alerts (Cloud Run)

---

## Changes Deployed

### Added: Grading Coverage Monitoring

**New functionality:**
- Checks grading coverage: predictions made vs predictions graded
- Alerts when coverage falls below 70% threshold
- Provides detailed breakdown of missing grades

**Alert triggers:**
- **WARNING (⚠️):** Coverage 40-69%
- **CRITICAL (🚨):** Coverage <40%

---

## How It Works

### Coverage Check Logic
```sql
-- Compares predictions vs grades for each game date
WITH predictions AS (
    SELECT COUNT(DISTINCT CONCAT(player_lookup, '|', system_id)) as total_preds
    FROM player_prop_predictions
    WHERE DATE(created_at) = '{game_date}'
),
graded AS (
    SELECT COUNT(DISTINCT CONCAT(player_lookup, '|', system_id)) as graded_preds
    FROM prediction_accuracy  
    WHERE game_date = '{game_date}'
)
SELECT
    total_preds,
    graded_preds,
    ROUND(100.0 * graded_preds / total_preds, 1) as coverage_pct
```

### Alert Message Content
- Coverage percentage vs threshold (70%)
- Total predictions vs graded predictions
- Missing grades count
- Possible causes (boxscores not ready, grading failed, Phase 3 errors)
- Action items with console links

---

## Configuration

**Environment Variables:**
- `ALERT_THRESHOLD_COVERAGE_MIN`: Coverage threshold (default: 70.0%)
- `SLACK_WEBHOOK_URL`: Slack notification webhook
- `ALERT_THRESHOLD_DAYS`: Days to check for trends (default: 7)

**Schedule:**
- **Trigger:** Cloud Scheduler `nba-grading-alerts-daily`
- **Time:** Daily at 12:30 PM PT (20:30 UTC)
- **Checks:** Previous day's game date (T-1)

---

## Monitoring Gap Closed ✅

**Before:**
- ❌ No alerts for low grading coverage
- ❌ Coverage drops went undetected
- ❌ Manual queries required to check coverage

**After:**
- ✅ Automated daily coverage monitoring
- ✅ Slack alerts for <70% coverage
- ✅ Detailed diagnostics in alert message
- ✅ Proactive issue detection

---

## Testing

**Manual Test:**
```bash
# Trigger the service manually (requires auth)
gcloud run services invoke nba-grading-alerts \
  --region us-west2 \
  --project nba-props-platform
```

**Check logs:**
```bash
gcloud logging read \
  'resource.labels.service_name="nba-grading-alerts" AND 
   jsonPayload.coverage_pct!=null' \
  --limit=5
```

---

## Integration with Existing Checks

The service now performs **6 checks** daily:

1. **Grading Coverage** ← NEW!
   - Predictions vs graded
   - Threshold: 70%
   
2. **Grading Health**
   - Grades generated
   - Issue rate

3. **Accuracy Drop**
   - System accuracy <55%
   - Last 7 days

4. **Calibration Health**
   - Calibration error >15pts
   - Last 7 days

5. **System Ranking Change**
   - Top system changed
   - Weekly comparison

6. **Weekly Summary**
   - Sent on Mondays
   - Performance overview

---

## Next Run

**Scheduled:** 2026-01-19 20:30 UTC (12:30 PM PT)
**Will check:** 2026-01-18 game date coverage

**Expected behavior:**
- Query predictions from `player_prop_predictions` WHERE created_at = '2026-01-18'
- Query grades from `prediction_accuracy` WHERE game_date = '2026-01-18'
- Alert if coverage <70%

---

## Success Criteria

✅ **Complete when:**
1. Service deployed and healthy
2. First coverage check completes successfully
3. Slack alert received (if coverage <70%)
4. Coverage monitoring documented

**Current Status:** ✅ Deployed, awaiting first scheduled run

---

**Deployed by:** Claude Sonnet 4.5 (Session 102)
**Related:** Critical monitoring gap closure from Session 100-101 handoff
**Impact:** Prevents silent grading failures, protects revenue operations
