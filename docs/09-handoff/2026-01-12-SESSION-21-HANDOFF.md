# Session 21 Handoff - January 12, 2026
**Session Focus:** Long-Term Pipeline Reliability & Self-Healing
**Status:** Planning Phase - Comprehensive Strategy Document
**Priority:** Build robust, self-healing, observable pipeline

---

## Executive Summary

This handoff document provides a comprehensive overview of the NBA predictions pipeline's current state, recent fixes, and a roadmap for achieving long-term reliability with self-healing capabilities, clear error reporting, and full visibility.

### What's Working
- Phase 4 processors: Stale running fix deployed (revision 00037-xj2)
- player_daily_cache: Jan 11 backfilled (199 records)
- Odds data: Accumulating for today (396 records and growing)
- Core pipeline: All phases operational

### What Needs Attention
- **196 stuck running records** across multiple processors (need Layer 2 cleanup)
- **Slack webhook invalid** (404) - all alerting disabled
- **No automated stale cleanup** - manual intervention still required
- **Sportsbook tracking untested** - needs 24h of data to verify

---

## Current System State

### Data Pipeline Status
| Component | Date | Records | Status |
|-----------|------|---------|--------|
| player_daily_cache | 2026-01-12 | 0 | Pending (games not played) |
| player_daily_cache | 2026-01-11 | 199 | ✅ OK |
| player_daily_cache | 2026-01-10 | 103 | ✅ OK |
| odds_api_player_points_props | 2026-01-12 | 396 | ✅ Accumulating |
| odds_api_player_points_props | 2026-01-11 | 3797 | ✅ OK |

### Service Revisions
| Service | Revision | Last Updated | Key Changes |
|---------|----------|--------------|-------------|
| nba-phase4-precompute-processors | 00037-xj2 | Jan 12, 2026 | Stale running fix + error logging |
| prediction-coordinator | 00034-scr | Jan 12, 2026 | Sportsbook fallback chain fix |
| prediction-worker | 00031-gj6 | Jan 12, 2026 | Line source tracking |

### Stuck Running Records (Critical - Needs Cleanup)
```
2026-01-12: BasketballRefRosterProcessor (103 stuck)
2026-01-12: OddsGameLinesProcessor (29 stuck)
2026-01-12: NbacScheduleProcessor (11 stuck)
2026-01-12: NbacInjuryReportProcessor (10 stuck)
2026-01-12: BdlLiveBoxscoresProcessor (9 stuck)
... and more (total ~196 stuck records)
```

These records are not blocking the pipeline (Layer 1 fix handles this), but they clutter the database and should be cleaned up by Layer 2.

---

## Recent Fixes (Sessions 19-20)

### Session 19: Sportsbook Table Bug Fix
**Problem:** Sportsbook fallback chain querying non-existent table.
**Fix:** Changed `odds_player_props` → `odds_api_player_points_props` in `player_loader.py`
**Status:** Deployed, needs 24h to verify sportsbook tracking works

### Session 20: Stale Running Fix (Layer 1)
**Problem:** Processors crash without updating status, leaving `status='running'` forever, blocking downstream processors.
**Fix:** Modified `check_upstream_processor_status()` to treat running >4 hours as "stale", allowing processing to continue.
**Status:** Deployed and verified working

### Session 20: BigQuery Schema Fix
**Problem:** 12 source tracking columns missing from `player_daily_cache` table.
**Fix:** Added columns via ALTER TABLE statement.
**Status:** Complete, Jan 11 backfilled successfully

---

## Long-Term Reliability Strategy

### The Three-Layer Defense Model

