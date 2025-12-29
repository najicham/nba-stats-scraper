# Live Data Reliability Project

**Created:** 2025-12-28
**Status:** In Progress
**Priority:** High
**Owner:** Backend Team

---

## Problem Statement

On 2025-12-28, the live data endpoint (`/v1/live/latest.json`) showed yesterday's games instead of today's. This caused:
- Challenge grading to fail (gradeGames found no matching data)
- User confusion (stale data displayed)
- Manual intervention required to fix

**Root causes identified:**
1. Scheduler timing gaps (didn't cover all game start times)
2. No date validation (BDL API returns any active games)
3. No monitoring or alerting for stale data
4. No self-healing for live data specifically

---

## Current State Assessment

### What Exists

| Component | Status | Notes |
|-----------|--------|-------|
| Live export function | ✅ Fixed | Date filtering added, DST handling fixed |
| Schedulers | ✅ Expanded | Now 4 PM - 11 PM ET + 12-1 AM |
| Self-heal function | ⚠️ Partial | Only checks predictions, not live data |
| Notification system | ✅ Exists | Supports Email, Slack, Discord |
| Alert rate limiting | ✅ Exists | Prevents alert storms |
| Monitoring scripts | ⚠️ Partial | No specific live data check |
| Status endpoint | ❌ Missing | Frontend can't verify freshness |
| Health dashboard | ❌ Missing | No visibility into pipeline health |

### Gap Analysis

```
┌─────────────────────────────────────────────────────────────────────┐
│                      RELIABILITY GAPS                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  DETECTION (Know when things break)                                 │
│  ├── ❌ No live data freshness monitoring                           │
│  ├── ❌ No scheduler failure alerting                               │
│  ├── ❌ No BDL API health monitoring                                │
│  └── ⚠️  Generic error alerting exists but not specific            │
│                                                                      │
│  VISIBILITY (See current state)                                     │
│  ├── ❌ No status.json for frontend                                 │
│  ├── ❌ No real-time dashboard                                      │
│  ├── ⚠️  Manual gsutil commands to check                           │
│  └── ⚠️  Logs exist but not aggregated                             │
│                                                                      │
│  RECOVERY (Fix automatically)                                       │
│  ├── ❌ No live data self-healing                                   │
│  ├── ❌ No automatic retry on BDL failure                           │
│  ├── ⚠️  Manual trigger required                                   │
│  └── ⚠️  Self-heal exists but only for predictions                 │
│                                                                      │
│  PREVENTION (Stop issues before they occur)                         │
│  ├── ✅ Date filtering added                                        │
│  ├── ✅ DST handling fixed                                          │
│  ├── ✅ Scheduler expanded                                          │
│  └── ❌ No integration tests                                        │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Improvement Plan

### Phase 1: Critical Improvements (This Week)

#### 1.1 Status Endpoint for Frontend
**Priority:** P0 | **Effort:** 2 hours

Add `/v1/status.json` that frontend can poll to verify data freshness:

```json
{
  "updated_at": "2025-12-28T23:57:26Z",
  "services": {
    "live_data": {
      "status": "healthy",
      "last_update": "2025-12-28T23:57:26Z",
      "games_date": "2025-12-28",
      "games_in_progress": 2,
      "games_final": 4,
      "is_stale": false,
      "next_update_expected": "2025-12-28T23:60:26Z"
    },
    "tonight_data": {
      "status": "healthy",
      "last_update": "2025-12-28T18:00:00Z",
      "predictions_count": 87
    },
    "grading": {
      "status": "healthy",
      "last_graded": "2025-12-28T23:57:26Z"
    }
  },
  "known_issues": [],
  "maintenance_windows": []
}
```

**Benefits:**
- Frontend can show "Data updating..." vs "Data stale"
- Reduces support burden
- Self-documenting health state

#### 1.2 Live Data Freshness Monitor
**Priority:** P0 | **Effort:** 4 hours

Cloud Function that runs every 5 minutes during game hours:

```python
def check_live_data_freshness():
    # 1. Check if games are in progress (NBA API)
    # 2. If yes, verify latest.json updated in last 10 min
    # 3. If stale, trigger self-heal and alert
    # 4. Write status to status.json
```

**Triggers:**
- Every 5 min from 4 PM - 1 AM ET
- Or on-demand via HTTP

#### 1.3 Self-Healing for Live Data
**Priority:** P0 | **Effort:** 2 hours

Extend existing self-heal function to include live data:

```python
def self_heal_live_data(target_date):
    # 1. Check if latest.json is stale
    # 2. If stale, call live-export function
    # 3. Verify fix worked
    # 4. Alert if still broken
```

### Phase 2: Enhanced Monitoring (Next Week)

#### 2.1 Unified Health Dashboard
**Priority:** P1 | **Effort:** 1 day

Create Cloud Monitoring dashboard with:
- Live data freshness (last update time)
- Export success/failure rates
- Scheduler execution status
- BDL API response times
- Error rates by component

#### 2.2 Proactive Alerting
**Priority:** P1 | **Effort:** 4 hours

Add Cloud Monitoring alerts:
- Live data stale > 10 min during games
- Scheduler missed 2+ consecutive runs
- Export error rate > 10%
- BDL API error rate > 5%

#### 2.3 Structured Logging
**Priority:** P2 | **Effort:** 4 hours

Add correlation IDs and structured fields:
```python
logger.info("Live export completed", extra={
    "correlation_id": request_id,
    "target_date": target_date,
    "games_count": len(games),
    "duration_ms": duration,
    "component": "live_export"
})
```

### Phase 3: Testing & Validation (Week 3)

#### 3.1 Unit Tests for Live Export
**Priority:** P1 | **Effort:** 4 hours

Test cases:
- Date filtering logic
- DST handling (test both EST and EDT)
- Empty API response handling
- Malformed data handling

#### 3.2 Integration Tests
**Priority:** P1 | **Effort:** 1 day

End-to-end tests:
- Mock BDL API → verify GCS output
- Test scheduler → function → GCS flow
- Test self-heal trigger

#### 3.3 Synthetic Monitoring
**Priority:** P2 | **Effort:** 4 hours

Cloud Scheduler job that:
- Fetches /v1/live/latest.json
- Verifies schema
- Verifies freshness
- Alerts on issues

### Phase 4: Long-term Improvements (Month 2)

#### 4.1 Dynamic Scheduler
**Priority:** P2 | **Effort:** 2 days

Instead of fixed windows, dynamically schedule based on:
- Today's actual game times (from schedule)
- Start 30 min before first game
- End 3 hours after last game

#### 4.2 Fallback Data Sources
**Priority:** P2 | **Effort:** 1 day

If BDL API fails:
1. Try NBA.com scoreboard API
2. Use BigQuery bdl_live_boxscores table
3. Mark data as "degraded" in status.json

#### 4.3 Staging Environment
**Priority:** P3 | **Effort:** 3 days

Separate environment for testing:
- Different GCS bucket
- Different schedulers
- Test changes before prod

---

## Implementation Checklist

### Phase 1 (This Week)
- [x] Create status.json exporter (`data_processors/publishing/status_exporter.py`)
- [x] Integrate status export into live export function
- [x] Create live data freshness monitor (`orchestration/cloud_functions/live_freshness_monitor/`)
- [x] Create deploy script for freshness monitor
- [x] Add unit tests for date filtering
- [ ] Deploy freshness monitor to GCP
- [ ] Test manually during games
- [ ] Document for frontend team

### Phase 2 (Next Week)
- [ ] Create Cloud Monitoring dashboard
- [ ] Set up alerting policies
- [ ] Add structured logging
- [ ] Create runbook for incidents

### Phase 3 (Week 3)
- [ ] Write unit tests
- [ ] Write integration tests
- [ ] Set up synthetic monitoring
- [ ] Add to CI/CD pipeline

---

## Success Metrics

| Metric | Current | Target | Measurement |
|--------|---------|--------|-------------|
| Data freshness during games | Unknown | > 95% within 5 min | Cloud Monitoring |
| MTTR for stale data | ~1 hour (manual) | < 10 min (auto) | Incident logs |
| False alert rate | N/A | < 5% | Alert logs |
| Frontend awareness of issues | 0% | 100% | status.json polling |

---

## Related Documents

- [Live Data Pipeline Analysis](../LIVE-DATA-PIPELINE-ANALYSIS.md) - Incident analysis
- [Self-Healing Pipeline](../self-healing-pipeline/README.md) - Existing self-heal
- [Observability](../observability/FAILURE-TRACKING-DESIGN.md) - Failure tracking design
- [Email Alerting](../email-alerting/README.md) - Notification system

---

## Appendix: Quick Commands

```bash
# Check live data freshness
gsutil stat gs://nba-props-platform-api/v1/live/latest.json | grep Updated

# View live data game date
gsutil cat gs://nba-props-platform-api/v1/live/latest.json | jq '.game_date, .games_in_progress'

# Manually trigger live export
curl -X POST "https://us-west2-nba-props-platform.cloudfunctions.net/live-export" \
  -H "Content-Type: application/json" \
  -d '{"target_date": "today"}'

# Check scheduler status
gcloud scheduler jobs list --location=us-west2 | grep live

# View recent function logs
gcloud functions logs read live-export --region=us-west2 --limit=20
```
