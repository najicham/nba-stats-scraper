# Session 103: Validation Findings and Remediation Complete

**Date:** 2025-12-09
**Status:** P1-P4 COMPLETE, P5-P6 pending for next session

---

## Executive Summary

This session performed comprehensive validation of the Oct-Dec 2021 backfill data and remediated critical data quality issues. The backfill process is now validated as mostly bulletproof, with clear documentation of expected behaviors and remaining work.

---

## Work Completed This Session

### P1: Deduplicate Phase 5 Predictions
**Status:** COMPLETE

**Before:** 53,686 rows (26,164 duplicates - 49%)
**After:** 27,522 unique rows

**Method Used:**
```sql
-- Created backup first
CREATE TABLE nba_predictions.player_prop_predictions_backup_20251209 AS
SELECT * FROM nba_predictions.player_prop_predictions;

-- Created deduped table keeping most recent per unique key
CREATE OR REPLACE TABLE nba_predictions.player_prop_predictions_deduped AS
SELECT * EXCEPT(rn) FROM (
  SELECT *, ROW_NUMBER() OVER(
    PARTITION BY game_date, player_lookup, system_id
    ORDER BY created_at DESC
  ) as rn
  FROM nba_predictions.player_prop_predictions
)
WHERE rn = 1;

-- Dropped original and copied deduped to original name
DROP TABLE nba_predictions.player_prop_predictions;
bq cp nba_predictions.player_prop_predictions_deduped nba_predictions.player_prop_predictions;
DROP TABLE nba_predictions.player_prop_predictions_deduped;
```

**Backup Available:** `nba_predictions.player_prop_predictions_backup_20251209` (can delete after verification period)

---

### P2: Fix NULL game_id in Predictions
**Status:** COMPLETE

**Before:** All 27,522 predictions had `game_id = NULL`
**After:** All 27,522 predictions have valid `game_id`

**Method Used:**
```sql
-- MERGE with de-duplicated source (some players have multiple games per day)
MERGE nba_predictions.player_prop_predictions T
USING (
  SELECT
    prediction_id,
    ANY_VALUE(game_id) as game_id
  FROM (
    SELECT
      p.prediction_id,
      pgs.game_id
    FROM nba_predictions.player_prop_predictions p
    JOIN nba_analytics.player_game_summary pgs
      ON p.game_date = pgs.game_date
      AND p.player_lookup = pgs.player_lookup
    WHERE p.game_id IS NULL
  )
  GROUP BY prediction_id
) S
ON T.prediction_id = S.prediction_id
WHEN MATCHED THEN UPDATE SET game_id = S.game_id;
```

---

### P3: Investigate Nov 1, 2021 Missing Data
**Status:** RESOLVED - NOT A BUG

**Finding:** Nov 1, 2021 is **intentionally missing** due to the 14-day bootstrap period.

**Root Cause Explanation:**
- 2021-22 NBA season started October 19, 2021
- Bootstrap period: Oct 19 (Day 0) through Nov 1 (Day 13)
- Phase 4 processing starts Nov 2 (Day 14)
- Nov 1 is Day 13 - within bootstrap window

**Bootstrap Logic Location:** `shared/config/nba_season_dates.py`
```python
def is_early_season(analysis_date: date, season_year: int, days_threshold: int = 14) -> bool:
    season_start = get_season_start_date(season_year)
    days_since_start = (analysis_date - season_start).days
    return 0 <= days_since_start < days_threshold
```

**Evidence from Logs:** (`/tmp/tdza_nov_dec_2021.log`, `/tmp/psza_nov_dec_2021.log`, etc.)
```
INFO:__main__:Processing game date 1/59: 2021-11-01
INFO:__main__:BOOTSTRAP: Skipping 2021-11-01 (early season period)
INFO:__main__:  Skipped: bootstrap period
INFO:__main__:Processing game date 2/59: 2021-11-02
```

**Conclusion:** This is BY DESIGN. All dates Oct 19 - Nov 1, 2021 are intentionally skipped.

---

### P4: Clean Stale PCF Failure Records
**Status:** COMPLETE

**Before:** 847 stale `calculation_error` records for Dec 1-6 with "No module named 'shared.utils.hash_utils'"
**After:** 0 stale records

**Method Used:**
```sql
DELETE FROM nba_processing.precompute_failures
WHERE processor_name = 'PlayerCompositeFactorsProcessor'
  AND failure_category = 'calculation_error'
  AND failure_reason LIKE '%hash_utils%'
  AND analysis_date >= '2021-12-01' AND analysis_date <= '2021-12-06';
-- Number of affected rows: 847
```