```
┌─────────────────────────────────────────────────────────────────┐
│                    LAYER 3: OBSERVABILITY                        │
│  • Dashboard: Pipeline health at a glance                        │
│  • Alerts: Slack notifications for failures                      │
│  • Logs: Structured logging with context                         │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    LAYER 2: SELF-HEALING                         │
│  • Stale cleanup job: Mark old "running" as "failed"            │
│  • Self-heal function: Re-trigger failed phases                  │
│  • DLQ monitor: Process failed messages                          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    LAYER 1: GRACEFUL DEGRADATION                 │
│  • Stale running detection: Treat >4h as stale ✅ DEPLOYED      │
│  • Defensive checks: Verify upstream data before processing     │
│  • Circuit breakers: Prevent cascading failures                  │
└─────────────────────────────────────────────────────────────────┘
```

### Current Implementation Status

| Layer | Component | Status | Priority |
|-------|-----------|--------|----------|
| Layer 1 | Stale running detection | ✅ DEPLOYED | Critical |
| Layer 1 | Defensive data checks | ✅ Working | Critical |
| Layer 2 | Stale cleanup job | ❌ NOT IMPLEMENTED | High |
| Layer 2 | Self-heal function | ⚠️ EXISTS, needs verification | Medium |
| Layer 2 | DLQ monitor | ✅ DEPLOYED | Medium |
| Layer 3 | Slack alerting | ❌ BROKEN (webhook 404) | High |
| Layer 3 | Daily health summary | ⚠️ Deployed, no Slack | Medium |
| Layer 3 | Pipeline health dashboard | ❌ NOT IMPLEMENTED | Low |

---

## Immediate Action Items (Priority Order)

### P0: Critical - Do First

#### 1. Implement Layer 2 Stale Cleanup Job
**Why:** 196 stuck running records cluttering database, will keep growing
**What:** Create Cloud Function that runs every 30 min to mark stale records as failed
**How:**
```sql
UPDATE `nba_reference.processor_run_history`
SET status = 'failed',
    errors = 'stale_running_cleanup: marked as failed after 4+ hours stuck in running state'
WHERE status = 'running'
  AND started_at < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 4 HOUR)
```
**Files to create:**
- `orchestration/cloud_functions/stale_running_cleanup/main.py`
- `orchestration/cloud_functions/stale_running_cleanup/requirements.txt`
- `bin/deploy/deploy_stale_cleanup.sh`

#### 2. Fix Slack Webhook
**Why:** All alerting is disabled, no visibility into failures
**What:** Create new webhook URL, update .env, redeploy functions
**How:**
1. Go to https://api.slack.com/apps
2. Create new webhook for #alerts channel
3. Update `.env`: `SLACK_WEBHOOK_URL=https://hooks.slack.com/services/NEW/URL/HERE`
4. Redeploy:
```bash
source .env
./bin/deploy/deploy_daily_health_summary.sh --skip-scheduler
./bin/orchestrators/deploy_phase4_timeout_check.sh --skip-scheduler
./bin/orchestrators/deploy_phase4_to_phase5.sh
```

### P1: High Priority

#### 3. Verify Sportsbook Tracking
**Why:** Session 19 fix deployed, need to confirm it works
**When:** After 24h (Jan 13)
**How:**
```sql
SELECT
    sportsbook,
    line_source_api,
    COUNT(*) as predictions,
    ROUND(100.0 * SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) / COUNT(*), 1) as win_rate
FROM nba_predictions.prediction_accuracy pa
JOIN nba_predictions.player_prop_predictions p
    ON pa.prediction_id = p.prediction_id
WHERE p.created_at >= '2026-01-13'
    AND p.sportsbook IS NOT NULL
GROUP BY 1, 2
ORDER BY win_rate DESC;
```

#### 4. Verify Self-Heal Function
**Why:** Exists but unclear if working correctly
**How:**
```bash
# Check logs
gcloud functions logs read self-heal-check --region us-west2 --limit 20

# Manual trigger
curl -X GET "https://self-heal-check-f7p3g7f6ya-wl.a.run.app"
```

### P2: Medium Priority

#### 5. Add Registry Automation Monitoring
**Why:** No visibility into registry automation status
**What:** Add checks to daily_health_summary for registry backlog

#### 6. Improve DLQ Monitoring
**Why:** Current monitoring catches messages but doesn't categorize
**What:** Add failure categorization, automatic retry suggestions

