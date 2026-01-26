# Spot Check Data Quality Investigation - 2026-01-26

## Summary

Investigation of 3 data quality issues found by the spot check system (Session 113).

## Priority 1: Mo Bamba Rolling Averages - 28% Error

### Issue
Mo Bamba (2025-01-20) has points_avg_last_5 off by 28.13%:
- Expected (recalculated): 6.40
- Cached: 4.60
- Difference: 28.13% (way above 2% tolerance)

### Root Cause: FOUND

The `player_daily_cache_processor.py` has an off-by-one date bug in the data extraction query.

**File**: `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`
**Line**: 425
**Current code**:
```python
WHERE game_date <= '{analysis_date.isoformat()}'  # BUG: Uses <=
```

**Problem**: The cache uses `game_date <= analysis_date` which INCLUDES games on the cache_date itself. But cache semantics specify that `cache_date` represents "features as of this date" meaning it should only include games BEFORE that date.

**Example for Mo Bamba**:
- Cache date: 2025-01-19
- Should include games: < 2025-01-19 (excluding 2025-01-19)
- Currently includes games: <= 2025-01-19 (including 2025-01-19)

**Games that SHOULD be in last 5** (game_date < 2025-01-19):
1. 2025-01-16: 4 points
2. 2025-01-15: 7 points
3. 2025-01-13: 5 points
4. 2025-01-08: 4 points
5. 2025-01-02: 12 points

**Sum = 32, Avg = 6.4** ✓ (matches expected)

**Games ACTUALLY used by cache** (game_date <= 2025-01-19):
1. 2025-01-19: 3 points (WRONG - should be excluded!)
2. 2025-01-16: 4 points
3. 2025-01-15: 7 points
4. 2025-01-13: 5 points
5. 2025-01-08: 4 points

**Sum = 23, Avg = 4.6** (matches cached value, but WRONG)

### Impact

This bug affects:
- **Check A**: Rolling averages (points_avg_last_5, points_avg_last_10)
- **Check D**: ML feature store (copies these values)
- **Check E**: Cache validation

All three checks failed for Mo Bamba with cascading errors from this single bug.

### Fix

Change line 425 in `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`:

```python
# Before
WHERE game_date <= '{analysis_date.isoformat()}'

# After
WHERE game_date < '{analysis_date.isoformat()}'
```

### Verification

After fix, need to:
1. Regenerate player_daily_cache for affected dates
2. Regenerate ml_feature_store_v2 (depends on cache)
3. Run spot check again to verify fix

## Issue 2: Terry Rozier Usage Rate - 2.02% Error

### Issue
Terry Rozier (2025-01-15) usage_rate off by 2.02%:
- Expected: 16.23
- Got: 15.90
- Difference: 2.02% (just outside 2% tolerance)

### Status
INVESTIGATING - This appears to be a precision/rounding issue rather than a systematic calculation bug.

### Next Steps
1. Check if usage_rate calculation uses appropriate precision
2. Consider if 2% tolerance is appropriate for usage_rate
3. Verify team_offense_game_summary data is correct

## Issue 3: Gui Santos Usage Rate - 2.44% Error

### Issue
Gui Santos (2025-01-15) usage_rate off by 2.44%:
- Expected: TBD
- Got: TBD
- Difference: 2.44%

### Status
TODO - Not yet investigated

## Broader Sweep Results (100 samples)

**Summary**: Confirmed widespread systematic issue
- **66% sample pass rate** (66/100)
- **34 players failed** with rolling average errors
- **Error range**: 2% to 37% for points_avg_last_5
- **Most common failures**: Rolling averages (Check A, D, E)
- **Secondary issue**: Usage rate precision (Check B)

**Pattern identified**: All rolling average failures are consistent with the date filter bug.

## Fixes Implemented

### Fix 1: Player Game Summary Extraction (Line 425)
**File**: `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`
**Function**: `_extract_player_game_data()`
**Change**: `game_date <= '{analysis_date}'` → `game_date < '{analysis_date}'`

