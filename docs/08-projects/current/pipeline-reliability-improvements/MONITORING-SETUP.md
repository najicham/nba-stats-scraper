# Pipeline Monitoring & Alerting Setup
**Date:** January 1, 2026
**Status:** 🟡 Partially Implemented (Metrics created, alerts pending)

---

## Overview

This document describes the monitoring and alerting setup for the NBA prediction pipeline, specifically designed to detect failures in the automatic daily runs.

### Critical Points to Monitor
1. **Scheduler Success** - Daily prediction schedulers must trigger successfully
2. **Batch Loading** - Coordinator must load historical games efficiently
3. **Consolidation** - Staging tables must merge into main predictions table
4. **Phase 6 Export** - Predictions must export to front-end
5. **Data Freshness** - Front-end data must update daily

---

## Quick Start

### Run Health Check (Manual)
```bash
# Check pipeline health for last hour
./bin/monitoring/check_pipeline_health.sh

# Check specific date
./bin/monitoring/check_pipeline_health.sh 2026-01-01
```

### Setup Log-Based Metrics
```bash
# Create all log-based metrics
./bin/monitoring/setup_alerts.sh
```

---

## Monitoring Scripts

### 1. Pipeline Health Check
**Location:** `bin/monitoring/check_pipeline_health.sh`

**Purpose:** Comprehensive health check for the entire pipeline

**Checks:**
- ✅ Batch loader execution (coordinator logs)
- ✅ Worker prediction generation
- ✅ Consolidation completion
- ✅ Phase 6 export success
- ✅ Front-end data freshness

**Usage:**
```bash
# Check last hour
./bin/monitoring/check_pipeline_health.sh

# Output example:
# ✓ SUCCESS: Batch loader ran: Batch loaded historical games for 118 players
# ✓ SUCCESS: Workers generated predictions: 50 completion events
# ⚠ WARNING: No consolidation completion detected (may still be running)
# ✓ SUCCESS: Phase 6 export completed: Export completed with errors in 156.0s
# ✓ SUCCESS: Front-end data is fresh (15 minutes old)
```

**When to Run:**
- After each scheduled run (7 AM ET, 11:30 AM ET, 6 PM ET)
- When investigating pipeline issues
- Before telling front-end data is ready

**Exit Codes:**
- `0` - All checks passed
- `1` - One or more checks failed
- `2` - Warnings detected (may not be critical)

---

### 2. Alert Setup Script
**Location:** `bin/monitoring/setup_alerts.sh`

**Purpose:** Create log-based metrics for Cloud Monitoring

**Creates 7 Metrics:**
1. `prediction_scheduler_failures` - Scheduler job failures
2. `batch_loading_failures` - Batch historical loading errors
3. `consolidation_failures` - Staging consolidation errors
4. `phase6_skipped` - Phase 6 skipped due to low completion
5. `staging_write_failures` - Worker staging write errors
6. `batch_completion_success` - Successful batch loading (positive signal)
7. `phase6_export_completions` - Successful Phase 6 exports

**Usage:**
```bash
./bin/monitoring/setup_alerts.sh
```

**Output:**
```
Creating log metric: prediction_scheduler_failures
  Creating new metric: prediction_scheduler_failures
...
✓ Log-based metrics created successfully!
```

---

## Log-Based Metrics Details

### 1. Scheduler Failures
**Metric:** `prediction_scheduler_failures`
**Filter:**
```
resource.type="cloud_scheduler_job"
AND (resource.labels.job_id="overnight-predictions"
     OR resource.labels.job_id="same-day-predictions"
     OR resource.labels.job_id="same-day-predictions-tomorrow")
AND jsonPayload.@type="type.googleapis.com/google.cloud.scheduler.logging.AttemptFinished"
AND jsonPayload.status!="OK"
```

**What it detects:** Any scheduler job that fails (404, 500, timeout, etc.)

**Alert Threshold:** > 0 failures in 5 minutes

**Why it matters:** If schedulers fail, predictions don't run automatically

---

### 2. Batch Loading Failures
**Metric:** `batch_loading_failures`
**Filter:**
```
resource.labels.service_name="prediction-coordinator"
AND textPayload=~"Batch historical load failed"
```

**What it detects:** Coordinator fails to pre-load historical games

**Alert Threshold:** > 0 failures in 5 minutes

**Why it matters:** Without batch loading, workers make individual BigQuery queries (225s vs 0.68s)

---

