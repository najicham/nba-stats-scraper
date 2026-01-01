# Tomorrow's Validation Checklist - January 1, 2026
**Target Time:** 7:10 AM ET (12:10 UTC)
**Scheduler:** overnight-predictions (runs at 7:00 AM ET)
**Purpose:** Verify automatic consolidation and Phase 6 triggering

---

## 🎯 Critical Success Criteria

**The pipeline MUST complete these steps AUTOMATICALLY:**
- [ ] Predictions generate (workers complete successfully)
- [ ] **Consolidation runs WITHOUT manual intervention** ⭐
- [ ] **Phase 6 triggers WITHOUT manual intervention** ⭐
- [ ] Front-end data updates automatically

**If ANY of these require manual intervention → FAILURE → Investigate root cause**

---

## ⏰ Timeline & Checklist

### 7:00 AM ET - Scheduler Triggers

**Wait 10 minutes for pipeline to complete**

---

### 7:10 AM ET - START VALIDATION

#### Step 1: Run Health Check ✅
```bash
cd /home/naji/code/nba-stats-scraper
./bin/monitoring/check_pipeline_health.sh
```

**Expected Output (SUCCESS):**
```
================================================
  NBA Prediction Pipeline Health Check
  Date: Thu Jan  1 07:10:00 ET 2026
  Target: TODAY
================================================

ℹ INFO: Checking prediction generation...
✓ SUCCESS: Batch loader ran: ✅ Batch loaded historical games for 118 players
✓ SUCCESS: Workers generated predictions: 50 completion events

ℹ INFO: Checking consolidation...
✓ SUCCESS: Consolidation completed: Cleaned up staging tables

ℹ INFO: Checking Phase 6 export...
✓ SUCCESS: Phase 6 export completed: Export completed in 156.0s

ℹ INFO: Checking front-end data freshness...
✓ SUCCESS: Front-end data is fresh (5 minutes old)
ℹ INFO: Generated at: 2026-01-01T12:05:00.000000+00:00
✓ SUCCESS: Front-end has 120 players with predictions

================================================
✓ SUCCESS: Pipeline health check PASSED
================================================
```

**Result:**
- [ ] All checks show `✓ SUCCESS`
- [ ] Exit code is 0
- [ ] No `✗ ERROR` or `⚠ WARNING` messages

**If health check FAILS → Go to Step 8 (Troubleshooting)**

---

#### Step 2: Verify Scheduler Triggered ✅

```bash
gcloud scheduler jobs describe overnight-predictions \
  --location=us-west2 \
  --format="yaml(status.lastAttemptTime,status.state)"
```

**Expected Output:**
```yaml
status:
  lastAttemptTime: '2026-01-01T12:00:00.xxxZ'
  state: SUCCESS
```

**Validation:**
- [ ] `lastAttemptTime` is ~12:00 UTC (7:00 AM ET) today
- [ ] `state: SUCCESS` (not FAILED or ERROR)

**If scheduler FAILED:**
```bash
# Check error logs
gcloud logging read 'resource.type="cloud_scheduler_job" AND resource.labels.job_id="overnight-predictions"' --limit=5 --format="value(timestamp,jsonPayload.status)"

# Manual trigger if needed
curl -X POST \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"game_date":"TODAY","force":true}' \
  https://prediction-coordinator-756957797294.us-west2.run.app/start
```

---

#### Step 3: Verify Batch Loader Ran ✅

```bash
gcloud logging read 'resource.labels.service_name="prediction-coordinator" AND textPayload=~"Batch loaded historical games" AND timestamp>="2026-01-01T11:55:00Z"' --limit=1 --format="value(timestamp,textPayload)"
```

**Expected Output:**
```
2026-01-01T12:01:30.xxxZ    ✅ Batch loaded historical games for 118 players
```

**Validation:**
- [ ] Timestamp is within 2 minutes of scheduler trigger (12:00-12:02 UTC)
- [ ] Shows player count (e.g., "118 players")
- [ ] Used batch loading (not individual queries)

**Performance Check:**
```bash
# Batch loading should complete in <1 second
# This confirms the 331x speedup is working
```

