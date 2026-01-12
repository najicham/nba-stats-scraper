# Pipeline Health Assessment - January 12, 2026

**Date:** January 12, 2026 (1 AM ET)
**Status:** HEALTHY with minor issues
**Assessment Type:** Comprehensive system review

---

## Executive Summary

The NBA prediction pipeline is **generally healthy** with all major components functioning. A few non-critical issues were identified:

| Category | Status | Details |
|----------|--------|---------|
| Backfill (4 seasons) | **HEALTHY** | All seasons have complete data |
| Today's Orchestration | **HEALTHY** | 587 predictions for Jan 11, 905 graded for Jan 10 |
| Live Scoring | **HEALTHY** | Polling every 3 min, 4,530 records for Jan 11 |
| Cloud Scheduler | **HEALTHY** | All NBA jobs enabled and running |
| Phase 4 Tables | **WARNING** | `player_daily_cache` empty (non-critical) |
| Live Export | **WARNING** | 15 days stale (may be disabled) |

---

## Detailed Findings

### 1. Backfill Completeness (4 Seasons)

**Status: COMPLETE**

| Season | Months | Games | Player-Games |
|--------|--------|-------|--------------|
| 2021-2022 | 9 | 1,316 | 3,634 |
| 2022-2023 | 9 | 1,320 | 3,711 |
| 2023-2024 | 9 | 1,318 | 4,017 |
| 2024-2025 | 9 | 1,320 | 3,969 |
| 2025-2026 | 4 | 555 | 2,130 |

Each season has 9 months of data (Oct-June), which is correct for NBA seasons.

**Player Game Summary Coverage:**
```
Year | Records | Unique Dates
2021 | 11,599  | 72 dates
2022 | 28,543  | 213 dates
2023 | 26,529  | 203 dates
2024 | 28,323  | 210 dates
2025 | 33,665  | 217 dates
2026 | 2,128   | 11 dates
```

No gaps detected in recent 14 days.

### 2. Today's Orchestration

**Status: HEALTHY**

| Metric | Value |
|--------|-------|
| Jan 11 Predictions | 587 (10 games) |
| Jan 10 Grading | 905 records |
| Jan 10 Player Summaries | 136 records |
| Jan 10 Games (Final) | 6 games |

Grading ran successfully with 83.7% win rate.

### 3. Live Scoring/Boxscores

**Status: HEALTHY**

| Date | First Poll | Last Poll | Games | Records |
|------|------------|-----------|-------|---------|
| Jan 11 | 9:00 PM | 5:00 AM | 10 | 4,530 |
| Jan 10 | 9:00 PM | 6:42 AM | 6 | 1,933 |
| Jan 9 | 1:03 AM | 6:45 AM | 10 | 6,626 |

Live boxscores are polling every 3 minutes during game hours as expected.

### 4. Cloud Scheduler Jobs

**Status: ALL NBA JOBS ENABLED**

Key jobs running:
- `bdl-live-boxscores-evening` - */3 16-23 * * *
- `bdl-live-boxscores-late` - */3 0-1 * * *
- `grading-daily` - 0 11 * * * (6 AM ET)
- `live-freshness-monitor` - */5 16-23,0-1 * * *
- `execute-workflows` - 5 0-23 * * *
- `master-controller-hourly` - 0 * * * *

MLB jobs are correctly PAUSED.

### 5. Issues Identified

#### Issue 1: `player_daily_cache` Empty (P2 - Low)
- Phase 4 table shows 0 records for today
- **Impact:** Minimal - this table is used for optimization, not core predictions
- **Action:** Monitor, investigate if persists

#### Issue 2: Live Export Stale (P2 - Low)
- Last update: 15 days ago (Dec 28)
- **Impact:** Website may show stale data
- **Action:** Check if intentionally disabled or needs fix

---

## Robustness Recommendations

### Implemented This Session

1. **Phase 4→5 Timeout Alerting** - Added Slack alerts when 4-hour timeout fires
2. **Sportsbook Tracking** - Code changes ready (deploying now)
3. **Performance Documentation** - Updated with sportsbook analysis queries

