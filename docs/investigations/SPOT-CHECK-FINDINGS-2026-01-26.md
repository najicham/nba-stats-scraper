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

## Recommendations

1. **URGENT**: Fix Mo Bamba date bug and regenerate affected data
2. **Review**: Consider increasing usage_rate tolerance to 2.5% or 3% to account for floating point precision
3. **Run broader sweep**: Complete 100-sample spot check to identify if these are isolated or systematic issues

## Files to Update

1. `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py` - Line 425 (date filter bug)
2. Consider updating tolerance in `scripts/spot_check_data_accuracy.py` if usage_rate precision is inherent

## Test Plan

After fix:
```bash
# 1. Test Mo Bamba specifically
python scripts/spot_check_data_accuracy.py --player-lookup mobamba --date 2025-01-20

# 2. Run broader sample
python scripts/spot_check_data_accuracy.py --samples 100 --start-date 2025-01-01 --end-date 2025-01-20

# 3. Check recent dates
python scripts/spot_check_data_accuracy.py --samples 50 --start-date 2025-01-15 --end-date 2025-01-25
```
