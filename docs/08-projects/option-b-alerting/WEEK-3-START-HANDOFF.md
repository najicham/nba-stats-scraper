# Week 3 Start - Handoff Document

**Created:** 2026-01-17
**For:** New chat session starting Week 3 implementation
**Previous Session:** Session 83 (Week 2 implementation)

---

## Quick Start Command

```
I'm ready to start Week 3 of Option B: NBA Alerting & Monitoring.

Read the context from: docs/08-projects/option-b-alerting/WEEK-3-START-HANDOFF.md

Week 2 is complete. Week 3 focus: Dashboards & Visibility.
```

---

## What Was Completed in Week 2

### ✅ Deployed & Tested

**Service Revision:** `prediction-worker-00060-wkn`
**Service URL:** `https://prediction-worker-f7p3g7f6ya-wl.a.run.app`
**Region:** us-west2

**New Endpoints (all working):**
- `GET /health/deep` - Deep health validation (4 dependency checks)
- `POST /internal/check-env` - Environment variable monitoring
- `POST /internal/deployment-started` - Deployment grace period

**Infrastructure Deployed:**
- Cloud Scheduler: `nba-env-var-check-prod` (runs every 5 minutes)
- Log-based metric: `nba_env_var_changes`
- Alert policy: `[WARNING] NBA Environment Variable Changes`
- GCS baseline: `gs://nba-scraped-data/env-snapshots/nba-prediction-worker-env.json`

**Key Achievement:**
- CatBoost incident detection: 3 days → 5 minutes (864x faster)

---

## Week 3 Objectives (10-12 hours)

### Objective 1: Cloud Monitoring Dashboards (4 hours)

**What to Build:**

1. **Prediction Metrics Dashboard**
   - Prediction request rate (requests/minute)
   - Response latency (P50, P95, P99 percentiles)
   - Fallback prediction rate with alert threshold line
   - Model loading success/failure counts
   - Active alerts list

2. **Data Pipeline Health Dashboard**
   - Feature generation completion rate
   - Feature quality score trends
   - BigQuery query performance
   - Pub/Sub message throughput
   - DLQ depth over time

3. **Model Performance Dashboard**
   - Prediction accuracy by system
   - Confidence score distribution
   - System agreement scores
   - Circuit breaker status
   - Top predictions by confidence

**Implementation Guide:**
- Dashboard config: JSON format for `gcloud monitoring dashboards create`
- Metrics source: Cloud Run metrics + log-based metrics from Week 1/2
- Auto-refresh: 1 minute intervals
- Shareable links for team access

**File to Create:**
- `bin/alerts/nba_monitoring_dashboard.json` (dashboard config)
- `bin/alerts/create_dashboards.sh` (deployment script)

---

### Objective 2: Daily Prediction Summaries to Slack (4 hours)

**What to Build:**

A Cloud Function that runs daily at 9 AM ET via Cloud Scheduler and sends a Slack summary.

**Summary Content:**
```
🏀 NBA Predictions Daily Summary - [Date]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 Yesterday's Stats
• Predictions Generated: 2,250 (450 players × 5 systems)
• Systems Operational: 5/5 ✅
• Average Confidence: 87.2%
• Fallback Rate: 1.2% ✅

🎯 Top 5 Picks (by confidence)
1. LeBron James OVER 26.5 (94.3% conf)
2. Stephen Curry OVER 24.5 (93.8% conf)
3. ...

⚠️ System Health
• Model Loading: ✅ All operational
• Feature Quality: ✅ 97.3% avg
• Circuit Breakers: ✅ All closed
• Alerts (24h): 0 🎉

🔗 Links
• Dashboard: [link]
• Logs: [link]
• Predictions: [BigQuery link]
```

**Implementation:**
- Cloud Function (Python): Queries BigQuery for stats
- Cloud Scheduler: Runs daily at 9 AM ET
- Slack webhook: Uses existing `SLACK_WEBHOOK_URL` from Secret Manager
- Format: Slack blocks for rich formatting

**Files to Create:**
- `bin/alerts/daily_summary/main.py` (Cloud Function code)
- `bin/alerts/daily_summary/requirements.txt` (dependencies)
- `bin/alerts/deploy_daily_summary.sh` (deployment script)

