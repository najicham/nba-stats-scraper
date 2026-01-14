# Monitoring Improvements - TODO List

**Last Updated:** 2026-01-14 (Session 40)

---

## High Priority

### 1. Cloud Monitoring Alert Policy Setup
**Status:** Pending (Manual)
**Effort:** 5 minutes
**Owner:** Manual Cloud Console

The log-based metric exists but the alert policy needs manual setup due to CLI permission issues.

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

### 3. Phase 3 Intermittent 404 Investigation
**Status:** Not Started
**Effort:** 1 hour
**Blocked By:** None

The `/process-date-range` endpoint works now but had 404 errors earlier today. Need to understand why.

**Investigation Steps:**
1. Check Cloud Run logs around 11:30 AM ET:
   ```bash
   gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-phase3-analytics-processors" AND timestamp>="2026-01-14T16:00:00Z" AND timestamp<="2026-01-14T17:00:00Z"' --limit=100
   ```

2. Check if cold start timing issue:
   - Look for startup logs before 404s
   - Check if Flask app initialized properly

3. Check revision traffic routing:
   ```bash
   gcloud run services describe nba-phase3-analytics-processors --region=us-west2 --format="yaml(status.traffic)"
   ```

4. Check scheduler job invocation logs:
   ```bash
   gcloud scheduler jobs describe same-day-phase3 --location=us-west2 --format="yaml(lastAttemptTime,status)"
   ```

**Possible Causes:**
- Cold start delay before Flask routes register
- Revision rollback timing
- DNS/routing cache staleness

---

## Nice to Have

### 4. Proactive Success Rate Alerts
**Status:** Not Started
**Effort:** 2 hours
**Blocked By:** None

Add Cloud Monitoring alerts that fire when phase success rates drop below thresholds.

**Options:**

**Option A: Custom Metric from Health Check**
- Modify `system_health_check.py` to write custom metrics
- Create alert policies on those metrics

**Option B: Log-based Metrics**
- Create log-based metrics from `processor_run_history` logs
- Alert on failure patterns

**Option C: Scheduled Query + Alert**
- BigQuery scheduled query checks success rates
- Pub/Sub notification on threshold breach

**Recommended Thresholds:**
- Phase 2: < 80% success over 1 hour
- Phase 3: < 90% success over 1 hour
- Phase 4: < 85% success over 1 hour
- Phase 5: < 70% success over 1 hour

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

- [x] OIDC validation in system_health_check.py (Session 39)
- [x] cleanup_stuck_processors.py script (Session 39)
- [x] Auth error log-based metric (Session 39)
- [x] West coast date fix for NBA BDL boxscores (Session 40) - `d78d57b`
- [x] Stuck processor cleanup - 25 cleaned (Session 40)
- [x] Phase 3 endpoint verification (Session 40)
- [x] MLB scrapers Pacific Time date logic (Session 40) - `0613a02`
- [x] Session 40 handoff documentation (Session 40) - `2d59800`

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
```
