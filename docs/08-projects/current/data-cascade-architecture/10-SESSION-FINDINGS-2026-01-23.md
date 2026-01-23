# Data Cascade Architecture - Session Findings (2026-01-23)

**Session Focus:** System architecture review, scheduler fix, improvement planning
**Date:** 2026-01-23

---

## Executive Summary

This session discovered and fixed a critical scheduler misconfiguration that had broken the master controller since December 20, 2025. Additionally, investigation revealed that **historical data completeness tracking infrastructure already exists** but is not consistently used.

---

## Critical Fix: Scheduler URLs

### Problem Discovered
The Cloud Scheduler jobs for orchestration were pointing to the wrong service:
- `master-controller-hourly` → `nba-phase1-scrapers` (wrong)
- `execute-workflows` → `nba-phase1-scrapers` (wrong)

The service `nba-phase1-scrapers` was misconfigured with analytics-processor code, causing all `/evaluate` and `/execute-workflows` calls to return 404.

### Impact
- Workflow decisions stopped being logged on **December 20, 2025**
- Master controller evaluations not running
- Scrapers still ran via other schedulers (bdl-live-boxscores, etc.) but orchestration was broken

### Fix Applied
```bash
gcloud scheduler jobs update http master-controller-hourly \
  --location=us-west2 \
  --uri="https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/evaluate" \
  --oidc-service-account-email=scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com \
  --oidc-token-audience="https://nba-scrapers-f7p3g7f6ya-wl.a.run.app"

gcloud scheduler jobs update http execute-workflows \
  --location=us-west2 \
  --uri="https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/execute-workflows" \
  --oidc-service-account-email=scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com \
  --oidc-token-audience="https://nba-scrapers-f7p3g7f6ya-wl.a.run.app"
```

### Verification
After fix, workflow decisions resumed logging:
- Jan 22: 266 decisions
- Jan 23: 44+ decisions (session ongoing)

---

## Historical Completeness Tracking - Key Finding

### Infrastructure Already Exists!

The data cascade problem documentation (this project) proposed adding completeness tracking. **This infrastructure already exists:**

#### 1. Validation Module
**Location:** `shared/validation/historical_completeness.py`

```python
def assess_historical_completeness(
    games_found: int,
    games_available: int,
    window_size=10
) -> HistoricalCompletenessResult
```

Returns:
- `games_found`: Actual games retrieved
- `games_expected`: min(games_available, window_size)
- `is_complete`: games_found >= games_expected
- `is_bootstrap`: games_expected < window_size (new player)
- `is_data_gap`: incomplete AND not bootstrap

#### 2. Feature Store Integration
**Location:** `data_processors/precompute/ml_feature_store_v2/ml_feature_store_processor.py`

Lines 967-1069 integrate completeness tracking:
```python
hist_completeness_data = self.feature_extractor.get_historical_completeness_data(player_lookup)
historical_completeness = assess_historical_completeness(
    games_found=hist_completeness_data['games_found'],
    games_available=hist_completeness_data['games_available'],
    contributing_dates=hist_completeness_data['contributing_game_dates'],
    window_size=WINDOW_SIZE
)

# Stored in output record
'historical_completeness': historical_completeness.to_bq_struct(),
```

#### 3. BigQuery Schema
**Table:** `nba_predictions.ml_feature_store_v2`

```sql
historical_completeness STRUCT<
  games_found INT64,
  games_expected INT64,
  is_complete BOOL,
  is_bootstrap BOOL,
  contributing_game_dates ARRAY<DATE>
>
```

### Current State Analysis

Query to check completeness by date:
```sql
SELECT
  game_date,
  COUNT(*) as total_features,
  COUNTIF(historical_completeness.is_complete) as complete,
  COUNTIF(NOT historical_completeness.is_complete AND NOT historical_completeness.is_bootstrap) as data_gaps,
  ROUND(COUNTIF(historical_completeness.is_complete) / COUNT(*) * 100, 1) as complete_pct
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY 1
ORDER BY 1 DESC
```

**Finding:** Most records have NULL values for `historical_completeness`, indicating the processor isn't consistently populating this field.

### Remaining Work

1. **Fix Consistency** - Ensure ml_feature_store_processor.py always populates `historical_completeness`
2. **Add Monitoring** - Daily health check should audit completeness percentages
3. **Filter in Predictions** - Prediction coordinator should filter features where `is_complete = false`
4. **Cascade Detection** - Use `contributing_game_dates` to identify features affected by backfills

---

## MERGE Fix Status