**BigQuery Queries Needed:**
```sql
-- Yesterday's prediction count
SELECT COUNT(*) FROM nba_predictions.player_prop_predictions
WHERE created_at >= CURRENT_DATE() - 1 AND created_at < CURRENT_DATE()

-- Top picks by confidence
SELECT player_lookup, predicted_points, confidence_score, recommendation, current_points_line
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v8' AND created_at >= CURRENT_DATE() - 1
ORDER BY confidence_score DESC LIMIT 5

-- Fallback rate
SELECT COUNTIF(confidence_score = 0.5) / COUNT(*) as fallback_rate
FROM nba_predictions.player_prop_predictions
WHERE created_at >= CURRENT_DATE() - 1
```

---

### Objective 3: Configuration Audit Dashboard (2 hours)

**What to Build:**

Track environment variable changes over time in BigQuery.

**BigQuery Table:** `nba_orchestration.env_var_audit`
```sql
CREATE TABLE nba_orchestration.env_var_audit (
  change_id STRING,
  timestamp TIMESTAMP,
  change_type STRING,  -- ADDED, REMOVED, MODIFIED
  changed_vars ARRAY<STRUCT<var_name STRING, old_value STRING, new_value STRING>>,
  deployer STRING,
  reason STRING,
  deployment_started_at TIMESTAMP
)
```

**Implementation:**
1. Update `env_monitor.py` to log changes to BigQuery (in addition to GCS baseline)
2. Create view: `recent_env_changes` (last 30 days)
3. Add chart to dashboard showing change timeline

**Files to Modify:**
- `predictions/worker/env_monitor.py` (add BigQuery logging)

**Files to Create:**
- `bin/alerts/create_audit_table.sql` (table schema)

---

## Current System State

### Project Configuration
- **GCP Project:** nba-props-platform
- **Region:** us-west2
- **Service:** prediction-worker
- **Service Account:** prediction-worker@nba-props-platform.iam.gserviceaccount.com

### Environment Variables (Production)
```bash
GCP_PROJECT_ID=nba-props-platform
PREDICTIONS_TABLE=nba_predictions.player_prop_predictions
PUBSUB_READY_TOPIC=prediction-ready-prod
CATBOOST_V8_MODEL_PATH=gs://nba-props-platform-models/catboost/v8/catboost_v8_33features_20260108_211817.cbm
```

### Permissions Already Configured
- ✅ BigQuery: dataEditor, dataViewer, jobUser
- ✅ GCS: objectCreator, objectViewer, objectAdmin on nba-scraped-data
- ✅ Pub/Sub: publisher
- ✅ Cloud Scheduler: via service account

### Secrets Available
- `SLACK_WEBHOOK_URL` - In Secret Manager (for daily summaries)
- `BREVO_SMTP_*` - Email alerting (optional)

---

## Files & Documentation Reference

### Implementation Guides
- **Main Guide:** `docs/09-handoff/OPTION-B-NBA-ALERTING-HANDOFF.md`
- **Week 2 Complete:** `docs/08-projects/option-b-alerting/SESSION-83-WEEK-2-IMPLEMENTATION.md`
- **Test Results:** `docs/08-projects/option-b-alerting/WEEK-2-TEST-RESULTS.md`

### Alert Runbooks
- **Location:** `docs/04-deployment/ALERT-RUNBOOKS.md` (2,000+ lines)
- **Week 1 Alerts:** Model loading, fallback rate
- **Week 2 Alerts:** Environment changes, health checks

### Code Locations
- **Worker Code:** `predictions/worker/worker.py`
- **Monitoring Modules:** `predictions/worker/env_monitor.py`, `predictions/worker/health_checks.py`
- **Alert Scripts:** `bin/alerts/setup_env_monitoring.sh`, `bin/alerts/setup_health_monitoring.sh`
- **Dockerfile:** `docker/predictions-worker.Dockerfile`

---

## Known Issues & Notes

### Issue 1: Uptime Check Manual Setup
**Status:** Health check endpoint works, but uptime check needs manual Cloud Console setup
**Reason:** `gcloud monitoring uptime` commands changed in recent SDK
**Workaround:** Documented in `WEEK-2-TEST-RESULTS.md`
**Alternative:** Use Cloud Scheduler pattern (like env monitoring)