### 3. Consolidation Failures
**Metric:** `consolidation_failures`
**Filter:**
```
resource.labels.service_name="prediction-coordinator"
AND textPayload=~"Consolidation failed"
```

**What it detects:** MERGE query failures when consolidating staging tables

**Alert Threshold:** > 0 failures in 5 minutes

**Why it matters:** Predictions stay in staging tables, Phase 6 never triggers, front-end not updated

---

### 4. Phase 6 Skipped
**Metric:** `phase6_skipped`
**Filter:**
```
resource.labels.service_name="phase5-to-phase6-orchestrator"
AND textPayload=~"Skipping Phase 6 trigger"
```

**What it detects:** Phase 6 orchestrator skips export due to <80% completion

**Alert Threshold:** > 0 skips in 10 minutes

**Why it matters:** Front-end data doesn't update, users see stale predictions

---

### 5. Staging Write Failures
**Metric:** `staging_write_failures`
**Filter:**
```
resource.labels.service_name="prediction-worker"
AND textPayload=~"Staging write failed"
```

**What it detects:** Workers unable to write predictions to staging tables

**Alert Threshold:** > 10 failures in 5 minutes

**Why it matters:** Missing predictions, incomplete batches, low completion percentage

---

### 6. Batch Completion Success (Positive Signal)
**Metric:** `batch_completion_success`
**Filter:**
```
resource.labels.service_name="prediction-coordinator"
AND textPayload=~"Batch loaded historical games"
```

**What it detects:** Successful batch loading events

**Alert Threshold:** = 0 successes in 2 hours (during prediction windows)

**Why it matters:** Absence of success indicates pipeline not running at all

---

### 7. Phase 6 Export Completions (Positive Signal)
**Metric:** `phase6_export_completions`
**Filter:**
```
resource.labels.service_name="phase6-export"
AND textPayload=~"Export completed"
```

**What it detects:** Successful Phase 6 exports

**Alert Threshold:** = 0 completions in 2 hours (during prediction windows)

**Why it matters:** Front-end data must update daily

---

## Recommended Alert Policies

### High Priority Alerts (Immediate Action Required)

#### 1. Consolidation Failures
**Severity:** P1 - Critical
**Condition:** consolidation_failures > 0 in last 5 minutes
**Notification:** Email + Slack
**Action:** Run manual consolidation immediately
```bash
PYTHONPATH=/home/naji/code/nba-stats-scraper python3 \
  bin/predictions/consolidate/manual_consolidation.py
```

#### 2. Phase 6 Skipped
**Severity:** P1 - Critical
**Condition:** phase6_skipped > 0 in last 10 minutes
**Notification:** Email + Slack
**Action:**
1. Check consolidation logs
2. Manually trigger Phase 6 if needed
```bash
gcloud pubsub topics publish nba-phase6-export-trigger \
  --message='{"game_date":"TODAY"}'
```

#### 3. Scheduler Failures
**Severity:** P1 - Critical
**Condition:** prediction_scheduler_failures > 2 in last 1 hour
**Notification:** Email + Slack
**Action:**
1. Check coordinator health endpoint
2. Manually trigger predictions
```bash
curl -X POST -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"game_date":"TODAY","force":true}' \
  https://prediction-coordinator-756957797294.us-west2.run.app/start
```

---

### Medium Priority Alerts (Action Within 1 Hour)

#### 4. Batch Loading Failures
**Severity:** P2 - High
**Condition:** batch_loading_failures > 0 in last 15 minutes
**Notification:** Email
**Action:**
1. Check data_loaders.py logs
2. Verify BigQuery connectivity
3. Workers will fall back to individual queries (slower but functional)

#### 5. Staging Write Failures (Widespread)
**Severity:** P2 - High
**Condition:** staging_write_failures > 20 in last 10 minutes
**Notification:** Email
**Action:**
1. Check dataset_prefix configuration
2. Verify staging table permissions
3. Check BigQuery quotas

---

### Low Priority Alerts (Informational)

#### 6. No Batch Success in Prediction Window
**Severity:** P3 - Medium
**Condition:** batch_completion_success = 0 between 07:00-08:00 ET
**Notification:** Email
**Action:** Verify schedulers triggered, check coordinator logs

#### 7. No Phase 6 Exports
**Severity:** P3 - Medium
**Condition:** phase6_export_completions = 0 in last 3 hours
**Notification:** Email
**Action:** Check orchestrator logs, verify completion thresholds

---

## Daily Monitoring Schedule

### Tomorrow's Test Run (January 1, 2026)

