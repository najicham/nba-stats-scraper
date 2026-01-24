# Session 83: Week 2 Alerts Implementation

**Status**: Ready to Start
**Priority**: High
**Estimated Scope**: 2-3 hours
**Prerequisites**: Session 82 complete (Week 1 alerts deployed)

---

## Objective

Implement Week 2 warning-level alerts for the NBA prediction platform to catch issues before they become critical.

**Success Criteria**:
- [ ] 3-4 warning-level alerts deployed to Cloud Monitoring
- [ ] Alerts documented in ALERT-RUNBOOKS.md
- [ ] Validation confirms alerts can trigger correctly
- [ ] Slack notifications configured (if available)

---

## Context from Session 82

### What Was Completed
- ✅ Week 1 critical alerts deployed:
  - `[CRITICAL] NBA Model Loading Failures`
  - `[CRITICAL] NBA High Fallback Prediction Rate`
- ✅ Enhanced validation in prediction-worker
- ✅ Alert runbooks created
- ✅ System validated and healthy

### Current System State (2026-01-17)
- **Prediction Worker**: revision `prediction-worker-00055-mlj` (100% traffic)
- **Model Loading**: Working correctly, CATBOOST_V8_MODEL_PATH preserved
- **Predictions**: 100% ML-based (no fallback predictions for current games)
- **Critical Alerts**: Enabled and healthy (not firing)
- **DLQ**: Empty (no message accumulation)

---

## What to Build: Week 2 Alerts

### From IMPLEMENTATION-ROADMAP.md

Implement **warning-level** alerts that detect issues early:

#### 1. Stale Predictions Alert (WARNING)
**Purpose**: Detect when prediction generation stops or slows

**Metric**: Time since last successful prediction
**Threshold**: > 2 hours with no new predictions
**Log-based metric**:
```
resource.labels.service_name="prediction-worker"
AND textPayload=~"Prediction saved successfully"
```

**Rationale**: Should have predictions regularly for upcoming games. 2+ hours of silence indicates orchestration or worker issue.

#### 2. DLQ Depth Alert (WARNING)
**Purpose**: Detect messages accumulating in dead letter queue

**Metric**: Pub/Sub subscription undelivered message count
**Threshold**: > 50 messages for > 30 minutes
**Metric type**: `pubsub.googleapis.com/subscription/num_undelivered_messages`
**Filter**: `resource.subscription_id="prediction-request-dlq-sub"`

**Rationale**: From Session 82, we documented DLQ monitoring. Should alert if messages pile up.

#### 3. Feature Pipeline Staleness (WARNING)
**Purpose**: Detect when ml_feature_store_v2 stops updating

**Metric**: Time since last feature update
**Threshold**: > 4 hours with no new features for upcoming games
**Query**:
```sql
SELECT MAX(created_at) as last_update
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date >= CURRENT_DATE()
```

**Rationale**: Features should update daily. Stale features = Phase 2 pipeline issue.

#### 4. Prediction Confidence Distribution Drift (WARNING)
**Purpose**: Detect when confidence scores shift dramatically (model issue)

**Metric**: % of predictions with confidence outside normal range (75-95%)
**Threshold**: > 30% of predictions outside range in 1 hour window
**Query**:
```sql
SELECT
  COUNTIF(confidence_score < 0.75 OR confidence_score > 0.95) / COUNT(*) as drift_pct
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
  AND system_id = 'catboost_v8'
```

**Rationale**: Normal ML predictions cluster 79-95%. Major shift suggests model corruption or feature issues.

---

## Implementation Steps

### Phase 1: Create Alerts (1-1.5 hours)

1. **Review alert strategy doc**:
   ```bash
   cat docs/04-deployment/ALERTING-AND-VISIBILITY-STRATEGY.md
   ```

