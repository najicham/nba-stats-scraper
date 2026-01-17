# NBA Alerting and Visibility Strategy

**Created**: 2026-01-17
**Purpose**: Prevent incidents like CatBoost V8 (Jan 14-17, 2026) through proactive monitoring
**Audience**: DevOps, SRE, Platform Team

---

## 🎯 PROBLEM STATEMENT

**CatBoost V8 Incident (Jan 14-17, 2026)**:
- Missing `CATBOOST_V8_MODEL_PATH` environment variable
- Service appeared healthy but predictions degraded for 3 days
- 1,071 failed predictions (50% confidence fallback)
- **Detection**: Manual investigation after 3 days
- **No alerts triggered**

**Root Issues**:
1. ❌ No alert when model failed to load
2. ❌ No alert when predictions used fallback
3. ❌ No alert when confidence distribution changed
4. ❌ No alert when environment variables changed
5. ❌ No visibility into service configuration state

---

## 📊 ALERTING STRATEGY

### Tier 1: CRITICAL - Immediate Response Required

These alerts indicate active degradation affecting production predictions.

#### 1.1 Model Loading Failures

**Alert**: "NBA Prediction Worker - Model Loading Failed"

**Trigger**: Model fails to load on service startup

**Detection Method**: Log-based metric

**Implementation**:
```bash
# Create log-based metric
gcloud logging metrics create nba_model_load_failures \
  --project=nba-props-platform \
  --description="NBA prediction worker model loading failures" \
  --log-filter='resource.type="cloud_run_revision"
    AND resource.labels.service_name="prediction-worker"
    AND severity>=ERROR
    AND (
      textPayload=~"model FAILED to load"
      OR textPayload=~"CatBoost V8 model FAILED to load"
      OR textPayload=~"Model not loaded"
    )'

# Create alert policy
gcloud alpha monitoring policies create \
  --project=nba-props-platform \
  --notification-channels=SLACK_CHANNEL_ID \
  --display-name="[CRITICAL] NBA Model Loading Failures" \
  --condition-display-name="Model failed to load in last 5 minutes" \
  --condition-threshold-value=1 \
  --condition-threshold-duration=300s \
  --condition-threshold-comparison=COMPARISON_GT \
  --aggregation-alignment-period=60s \
  --condition-threshold-filter='metric.type="logging.googleapis.com/user/nba_model_load_failures"
    resource.type="cloud_run_revision"'
```

**Alert Channels**: Slack (immediate), Email (critical), PagerDuty (if exists)

**Expected Behavior**: Alert fires within 5 minutes of model loading failure

**Runbook**:
1. Check service logs for error details
2. Verify `CATBOOST_V8_MODEL_PATH` environment variable is set
3. Verify GCS model file exists
4. Check service account has `storage.objectViewer` role
5. Redeploy if needed with correct env vars

---

#### 1.2 High Fallback Prediction Rate

**Alert**: "NBA Predictions Using Fallback (Degraded Quality)"

**Trigger**: More than 10% of predictions using fallback mode

**Detection Method**: Log-based metric on fallback predictions

**Implementation**:
```bash
# Create log-based metric for fallback predictions
gcloud logging metrics create nba_fallback_predictions \
  --project=nba-props-platform \
  --description="NBA predictions using fallback mode (50% confidence)" \
  --log-filter='resource.type="cloud_run_revision"
    AND resource.labels.service_name="prediction-worker"
    AND (
      textPayload=~"FALLBACK_PREDICTION"
      OR textPayload=~"using weighted average"
      OR textPayload=~"confidence will be 50"
    )'

# Create alert policy
gcloud alpha monitoring policies create \
  --project=nba-props-platform \
  --notification-channels=SLACK_CHANNEL_ID \
  --display-name="[CRITICAL] NBA High Fallback Prediction Rate" \
  --condition-display-name="Fallback rate > 10% in last 10 minutes" \
  --condition-threshold-value=0.1 \
  --condition-threshold-duration=600s \
  --condition-threshold-comparison=COMPARISON_GT \
  --aggregation-alignment-period=60s \
  --condition-threshold-filter='metric.type="logging.googleapis.com/user/nba_fallback_predictions"
    resource.type="cloud_run_revision"'
```

**Alert Channels**: Slack, Email

