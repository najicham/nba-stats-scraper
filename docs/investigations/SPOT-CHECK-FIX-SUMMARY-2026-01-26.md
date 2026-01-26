# Spot Check Data Quality Fix - Summary

**Date**: 2026-01-26
**Status**: ✅ FIX IMPLEMENTED
**Impact**: CRITICAL - Affects ~45,000 cache records

---

## Executive Summary

The spot check system (Session 113) identified a critical bug in `player_daily_cache_processor.py` causing rolling averages to be calculated incorrectly. The bug affected 34% of sampled players with errors ranging from 2% to 37%.

**Root Cause**: Date filter used `<=` instead of `<` when extracting historical games for cache calculation.

**Fix**: Changed two date filters from `<=` to `<` to correctly implement cache semantics.

**Status**: Code fix complete. Data regeneration pending.

---

## Bug Details

### What Was Wrong

The cache processor used:
```sql
WHERE game_date <= '{analysis_date}'  -- WRONG: includes games ON analysis_date
```

Should have been:
```sql
WHERE game_date < '{analysis_date}'   -- CORRECT: only games BEFORE analysis_date
```

### Why It Mattered

Cache semantics: `cache_date` represents "features as of this date" meaning it should only include **historical data** (games before that date), not including the date itself.

### Example Impact (Mo Bamba, cache_date = 2025-01-19)

**BEFORE FIX** (using `<=`):
- Included game on 2025-01-19 (3 points) ❌
- Last 5 games: [3, 4, 7, 5, 4] = 4.6 avg
- Error: 28.13% off

**AFTER FIX** (using `<`):
- Excluded game on 2025-01-19 ✓
- Last 5 games: [4, 7, 5, 4, 12] = 6.4 avg
- Matches expected value ✓

---

## Scope of Impact

### Broader Sweep Results (100 samples, 2025-01-01 to 2025-01-20)
- **34/100 players failed** (34% failure rate)
- **Rolling average errors**: 2% to 37%
- **Overall check accuracy**: 30% (should be >95%)

### Affected Tables
1. **nba_precompute.player_daily_cache** - Primary (wrong rolling averages stored)
2. **nba_predictions.ml_feature_store_v2** - Cascading (copies values from cache)
3. **Predictions** - Potential accuracy impact (uses ML features)

### Estimated Records Affected
- **Time period**: 2024-10-01 to 2025-01-26 (~118 days)
- **Players per day**: ~450 active
- **Total cache records**: ~53,100 affected

---

## Fixes Implemented

### Fix 1: Player Game Summary Extraction
**File**: `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`
**Line**: 425
**Function**: `_extract_player_game_data()`

```python
# BEFORE
WHERE game_date <= '{analysis_date.isoformat()}'

# AFTER
WHERE game_date < '{analysis_date.isoformat()}'  # FIX: Changed <= to <
```

### Fix 2: Team Offense Data Extraction
**File**: `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`
**Line**: 454
**Function**: `_extract_team_offense_data()`

```python
# BEFORE
WHERE game_date <= '{analysis_date.isoformat()}'

# AFTER
WHERE game_date < '{analysis_date.isoformat()}'  # FIX: Changed <= to <
```

### Verification

Tested with Mo Bamba (known failure):
```sql
-- Query with FIX produces correct values
avg_last_5 = 6.4 (expected: 6.4) ✓
avg_last_10 = 3.8 (expected: 3.8) ✓
```

---

## Data Regeneration Plan

### Phase 1: Recent Data (URGENT - 30 days)
**Priority**: HIGH - Most critical for active predictions
**Timeline**: Run immediately

```bash
# Regenerate last 30 days
python backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
  --start-date 2024-12-27 \
  --end-date 2025-01-26 \
  --backfill-mode
```

**Expected time**: ~3-5 hours
**Records**: ~13,500 (30 days × 450 players)

### Phase 2: Season Data (HIGH - Full season)
**Priority**: HIGH - Complete season accuracy
**Timeline**: Run after Phase 1

```bash
# Backfill entire 2024-25 season
python backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
  --start-date 2024-10-01 \
  --end-date 2025-01-26 \
  --backfill-mode
```