### Implemented in Follow-up Session (Jan 12)

4. **Phase 4→5 HTTP Error Fix** - `trigger_prediction_coordinator()` no longer raises on failure
5. **Scheduled Phase 4 Staleness Check** - New function checks every 30 min for stuck Phase 4 states
6. **Daily Health Summary Alert** - Morning Slack summary at 7 AM ET with win rate, predictions, issues
7. **Live Freshness Monitor Alerting** - Updated deployment to include SLACK_WEBHOOK_URL

### Recommended Improvements

#### P0 - Critical (This Week) - IMPLEMENTED

1. **Deploy Phase 4→5 Alert Function** ✅
   - File modified: `orchestration/cloud_functions/phase4_to_phase5/main.py`
   - Deployment script updated: `bin/orchestrators/deploy_phase4_to_phase5.sh`
   - Command: `SLACK_WEBHOOK_URL=<url> ./bin/orchestrators/deploy_phase4_to_phase5.sh`

2. **Add Phase 4→5 Scheduled Timeout Check** ✅
   - Created: `orchestration/cloud_functions/phase4_timeout_check/`
   - Deployment: `./bin/orchestrators/deploy_phase4_timeout_check.sh`
   - Runs every 30 minutes, checks for stale states > 4 hours

#### P1 - High (This Sprint) - PARTIALLY IMPLEMENTED

3. **Create Daily Health Summary Alert** ✅
   - Created: `orchestration/cloud_functions/daily_health_summary/`
   - Deployment: `./bin/deploy/deploy_daily_health_summary.sh`
   - Runs at 7 AM ET with win rate, predictions, issues, 7-day trend

4. **Add Outage Detection for Live Scoring** ✅
   - Already implemented in `live_freshness_monitor` with 4-hour critical threshold
   - Updated deployment script to include SLACK_WEBHOOK_URL
   - Redeploy: `SLACK_WEBHOOK_URL=<url> ./bin/deploy/deploy_live_freshness_monitor.sh`

5. **Registry System Automation**
   - 2,099 names pending resolution
   - Create scheduler jobs for:
     - Nightly gamebook → registry
     - Morning roster → registry

#### P2 - Medium (Backlog)

6. **DLQ Monitoring**
   - Pub/Sub dead-letter queues expire silently
   - Add alerting + auto-replay

7. **End-to-End Latency Tracking**
   - Track game_end → predictions_graded time
   - Create `pipeline_execution_log` table

8. **Prediction Quality Score Dashboard**
   - Track confidence calibration over time
   - Detect model drift early

---

## Verification Queries

### Check Today's Status
```bash
PYTHONPATH=. python tools/monitoring/check_pipeline_health.py
```

### Check Backfill Coverage
```sql
SELECT
  EXTRACT(YEAR FROM game_date) as year,
  COUNT(*) as records,
  COUNT(DISTINCT game_date) as dates
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-01'
GROUP BY 1 ORDER BY 1
```

### Check Live Scoring Health
```sql
SELECT
  game_date,
  MIN(poll_timestamp) as first,
  MAX(poll_timestamp) as last,
  COUNT(*) as records
FROM `nba-props-platform.nba_raw.bdl_live_boxscores`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY 1 ORDER BY 1 DESC
```

### Check for Orchestration Errors
```bash
gcloud logging read 'severity>=ERROR AND timestamp>="YYYY-MM-DDT00:00:00Z"' \
  --limit=30 --format="table(timestamp,resource.labels.service_name)" \
  --project=nba-props-platform
```

---

## Conclusion

The pipeline is fundamentally healthy. The recurring "issues every morning" pattern is likely due to:

1. **Detection of old data gaps during backfill runs** - This is expected behavior as we process historical data
2. **Silent failures without alerting** - The Phase 4→5 timeout alert fix addresses this

With the new alerting implemented, visibility should improve significantly. The system is correctly:
- Generating predictions daily
- Grading with 70%+ accuracy
- Polling live data every 3 minutes
- Running all scheduled jobs

**No critical issues require immediate attention.**

---

*Created: January 12, 2026*
*Next Assessment: After Phase 4→5 alert deployment*
