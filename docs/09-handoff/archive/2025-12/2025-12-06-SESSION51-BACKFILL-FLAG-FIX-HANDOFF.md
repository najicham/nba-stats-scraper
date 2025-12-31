# Session 51: Backfill Flag Fix & System Improvements
**Date:** 2025-12-06
**Previous Session:** 50 (Processor Optimization Testing)
**Status:** Bug fixes complete, upstream backfills pending

## Executive Summary

Session 51 investigated November 2021 backfill failures and discovered a critical bug: the Session 50 parallel backfill used `is_backfill=True` but the processor only recognized `backfill_mode=True`. This caused completeness checks to be enforced, resulting in most players being skipped.

**Key Fixes Applied:**
1. Backfill flag validation - now accepts both flags with deprecation warning
2. SES email credentials - fixed dotenv loading
3. Clear logging for backfill mode activation

## Root Cause Analysis

### November 2021 Data Gap Investigation

| Date Range | Issue | Root Cause |
|------------|-------|------------|
| Nov 1-4 | No data | Bootstrap period (first 14 days of season) - Expected |
| Nov 5-6, 9, 11, 16, 23 | pcf=0, mlfs=0 | `player_daily_cache` incomplete (<70 players) |
| Nov 7-8 | pcf exists, mlfs=0 | Backfill used wrong flag (`is_backfill` not `backfill_mode`) |
| Nov 18, 21 | mlfs undercounting | `is_production_ready=false` cascade failure |
| Nov 29-30 | pcf=0, mlfs=0 | `team_defense_zone_analysis` missing 1 team |

### The Backfill Flag Bug

**Session 50's inline code used:**
```python
processor.run(opts={
    'analysis_date': d,
    'is_backfill': True,  # WRONG KEY!
})
```

**But the processor checked:**
```python
def is_backfill_mode(self) -> bool:
    return self.opts.get('backfill_mode', False)  # Different key!
```

**Result:** Completeness checks were enforced, skipping players without `is_production_ready=true`.

## Fixes Applied

### 1. Backfill Flag Validation (`precompute_base.py`)

**Location:** `data_processors/precompute/precompute_base.py:641-710`

**Changes:**
- `is_backfill_mode` property now accepts: `backfill_mode`, `is_backfill` (legacy), `skip_downstream_trigger`
- New method `_validate_and_normalize_backfill_flags()` added
- Logs deprecation warning for `is_backfill`
- Raises `ValueError` for invalid flags like `backfill`, `isBackfill`, `backfillMode`
- Clear logging when backfill mode activates

**Test the fix:**
```python
from datetime import date
from data_processors.precompute.ml_feature_store.ml_feature_store_processor import MLFeatureStoreProcessor

processor = MLFeatureStoreProcessor()
processor.set_opts({'analysis_date': date(2021, 11, 10), 'is_backfill': True})
processor._validate_and_normalize_backfill_flags()
print(f'is_backfill_mode: {processor.is_backfill_mode}')  # Should be True
```

### 2. SES Email Fix (`email_alerting_ses.py`)

**Location:** `shared/utils/email_alerting_ses.py:24-27`

**Changes:**
- Added `from dotenv import load_dotenv` and `load_dotenv()` at module level
- Ensures `.env` credentials are loaded before boto3 client initialization

**Credentials added to `.env`:**
```bash
AWS_SES_ACCESS_KEY_ID=<your-access-key-id>
AWS_SES_SECRET_ACCESS_KEY=<your-secret-access-key>
AWS_SES_REGION=us-west-2
AWS_SES_FROM_EMAIL=alert@989.ninja
```

## Current Data State

### November 2021 Coverage

```sql
-- Run this to check current state
SELECT game_date, COUNT(*) as mlfs_records
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date BETWEEN "2021-11-01" AND "2021-11-30"
GROUP BY game_date ORDER BY game_date;
```

**Current:** 14/29 dates have data (48% coverage)
**Expected after fix:** 25/29 dates (86% - excluding Nov 1-4 bootstrap)

### Upstream Data Gaps

```sql
-- Check all upstream table coverage
WITH dates AS (
  SELECT DATE_ADD(DATE "2021-11-01", INTERVAL n DAY) as game_date
  FROM UNNEST(GENERATE_ARRAY(0, 29)) as n
),
pdc AS (SELECT cache_date as game_date, COUNT(*) as cnt FROM `nba_precompute.player_daily_cache` WHERE cache_date BETWEEN "2021-11-01" AND "2021-11-30" GROUP BY cache_date),
pcf AS (SELECT game_date, COUNT(*) as cnt FROM `nba_precompute.player_composite_factors` WHERE game_date BETWEEN "2021-11-01" AND "2021-11-30" GROUP BY game_date),
psza AS (SELECT analysis_date as game_date, COUNT(*) as cnt FROM `nba_precompute.player_shot_zone_analysis` WHERE analysis_date BETWEEN "2021-11-01" AND "2021-11-30" GROUP BY analysis_date),
tdza AS (SELECT analysis_date as game_date, COUNT(*) as cnt FROM `nba_precompute.team_defense_zone_analysis` WHERE analysis_date BETWEEN "2021-11-01" AND "2021-11-30" GROUP BY analysis_date),
mlfs AS (SELECT game_date, COUNT(*) as cnt FROM `nba_predictions.ml_feature_store_v2` WHERE game_date BETWEEN "2021-11-01" AND "2021-11-30" GROUP BY game_date)
SELECT d.game_date,
  COALESCE(pdc.cnt, 0) as pdc,
  COALESCE(pcf.cnt, 0) as pcf,
  COALESCE(psza.cnt, 0) as psza,
  COALESCE(tdza.cnt, 0) as tdza,
  COALESCE(mlfs.cnt, 0) as mlfs
FROM dates d
LEFT JOIN pdc ON d.game_date = pdc.game_date
LEFT JOIN pcf ON d.game_date = pcf.game_date
LEFT JOIN psza ON d.game_date = psza.game_date
LEFT JOIN tdza ON d.game_date = tdza.game_date
LEFT JOIN mlfs ON d.game_date = mlfs.game_date
ORDER BY d.game_date;
```