**Overnight Predictions Scheduler:** 7:00 AM ET (12:00 UTC)

**Monitoring Timeline:**
```
07:00 ET - Scheduler triggers
07:01 ET - Check: Batch loading started
07:02 ET - Check: Workers generating predictions
07:03 ET - Check: Consolidation running
07:04 ET - Check: Phase 6 triggered
07:05 ET - Check: Front-end data updated

07:10 ET - Run full health check:
           ./bin/monitoring/check_pipeline_health.sh
```

**What to Verify:**
- [ ] Scheduler triggered successfully (no 404 errors)
- [ ] Batch loader ran (<1 second)
- [ ] All workers used pre-loaded data
- [ ] Consolidation ran AUTOMATICALLY (no manual intervention)
- [ ] Phase 6 triggered AUTOMATICALLY (completion > 80%)
- [ ] Front-end data updated (all-players.json timestamp)

**Success Criteria:**
- ✅ No manual intervention required
- ✅ Zero consolidation failures
- ✅ Zero Phase 6 skips
- ✅ Front-end data timestamp within 10 minutes of scheduler trigger

**If ANY check fails:**
1. Run health check script
2. Review logs for specific service
3. Apply manual fix if needed
4. File issue for permanent fix

---

## Manual Intervention Procedures

### If Consolidation Fails
```bash
# 1. Check error logs
gcloud logging read \
  'resource.labels.service_name="prediction-coordinator" AND
   textPayload=~"Consolidation failed"' \
  --limit=5 --format="value(textPayload,timestamp)"

# 2. Run manual consolidation
PYTHONPATH=/home/naji/code/nba-stats-scraper python3 \
  bin/predictions/consolidate/manual_consolidation.py

# 3. Verify success
bq query --use_legacy_sql=false "
SELECT COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)"
```

### If Phase 6 Doesn't Trigger
```bash
# 1. Check orchestrator logs
gcloud logging read \
  'resource.labels.service_name="phase5-to-phase6-orchestrator"' \
  --limit=10 --freshness=30m

# 2. Manually trigger Phase 6
gcloud pubsub topics publish nba-phase6-export-trigger \
  --message='{"game_date":"'$(date +%Y-%m-%d)'"}'

# 3. Verify export completed
sleep 180 && gsutil cat \
  gs://nba-props-platform-api/v1/tonight/all-players.json | \
  jq '.generated_at, .total_with_lines'
```

### If Scheduler Fails
```bash
# 1. Check scheduler status
gcloud scheduler jobs describe overnight-predictions \
  --location=us-west2 \
  --format="yaml(status)"

# 2. Manually trigger predictions
curl -X POST \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"game_date":"TODAY","force":true}' \
  https://prediction-coordinator-756957797294.us-west2.run.app/start

# 3. Monitor progress
sleep 60 && ./bin/monitoring/check_pipeline_health.sh
```

---

## Cloud Console Links

### Logs Explorer
**Prediction Coordinator:**
```
https://console.cloud.google.com/logs/query;query=resource.labels.service_name%3D%22prediction-coordinator%22;timeRange=PT1H?project=nba-props-platform
```

**Prediction Worker:**
```
https://console.cloud.google.com/logs/query;query=resource.labels.service_name%3D%22prediction-worker%22;timeRange=PT1H?project=nba-props-platform
```

**Phase 6 Orchestrator:**
```
https://console.cloud.google.com/logs/query;query=resource.labels.service_name%3D%22phase5-to-phase6-orchestrator%22;timeRange=PT1H?project=nba-props-platform
```

**Phase 6 Export:**
```
https://console.cloud.google.com/logs/query;query=resource.labels.service_name%3D%22phase6-export%22;timeRange=PT1H?project=nba-props-platform
```

### Monitoring Dashboards
**Log-Based Metrics:**
```
https://console.cloud.google.com/logs/metrics?project=nba-props-platform
```

**Alert Policies:**
```
https://console.cloud.google.com/monitoring/alerting?project=nba-props-platform
```

**Uptime Checks:**
```
https://console.cloud.google.com/monitoring/uptime?project=nba-props-platform
```

---

## Key Log Queries

### Today's Batch Loading Success
```
resource.labels.service_name="prediction-coordinator"
AND textPayload=~"Batch loaded historical games"
AND timestamp >= timestamp("TODAY")
```

