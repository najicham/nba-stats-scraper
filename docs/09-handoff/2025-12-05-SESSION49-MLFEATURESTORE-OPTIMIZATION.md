# Session 49: MLFeatureStoreProcessor Optimization

**Date:** 2025-12-05
**Previous Session:** 48 (Data Cleanup and Optimization Handoff)
**Status:** Implementation complete, ready for testing

## Executive Summary

Session 49 implemented critical performance optimizations to MLFeatureStoreProcessor, addressing the #1 blocker for running 4 seasons of data. The processor was averaging **33 minutes/day** - with these optimizations, we expect **3-9 minutes/day** (3.7-11x speedup).

## Key Finding: Table Location Mystery SOLVED

The `ml_feature_store` table was NOT missing - it exists at:
```
nba_predictions.ml_feature_store_v2
```

Session 48 searched `nba_precompute` but the processor intentionally writes to `nba_predictions` (cross-dataset write for Phase 5 consumption).

## Optimizations Implemented

### 1. Source Hash Query Optimization
**File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
**Lines:** 352-407

| Before | After |
|--------|-------|
| 4 sequential BigQuery queries | 1 UNION ALL query |
| ~30-60 seconds | ~5-10 seconds |

```sql
-- NEW: Single combined query
WITH latest_hashes AS (
    SELECT 'daily_cache' as source, data_hash, processed_at
    FROM `nba_precompute.player_daily_cache`
    WHERE cache_date = '{date}'
    UNION ALL
    SELECT 'composite' as source, data_hash, processed_at
    FROM `nba_precompute.player_composite_factors`
    ...
)
SELECT source, data_hash FROM ranked_hashes WHERE rn = 1
```

### 2. Upstream Completeness Query Optimization
**File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
**Lines:** 566-702

| Before | After |
|--------|-------|
| 4 separate queries | 2 combined queries |
| ~120-180 seconds | ~20-40 seconds |

- Query 1: All player-level tables (daily_cache, composite, shot_zone) with FULL OUTER JOINs
- Query 2: Team defense completeness

### 3. BatchWriter MERGE Pattern (CRITICAL)
**File:** `data_processors/precompute/ml_feature_store/batch_writer.py`

| Before | After |
|--------|-------|
| DELETE all rows for date | Create temp table |
| Split into 100-row batches | Single batch load |
| Sequential INSERT jobs (4-5) | MERGE from temp to target |
| ~600-1200 seconds | ~30-60 seconds |

**Key Benefits:**
- No streaming buffer issues (uses batch loading, not streaming inserts)
- Atomic operation (either all succeed or all fail)
- Handles upserts correctly (WHEN MATCHED / WHEN NOT MATCHED)
- Follows `bigquery-best-practices.md` pattern

### 4. Timing Instrumentation
Added detailed timing throughout:
- `extract_raw_data()` - tracks check_dependencies, get_players, batch_extract
- `calculate_precompute()` - tracks completeness_check, player_processing
- `BatchWriter` - tracks schema, load, merge steps
- `get_precompute_stats()` - logs performance breakdown

## Expected Performance

| Phase | Before | After | Savings |
|-------|--------|-------|---------|
| Source hash queries | 30-60s | 5-10s | ~50s |
| Upstream completeness | 120-180s | 20-40s | ~140s |
| BatchWriter (DELETE+INSERT) | 600-1200s | 30-60s | ~900s |
| **Total** | **~33 min** | **~3-9 min** | **~24-30 min** |

## Files Modified

1. **ml_feature_store_processor.py**
   - `_extract_source_hashes()` - combined query
   - `_query_upstream_completeness()` - combined queries
   - `__init__()` - added `_timing` dict
   - `extract_raw_data()` - timing instrumentation
   - `calculate_precompute()` - timing instrumentation
   - `get_precompute_stats()` - timing breakdown logging

2. **batch_writer.py** - Complete rewrite
   - `write_batch()` - new MERGE pattern
   - `_load_to_temp_table()` - single batch load
   - `_merge_to_target()` - MERGE query
   - `write_batch_legacy()` - kept for rollback

## Streaming Buffer Prevention

The optimizations specifically avoid streaming buffer issues:

1. **No `insert_rows_json()`** - This creates streaming buffers
2. **Uses `load_table_from_json()`** - Batch loads don't create streaming buffers
3. **MERGE works immediately** - No 90-minute wait for streaming buffer to clear
4. **Graceful fallback** - If buffer exists, skip and retry next run

Reference: `/docs/05-development/guides/bigquery-best-practices.md`

## Testing Instructions

### Quick Single-Date Test
```bash
cd /home/naji/code/nba-stats-scraper
source .venv/bin/activate

# Test on a date with known data
python -c "
from datetime import date
from data_processors.precompute.ml_feature_store.ml_feature_store_processor import MLFeatureStoreProcessor

processor = MLFeatureStoreProcessor()
processor.run(analysis_date=date(2021, 11, 20), is_backfill=True)
print(processor.get_precompute_stats())
"
```

### Expected Output
Look for timing breakdown in logs:
```
📊 PERFORMANCE TIMING BREAKDOWN:
   Extract Phase: X.Xs
     - check_dependencies: X.Xs
     - get_players_with_games: X.Xs
     - batch_extract_all_data: X.Xs
   Calculate Phase: X.Xs
     - completeness_check: X.Xs
     - player_processing: X.Xs
   (Write timing in BatchWriter logs above)
```

## Processor Parallelization Status (All Others)

Confirmed all other processors are already parallelized:

| Processor | Workers | Status |
|-----------|---------|--------|
| PlayerShotZoneAnalysisProcessor | 10 | ✅ |
| PlayerDailyCacheProcessor | 8 | ✅ |
| PlayerCompositeFactorsProcessor | 10 | ✅ |
| TeamDefenseZoneAnalysisProcessor | 4 | ✅ |
| MLFeatureStoreProcessor | 10 | ✅ |

## First Month Backfill Status

Phase 3 Analytics (2021-10-19 to 2021-11-19):
- player_game_summary: 100% data_hash coverage
- team_defense_game_summary: 100%
- team_offense_game_summary: 100%
- upcoming_player_game_context: 100%
- upcoming_team_game_context: 100%

Phase 4 Precompute:
- player_daily_cache: OK (2021-11-05 to 2021-11-30)
- player_composite_factors: Needs cleanup (data extends to 2025-12-03)
- ml_feature_store: In `nba_predictions` dataset (not `nba_precompute`)

## Next Steps (Session 50+)

1. **Test the optimization** - Run single-date test, verify timing improvement
2. **Clean up extended data** - Delete data > 2021-11-30 if still needed
3. **Run MLFeatureStore backfill** for first month (2021-10-19 to 2021-11-30)
4. **Plan Phase 5 and Phase 6 backfill** after Phase 4 complete

## Rollback Plan

If MERGE pattern causes issues:
```python
# In batch_writer.py, change write_batch() call to:
self.batch_writer.write_batch_legacy(...)  # Uses old DELETE+INSERT
```

Legacy method is preserved in `write_batch_legacy()`.

---

**Session Duration:** ~45 minutes
**Changes:** 2 files modified, ~400 lines changed
**Risk Level:** Medium (significant change to write pattern, but follows best practices)
