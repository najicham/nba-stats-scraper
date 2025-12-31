# Session 59: MLFS Backfill Plan

**Date:** 2025-12-06
**Previous Session:** 58 (Backfill Performance Optimization)
**Status:** Ready to execute

## Summary

Session 58's performance optimizations are in the working directory but **NOT COMMITTED**. Any NEW process started will use the optimized code. The old running processes are stale.

## Current Nov 2021 Coverage

| Processor | Dates | Status |
|-----------|-------|--------|
| TDZA | 29 | Complete |
| PSZA | 26 | Complete |
| PDC | 25 | Complete |
| PCF | 19 | 6 dates missing (early season gaps) |
| MLFS | 17 | Blocked by PCF gaps |

## Optimizations Ready (Uncommitted)

1. **60s query timeout** for backfill mode (was unlimited)
2. **Skip notifications** in backfill mode (was sending email+slack per failure)
3. **Skip stale data warnings** in backfill mode
4. **MLFS duplicate dep check removed** (was running check_dependencies twice)

## Execution Plan

### Step 1: Check Current MLFS Coverage

```bash
bq query --use_legacy_sql=false "
SELECT game_date
FROM nba_predictions.ml_feature_store_v2
WHERE game_date BETWEEN '2021-11-01' AND '2021-11-30'
GROUP BY game_date
ORDER BY game_date"
```

### Step 2: Run MLFS Backfill (Uses Optimized Code)

```bash
source .venv/bin/activate && PYTHONPATH=/home/naji/code/nba-stats-scraper \
python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2021-11-05 --end-date 2021-11-30 2>&1 | tee /tmp/mlfs_optimized.log
```

### Step 3: Monitor Progress

```bash
# Watch the log
tail -f /tmp/mlfs_optimized.log

# Check for "Dependencies validated in Xs" - should be <10s now, not 30+ min
grep "Dependencies validated" /tmp/mlfs_optimized.log
```

### Step 4: Verify Results

```bash
# Check coverage after completion
bq query --use_legacy_sql=false "
SELECT 'MLFS' as processor, COUNT(DISTINCT game_date) as dates
FROM nba_predictions.ml_feature_store_v2
WHERE game_date BETWEEN '2021-11-01' AND '2021-11-30'"

# Check failures
bq query --use_legacy_sql=false "
SELECT failure_category, COUNT(*) as count
FROM nba_processing.precompute_failures
WHERE processor_name = 'MLFeatureStoreProcessor'
  AND analysis_date BETWEEN '2021-11-01' AND '2021-11-30'
GROUP BY failure_category"
```

## Expected Performance

| Metric | Before Optimization | After Optimization |
|--------|--------------------|--------------------|
| Dependency check | 30+ min (timeout cascades) | <10s |
| Per-date processing | 30+ min | ~2 min |
| Notifications | 2-4 per failed date | 0 |

## Known Limitations

- MLFS will fail for dates where PCF has no data (6 dates in Nov 2021)
- These failures will be recorded in `precompute_failures` with `MISSING_DEPENDENCIES`
- This is expected - early season games don't have enough player history

## Files Modified (Uncommitted)

| File | Changes |
|------|---------|
| `data_processors/precompute/precompute_base.py` | Query timeout, notification skip, failure tracking |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | Removed duplicate dep check |

## Registry Failures Integration

- Table `nba_processing.registry_failures` exists and is ready
- Code integrated in PGS and UPGC processors
- Currently 0 rows (all players resolving correctly)
- Will auto-populate if future runs encounter unresolved players

---

**Last Updated:** 2025-12-06
