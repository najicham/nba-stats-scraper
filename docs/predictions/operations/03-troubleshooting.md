# Phase 5 Troubleshooting Guide

**File:** `docs/processors/11-phase5-troubleshooting.md`
**Created:** 2025-11-09 15:00 PST
**Last Updated:** 2025-11-15 17:00 PST
**Purpose:** Failure scenarios, recovery procedures, and operational runbooks for Phase 5
**Status:** Draft (awaiting deployment)

---

## 📋 Table of Contents

1. [Failure Scenarios & Recovery](#failure-scenarios)
2. [Incident Response Playbook](#incident-response)
3. [Operational Procedures](#operational-procedures)
4. [Monitoring & Health Checks](#monitoring)
5. [Manual Operations Runbook](#runbook)
6. [Alert Rules](#alert-rules)
7. [Related Documentation](#related-docs)

---

## 🚨 Failure Scenarios & Recovery {#failure-scenarios}

### Scenario 1: Phase 4 Incomplete (No Features)

**Issue:** Phase 4 didn't run or failed, no features in `ml_feature_store_v2`

**Impact:** Phase 5 CANNOT run (no features to read)

**Severity:** 🔴 CRITICAL

**Detection:**

```sql
SELECT COUNT(*)
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE();
-- Returns: 0 (expected: 450)
```

**Recovery:**

```bash
# Step 1: Check Phase 4 logs
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=phase4-ml-feature-store-v2" \
  --limit 50 \
  --format json

# Step 2: Manually trigger Phase 4 processor #5
gcloud run jobs execute phase4-ml-feature-store-v2 \
  --region us-central1 \
  --set-env-vars "GAME_DATE=2025-11-07"

# Step 3: Wait for completion (~2 minutes)

# Step 4: Verify features created
bq query --use_legacy_sql=false "SELECT COUNT(*) FROM ml_feature_store_v2 WHERE game_date = CURRENT_DATE()"

# Step 5: Manually trigger Phase 5 coordinator
gcloud scheduler jobs run phase5-daily-predictions-trigger --location us-central1
```

**Timeline:** 5-10 minutes to recover

---

### Scenario 2: Coordinator Fails to Start

**Issue:** Coordinator crashes on startup (code bug, config error)

**Impact:** No workers receive tasks (0 predictions generated)

**Severity:** 🔴 CRITICAL

**Detection:**

```bash
# Check coordinator logs
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=phase5-prediction-coordinator" \
  --limit 10 \
  --format json
```

**Recovery:**

```bash
# Option A: Retry with same version
gcloud scheduler jobs run phase5-daily-predictions-trigger --location us-central1

# Option B: Rollback to previous working version
gcloud run jobs update phase5-prediction-coordinator \
  --image gcr.io/nba-props-platform/prediction-coordinator:previous-working-tag \
  --region us-central1

# Then retry
gcloud scheduler jobs run phase5-daily-predictions-trigger --location us-central1
```

**Timeline:** 2-5 minutes to recover

---

### Scenario 3: Some Workers Crash

**Issue:** 5 out of 20 workers crash (e.g., memory error)

**Impact:** Some players missing predictions (445/450 complete)

**Severity:** 🟡 WARNING (acceptable partial failure)

**Detection:**

```sql
-- Check which players missing predictions
SELECT DISTINCT player_lookup
FROM `nba_analytics.upcoming_player_game_context`
WHERE game_date = CURRENT_DATE()
  AND player_lookup NOT IN (
    SELECT DISTINCT player_lookup
    FROM `nba_predictions.player_prop_predictions`
    WHERE game_date = CURRENT_DATE()
  );
```

**Recovery:**

```bash
# Pub/Sub automatically retries failed messages (up to 3 times)
# If still failing after 3 retries, messages go to DLQ

# Check DLQ for failed players
bq query --use_legacy_sql=false "
SELECT
  JSON_EXTRACT_SCALAR(data, '$.player_lookup') as player,
  JSON_EXTRACT_SCALAR(data, '$.error') as error
FROM \`nba_logs.pubsub_dlq_messages\`
WHERE topic_name = 'prediction-worker-dlq'
  AND DATE(publish_time) = CURRENT_DATE()
"

# Manual recovery: Re-publish failed messages
python scripts/republish_failed_predictions.py --date 2025-11-07 --players "player1,player2,player3"
```

**Timeline:** Automatic retry (3 attempts), or manual recovery in 5 minutes

---

### Scenario 4: All Workers Crash Loop

**Issue:** Bug in worker code causes all instances to crash immediately

**Impact:** No predictions generated (0/450)

**Severity:** 🔴 CRITICAL

**Detection:**

```bash
# Check worker logs (all crashing)
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=phase5-prediction-worker" \
  --limit 50 \
  --format json | grep ERROR
```

**Recovery:**

```bash
# Step 1: Rollback worker to previous working version
gcloud run services update phase5-prediction-worker \
  --image gcr.io/nba-props-platform/prediction-worker:previous-working-tag \
  --region us-central1

# Step 2: Purge existing messages (prevent reprocessing with bad code)
gcloud pubsub subscriptions seek phase5-prediction-worker-sub \
  --time=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Step 3: Re-trigger coordinator (creates new messages)
gcloud scheduler jobs run phase5-daily-predictions-trigger --location us-central1
```

**Timeline:** 10-15 minutes to rollback and recover

---

### Scenario 5: Workers Timeout

**Issue:** Workers take >10 minutes per player (timeout)

**Impact:** Predictions incomplete, workers killed mid-processing

**Severity:** 🟡 WARNING

**Detection:**

```sql
-- Check prediction processing times
SELECT
  player_lookup,
  MIN(created_at) as first_prediction,
  MAX(created_at) as last_prediction,
  TIMESTAMP_DIFF(MAX(created_at), MIN(created_at), SECOND) as processing_seconds
FROM `nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
GROUP BY player_lookup
HAVING processing_seconds > 300  -- Over 5 minutes
ORDER BY processing_seconds DESC;
```

**Recovery:**

```bash
# Step 1: Identify slow component (BigQuery? XGBoost?)
# Check worker logs for timing

# Step 2: Increase timeout (temporary fix)
gcloud run services update phase5-prediction-worker \
  --timeout 900s \
  --region us-central1

# Step 3: Re-trigger for failed players
python scripts/republish_failed_predictions.py --date 2025-11-07

# Step 4: Investigate and fix performance issue (permanent fix)
```

**Timeline:** Immediate timeout increase, performance fix in days

---

### Scenario 6: One Prediction System Fails

**Issue:** XGBoost model fails to load (all workers)

**Impact:** Missing XGBoost predictions (4/5 systems work)

**Severity:** 🟡 WARNING (graceful degradation acceptable)

**Detection:**

```sql
-- Check system coverage
SELECT
  system_id,
  COUNT(DISTINCT player_lookup) as players
FROM `nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
GROUP BY system_id
ORDER BY players DESC;

-- Expected: 5 systems × 450 players
-- If XGBoost missing: Only 4 systems × 450 players
```

**Recovery:**

```bash
# Step 1: Workers continue with other 4 systems (no action needed)

# Step 2: Check XGBoost model path
gcloud storage ls gs://nba-props-models/xgboost/v1/

# Step 3: Fix model (reload, retrain, etc.)

# Step 4: Deploy fix and re-run XGBoost predictions only
python scripts/run_single_system.py --system xgboost --date 2025-11-07
```

**Timeline:** 4 systems working immediately, fix XGBoost within hours

---

## 🚨 Incident Response Playbook {#incident-response}

### P0 Incident: No Predictions Generated

**Symptoms:**
- 0 rows in `player_prop_predictions` for today
- Phase 6 publishing failed
- Critical alert in PagerDuty

**Response Procedure:**

**1. Acknowledge (1 min)**

```bash
# Acknowledge PagerDuty
# Post in Slack: "P0: No predictions, investigating"
```

**2. Check Coordinator (2 min)**

```bash
# Did coordinator run?
gcloud logging read "resource.type=cloud_run_job \
  AND resource.labels.job_name=prediction-coordinator \
  AND timestamp >= '$(date +%Y-%m-%d)T06:00:00Z'" \
  --limit 10

# Expected: Coordinator published 450 messages
# If no logs: Coordinator didn't run → Check Cloud Scheduler
```

**3. Check Pub/Sub Queue (2 min)**

```bash
# Are messages stuck in queue?
gcloud pubsub subscriptions describe prediction-worker-sub \
  --format="table(name, numUndeliveredMessages)"

# Expected: 0 (all delivered)
# If >0: Messages not delivered → Check worker
```

**4. Check Worker (3 min)**

```bash
# Are workers running?
gcloud run services describe prediction-worker \
  --region us-central1 \
  --format="table(status.traffic)"

# Did workers receive requests?
gcloud logging read "resource.type=cloud_run_revision \
  AND resource.labels.service_name=prediction-worker \
  AND timestamp >= '$(date +%Y-%m-%d)T06:00:00Z'" \
  --limit 10

# Expected: 450 requests processed
# If no logs: Workers not receiving messages → Check Pub/Sub push endpoint
```

**5. Root Cause (5 min)**

**Scenario A: Coordinator didn't run**

```bash
# Check Cloud Scheduler job status
gcloud scheduler jobs describe phase5-daily-predictions-trigger \
  --location us-central1

# If paused or misconfigured, fix and trigger manually
gcloud scheduler jobs run phase5-daily-predictions-trigger \
  --location us-central1
```

**Scenario B: Workers not scaling**

```bash
# Check service configuration
gcloud run services describe prediction-worker \
  --region us-central1 \
  --format="yaml(spec.template.spec)"

# Verify:
# - max-instances > 0
# - Pub/Sub push subscription configured
# - Service account has run.invoker permission
```

**Scenario C: All workers failing**

```bash
# Check for systematic errors
gcloud logging read "resource.type=cloud_run_revision \
  AND resource.labels.service_name=prediction-worker \
  AND severity >= ERROR \
  AND timestamp >= '$(date +%Y-%m-%d)T06:00:00Z'" \
  --limit 50

# Common errors:
# - "No features available" → Phase 4 failed
# - "Permission denied" → IAM issue
# - "Timeout" → Workers too slow
```

**6. Execute Fix (5-15 min)**

**For Phase 4 failure:**

```bash
# Verify Phase 4 completed
bq query "SELECT COUNT(*) FROM ml_feature_store_v2 WHERE game_date = CURRENT_DATE()"
# Expected: 450 rows
# If 0: Run Phase 4 manually (see Phase 4 incident response)
```

**For permission issue:**

```bash
# Grant necessary permissions
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:prediction-worker@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/bigquery.dataEditor"
```

**For worker code issue:**

```bash
# Rollback to previous working version
gcloud run services update prediction-worker \
  --image gcr.io/nba-props-platform/prediction-worker:previous-working-tag \
  --region us-central1
```

**7. Re-trigger Predictions (1 min)**

```bash
# Trigger coordinator manually
gcloud scheduler jobs run phase5-daily-predictions-trigger \
  --location us-central1

# Or use coordinator API
curl -X POST https://prediction-coordinator-xxx.run.app/start \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "'$(date +%Y-%m-%d)'"}'
```

**8. Verify Fix (2 min)**

```bash
# Wait 5 minutes, then check predictions
sleep 300

bq query "SELECT COUNT(*) as predictions FROM player_prop_predictions WHERE game_date = CURRENT_DATE()"
# Expected: 2,250 (single line) or 11,250 (multi-line)
```

**9. Communicate Resolution (2 min)**

```
# Slack #nba-props-incidents
"RESOLVED: P0 predictions restored. Root cause: [X].
Predictions available at [time].
Phase 6 publishing can proceed."

# Resolve PagerDuty incident
```

**Total Response Time:** 15-30 minutes

---

### P1 Incident: Partial Predictions

**Symptoms:**
- <90% of expected players have predictions
- Some systems failed
- Warning alert in Slack

**Response Procedure:**

Similar to P0, but:
- Identify which players/systems missing
- Re-run only failed players (if possible)
- Proceed with Phase 6 using partial data

---

### P2 Incident: Degraded Performance

**Symptoms:**
- Predictions took >10 minutes
- Workers timing out
- High latency alerts

**Response Procedure:**
- Check Cloud Run metrics (CPU, memory)
- Review slow queries in BigQuery
- Consider scaling adjustments

---

## 📋 Operational Procedures {#operational-procedures}

### Daily Morning Checklist (9:30 AM ET)

**Step 1: Verify Worker Execution (2 minutes)**

```bash
# Check Cloud Run service status
gcloud run services describe prediction-worker \
  --region us-central1 \
  --format="table(status.conditions)"

# Expected: All conditions "True" (Ready, RoutesReady, ConfigurationsReady)
```

```sql
-- Quick health check
SELECT
  'Worker Predictions' as check_name,
  COUNT(DISTINCT player_lookup) as players,
  COUNT(DISTINCT system_id) as systems,
  COUNT(*) as total_predictions,
  MAX(created_at) as last_prediction_time,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(created_at), HOUR) as hours_ago
FROM `nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE();
```

**Expected:**
- `players`: 100-450 (depends on game schedule)
- `systems`: 5
- `total_predictions`: 500-2,250 (single line mode)
- `hours_ago`: 12-15 hours (ran at 6 AM)

**Step 2: Check System Coverage (1 minute)**

```sql
-- Verify all 5 systems ran
SELECT
  system_id,
  COUNT(DISTINCT player_lookup) as players,
  COUNT(*) as predictions,
  AVG(confidence_score) as avg_confidence
FROM `nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
GROUP BY system_id
ORDER BY system_id;
```

**Expected:** 5 rows (one per system), all with similar player counts

**Step 3: Review Alerts (2 minutes)**

Check Slack #nba-props-alerts for:
- [ ] No critical alerts (🚨)
- [ ] Review any warnings (⚠️)
- [ ] Acknowledge incidents

**Step 4: Sample Predictions (2 minutes)**

```sql
-- Spot check a popular player
SELECT
  system_id,
  predicted_points,
  confidence_score,
  recommendation,
  line_margin
FROM `nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
  AND player_lookup = 'lebron-james'  -- Or any active star
ORDER BY system_id;
```

**Expected:** 5 predictions, reasonable values (20-30 points for LeBron)

**Total Time:** ~7 minutes

---

### Weekly Review (Monday, 10 AM ET)

**Step 1: Worker Performance (5 minutes)**

```sql
-- Last 7 days processing stats
WITH daily_stats AS (
  SELECT
    game_date,
    COUNT(DISTINCT player_lookup) as players,
    COUNT(*) as predictions,
    COUNT(DISTINCT system_id) as systems,
    MIN(created_at) as first_prediction,
    MAX(created_at) as last_prediction
  FROM `nba_predictions.player_prop_predictions`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY game_date
)
SELECT
  game_date,
  players,
  predictions,
  systems,
  TIMESTAMP_DIFF(last_prediction, first_prediction, SECOND) / 60.0 as duration_minutes
FROM daily_stats
ORDER BY game_date DESC;
```

**Look for:**
- Duration trend (should be 2-5 minutes consistently)
- Missing days (no games on off days is normal)
- System count (should always be 5)

**Step 2: System Success Rates (5 minutes)**

```sql
-- System reliability over last 7 days
WITH system_coverage AS (
  SELECT
    game_date,
    system_id,
    COUNT(DISTINCT player_lookup) as players
  FROM `nba_predictions.player_prop_predictions`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY game_date, system_id
),
daily_totals AS (
  SELECT
    game_date,
    MAX(players) as max_players_any_system
  FROM system_coverage
  GROUP BY game_date
)
SELECT
  sc.system_id,
  COUNT(*) as days_active,
  AVG(sc.players * 100.0 / dt.max_players_any_system) as avg_coverage_pct
FROM system_coverage sc
JOIN daily_totals dt ON sc.game_date = dt.game_date
GROUP BY sc.system_id
ORDER BY avg_coverage_pct DESC;
```

**Expected:**
- All 5 systems: 7 days active, >95% coverage
- If <95%: Investigate system failures

**Step 3: Cloud Run Metrics (10 minutes)**

```bash
# Check instance scaling patterns
gcloud logging read "resource.type=cloud_run_revision \
  AND resource.labels.service_name=prediction-worker \
  AND timestamp >= '$(date -d '7 days ago' +%Y-%m-%d)'" \
  --limit 1000 \
  --format json | jq -r '.[].jsonPayload.instance_id' | sort | uniq -c

# Expected: 15-25 unique instances over 7 days (scaling working)

# Check for errors
gcloud logging read "resource.type=cloud_run_revision \
  AND resource.labels.service_name=prediction-worker \
  AND severity >= ERROR \
  AND timestamp >= '$(date -d '7 days ago' +%Y-%m-%d)'" \
  --limit 100

# Expected: <10 errors per week (occasional failures OK)
```

**Total Time:** ~20 minutes

---

## 📊 Monitoring & Health Checks {#monitoring}

### Key Metrics to Monitor

**Processing Performance:**

```sql
-- Daily performance summary
CREATE OR REPLACE VIEW `nba_analytics.phase5_performance_daily` AS
WITH prediction_timing AS (
  SELECT
    DATE(created_at) as game_date,
    MIN(created_at) as first_prediction_time,
    MAX(created_at) as last_prediction_time,
    COUNT(DISTINCT player_lookup) as players_processed,
    COUNT(*) as total_predictions,
    COUNT(DISTINCT system_id) as systems_run
  FROM `nba_predictions.player_prop_predictions`
  WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  GROUP BY DATE(created_at)
)
SELECT
  game_date,
  first_prediction_time,
  last_prediction_time,
  TIMESTAMP_DIFF(last_prediction_time, first_prediction_time, SECOND) / 60.0 as processing_duration_minutes,
  players_processed,
  total_predictions,
  systems_run,
  CASE
    WHEN TIMESTAMP_DIFF(last_prediction_time, first_prediction_time, SECOND) / 60.0 < 3 THEN '🟢 EXCELLENT'
    WHEN TIMESTAMP_DIFF(last_prediction_time, first_prediction_time, SECOND) / 60.0 < 5 THEN '🟡 GOOD'
    WHEN TIMESTAMP_DIFF(last_prediction_time, first_prediction_time, SECOND) / 60.0 < 8 THEN '🟠 SLOW'
    ELSE '🔴 CRITICAL'
  END as performance_status
FROM prediction_timing
ORDER BY game_date DESC;
```

### CLI Monitoring Tools

**Daily Health Check Script:**

```bash
#!/bin/bash
# scripts/check_phase5_health.sh
# Run at 7 AM to check Phase 5 completion

GAME_DATE=${1:-$(date +%Y-%m-%d)}

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Phase 5 Health Check: $GAME_DATE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Check 1: Processing Duration
echo ""
echo "1. Processing Performance:"
bq query --use_legacy_sql=false --format=pretty <<SQL
SELECT
  game_date,
  FORMAT_TIMESTAMP('%H:%M:%S', first_prediction_time) as start_time,
  FORMAT_TIMESTAMP('%H:%M:%S', last_prediction_time) as end_time,
  ROUND(processing_duration_minutes, 2) as duration_min,
  players_processed,
  total_predictions,
  performance_status
FROM \`nba_analytics.phase5_performance_daily\`
WHERE game_date = '$GAME_DATE'
SQL

# Check 2: System Coverage
echo ""
echo "2. System Coverage:"
bq query --use_legacy_sql=false --format=pretty <<SQL
SELECT
  system_id,
  COUNT(DISTINCT player_lookup) as players,
  AVG(confidence_score) as avg_confidence
FROM \`nba_predictions.player_prop_predictions\`
WHERE game_date = '$GAME_DATE'
GROUP BY system_id
ORDER BY players DESC
SQL

# Check 3: Missing Players
echo ""
echo "3. Missing Players:"
bq query --use_legacy_sql=false --format=pretty <<SQL
SELECT COUNT(*) as missing_count
FROM \`nba_analytics.upcoming_player_game_context\`
WHERE game_date = '$GAME_DATE'
  AND player_lookup NOT IN (
    SELECT DISTINCT player_lookup
    FROM \`nba_predictions.player_prop_predictions\`
    WHERE game_date = '$GAME_DATE'
  )
SQL

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
```

---

## 🔧 Manual Operations Runbook {#runbook}

### Manual Trigger: Coordinator

**Trigger full Phase 5 batch for today:**

```bash
# Via Cloud Scheduler
gcloud scheduler jobs run phase5-daily-predictions-trigger \
  --location us-central1

# Via curl (with auth)
curl -X POST https://prediction-coordinator-xxx.run.app/start-daily-predictions \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{}'
```

**Trigger for specific date:**

```bash
curl -X POST https://prediction-coordinator-xxx.run.app/start-daily-predictions \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2025-11-07"}'
```

### Manual Trigger: Individual Player

**Re-run predictions for specific player:**

```bash
# Publish message directly to Pub/Sub
gcloud pubsub topics publish prediction-request \
  --message '{"player_lookup":"lebron-james","game_date":"2025-11-07","opening_line":25.5,"line_values":[23.5,24.5,25.5,26.5,27.5],"opponent_team_abbr":"GSW","is_home":true,"feature_version":"v1_baseline_25"}'
```

### Check Coordinator Status

```bash
# Get latest coordinator run logs
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=phase5-prediction-coordinator" \
  --limit 10 \
  --format json | jq '.[].jsonPayload.message'

# Check coordinator execution history
gcloud run jobs executions list \
  --job phase5-prediction-coordinator \
  --region us-central1 \
  --limit 10
```

### Check Worker Status

```bash
# Get worker logs for today
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=phase5-prediction-worker AND timestamp >= '2025-11-07T06:00:00Z'" \
  --limit 50 \
  --format json

# Check worker instance count
gcloud run revisions list \
  --service phase5-prediction-worker \
  --region us-central1 \
  --platform managed
```

### Check Pub/Sub Queue

```bash
# Check pending messages in worker subscription
gcloud pubsub subscriptions describe phase5-prediction-worker-sub

# Purge messages (if needed)
gcloud pubsub subscriptions seek phase5-prediction-worker-sub \
  --time=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
```

### Check DLQ

```bash
# Pull failed messages from DLQ
gcloud pubsub subscriptions pull prediction-worker-dlq-sub \
  --limit 10 \
  --auto-ack

# Query DLQ in BigQuery (if exporting to BQ)
bq query --use_legacy_sql=false "
SELECT
  JSON_EXTRACT_SCALAR(data, '$.player_lookup') as player,
  JSON_EXTRACT_SCALAR(data, '$.error') as error
FROM \`nba_logs.pubsub_dlq_messages\`
WHERE topic_name = 'prediction-worker-dlq'
  AND DATE(publish_time) = CURRENT_DATE()
"
```

### Verify Predictions Written

```bash
# Check prediction count
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total_predictions,
  COUNT(DISTINCT player_lookup) as players,
  COUNT(DISTINCT system_id) as systems
FROM \`nba_predictions.player_prop_predictions\`
WHERE game_date = CURRENT_DATE()
"

# Expected: 11,250 predictions, 450 players, 5 systems
```

### Find Missing Players

```sql
-- Identify players without predictions
SELECT DISTINCT player_lookup
FROM `nba_analytics.upcoming_player_game_context`
WHERE game_date = CURRENT_DATE()
  AND player_lookup NOT IN (
    SELECT DISTINCT player_lookup
    FROM `nba_predictions.player_prop_predictions`
    WHERE game_date = CURRENT_DATE()
  )
```

### Rollback Services

```bash
# Rollback coordinator to previous version
gcloud run jobs update phase5-prediction-coordinator \
  --image gcr.io/nba-props-platform/prediction-coordinator:previous-tag \
  --region us-central1

# Rollback worker to previous version
gcloud run services update phase5-prediction-worker \
  --image gcr.io/nba-props-platform/prediction-worker:previous-tag \
  --region us-central1
```

---

## 🔔 Alert Rules {#alert-rules}

### Critical Alerts (PagerDuty)

| Rule | Severity | Action |
|------|----------|--------|
| Phase 5 fails all retries | 🔴 CRITICAL | Page on-call |
| 0 predictions on game day | 🔴 CRITICAL | Page on-call |
| Coordinator timeout (>5 min) | 🔴 CRITICAL | Page on-call |
| >50 players missing predictions | 🔴 CRITICAL | Page on-call |

### Warning Alerts (Slack)

| Rule | Severity | Action |
|------|----------|--------|
| Processing duration >5 min | 🟡 WARNING | Slack #nba-props-alerts |
| <5 systems running | 🟡 WARNING | Slack |
| Feature quality <70 avg | 🟡 WARNING | Slack |
| >10 workers timeout | 🟡 WARNING | Slack |

---

## 🔗 Related Documentation {#related-docs}

**Phase 5 Docs:**
- **Operations Guide:** `09-phase5-operations-guide.md` - Coordinator/worker configuration
- **Scheduling Strategy:** `10-phase5-scheduling-strategy.md` - Cloud Scheduler, dependency management
- **Worker Deep-Dive:** `12-phase5-worker-deepdive.md` - Model loading, performance optimization

**Upstream Dependencies:**
- **Phase 4 Troubleshooting:** `07-phase4-troubleshooting.md` - Feature generation issues
- **Phase 3 Troubleshooting:** `04-phase3-troubleshooting.md` - Upcoming context issues

**Infrastructure:**
- **Pub/Sub Verification:** `docs/infrastructure/01-pubsub-integration-verification.md`
- **Monitoring:** `docs/monitoring/01-grafana-monitoring-guide.md`

---

**Last Updated:** 2025-11-15 17:00 PST
**Next Review:** After first Phase 5 production incident
**Status:** Draft - Ready for implementation review