2. **Create log-based metrics** (for #1):
   - Metric name: `nba_prediction_generation_success`
   - Filter: Successful prediction logs
   - Counter type

3. **Create alerts in Cloud Monitoring**:
   - Use `gcloud alpha monitoring policies create`
   - Follow naming: `[WARNING] NBA [Description]`
   - Set appropriate thresholds
   - Configure notification channels (Slack if available)

4. **For DLQ alert (#2)**:
   - Use existing Pub/Sub metric
   - No custom metric needed

5. **For SQL-based alerts (#3, #4)**:
   - Consider: Log-based metrics via scheduled query + log sink
   - OR: Cloud Monitoring query-based alerts (if supported)
   - OR: Document as manual check for now, automate later

### Phase 2: Document Runbooks (30-45 min)

Update `docs/04-deployment/ALERT-RUNBOOKS.md`:

For each alert, add section with:
- Alert details (name, metric, threshold)
- What it means
- Common causes
- Investigation steps
- Fixes
- Verification

Use existing critical alert sections as template.

### Phase 3: Validation (30-45 min)

1. **Test each alert can trigger**:
   - Stale predictions: Wait 2+ hours OR simulate by stopping orchestrator
   - DLQ depth: Manually publish test messages to DLQ
   - Feature staleness: Check if query returns expected data
   - Confidence drift: Verify query works on real data

2. **Verify notifications work** (if Slack configured)

3. **Update IMPLEMENTATION-ROADMAP.md**:
   - Mark Week 2 as complete
   - Update status section

### Phase 4: Handoff Documentation (15 min)

Create `docs/09-handoff/SESSION-83-WEEK2-ALERTS-COMPLETE.md`:
- What was implemented
- Alert names and IDs
- Validation results
- Known limitations
- Next steps (Week 3+ alerts)

---

## Key Files to Work With

### Read These First
- `docs/04-deployment/ALERTING-AND-VISIBILITY-STRATEGY.md` - Overall strategy
- `docs/04-deployment/IMPLEMENTATION-ROADMAP.md` - Full roadmap
- `docs/04-deployment/ALERT-RUNBOOKS.md` - Existing runbook format

### Modify These
- `docs/04-deployment/ALERT-RUNBOOKS.md` - Add Week 2 alert sections
- `docs/04-deployment/IMPLEMENTATION-ROADMAP.md` - Update status

### Create These
- `docs/09-handoff/SESSION-83-WEEK2-ALERTS-COMPLETE.md` - Final handoff

---

## Important Notes

### Alert Naming Convention
- Format: `[WARNING] NBA [Brief Description]`
- Examples:
  - `[WARNING] NBA Stale Predictions`
  - `[WARNING] NBA High DLQ Depth`
  - `[WARNING] NBA Feature Pipeline Stale`
  - `[WARNING] NBA Confidence Distribution Drift`

### Threshold Philosophy
- **WARNING alerts** should fire before CRITICAL
- Give enough time to investigate before issue becomes critical
- Avoid alert fatigue - tune thresholds based on normal patterns

### SQL-Based Metrics Challenge
Cloud Monitoring doesn't natively support scheduled SQL queries for metrics. Options:
1. **Cloud Scheduler + Cloud Function + Logging** - Run query hourly, write metric to logs
2. **Log-based metric from application** - Add logging to existing services
3. **Manual checks initially** - Document in runbook, automate later

**Recommendation**: Start with #3 (document manual checks), then implement #1 if alerts prove valuable.

---

## Testing Commands

### Check Current Prediction Freshness
```bash
bq query --use_legacy_sql=false --project_id=nba-props-platform '
SELECT
  MAX(created_at) as last_prediction,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(created_at), MINUTE) as minutes_ago
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE system_id = "catboost_v8"'
```

### Check DLQ Depth
```bash
gcloud pubsub subscriptions describe prediction-request-dlq-sub \
  --project=nba-props-platform \
  --format=json | jq '{undelivered: .numUndeliveredMessages}'
```

### Check Feature Freshness
```bash
bq query --use_legacy_sql=false --project_id=nba-props-platform '
SELECT
  MAX(created_at) as last_feature,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(created_at), HOUR) as hours_ago
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date >= CURRENT_DATE()'
```

### Check Confidence Distribution
```bash
bq query --use_legacy_sql=false --project_id=nba-props-platform '
SELECT
  ROUND(confidence_score * 100) as confidence,
  COUNT(*) as count
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
  AND system_id = "catboost_v8"
GROUP BY confidence
ORDER BY confidence'
```

---

## Success Checklist

- [ ] 3-4 warning-level alerts deployed to Cloud Monitoring
- [ ] All alerts have runbook sections in ALERT-RUNBOOKS.md
- [ ] Tested that alerts can trigger (or have test plan)
- [ ] IMPLEMENTATION-ROADMAP.md updated to mark Week 2 complete
- [ ] Handoff document created (SESSION-83-WEEK2-ALERTS-COMPLETE.md)
- [ ] No breaking changes to existing critical alerts
- [ ] Validation confirms system still healthy

---

## Questions to Consider

1. **Notification channels**: Is Slack configured? If not, email only?
2. **On-call rotation**: Who should receive these warnings?
3. **Alert testing**: Simulate or wait for natural triggers?
4. **SQL metric automation**: Implement now or later?

---

## Related Sessions

- **Session 82**: Week 1 critical alerts (prerequisite)
- **Session 84**: Week 3+ alerts (follow-up)
- **Session 85**: NBA grading (parallel priority)

---

**Ready to start**: Copy this document content into a new chat to begin implementation.
**Estimated completion**: 2-3 hours for full implementation and documentation.
