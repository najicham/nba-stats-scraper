# Session 84: Week 3+ Alerts Implementation

**Status**: Ready to Start (after Session 83)
**Priority**: Medium
**Estimated Scope**: 1-2 hours
**Prerequisites**: Session 83 complete (Week 2 alerts deployed)

---

## Objective

Implement Week 3+ operational and informational alerts for comprehensive monitoring of the NBA prediction platform.

**Success Criteria**:
- [ ] 3-5 INFO-level alerts deployed
- [ ] Alerts provide visibility into system operations
- [ ] Runbooks updated with investigation procedures
- [ ] Full alerting strategy implemented and documented

---

## Context from Previous Sessions

### Session 82 (Week 1): Critical Alerts ✅
- Model Loading Failures
- High Fallback Prediction Rate

### Session 83 (Week 2): Warning Alerts ✅
- Stale Predictions
- DLQ Depth
- Feature Pipeline Staleness
- Confidence Distribution Drift

### Current Gap: Week 3+ Alerts
Operational visibility and trend monitoring not yet implemented.

---

## What to Build: Week 3+ Alerts

### From IMPLEMENTATION-ROADMAP.md

Implement **info-level** alerts for operational awareness:

#### 1. Daily Prediction Volume Anomaly (INFO)
**Purpose**: Detect unusual prediction volume (too high or too low)

**Metric**: Count of predictions generated per day
**Threshold**: > 30% deviation from 7-day average
**Query**:
```sql
-- Today's volume
SELECT COUNT(*) as today_volume
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE DATE(created_at) = CURRENT_DATE()
  AND system_id = 'catboost_v8'

-- 7-day average
SELECT AVG(daily_count) as avg_volume
FROM (
  SELECT DATE(created_at) as date, COUNT(*) as daily_count
  FROM `nba-props-platform.nba_predictions.player_prop_predictions`
  WHERE DATE(created_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND system_id = 'catboost_v8'
  GROUP BY date
)
```

**Rationale**: Helps identify schedule changes, pipeline issues, or unexpected behavior.

#### 2. Data Source Availability (INFO)
**Purpose**: Track which data sources are contributing vs. failing

**Metric**: % of boxscores from each source (BDL, ESPN, NBA.com)
**Threshold**: Primary source (NBA.com) < 80% contribution
**Query**:
```sql
SELECT
  primary_source_used,
  COUNT(*) as records,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 2) as pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
GROUP BY primary_source_used
```

**Rationale**: Ensures redundancy is working and flags source degradation.

#### 3. Model Version Tracking (INFO)
**Purpose**: Alert when multiple model versions are in production

**Metric**: Count of distinct model versions generating predictions
**Threshold**: > 1 active model version
**Query**:
```sql
SELECT
  model_version,
  COUNT(*) as predictions,
  MIN(created_at) as first_seen,
  MAX(created_at) as last_seen
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
  AND system_id = 'catboost_v8'
GROUP BY model_version
HAVING COUNT(DISTINCT model_version) > 1
```

**Rationale**: During rollouts, multiple versions may run. Good to track for consistency.

#### 4. Prediction Latency (INFO)
**Purpose**: Track how long predictions take to generate

**Metric**: p95 latency from prediction request to completion
**Threshold**: > 5 seconds (indicates performance degradation)
**Source**: Log-based metric from prediction-worker logs

**Log filter**:
```
resource.labels.service_name="prediction-worker"
AND textPayload=~"Prediction completed in"
```

**Extract latency** from log message and create distribution metric.

**Rationale**: Early warning of performance issues before users are impacted.

#### 5. Workflow Execution Success Rate (INFO)
**Purpose**: Monitor overall orchestration health

**Metric**: % of workflow executions that succeed
**Threshold**: < 95% success rate over 24 hours
**Query**:
```sql
SELECT
  workflow_name,
  COUNTIF(status = 'completed') as success_count,
  COUNT(*) as total_count,
  ROUND(100.0 * COUNTIF(status = 'completed') / COUNT(*), 2) as success_rate
FROM `nba-props-platform.nba_orchestration.workflow_executions`
WHERE DATE(execution_time) >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
GROUP BY workflow_name
HAVING success_rate < 95
```

**Rationale**: From Session 82 validation, workflows are critical. Should track success rate.

---

## Implementation Approach

### Option A: Scheduled Reports (Recommended for Week 3+)
Instead of real-time alerts, implement **daily digest reports**:

1. **Cloud Scheduler** triggers daily (8am PT)
2. **Cloud Function** runs queries above
3. **Results sent to Slack** as summary report
4. **Only alert if anomalies detected**

**Pros**:
- Less alert fatigue
- Better for trend data
- Easier to implement than real-time metrics