**If batch loading FAILED or not found:**
```bash
# Check for batch loading errors
gcloud logging read 'resource.labels.service_name="prediction-coordinator" AND textPayload=~"Batch historical load failed" AND timestamp>="2026-01-01T11:55:00Z"' --limit=5 --format="value(textPayload)"

# Workers will fall back to individual queries (slower but functional)
# Not a blocker, but investigate root cause
```

---

#### Step 4: Verify Workers Completed ✅

```bash
gcloud logging read 'resource.labels.service_name="prediction-worker" AND textPayload=~"Successfully generated" AND timestamp>="2026-01-01T11:55:00Z"' --limit=20 --format="value(timestamp,textPayload)" | head -20
```

**Expected Output:**
```
2026-01-01T12:02:15.xxxZ    Successfully generated 25 predictions for player1
2026-01-01T12:02:16.xxxZ    Successfully generated 25 predictions for player2
...
```

**Validation:**
- [ ] At least 50+ worker completion events
- [ ] Timestamps within 1-3 minutes after batch loading
- [ ] "Successfully generated" messages (not errors)

**Check for Batch Data Usage:**
```bash
gcloud logging read 'resource.labels.service_name="prediction-worker" AND textPayload=~"Worker using pre-loaded historical games" AND timestamp>="2026-01-01T11:55:00Z"' --limit=10 --format="value(textPayload)"
```

**Expected:**
```
✅ Worker using pre-loaded historical games (30 games) from coordinator
✅ Worker using pre-loaded historical games (30 games) from coordinator
...
```

**Validation:**
- [ ] Workers received batch data from coordinator
- [ ] Shows "(30 games)" or similar count
- [ ] Confirms zero individual BigQuery queries

---

#### Step 5: Verify Consolidation Ran AUTOMATICALLY ⭐ **CRITICAL**

```bash
# Check for consolidation success (staging cleanup is the success indicator)
gcloud logging read 'resource.labels.service_name="prediction-coordinator" AND textPayload=~"Cleaned up staging" AND timestamp>="2026-01-01T11:55:00Z"' --limit=1 --format="value(timestamp,textPayload)"
```

**Expected Output:**
```
2026-01-01T12:03:30.xxxZ    Cleaned up staging tables for batch_2026-01-01_xxx
```

**⭐ THIS IS THE KEY VALIDATION ⭐**

**Validation:**
- [ ] Consolidation ran **WITHOUT manual intervention**
- [ ] Timestamp is 2-4 minutes after workers completed
- [ ] Message indicates staging tables were cleaned up

**Check for Consolidation Errors:**
```bash
gcloud logging read 'resource.labels.service_name="prediction-coordinator" AND textPayload=~"Consolidation failed" AND timestamp>="2026-01-01T11:55:00Z"' --limit=5 --format="value(textPayload)"
```

**Expected:** No results (empty output = no errors)

**If consolidation FAILED or didn't run:**
```bash
# ❌ FAILURE - Manual intervention required
# This means automatic consolidation is broken

# Check error details
gcloud logging read 'resource.labels.service_name="prediction-coordinator" AND (textPayload=~"Consolidation" OR textPayload=~"MERGE") AND timestamp>="2026-01-01T11:55:00Z"' --limit=10 --format="value(timestamp,textPayload)"

# Manual consolidation
PYTHONPATH=/home/naji/code/nba-stats-scraper python3 bin/predictions/consolidate/manual_consolidation.py

# ⚠️ INVESTIGATE ROOT CAUSE AFTER FIXING
```

**Verify Predictions in BigQuery:**
```bash
bq query --use_legacy_sql=false "
SELECT
  COUNT(DISTINCT player_lookup) as players,
  COUNT(*) as predictions,
  MIN(created_at) as first_created,
  MAX(created_at) as last_created
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)"
```

**Expected:**
```
+----------+-------------+---------------------+---------------------+
| players  | predictions | first_created       | last_created        |
+----------+-------------+---------------------+---------------------+
|      120 |         600 | 2026-01-01 12:02:00 | 2026-01-01 12:02:30 |
+----------+-------------+---------------------+---------------------+
```

