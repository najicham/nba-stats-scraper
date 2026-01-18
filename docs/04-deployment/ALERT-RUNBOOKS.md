# NBA Prediction Platform - Alert Runbooks

**Status**: Week 3 Implementation Complete (2026-01-17)
**Related Docs**:
- [Alerting Strategy](./ALERTING-AND-VISIBILITY-STRATEGY.md)
- [Implementation Roadmap](./IMPLEMENTATION-ROADMAP.md)
- [Environment Variables](./NBA-ENVIRONMENT-VARIABLES.md)
- [Week 3 Implementation](../08-projects/option-b-alerting/WEEK-3-IMPLEMENTATION-COMPLETE.md)

---

## Table of Contents

**Week 3: Dashboards & Visibility**
- [Cloud Monitoring Dashboards](#cloud-monitoring-dashboards)
- [Daily Slack Summaries](#daily-slack-summaries)
- [Configuration Audit Trail](#configuration-audit-trail)

**Week 1: Critical Alerts**
1. [Model Loading Failure Alert](#model-loading-failure-alert)
2. [High Fallback Prediction Rate Alert](#high-fallback-prediction-rate-alert)

**Week 2: Warning Alerts**
3. [Environment Variable Change Alert](#environment-variable-change-alert)
4. [Deep Health Check Failure Alert](#deep-health-check-failure-alert)
5. [Stale Predictions Alert](#stale-predictions-alert)
6. [High DLQ Depth Alert](#high-dlq-depth-alert)
7. [Feature Pipeline Staleness Check](#feature-pipeline-staleness-check)
8. [Confidence Distribution Drift Check](#confidence-distribution-drift-check)

---

## Cloud Monitoring Dashboards

### Overview

Three comprehensive dashboards provide real-time visibility into the NBA prediction system:

1. **NBA Prediction Metrics Dashboard** - Service performance and health
2. **NBA Data Pipeline Health Dashboard** - Data quality and infrastructure
3. **NBA Model Performance Dashboard** - ML model metrics and predictions

### Accessing Dashboards

**Method 1: Cloud Console**
1. Go to https://console.cloud.google.com/monitoring
2. Select project: `nba-props-platform`
3. Click "Dashboards" in left menu
4. Look for dashboards starting with "NBA"

**Method 2: Direct Links**
```bash
# Get dashboard URLs
gcloud monitoring dashboards list \
  --project=nba-props-platform \
  --format="table(name,displayName)"
```

**Method 3: CLI**
```bash
# List all dashboards
gcloud monitoring dashboards list --project=nba-props-platform
```

### Dashboard 1: NBA Prediction Metrics

**Widgets:**
- Prediction request rate (requests/minute)
- Response latency (P50, P95 percentiles)
- Fallback prediction rate with thresholds (5%, 10%)
- Model loading failures
- Container instances, memory, CPU utilization
- Environment variable changes detected
- Error rate (5xx responses)

**Key Thresholds:**
- Fallback rate > 5%: Warning (yellow)
- Fallback rate > 10%: Critical (red)
- Model load failures > 0: Critical (red)
- Memory > 80%: Warning, > 90%: Critical
- P95 latency > 3s: Warning, > 5s: Critical

**When to Check:**
- After deployments (verify no degradation)
- When investigating performance issues
- Daily health check (glance at fallback rate, errors)

### Dashboard 2: NBA Data Pipeline Health

**Widgets:**
- Feature pipeline staleness alerts
- Confidence distribution drift alerts
- BigQuery query performance (P95)
- Pub/Sub topic throughput
- Dead Letter Queue depth
- Oldest unacked message age
- BigQuery scanned bytes (cost indicator)
- GCS bucket operations

**Key Thresholds:**
- DLQ depth > 50: Warning, > 100: Critical
- Oldest message age > 1 hour: Warning, > 24 hours: Critical
- Feature staleness > 4 hours: Warning

**When to Check:**
- When predictions seem stale
- During data pipeline troubleshooting
- Cost optimization reviews (BigQuery bytes)

### Dashboard 3: NBA Model Performance

**Widgets:**
- CatBoost V8 & XGBoost V1 prediction rates
- High confidence predictions (>= 0.70)
- OVER/UNDER recommendation breakdown
- Model loading success at startup
- Prediction errors and exceptions
- Low confidence / PASS recommendations
- System health scorecards
- Active alerts count

**Key Metrics:**
- High confidence predictions should be 30-50% of total
- PASS recommendations should be < 20% of total
- Model loading success should be 100%
- Active alerts should be 0

**When to Check:**
- Daily performance review
- When investigating prediction accuracy
- After model updates or retraining

### Creating New Dashboards

If dashboards need to be recreated:

```bash
# Deploy all 3 dashboards
cd /home/naji/code/nba-stats-scraper
./bin/alerts/create_dashboards.sh nba-props-platform prod
```

**Deployment time:** 2-3 minutes
**Result:** 3 dashboard URLs printed to console

### Troubleshooting

**Problem: Widgets show "No data available"**
- **Cause:** Metrics not yet generated or log-based metrics not created
- **Solution:** Wait 5 minutes for metrics to populate, check log-based metric exists

**Problem: Dashboard not found**
- **Cause:** Dashboard deleted or project mismatch
- **Solution:** Redeploy using `create_dashboards.sh`

**Problem: Metrics delay**
- **Cause:** Cloud Monitoring has 1-2 minute lag
- **Solution:** Normal behavior, use logs for real-time data

---

## Daily Slack Summaries

### Overview

Automated daily summary sent to Slack at **9:00 AM ET** with yesterday's prediction stats, top picks, and system health.

### Summary Content

```
🏀 NBA Predictions Daily Summary - [Date]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 Yesterday's Stats
• Predictions Generated: 2,250
• Unique Players: 450
• Systems Operational: 5/5 ✅
• Average Confidence: 87.2%
• Fallback Rate: 1.2% ✅

📈 Recommendations Breakdown
• OVER: 1,100
• UNDER: 1,050
• PASS: 100

🎯 Top 5 Picks (by confidence)
1. LeBron James OVER 26.5 (94.3% conf) [catboost_v8]
2. Stephen Curry OVER 24.5 (93.8% conf) [catboost_v8]
...

⚙️ System Health
• Model Loading: ✅ All operational
• Feature Quality: ✅ Fresh (2.3h old)
• Alerts (24h): 0 🎉

🔗 Quick Links
• Dashboards | Logs | BigQuery
```

### Interpreting the Summary

**📊 Yesterday's Stats:**
- **Predictions Generated:** Total predictions across all systems
  - Normal: 2,000-3,000 (depends on games scheduled)
  - Low: < 1,000 (investigate - missing games or systems down)
  - High: > 4,000 (many games or systems running multiple times)

- **Systems Operational:** Count of active prediction systems
  - Expected: 5/5 (all systems healthy)
  - Warning: 4/5 or less (check logs for failures)

- **Average Confidence:** Mean confidence across all predictions
  - Healthy: 75-90%
  - Warning: 60-75% (lower quality predictions)
  - Critical: < 60% or > 95% (investigate unusual pattern)

- **Fallback Rate:** Percentage using fallback (50% confidence)
  - Healthy: < 5%
  - Warning: 5-10%
  - Critical: > 10% (model loading issues)

**🎯 Top 5 Picks:**
- Shows highest confidence predictions for reference
- Can be shared with users or used for quality spot-checks
- System ID shows which model generated the prediction

**⚙️ System Health:**
- **Model Loading:** Should always be ✅
- **Feature Quality:** Features should be < 4 hours old
- **Alerts:** Count of alerts triggered in last 24 hours

### Manual Triggering

To send summary immediately (for testing):

```bash
# Method 1: Trigger Cloud Scheduler
gcloud scheduler jobs run nba-daily-summary-prod \
  --location=us-west2 \
  --project=nba-props-platform

# Method 2: Call Cloud Function directly
curl -X POST https://<REGION>-<PROJECT>.cloudfunctions.net/nba-daily-summary-prod
```

### Troubleshooting

**Problem: Summary not received**
1. Check Cloud Scheduler job status:
```bash
gcloud scheduler jobs describe nba-daily-summary-prod \
  --location=us-west2 \
  --project=nba-props-platform
```

2. Check Cloud Function logs:
```bash
gcloud functions logs read nba-daily-summary-prod \
  --region=us-west2 \
  --project=nba-props-platform \
  --limit=50
```

3. Verify Slack webhook:
```bash
gcloud secrets versions access latest \
  --secret=nba-daily-summary-slack-webhook \
  --project=nba-props-platform
```

**Problem: Incorrect data in summary**
- Compare with BigQuery directly:
```sql
SELECT COUNT(*) FROM `nba_predictions.player_prop_predictions`
WHERE created_at >= TIMESTAMP(CURRENT_DATE() - 1)
AND created_at < TIMESTAMP(CURRENT_DATE())
```

**Problem: Summary shows 0 predictions**
- Check if predictions actually ran yesterday
- Verify BigQuery table has data
- Check for date/timezone issues (summary uses UTC)

### Modifying Summary Schedule

To change the schedule (currently 9 AM ET):

```bash
# Update scheduler schedule
gcloud scheduler jobs update http nba-daily-summary-prod \
  --location=us-west2 \
  --project=nba-props-platform \
  --schedule="0 10 * * *"  # 10 AM ET instead
```

### Deployment

If Cloud Function needs redeployment:

```bash
cd /home/naji/code/nba-stats-scraper
export SLACK_WEBHOOK_URL='https://hooks.slack.com/services/...'
./bin/alerts/deploy_daily_summary.sh nba-props-platform us-west2 prod
```

---

## Configuration Audit Trail

### Overview

Complete audit log of all environment variable changes stored in BigQuery table `nba_orchestration.env_var_audit`.

**Purpose:**
- Track who changed what and when
- Investigate incidents (e.g., "When was CATBOOST_V8_MODEL_PATH deleted?")
- Compliance and security audits
- Understand deployment history

### Accessing Audit Data

**Quick View (Last 30 Days):**
```sql
SELECT *
FROM `nba_orchestration.recent_env_changes`
ORDER BY timestamp DESC
LIMIT 50;
```

**Changes to Specific Variable:**
```sql
SELECT
  timestamp,
  change_type,
  var.var_name,
  var.old_value,
  var.new_value,
  reason,
  alert_triggered
FROM `nba_orchestration.env_var_audit`,
UNNEST(changed_vars) as var
WHERE var.var_name = 'CATBOOST_V8_MODEL_PATH'
ORDER BY timestamp DESC;
```

**Unexpected Changes (Alerts):**
```sql
SELECT *
FROM `nba_orchestration.recent_env_changes`
WHERE alert_triggered = TRUE
ORDER BY timestamp DESC;
```

### Common Investigation Patterns

**Pattern 1: "When did this break?"**
Find when a critical variable was removed or changed:

```sql
SELECT
  timestamp,
  change_type,
  changed_vars,
  deployer,
  reason
FROM `nba_orchestration.env_var_audit`
WHERE EXISTS (
  SELECT 1 FROM UNNEST(changed_vars) as var
  WHERE var.var_name = 'CATBOOST_V8_MODEL_PATH'
  AND (change_type = 'REMOVED' OR var.new_value IS NULL)
)
ORDER BY timestamp DESC
LIMIT 10;
```

**Pattern 2: "Who made changes?"**
See all changes by a specific deployer:

```sql
SELECT
  timestamp,
  change_type,
  affected_variables,
  reason
FROM `nba_orchestration.recent_env_changes`
WHERE deployer = 'prediction-worker'
ORDER BY timestamp DESC;
```

**Pattern 3: "What changed during deployment?"**
View changes during a specific deployment:

```sql
SELECT
  timestamp,
  change_type,
  changed_vars,
  in_deployment_window
FROM `nba_orchestration.env_var_audit`
WHERE DATE(timestamp) = '2026-01-17'
ORDER BY timestamp;
```

### Audit Data Fields

- **change_id:** Unique identifier for this change
- **timestamp:** When change was detected (UTC)
- **change_type:** ADDED, REMOVED, MODIFIED, DEPLOYMENT_START, BASELINE_INIT
- **changed_vars:** Array of variables that changed
- **deployer:** Service account or user (usually "prediction-worker")
- **reason:** Why change occurred
- **deployment_started_at:** Deployment start time (if applicable)
- **in_deployment_window:** Whether during grace period
- **alert_triggered:** Whether this triggered an alert
- **alert_reason:** Why alert fired

### Visualizing Audit Data

**Option 1: Looker Studio**
1. Create data source: `nba_orchestration.recent_env_changes`
2. Add timeline chart (timestamp vs change count)
3. Add pie chart (change_type distribution)
4. Filter by alert_triggered for incident view

**Option 2: Export to Sheets**
```sql
SELECT
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', timestamp) as time,
  change_type,
  ARRAY_TO_STRING(affected_variables, ', ') as variables,
  reason,
  CASE WHEN alert_triggered THEN '⚠️ YES' ELSE '✓ No' END as alert
FROM `nba_orchestration.recent_env_changes`
ORDER BY timestamp DESC
LIMIT 100;
```

### Complete Documentation

See: `schemas/bigquery/nba_orchestration/AUDIT_DATA_ACCESS.md`

---

## Model Loading Failure Alert

### Alert Details

- **Name**: `[CRITICAL] NBA Model Loading Failures`
- **Severity**: CRITICAL
- **Metric**: `nba_model_load_failures`
- **Threshold**: > 0 errors in 5-minute window
- **Service**: `prediction-worker`
- **Notification**: Slack (#platform-team or configured channel)

### What This Alert Means

The CatBoost V8 machine learning model failed to load at service startup or during runtime. This means:
- **All predictions will use fallback mode** (50% confidence, PASS recommendation)
- **Prediction quality is degraded** - no actual ML-based predictions
- **Business impact**: Users receive conservative recommendations instead of data-driven predictions

### Common Causes

1. **Missing `CATBOOST_V8_MODEL_PATH` environment variable**
   - Most likely cause (what happened in Jan 2026 incident)
   - Service deployed without this critical env var

2. **GCS permission issues**
   - Service account lacks `storage.objects.get` permission
   - Bucket or object access misconfigured

3. **Model file doesn't exist or moved**
   - Path points to non-existent GCS object
   - Model file was deleted or relocated

4. **CatBoost library issues**
   - Library not installed in Docker image
   - Version incompatibility

### Investigation Steps

#### 1. Check Environment Variables

```bash
# View current env vars
gcloud run services describe prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --format=json | jq -r '.spec.template.spec.containers[0].env[] | "\(.name)=\(.value)"'

# Expected output should include:
# CATBOOST_V8_MODEL_PATH=gs://nba-props-platform-models/catboost/v8/catboost_v8_33features_YYYYMMDD_HHMMSS.cbm
```

**If `CATBOOST_V8_MODEL_PATH` is missing**: → Go to Fix #1

#### 2. Check Service Logs

```bash
# View recent error logs
gcloud logging read 'resource.labels.service_name="prediction-worker"
  AND severity>=ERROR
  AND textPayload=~"model"' \
  --project=nba-props-platform \
  --limit=10 \
  --format="table(timestamp,severity,textPayload)"
```

Look for:
- `"CatBoost V8 model FAILED to load"`
- `"403"` or `"Permission denied"` → GCS permission issue (Fix #2)
- `"404"` or `"not found"` → Model file doesn't exist (Fix #3)
- Other error messages → Library or code issues (Fix #4)

#### 3. Verify Model File Exists

```bash
# Check if model file exists in GCS
# (Replace path with actual path from env var)
gsutil ls gs://nba-props-platform-models/catboost/v8/

# Try to access the specific model file
gsutil stat gs://nba-props-platform-models/catboost/v8/catboost_v8_33features_20260108_211817.cbm
```

#### 4. Check Service Account Permissions

```bash
# Get the service account
SERVICE_ACCOUNT=$(gcloud run services describe prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --format="value(spec.template.spec.serviceAccountName)")

echo "Service Account: $SERVICE_ACCOUNT"

# Check IAM policy on the bucket
gsutil iam get gs://nba-props-platform-models | grep -A 5 "$SERVICE_ACCOUNT"
```

### Fixes

#### Fix #1: Restore Missing Environment Variable

```bash
# Set the CATBOOST_V8_MODEL_PATH environment variable
# ⚠️ CRITICAL: Use --update-env-vars, NOT --set-env-vars

# Get the latest model path
LATEST_MODEL=$(gsutil ls gs://nba-props-platform-models/catboost/v8/ | grep 'catboost_v8_33features' | sort | tail -1)

echo "Latest model: $LATEST_MODEL"

# Update env var (preserves all other env vars)
gcloud run services update prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --update-env-vars CATBOOST_V8_MODEL_PATH="$LATEST_MODEL"
```

**Verification**:
```bash
# Wait 1-2 minutes for new revision to deploy
# Check logs for successful model load
gcloud logging read 'resource.labels.service_name="prediction-worker"
  AND textPayload=~"CATBOOST_V8_MODEL_PATH set"' \
  --project=nba-props-platform \
  --limit=5
```

#### Fix #2: Grant GCS Read Permission

```bash
# Grant service account permission to read from models bucket
SERVICE_ACCOUNT="prediction-worker@nba-props-platform.iam.gserviceaccount.com"

gsutil iam ch serviceAccount:$SERVICE_ACCOUNT:objectViewer \
  gs://nba-props-platform-models
```

**Verification**:
```bash
# Restart the service to trigger model reload
gcloud run services update prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --update-env-vars DUMMY=restart

# Check logs for successful load
gcloud logging read 'resource.labels.service_name="prediction-worker"
  AND (textPayload=~"✓ CATBOOST_V8_MODEL_PATH" OR textPayload=~"model loaded")' \
  --project=nba-props-platform \
  --limit=5
```

#### Fix #3: Update Model Path

```bash
# List available models
gsutil ls gs://nba-props-platform-models/catboost/v8/

# Update to correct path
gcloud run services update prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --update-env-vars CATBOOST_V8_MODEL_PATH="gs://nba-props-platform-models/catboost/v8/[CORRECT_MODEL_FILE]"
```

#### Fix #4: Code or Library Issues

If the issue is not env var or permissions:

1. Check Docker image includes catboost:
   ```bash
   # Check requirements.txt
   cat predictions/worker/requirements.txt | grep catboost
   ```

2. Review recent code changes:
   ```bash
   git log --oneline -10 predictions/worker/
   ```

3. Rollback to last known good revision:
   ```bash
   # List recent revisions
   gcloud run revisions list --service=prediction-worker \
     --region=us-west2 --project=nba-props-platform --limit=5

   # Rollback to previous revision
   gcloud run services update-traffic prediction-worker \
     --region=us-west2 --project=nba-props-platform \
     --to-revisions=[PREVIOUS_REVISION]=100
   ```

### Verification

After applying fix, verify the system is healthy:

```bash
# 1. Check predictions are using actual model (not fallback)
bq query --use_legacy_sql=false --project_id=nba-props-platform '
SELECT
  ROUND(confidence_score * 100) as confidence,
  COUNT(*) as predictions
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE system_id = "catboost_v8"
  AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
GROUP BY confidence
ORDER BY confidence DESC
LIMIT 10'

# Expected: Variety of scores (79-95%), NO 50%
# If you see 50% scores: Model still not loading correctly

# 2. Check alert has cleared
gcloud alpha monitoring policies list \
  --project=nba-props-platform \
  --filter="displayName:'Model Loading Failures'" \
  --format="table(displayName,conditions[0].displayName,enabled)"
```

### Prevention

To prevent this alert in the future:

1. **Never use `--set-env-vars`** - always use `--update-env-vars`
2. **Use Infrastructure as Code** - Store env vars in version control
3. **Implement startup validation** - Service logs ERROR on missing vars (implemented Week 1)
4. **Test deployments in staging** - Catch issues before production

### Related Incidents

- **Jan 14-17, 2026**: CatBoost V8 incident - `CATBOOST_V8_MODEL_PATH` deleted during deployment
  - Detection time: 3 days (manual)
  - Impact: 1,071 degraded predictions
  - Root cause: Used `--set-env-vars` instead of `--update-env-vars`
  - Resolution: Restored env var, deleted bad predictions
  - Prevention: This alert + startup validation

---

## High Fallback Prediction Rate Alert

### Alert Details

- **Name**: `[CRITICAL] NBA High Fallback Prediction Rate`
- **Severity**: CRITICAL
- **Metric**: `nba_fallback_predictions`
- **Threshold**: > 10% of predictions in 10-minute window
- **Service**: `prediction-worker`
- **Notification**: Slack (#platform-team or configured channel)

### What This Alert Means

More than 10% of predictions are using fallback mode (weighted average, 50% confidence, PASS recommendation). This indicates:
- **CatBoost V8 model is not generating predictions** for many players
- **Prediction quality is degraded** for affected players
- **Possible systemic issue** with model loading or feature data

### Normal vs. Abnormal Fallback Rates

**Normal**:
- **0-5%**: A few players may lack features or historical data
- **Isolated fallbacks**: New players, first game of season, data gaps

**Abnormal** (triggers alert):
- **> 10%**: Systemic issue with model or features
- **Sustained fallbacks**: Many players over extended period

### Common Causes

1. **Model failed to load** (but service started successfully)
   - Most common cause
   - Check Model Loading Failure Alert (should fire first)

2. **Missing features in ml_feature_store_v2**
   - Feature pipeline failed
   - BigQuery table issue
   - Data quality problem

3. **Memory or resource constraints**
   - Model loaded but crashes on prediction
   - OOM errors
   - CPU/memory limits too low

4. **Model prediction errors**
   - Input data format changed
   - Model incompatible with current features
   - Coding bug in prediction logic

### Investigation Steps

#### 1. Check if Model Loading Alert Also Fired

```bash
# Check if model loading alert is also active
gcloud alpha monitoring policies list \
  --project=nba-props-platform \
  --filter="displayName:'Model Loading'" \
  --format="table(displayName,conditions[0].displayName,enabled)"
```

**If Model Loading Alert fired**: → Follow Model Loading Alert runbook first

#### 2. Check Fallback Rate and Affected Players

```bash
# Query recent fallback predictions
bq query --use_legacy_sql=false --project_id=nba-props-platform '
SELECT
  player_name,
  game_date,
  confidence_score,
  recommendation,
  created_at
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE system_id = "catboost_v8"
  AND confidence_score = 0.5
  AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
ORDER BY created_at DESC
LIMIT 20'

# Check fallback rate
bq query --use_legacy_sql=false --project_id=nba-props-platform '
SELECT
  COUNT(CASE WHEN confidence_score = 0.5 THEN 1 END) as fallback_count,
  COUNT(*) as total_predictions,
  ROUND(100.0 * COUNT(CASE WHEN confidence_score = 0.5 THEN 1 END) / COUNT(*), 2) as fallback_percent
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE system_id = "catboost_v8"
  AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)'
```

#### 3. Check Service Logs for Errors

```bash
# Check for fallback prediction warnings
gcloud logging read 'resource.labels.service_name="prediction-worker"
  AND textPayload=~"FALLBACK_PREDICTION"' \
  --project=nba-props-platform \
  --limit=20 \
  --format="table(timestamp,severity,textPayload)"
```

Look for patterns in the log messages:
- `"model not loaded"` → Model loading issue (Fix #1)
- `"missing features"` or `"no features"` → Feature data issue (Fix #2)
- `"Error"` or `"Exception"` → Model prediction error (Fix #4)
- `"OOM"` or `"memory"` → Resource constraints (Fix #3)

#### 4. Check Feature Availability

```bash
# Check if features exist for affected players
bq query --use_legacy_sql=false --project_id=nba-props-platform '
SELECT
  player_name,
  player_lookup,
  COUNT(*) as feature_count
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE()
GROUP BY player_name, player_lookup
ORDER BY feature_count DESC
LIMIT 10'
```

### Fixes

#### Fix #1: Model Loading Issue

→ **Follow Model Loading Failure Alert runbook**

#### Fix #2: Missing Features

```bash
# Check if Phase 2 feature pipeline ran
gcloud logging read 'resource.labels.service_name="nba-phase2-features"
  AND timestamp>="-1h"' \
  --project=nba-props-platform \
  --limit=10

# If pipeline didn't run, trigger manually
gcloud run jobs execute nba-phase2-features \
  --region=us-west2 \
  --project=nba-props-platform \
  --wait

# Verify features were created
bq query --use_legacy_sql=false --project_id=nba-props-platform '
SELECT
  COUNT(DISTINCT player_lookup) as players_with_features,
  MAX(created_at) as last_feature_created
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE()'
```

#### Fix #3: Resource Constraints

```bash
# Check current service configuration
gcloud run services describe prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --format="value(spec.template.spec.containers[0].resources.limits.memory)"

# If memory is too low, increase it
gcloud run services update prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --memory=4Gi \
  --cpu=2
```

#### Fix #4: Model Prediction Errors

```bash
# Check for specific error messages in logs
gcloud logging read 'resource.labels.service_name="prediction-worker"
  AND severity>=ERROR
  AND textPayload=~"predict"' \
  --project=nba-props-platform \
  --limit=10

# If error indicates code bug, rollback to previous revision
gcloud run services update-traffic prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --to-revisions=[PREVIOUS_REVISION]=100
```

### Verification

After applying fix:

```bash
# 1. Wait 10-15 minutes for new predictions

# 2. Check fallback rate dropped below 10%
bq query --use_legacy_sql=false --project_id=nba-props-platform '
SELECT
  ROUND(100.0 * COUNT(CASE WHEN confidence_score = 0.5 THEN 1 END) / COUNT(*), 2) as fallback_percent,
  COUNT(*) as total_predictions
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE system_id = "catboost_v8"
  AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 15 MINUTE)'

# Expected: < 10%

# 3. Check alert has cleared
gcloud alpha monitoring policies list \
  --project=nba-props-platform \
  --filter="displayName:'Fallback'" \
  --format="table(displayName,conditions[0].displayName,enabled)"
```

### Prevention

To prevent high fallback rates:

1. **Monitor feature pipeline health** - Ensure Phase 2 runs daily
2. **Test model changes** - Validate in dev before production
3. **Resource planning** - Size containers appropriately for model
4. **Model validation** - Test predictions during deployment

### Related Alerts

- **Model Loading Failure Alert** - Often fires before this alert
- **Phase 2 Feature Pipeline Failure** - Upstream cause of missing features

---

## Expected 500 Errors: FeatureValidationError

### Overview

Starting with Session 82 (2026-01-17), the prediction-worker includes **enhanced validation** that checks feature quality before generating predictions. When features fail validation, the service returns HTTP 500 to trigger Pub/Sub retry.

**This is expected and correct behavior** - not an incident.

### What You'll See

```
2026-01-17 20:57:59 - worker - ERROR - TRANSIENT failure for [player] on [date] -
returning 500 to trigger Pub/Sub retry. Reason: invalid_features, Error: FeatureValidationError
```

### Why This Happens

1. **Invalid or corrupt feature data** - Features don't pass validation rules
2. **Old game data** - Backfill or retry of historical games with outdated schemas
3. **Data quality issues** - Missing required features or malformed data

### Is This A Problem?

**No**, if:
- ✅ Errors are sporadic (< 10-20 per hour)
- ✅ Errors affect old games (dates in the past)
- ✅ Today's predictions are succeeding with ML confidence scores
- ✅ Pub/Sub is processing retries normally

**Yes**, investigate if:
- ❌ High volume (> 50 errors per hour sustained)
- ❌ Errors affect today's games
- ❌ No successful predictions for current games
- ❌ DLQ accumulating messages (see below)

### How to Check

```bash
# Count recent 500 errors
gcloud logging read 'resource.labels.service_name="prediction-worker"
  AND httpRequest.status=500
  AND timestamp>="'$(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S)'Z"' \
  --project=nba-props-platform \
  --format=json | jq '. | length'

# Check affected game dates
gcloud logging read 'resource.labels.service_name="prediction-worker"
  AND textPayload=~"FeatureValidationError"
  AND timestamp>="'$(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S)'Z"' \
  --project=nba-props-platform \
  --limit=10 \
  --format=json | jq -r '.[] | .textPayload' | grep -oP 'on \K\d{4}-\d{2}-\d{2}' | sort | uniq -c
```

### When to Act

1. **Monitor DLQ** - Check if messages are accumulating (see DLQ Monitoring section)
2. **Verify current game predictions** - Ensure today's games are predicting successfully
3. **Only escalate** if current predictions are failing

---

## DLQ (Dead Letter Queue) Monitoring

### Overview

Messages that fail prediction after maximum retries are sent to the Dead Letter Queue (DLQ):
- **Topic**: `prediction-request-dlq`
- **Subscription**: `prediction-request-dlq-sub`

### When to Check DLQ

1. **After seeing sustained 500 errors** (> 50/hour for > 2 hours)
2. **During validation checks** (daily health check)
3. **When current game predictions are missing**

### Check DLQ Status

```bash
# Check undelivered messages in DLQ
gcloud pubsub subscriptions describe prediction-request-dlq-sub \
  --project=nba-props-platform \
  --format=json | jq '{
    name: .name,
    undeliveredMessages: .numUndeliveredMessages,
    oldestMessageAge: .oldestUnackedMessageAge
  }'
```

### Interpret Results

**Healthy**:
```json
{
  "undeliveredMessages": null,  // or "0"
  "oldestMessageAge": null
}
```

**Needs Attention**:
```json
{
  "undeliveredMessages": "150",
  "oldestMessageAge": "3600s"  // 1 hour
}
```

### Investigate DLQ Messages

```bash
# Pull sample messages from DLQ (does not ACK them)
gcloud pubsub subscriptions pull prediction-request-dlq-sub \
  --project=nba-props-platform \
  --limit=5 \
  --format=json | jq -r '.[] | {
    player: .message.data | @base64d | fromjson | .player_lookup,
    game_date: .message.data | @base64d | fromjson | .game_date,
    publishTime: .message.publishTime
  }'
```

### Remediation

**If DLQ has old game data** (expected):
```bash
# These can be safely acknowledged/purged if they're historical backfills
# Only do this if you've confirmed they're old games that don't need predictions

gcloud pubsub subscriptions pull prediction-request-dlq-sub \
  --project=nba-props-platform \
  --auto-ack \
  --limit=100
```

**If DLQ has current game data** (problem):
1. Investigate why current games are failing validation
2. Check feature pipeline health (Phase 2)
3. Review recent code changes
4. Consider manual prediction generation if urgent

### Alert Recommendation

Consider adding a DLQ depth alert (Week 2+ priority):
- **Metric**: Pub/Sub subscription undelivered messages
- **Threshold**: > 50 messages for > 30 minutes
- **Severity**: WARNING
- **Action**: Investigate message content and root cause

---

## Environment Variable Change Alert

### Alert Details

- **Name**: `[WARNING] NBA Environment Variable Changes`
- **Severity**: WARNING
- **Metric**: `nba_env_var_changes` (log-based)
- **Threshold**: > 0 changes detected in 5-minute window (outside deployment grace period)
- **Service**: `prediction-worker`
- **Notification**: Slack (#platform-team or configured channel)
- **Check Frequency**: Every 5 minutes (via Cloud Scheduler)

### What This Alert Means

One or more critical environment variables changed unexpectedly **outside** a planned deployment window. This indicates:
- **Unplanned configuration change** - someone updated env vars manually
- **Accidental deletion** - critical variable removed (like CatBoost incident)
- **Deployment without grace period** - deployment done without calling `/internal/deployment-started`

**Critical Variables Monitored:**
- `XGBOOST_V1_MODEL_PATH`
- `CATBOOST_V8_MODEL_PATH` (most critical)
- `NBA_ACTIVE_SYSTEMS`
- `NBA_MIN_CONFIDENCE`
- `NBA_MIN_EDGE`

### How Monitoring Works

**Baseline Storage:**
- Current env var snapshot stored in GCS: `gs://nba-scraped-data/env-snapshots/nba-prediction-worker-env.json`
- SHA256 hash computed for quick change detection
- Baseline updated after alerts to prevent repeated notifications

**Deployment Grace Period:**
- 30-minute window after calling `/internal/deployment-started`
- Changes during this window are **expected** and **not alerted**
- Allows planned deployments without false alarms

**Change Detection:**
- Cloud Scheduler calls `/internal/check-env` every 5 minutes
- Compares current env vars to baseline
- If changed AND outside grace period → Alert fires
- Audit log written to BigQuery

### Common Causes

1. **Manual env var update without grace period**
   - Someone used `gcloud run services update --update-env-vars` directly
   - Fix: Always call `/internal/deployment-started` first

2. **Accidental deletion during deployment**
   - Deployment script didn't preserve existing env vars
   - Used `--set-env-vars` instead of `--update-env-vars`
   - Fix: See Fix #1

3. **Automated process changed env vars**
   - CI/CD pipeline or external tool modified service
   - Fix: Update automation to use grace period

4. **Service recreated without env vars**
   - Service deleted and recreated
   - Fix: Redeploy with correct env vars

### Investigation Steps

#### 1. Check Alert Details

```bash
# View recent env var change logs
gcloud logging read 'resource.labels.service_name="prediction-worker"
  AND jsonPayload.alert_type="ENV_VAR_CHANGE"
  AND severity="ERROR"' \
  --project=nba-props-platform \
  --limit=5 \
  --format=json | jq -r '.[] | {timestamp, changes: .jsonPayload.changes}'
```

**Look for:**
- Which variables changed (var_name)
- Change type (ADDED, REMOVED, MODIFIED)
- Old value vs new value

#### 2. Check Audit Trail in BigQuery

```sql
-- Get most recent change
SELECT
  timestamp,
  change_type,
  changed_vars,
  deployer,
  reason,
  in_deployment_window,
  alert_triggered
FROM `nba_orchestration.env_var_audit`
ORDER BY timestamp DESC
LIMIT 5;
```

**Identify:**
- When change occurred
- Who/what made the change (deployer)
- Whether it was during deployment window

#### 3. Verify Current Configuration

```bash
# Get current env vars
gcloud run services describe prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --format=json | jq -r '.spec.template.spec.containers[0].env[]'
```

**Check:**
- All 5 critical variables present
- Values are correct (especially CATBOOST_V8_MODEL_PATH)

#### 4. Check Recent Deployments

```bash
# List recent service revisions
gcloud run revisions list \
  --service=prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --limit=5 \
  --format="table(metadata.name,metadata.creationTimestamp,status.conditions[0].message)"
```

**Correlate:**
- Alert timestamp with deployment time
- If deployment just before alert → likely deployment without grace period

### Fixes

#### Fix #1: Restore Missing or Incorrect Env Var

If `CATBOOST_V8_MODEL_PATH` or other critical var is missing/wrong:

```bash
# Set correct value
gcloud run services update prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --update-env-vars CATBOOST_V8_MODEL_PATH="gs://nba-props-platform-models/catboost/v8/catboost_v8_33features_20260108_211817.cbm"
```

**Verify after update:**
```bash
# Check env var set correctly
gcloud run services describe prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --format=json | jq -r '.spec.template.spec.containers[0].env[] | select(.name=="CATBOOST_V8_MODEL_PATH")'
```

#### Fix #2: Update Baseline (If Change Was Intentional)

If the change was planned but grace period wasn't activated:

```bash
# Mark as deployment start (activates grace period)
curl -X POST https://prediction-worker-f7p3g7f6ya-wl.a.run.app/internal/deployment-started

# Make env var change
gcloud run services update prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --update-env-vars YOUR_VAR="new_value"
```

**Note:** This will update the baseline and prevent future alerts for this configuration.

#### Fix #3: Investigate Unauthorized Change

If change was NOT intentional:

1. Review BigQuery audit trail for deployer identity
2. Check IAM permissions on Cloud Run service
3. Review audit logs for who made the change
4. Revert to previous configuration
5. Implement additional access controls if needed

```bash
# Check who has permission to update service
gcloud run services get-iam-policy prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform
```

### Verification

After applying fix:

```bash
# 1. Trigger env check manually
curl -X POST https://prediction-worker-f7p3g7f6ya-wl.a.run.app/internal/check-env

# 2. Check response (should show OK or DEPLOYMENT_IN_PROGRESS)
# Expected: {"status": "OK", "changes": [], "message": "No changes detected"}

# 3. Verify baseline updated in GCS
gsutil cat gs://nba-scraped-data/env-snapshots/nba-prediction-worker-env.json | jq .

# 4. Check BigQuery audit log
bq query --use_legacy_sql=false --project_id=nba-props-platform \
  'SELECT * FROM `nba_orchestration.env_var_audit` ORDER BY timestamp DESC LIMIT 3'
```

### Prevention

**For Planned Deployments:**
Always use the grace period:

```bash
# 1. Activate grace period FIRST
curl -X POST https://prediction-worker-f7p3g7f6ya-wl.a.run.app/internal/deployment-started

# 2. Make changes within 30 minutes
gcloud run services update prediction-worker ... --update-env-vars ...

# 3. Changes detected but not alerted (expected)
```

**For Deployment Scripts:**
Update `deploy_prediction_worker.sh` to call `/internal/deployment-started`:

```bash
# Add before deployment
SERVICE_URL=$(gcloud run services describe prediction-worker --region=us-west2 --format='value(status.url)')
curl -X POST "${SERVICE_URL}/internal/deployment-started"

# Then deploy
gcloud run deploy ...
```

**For CI/CD Pipelines:**
Add pre-deployment step to activate grace period.

### Related Alerts

- **Model Loading Failure** - Often follows env var deletion
- **High Fallback Rate** - Symptoms of missing model path
- **Deep Health Check Failure** - Configuration check will fail

### Escalation

- **If intentional change:** No action needed after verification
- **If accidental:** Fix immediately (high priority)
- **If unauthorized:** Escalate to security team

---

## Deep Health Check Failure Alert

### Alert Details

- **Name**: `[WARNING] NBA Prediction Worker Health Check Failed`
- **Severity**: WARNING
- **Metric**: Cloud Monitoring Uptime Check
- **Threshold**: 2 consecutive failures (10-minute window)
- **Service**: `prediction-worker`
- **Endpoint**: `/health/deep`
- **Notification**: Slack (#platform-team or configured channel)

### What This Alert Means

The deep health check endpoint failed, meaning one or more dependency checks failed:
- **GCS Access Check** - Cannot read model files from GCS
- **BigQuery Access Check** - Cannot query predictions table
- **Model Loading Check** - Model paths invalid or files missing
- **Configuration Check** - Required environment variables missing

**vs Basic Health Check:**
- `/health` - Simple HTTP 200 (service is running)
- `/health/deep` - Validates all dependencies (service can actually work)

### Health Checks Performed

**1. GCS Access Check**
- Validates model file exists at `CATBOOST_V8_MODEL_PATH`
- Checks service account has `storage.objects.get` permission
- Returns file size and last modified timestamp

**2. BigQuery Access Check**
- Runs test query against `nba_predictions.player_prop_predictions`
- Verifies service account has BigQuery permissions
- Checks table exists and is accessible

**3. Model Loading Check**
- Validates `CATBOOST_V8_MODEL_PATH` is properly formatted
- Checks GCS path format (`gs://...`)
- Verifies file extension (`.cbm`)

**4. Configuration Check**
- Ensures `GCP_PROJECT_ID` is set
- Validates required env vars present
- Checks values are parseable

### Common Causes

1. **GCS Permission Issues**
   - Service account lacks storage permissions
   - Bucket access revoked

2. **Model File Missing**
   - File deleted from GCS
   - Path points to non-existent object

3. **BigQuery Permission Issues**
   - Service account lacks BigQuery permissions
   - Table doesn't exist or was deleted

4. **Environment Variable Missing**
   - Critical env var was removed
   - See "Environment Variable Change Alert"

### Investigation Steps

#### 1. Call Health Check Manually

```bash
# Get detailed health check response
curl https://prediction-worker-f7p3g7f6ya-wl.a.run.app/health/deep | jq .
```

**Example Failure Response:**
```json
{
  "status": "unhealthy",
  "checks_run": 4,
  "checks_passed": 2,
  "checks_failed": 2,
  "total_duration_ms": 431,
  "checks": [
    {
      "check": "gcs_access",
      "status": "fail",
      "error": "Permission denied",
      "duration_ms": 129
    },
    {
      "check": "bigquery_access",
      "status": "pass",
      "duration_ms": 98
    }
    // ...
  ]
}
```

**Identify:** Which check(s) failed

#### 2. Fix Based on Failed Check

**If gcs_access failed:**
- See "Model Loading Failure Alert" → Fix #2 (GCS Permissions)

**If bigquery_access failed:**
```bash
# Grant BigQuery permissions
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:prediction-worker@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/bigquery.dataEditor"
```

**If model_loading failed:**
- See "Model Loading Failure Alert" → Fix #1 or #3

**If configuration failed:**
- See "Environment Variable Change Alert" → Fix #1

### Verification

```bash
# Call health check again
curl https://prediction-worker-f7p3g7f6ya-wl.a.run.app/health/deep | jq .

# Should return:
# {
#   "status": "healthy",
#   "checks_passed": 4,
#   "checks_failed": 0
# }
```

### Prevention

- Monitor env var changes (prevents configuration issues)
- Use IAM policy version control
- Test health checks after deployments

---

## Stale Predictions Alert

### Alert Details

- **Name**: `[WARNING] NBA Stale Predictions`
- **Severity**: WARNING
- **Metric**: `nba_prediction_generation_success` (log-based, absence detection)
- **Threshold**: No successful predictions for > 2 hours
- **Service**: `prediction-worker`
- **Notification**: Slack (#platform-team or configured channel)

### What This Alert Means

No predictions have been generated for 2+ hours. This indicates:
- **Prediction orchestration has stopped** or is not triggering the worker
- **Cloud Run service may be down** or not receiving requests
- **Pub/Sub subscription may be failing** to deliver messages
- **No upcoming games** requiring predictions (normal during off-season)

### Normal vs. Abnormal Patterns

**Normal**:
- **Off-season periods**: No games = no predictions (expected)
- **Late night/early morning**: Games cluster in evenings, gaps are normal
- **All-Star break**: No games for several days

**Abnormal** (triggers alert):
- **During NBA season with scheduled games**: Should have predictions regularly
- **24 hours before game time**: Predictions should generate for upcoming games
- **After orchestrator should have run**: Expected prediction windows missed

### Common Causes

1. **Cloud Scheduler not triggering orchestrator**
   - Scheduler paused or disabled
   - Schedule misconfigured
   - Orchestrator service down

2. **Prediction-worker service down or scaled to zero**
   - Service crashed or failing health checks
   - No instances running
   - Cold start issues preventing execution

3. **Pub/Sub subscription issues**
   - Messages not being delivered
   - Subscription disabled or deleted
   - Message retention expired

4. **No upcoming games** (not actually a problem)
   - Off-season
   - All-Star break
   - No games scheduled

### Investigation Steps

#### 1. Check if Games Are Scheduled

```bash
# Check if there are upcoming games in the database
bq query --use_legacy_sql=false --project_id=nba-props-platform '
SELECT
  game_date,
  COUNT(*) as game_count
FROM `nba-props-platform.nba_source.nba_games`
WHERE game_date BETWEEN CURRENT_DATE() AND DATE_ADD(CURRENT_DATE(), INTERVAL 3 DAY)
  AND season_year >= 2025
GROUP BY game_date
ORDER BY game_date'
```

**If no games**: → This is expected, dismiss alert

#### 2. Check Recent Prediction Activity

```bash
# Check when last prediction was generated
bq query --use_legacy_sql=false --project_id=nba-props-platform '
SELECT
  MAX(created_at) as last_prediction,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(created_at), HOUR) as hours_ago,
  COUNT(*) as predictions_last_24h
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE system_id = "catboost_v8"
  AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)'
```

#### 3. Check Cloud Scheduler Status

```bash
# List prediction orchestrator jobs
gcloud scheduler jobs list --project=nba-props-platform --filter="name~prediction" --format="table(name,state,schedule,lastAttemptTime)"

# Check specific job status
gcloud scheduler jobs describe nba-prediction-orchestrator \
  --project=nba-props-platform \
  --location=us-west2 \
  --format=json | jq '{state: .state, lastAttemptTime: .lastAttemptTime, schedule: .schedule}'
```

**If scheduler is PAUSED**: → Re-enable it (Fix #1)

#### 4. Check Prediction-Worker Service

```bash
# Check service status
gcloud run services describe prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --format=json | jq '{
    status: .status.conditions[] | select(.type=="Ready") | .status,
    latestRevision: .status.latestReadyRevisionName,
    url: .status.url
  }'

# Check recent logs
gcloud logging read 'resource.labels.service_name="prediction-worker"
  AND timestamp>="-2h"' \
  --project=nba-props-platform \
  --limit=20 \
  --format="table(timestamp,severity,textPayload)"
```

**If service is not Ready**: → Check logs for errors (Fix #2)

#### 5. Check Pub/Sub Subscription

```bash
# Check subscription status
gcloud pubsub subscriptions describe prediction-request-sub \
  --project=nba-props-platform \
  --format=json | jq '{
    ackDeadline: .ackDeadlineSeconds,
    messageRetention: .messageRetentionDuration,
    pushConfig: .pushConfig.pushEndpoint,
    undeliveredMessages: .numUndeliveredMessages
  }'

# Check for delivery errors
gcloud logging read 'resource.type="pubsub_subscription"
  AND resource.labels.subscription_id="prediction-request-sub"
  AND severity>=ERROR' \
  --project=nba-props-platform \
  --limit=10
```

### Fixes

#### Fix #1: Re-enable Cloud Scheduler

```bash
# Resume paused scheduler job
gcloud scheduler jobs resume nba-prediction-orchestrator \
  --project=nba-props-platform \
  --location=us-west2

# Trigger manually to test
gcloud scheduler jobs run nba-prediction-orchestrator \
  --project=nba-props-platform \
  --location=us-west2
```

**Verification**:
```bash
# Wait 5 minutes and check for new predictions
gcloud logging read 'resource.labels.service_name="prediction-worker"
  AND textPayload=~"Prediction saved successfully"' \
  --project=nba-props-platform \
  --limit=5
```

#### Fix #2: Restart Prediction-Worker Service

```bash
# Update service to force new revision (triggers restart)
gcloud run services update prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --update-env-vars RESTART_TIME=$(date +%s)

# Wait for new revision to be ready
gcloud run revisions list --service=prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --limit=1
```

**Verification**:
```bash
# Check service is healthy
gcloud run services describe prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --format="value(status.conditions[0].status)"

# Should return: True
```

#### Fix #3: Fix Pub/Sub Subscription

```bash
# Check if subscription exists
gcloud pubsub subscriptions describe prediction-request-sub \
  --project=nba-props-platform

# If subscription is missing, recreate it
gcloud pubsub subscriptions create prediction-request-sub \
  --project=nba-props-platform \
  --topic=prediction-requests \
  --push-endpoint=https://prediction-worker-756957797294.us-west2.run.app/predict \
  --ack-deadline=600 \
  --message-retention-duration=7d \
  --dead-letter-topic=prediction-request-dlq \
  --max-delivery-attempts=5
```

### Verification

After applying fix:

```bash
# 1. Verify predictions are being generated
bq query --use_legacy_sql=false --project_id=nba-props-platform '
SELECT
  player_name,
  game_date,
  confidence_score,
  created_at
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE system_id = "catboost_v8"
  AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 MINUTE)
ORDER BY created_at DESC
LIMIT 10'

# Expected: Recent predictions within last 30 minutes

# 2. Check alert has cleared (will take 2+ hours if predictions resume)
gcloud alpha monitoring policies list \
  --project=nba-props-platform \
  --filter='displayName:"Stale Predictions"' \
  --format="table(displayName,enabled)"
```

### Prevention

To prevent stale predictions:

1. **Monitor scheduler health** - Ensure Cloud Scheduler jobs are enabled
2. **Set up orchestrator alerts** - Alert if orchestrator fails
3. **Test during off-season** - Don't disable alerts, just acknowledge during known gaps
4. **Document maintenance windows** - If pausing, document expected resume time

### Related Alerts

- **Prediction Worker Service Down** - May fire before this alert
- **Cloud Scheduler Failures** - Upstream cause

---

## High DLQ Depth Alert

### Alert Details

- **Name**: `[WARNING] NBA High DLQ Depth`
- **Severity**: WARNING
- **Metric**: `pubsub.googleapis.com/subscription/num_undelivered_messages`
- **Threshold**: > 50 messages for > 30 minutes
- **Resource**: `prediction-request-dlq-sub` Pub/Sub subscription
- **Notification**: Slack (#platform-team or configured channel)

### What This Alert Means

Messages are accumulating in the Dead Letter Queue (DLQ). This indicates:
- **Predictions are failing repeatedly** and exhausting retries
- **Persistent issues** with specific players or games
- **Data quality problems** preventing successful predictions
- **Feature validation failures** for multiple predictions

### Normal vs. Abnormal DLQ Depth

**Normal**:
- **0-10 messages**: A few edge cases or old game retries (expected)
- **Sporadic additions**: Occasional feature validation failures for old games
- **Self-clearing**: Messages that eventually succeed on retry

**Abnormal** (triggers alert):
- **> 50 messages sustained**: Systemic issue affecting many predictions
- **Rapid accumulation**: Many failures in short time
- **Current game dates**: Today's games failing validation

### Common Causes

1. **Feature validation failures for old games**
   - Historical data backfill with outdated schemas
   - Old games being retried repeatedly
   - Expected for games older than current season

2. **Missing features for current games**
   - Phase 2 feature pipeline failed
   - ml_feature_store_v2 not updated
   - Data quality issues

3. **Model prediction errors**
   - Model incompatible with feature format
   - Memory issues causing crashes
   - Code bugs in prediction logic

4. **Service configuration issues**
   - Environment variables missing
   - Model not loading correctly
   - Database connection failures

### Investigation Steps

#### 1. Check DLQ Message Count

```bash
# Get current DLQ depth
gcloud pubsub subscriptions describe prediction-request-dlq-sub \
  --project=nba-props-platform \
  --format=json | jq '{
    undeliveredMessages: .numUndeliveredMessages,
    oldestMessageAge: .oldestUnackedMessageAge
  }'
```

#### 2. Sample DLQ Messages to Identify Pattern

```bash
# Pull sample messages (does NOT acknowledge them)
gcloud pubsub subscriptions pull prediction-request-dlq-sub \
  --project=nba-props-platform \
  --limit=10 \
  --format=json | jq -r '.[] | {
    player: (.message.data | @base64d | fromjson | .player_lookup),
    game_date: (.message.data | @base64d | fromjson | .game_date),
    publishTime: .message.publishTime,
    deliveryAttempts: .deliveryAttempt
  }'
```

Look for patterns:
- **All old game dates** (e.g., 2024-XX-XX): → Historical data issue (Fix #1)
- **Current game dates** (today or future): → Active problem (Fix #2)
- **Same players repeatedly**: → Player-specific feature issue
- **Many different players**: → Systemic feature or model issue

#### 3. Check Recent Prediction Errors

```bash
# Check for FeatureValidationError logs
gcloud logging read 'resource.labels.service_name="prediction-worker"
  AND textPayload=~"FeatureValidationError"
  AND timestamp>="-2h"' \
  --project=nba-props-platform \
  --limit=20 \
  --format=json | jq -r '.[] | .textPayload' | grep -oP 'on \K\d{4}-\d{2}-\d{2}' | sort | uniq -c

# Check for other prediction failures
gcloud logging read 'resource.labels.service_name="prediction-worker"
  AND severity>=ERROR
  AND timestamp>="-2h"' \
  --project=nba-props-platform \
  --limit=20 \
  --format="table(timestamp,textPayload)"
```

#### 4. Verify Current Game Predictions Are Succeeding

```bash
# Check recent successful predictions
bq query --use_legacy_sql=false --project_id=nba-props-platform '
SELECT
  game_date,
  COUNT(*) as predictions,
  COUNT(DISTINCT player_lookup) as unique_players,
  ROUND(AVG(confidence_score) * 100, 1) as avg_confidence
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE system_id = "catboost_v8"
  AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
  AND game_date >= CURRENT_DATE()
GROUP BY game_date
ORDER BY game_date'
```

**If current games are predicting successfully**: → DLQ contains old game data (Fix #1)
**If no recent predictions for current games**: → Active issue (Fix #2)

### Fixes

#### Fix #1: Purge Old Game Messages from DLQ

If DLQ contains only old game dates (e.g., games from previous seasons):

```bash
# IMPORTANT: Only do this after confirming messages are for OLD games
# First, verify message dates
gcloud pubsub subscriptions pull prediction-request-dlq-sub \
  --project=nba-props-platform \
  --limit=20 \
  --format=json | jq -r '.[] | (.message.data | @base64d | fromjson | .game_date)' | sort | uniq -c

# If all dates are old (before current season), purge with auto-ack
# This will acknowledge and remove messages
gcloud pubsub subscriptions pull prediction-request-dlq-sub \
  --project=nba-props-platform \
  --auto-ack \
  --limit=500

# Repeat until DLQ is empty or only recent messages remain
```

**Verification**:
```bash
# Check DLQ is now empty or reduced
gcloud pubsub subscriptions describe prediction-request-dlq-sub \
  --project=nba-props-platform \
  --format="value(numUndeliveredMessages)"

# Should be 0 or low number
```

#### Fix #2: Investigate Current Game Failures

If DLQ contains current game dates:

```bash
# 1. Check if Phase 2 feature pipeline ran today
bq query --use_legacy_sql=false --project_id=nba-props-platform '
SELECT
  MAX(created_at) as last_feature_created,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(created_at), HOUR) as hours_ago,
  COUNT(DISTINCT player_lookup) as players_with_features
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date >= CURRENT_DATE()'

# 2. If features are stale (> 4 hours old), trigger Phase 2 manually
gcloud run jobs execute nba-phase2-features \
  --region=us-west2 \
  --project=nba-props-platform \
  --wait

# 3. After Phase 2 completes, retry DLQ messages
# Pull and re-publish to main topic (they'll be retried)
# Note: This is manual - consider creating a retry script
```

#### Fix #3: Check Model and Service Health

If failures persist after feature refresh:

```bash
# Follow Model Loading Failure Alert runbook
# Specifically:
# 1. Check CATBOOST_V8_MODEL_PATH is set
# 2. Check model loading logs
# 3. Check service has adequate resources
```

### Verification

After applying fix:

```bash
# 1. Verify DLQ depth is decreasing
watch -n 30 'gcloud pubsub subscriptions describe prediction-request-dlq-sub \
  --project=nba-props-platform \
  --format="value(numUndeliveredMessages)"'

# 2. Verify current game predictions are succeeding
bq query --use_legacy_sql=false --project_id=nba-props-platform '
SELECT
  COUNT(*) as recent_predictions,
  MIN(created_at) as earliest,
  MAX(created_at) as latest
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE system_id = "catboost_v8"
  AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)'

# Expected: Recent predictions flowing

# 3. Check alert status (will clear after 30 minutes if DLQ < 50)
gcloud alpha monitoring policies list \
  --project=nba-props-platform \
  --filter='displayName:"DLQ"' \
  --format="table(displayName,enabled)"
```

### Prevention

To prevent DLQ accumulation:

1. **Monitor feature pipeline** - Ensure Phase 2 runs daily before prediction window
2. **Implement DLQ monitoring dashboard** - Track message age and content
3. **Set up automated cleanup** - Purge messages older than 30 days automatically
4. **Improve validation** - Make feature validation more lenient for edge cases

### Related Alerts

- **Expected 500 Errors: FeatureValidationError** - Related to validation failures
- **Feature Pipeline Staleness** - Upstream cause of missing features
- **Model Loading Failure** - Can cause all predictions to fail

---

## Feature Pipeline Staleness Check

### Alert Details

- **Name**: `[WARNING] NBA Feature Pipeline Stale`
- **Severity**: WARNING
- **Alert Policy ID**: `16018926837468712704`
- **Metric**: `nba_feature_pipeline_stale` (log-based)
- **Threshold**: ml_feature_store_v2 not updated for > 4 hours (for current/upcoming games)
- **Monitoring Script**: `bin/alerts/monitor_feature_staleness.sh`
- **Notification**: Slack (#platform-team)
- **Status**: ✅ Automated (Week 2.5 - Session 83)

### How This Alert Works

**Monitoring Script**: `bin/alerts/monitor_feature_staleness.sh`
- Runs BigQuery query to check feature freshness
- Writes structured log to Cloud Logging if features are stale
- Log-based metric `nba_feature_pipeline_stale` increments
- Alert fires if metric > 0 for 10+ minutes

**Current Status**: Alert is active. Monitoring script can be run:
- Manually: `./bin/alerts/monitor_feature_staleness.sh`
- Via Cloud Scheduler (optional): See `MONITORING-AUTOMATION-SETUP.md`

### What This Alert Detects

The Phase 2 feature pipeline has not run successfully in 4+ hours. This means:
- **ml_feature_store_v2 table** contains stale features
- **New predictions** may use outdated player/team statistics
- **Feature quality** may be degraded
- **Upstream data pipeline** (Phase 1) may have failed

### Why This Matters

Fresh features are critical for prediction quality:
- **Player statistics** change after each game
- **Team performance** metrics update daily
- **Matchup data** needs latest opponent stats
- **Injury status** affects availability and performance

### How to Perform This Check

#### Check Feature Freshness

```bash
# Check when features were last created for current/upcoming games
bq query --use_legacy_sql=false --project_id=nba-props-platform '
SELECT
  MAX(created_at) as last_feature_update,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(created_at), HOUR) as hours_ago,
  COUNT(DISTINCT player_lookup) as players_with_features,
  MIN(game_date) as earliest_game,
  MAX(game_date) as latest_game
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date >= CURRENT_DATE()'
```

**Interpret Results**:
- `hours_ago < 4`: ✅ Features are fresh
- `hours_ago >= 4 AND hours_ago < 12`: ⚠️ Features getting stale, investigate
- `hours_ago >= 12`: ❌ Features very stale, immediate action needed
- `players_with_features = 0`: ❌ Critical - no features for upcoming games

### Investigation Steps

#### 1. Check Phase 2 Job Execution History

```bash
# List recent Phase 2 job executions
gcloud run jobs executions list \
  --job=nba-phase2-features \
  --region=us-west2 \
  --project=nba-props-platform \
  --limit=10 \
  --format="table(name,status.conditions[0].type,status.completionTime)"
```

**Look for**:
- Recent successful completion
- Failed executions
- No recent executions at all

#### 2. Check Phase 2 Job Logs

```bash
# Check recent logs for errors
gcloud logging read 'resource.type="cloud_run_job"
  AND resource.labels.job_name="nba-phase2-features"
  AND timestamp>="-24h"' \
  --project=nba-props-platform \
  --limit=50 \
  --format="table(timestamp,severity,textPayload)"
```

#### 3. Check Cloud Scheduler for Phase 2

```bash
# Check if Phase 2 scheduler is enabled
gcloud scheduler jobs list \
  --project=nba-props-platform \
  --filter="name~phase2" \
  --format="table(name,state,schedule,lastAttemptTime)"
```

### Remediation

#### Fix: Manually Trigger Phase 2 Feature Pipeline

```bash
# Trigger Phase 2 job manually
gcloud run jobs execute nba-phase2-features \
  --region=us-west2 \
  --project=nba-props-platform \
  --wait

# Monitor execution
gcloud run jobs executions list \
  --job=nba-phase2-features \
  --region=us-west2 \
  --project=nba-props-platform \
  --limit=1 \
  --format="table(name,status.conditions[0].type,status.completionTime)"
```

**Verification**:
```bash
# Re-run feature freshness check (should now show recent update)
bq query --use_legacy_sql=false --project_id=nba-props-platform '
SELECT
  MAX(created_at) as last_feature_update,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(created_at), MINUTE) as minutes_ago,
  COUNT(DISTINCT player_lookup) as players_with_features
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date >= CURRENT_DATE()'

# Expected: minutes_ago < 15
```

### When to Perform This Check

1. **Daily health check** - Part of morning operations routine
2. **Before prediction window** - Ensure features are fresh before predictions generate
3. **When DLQ depth alert fires** - Stale features can cause validation failures
4. **After Phase 1 pipeline runs** - Verify Phase 2 processes new data
5. **When investigating prediction anomalies** - Stale features affect quality

### Alert Automation

**Current Implementation**:
- ✅ Monitoring script: `bin/alerts/monitor_feature_staleness.sh`
- ✅ Log-based metric: `nba_feature_pipeline_stale`
- ✅ Alert policy: Active and notifying to Slack
- ⏳ Cloud Scheduler: Optional (see MONITORING-AUTOMATION-SETUP.md)

**To fully automate**: Set up Cloud Scheduler to run monitoring script hourly (see `docs/08-projects/current/nba-alerting-visibility/MONITORING-AUTOMATION-SETUP.md`)

---

## Confidence Distribution Drift Check

### Alert Details

- **Name**: `[WARNING] NBA Confidence Distribution Drift`
- **Severity**: WARNING
- **Alert Policy ID**: `5839862583446976986`
- **Metric**: `nba_confidence_drift` (log-based)
- **Threshold**: > 30% of predictions outside normal range (75-95%) in 2-hour window
- **Monitoring Script**: `bin/alerts/monitor_confidence_drift.sh`
- **Notification**: Slack (#platform-team)
- **Status**: ✅ Automated (Week 2.5 - Session 83)

### How This Alert Works

**Monitoring Script**: `bin/alerts/monitor_confidence_drift.sh`
- Runs BigQuery query to analyze confidence distribution in last 2 hours
- Writes structured log to Cloud Logging if drift exceeds threshold
- Log-based metric `nba_confidence_drift` increments
- Alert fires if metric > 0 for 20+ minutes

**Current Status**: Alert is active. Monitoring script can be run:
- Manually: `./bin/alerts/monitor_confidence_drift.sh`
- Via Cloud Scheduler (optional): See `MONITORING-AUTOMATION-SETUP.md`

### What This Alert Detects

Unusual patterns in prediction confidence scores. This can indicate:
- **Model corruption** or incorrect model version loaded
- **Feature quality issues** affecting confidence calculations
- **Code bugs** in prediction logic
- **Data drift** - feature distributions changed significantly
- **Fallback mode** - model not loading, using weighted averages

### Normal Confidence Distribution

**CatBoost V8 Expected Patterns**:
- **Range**: 79% - 95% for most predictions
- **Mean**: ~87%
- **Distribution**: Bell curve centered around 85-88%
- **Outliers**: < 5% of predictions outside 75-95% range

**Abnormal Patterns**:
- **All 50%**: Model not loaded, all fallback predictions (CRITICAL)
- **Very narrow range**: All predictions clustered (e.g., all 83-85%)
- **Bimodal**: Two distinct clusters (suggests two different prediction modes)
- **Outside expected range**: Many predictions < 75% or > 95%

### How to Perform This Check

#### Check Confidence Distribution

```bash
# Get confidence distribution for recent predictions
bq query --use_legacy_sql=false --project_id=nba-props-platform '
WITH recent_predictions AS (
  SELECT
    ROUND(confidence_score * 100) as confidence_pct,
    COUNT(*) as prediction_count
  FROM `nba-props-platform.nba_predictions.player_prop_predictions`
  WHERE system_id = "catboost_v8"
    AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
  GROUP BY confidence_pct
),
stats AS (
  SELECT
    COUNT(*) as total_predictions,
    ROUND(AVG(confidence_score) * 100, 1) as avg_confidence,
    ROUND(MIN(confidence_score) * 100, 1) as min_confidence,
    ROUND(MAX(confidence_score) * 100, 1) as max_confidence,
    COUNTIF(confidence_score < 0.75 OR confidence_score > 0.95) as outside_normal_range,
    ROUND(100.0 * COUNTIF(confidence_score < 0.75 OR confidence_score > 0.95) / COUNT(*), 1) as drift_pct,
    COUNTIF(confidence_score = 0.50) as fallback_count
  FROM `nba-props-platform.nba_predictions.player_prop_predictions`
  WHERE system_id = "catboost_v8"
    AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
)
SELECT
  "=== Summary Statistics ===" as section,
  total_predictions,
  avg_confidence,
  min_confidence,
  max_confidence,
  outside_normal_range,
  drift_pct,
  fallback_count,
  CASE
    WHEN fallback_count = total_predictions THEN "❌ CRITICAL: All fallback predictions"
    WHEN drift_pct > 30 THEN "⚠️ WARNING: High drift detected"
    WHEN drift_pct > 15 THEN "⚠️ CAUTION: Moderate drift"
    ELSE "✅ OK: Normal distribution"
  END as status
FROM stats
UNION ALL
SELECT
  "=== Distribution ===" as section,
  NULL, confidence_pct, prediction_count, NULL, NULL, NULL, NULL, NULL
FROM recent_predictions
ORDER BY section DESC, confidence_pct DESC'
```

**Interpret Results**:
- `drift_pct < 15%`: ✅ Normal
- `drift_pct 15-30%`: ⚠️ Moderate drift, investigate
- `drift_pct > 30%`: ❌ High drift, immediate action
- `fallback_count > 0`: Check if model loaded correctly

#### Visualize Distribution (Optional)

```bash
# Simple histogram of confidence scores
bq query --use_legacy_sql=false --project_id=nba-props-platform '
SELECT
  ROUND(confidence_score * 100) as confidence,
  COUNT(*) as count,
  REPEAT("█", CAST(COUNT(*) / 2 AS INT64)) as histogram
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE system_id = "catboost_v8"
  AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
GROUP BY confidence
ORDER BY confidence DESC'
```

### Investigation Steps

#### 1. Compare to Historical Baseline

```bash
# Compare current hour to previous day
bq query --use_legacy_sql=false --project_id=nba-props-platform '
WITH current_hour AS (
  SELECT
    "Current Hour" as period,
    ROUND(AVG(confidence_score) * 100, 1) as avg_confidence,
    ROUND(STDDEV(confidence_score) * 100, 1) as stddev_confidence,
    ROUND(100.0 * COUNTIF(confidence_score < 0.75 OR confidence_score > 0.95) / COUNT(*), 1) as drift_pct
  FROM `nba-props-platform.nba_predictions.player_prop_predictions`
  WHERE system_id = "catboost_v8"
    AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
),
previous_day AS (
  SELECT
    "Previous 24h" as period,
    ROUND(AVG(confidence_score) * 100, 1) as avg_confidence,
    ROUND(STDDEV(confidence_score) * 100, 1) as stddev_confidence,
    ROUND(100.0 * COUNTIF(confidence_score < 0.75 OR confidence_score > 0.95) / COUNT(*), 1) as drift_pct
  FROM `nba-props-platform.nba_predictions.player_prop_predictions`
  WHERE system_id = "catboost_v8"
    AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 25 HOUR)
    AND created_at < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
)
SELECT * FROM current_hour
UNION ALL
SELECT * FROM previous_day
ORDER BY period DESC'
```

**If significant deviation from baseline**: → Investigate model or feature changes

#### 2. Check Model Loading Status

```bash
# Verify model loaded correctly at startup
gcloud logging read 'resource.labels.service_name="prediction-worker"
  AND (textPayload=~"CATBOOST_V8_MODEL_PATH" OR textPayload=~"model loaded")' \
  --project=nba-props-platform \
  --limit=10 \
  --format="table(timestamp,textPayload)"
```

**If model not loaded or error**: → Follow Model Loading Failure Alert runbook

#### 3. Check Feature Quality

```bash
# Check if feature pipeline ran recently
bq query --use_legacy_sql=false --project_id=nba-props-platform '
SELECT
  MAX(created_at) as last_feature_update,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(created_at), HOUR) as hours_ago
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date >= CURRENT_DATE()'
```

**If features are stale**: → Follow Feature Pipeline Staleness Check

### Remediation

#### Fix #1: All Predictions at 50% (Fallback Mode)

```bash
# This indicates model not loaded - follow Model Loading Failure Alert runbook
# Quick check:
gcloud run services describe prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --format=json | jq -r '.spec.template.spec.containers[0].env[] | select(.name=="CATBOOST_V8_MODEL_PATH") | .value'

# If missing, restore it:
LATEST_MODEL=$(gsutil ls gs://nba-props-platform-models/catboost/v8/ | grep 'catboost_v8_33features' | sort | tail -1)
gcloud run services update prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --update-env-vars CATBOOST_V8_MODEL_PATH="$LATEST_MODEL"
```

#### Fix #2: Unusual Distribution (Not Fallback)

```bash
# If distribution is unusual but not all 50%:
# 1. Check recent code deployments
gcloud run revisions list --service=prediction-worker \
  --region=us-west2 \
  --project=nba-props-platform \
  --limit=5 \
  --format="table(name,creationTimestamp,trafficPercent)"

# 2. Consider rolling back if recent deployment correlates with drift
# gcloud run services update-traffic prediction-worker \
#   --region=us-west2 \
#   --project=nba-props-platform \
#   --to-revisions=[PREVIOUS_REVISION]=100

# 3. Check if this is expected due to game context
# (e.g., playoff games, star player injuries, unusual matchups)
```

### Verification

```bash
# Re-run distribution check after fix
# Wait 15-30 minutes for new predictions to generate
bq query --use_legacy_sql=false --project_id=nba-props-platform '
SELECT
  ROUND(AVG(confidence_score) * 100, 1) as avg_confidence,
  ROUND(MIN(confidence_score) * 100, 1) as min_confidence,
  ROUND(MAX(confidence_score) * 100, 1) as max_confidence,
  ROUND(100.0 * COUNTIF(confidence_score < 0.75 OR confidence_score > 0.95) / COUNT(*), 1) as drift_pct,
  COUNT(*) as prediction_count
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE system_id = "catboost_v8"
  AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 MINUTE)'

# Expected: drift_pct < 15%, avg_confidence ~87%
```

### When to Perform This Check

1. **Weekly quality review** - Part of weekly health check
2. **After model updates** - Verify new model produces expected distribution
3. **When DLQ depth increases** - Distribution drift can cause validation failures
4. **User reports prediction quality issues** - Verify confidence scores are reasonable
5. **After significant code changes** - Ensure prediction logic still correct

### Alert Automation

**Current Implementation**:
- ✅ Monitoring script: `bin/alerts/monitor_confidence_drift.sh`
- ✅ Log-based metric: `nba_confidence_drift`
- ✅ Alert policy: Active and notifying to Slack
- ⏳ Cloud Scheduler: Optional (see MONITORING-AUTOMATION-SETUP.md)

**To fully automate**: Set up Cloud Scheduler to run monitoring script every 2 hours (see `docs/08-projects/current/nba-alerting-visibility/MONITORING-AUTOMATION-SETUP.md`)

---

## Environment Variable Change Alert

### Alert Details

- **Name**: `[WARNING] NBA Environment Variable Changes`
- **Severity**: WARNING
- **Metric**: `nba_env_var_changes`
- **Threshold**: > 0 changes detected outside deployment window
- **Service**: `prediction-worker`
- **Notification**: Slack (#platform-team or configured channel)
- **Auto-close**: 1 hour

### What This Alert Means

One or more critical environment variables changed unexpectedly outside of a planned deployment window.

**Monitored Variables**:
- `XGBOOST_V1_MODEL_PATH`
- `CATBOOST_V8_MODEL_PATH`
- `NBA_ACTIVE_SYSTEMS`
- `NBA_MIN_CONFIDENCE`
- `NBA_MIN_EDGE`

**Why This Matters**:
- The CatBoost incident (Jan 14-17, 2026) was caused by accidental deletion of `CATBOOST_V8_MODEL_PATH`
- Environment variable changes can silently degrade service quality
- Early detection prevents 3-day undetected outages

### Investigation Steps

#### 1. Check the Alert Log for Changes

```bash
# View recent environment change logs
gcloud logging read 'resource.labels.service_name="prediction-worker"
  AND jsonPayload.alert_type="ENV_VAR_CHANGE"
  AND severity="ERROR"' \
  --project=nba-props-platform \
  --limit=5 \
  --format=json | jq -r '.[] | .jsonPayload.changes'

# Expected output shows which variables changed:
# [
#   {
#     "var_name": "CATBOOST_V8_MODEL_PATH",
#     "change_type": "REMOVED",
#     "old_value": "gs://...",
#     "new_value": null
#   }
# ]
```

#### 2. Verify Current Environment Variables

```bash
# View current env vars
gcloud run services describe prediction-worker \
  --region=us-central1 \
  --project=nba-props-platform \
  --format=json | jq -r '.spec.template.spec.containers[0].env[] | select(.name | IN("XGBOOST_V1_MODEL_PATH", "CATBOOST_V8_MODEL_PATH", "NBA_ACTIVE_SYSTEMS", "NBA_MIN_CONFIDENCE", "NBA_MIN_EDGE")) | "\(.name)=\(.value)"'
```

#### 3. Check Recent Deployments

```bash
# Check recent revisions
gcloud run revisions list \
  --service=prediction-worker \
  --region=us-central1 \
  --project=nba-props-platform \
  --limit=5 \
  --format="table(metadata.name,status.conditions[0].lastTransitionTime,metadata.annotations.run.googleapis.com/client-version)"

# Look for deployments around the time of the alert
```

#### 4. Verify Predictions Are Working

```bash
# Check for recent fallback predictions (indicates CatBoost model issue)
gcloud logging read 'resource.labels.service_name="prediction-worker"
  AND textPayload=~"FALLBACK_PREDICTION"' \
  --project=nba-props-platform \
  --limit=5

# If you see fallback logs → model loading is broken
# If no fallback logs → change may not have broken predictions
```

### Common Scenarios

#### Scenario 1: Planned Deployment (False Alarm)

**Cause**: Deployment happened but `/internal/deployment-started` was not called.

**Symptoms**:
- Alert fired during or after deployment
- Changes are intentional (e.g., updated model path)
- Predictions are working correctly

**Fix**: No action needed. Baseline was automatically updated.

**Prevention**: Call `/internal/deployment-started` BEFORE deploying:
```bash
curl -X POST https://prediction-worker-<SERVICE_ID>-uc.a.run.app/internal/deployment-started \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"
```

#### Scenario 2: Accidental Variable Deletion

**Cause**: Deployment script used `--set-env-vars` instead of `--update-env-vars`.

**Symptoms**:
- `CATBOOST_V8_MODEL_PATH` changed from valid path to null
- Fallback predictions with 50% confidence
- Model loading failure logs

**Fix**: Restore the missing variable

#### Scenario 3: Unauthorized Configuration Change

**Cause**: Manual change via console or script without authorization.

**Symptoms**:
- Unexpected change outside deployment
- No recent deployments in revision history

**Fix**: Investigate who made the change and revert if unauthorized

### Fixes

#### Fix #1: Restore Missing Environment Variable

```bash
# Get the old value from alert log
OLD_VALUE=$(gcloud logging read 'resource.labels.service_name="prediction-worker"
  AND jsonPayload.alert_type="ENV_VAR_CHANGE"' \
  --project=nba-props-platform \
  --limit=1 \
  --format=json | jq -r '.[0].jsonPayload.changes[0].old_value')

echo "Old value was: $OLD_VALUE"

# Restore the variable
gcloud run services update prediction-worker \
  --region=us-central1 \
  --project=nba-props-platform \
  --update-env-vars CATBOOST_V8_MODEL_PATH="$OLD_VALUE"
```

**Verification**:
```bash
# Check env var is restored
gcloud run services describe prediction-worker \
  --region=us-central1 \
  --project=nba-props-platform \
  --format=json | jq -r '.spec.template.spec.containers[0].env[] | select(.name=="CATBOOST_V8_MODEL_PATH") | .value'

# Wait 2 minutes and verify no fallback predictions
gcloud logging read 'resource.labels.service_name="prediction-worker"
  AND textPayload=~"FALLBACK_PREDICTION"' \
  --project=nba-props-platform \
  --limit=1

# Should return no results
```

#### Fix #2: Update Deployment Script

If the issue was caused by deployment script:

```bash
# Update deployment script to preserve env vars
cd bin/predictions/deploy
vi deploy_prediction_worker.sh

# Ensure script uses --update-env-vars, not --set-env-vars
# See: docs/04-deployment/DEPLOYMENT-SCRIPT-FIX.md
```

### Prevention

1. **Always call /internal/deployment-started BEFORE deploying**
   ```bash
   # Add to deployment script
   curl -X POST $SERVICE_URL/internal/deployment-started \
     -H "Authorization: Bearer $(gcloud auth print-identity-token)"
   sleep 5  # Wait for grace period to activate
   ```

2. **Use --update-env-vars instead of --set-env-vars**
   ```bash
   # Good: Updates specific vars, preserves others
   gcloud run deploy --update-env-vars KEY=VALUE

   # Bad: Replaces ALL vars, loses others
   gcloud run deploy --set-env-vars KEY=VALUE
   ```

3. **Review env vars before deploying**
   ```bash
   # Check what will be deployed
   gcloud run services describe prediction-worker --format=json | \
     jq '.spec.template.spec.containers[0].env'
   ```

---

## Deep Health Check Failure Alert

### Alert Details

- **Name**: `[WARNING] NBA Prediction Worker Health Check Failed`
- **Severity**: WARNING
- **Check**: Cloud Monitoring Uptime Check on `/health/deep`
- **Threshold**: 2 consecutive failures (10 minute detection window)
- **Service**: `prediction-worker`
- **Notification**: Slack (#platform-team or configured channel)
- **Auto-close**: 30 minutes after passing

### What This Alert Means

The deep health check endpoint failed to validate one or more critical dependencies.

**Dependencies Checked**:
1. **GCS Access**: Can read model files from buckets
2. **BigQuery Access**: Can query `nba_predictions` tables
3. **Model Loading**: CatBoost V8 model is accessible
4. **Configuration**: All required environment variables are set

**Why This Matters**:
- Early warning of infrastructure issues before they cause prediction failures
- Validates entire prediction pipeline, not just HTTP 200
- Helps distinguish service-up-but-broken from service-down

### Investigation Steps

#### 1. Call Health Endpoint Directly

```bash
# Get service URL
SERVICE_URL=$(gcloud run services describe prediction-worker \
  --region=us-central1 \
  --project=nba-props-platform \
  --format='value(status.url)')

# Call health endpoint
curl -s "${SERVICE_URL}/health/deep" | jq .

# Expected output:
# {
#   "status": "healthy",
#   "checks": [
#     {"check": "gcs_access", "status": "pass", "duration_ms": 123},
#     {"check": "bigquery_access", "status": "pass", "duration_ms": 234},
#     {"check": "model_loading", "status": "pass", "duration_ms": 45},
#     {"check": "configuration", "status": "pass", "duration_ms": 12}
#   ],
#   "total_duration_ms": 414,
#   "checks_passed": 4,
#   "checks_failed": 0
# }

# If status is "unhealthy", look for which check failed
```

#### 2. Identify Failed Check

```bash
# View recent health check logs
gcloud logging read 'resource.labels.service_name="prediction-worker"
  AND textPayload=~"health check"' \
  --project=nba-props-platform \
  --limit=10
```

#### 3. Check Service Status

```bash
# Verify service is running
gcloud run services describe prediction-worker \
  --region=us-central1 \
  --project=nba-props-platform \
  --format="value(status.conditions[0].status,status.conditions[0].message)"

# Should return: True
```

### Common Failures and Fixes

#### Failure: GCS Access

**Symptoms**:
```json
{
  "check": "gcs_access",
  "status": "fail",
  "error": "403 Forbidden" or "Model file not found"
}
```

**Causes**:
- Service account lacks permissions
- Model file deleted or moved
- GCS bucket access restricted

**Fix #1: Grant GCS Permissions**
```bash
# Grant storage.objects.get permission
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:prediction-worker@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"
```

**Fix #2: Verify Model File Exists**
```bash
# Get model path
MODEL_PATH=$(gcloud run services describe prediction-worker \
  --region=us-central1 \
  --project=nba-props-platform \
  --format=json | jq -r '.spec.template.spec.containers[0].env[] | select(.name=="CATBOOST_V8_MODEL_PATH") | .value')

# Check if file exists
gsutil ls "$MODEL_PATH"

# If not found, update to correct path
```

#### Failure: BigQuery Access

**Symptoms**:
```json
{
  "check": "bigquery_access",
  "status": "fail",
  "error": "403 Permission denied" or "Table not found"
}
```

**Causes**:
- Service account lacks BigQuery permissions
- Table doesn't exist
- BigQuery quota exceeded

**Fix: Grant BigQuery Permissions**
```bash
# Grant BigQuery data viewer permission
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:prediction-worker@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/bigquery.dataViewer"

# Grant BigQuery job user permission (for queries)
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:prediction-worker@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/bigquery.jobUser"
```

#### Failure: Model Loading

**Symptoms**:
```json
{
  "check": "model_loading",
  "status": "fail",
  "error": "Invalid model path format" or "Local model file not found"
}
```

**Causes**:
- `CATBOOST_V8_MODEL_PATH` not set or invalid
- Model file format incorrect
- No local models in development

**Fix: Set Model Path**
```bash
# Update to correct model path
gcloud run services update prediction-worker \
  --region=us-central1 \
  --project=nba-props-platform \
  --update-env-vars CATBOOST_V8_MODEL_PATH="gs://nba-props-platform-models/catboost/v8/catboost_v8_33features_YYYYMMDD_HHMMSS.cbm"
```

#### Failure: Configuration

**Symptoms**:
```json
{
  "check": "configuration",
  "status": "fail",
  "details": {
    "GCP_PROJECT_ID": {"status": "fail", "set": false, "error": "Required env var not set"}
  }
}
```

**Causes**:
- Required environment variable missing
- Configuration value invalid or unparseable

**Fix: Set Missing Variables**
```bash
# Set required env vars
gcloud run services update prediction-worker \
  --region=us-central1 \
  --project=nba-props-platform \
  --update-env-vars GCP_PROJECT_ID=nba-props-platform
```

### Verification

```bash
# Call health endpoint again
curl -s "${SERVICE_URL}/health/deep" | jq '.status'
# Should return: "healthy"

# Check uptime check status in console
gcloud monitoring uptime-checks list --project=nba-props-platform
```

### When Alert Fires But Health Check Passes

If you call `/health/deep` directly and it passes, but the alert fired:

**Possible Causes**:
1. **Transient issue**: Temporary network/GCS/BigQuery issue that resolved itself
2. **Service restart**: Service was restarting during health check
3. **Cold start**: Health check timed out during cold start

**Action**: Monitor for repeat occurrences. If alert fires repeatedly, investigate deeper.

---

## General Alert Response Checklist

For any critical alert:

1. ✅ **Acknowledge** alert in Slack
2. ✅ **Assess impact** - Check recent prediction counts/quality
3. ✅ **Follow runbook** - Execute investigation steps
4. ✅ **Apply fix** - Use appropriate fix from runbook
5. ✅ **Verify** - Confirm alert cleared and system healthy
6. ✅ **Document** - Update incident log with:
   - Time detected
   - Root cause
   - Fix applied
   - Time resolved
7. ✅ **Post-mortem** (for extended outages) - Identify improvements

---

## Support & Escalation

- **Primary**: Platform team (#platform-team Slack channel)
- **On-call**: Check on-call rotation in PagerDuty (if configured)
- **Documentation**: `/docs/04-deployment/` directory
- **GCP Console**: https://console.cloud.google.com/run?project=nba-props-platform

---

**Last Updated**: 2026-01-17 (Week 2 + Automation - Session 83)
**Next Review**: After Week 3 implementation (dashboards and visibility)

**Note**: Feature Staleness and Confidence Drift alerts are now automated. See `docs/08-projects/current/nba-alerting-visibility/MONITORING-AUTOMATION-SETUP.md` for Cloud Scheduler setup instructions.
