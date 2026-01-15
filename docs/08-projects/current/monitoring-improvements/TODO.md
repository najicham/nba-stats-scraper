# Monitoring Improvements - TODO List

**Last Updated:** 2026-01-14 (Session 45)

---

## High Priority

### 1. Cloud Monitoring Alert Policy Setup
**Status:** Pending (Manual - 5 min)
**Effort:** 5 minutes
**Owner:** Manual Cloud Console

The log-based metric exists but the alert policy needs manual setup due to CLI permission issues (gcloud alpha not installed).

**Metric Details:**
```yaml
name: cloud_run_auth_errors
type: logging.googleapis.com/user/cloud_run_auth_errors
filter: resource.type="cloud_run_revision" AND (textPayload=~"401" OR textPayload=~"403" ...)
kind: DELTA
valueType: INT64
```

**Steps:**
1. Go to Cloud Console > Monitoring > Alerting > Create Policy
2. Add condition:
   - Resource type: `Cloud Run Revision`
   - Metric: `logging.googleapis.com/user/cloud_run_auth_errors`
   - Aggregation: Sum over 5 minutes
   - Threshold: > 10
3. Add notification channel (email/Slack)
4. Set documentation:
   ```
   ## Cloud Run Authentication Error Spike

   ### Possible Causes
   - Pub/Sub subscription missing OIDC
   - Scheduler job with wrong audience
   - Service account permissions revoked

   ### Resolution
   1. Run: python scripts/system_health_check.py --hours=1
   2. Check Pub/Sub OIDC: gcloud pubsub subscriptions describe <name>
   3. Check scheduler audiences: gcloud scheduler jobs describe <name>
   ```

**Verification:**
```bash
gcloud alpha monitoring policies list --filter='displayName~Auth'
```

---

## Medium Priority

### 2. MLB Scrapers Date Logic Fix
**Status:** COMPLETED (Session 40)
**Effort:** 30 minutes
**Blocked By:** None
**Commit:** `0613a02`

Five MLB scrapers use UTC-based date calculation (same bug as NBA BDL boxscores). Need Pacific Time for MLB since many games are PT-based.

**Files to Update:**
```
scrapers/mlb/statcast/mlb_statcast_pitcher.py:111
scrapers/mlb/balldontlie/mlb_pitcher_stats.py:127
scrapers/mlb/balldontlie/mlb_box_scores.py:94
scrapers/mlb/balldontlie/mlb_games.py:91
scrapers/mlb/balldontlie/mlb_batter_stats.py:135
```

**Implementation:**
1. Add `get_yesterday_pacific()` to `scrapers/utils/date_utils.py`:
   ```python
   def get_yesterday_pacific() -> str:
       """Get yesterday's date in Pacific Time (for MLB games)."""
       pt_tz = ZoneInfo("America/Los_Angeles")
       pt_now = datetime.now(pt_tz)
       yesterday = (pt_now - timedelta(days=1)).date()
       return yesterday.isoformat()
   ```

2. Update each MLB scraper to use the new function

**Testing:**
```bash
# Verify logic
python -c "from scrapers.utils.date_utils import get_yesterday_pacific; print(get_yesterday_pacific())"
```

---

### 3. Phase 3 404 Root Cause Analysis
**Status:** COMPLETED (Session 40)
**Root Cause:** Wrong source directory deployed

**Investigation Findings:**

All 404 errors were on revision `00055-mgt`, NOT `00054-ltj`:
```
2026-01-14T14:48:07Z  404  /process-date-range  00055-mgt
2026-01-14T14:47:09Z  404  /process-date-range  00055-mgt
2026-01-14T14:12:43Z  404  /process-date-range  00055-mgt
2026-01-14T11:30:01Z  404  /process-date-range  00055-mgt
```

**Source Archive Size Analysis:**
- Revision 00054: `14.5 MB` (correct - just analytics code)
- Revision 00055: `492.5 MB` (WRONG - entire repo uploaded!)

**Root Cause:**
1. Revision 00055 was deployed from repo root (not analytics directory)
2. The root Procfile runs predictions service, not analytics
3. Predictions service doesn't have `/process-date-range` endpoint
4. Hence the 404 errors

**Timeline:**
- 00054: Created 2026-01-13T23:54:38Z (gcloud 550.0.0) - WORKING
- 00055: Created 2026-01-14T04:50:11Z (gcloud 547.0.0) - BROKEN
- Traffic rolled back to 00054, fixing the issue

**Fix Applied:**
Created `data_processors/analytics/Procfile` to ensure correct Flask app starts:
```
web: gunicorn --bind :$PORT --workers 1 --threads 5 --timeout 600 main_analytics_service:app
```

**Prevention:**
- Always deploy Phase 3 from `data_processors/analytics/` directory
- The new Procfile ensures correct app even if deployed from wrong location

---

## Nice to Have

### 4. Proactive Success Rate Alerts
**Status:** DESIGNED (Ready to Implement)
**Effort:** 30 minutes
**Blocked By:** SLACK_WEBHOOK_URL environment variable

**Finding:** `system_health_check.py` already has Slack integration!

**Current Capabilities (already built):**
- Success rate thresholds: 50% critical, 80% warning
- Phase-by-phase health assessment
- Stuck processor detection
- Noise reduction (expected vs real failures)
- Slack message formatting (lines 643-749)
- `--slack` flag to send reports

**Implementation Plan:**