**Expected time**: ~12-15 hours
**Records**: ~53,100 (118 days × 450 players)

### Phase 3: ML Feature Store (MEDIUM)
**Priority**: MEDIUM - Update downstream dependencies
**Timeline**: Run after Phase 2

```bash
# Regenerate ML features (depends on cache)
python backfill_jobs/predictions/ml_feature_store_v2_backfill.py \
  --start-date 2024-10-01 \
  --end-date 2025-01-26 \
  --backfill-mode
```

**Expected time**: ~8-10 hours

---

## Validation Plan

### Step 1: Verify Known Failures (Post Phase 1)

Test specific players that failed in original sweep:

```bash
# Mo Bamba (28% error before fix)
python scripts/spot_check_data_accuracy.py --player-lookup mobamba --date 2025-01-20

# Josh Giddey (27% error)
python scripts/spot_check_data_accuracy.py --player-lookup joshgiddey --date 2025-01-20

# Justin Champagnie (37% error)
python scripts/spot_check_data_accuracy.py --player-lookup justinchampagnie --date 2025-01-08
```

**Expected**: All checks pass (0% error)

### Step 2: Broad Validation (Post Phase 2)

Run comprehensive spot check across regenerated dates:

```bash
python scripts/spot_check_data_accuracy.py \
  --samples 100 \
  --start-date 2025-01-01 \
  --end-date 2025-01-26
```

**Expected**: >95% accuracy (vs 30% before fix)

### Step 3: Edge Cases (Optional)

Test edge cases:
- Early season games (limited history)
- Players with trades (team changes)
- Bench players (low minutes)

---

## Secondary Issues (Lower Priority)

### Usage Rate Precision

Multiple players showed 2-6% usage_rate mismatches:
- Terry Rozier: 2.02%
- Gui Santos: 2.44%
- ~15 others: 2-6%

**Analysis**:
- May be floating-point precision differences
- May be rounding in formula implementation
- Not blocking for fix deployment

**Recommendation**: Investigate after rolling average fix validated. May need to:
1. Review usage_rate formula precision
2. Consider increasing tolerance to 2.5-3%
3. Verify team_offense_game_summary accuracy

---

## Timeline

| Phase | Task | Duration | Start | Status |
|-------|------|----------|-------|--------|
| 0 | Code fix | 1 hour | 2026-01-26 09:00 | ✅ DONE |
| 1 | Regenerate last 30 days | 3-5 hours | 2026-01-26 10:00 | ⏳ PENDING |
| 2 | Validate Phase 1 | 30 min | After Phase 1 | ⏳ PENDING |
| 3 | Regenerate full season | 12-15 hours | After Phase 2 | ⏳ PENDING |
| 4 | Validate Phase 3 | 1 hour | After Phase 3 | ⏳ PENDING |
| 5 | Regenerate ML features | 8-10 hours | After Phase 3 | ⏳ PENDING |
| 6 | Final validation | 1 hour | After Phase 5 | ⏳ PENDING |

**Total estimated time**: ~24-32 hours (can run overnight)

---

## Lessons Learned

1. **Cache semantics must be explicit**: Add comments to clarify "as of" behavior
2. **Spot check system works**: Caught a critical bug that would have affected predictions
3. **Cascading failures**: One bug in cache → ML features → predictions
4. **Date filter semantics matter**: `<` vs `<=` is critical for temporal data

## Recommendations

1. ✅ **Deploy fix immediately** - Code changes complete
2. 🔄 **Run Phase 1 regeneration** - Start with last 30 days
3. 📊 **Monitor spot check results** - Validate improvement
4. 📝 **Document cache semantics** - Add explicit comments to code
5. 🔍 **Investigate usage_rate** - Lower priority, after main fix validated

---

## Files Modified

- `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`
  - Line 425: Fixed player game data extraction (date filter)
  - Line 454: Fixed team offense data extraction (date filter)

## Documentation Created

- `docs/investigations/SPOT-CHECK-FINDINGS-2026-01-26.md` - Detailed investigation
- `docs/investigations/SPOT-CHECK-FIX-SUMMARY-2026-01-26.md` - This summary

---

**Contact**: Data Engineering Team
**Last Updated**: 2026-01-26 09:15:00 PST