**Expected Behavior**: Alert fires if >10% of predictions use fallback in 10-minute window

**Why 10% threshold?**: Some fallback is expected during cold starts, but sustained high rate indicates configuration issue

**Runbook**:
1. Query BigQuery for confidence distribution
2. Check if model path environment variable is set
3. Check model loading logs
4. Verify recent deployments didn't drop env vars

---

#### 1.3 Confidence Score Distribution Anomaly

**Alert**: "NBA Prediction Confidence Distribution Abnormal"

**Trigger**: All predictions have same confidence score (e.g., all 50%)

**Detection Method**: BigQuery scheduled query checking confidence distribution

**Implementation**:
```sql
-- Create scheduled query (runs every hour)
-- BigQuery -> Scheduled Queries -> Create

-- Query:
WITH confidence_distribution AS (
  SELECT
    game_date,
    system_id,
    ROUND(confidence_score * 100) as confidence,
    COUNT(*) as prediction_count,
    COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY game_date, system_id) as pct
  FROM `nba-props-platform.nba_predictions.player_prop_predictions`
  WHERE game_date = CURRENT_DATE()
    AND system_id = 'catboost_v8'
  GROUP BY game_date, system_id, confidence
),
anomaly_check AS (
  SELECT
    game_date,
    system_id,
    COUNT(DISTINCT confidence) as unique_confidence_values,
    MAX(pct) as max_single_confidence_pct,
    ARRAY_AGG(confidence ORDER BY prediction_count DESC LIMIT 3) as top_confidences
  FROM confidence_distribution
  GROUP BY game_date, system_id
)
SELECT
  game_date,
  system_id,
  unique_confidence_values,
  max_single_confidence_pct,
  top_confidences,
  CASE
    WHEN unique_confidence_values = 1 AND top_confidences[OFFSET(0)] = 50 THEN 'CRITICAL: All predictions at 50% - model not loaded'
    WHEN unique_confidence_values <= 2 THEN 'WARNING: Low confidence diversity'
    WHEN max_single_confidence_pct > 0.8 THEN 'WARNING: High concentration in single confidence value'
    ELSE 'OK'
  END as status
FROM anomaly_check
WHERE status != 'OK'
```

**Alert Action**: Send to Pub/Sub topic → Cloud Function → Slack

**Expected Behavior**: Expected confidence range is 79-95% with variety

**Runbook**:
1. Check status from query result
2. If all 50%: Model not loaded, check env vars
3. If low diversity: Check feature quality scores
4. Compare to historical distributions

---

### Tier 2: WARNING - Investigate Soon

These alerts indicate potential issues that should be investigated within 1-2 hours.

#### 2.1 Environment Variable Changes

**Alert**: "NBA Service Environment Variables Changed"

**Trigger**: Environment variables modified on Cloud Run service

**Detection Method**: Cloud Audit Logs

**Implementation**:
```bash
# Create log-based metric for env var changes
gcloud logging metrics create nba_env_var_changes \
  --project=nba-props-platform \
  --description="Environment variable changes on NBA services" \
  --log-filter='protoPayload.serviceName="run.googleapis.com"
    AND protoPayload.methodName="google.cloud.run.v1.Services.ReplaceService"
    AND (
      protoPayload.request.metadata.name="prediction-worker"
      OR protoPayload.request.metadata.name="prediction-coordinator"
      OR protoPayload.request.metadata.name=~"nba-phase"
    )
    AND protoPayload.request.spec.template.spec.containers.env'

# Create alert
gcloud alpha monitoring policies create \
  --project=nba-props-platform \
  --notification-channels=SLACK_CHANNEL_ID \
  --display-name="[WARNING] NBA Environment Variables Changed" \
  --condition-display-name="Env vars changed" \
  --condition-threshold-value=1 \
  --condition-threshold-duration=60s \
  --aggregation-alignment-period=60s \
  --condition-threshold-filter='metric.type="logging.googleapis.com/user/nba_env_var_changes"'
```

**Alert Channels**: Slack

**Alert Message Should Include**:
- Service name
- Who made the change (protoPayload.authenticationInfo.principalEmail)
- Timestamp
- Link to Cloud Console

**Expected Behavior**: Alert fires immediately when env vars change