### Fix 2: Team Offense Data Extraction (Line 454)
**File**: `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`
**Function**: `_extract_team_offense_data()`
**Change**: `game_date <= '{analysis_date}'` → `game_date < '{analysis_date}'`

**Rationale**: Both queries extract data for cache calculation. Cache semantics require "as of" behavior - features should only include games BEFORE the cache_date, not including it.

## Impact Assessment

### Tables Affected
1. **nba_precompute.player_daily_cache** - Primary issue (wrong rolling averages)
2. **nba_predictions.ml_feature_store_v2** - Cascading issue (copies bad values from cache)
3. Predictions using these features - Potential accuracy impact

### Time Period Affected
- All dates processed with the buggy code
- Likely spans entire 2024-25 season (October 2024 - January 2025)
- Estimated: ~100+ days × ~450 players = ~45,000 affected cache records

## Recommendations

### 1. **URGENT**: Regenerate Affected Data

Priority order:
1. Regenerate `player_daily_cache` for affected dates (2024-10-01 to 2025-01-26)
2. Regenerate `ml_feature_store_v2` (depends on cache)
3. Consider re-running predictions for critical dates if accuracy impact is measurable

### 2. **Usage Rate Precision** (Lower Priority)

Multiple players show 2-5% usage_rate mismatches:
- Could be floating-point precision issue
- Could be rounding differences in formula
- Recommend: Investigate usage_rate calculation after fixing rolling averages

### 3. **Validation** (Post-Fix)

Run spot checks to verify fix:
```bash
# Verify specific known failures
python scripts/spot_check_data_accuracy.py --player-lookup mobamba --date 2025-01-20
python scripts/spot_check_data_accuracy.py --player-lookup joshgiddey --date 2025-01-20

# Broad validation
python scripts/spot_check_data_accuracy.py --samples 100 --start-date 2025-01-15 --end-date 2025-01-25
```

## Files Modified

1. `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`
   - Line 425: Fixed player game data extraction
   - Line 454: Fixed team offense data extraction

## Data Regeneration Plan

### Phase 1: Recent Data (High Priority)
```bash
# Regenerate last 30 days (most critical for predictions)
for date in $(seq -f "2025-01-%02g" 1 26); do
  python data_processors/precompute/player_daily_cache/player_daily_cache_processor.py \
    --analysis_date $date
done
```

### Phase 2: Season Data (Medium Priority)
```bash
# Backfill entire 2024-25 season
python backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
  --start-date 2024-10-01 \
  --end-date 2025-01-26
```

### Phase 3: Downstream Updates (Post Phase 1-2)
```bash
# Regenerate ML feature store (depends on cache)
python data_processors/predictions/ml_feature_store_v2_processor.py \
  --start-date 2024-10-01 \
  --end-date 2025-01-26
```

## Testing Verification

After regeneration, verify fix with spot checks:

```bash
# 1. Test known failures from sweep
python scripts/spot_check_data_accuracy.py --player-lookup mobamba --date 2025-01-20
python scripts/spot_check_data_accuracy.py --player-lookup joshgiddey --date 2025-01-20
python scripts/spot_check_data_accuracy.py --player-lookup justinchampagnie --date 2025-01-08

# 2. Broad validation across date range
python scripts/spot_check_data_accuracy.py --samples 100 --start-date 2025-01-01 --end-date 2025-01-26

# 3. Expected result: >95% accuracy (vs current 30%)
```

## Root Cause Analysis

**What went wrong**: Date filter used `<=` instead of `<` in cache data extraction

**Why it matters**: Cache represents "features as of cache_date" meaning it should only include historical data (games before that date), not including the date itself

**How it propagated**:
1. Wrong data in `player_daily_cache`
2. `ml_feature_store_v2` copied wrong values
3. Spot check correctly detected the discrepancy

**Lesson learned**: Cache semantics must be clearly documented and enforced in code comments