**Validation:**
- [ ] ~100-150 players (depends on games today)
- [ ] ~500-750 predictions (5 systems × players)
- [ ] Created within last hour

---

#### Step 6: Verify Phase 6 Triggered AUTOMATICALLY ⭐ **CRITICAL**

```bash
# Check Phase 6 orchestrator decision
gcloud logging read 'resource.labels.service_name="phase5-to-phase6-orchestrator" AND timestamp>="2026-01-01T11:55:00Z"' --limit=10 --format="value(timestamp,textPayload)"
```

**Expected Output (SUCCESS):**
```
2026-01-01T12:04:00.xxxZ    [batch_xxx] Triggering Phase 6: completion 95.0% >= 80.0%
2026-01-01T12:04:00.xxxZ    [batch_xxx] Published to phase6-export-trigger
```

**⚠️ FAILURE Output:**
```
2026-01-01T12:04:00.xxxZ    [batch_xxx] Skipping Phase 6 trigger - completion too low (0.0% < 80.0%)
```

**⭐ THIS IS THE KEY VALIDATION ⭐**

**Validation:**
- [ ] Orchestrator shows "Triggering Phase 6" (not "Skipping")
- [ ] Completion percentage > 80%
- [ ] Published to phase6-export-trigger topic
- [ ] **NO manual Pub/Sub publish was needed**

**If Phase 6 was SKIPPED:**
```bash
# ❌ FAILURE - Automatic Phase 6 failed
# This means consolidation or completion tracking is broken

# Check completion percentage
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  https://prediction-coordinator-756957797294.us-west2.run.app/progress | jq .

# If completion is low, check consolidation logs
# If consolidation succeeded but Phase 6 skipped, investigate completion event publishing

# Manual Phase 6 trigger
gcloud pubsub topics publish nba-phase6-export-trigger \
  --message='{"game_date":"'$(date +%Y-%m-%d)'"}'

# ⚠️ INVESTIGATE ROOT CAUSE AFTER FIXING
```

**Check Phase 6 Export Completion:**
```bash
gcloud logging read 'resource.labels.service_name="phase6-export" AND textPayload=~"Export completed" AND timestamp>="2026-01-01T11:55:00Z"' --limit=1 --format="value(timestamp,textPayload)"
```

**Expected Output:**
```
2026-01-01T12:06:30.xxxZ    [batch_xxx] Export completed in 150.0s
```

**Validation:**
- [ ] Export completed within 5 minutes of Phase 6 trigger
- [ ] No critical errors (409 conflicts are non-fatal)

---

#### Step 7: Verify Front-End Data Updated ✅

```bash
# Check all-players.json metadata
gsutil cat gs://nba-props-platform-api/v1/tonight/all-players.json | jq '{game_date, generated_at, total_players, total_with_lines, games_count: (.games | length)}'
```

**Expected Output:**
```json
{
  "game_date": "2026-01-01",
  "generated_at": "2026-01-01T12:06:30.000000+00:00",
  "total_players": 250,
  "total_with_lines": 120,
  "games_count": 8
}
```

**Validation:**
- [ ] `game_date` is today (2026-01-01)
- [ ] `generated_at` is within last 10 minutes
- [ ] `total_with_lines` matches prediction count
- [ ] Data is fresh and ready for front-end

**Sample Prediction Quality:**
```bash
gsutil cat gs://nba-props-platform-api/v1/tonight/all-players.json | jq '[.games[].players[] | select(.prediction)] | .[0:3] | .[] | {player: .player_lookup, line: .props[0].line, predicted: .prediction.predicted, confidence: .prediction.confidence, recommendation: .prediction.recommendation}'
```

**Expected:**
```json
{
  "player": "lebron-james",
  "line": 24.5,
  "predicted": 27.3,
  "confidence": 0.85,
  "recommendation": "OVER"
}
```

**Validation:**
- [ ] Players have valid predictions
- [ ] Confidence scores are reasonable (0.5-1.0)
- [ ] Recommendations are OVER or UNDER
- [ ] Predicted values make sense