**Context:** PCF table had actual data for these dates despite the failure records. The failure records were from an initial failed run; a successful re-run populated the data but didn't clean up the failure records.

---

## Remaining Tasks for Next Session

### P5: Run Phase 5 Predictions for Nov 5-14
**Status:** PENDING
**Priority:** HIGH

Phase 4 data exists for Nov 5-14 (10 dates), but Phase 5 predictions were never generated.

**Command to Run:**
```bash
PYTHONPATH=. .venv/bin/python backfill_jobs/prediction/player_prop_predictions_backfill.py \
  --start-date 2021-11-05 --end-date 2021-11-14 --skip-preflight --no-resume \
  2>&1 | tee /tmp/phase5_nov5_14.log
```

**Expected Output:** ~10 game dates with predictions

**IMPORTANT:** Before running P5, verify P6 (idempotency) is complete OR use `--dates` flag for specific dates to avoid creating duplicates if you need to re-run.

---

### P6: Add Idempotency to Prediction Backfill Script
**Status:** PENDING
**Priority:** HIGH

**Problem:** The current script uses `insert_rows_json()` (append-only). Running the same date twice creates duplicates.

**Location:** `backfill_jobs/prediction/player_prop_predictions_backfill.py:386`

**Recommended Fix Options:**

**Option A: Add pre-delete before insert (simpler)**
```python
def write_predictions_to_bq(self, predictions, game_date):
    # Delete existing predictions for this date first
    delete_query = f"""
    DELETE FROM `{PREDICTIONS_TABLE}`
    WHERE game_date = '{game_date.isoformat()}'
    """
    self.bq_client.query(delete_query).result()

    # Then insert new predictions
    # ... existing insert logic ...
```

**Option B: Use MERGE/upsert pattern (more robust)**
See the code example in the original document below.

**Also Fix:** Add `game_id` to the write function - it's available from `get_players_for_date()` but not passed through.

---

## How to Validate Backfill Data

### 1. Run the Validation Script
```bash
# Basic validation
PYTHONPATH=. .venv/bin/python scripts/validate_backfill_coverage.py \
  --start-date 2021-11-01 --end-date 2021-12-31

# With details (shows per-date breakdown)
PYTHONPATH=. .venv/bin/python scripts/validate_backfill_coverage.py \
  --start-date 2021-11-01 --end-date 2021-12-31 --details

# Player-level reconciliation (most thorough)
PYTHONPATH=. .venv/bin/python scripts/validate_backfill_coverage.py \
  --start-date 2021-11-01 --end-date 2021-12-31 --reconcile
```

**Key Status Codes:**
- `OK` - Records present
- `Skipped` - Player-level expected failures (EXPECTED_INCOMPLETE, INSUFFICIENT_DATA)
- `DepsMiss` - Date-level upstream dependency missing
- `Untracked` - **INVESTIGATE!** No records AND no failure records
- `Investigate` - Has processing errors (INCOMPLETE_UPSTREAM, PROCESSING_ERROR)

### 2. Quick Coverage Queries

**Phase 4 Coverage by Processor:**
```sql
SELECT
  processor,
  FORMAT_DATE('%Y-%m', date) as month,
  COUNT(DISTINCT date) as days
FROM (
  SELECT 'TDZA' as processor, analysis_date as date FROM nba_precompute.team_defense_zone_analysis WHERE analysis_date >= '2021-10-01' AND analysis_date <= '2022-04-30'
  UNION ALL SELECT 'PSZA', analysis_date FROM nba_precompute.player_shot_zone_analysis WHERE analysis_date >= '2021-10-01' AND analysis_date <= '2022-04-30'
  UNION ALL SELECT 'PCF', game_date FROM nba_precompute.player_composite_factors WHERE game_date >= '2021-10-01' AND game_date <= '2022-04-30'
  UNION ALL SELECT 'PDC', cache_date FROM nba_precompute.player_daily_cache WHERE cache_date >= '2021-10-01' AND cache_date <= '2022-04-30'
  UNION ALL SELECT 'MLFS', game_date FROM nba_predictions.ml_feature_store_v2 WHERE game_date >= '2021-10-01' AND game_date <= '2022-04-30'
)
GROUP BY processor, month
ORDER BY month, processor;
```

