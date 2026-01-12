# Session 20 Handoff - January 12, 2026

**Session Focus:** Pipeline Reliability - Stale Running Fix & BigQuery Save Error Investigation
**Duration:** ~2 hours
**Status:** Partially Complete - Deployment in progress

---

## Executive Summary

This session diagnosed and fixed a critical pipeline blocker where **stale "running" records** in `processor_run_history` were blocking all Phase 4 processors. A secondary **BigQuery save error** was discovered and is under investigation.

### Key Accomplishments
1. **Root Cause Identified**: Stale running records (processors crashed without updating status)
2. **Layer 1 Fix Deployed**: Modified `check_upstream_processor_status()` to handle stale running
3. **Error Logging Added**: Enhanced BigQuery load job error visibility
4. **Deployment In Progress**: Revision 00037 deploying with error logging fix

---

## Problem Statement

### Original Symptom
`player_daily_cache` table had no data for January 11-12, 2026. Health check showed:
```
[FAIL] player_daily_cache: 0 records (today)
```

### Root Cause #1: Stale Running Records (FIXED)
Processors were writing `status='running'` at start but crashing before writing `status='success'` or `status='failed'`. The defensive checks in Phase 4 processors required upstream `status='success'`, causing a cascade of failures.

**Evidence:**
```
⚠️  STALE RUNNING DETECTED: PlayerGameSummaryProcessor on 2026-01-11
has been 'running' for 6.4 hours (threshold: 4h). Run ID: PlayerGameSummaryProcessor_20260112_113008_d1cb5a05
```

### Root Cause #2: BigQuery Save Error (INVESTIGATING)
After fixing stale running, the processor still fails during BigQuery save:
```
google.api_core.exceptions.BadRequest: 400 Error while reading data,
error message: JSON table encountered too many errors, giving up. Rows: 1; errors: 1.
```

Only 1 row out of 199 is causing the failure - likely a field type mismatch.

---

## Fixes Implemented

### Fix 1: Stale Running Handling (Layer 1)

**File:** `shared/utils/completeness_checker.py`

**Change:** Modified `check_upstream_processor_status()` to detect and handle stale running records.

**Key Logic:**
```python
if row.status == 'running':
    age_hours = (now - started_at).total_seconds() / 3600
    if age_hours > stale_threshold_hours:  # Default: 4 hours
        logger.warning(f"⚠️  STALE RUNNING DETECTED: {processor_name}...")
        return {
            'status': 'stale_running',
            'safe_to_process': True,  # Allow downstream to proceed
            'stale_age_hours': age_hours
        }
```

**Deployment:** Revision `nba-phase4-precompute-processors-00036-ldn` (deployed and verified)

**Verification:**
```bash
PYTHONPATH=. python -c "
from datetime import date
from google.cloud import bigquery
from shared.utils.completeness_checker import CompletenessChecker
checker = CompletenessChecker(bigquery.Client(), 'nba-props-platform')
result = checker.check_upstream_processor_status('PlayerGameSummaryProcessor', date(2026, 1, 11))
print(f'Status: {result[\"status\"]}, safe_to_process: {result[\"safe_to_process\"]}')"
```

Expected output: `Status: stale_running, safe_to_process: True`

### Fix 2: Enhanced Error Logging

**File:** `data_processors/precompute/precompute_base.py`

**Change:** Added BigQuery load job error details to exception handler (lines 1459-1471).

**Purpose:** Capture actual field causing the "JSON table encountered too many errors" issue.

**Deployment:** In progress (revision 00037)

---

## Current State

### Deployments
| Component | Revision | Status |
|-----------|----------|--------|
| nba-phase4-precompute-processors | 00037-xj2 | Running (stale fix + error logging) |

### Data State
| Table | Date | Records | Status |
|-------|------|---------|--------|
| player_daily_cache | 2026-01-12 | 0 | Missing |
| player_daily_cache | 2026-01-11 | 0 | Missing |
| player_daily_cache | 2026-01-10 | 103 | OK |
| player_game_summary | 2026-01-11 | 324 | OK |
| player_game_summary | 2026-01-10 | 136 | OK |

### Firestore State
Phase 4 completion for 2026-01-12 shows all 5 processors "completed" but this is misleading - they ran but failed during save:
```
phase4_completion/2026-01-12:
  team_defense_zone_analysis: completed
  player_shot_zone_analysis: completed
  player_composite_factors: completed
  player_daily_cache: completed  # Actually failed during save
  ml_feature_store: completed
  _triggered: True
```

---

## Immediate Next Steps

### Step 1: Wait for Deployment
```bash
# Check deployment status
gcloud run services describe nba-phase4-precompute-processors --region us-west2 \
  --format="value(status.latestReadyRevisionName)"
# Should show 00037-xxx when complete
```

### Step 2: Test player_daily_cache with New Logging
```bash
SERVICE_URL="https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app"
TOKEN=$(gcloud auth print-identity-token)

curl -X POST "$SERVICE_URL/process-date" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"processors": ["PlayerDailyCacheProcessor"], "analysis_date": "2026-01-11"}'
```

### Step 3: Analyze Error from Logs
```bash
gcloud logging read 'resource.type="cloud_run_revision" AND
  resource.labels.service_name="nba-phase4-precompute-processors" AND
  textPayload=~"BigQuery load job errors"' \
  --limit 10 --format=json | jq -r '.[].textPayload'
```

### Step 4: Fix the Specific Field
Once the actual error is identified, fix the field type/format in:
- `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`