**Option A: Scheduled Health Check with Slack (Recommended - 30 min)**
```bash
# 1. Set up Slack webhook
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."

# 2. Create scheduler job
gcloud scheduler jobs create http health-check-hourly \
  --location=us-west2 \
  --schedule="0 * * * *" \
  --uri="https://admin-service.../run-health-check" \
  --http-method=POST \
  --message-body='{"slack": true, "hours": 1}'
```

**Option B: Cloud Function Wrapper (1 hour)**
- Create a Cloud Function that runs health check
- Trigger on schedule via Cloud Scheduler
- Send Slack alert only when issues detected

**Thresholds (already configured in system_health_check.py):**
```python
THRESHOLDS = {
    "success_rate_critical": 50.0,  # Below = critical
    "success_rate_warning": 80.0,   # Below = warning
    "stuck_minutes": 15,            # Stuck threshold
}
```

**Quick Test:**
```bash
# Test Slack integration
SLACK_WEBHOOK_URL="your-webhook" python scripts/system_health_check.py --hours=1 --slack
```

---

### 5. DLQ Monitoring Alerts
**Status:** Not Started
**Effort:** 1 hour
**Blocked By:** None

Alert when Dead Letter Queue message count exceeds threshold.

**Implementation:**
```bash
# Create metric
gcloud logging metrics create dlq_messages \
  --description="Messages in Dead Letter Queues" \
  --log-filter='resource.type="pubsub_subscription" AND labels.subscription_id=~"dlq"'

# Create alert policy for > 10 messages
```

---

## Completed

- [x] **OddsAPI Batch Processing** (Session 45) - `124e871` - Reduces processing 60+ min → <5 min
- [x] OIDC validation in system_health_check.py (Session 39)
- [x] cleanup_stuck_processors.py script (Session 39)
- [x] Auth error log-based metric (Session 39)
- [x] West coast date fix for NBA BDL boxscores (Session 40) - `d78d57b`
- [x] Stuck processor cleanup - 25 cleaned (Session 40)
- [x] Phase 3 endpoint verification (Session 40)
- [x] MLB scrapers Pacific Time date logic (Session 40) - `0613a02`
- [x] Session 40 handoff documentation (Session 40) - `08c83dd`
- [x] Phase 3 404 root cause analysis (Session 40) - deployment issue identified
- [x] Phase 3 Procfile fix (Session 40) - prevents future deployment issues
- [x] Proactive alerting design (Session 40) - system_health_check.py already supports Slack
- [x] **Betting lines fix** (Session 41) - Identified root cause: timing + worker bug
- [x] **Prediction Line Enrichment Processor** (Session 41) - Created enrichment post-processor
- [x] **Historical backfill** (Session 41) - Enriched 1,935 predictions (Jan 1-14)
- [x] **Worker v3.5 fix** (Session 41) - Use estimated lines when no prop exists
- [x] **Coordinator deduplication** (Session 41) - Pick latest Phase 3 record per player

---

## Dependencies

```
┌─────────────────────────────────────────────────────────────┐
│                    Monitoring Stack                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Cloud Monitoring                                           │
│  ├── Log-based Metric: cloud_run_auth_errors ✅            │
│  ├── Alert Policy: Auth Error Spike ⏳ (needs setup)       │
│  └── Dashboard: (future)                                    │
│                                                             │
│  Scripts                                                    │
│  ├── system_health_check.py ✅                             │
│  ├── cleanup_stuck_processors.py ✅                        │
│  └── setup_auth_error_alert.sh ✅                          │
│                                                             │
│  Scheduler Jobs                                             │
│  ├── cleanup-processor (every 15 min) ✅                   │
│  ├── stale-running-cleanup-job (every 30 min) ✅           │
│  └── bdl-boxscores-yesterday-catchup (4 AM ET) ✅          │
│                                                             │
│  Date Utilities                                             │
│  ├── get_yesterday_eastern() ✅                            │
│  ├── get_today_eastern() ✅                                │
│  └── get_yesterday_pacific() ⏳ (needs implementation)     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Quick Reference

```bash
# Health check
python scripts/system_health_check.py --hours=12

# Fast health check (no infra)
python scripts/system_health_check.py --hours=1 --skip-infra

# Preview stuck processors
python scripts/cleanup_stuck_processors.py

# Clean stuck processors
python scripts/cleanup_stuck_processors.py --execute

# Check auth metric
gcloud logging metrics describe cloud_run_auth_errors

# Check scheduler job health
gcloud scheduler jobs list --location=us-west2 --format="table(name,state,lastAttemptTime)"

# ===== BETTING LINES ENRICHMENT (Session 41) =====

# Enrich predictions with betting lines for today
python -m data_processors.enrichment.prediction_line_enrichment.prediction_line_enrichment_processor

# Enrich for specific date
python -m data_processors.enrichment.prediction_line_enrichment.prediction_line_enrichment_processor --date 2026-01-15

# Enrich date range
python -m data_processors.enrichment.prediction_line_enrichment.prediction_line_enrichment_processor --start-date 2026-01-01 --end-date 2026-01-14

# Dry run (preview only)
python -m data_processors.enrichment.prediction_line_enrichment.prediction_line_enrichment_processor --date 2026-01-15 --dry-run

# Check line coverage
bq query --use_legacy_sql=false '
SELECT game_date, COUNT(*) as total,
       COUNTIF(current_points_line IS NOT NULL) as with_line,
       ROUND(COUNTIF(current_points_line IS NOT NULL) / COUNT(*) * 100, 1) as pct
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY game_date ORDER BY game_date'
```
