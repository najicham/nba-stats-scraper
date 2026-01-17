# Backfill Issues Found - Needs Investigation

**Date**: 2026-01-16
**Status**: ⚠️ BLOCKED - Backfills cannot complete due to data quality issues

---

## Issue Summary

Attempted to backfill `player_daily_cache` for Jan 8, 2026 as part of CatBoost V8 incident remediation.

**Result**: FAILED - All 118 players classified as INCOMPLETE_DATA, no records saved.

---

## Error Details

### Backfill Command
```bash
python -m data_processors.precompute.player_daily_cache.player_daily_cache_processor --analysis_date 2026-01-08
```

### Errors Encountered

1. **SQL Syntax Error** (Non-blocking warning)
   ```
   WARNING: Failed to extract source hashes: 400 Syntax error: Expected end of input but got keyword UNION at [7:13]
   Job ID: 75393d6f-24de-497c-9948-15d0def9716a
   ```

2. **BigQuery Timeout** (Blocking)
   ```
   WARNING: Completeness check for l5 failed: Timeout of 600.0s exceeded
   HTTPSConnectionPool(host='bigquery.googleapis.com', port=443): Read timed out
   ```

3. **Circuit Breaker Type Mismatch** (Non-blocking warning)
   ```
   WARNING: Failed to batch record reprocess attempts: 400 Query column 9 has type INT64
   which cannot be inserted into column circuit_breaker_until, which has type TIMESTAMP at [7:17]
   Job ID: 32d52d8c-1fbd-445e-af2f-e400dfcc8ed5
   ```

4. **Data Quality Failure** (BLOCKING - Root Cause)
   ```
   INFO: Completed 0 players in 3.7s (avg 0.00s/player) | 118 failed
   INFO: Failure breakdown by category:
      INCOMPLETE_DATA: 118 (expected - data quality)
   WARNING: No transformed data to save
   ERROR: ✗ Failed to save player daily cache
   ```

---

## Root Cause Analysis

### Why Backfill Failed

**All 118 players failed completeness checks** with classification: `INCOMPLETE_DATA`

This means the historical data for Jan 8, 2026 doesn't meet the processor's quality thresholds:
- L5 games window: Incomplete
- L10 games window: Incomplete
- L7 days window: Incomplete
- L14 days window: Incomplete

### Chicken-and-Egg Problem

The backfill is designed to **restore data quality**, but it **requires minimum data quality** to run.

When upstream data sources (player_game_summary, team_offense, etc.) are incomplete or missing for a date, the processor correctly refuses to generate cache records rather than generating low-quality cache data.

### Why This Happened

Looking at the original incident timeline:
- **Jan 7-8**: The upstream pipeline may have had issues BEFORE player_daily_cache failed
- **Jan 12**: PlayerGameSummaryProcessor stuck for 8+ hours, so downstream data was incomplete
- The OIDC permission error prevented Cloud Scheduler from triggering, but even if it had triggered, the data quality may have been too poor

---

## Data Extracted (Before Failure)

The processor successfully extracted:
- `player_game_summary`: 12,275 records
- `team_offense_game_summary`: 324 records
- `upcoming_player_game_context`: 199 records
- `shot_zone_analysis`: 430 records
- **Total players to process**: 199
- **Players meeting quality threshold**: 0 (118 processed, ALL failed)

---

## Secondary Issues Found

### 1. Source Hash Extraction SQL Error
**File**: `player_daily_cache_processor.py` (lines 963-1037, method: `_extract_source_hashes`)
**Error**: "Expected end of input but got keyword UNION at [7:13]"
**Impact**: Non-blocking (processor continues), but prevents smart reprocessing optimization
**Priority**: P2 - Fix for future runs

### 2. BigQuery Timeout on Completeness Check
**File**: Likely in `shared/utils/completeness_checker.py`
**Error**: L5 games window query timeout after 600 seconds
**Impact**: Blocking - causes completeness check to fail for one window
**Possible Causes**:
- Query too complex for historical date
- BigQuery quota/concurrency issue
- Missing index on game_date column
**Priority**: P1 - Investigate query performance