### Issue 2: Docker Caching
**Fixed:** Added `--no-cache` flag to `bin/predictions/deploy/deploy_prediction_worker.sh`
**Lesson:** Always test new endpoints immediately after deployment

### Issue 3: Slack Channel for Alerts
**Status:** Alert policies created but Slack channel not configured
**Action:** Manual setup needed via Cloud Console → Monitoring → Notification Channels

---

## Quick Reference Commands

### Deploy Worker
```bash
./bin/predictions/deploy/deploy_prediction_worker.sh prod
```

### Test Endpoints
```bash
# Deep health check
curl https://prediction-worker-f7p3g7f6ya-wl.a.run.app/health/deep | jq .

# Environment check
curl -X POST https://prediction-worker-f7p3g7f6ya-wl.a.run.app/internal/check-env | jq .

# Deployment grace period
curl -X POST https://prediction-worker-f7p3g7f6ya-wl.a.run.app/internal/deployment-started | jq .
```

### View Logs
```bash
gcloud run services logs read prediction-worker \
  --project=nba-props-platform \
  --region=us-west2 \
  --limit=50
```

### Check Scheduler
```bash
# List jobs
gcloud scheduler jobs list --project=nba-props-platform --location=us-west2

# Run env check manually
gcloud scheduler jobs run nba-env-var-check-prod \
  --project=nba-props-platform \
  --location=us-west2
```

### View Metrics
```bash
# List log-based metrics
gcloud logging metrics list --project=nba-props-platform

# List alert policies
gcloud alpha monitoring policies list --project=nba-props-platform
```

---

## Week 3 Implementation Strategy

### Recommended Approach

**Session 1 (4 hours): Dashboards**
1. Research Cloud Monitoring dashboard JSON format
2. Create prediction metrics dashboard
3. Create data pipeline health dashboard
4. Deploy and verify dashboards
5. Document dashboard links in runbooks

**Session 2 (4 hours): Daily Summaries**
1. Create Cloud Function for Slack summary
2. Set up BigQuery queries for stats
3. Configure Cloud Scheduler (9 AM ET daily)
4. Test summary generation
5. Verify Slack webhook delivery

**Session 3 (2 hours): Configuration Audit**
1. Create BigQuery audit table
2. Update env_monitor.py to log changes
3. Create recent_env_changes view
4. Add audit chart to dashboard
5. Test end-to-end

### Success Criteria

- ✅ 3 dashboards created and accessible
- ✅ Daily Slack summary running automatically
- ✅ Environment change audit trail in BigQuery
- ✅ All Week 3 components documented in runbooks
- ✅ Handoff doc created for Week 4 (if continuing)

---

## Tips for New Session

1. **Start Fresh:** This handoff has everything needed - no need to re-read prior sessions
2. **Focus Areas:** Dashboards (JSON), Cloud Functions (Python), BigQuery (SQL)
3. **Testing:** Create dashboards in Cloud Console first, then export JSON config
4. **Slack Format:** Use Slack Block Kit Builder for testing message formatting
5. **Documentation:** Update `ALERT-RUNBOOKS.md` with dashboard links and daily summary info

---

## Contact & Context

**Project:** NBA Props Platform - Alerting & Monitoring (Option B)
**Timeline:** 3-week implementation (Week 2 complete, Week 3 next)
**Total Effort:** Week 2 actual: 8.5 hours (Week 3 estimate: 10-12 hours)

**Documentation Location:** `/docs/08-projects/option-b-alerting/`

**Previous Sessions:**
- Session 82: Week 1 CRITICAL alerts (model loading, fallback rate)
- Session 83: Week 2 WARNING alerts (env monitoring, health checks) ✅ COMPLETE

---

## Ready to Start Week 3?

Use this prompt in your new session:

```
I'm ready to start Week 3 of Option B: NBA Alerting & Monitoring.

Context: Read docs/08-projects/option-b-alerting/WEEK-3-START-HANDOFF.md

Week 2 is complete (env monitoring & health checks deployed and tested).
Week 3 focus: Build Cloud Monitoring dashboards, daily Slack summaries,
and configuration audit tracking.

Let's start with Objective 1: Cloud Monitoring Dashboards.
```

Good luck! 🚀