**Cons**:
- Not real-time (but Week 3+ alerts don't need to be)

### Option B: Log-Based Metrics + Alerts
Create metrics for each, set up traditional Cloud Monitoring alerts.

**Pros**:
- Real-time monitoring
- Integrated with existing alerts

**Cons**:
- More complex for SQL-based metrics
- Potential for alert fatigue

**Recommendation**: Start with **Option A** for Week 3+. These are informational and benefit from daily aggregation.

---

## Implementation Steps

### Phase 1: Create Daily Digest Function (1 hour)

1. **Create Cloud Function** (`nba_daily_digest`):
   - Language: Python
   - Trigger: Cloud Scheduler (daily 8am PT)
   - Queries: Run all 5 queries above
   - Output: Format as Slack message

2. **Configure Cloud Scheduler**:
   ```bash
   gcloud scheduler jobs create http nba-daily-digest \
     --location=us-west2 \
     --schedule="0 8 * * *" \
     --time-zone="America/Los_Angeles" \
     --uri="https://[FUNCTION_URL]" \
     --http-method=POST
   ```

3. **Slack Integration**:
   - Webhook URL for #nba-platform-health channel
   - Format report with markdown
   - Only send if anomalies detected (otherwise just log "all good")

### Phase 2: Document Runbooks (30 min)

Update `docs/04-deployment/ALERT-RUNBOOKS.md`:

Add section: **Daily Digest Alerts**

For each metric:
- What it measures
- Normal ranges
- What anomalies indicate
- How to investigate

### Phase 3: Testing (15 min)

1. **Test function manually**:
   ```bash
   gcloud functions call nba-daily-digest
   ```

2. **Verify Slack notification**

3. **Check logs** for errors

### Phase 4: Documentation (15 min)

Create `docs/09-handoff/SESSION-84-WEEK3-ALERTS-COMPLETE.md`:
- Implementation details
- Function URL and configuration
- How to modify queries
- How to add new metrics

Update `docs/04-deployment/IMPLEMENTATION-ROADMAP.md`:
- Mark all alerting phases complete
- Note completion date

---

## Alternative: Manual Dashboard

If Cloud Function is too complex, create **Looker Studio dashboard** instead:

1. **Create data source**: Connect to BigQuery
2. **Add scorecards** for each metric
3. **Set alert thresholds** with conditional formatting
4. **Share with team**
5. **Manual daily review** (no automation)

**Trade-off**: Less automated but faster to implement.

---

## Key Files

### Read
- `docs/04-deployment/ALERTING-AND-VISIBILITY-STRATEGY.md`
- `docs/04-deployment/IMPLEMENTATION-ROADMAP.md`
- Session 83 handoff (for context on Week 2 alerts)

### Modify
- `docs/04-deployment/ALERT-RUNBOOKS.md` - Add daily digest section
- `docs/04-deployment/IMPLEMENTATION-ROADMAP.md` - Mark complete

### Create
- Cloud Function: `functions/nba_daily_digest/main.py`
- `docs/09-handoff/SESSION-84-WEEK3-ALERTS-COMPLETE.md`

---

## Sample Daily Digest Format

```
🏀 NBA Platform Daily Digest - 2026-01-18

✅ HEALTHY: All systems nominal

📊 Metrics:
• Predictions: 247 (avg: 238, +3.8%)
• Primary source: nba.com (100%)
• Model versions: 1 (catboost_v8_33features_20260108_211817.cbm)
• p95 latency: 2.3s
• Workflow success: 100% (24/24)

---
⚠️ ATTENTION NEEDED: None

📈 Trends:
• Prediction volume up 3.8% vs 7-day avg
• All data sources healthy
• Latency within normal range

View full logs: https://console.cloud.google.com/...
```

If anomalies:
```
🏀 NBA Platform Daily Digest - 2026-01-18

⚠️ ATTENTION NEEDED: 2 anomalies detected

📊 Metrics:
• Predictions: 147 (avg: 238, -38% ⚠️)
• Primary source: bdl (60% ⚠️), nba.com (40%)
• Model versions: 1
• p95 latency: 2.1s
• Workflow success: 95% (19/20)

🔍 Anomalies:
1. ⚠️ Prediction volume 38% below average
   → Investigate: Fewer games scheduled or orchestration issue?

2. ⚠️ NBA.com source only 40% (expected 80%+)
   → Investigate: NBA.com API issues? Check Phase 1 scrapers.

Runbook: docs/04-deployment/ALERT-RUNBOOKS.md
Logs: https://console.cloud.google.com/...
```

---

## Success Checklist

- [ ] Daily digest implemented (Cloud Function OR dashboard)
- [ ] All 5 metrics tracked
- [ ] Slack notifications working (if automated)
- [ ] Runbook section added for digest alerts
- [ ] Tested with sample data
- [ ] IMPLEMENTATION-ROADMAP.md marked complete
- [ ] Handoff document created

---

## Considerations

1. **Notification fatigue**: Only alert on anomalies, not every day
2. **Metric staleness**: Cache query results to avoid quota issues
3. **Cost**: BigQuery queries daily - monitor costs
4. **Maintenance**: Queries may need tuning as system evolves

---

## Optional Enhancements

If time permits:
- **Grafana dashboard** integration
- **Historical trend charts** (not just daily)
- **Correlation analysis** (e.g., low volume + source issues = investigation needed)
- **Anomaly detection ML** (instead of simple thresholds)

---

## Related Sessions

- **Session 82**: Week 1 critical alerts (foundation)
- **Session 83**: Week 2 warning alerts (prerequisite)
- **Session 85**: NBA grading (parallel work)

---

**Ready to start**: Copy this document content into a new chat to begin implementation.
**Estimated completion**: 1-2 hours (Cloud Function) or 30 min (dashboard only).