### P3: Lower Priority (Defer)

#### 7. E2E Latency Tracking
**Why:** No current latency issues
**What:** Track game_end → predictions_graded time

#### 8. Pipeline Health Dashboard
**Why:** Nice to have, not critical
**What:** Grafana or similar for visualizing pipeline health

---

## Architecture Reference

### Pipeline Flow
```
┌──────────────────────────────────────────────────────────────────────────────┐
│  PHASE 1: SCRAPERS                                                           │
│  Schedule-driven: BDL, ESPN, Basketball-Ref, Odds API, etc.                  │
│  Output: nba_raw.* tables                                                    │
└─────────────────────────────────┬────────────────────────────────────────────┘
                                  ↓ Pub/Sub: scraper-completions
┌──────────────────────────────────────────────────────────────────────────────┐
│  PHASE 2: RAW PROCESSORS                                                     │
│  Event-driven: Process raw data, normalize, validate                         │
│  Output: nba_analytics.* tables                                              │
└─────────────────────────────────┬────────────────────────────────────────────┘
                                  ↓ Pub/Sub: phase-2-completions
┌──────────────────────────────────────────────────────────────────────────────┐
│  PHASE 3: ANALYTICS                                                          │
│  Event-driven: player_game_summary, team_offense_summary, etc.               │
│  Output: nba_analytics.* summary tables                                      │
└─────────────────────────────────┬────────────────────────────────────────────┘
                                  ↓ Pub/Sub: phase-3-completions
┌──────────────────────────────────────────────────────────────────────────────┐
│  PHASE 4: PRECOMPUTE (Where stale running was fixed)                         │
│  5 processors run in parallel:                                               │
│  • team_defense_zone_analysis → player_shot_zone_analysis                    │
│  • player_composite_factors                                                  │
│  • player_daily_cache                                                        │
│  • ml_feature_store                                                          │
│  Completion: Firestore phase4_completion/{date} document                     │
└─────────────────────────────────┬────────────────────────────────────────────┘
                                  ↓ Firestore trigger: phase4-to-phase5
┌──────────────────────────────────────────────────────────────────────────────┐
│  PHASE 5: PREDICTIONS                                                        │
│  • prediction-coordinator: Loads players, creates prediction jobs            │
│  • prediction-worker (8 instances): Runs ML model, writes predictions        │
│  Output: nba_predictions.player_prop_predictions                             │
└─────────────────────────────────┬────────────────────────────────────────────┘
                                  ↓ Pub/Sub: phase-5-completions
┌──────────────────────────────────────────────────────────────────────────────┐
│  PHASE 5B: GRADING (After games complete)                                    │
│  • Checks box scores for actual results                                      │
│  • Grades predictions (correct/incorrect)                                    │
│  Output: nba_predictions.prediction_accuracy                                 │
└─────────────────────────────────┬────────────────────────────────────────────┘
                                  ↓
┌──────────────────────────────────────────────────────────────────────────────┐
│  PHASE 6: EXPORT                                                             │
│  • Exports best bets to GCS bucket                                           │
│  • Powers API/frontend                                                       │
│  Output: gs://nba-props-platform-api/v1/live/today.json                      │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Key Tables
| Dataset | Table | Purpose |
|---------|-------|---------|
| nba_reference | processor_run_history | Track processor status (running/success/failed) |
| nba_precompute | player_daily_cache | Cached player stats for fast predictions |
| nba_raw | odds_api_player_points_props | Betting lines from sportsbooks |
| nba_predictions | player_prop_predictions | Generated predictions |
| nba_predictions | prediction_accuracy | Graded results |

### Key Files
| File | Purpose |
|------|---------|
| `shared/utils/completeness_checker.py` | Defensive checks, stale running detection |
| `data_processors/precompute/precompute_base.py` | Base class for Phase 4 processors |
| `predictions/coordinator/player_loader.py` | Loads player data, sportsbook fallback |
| `orchestration/cloud_functions/self_heal/main.py` | Self-healing trigger |

---

## Monitoring & Alerting Functions

### Currently Deployed Functions
| Function | Schedule | Purpose | Slack Status |
|----------|----------|---------|--------------|
| daily-health-summary | 7 AM ET daily | Morning pipeline health report | ❌ No webhook |
| phase4-timeout-check | */30 * * * * | Catch stuck Phase 4 | ❌ No webhook |
| grading-delay-alert | 10 AM ET daily | Alert if grading missing | ❌ No webhook |
| self-heal-check | */30 * * * * | Re-trigger failed phases | ✅ Works |
| dlq-monitor | Event-driven | Process failed messages | ✅ Works |
| live-freshness-monitor | */3 * * * * | Check live export staleness | ❌ No webhook |

### Health Check Commands
```bash
# Full pipeline health
PYTHONPATH=. python tools/monitoring/check_pipeline_health.py

