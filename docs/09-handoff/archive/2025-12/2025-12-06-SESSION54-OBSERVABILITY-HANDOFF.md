# Session 54: Backfill Observability Implementation Handoff

**Date:** 2025-12-06
**Previous Session:** 53 (Backfill Progress)
**Status:** Infrastructure built, needs re-run with new code

## Executive Summary

Session 54 addressed the critical observability gap: "When a player is missing from a backfill, is it expected or an error?" We built infrastructure for true player-level reconciliation but the current backfills ran with old code.

## The Problem We Solved

When running backfills, some records weren't being created. We needed visibility into:
- Is the missing record expected (INSUFFICIENT_DATA, MISSING_DEPENDENCIES)?
- Is it an actual error that needs investigation?

## Code Changes Made

### 1. Date-Level Failure Tracking (NEW)

**File:** `data_processors/precompute/precompute_base.py`

Added `_record_date_level_failure()` method that records when an entire date fails:
```python
def _record_date_level_failure(self, category: str, reason: str, can_retry: bool = True):
    """Record date-level failure (e.g., missing dependencies) to BigQuery"""
```

Added call in the dependency check section (around line 218):
```python
if not dep_check['all_critical_present']:
    self._record_date_level_failure(
        category='MISSING_DEPENDENCIES',
        reason=f"Missing: {', '.join(dep_check['missing'])}",
        can_retry=True
    )
```

### 2. Player-Level Failure Tracking

**Files modified:**
- `data_processors/precompute/precompute_base.py` - Added `save_failures_to_bq()` method
- `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` - Added call
- `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py` - Added call
- `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py` - Added call
- `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py` - Already had it

### 3. Validation Script Enhanced

**File:** `scripts/validate_backfill_coverage.py`

Added `--reconcile` mode for true player-level reconciliation:
```bash
python scripts/validate_backfill_coverage.py --start-date 2021-11-05 --end-date 2021-11-15 --reconcile
```

This answers: "For each player who played, do they have EITHER a record OR a failure record?"

## Current Data State

### November 2021 MLFS Coverage
```
| Date       | Records | Status              |
|------------|---------|---------------------|
| 2021-11-10 |     450 | Complete            |
| 2021-11-12 |     385 | Complete            |
| 2021-11-13 |     244 | Complete            |
| 2021-11-14 |     243 | Complete            |
| 2021-11-15 |     389 | Complete            |
| 2021-11-17 |     382 | Complete            |
| 2021-11-18 |     200 | Complete            |
| 2021-11-19 |     314 | Complete            |
| 2021-11-20 |     312 | Complete            |
| 2021-11-22 |     346 | Complete            |
| 2021-11-24 |     450 | Complete            |
| 2021-11-26 |     418 | Complete            |
| 2021-11-27 |     289 | Complete            |
| 2021-11-28 |     169 | Complete            |
| 2021-11-29 |     302 | Complete            |
| 2021-11-30 |     167 | Complete            |
```

Total: 16 dates with MLFS records (5,061 total records)

### Failure Records in BigQuery
```
| Processor                       | Category             | Count |
|---------------------------------|----------------------|-------|
| PlayerShotZoneAnalysisProcessor | INSUFFICIENT_DATA    | 4,662 |
| MLFeatureStoreProcessor         | MISSING_DEPENDENCIES |     1 |
```

**Key Issue:** Only PSZA and 1 MLFS date-level failure are tracked. PDC, PCF, and MLFS player-level failures are NOT tracked because backfills ran with old code.

### Reconciliation Results (Nov 5-15)

```
Processor   Expected   Has Record   Has Failure   Unaccounted   Coverage
-------------------------------------------------------------------------
PSZA           1843         1050           779            14        99%
PDC            1843         1049             0           794        57%
PCF            1843         1397             0           446        76%
MLFS           1843         1047             0           796        57%
```

**Interpretation:**
- **PSZA** is at 99% coverage - excellent! Only 14 players unaccounted.
- **PDC/PCF/MLFS** have low coverage because they're NOT saving failure records (old code)

## Immediate Next Steps

### Step 1: Re-run Backfills with New Code

The code changes are in place. Re-running backfills will populate failure records.

```bash
# Clear checkpoints to force re-processing
rm -rf /tmp/backfill_checkpoints/*

# Run in order (each depends on previous):

# 1. PDC (no dependencies except Phase 3)
python backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
  --start-date 2021-11-05 --end-date 2021-11-30 2>&1 | tee /tmp/pdc_backfill.log

# 2. PCF (depends on PDC, PSZA)
python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
  --start-date 2021-11-05 --end-date 2021-11-30 2>&1 | tee /tmp/pcf_backfill.log

# 3. MLFS (depends on all)
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2021-11-05 --end-date 2021-11-30 2>&1 | tee /tmp/mlfs_backfill.log
```

### Step 2: Validate Coverage

```bash
# Quick check
python scripts/validate_backfill_coverage.py --start-date 2021-11-05 --end-date 2021-11-30

# Full reconciliation
python scripts/validate_backfill_coverage.py --start-date 2021-11-05 --end-date 2021-11-30 --reconcile
```