---

## 📊 Final Validation Summary

### ✅ SUCCESS Criteria (All Must Pass)

**Pipeline Automation:**
- [ ] Scheduler triggered successfully
- [ ] Batch loader ran (331x speedup working)
- [ ] Workers generated predictions using batch data
- [ ] **Consolidation ran AUTOMATICALLY** ⭐
- [ ] **Phase 6 triggered AUTOMATICALLY** ⭐
- [ ] Front-end data updated automatically

**No Manual Interventions:**
- [ ] Zero manual consolidation needed
- [ ] Zero manual Phase 6 triggers needed
- [ ] Zero manual fixes required

**Performance:**
- [ ] Batch loading completed in <1 second
- [ ] All workers used pre-loaded data
- [ ] Total pipeline time <10 minutes

**Data Quality:**
- [ ] 100+ players with predictions
- [ ] All 5 systems generated predictions
- [ ] Front-end data is fresh (<10 min old)

---

## ❌ Failure Scenarios & Actions

### Scenario 1: Consolidation Didn't Run
**Symptoms:**
- No "Cleaned up staging" log message
- OR "Consolidation failed" error in logs

**Actions:**
1. Check error logs for MERGE query failures
2. Run manual consolidation
3. **Root cause:** Review coordinator consolidation trigger logic
4. **Fix needed:** Ensure consolidation runs after worker completion

**Next Steps:**
- File issue: "Automatic consolidation not triggering"
- Investigate completion event tracking
- Review batch completion handler code

---

### Scenario 2: Phase 6 Was Skipped
**Symptoms:**
- "Skipping Phase 6 trigger - completion too low"
- Completion percentage < 80%

**Actions:**
1. Check if consolidation completed successfully
2. Check completion percentage in /progress endpoint
3. Run manual Phase 6 trigger
4. **Root cause:** Completion events not being tracked correctly

**Next Steps:**
- File issue: "Phase 6 completion tracking broken"
- Investigate worker completion event publishing
- Verify completion event handler in coordinator

---

### Scenario 3: Scheduler Failed
**Symptoms:**
- Scheduler status: FAILED
- OR no logs from coordinator at 12:00 UTC

**Actions:**
1. Check scheduler error logs
2. Verify coordinator service is healthy
3. Run manual prediction trigger
4. **Root cause:** Cold start 404 or timeout

**Next Steps:**
- Verify scheduler retry logic is configured
- Consider min_instances=1 for coordinator
- Check if OIDC token is working

---

### Scenario 4: Batch Loader Failed
**Symptoms:**
- "Batch historical load failed" in logs
- Workers making individual queries

**Actions:**
1. Check data_loaders.py import errors
2. Verify BigQuery connectivity
3. **Root cause:** PredictionDataLoader initialization issue

**Next Steps:**
- Workers will fall back (slower but functional)
- Investigate data_loader import/initialization
- Check coordinator Docker image includes data_loaders.py

---

## 📝 Results Documentation

### After Validation, Document Results:

**File:** `docs/09-handoff/2026-01-01-VALIDATION-RESULTS.md`

**Template:**
```markdown
# Validation Results - January 1, 2026

**Time:** 7:10 AM ET
**Status:** [SUCCESS / PARTIAL / FAILURE]

## Checklist Results
- [ ] Scheduler triggered: [PASS/FAIL]
- [ ] Batch loader ran: [PASS/FAIL]
- [ ] Workers completed: [PASS/FAIL]
- [ ] Consolidation AUTOMATIC: [PASS/FAIL] ⭐
- [ ] Phase 6 AUTOMATIC: [PASS/FAIL] ⭐
- [ ] Front-end updated: [PASS/FAIL]

## Manual Interventions Required
- [ ] None (100% automatic) ✅
- OR list interventions needed

## Performance Metrics
- Batch loading time: ___ seconds
- Worker completion time: ___ seconds
- Total pipeline time: ___ minutes

## Issues Found
- None
- OR list issues with severity

## Next Steps
- [If SUCCESS] Pipeline is fully automatic! 🎉
- [If FAILURE] Root cause analysis needed
```