# Check specific table
PYTHONPATH=. python -c "
from google.cloud import bigquery
client = bigquery.Client()
query = '''
SELECT DATE(cache_date) as date, COUNT(*) as count
FROM nba_precompute.player_daily_cache
WHERE cache_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 5 DAY)
GROUP BY 1 ORDER BY 1 DESC
'''
for row in client.query(query).result():
    print(f'{row.date}: {row.count} records')
"

# Check stuck running
PYTHONPATH=. python -c "
from google.cloud import bigquery
client = bigquery.Client()
query = '''
SELECT processor_name, COUNT(*) as stuck_count
FROM nba_reference.processor_run_history
WHERE status = 'running'
  AND started_at < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 4 HOUR)
GROUP BY 1
ORDER BY 2 DESC
'''
for row in client.query(query).result():
    print(f'{row.processor_name}: {row.stuck_count} stuck')
"
```

---

## Implementation Guide: Layer 2 Stale Cleanup Job

### Step 1: Create the Cloud Function

```python
# orchestration/cloud_functions/stale_running_cleanup/main.py
import functions_framework
from google.cloud import bigquery
from datetime import datetime
import logging
import os

logger = logging.getLogger(__name__)

@functions_framework.http
def cleanup_stale_running(request):
    """
    Clean up processor_run_history records stuck in 'running' state.

    Runs every 30 minutes via Cloud Scheduler.
    Marks records older than 4 hours as 'failed' with cleanup note.
    """
    client = bigquery.Client()
    project = os.environ.get('GCP_PROJECT', 'nba-props-platform')

    # Find and update stale records
    update_query = f"""
    UPDATE `{project}.nba_reference.processor_run_history`
    SET
        status = 'failed',
        errors = CONCAT(
            COALESCE(errors, ''),
            ' | stale_running_cleanup: marked as failed after ',
            CAST(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, HOUR) AS STRING),
            ' hours stuck in running state at ',
            CAST(CURRENT_TIMESTAMP() AS STRING)
        )
    WHERE status = 'running'
      AND started_at < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 4 HOUR)
    """

    # First count how many will be affected
    count_query = f"""
    SELECT COUNT(*) as count
    FROM `{project}.nba_reference.processor_run_history`
    WHERE status = 'running'
      AND started_at < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 4 HOUR)
    """

    count_result = list(client.query(count_query).result())[0]
    stale_count = count_result.count

    if stale_count == 0:
        logger.info("No stale running records found")
        return {"status": "ok", "cleaned": 0, "message": "No stale records"}

    # Execute cleanup
    client.query(update_query).result()

    logger.warning(f"Cleaned up {stale_count} stale running records")

    # Send Slack alert if configured
    webhook_url = os.environ.get('SLACK_WEBHOOK_URL')
    if webhook_url and stale_count > 0:
        import requests
        requests.post(webhook_url, json={
            "text": f"🧹 Stale Running Cleanup: Marked {stale_count} stuck records as failed"
        })

    return {
        "status": "ok",
        "cleaned": stale_count,
        "message": f"Cleaned {stale_count} stale running records",
        "timestamp": datetime.utcnow().isoformat()
    }