**Phase 5 Predictions Coverage:**
```sql
SELECT
  FORMAT_DATE('%Y-%m', game_date) as month,
  COUNT(DISTINCT game_date) as game_dates,
  COUNT(*) as predictions,
  COUNT(DISTINCT player_lookup) as unique_players
FROM nba_predictions.player_prop_predictions
GROUP BY month
ORDER BY month;
```

**Check for Duplicates:**
```sql
SELECT
  'Predictions' as table_name,
  COUNT(*) as total_rows,
  COUNT(DISTINCT CONCAT(game_date, '|', player_lookup, '|', system_id)) as unique_keys,
  COUNT(*) - COUNT(DISTINCT CONCAT(game_date, '|', player_lookup, '|', system_id)) as duplicates
FROM nba_predictions.player_prop_predictions;
```

**Find Missing Dates (Phase 5):**
```sql
WITH expected AS (
  SELECT DISTINCT game_date
  FROM nba_analytics.player_game_summary
  WHERE game_date >= '2021-11-02' AND game_date <= '2021-12-31'  -- After bootstrap
),
actual AS (
  SELECT DISTINCT game_date
  FROM nba_predictions.player_prop_predictions
)
SELECT e.game_date as missing_date
FROM expected e
LEFT JOIN actual a ON e.game_date = a.game_date
WHERE a.game_date IS NULL
ORDER BY missing_date;
```

### 3. Check Failure Records

**Summary by Category:**
```sql
SELECT
  processor_name,
  failure_category,
  COUNT(*) as count
FROM nba_processing.precompute_failures
WHERE analysis_date >= '2021-11-01' AND analysis_date <= '2021-12-31'
GROUP BY processor_name, failure_category
ORDER BY processor_name, count DESC;
```

**Expected vs Unexpected Categories:**

**Expected (not errors):**
- `EXPECTED_INCOMPLETE` - Player hasn't played enough games (bootstrap)
- `INSUFFICIENT_DATA` - Not enough game history for lookback
- `MISSING_DEPENDENCIES` - Upstream not ready
- `NO_SHOT_ZONE` - No shot data for player

**Investigate These:**
- `INCOMPLETE_UPSTREAM` - Player has games but missing upstream (needs backfill)
- `PROCESSING_ERROR` - Actual error during processing
- `calculation_error` - Code error (check if data exists despite error)

---

## How to Find More Issues

### 1. Check for Stale Failure Records
Failure records that exist but the data was actually written:
```sql
-- Find PCF failures where data actually exists
SELECT f.analysis_date, f.failure_category, COUNT(f.*) as failures, COUNT(p.*) as actual_records
FROM nba_processing.precompute_failures f
LEFT JOIN nba_precompute.player_composite_factors p
  ON f.analysis_date = p.game_date AND f.entity_id = p.player_lookup
WHERE f.processor_name = 'PlayerCompositeFactorsProcessor'
  AND f.analysis_date >= '2021-11-01'
GROUP BY f.analysis_date, f.failure_category
HAVING COUNT(p.*) > 0;  -- Has records despite failures
```

### 2. Check for Data Anomalies

**Suspiciously high/low values:**
```sql
-- PCF outliers
SELECT game_date, player_lookup, overall_composite
FROM nba_precompute.player_composite_factors
WHERE overall_composite > 2.0 OR overall_composite < 0.1
ORDER BY game_date;

-- PDC with zero stats for players who played
SELECT pdc.cache_date, pdc.player_lookup, pdc.l5_avg_points
FROM nba_precompute.player_daily_cache pdc
JOIN nba_analytics.player_game_summary pgs
  ON pdc.cache_date = pgs.game_date AND pdc.player_lookup = pgs.player_lookup
WHERE pdc.l5_avg_points = 0 AND pgs.points > 0;
```

### 3. Check Prediction Quality
```sql
-- Prediction vs Actual comparison
SELECT
  p.system_id,
  COUNT(*) as predictions,
  ROUND(AVG(ABS(p.predicted_points - pgs.points)), 2) as mae,
  ROUND(AVG(p.predicted_points), 2) as avg_predicted,
  ROUND(AVG(pgs.points), 2) as avg_actual
FROM nba_predictions.player_prop_predictions p
JOIN nba_analytics.player_game_summary pgs
  ON p.game_date = pgs.game_date AND p.player_lookup = pgs.player_lookup
GROUP BY p.system_id
ORDER BY mae;
```

---

## Key Files and Locations

