# Prediction Monitoring System - Validation Guide

**Created:** 2026-01-18 (Session 106)
**Purpose:** Guide for future sessions to validate and troubleshoot the prediction monitoring system
**Last Updated:** 2026-01-18

---

## Quick Health Check (3 Minutes)

Run these commands to verify the system is working:

```bash
# 1. Check Cloud Functions are deployed and healthy
gcloud functions list --gen2 --filter="name:(validate-freshness OR check-missing OR reconcile)" \
  --format="table(name,state,serviceConfig.uri)" 2>&1 | grep -v "unrecognized"

# 2. Check Cloud Schedulers are enabled
gcloud scheduler jobs list --location=us-west2 \
  --format="table(name,schedule,state)" | \
  grep -E "validate-freshness|missing-prediction|daily-reconciliation"

# 3. Test check-missing endpoint (should return JSON with missing players)
curl -s "https://us-west2-nba-props-platform.cloudfunctions.net/check-missing?game_date=$(date +%Y-%m-%d)" | jq '.missing_count'
```

**Expected Results:**
- All 3 functions show `ACTIVE` state
- All 3 schedulers show `ENABLED` state
- check-missing returns a number (0 if all good, >0 if players missing)

---

## System Architecture

### Components Deployed

**Cloud Functions (3 functions):**
1. **validate-freshness** - Checks data freshness before predictions
   - URL: https://us-west2-nba-props-platform.cloudfunctions.net/validate-freshness
   - Entry point: `validate_freshness`
   - Service account: scheduler-orchestration@nba-props-platform

2. **check-missing** - Detects missing predictions + sends Slack alerts
   - URL: https://us-west2-nba-props-platform.cloudfunctions.net/check-missing
   - Entry point: `check_missing`
   - Service account: scheduler-orchestration@nba-props-platform
   - Secret: slack-webhook-monitoring-error

3. **reconcile** - Full pipeline reconciliation
   - URL: https://us-west2-nba-props-platform.cloudfunctions.net/reconcile
   - Entry point: `reconcile`
   - Service account: scheduler-orchestration@nba-props-platform
   - Secret: slack-webhook-monitoring-error

**Cloud Schedulers (3 jobs):**
- **validate-freshness-check**: `45 17 * * *` (5:45 PM ET daily)
- **missing-prediction-check**: `0 19 * * *` (7:00 PM ET daily)
- **daily-reconciliation**: `0 9 * * *` (9:00 AM ET daily)

**Slack Alerts:**
- Channel: Configured via secret `slack-webhook-monitoring-error`
- Alert level: CRITICAL for ANY missing player

---

## Detailed Validation Steps

### 1. Verify Cloud Functions Are Deployed

```bash
# List all monitoring functions
gcloud functions list --gen2 \
  --filter="name:(validate-freshness OR check-missing OR reconcile)" \
  --format="table(name,state,updateTime,serviceConfig.uri)" \
  2>&1 | grep -v "unrecognized"
```

**Expected Output:**
```
NAME                 STATE   UPDATE_TIME          URI
validate-freshness   ACTIVE  2026-01-18T22:18:51  https://validate-freshness-...
check-missing        ACTIVE  2026-01-18T22:19:46  https://check-missing-...
reconcile            ACTIVE  2026-01-18T22:20:54  https://reconcile-...
```

**Troubleshooting:**
- If `STATE` is not `ACTIVE`: Check deployment logs
- If missing: Redeploy using `./deploy.sh`

---

### 2. Test Each Endpoint Manually

#### Test validate-freshness

```bash
curl -s "https://us-west2-nba-props-platform.cloudfunctions.net/validate-freshness?game_date=2026-01-18" | jq '.'
```

**Expected Response:**
```json
{
  "fresh": true/false,
  "game_date": "2026-01-18",
  "max_age_hours": 24,
  "errors": [...],
  "details": {
    "phase3": {
      "total_players": 144,
      "players_with_lines": 60,
      "data_age_hours": 2.25,
      ...
    },
    ...
  }
}
```

**Key Fields:**
- `fresh`: Should be `true` if data is fresh
- `errors`: Should be empty array if no issues
- `details.phase3.total_players`: Should be 100+ for game days

---

#### Test check-missing

```bash
curl -s "https://us-west2-nba-props-platform.cloudfunctions.net/check-missing?game_date=$(date +%Y-%m-%d)" | jq '.'
```

