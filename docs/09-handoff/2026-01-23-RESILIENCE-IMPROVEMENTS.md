# Resilience Improvements: Jan 22-23 Incident Post-Mortem

**Date:** 2026-01-23
**Incident:** Complete data gap for Jan 22 games (8 games, 282 player records)
**Resolution Time:** ~2 hours manual intervention

---

## Incident Summary

Jan 22 games were not processed into analytics due to a cascading series of failures:

1. **execute-workflows scheduler job** was pointing to deleted `nba-phase1-scrapers` service
2. When fixed at 7:37 PM PST, the post_game_window time windows had already passed
3. Schedule data showed 3 games still "In Progress" (stale), causing analytics processor to skip
4. Manual intervention required to scrape, update schedule, and run analytics

---

## Root Causes Identified

### 1. Scheduler Job Service Dependencies
**Problem:** 9 scheduler jobs were pointing to a misconfigured/deleted service (`nba-phase1-scrapers`)
**Impact:** Complete workflow execution failure for hours
**Current State:** Fixed manually by updating to `nba-scrapers`

### 2. Stale Schedule Data
**Problem:** `nbac_schedule.game_status` not updated when games finish
**Impact:** `ENABLE_GAMES_FINISHED_CHECK` causes analytics to skip processing
**Current State:** Required manual UPDATE query to fix

### 3. Time Window Sensitivity
**Problem:** Post-game windows have ±30 min tolerance, run hourly at :05
**Impact:** If orchestrator is down during window, games are missed entirely
**Current State:** Must wait until next window or manual intervention

### 4. Distributed Lock Stuck
**Problem:** Firestore workflow_controller lock can get stuck
**Impact:** Prevents all workflow evaluation
**Current State:** TTL auto-expires in 5 minutes (worked as designed)

### 5. No Proactive Alerting
**Problem:** No alerts when data gaps form or workflows stop running
**Impact:** Issues discovered only during manual checks
**Current State:** No automated detection

---

## Recommended Improvements

### High Priority (Prevents Future Incidents)

#### 1. Service Health Dependency Validation
```yaml
# scheduler job should validate target service exists and is healthy
# before enabling/keeping enabled

improvement: scheduler-health-check
description: Add health validation for scheduler target services
implementation:
  - Add daily job that validates all scheduler targets return 200
  - Auto-disable jobs pointing to unhealthy services
  - Alert on any disabled jobs
```

#### 2. Schedule Data Freshness Monitoring
```yaml
improvement: schedule-staleness-alert
description: Alert when game_status is stale
implementation:
  - Monitor for games with status != 3 (Final) more than 4 hours after start_time
  - Auto-trigger schedule refresh when staleness detected
  - Add schedule refresh to morning_recovery workflow
```

#### 3. Workflow Execution Gap Detection
```yaml
improvement: workflow-gap-alert
description: Alert when expected workflows don't run
implementation:
  - Track expected vs actual workflow_decisions per hour
  - Alert if post_game_window_1/2/3 don't show RUN when games are scheduled
  - Dashboard showing workflow execution health
```

#### 4. Data Completeness Monitoring
```yaml
improvement: analytics-completeness-check
description: Detect raw → analytics data gaps
implementation:
  - Scheduled query comparing raw counts to analytics counts
  - Alert when analytics records < 90% of raw records for any date
  - Auto-trigger reprocessing for gaps
```

### Medium Priority (Reduces Manual Intervention)

#### 5. Manual Backfill Endpoint
```yaml
improvement: backfill-endpoint
description: Easy API to reprocess specific dates
implementation:
  - POST /backfill with date range and processor
  - Bypass early exit checks (backfill_mode=True)
  - No API key required for internal access
status: process-date-range endpoint exists but requires API key
```

#### 6. Schedule Auto-Refresh
```yaml
improvement: schedule-auto-refresh
description: Keep schedule data fresh automatically
implementation:
  - Poll BDL/NBA.com for game status updates during game windows
  - Run every 15 min during 7 PM - 2 AM ET
  - Update game_status in nbac_schedule
```