### Backfill Scripts
| Script | Purpose |
|--------|---------|
| `backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py` | TDZA backfill |
| `backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py` | PSZA backfill |
| `backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py` | PCF backfill |
| `backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py` | PDC backfill |
| `backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py` | MLFS backfill |
| `backfill_jobs/prediction/player_prop_predictions_backfill.py` | Phase 5 predictions |

### Validation Scripts
| Script | Purpose |
|--------|---------|
| `scripts/validate_backfill_coverage.py` | Main validation - coverage, failures, reconciliation |
| `scripts/cleanup_stale_pcf_failures.py` | Clean stale PCF failure records (created this session) |

### Configuration
| File | Purpose |
|------|---------|
| `shared/config/nba_season_dates.py` | Bootstrap period logic, season dates |
| `shared/processors/mixins/precompute_base_mixin.py` | Base mixin for backfill mode |

### Log Files
Backfill logs are written to `/tmp/`:
- `/tmp/tdza_*.log` - Team Defense Zone Analysis
- `/tmp/psza_*.log` - Player Shot Zone Analysis
- `/tmp/pcf_*.log` - Player Composite Factors
- `/tmp/pdc_*.log` - Player Daily Cache
- `/tmp/mlfs_*.log` - ML Feature Store
- `/tmp/phase5_*.log` - Phase 5 Predictions

---

## Current Data State (After Session 103)

### Phase 4 Coverage (Nov-Dec 2021)
| Processor | Days | Date Range | Status |
|-----------|------|------------|--------|
| TDZA | 59 | Nov 2 - Dec 31 | Complete |
| PSZA | 56 | Nov 5 - Dec 31 | Complete (Nov 2-4 bootstrap) |
| PCF | 58 | Nov 2 - Dec 31 | Complete |
| PDC | 58 | Nov 2 - Dec 31 | Complete |
| MLFS | 58 | Nov 2 - Dec 31 | Complete |

### Phase 5 Coverage
| Period | Dates | Predictions | Status |
|--------|-------|-------------|--------|
| Nov 15-30 | 15 | ~15,000 | Complete |
| Dec 1-31 | 30 | ~12,500 | Complete |
| **Nov 5-14** | **10** | **0** | **NEEDS BACKFILL** |

### Data Quality
- Duplicates: 0 (was 26,164)
- NULL game_id: 0 (was 27,522)
- Stale failures: 0 (was 847)

---

## Investigation Summary - How We Found Issues

### Method 1: BigQuery Coverage Analysis
Compared expected dates (from `player_game_summary`) vs actual dates in each processor table.

### Method 2: Validation Script
```bash
PYTHONPATH=. .venv/bin/python scripts/validate_backfill_coverage.py --start-date 2021-11-01 --end-date 2021-12-31 --details
```
This showed "UNTRACKED" status for Nov 1 and revealed PCF "Investigate" status.

### Method 3: Duplicate Detection Query
```sql
SELECT game_date, player_lookup, system_id, COUNT(*) as dup_count
FROM nba_predictions.player_prop_predictions
GROUP BY game_date, player_lookup, system_id
HAVING COUNT(*) > 1;
```

### Method 4: Log File Analysis
```bash
grep -E "(SUMMARY|Complete|error|failed|skip)" /tmp/phase5_nov_dec_2021.log | head -30
```

### Method 5: Failure Record Analysis
```sql
SELECT failure_category, failure_reason, COUNT(*)
FROM nba_processing.precompute_failures
WHERE processor_name = 'PlayerCompositeFactorsProcessor'
GROUP BY failure_category, failure_reason;
```

---

## Next Session Recommended Flow

1. **Read this document** for context
2. **Run quick verification** to confirm P1-P4 are still good:
   ```bash
   bq query --use_legacy_sql=false "SELECT COUNT(*) as predictions, COUNTIF(game_id IS NULL) as null_game_id FROM nba_predictions.player_prop_predictions"
   ```
3. **Implement P6** (idempotency) FIRST before running any more backfills
4. **Run P5** (Nov 5-14 predictions) after P6 is complete
5. **Validate** results with the validation script
6. **Consider** expanding to Jan-Apr 2022 (rest of season)

---

## Git Status

**Latest commit:** `22d5429` - docs: Add Session 94-101 handoff documents

**Files to commit this session:**
- `docs/09-handoff/2025-12-09-SESSION103-VALIDATION-AND-REMEDIATION-PLAN.md` (this file)
- `scripts/cleanup_stale_pcf_failures.py` (created by agent)

**Backup table to eventually delete:**
- `nba_predictions.player_prop_predictions_backup_20251209`