**Runbook**:
1. Review what changed (check Cloud Audit Logs)
2. Verify change was intentional
3. Check if critical env vars (like CATBOOST_V8_MODEL_PATH) were removed
4. Rollback if accidental
5. Update documentation

---

#### 2.2 Service Deployment Without Required Variables

**Alert**: "NBA Service Deployed Missing Required Variables"

**Trigger**: Deployment completes but startup logs show missing required vars

**Detection Method**: Log-based metric on startup validation

**Implementation**:
```bash
# Create log-based metric
gcloud logging metrics create nba_missing_required_vars \
  --project=nba-props-platform \
  --description="Services started with missing required environment variables" \
  --log-filter='resource.type="cloud_run_revision"
    AND (
      resource.labels.service_name="prediction-worker"
      OR resource.labels.service_name="prediction-coordinator"
    )
    AND severity=ERROR
    AND textPayload=~"Missing required environment variables"'

# Create alert
gcloud alpha monitoring policies create \
  --project=nba-props-platform \
  --notification-channels=SLACK_CHANNEL_ID \
  --display-name="[WARNING] NBA Service Missing Required Variables" \
  --condition-display-name="Service started with missing vars" \
  --condition-threshold-value=1 \
  --condition-threshold-duration=60s \
  --aggregation-alignment-period=60s \
  --condition-threshold-filter='metric.type="logging.googleapis.com/user/nba_missing_required_vars"'
```

**Prerequisite**: Requires startup validation code (see NBA-FOCUSED-FIX-TODO-LIST.md, Task 5)

**Alert Channels**: Slack, Email

**Runbook**:
1. Check startup logs for which variables are missing
2. Redeploy with correct env vars using `--update-env-vars`
3. Verify service health after fix

---

#### 2.3 GCS Model File Access Issues

**Alert**: "NBA Prediction Worker Cannot Access GCS Model File"

**Trigger**: Deep health check reports GCS access failure

**Detection Method**: Health check endpoint monitoring

**Implementation**:
```bash
# Create uptime check for deep health endpoint
gcloud monitoring uptime create nba-prediction-worker-deep-health \
  --project=nba-props-platform \
  --display-name="NBA Prediction Worker Deep Health" \
  --resource-type=uptime-url \
  --monitored-resource=https://prediction-worker-756957797294.us-west2.run.app/health/deep \
  --check-interval=5m \
  --timeout=30s

# Create alert policy for failed health checks
gcloud alpha monitoring policies create \
  --project=nba-props-platform \
  --notification-channels=SLACK_CHANNEL_ID \
  --display-name="[WARNING] NBA Prediction Worker Deep Health Failed" \
  --condition-display-name="Deep health check failing" \
  --condition-threshold-value=2 \
  --condition-threshold-duration=300s \
  --aggregation-alignment-period=60s \
  --condition-threshold-filter='metric.type="monitoring.googleapis.com/uptime_check/check_passed"
    resource.labels.check_id="nba-prediction-worker-deep-health"'
```

**Prerequisite**: Requires deep health check endpoint (see NBA-FOCUSED-FIX-TODO-LIST.md, Task 6)

**Alert Channels**: Slack

**Runbook**:
1. Check deep health check response for details
2. Verify GCS model file exists
3. Check service account permissions
4. Test GCS access manually

---

### Tier 3: INFO - Awareness and Tracking

These alerts provide visibility but don't require immediate action.

#### 3.1 New Service Revision Deployed

**Alert**: "NBA Service Deployed - New Revision"

**Trigger**: New Cloud Run revision created

**Detection Method**: Cloud Audit Logs

**Implementation**:
```bash
# Create log sink to Pub/Sub
gcloud logging sinks create nba-deployments \
  --project=nba-props-platform \
  --log-filter='protoPayload.serviceName="run.googleapis.com"
    AND protoPayload.methodName="google.cloud.run.v1.Services.ReplaceService"
    AND (
      protoPayload.request.metadata.name="prediction-worker"
      OR protoPayload.request.metadata.name="prediction-coordinator"
      OR protoPayload.request.metadata.name=~"nba-phase"
    )' \
  --destination=pubsub.googleapis.com/projects/nba-props-platform/topics/nba-deployment-notifications

# Cloud Function subscribes to topic and sends to Slack
```