### Background
The MERGE operation was failing with:
```
Schema update options should only be specified with WRITE_APPEND disposition,
or with WRITE_TRUNCATE disposition on a table partition.
```

### Fix Applied (Commit 5f45fea3)
Removed `schema_update_options` from temp table LoadJobConfig in `analytics_base.py`:
```python
job_config = bigquery.LoadJobConfig(
    schema=table_schema,
    source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    autodetect=(table_schema is None),
    # Note: schema_update_options not compatible with WRITE_TRUNCATE on non-partitioned tables
)
```

### Deployment Status
- Service `nba-phase3-analytics-processors` redeployed at 03:21 UTC
- No MERGE attempts since redeployment (waiting for data to flow)
- Next opportunity: post_game_window_2 at 01:00 ET (06:00 UTC)

### Verification Command
```bash
gcloud logging read 'resource.labels.service_name="nba-phase3-analytics-processors" AND textPayload=~"MERGE"' \
  --limit=20 --freshness=6h --format="table(timestamp,textPayload)"
```

**Expected:** Should see "MERGE completed" instead of "MERGE failed...falling back to DELETE + INSERT"

---

## System Architecture Improvements Planned

### P0: Historical Data Completeness (Existing Infrastructure)
- **Status:** Infrastructure exists, needs consistent usage
- **Action:** Fix processor to always populate completeness struct

### P1: Distributed Health Status Cache
- **Purpose:** Real-time ops visibility
- **Design:** Firestore `system_health/live` document
- **Updated by:** Each monitoring function
- **Schema:**
```python
{
  'timestamp': datetime,
  'phase_status': {
    'phase_2': {'completion_pct': 95, 'last_update': datetime},
    'phase_3': {...}, 'phase_4': {...}, 'phase_5': {...}
  },
  'alerts': [],
  'dlq_message_count': 0,
  'data_freshness_hours': 0.5
}
```

### P1: Failure Mode Classification & Auto-Recovery
- **Purpose:** Reduce MTTR
- **Implementation:** Add to DLQ monitor
- **Classification:**
  - HTTP 429 → Transient → Retry with backoff
  - HTTP 404 (game not found) → Permanent → Skip game
  - BigQuery Quota → Transient → Retry in 5 min
  - Auth failure → Permanent → Page oncall

### P2: Scraper Coverage Matrix
- **Purpose:** Track success/failure per scraper per date
- **Table:** `nba_orchestration.scraper_coverage`
- **Populated by:** workflow_executor after each run

### P2: Phase Transition SLA Monitoring
- **Purpose:** Early warning of slowdowns
- **SLA Thresholds:**
  - Phase 2→3: 30 min
  - Phase 3→4: 60 min
  - Phase 4→5: 45 min
  - Phase 5→6: 30 min

---

## Single Points of Failure Identified

| Component | Risk | Current Mitigation |
|-----------|------|-------------------|
| Schedule scraper staleness | Pipeline can't make game-aware decisions | 6-hour threshold + config override |
| BigQuery for workflow decisions | No audit trail if down | Error propagates but no proactive alert |
| Prediction coordinator availability | Features computed but no predictions | Tiered timeout (30m→1h→2h) |
| Master controller scheduler URL | **Fixed this session** | Now points to correct service |

---

## Files Modified This Session

| File | Change |
|------|--------|
| Cloud Scheduler: `master-controller-hourly` | URL updated to nba-scrapers |
| Cloud Scheduler: `execute-workflows` | URL updated to nba-scrapers |

---

## Monitoring Commands for Follow-up

### Check Workflow Decisions
```sql
SELECT workflow_name, action, reason, decision_time
FROM `nba_orchestration.workflow_decisions`
WHERE decision_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
ORDER BY decision_time DESC
```

### Check Historical Completeness Coverage
```sql
SELECT
  game_date,
  COUNTIF(historical_completeness.is_complete IS NOT NULL) as has_completeness,
  COUNT(*) as total
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY 1
ORDER BY 1 DESC
```

### Verify MERGE Working
```bash
gcloud logging read 'resource.labels.service_name="nba-phase3-analytics-processors" AND textPayload=~"MERGE completed"' \
  --limit=5 --freshness=12h
```

---

## Next Session Priorities

1. **Verify MERGE fix** after post_game_window_2 runs (~01:00 ET)
2. **Fix historical_completeness population** in ml_feature_store_processor.py
3. **Add completeness audit** to daily health check
4. **Decommission or fix** `nba-phase1-scrapers` service (currently misconfigured)