**Expected Response:**
```json
{
  "game_date": "2026-01-18",
  "missing_count": 14,
  "missing_players": [
    {
      "player_lookup": "jamalmurray",
      "team_abbr": "DEN",
      "opponent_team_abbr": "CHA",
      "current_points_line": 28.5,
      "avg_minutes_per_game_last_7": 13.3,
      "player_status": null
    },
    ...
  ],
  "summary": {
    "eligible_players": 71,
    "predicted_players": 57,
    "coverage_percent": 80.28,
    ...
  },
  "alert_sent": true
}
```

**Key Fields:**
- `missing_count`: Number of missing predictions (0 = perfect)
- `alert_sent`: `true` if Slack alert was sent
- `summary.coverage_percent`: Should be ≥95% ideally

---

#### Test reconcile

```bash
curl -s "https://us-west2-nba-props-platform.cloudfunctions.net/reconcile?game_date=$(date +%Y-%m-%d)" | jq '.'
```

**Expected Response:**
```json
{
  "game_date": "2026-01-18",
  "timestamp": "2026-01-18T22:30:00",
  "freshness": {
    "passed": true,
    "errors": [],
    ...
  },
  "coverage": {
    "missing_count": 0,
    "alert_sent": false,
    ...
  },
  "overall_status": "PASS"
}
```

**Key Fields:**
- `overall_status`: Should be `"PASS"` for healthy system
- `freshness.passed`: Should be `true`
- `coverage.missing_count`: Should be `0`

---

### 3. Verify Cloud Schedulers

```bash
# List monitoring schedulers
gcloud scheduler jobs list --location=us-west2 \
  --format="table(name,schedule,state,lastAttemptTime,status)" | \
  grep -E "validate-freshness|missing-prediction|daily-reconciliation"
```

**Expected Output:**
```
NAME                          SCHEDULE        STATE    LAST_ATTEMPT_TIME      STATUS
validate-freshness-check      45 17 * * *     ENABLED  2026-01-18T17:45:00    SUCCESS
missing-prediction-check      0 19 * * *      ENABLED  2026-01-18T19:00:00    SUCCESS
daily-reconciliation          0 9 * * *       ENABLED  2026-01-18T09:00:00    SUCCESS
```

**Key Fields:**
- `STATE`: Must be `ENABLED` for all 3
- `STATUS`: Should be `SUCCESS` after first run
- `LAST_ATTEMPT_TIME`: Should update after each scheduled run

---

### 4. Test Manual Scheduler Trigger

```bash
# Trigger missing-prediction-check manually
gcloud scheduler jobs run missing-prediction-check --location=us-west2

# Wait 30 seconds, then check logs
sleep 30
gcloud logging read 'resource.type="cloud_scheduler_job" AND resource.labels.job_id="missing-prediction-check"' \
  --limit=1 --format=json | jq -r '.[0].textPayload'
```

**Expected Output:**
Should show successful HTTP request to Cloud Function

---

### 5. Verify Slack Integration

**Check if alert was sent:**
```bash
# Check function logs for Slack alert
gcloud functions logs read check-missing --gen2 --region=us-west2 --limit=20 | grep -i slack
```

**Expected Output:**
```
Sent missing prediction alert to Slack (14 missing)
```

**Manually verify in Slack:**
- Channel: The one configured in `slack-webhook-monitoring-error` secret
- Look for message with header: `🚨 MISSING PREDICTIONS ALERT`
- Should include player names, lines, and investigation steps

---

### 6. Check Secret Configuration

```bash
# Verify secret exists and has correct permissions
gcloud secrets describe slack-webhook-monitoring-error --format="value(name)"

# Check IAM policy
gcloud secrets get-iam-policy slack-webhook-monitoring-error
```

**Expected Output:**
Service account `scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com` should have `roles/secretmanager.secretAccessor` role.

---

## Monitoring Logs

### View Cloud Function Logs

```bash
# Last 20 entries from check-missing
gcloud functions logs read check-missing --gen2 --region=us-west2 --limit=20

# Filter for errors only
gcloud functions logs read check-missing --gen2 --region=us-west2 --limit=50 | grep -i error

# Real-time streaming
gcloud functions logs tail check-missing --gen2 --region=us-west2
```

### View Scheduler Execution Logs

```bash
# Last 5 executions of missing-prediction-check
gcloud logging read \
  'resource.type="cloud_scheduler_job" AND
   resource.labels.job_id="missing-prediction-check"' \
  --limit=5 --format=json | jq -r '.[] | "\(.timestamp) \(.textPayload)"'
```