```

### Step 2: Deploy Script

```bash
# bin/deploy/deploy_stale_cleanup.sh
#!/bin/bash
set -e

FUNCTION_NAME="stale-running-cleanup"
REGION="us-west2"
PROJECT="nba-props-platform"

# Deploy function
gcloud functions deploy $FUNCTION_NAME \
    --gen2 \
    --runtime python311 \
    --region $REGION \
    --source orchestration/cloud_functions/stale_running_cleanup \
    --entry-point cleanup_stale_running \
    --trigger-http \
    --allow-unauthenticated \
    --set-env-vars "GCP_PROJECT=$PROJECT,SLACK_WEBHOOK_URL=${SLACK_WEBHOOK_URL:-}"

# Create scheduler job
gcloud scheduler jobs create http stale-running-cleanup-job \
    --schedule "*/30 * * * *" \
    --time-zone "America/New_York" \
    --uri "https://${REGION}-${PROJECT}.cloudfunctions.net/${FUNCTION_NAME}" \
    --http-method GET \
    --location $REGION \
    --attempt-deadline 180s \
    2>/dev/null || echo "Scheduler job already exists"

echo "Deployed $FUNCTION_NAME"
```

---

## Quick Reference Commands

### Deploy Commands
```bash
# Phase 4 Processors
./bin/precompute/deploy/deploy_precompute_processors.sh

# Prediction Coordinator
./bin/predictions/deploy/deploy_prediction_coordinator.sh prod

# Cloud Functions
./bin/deploy/deploy_daily_health_summary.sh --skip-scheduler
./bin/orchestrators/deploy_phase4_timeout_check.sh --skip-scheduler
```

### Manual Triggers
```bash
# Trigger player_daily_cache
SERVICE_URL="https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app"
TOKEN=$(gcloud auth print-identity-token)
curl -X POST "$SERVICE_URL/process-date" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"processors": ["PlayerDailyCacheProcessor"], "analysis_date": "2026-01-11"}'

# Trigger self-heal
curl -X GET "https://self-heal-check-f7p3g7f6ya-wl.a.run.app"
```

### View Logs
```bash
# Phase 4 processors
gcloud run services logs read nba-phase4-precompute-processors --region us-west2 --limit 50

# Self-heal function
gcloud functions logs read self-heal-check --region us-west2 --limit 20

# Filter for errors
gcloud logging read 'resource.type="cloud_run_revision" AND severity>=ERROR' --limit 20
```

---

## Files Modified in Recent Sessions

| Session | File | Change |
|---------|------|--------|
| 19 | `predictions/coordinator/player_loader.py` | Fixed sportsbook table name |
| 20 | `shared/utils/completeness_checker.py` | Added stale running handling |
| 20 | `data_processors/precompute/precompute_base.py` | Added BQ error logging |
| 20 | BigQuery schema | Added 12 source tracking columns |

---

## Success Criteria for Long-Term Reliability

### Must Have (Critical)
- [ ] Layer 2 stale cleanup job running every 30 min
- [ ] Slack alerting working for all monitoring functions
- [ ] Zero stuck running records older than 4 hours
- [ ] player_daily_cache generating daily

### Should Have (High)
- [ ] Sportsbook tracking verified working
- [ ] Self-heal function verified triggering correctly
- [ ] Daily health summary sending to Slack

### Nice to Have (Medium)
- [ ] Registry automation monitoring
- [ ] DLQ categorization
- [ ] Pipeline health dashboard

---

## Handoff Checklist

Before ending session, ensure:
- [ ] All code changes committed and pushed
- [ ] Deployments verified working
- [ ] MASTER-TODO.md updated
- [ ] Handoff doc created/updated
- [ ] Any pending items documented

---

*Created: 2026-01-12*
*Last Updated: 2026-01-12 (Session 21 Planning)*
*For questions, see: docs/08-projects/current/pipeline-reliability-improvements/*