---

## 🎯 Success Metrics

### 🏆 COMPLETE SUCCESS
**All criteria met:**
- ✅ Health check script returns exit code 0
- ✅ Consolidation ran automatically
- ✅ Phase 6 triggered automatically
- ✅ Zero manual interventions
- ✅ Front-end data updated within 10 minutes

**Result:** Pipeline is fully automatic and production-ready! 🎉

---

### ⚠️ PARTIAL SUCCESS
**Some automation works, but manual intervention needed:**
- ✅ Predictions generated
- ✅ Batch loader working
- ❌ Consolidation required manual trigger
- OR ❌ Phase 6 required manual trigger

**Result:** Pipeline works but needs automation fixes

**Next Steps:**
1. Document which step required manual intervention
2. Investigate root cause
3. Fix automation gap
4. Retest tomorrow

---

### ❌ FAILURE
**Pipeline didn't run or multiple manual interventions needed:**
- ❌ Scheduler didn't trigger
- OR ❌ Multiple errors requiring manual fixes
- OR ❌ Front-end data not updated

**Result:** Major issues need investigation

**Next Steps:**
1. Emergency fix to get today's predictions out
2. Full root cause analysis
3. Review logs for all failures
4. Plan remediation strategy

---

## 📞 Quick Reference Commands

### Emergency Manual Triggers
```bash
# Manual predictions
curl -X POST -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"game_date":"TODAY","force":true}' \
  https://prediction-coordinator-756957797294.us-west2.run.app/start

# Manual consolidation
PYTHONPATH=/home/naji/code/nba-stats-scraper python3 \
  bin/predictions/consolidate/manual_consolidation.py

# Manual Phase 6
gcloud pubsub topics publish nba-phase6-export-trigger \
  --message='{"game_date":"'$(date +%Y-%m-%d)'"}'
```

### Quick Status Checks
```bash
# Scheduler status
gcloud scheduler jobs describe overnight-predictions --location=us-west2

# Coordinator health
curl -s https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/health | jq .

# Batch progress
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  https://prediction-coordinator-756957797294.us-west2.run.app/progress | jq .

# Front-end data age
gsutil cat gs://nba-props-platform-api/v1/tonight/all-players.json | jq -r '.generated_at'
```

---

## 🎯 Expected Timeline

**7:00 AM ET** - Scheduler triggers
**7:01 AM ET** - Batch loading completes (<1 second)
**7:02 AM ET** - Workers generate predictions (~30 seconds)
**7:03 AM ET** - Consolidation runs automatically (~30 seconds)
**7:04 AM ET** - Phase 6 orchestrator evaluates completion
**7:05 AM ET** - Phase 6 export starts
**7:07 AM ET** - Phase 6 export completes
**7:10 AM ET** - **YOU RUN HEALTH CHECK** ✅

---

## 📚 Related Documentation

- [Monitoring Setup](../08-projects/current/pipeline-reliability-improvements/MONITORING-SETUP.md)
- [Session Summary](./2026-01-01-SESSION-SUMMARY.md)
- [Batch Loader Verification](../08-projects/current/pipeline-reliability-improvements/BATCH-LOADER-VERIFICATION.md)

---

**Prepared:** January 1, 2026 02:50 UTC
**Target Validation:** January 1, 2026 07:10 ET
**Critical Validation:** Automatic consolidation + Phase 6 triggering
**Success Criteria:** Zero manual interventions required

---

## ✅ Pre-Validation Checklist

**Before you go to sleep tonight:**
- [x] All code committed and pushed to GitHub
- [x] Monitoring metrics created in Cloud Monitoring
- [x] Health check script tested and working
- [x] Manual intervention procedures documented
- [x] Validation checklist prepared (this document)

**Tomorrow morning:**
- [ ] Wait until 7:10 AM ET
- [ ] Run health check script
- [ ] Follow this checklist step by step
- [ ] Document results

---

**Good luck tomorrow! 🚀**

If all checks pass, we'll have achieved **full pipeline automation** - the ultimate goal of this entire project!