### Check for Errors in Last 24 Hours

```bash
# All errors from monitoring functions
gcloud logging read \
  'resource.labels.service_name=~"(validate-freshness|check-missing|reconcile)" AND
   severity>=ERROR AND
   timestamp>="'$(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%S)'"' \
  --format=json | jq -r '.[] | "\(.timestamp) [\(.severity)] \(.textPayload // .jsonPayload.message)"'
```

---

## Common Issues and Solutions

### Issue 1: Cloud Function Returns 500 Error

**Symptoms:**
```bash
curl https://us-west2-nba-props-platform.cloudfunctions.net/check-missing
# Returns: 500 Internal Server Error
```

**Diagnosis:**
```bash
# Check function logs for errors
gcloud functions logs read check-missing --gen2 --region=us-west2 --limit=50 | grep -A 5 -i error
```

**Common Causes:**
1. **Missing BigQuery permissions**: Service account needs BigQuery Data Viewer role
2. **Missing secret access**: Service account needs secretmanager.secretAccessor on slack webhook
3. **Import errors**: Module dependencies not installed correctly

**Solution:**
```bash
# Grant BigQuery access
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/bigquery.dataViewer"

# Grant secret access
gcloud secrets add-iam-policy-binding slack-webhook-monitoring-error \
  --member="serviceAccount:scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

# Redeploy function
cd orchestration/cloud_functions/prediction_monitoring
./deploy.sh
```

---

### Issue 2: Scheduler Not Triggering

**Symptoms:**
- `lastAttemptTime` not updating
- No logs in Cloud Scheduler logs
- Functions never receive requests

**Diagnosis:**
```bash
# Check scheduler state
gcloud scheduler jobs describe missing-prediction-check --location=us-west2
```

**Solution:**
```bash
# Resume scheduler if paused
gcloud scheduler jobs resume missing-prediction-check --location=us-west2

# Manually trigger to test
gcloud scheduler jobs run missing-prediction-check --location=us-west2
```

---

### Issue 3: No Slack Alerts Received

**Symptoms:**
- `alert_sent: false` in response
- No errors in logs
- No message in Slack

**Diagnosis:**
```bash
# Check if secret has a value
gcloud secrets versions access latest --secret=slack-webhook-monitoring-error | head -c 50

# Check function logs for Slack errors
gcloud functions logs read check-missing --gen2 --region=us-west2 --limit=50 | grep -i "slack\|webhook"
```

**Solution:**
```bash
# Verify webhook URL is correct
gcloud secrets versions access latest --secret=slack-webhook-monitoring-error

# Test webhook manually
WEBHOOK_URL=$(gcloud secrets versions access latest --secret=slack-webhook-monitoring-error)
curl -X POST "$WEBHOOK_URL" \
  -H 'Content-Type: application/json' \
  -d '{"text":"Test message from monitoring system"}'
```

---

### Issue 4: False Positive Alerts

**Symptoms:**
- Alerts triggered when all predictions are actually present
- `missing_count` > 0 but players were actually predicted

**Diagnosis:**
```bash
# Check specific player in predictions table
bq query --nouse_legacy_sql "
SELECT player_lookup, COUNT(*) as predictions
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE DATE(game_date) = CURRENT_DATE()
  AND player_lookup = 'jamalmurray'
GROUP BY player_lookup
"

# Check player in upcoming_player_game_context
bq query --nouse_legacy_sql "
SELECT player_lookup, current_points_line, is_production_ready
FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date = CURRENT_DATE()
  AND player_lookup = 'jamalmurray'
"
```

**Solution:**
- If player is in predictions but still showing as missing: Query logic issue, check eligibility criteria
- If player is not in upstream table: Phase 3 timing issue (root cause from Session 106)

---

### Issue 5: Phase 4 Validation Fails

**Symptoms:**
```json
{
  "phase4_fresh": false,
  "phase4_reason": "Table ml_feature_store_v2 was not found"
}
```

**Diagnosis:**
The table might have a different name or not exist.

**Solution:**
```bash
# List tables in nba_analytics dataset
bq ls --max_results=100 nba-props-platform:nba_analytics | grep -i feature

# Update validator if table name is different
# Edit: orchestration/cloud_functions/prediction_monitoring/data_freshness_validator.py
# Line ~78: Update table name in query
```

---

## Daily Monitoring Routine

### Morning Routine (9:15 AM ET)

**After daily-reconciliation runs at 9:00 AM:**