## Next Steps (Priority Order)

### 1. Backfill Upstream Processors

Run in this order (dependency chain):

```bash
cd /home/naji/code/nba-stats-scraper
source .venv/bin/activate

# Step 1: Player Daily Cache (depends on Phase 3 data)
python backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
  --start-date 2021-11-05 --end-date 2021-11-30

# Step 2: Player Composite Factors (depends on PDC, PSZA, TDZA)
python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
  --start-date 2021-11-05 --end-date 2021-11-30

# Step 3: Clear MLFS checkpoint and re-run
rm /tmp/backfill_checkpoints/ml_feature_store_2021-11-05_2021-11-30.json
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2021-11-05 --end-date 2021-11-30
```

### 2. Verify Results

```sql
-- After backfills complete, verify coverage
SELECT
  game_date,
  COUNT(*) as players,
  COUNT(CASE WHEN is_production_ready THEN 1 END) as production_ready
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date BETWEEN "2021-11-05" AND "2021-11-30"
GROUP BY game_date
ORDER BY game_date;
```

## Areas for Further Investigation/Improvement

### High Priority

1. **Schema Mismatch Warning**
   - Warning: `Field processor_name has changed mode from REQUIRED to NULLABLE`
   - Location: `nba_processing.precompute_processor_runs`
   - Migration file exists: `scripts/migrations/fix_precompute_processor_runs_schema.sql`
   - **Action:** Verify if migration needs to be run

2. **Upstream Coverage Dashboard**
   - No easy way to see which dates are missing upstream data
   - **Action:** Create monitoring view for data coverage gaps

3. **Date JSON Serialization Bug**
   - Warning: `Object of type date is not JSON serializable`
   - Occurs when saving debug data
   - **Action:** Find and fix the serialization issue

### Medium Priority

4. **Bootstrap Period Handling**
   - Currently skips first 14 days of each season
   - Consider: Configurable bootstrap days per processor?
   - Consider: Force-process option for historical analysis?

5. **Backfill Orchestration**
   - No automated dependency-aware backfill
   - **Action:** Create script that runs all processors in correct order

6. **Alert Categories**
   - All alerts go to same recipients
   - **Action:** Implement tiered alerting (critical vs warning vs info)

### Low Priority

7. **Unknown Team Codes Warning**
   - `Unknown team codes: away=PAY, home=BAR` (pre-season games?)
   - Non-blocking but worth investigating

8. **Completeness Threshold Tuning**
   - Some dates have PCF data but very low `is_production_ready` rate
   - Investigate thresholds and adjust for historical data

## Files Modified This Session

1. `data_processors/precompute/precompute_base.py`
   - Added `_validate_and_normalize_backfill_flags()` method
   - Updated `is_backfill_mode` property to accept `is_backfill`
   - Added call to validation in `run()` method

2. `shared/utils/email_alerting_ses.py`
   - Added `from dotenv import load_dotenv` import
   - Added `load_dotenv()` call at module level

3. `.env`
   - Added AWS SES credentials (AWS_SES_ACCESS_KEY_ID, AWS_SES_SECRET_ACCESS_KEY)

## Processor Dependency Chain Reference

```
Phase 3 (Analytics):
  player_game_summary
  team_defense_game_summary
  team_offense_game_summary
  upcoming_player_game_context
  upcoming_team_game_context
       ↓
Phase 4 (Precompute):
  1. team_defense_zone_analysis (depends on: team_defense_game_summary)
  2. player_shot_zone_analysis (depends on: team_offense_game_summary)
  3. player_daily_cache (depends on: upcoming_player_game_context)
  4. player_composite_factors (depends on: #1, #2, #3, upcoming contexts)
  5. ml_feature_store (depends on: ALL of #1-4)
```

## Quick Commands

```bash
# Check backfill checkpoint
cat /tmp/backfill_checkpoints/ml_feature_store_2021-11-05_2021-11-30.json

# Test SES email
python3 -c "
from shared.utils.email_alerting_ses import EmailAlerterSES
alerter = EmailAlerterSES()
alerter.send_error_alert('Test', {'test': True}, 'TestProcessor')
"

# Check running backfills
ps aux | grep -E "python.*backfill" | grep -v grep

# Monitor BigQuery job
bq ls -j --max_results=5
```

## Related Documentation

- Session 50 Handoff: `docs/09-handoff/2025-12-05-SESSION50-PROCESSOR-OPTIMIZATION-TESTING.md`
- Processor Optimization Project: `docs/08-projects/current/processor-optimization/`
- Phase 4 Precompute Base: `data_processors/precompute/precompute_base.py`
- ML Feature Store Processor: `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