### Step 3: Investigate Remaining Gaps

If reconciliation shows unaccounted players > 0, investigate:
```sql
-- Find unaccounted players for a specific date/processor
WITH expected AS (
    SELECT DISTINCT player_lookup FROM nba_analytics.player_game_summary WHERE game_date = '2021-11-05'
),
has_record AS (
    SELECT DISTINCT player_lookup FROM nba_precompute.player_shot_zone_analysis WHERE analysis_date = '2021-11-05'
),
has_failure AS (
    SELECT DISTINCT entity_id as player_lookup FROM nba_processing.precompute_failures
    WHERE processor_name = 'PlayerShotZoneAnalysisProcessor' AND analysis_date = '2021-11-05'
)
SELECT e.player_lookup as unaccounted_player
FROM expected e
LEFT JOIN has_record r ON e.player_lookup = r.player_lookup
LEFT JOIN has_failure f ON e.player_lookup = f.player_lookup
WHERE r.player_lookup IS NULL AND f.player_lookup IS NULL;
```

## Why Early November Dates Have Low Coverage

Dates like Nov 5-9 have fewer records because:

1. **Season started Oct 19, 2021** - Players don't have 10+ games of history yet
2. **INSUFFICIENT_DATA is expected** - PSZA requires 10 games, so early-season players are skipped
3. **Cascading dependencies** - If PDC doesn't have data, PCF can't run, so MLFS can't run

This is **expected bootstrap behavior**, not an error.

## Failure Categories Reference

| Category | Meaning | Expected? |
|----------|---------|-----------|
| INSUFFICIENT_DATA | Player doesn't have enough game history | Yes (early season) |
| INCOMPLETE_DATA | Upstream data incomplete | Yes (bootstrap) |
| MISSING_DEPENDENCIES | Date-level: upstream tables empty | Yes (bootstrap) |
| MISSING_UPSTREAM | Player-level: no upstream record | Yes (order) |
| NO_SHOT_ZONE | Player has no shot data | Yes (rare players) |
| PROCESSING_ERROR | Actual exception during processing | **NO - investigate!** |
| UNKNOWN | Uncategorized failure | **NO - investigate!** |

## Files Modified This Session

1. `data_processors/precompute/precompute_base.py`
   - Added `failed_entities = []` initialization
   - Added `_record_date_level_failure()` method
   - Added `save_failures_to_bq()` method
   - Added call to `_record_date_level_failure` on missing dependencies

2. `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
   - Added failure category breakdown logging
   - Added `save_failures_to_bq()` call

3. `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py`
   - Added failure category breakdown logging
   - Added `save_failures_to_bq()` call

4. `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`
   - Added failure category breakdown logging
   - Added `save_failures_to_bq()` call

5. `scripts/validate_backfill_coverage.py`
   - Added `MISSING_DEPENDENCIES` and `MINIMUM_THRESHOLD_NOT_MET` to expected categories
   - Added `get_player_reconciliation()` method for true player-level reconciliation
   - Added `--reconcile` flag for reconciliation mode
   - Updated status codes: `DEPS_MISSING`, `UNTRACKED` (replaces `MISSING`)

## Quick Commands Reference

```bash
# Check current MLFS coverage
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as records
FROM nba_predictions.ml_feature_store_v2
WHERE game_date BETWEEN '2021-11-01' AND '2021-11-30'
GROUP BY game_date ORDER BY game_date"

# Check failure records
bq query --use_legacy_sql=false "
SELECT processor_name, failure_category, COUNT(*) as count
FROM nba_processing.precompute_failures
WHERE analysis_date BETWEEN '2021-11-01' AND '2021-11-30'
GROUP BY processor_name, failure_category
ORDER BY processor_name"

# Run validation
python scripts/validate_backfill_coverage.py --start-date 2021-11-05 --end-date 2021-11-30 --reconcile
```

## Target State

After re-running backfills with new code, each processor should show:

```
Processor   Expected   Has Record   Has Failure   Unaccounted   Coverage
-------------------------------------------------------------------------
PSZA           XXXX         XXXX          XXXX             0       100%
PDC            XXXX         XXXX          XXXX             0       100%
PCF            XXXX         XXXX          XXXX             0       100%
MLFS           XXXX         XXXX          XXXX             0       100%
```

**Unaccounted = 0** means every player either:
- Has a record in the output table, OR
- Has a failure record explaining why not

## Known Issues

1. **Schema mismatch warning:** `precompute_processor_runs.processor_name` mode changed
   - Migration exists: `scripts/migrations/fix_precompute_processor_runs_schema.sql`

2. **JSON serialization bug:** `Object of type date is not JSON serializable`
   - Occurs when saving debug data, non-blocking

## Related Documentation

- Session 52 Handoff: `docs/09-handoff/2025-12-06-SESSION52-BACKFILL-COMPLETION-HANDOFF.md`
- Session 53 Handoff: `docs/09-handoff/2025-12-06-SESSION53-NAME-RESOLUTION-IMPLEMENTATION.md`
- Validation Script: `scripts/validate_backfill_coverage.py`