```bash
# 1. Check if reconciliation passed
curl -s "https://us-west2-nba-props-platform.cloudfunctions.net/reconcile?game_date=$(date -d yesterday +%Y-%m-%d)" | jq '.overall_status'
# Expected: "PASS"

# 2. Check yesterday's coverage
curl -s "https://us-west2-nba-props-platform.cloudfunctions.net/check-missing?game_date=$(date -d yesterday +%Y-%m-%d)" | jq '.summary.coverage_percent'
# Expected: >= 95.0

# 3. Review any Slack alerts from yesterday
# Check Slack channel for alerts
```

---

### Evening Routine (7:15 PM ET)

**After missing-prediction-check runs at 7:00 PM:**

```bash
# 1. Check today's coverage
curl -s "https://us-west2-nba-props-platform.cloudfunctions.net/check-missing?game_date=$(date +%Y-%m-%d)" | jq '{missing: .missing_count, coverage: .summary.coverage_percent}'

# 2. If missing > 0, investigate
# View missing players
curl -s "https://us-west2-nba-props-platform.cloudfunctions.net/check-missing?game_date=$(date +%Y-%m-%d)" | jq '.missing_players[] | {player: .player_lookup, line: .current_points_line, team: .team_abbr}'

# 3. Check Slack for alert details
```

---

## Performance Metrics

### Expected Response Times

| Endpoint | Expected Time | Notes |
|----------|---------------|-------|
| validate-freshness | < 10 seconds | BigQuery queries Phase 3/4 tables |
| check-missing | < 15 seconds | Complex JOIN query + Slack API call |
| reconcile | < 20 seconds | Calls both validators + detector |

### Monitor Execution Times

```bash
# Check recent execution durations
gcloud logging read \
  'resource.labels.service_name="check-missing" AND
   jsonPayload.message:"Duration"' \
  --limit=5 --format=json | jq -r '.[] | "\(.timestamp) Duration: \(.jsonPayload.executionTime)ms"'
```

---

## Redeployment Guide

### When to Redeploy

- Code changes to validators or detector
- BigQuery schema changes
- New requirements or thresholds
- Bug fixes

### Redeployment Steps

```bash
# 1. Navigate to monitoring directory
cd /home/naji/code/nba-stats-scraper/orchestration/cloud_functions/prediction_monitoring

# 2. Ensure dependencies are up to date
cp ../../predictions/coordinator/data_freshness_validator.py .
cp ../../predictions/coordinator/missing_prediction_detector.py .
cp -r ../../shared/utils/slack_channels.py shared/utils/

# 3. Deploy all functions
./deploy.sh

# 4. Test endpoints
curl "https://us-west2-nba-props-platform.cloudfunctions.net/check-missing?game_date=$(date +%Y-%m-%d)" | jq '.missing_count'

# 5. Verify schedulers still enabled
gcloud scheduler jobs list --location=us-west2 | grep -E "validate-freshness|missing-prediction|daily-reconciliation"
```

---

## Related Documentation

- **Session Summary**: `docs/09-handoff/SESSION-106-SUMMARY.md`
- **Deployment Log**: `docs/09-handoff/SESSION-106-DEPLOYMENT.md`
- **Quick Start**: `orchestration/cloud_functions/prediction_monitoring/QUICK-START.md`
- **Full README**: `orchestration/cloud_functions/prediction_monitoring/README.md`

---

## Support Commands

```bash
# Complete health check script (copy-paste friendly)
echo "=== Monitoring System Health Check ===" && \
echo "1. Cloud Functions:" && \
gcloud functions list --gen2 --filter="name:(validate-freshness OR check-missing OR reconcile)" --format="table(name,state)" 2>&1 | grep -v "unrecognized" && \
echo "" && echo "2. Cloud Schedulers:" && \
gcloud scheduler jobs list --location=us-west2 --format="table(name,state)" | grep -E "validate-freshness|missing-prediction|daily-reconciliation" && \
echo "" && echo "3. Today's Coverage:" && \
curl -s "https://us-west2-nba-props-platform.cloudfunctions.net/check-missing?game_date=$(date +%Y-%m-%d)" | jq '{missing: .missing_count, coverage: .summary.coverage_percent, alert_sent: .alert_sent}' && \
echo "=== Health Check Complete ==="
```

---

**Validation Guide Version:** 1.0
**Last Updated:** 2026-01-18 2:30 PM ET
**Status:** ✅ System Deployed and Operational