**Alert Channels**: Slack (#deployments channel)

**Alert Message Should Include**:
- Service name
- New revision name
- Deployed by (user email)
- Timestamp
- Previous revision (for comparison)
- Link to Cloud Console

**Expected Behavior**: Notification within 1 minute of deployment

**Purpose**: Deployment audit trail, helps correlate issues with recent changes

---

#### 3.2 Daily Prediction Summary

**Alert**: "NBA Daily Prediction Summary"

**Trigger**: Daily at 9 AM (after predictions complete)

**Detection Method**: BigQuery scheduled query

**Implementation**:
```sql
-- Scheduled query runs daily at 9 AM
SELECT
  CURRENT_DATE() as report_date,
  system_id,
  COUNT(*) as total_predictions,
  COUNT(DISTINCT player_lookup) as unique_players,
  ROUND(AVG(confidence_score) * 100, 1) as avg_confidence,
  ROUND(MIN(confidence_score) * 100, 1) as min_confidence,
  ROUND(MAX(confidence_score) * 100, 1) as max_confidence,
  COUNTIF(confidence_score = 0.50) as fallback_count,
  COUNTIF(recommendation = 'OVER') as over_count,
  COUNTIF(recommendation = 'UNDER') as under_count,
  COUNTIF(recommendation = 'PASS') as pass_count
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v8'
GROUP BY system_id

-- Send to Pub/Sub → Cloud Function → Slack
```

**Alert Channels**: Slack (#predictions-summary)

**Alert Message Format**:
```
📊 NBA Predictions Summary - 2026-01-17

CatBoost V8:
✅ Total Predictions: 80
✅ Unique Players: 57
✅ Avg Confidence: 87.3%
✅ Confidence Range: 79% - 95%
⚠️ Fallback Count: 0 (expected: 0)
📈 OVER: 35 | UNDER: 40 | PASS: 5

Status: ✅ HEALTHY
```

**Purpose**: Daily health check, baseline for detecting anomalies

---

## 🔍 VISIBILITY DASHBOARDS

### Dashboard 1: NBA Prediction Service Health

**Platform**: Cloud Monitoring / Grafana

**Panels**:

1. **Model Loading Success Rate** (Last 24h)
   - Metric: `nba_model_load_failures` (inverted)
   - Visualization: Line chart
   - Alert Threshold: 95%

2. **Fallback Prediction Rate** (Last 24h)
   - Metric: `nba_fallback_predictions` / total predictions
   - Visualization: Line chart
   - Alert Threshold: 10%

3. **Confidence Score Distribution** (Today)
   - Source: BigQuery
   - Visualization: Histogram
   - Expected: Bell curve between 79-95%

4. **Predictions Generated** (Last 7 days)
   - Source: BigQuery
   - Visualization: Bar chart by system
   - Track: catboost_v8, ensemble_v1, etc.

5. **Service Uptime** (Last 30 days)
   - Metric: Cloud Run uptime checks
   - Visualization: Uptime percentage
   - Target: 99.9%

6. **Environment Variable Stability** (Last 30 days)
   - Metric: `nba_env_var_changes`
   - Visualization: Timeline
   - Annotate: Deployments

**Access**: https://console.cloud.google.com/monitoring/dashboards/custom/nba-predictions

---

### Dashboard 2: Configuration Audit

**Platform**: Custom web dashboard or Looker

**Data Sources**: Cloud Run API + BigQuery

**Panels**:

1. **Required Environment Variables Status**
   - Service: prediction-worker
   - Show: ✅ or ❌ for each required var
   - Refresh: Every 5 minutes

2. **Model File Accessibility**
   - Test: GCS file exists
   - Show: File size, last modified, accessible
   - Refresh: Every 15 minutes

3. **Recent Deployments**
   - Source: Cloud Audit Logs
   - Show: Last 10 deployments with env var changes
   - Highlight: Changes to critical vars

4. **Alert Configuration Status**
   - Show: Which alerts are enabled
   - Show: Last time each alert fired
   - Show: Alert response times

**Purpose**: Quick visibility into configuration state

---

## 🚨 ALERT ROUTING

### Slack Channels

**#nba-alerts-critical** (PagerDuty integration):
- Model loading failures
- High fallback rate
- Service down

**#nba-alerts-warning**:
- Environment variable changes
- Missing required variables
- GCS access issues

**#nba-deployments**:
- New revision deployments
- Configuration changes

**#nba-predictions-summary**:
- Daily summaries
- Performance metrics

### Email

**nchammas@gmail.com**:
- All critical alerts
- Daily summaries

### PagerDuty (If Available)

**On-Call Rotation**:
- Critical alerts only
- Model loading failures
- Service completely down

---

## 📋 IMPLEMENTATION CHECKLIST

### Phase 1: Critical Alerts (Week 1)
- [ ] Create log-based metric for model loading failures
- [ ] Create alert policy for model loading failures
- [ ] Create log-based metric for fallback predictions
- [ ] Create alert policy for high fallback rate
- [ ] Set up Slack webhook integration
- [ ] Test alerts with intentional failure

### Phase 2: Warning Alerts (Week 2)
- [ ] Create log-based metric for env var changes
- [ ] Create alert for env var changes
- [ ] Add startup validation to prediction-worker
- [ ] Create alert for missing required vars
- [ ] Add deep health check endpoint
- [ ] Create uptime check for deep health
- [ ] Create alert for deep health failures

### Phase 3: Dashboards (Week 3)
- [ ] Create Cloud Monitoring dashboard
- [ ] Add model loading success rate panel
- [ ] Add fallback rate panel
- [ ] Add confidence distribution panel
- [ ] Create BigQuery scheduled query for daily summary
- [ ] Set up Pub/Sub → Cloud Function → Slack pipeline
- [ ] Test daily summary delivery

### Phase 4: Info Alerts (Week 4)
- [ ] Create log sink for deployment notifications
- [ ] Create Cloud Function for deployment Slack notifications
- [ ] Set up daily prediction summary query
- [ ] Create configuration audit dashboard
- [ ] Document runbooks for each alert

---

## 🎯 SUCCESS METRICS

**Incident Detection Time**:
- **Before**: 3 days (CatBoost V8 incident)
- **Target**: < 5 minutes

**Alert Accuracy**:
- **Target**: < 5% false positive rate
- **Target**: 0% false negatives for critical issues

**Mean Time to Detection (MTTD)**:
- **Target**: < 5 minutes for critical issues
- **Target**: < 1 hour for warnings

**Mean Time to Resolution (MTTR)**:
- **Target**: < 30 minutes for critical issues
- **Target**: < 2 hours for warnings

---

## 🔄 MAINTENANCE

### Weekly Review
- Review alert firing frequency
- Adjust thresholds if too many false positives
- Check that all alerts are working (test alerts)

### Monthly Review
- Review MTTD/MTTR metrics
- Update runbooks based on incidents
- Add new alerts based on new failure modes

### Quarterly Review
- Full alert audit
- Dashboard redesign if needed
- Update this strategy document

---

## 📚 RELATED DOCUMENTATION

- **Environment Variables**: `docs/04-deployment/NBA-ENVIRONMENT-VARIABLES.md`
- **NBA Fix Todo List**: `docs/08-projects/current/catboost-v8-jan-2026-incident/NBA-FOCUSED-FIX-TODO-LIST.md`
- **Root Cause Analysis**: `docs/08-projects/current/catboost-v8-jan-2026-incident/ROOT-CAUSE-ANALYSIS.md`

---

## 🎓 LESSONS FROM CATBOOST V8 INCIDENT

**What Would Have Prevented It**:
1. ✅ Alert on model loading failure → Would fire immediately
2. ✅ Alert on high fallback rate → Would fire within 10 minutes
3. ✅ Alert on env var changes → Would flag when variable was removed
4. ✅ Deep health check → Would show degraded state
5. ✅ Daily summary → Would show anomalous confidence distribution

**Detection Timeline with This Strategy**:
- **00:00** - Deployment with missing env var
- **00:01** - Startup validation logs error (if implemented)
- **00:01** - Alert: "Service Missing Required Variables" fires
- **00:05** - Model loading failure logged
- **00:05** - Alert: "Model Loading Failed" fires
- **00:10** - First predictions use fallback
- **00:20** - Alert: "High Fallback Rate" fires (after 10-min window)
- **Total detection time**: < 1 minute (vs 3 days actual)

---

**Document Created**: 2026-01-17
**Status**: Ready for implementation
**Owner**: Platform Team