#### 7. Catch-up Workflow Enhancement
```yaml
improvement: catchup-workflow
description: Automatic data gap recovery
implementation:
  - morning_recovery should check last 3 days, not just yesterday
  - Add completeness check before considering recovery "done"
  - Retry processing for any gaps found
```

### Low Priority (Nice to Have)

#### 8. Lock Monitoring Dashboard
```yaml
improvement: lock-dashboard
description: Visibility into distributed locks
implementation:
  - Firestore UI showing all active locks
  - Age of each lock
  - Button to force-release stuck locks
```

#### 9. Scheduler Job Audit
```yaml
improvement: scheduler-audit
description: Regular validation of all scheduler jobs
implementation:
  - Weekly report of all jobs and their target services
  - Flag any jobs with no recent successful runs
  - Document expected vs actual schedules
```

---

## Implementation Priorities

| Priority | Improvement | Effort | Impact |
|----------|-------------|--------|--------|
| P0 | Workflow execution gap detection | Medium | Prevents multi-hour gaps |
| P0 | Data completeness monitoring | Low | Catches gaps early |
| P1 | Schedule staleness alert | Low | Prevents analytics skip |
| P1 | Manual backfill endpoint (fix auth) | Low | Reduces recovery time |
| P2 | Service health dependency validation | Medium | Prevents scheduler issues |
| P2 | Schedule auto-refresh | Medium | Keeps schedule fresh |
| P3 | Catch-up workflow enhancement | Medium | Better recovery |
| P3 | Lock monitoring dashboard | Low | Debugging visibility |

---

## Immediate Actions Taken

1. ✅ Fixed 9 scheduler jobs (pointed to correct service)
2. ✅ Deleted orphaned nba-phase1-scrapers service
3. ✅ Cleared stuck Firestore lock (auto-expired)
4. ✅ Updated stale schedule data (game_status = 3)
5. ✅ Manually scraped Jan 22 player boxscores
6. ✅ Manually ran analytics processor for Jan 21-22
7. ✅ Verified 282 records in player_game_summary for Jan 22

---

## Monitoring Commands (Quick Reference)

```bash
# Check for data gaps
bq query --use_legacy_sql=false '
SELECT
  r.game_date,
  r.raw_records,
  a.analytics_records,
  r.raw_records - COALESCE(a.analytics_records, 0) as gap
FROM (
  SELECT game_date, COUNT(*) as raw_records
  FROM `nba_raw.bdl_player_boxscores`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY 1
) r
LEFT JOIN (
  SELECT game_date, COUNT(*) as analytics_records
  FROM `nba_analytics.player_game_summary`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY 1
) a ON r.game_date = a.game_date
ORDER BY r.game_date DESC'

# Check workflow execution
bq query --use_legacy_sql=false '
SELECT workflow_name, action, reason, decision_time
FROM `nba_orchestration.workflow_decisions`
WHERE workflow_name LIKE "post_game%"
  AND decision_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
ORDER BY decision_time DESC'

# Check for stale games
bq query --use_legacy_sql=false '
SELECT game_date, game_status, COUNT(*) as games
FROM `nba_raw.nbac_schedule`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY 1, 2
ORDER BY 1 DESC, 2'

# Force run analytics locally
PYTHONPATH=. python3 -c "
from data_processors.analytics.player_game_summary.player_game_summary_processor import PlayerGameSummaryProcessor
processor = PlayerGameSummaryProcessor()
processor.run({'start_date': 'YYYY-MM-DD', 'end_date': 'YYYY-MM-DD', 'backfill_mode': True})
"
```

---

## Lessons Learned

1. **Service deletions need scheduler audit** - Before deleting a service, check all scheduler jobs
2. **Time-window workflows are fragile** - Need redundancy for critical windows
3. **Schedule freshness is critical** - Analytics decisions based on stale data cause cascading issues
4. **Manual intervention should be easy** - Having to run Python locally is too slow
5. **Gaps compound quickly** - One missed window affects multiple downstream processors