### 3. Circuit Breaker Type Mismatch
**File**: `player_daily_cache_processor.py` (circuit breaker recording logic)
**Error**: Trying to insert INT64 into TIMESTAMP column `circuit_breaker_until`
**Impact**: Non-blocking (falls back to individual inserts, slower but works)
**Root Cause**: Likely passing Unix timestamp (int) instead of TIMESTAMP object
**Priority**: P2 - Fix for performance

---

## Attempted Fixes vs Results

| Fix Attempted | Result | Notes |
|---------------|--------|-------|
| Backfill Jan 8 player_daily_cache | ❌ FAILED | All 118 players INCOMPLETE_DATA |
| Backfill Jan 12 player_daily_cache | ⏸️ NOT ATTEMPTED | Likely same issue |
| Regenerate ML Feature Store Jan 8 | ⏸️ NOT ATTEMPTED | Blocked by player_daily_cache failure |
| Regenerate ML Feature Store Jan 12 | ⏸️ NOT ATTEMPTED | Blocked by player_daily_cache failure |

---

## Recommendations

### Immediate Action (Today)
✅ **Deploy CatBoost model to fix 50% confidence issue** (production blocker)
- This is independent of backfills
- Restores production functionality

### Short-term Investigation (Next 1-2 days)
1. **Investigate data quality for Jan 8 & 12**
   - Check if `player_game_summary` has sufficient records for those dates
   - Check if `team_offense_game_summary` is complete
   - Identify which completeness window is failing (L5, L10, L7d, L14d)

2. **Debug completeness checker timeout**
   - Profile the L5 games window query
   - Check if query can be optimized
   - Consider increasing timeout or adding query hints

3. **Fix secondary SQL errors**
   - Source hash extraction UNION error
   - Circuit breaker type mismatch

### Medium-term Solution (Next week)
1. **Consider alternative backfill approach**
   - Manual SQL to populate player_daily_cache with best-effort data
   - Relax completeness requirements for historical backfills (add --force flag)
   - Generate synthetic cache data from available Phase 3 sources

2. **Improve processor resilience**
   - Add --skip-completeness flag for backfill scenarios
   - Better error messages explaining WHY data is incomplete
   - Graceful degradation (save partial cache records with quality flags)

---

## Impact Assessment

### Historical Data Quality
- Jan 8 & 12 player_daily_cache: **Still at 0 records** (no change)
- ML Feature Store for those dates: **Still using Phase 3 fallback**
- Feature quality scores: **Still degraded (77-84 vs 90+)**

### Production System
- **No impact**: The 50% confidence issue is independent of backfills
- **Historical analysis**: Degraded for Jan 8-12 date range
- **Future predictions**: Unaffected (daily pipeline working since OIDC fix on Jan 9)

### Priority
- **Backfills**: P2 - Nice to have for historical accuracy
- **Model deployment**: P0 - CRITICAL for production use

---

## Next Steps

1. ✅ Proceed with model deployment (critical path)
2. ⏸️ Pause backfill investigation until model deployed
3. 📋 File separate investigation task for data quality analysis
4. 📋 File bug reports for SQL errors found
5. 🔍 After model deployed, investigate Jan 8-12 data completeness in detail

---

## Related Files
- Investigation output: `/tmp/claude/-home-naji-code-nba-stats-scraper/tasks/b831c29.output`
- Processor code: `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`
- Completeness checker: `shared/utils/completeness_checker.py`
- Original incident docs: `docs/08-projects/current/catboost-v8-jan-2026-incident/ROOT_CAUSE_ANALYSIS.md`

---

## Decision Log

**2026-01-16 19:25 UTC**: Decided to **skip backfills** and **proceed with model deployment**

**Rationale**:
1. Backfills failed due to historical data quality (chicken-and-egg problem)
2. Model deployment is the critical production blocker (50% confidence issue)
3. Backfills improve historical data but don't unblock production
4. Better to fix production first, then investigate data quality issues separately
5. Investigation will require separate task to understand why Jan 8-12 data is incomplete

**Approved by**: Naji (user)