### Step 5: Backfill Data
After fixing, run for both dates:
```bash
# Jan 11
curl -X POST "$SERVICE_URL/process-date" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"processors": ["PlayerDailyCacheProcessor"], "analysis_date": "2026-01-11"}'

# Jan 12
curl -X POST "$SERVICE_URL/process-date" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"processors": ["PlayerDailyCacheProcessor"], "analysis_date": "2026-01-12"}'
```

---

## Other Issues Discovered

### 1. No Odds Data for Today
```sql
-- Returns 0 for Jan 12
SELECT COUNT(*) FROM nba_raw.odds_api_player_points_props
WHERE DATE(game_date) = '2026-01-12'
```
- Impact: Predictions use ESTIMATED lines, sportsbook column is NULL
- Action: Investigate odds scraper - no scheduler job found for odds

### 2. Slack Webhook Invalid (404)
- All alerting functions deployed but webhook returns 404
- Affected: `daily-health-summary`, `phase4-timeout-check`, `phase4-to-phase5-orchestrator`
- Fix: Create new webhook at https://api.slack.com/apps

### 3. Live Export Stale (373 hours)
- `today.json` shows Dec 28 data
- Root cause: "No best bets found for 2026-01-12"
- Downstream of player_daily_cache issue

### 4. Batch Reprocess Type Mismatch
```
Query column 9 has type INT64 which cannot be inserted into column
circuit_breaker_until, which has type TIMESTAMP
```
- Has working fallback to individual inserts
- Low priority

---

## Key Files Modified

| File | Changes |
|------|---------|
| `shared/utils/completeness_checker.py` | Added stale running handling to `check_upstream_processor_status()` |
| `data_processors/precompute/precompute_base.py` | Added BigQuery load job error logging |

---

## Architecture Context

### Pipeline Flow
```
Phase 3 (Analytics)
    ↓ writes to processor_run_history (status='success')
Phase 4 (Precompute)
    ↓ checks processor_run_history for upstream status
    ↓ if status='running' for >4h → treat as stale, allow processing
    ↓ writes to nba_precompute.player_daily_cache
Phase 5 (Predictions)
    ↓ loads cache for fast predictions
```

### Defensive Checks in precompute_base.py
1. **DEFENSE 1**: Check upstream processor status (now handles stale running)
2. **DEFENSE 2**: Check for data gaps in lookback window

### Stale Running Pattern
```
Processor starts → writes status='running'
Processor crashes → no status update
Next run → sees 'running', blocks
After 4h → Layer 1 fix treats as 'stale_running', allows processing
```

---

## Useful Commands

### Check Pipeline Health
```bash
PYTHONPATH=. python tools/monitoring/check_pipeline_health.py
```

### Check Stale Running Records
```bash
PYTHONPATH=. python -c "
from google.cloud import bigquery
client = bigquery.Client()
query = '''
SELECT processor_name, data_date, COUNT(*) as stuck_count
FROM nba_reference.processor_run_history
WHERE status = 'running'
  AND started_at < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 4 HOUR)
GROUP BY 1, 2
ORDER BY 2 DESC
LIMIT 20
'''
for row in client.query(query).result():
    print(f'{row.data_date}: {row.processor_name} ({row.stuck_count} stuck)')
"
```

### Check player_daily_cache Data
```bash
PYTHONPATH=. python -c "
from google.cloud import bigquery
client = bigquery.Client()
query = '''
SELECT DATE(cache_date) as date, COUNT(*) as count
FROM nba_precompute.player_daily_cache
WHERE cache_date >= '2026-01-08'
GROUP BY 1 ORDER BY 1 DESC
'''
for row in client.query(query).result():
    print(f'{row.date}: {row.count} records')
"
```

### Check Recent Processor Logs
```bash
gcloud run services logs read nba-phase4-precompute-processors \
  --region us-west2 --limit 50 2>/dev/null | grep -i "error\|fail\|stale"
```

---

## Long-Term Recommendations

### Layer 2: Stale Cleanup Job (Not Yet Implemented)
Create scheduled function to mark stale running records as failed:
```sql
UPDATE nba_reference.processor_run_history
SET status = 'failed', errors = 'stale_running_cleanup'
WHERE status = 'running'
  AND started_at < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 4 HOUR)
```

### Potential BigQuery Save Error Causes
1. **Date serialization**: Check if any `date` objects not converted to strings
2. **NUMERIC precision**: BigQuery NUMERIC fields have strict precision
3. **Empty arrays**: `data_quality_issues: []` for REPEATED STRING
4. **Enum values**: `quality_tier` might return unexpected type

---

## Session Timeline

| Time (UTC) | Event |
|------------|-------|
| 16:38 | Started daily orchestration check |
| 16:45 | Identified stale running as root cause |
| 17:15 | Implemented Layer 1 fix |
| 17:36 | Deployed revision 00036 (stale fix) |
| 17:53 | Tested - stale fix working, BigQuery save error discovered |
| 18:04 | Added error logging enhancement |
| 18:10 | Started deployment of revision 00037 |
| 18:15 | Wrote handoff document |

---

## Files Referenced

- `docs/09-handoff/2026-01-12-DAILY-ORCHESTRATION-CHECK.md` - Original check guide
- `docs/09-handoff/2026-01-12-SESSION-19-HANDOFF.md` - Previous session context
- `shared/utils/completeness_checker.py` - Stale running fix location
- `data_processors/precompute/precompute_base.py` - Error logging location
- `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py` - Processor code
- `schemas/bigquery/precompute/player_daily_cache.sql` - Table schema

---

*Handoff written: 2026-01-12 18:15 UTC*
*Next session should: Complete BigQuery error investigation and backfill missing data*