### Today's Consolidation Attempts
```
resource.labels.service_name="prediction-coordinator"
AND (textPayload=~"Consolidation failed" OR textPayload=~"Cleaned up staging")
AND timestamp >= timestamp("TODAY")
```

### Today's Phase 6 Status
```
resource.labels.service_name="phase5-to-phase6-orchestrator"
AND timestamp >= timestamp("TODAY")
```

### Worker Errors (Last Hour)
```
resource.labels.service_name="prediction-worker"
AND severity >= "ERROR"
AND timestamp >= timestamp_sub(current_timestamp(), interval 1 hour)
```

---

## Troubleshooting Guide

### Pipeline Not Running
**Symptom:** No logs from coordinator in last 2 hours during prediction window

**Check:**
1. Scheduler job last run time
2. Coordinator service status
3. Cloud Run deployment status

**Fix:**
```bash
# Check scheduler
gcloud scheduler jobs describe overnight-predictions --location=us-west2

# Check service
gcloud run services describe prediction-coordinator --region=us-west2

# Manually trigger
curl -X POST -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"game_date":"TODAY"}' \
  https://prediction-coordinator-756957797294.us-west2.run.app/start
```

---

### Batch Loader Not Working
**Symptom:** Logs show "Batch historical load failed"

**Check:**
1. data_loaders.py import errors
2. BigQuery connectivity
3. PredictionDataLoader initialization

**Fix:**
```bash
# Check coordinator logs for detailed error
gcloud logging read \
  'resource.labels.service_name="prediction-coordinator" AND
   textPayload=~"Batch historical"' \
  --limit=5 --format="value(textPayload)"

# Workers will fall back to individual queries (slower but functional)
# No immediate action needed unless performance is critical
```

---

### Consolidation Failures
**Symptom:** "Consolidation failed" or "Invalid MERGE query"

**Check:**
1. MERGE query syntax errors
2. BigQuery partitioning errors
3. Staging table existence

**Fix:**
```bash
# Run manual consolidation
PYTHONPATH=/home/naji/code/nba-stats-scraper python3 \
  bin/predictions/consolidate/manual_consolidation.py

# If still failing, check MERGE query in batch_staging_writer.py
# Look for FLOAT64 partitioning errors or type mismatches
```

---

### Phase 6 Skipped
**Symptom:** "Skipping Phase 6 trigger - completion too low"

**Check:**
1. Consolidation completed successfully
2. Completion percentage (should be > 80%)
3. Phase 5 completion message published

**Fix:**
```bash
# Check completion status
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  https://prediction-coordinator-756957797294.us-west2.run.app/progress

# If consolidation failed, fix that first
# Then manually trigger Phase 6
gcloud pubsub topics publish nba-phase6-export-trigger \
  --message='{"game_date":"'$(date +%Y-%m-%d)'"}'
```

---

## Future Improvements

### Short-Term (Next Week)
1. Create actual alert policies from log-based metrics
2. Set up email notification channel
3. Create Slack webhook for critical alerts
4. Add uptime checks for coordinator /health endpoint

### Medium-Term (Next Month)
1. Create Cloud Monitoring dashboard with all metrics
2. Set up SLIs (Service Level Indicators) for pipeline
3. Implement circuit breaker pattern for repeated failures
4. Add automatic retry logic for consolidation failures

### Long-Term (Next Quarter)
1. Integrate with PagerDuty for on-call rotations
2. Create runbook automation (auto-remediation)
3. Implement prediction pipeline SLAs
4. Add predictive alerts (detect issues before they occur)

---

## Testing Alerts

To test alerts are working:

### 1. Test Scheduler Failure Alert
```bash
# Manually fail a scheduler (don't do this in production!)
# Instead, verify alert works by checking metric in console
```

### 2. Test Consolidation Alert
```bash
# Monitor existing consolidation_failures metric
# Next consolidation failure will trigger alert
```

### 3. Test Health Check Script
```bash
# Run health check
./bin/monitoring/check_pipeline_health.sh

# Should output SUCCESS for all checks if pipeline recently ran
```

---

## Related Documentation

- [Session Summary](../../09-handoff/2026-01-01-SESSION-SUMMARY.md) - Tonight's debugging session
- [Batch Loader Verification](./BATCH-LOADER-VERIFICATION.md) - Performance verification
- [Manual Consolidation Script](../../../bin/predictions/consolidate/manual_consolidation.py) - Emergency consolidation

---

**Last Updated:** January 1, 2026
**Next Review:** After first successful automatic run (January 1, 7 AM ET)
**Owner:** Pipeline Team
