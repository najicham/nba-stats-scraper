# Spot Check Data Quality Fix - Project

**Project ID**: `spot-check-data-quality-fix`
**Created**: 2026-01-26
**Status**: 🔧 IN PROGRESS - Code fix complete, data regeneration pending
**Priority**: 🔴 CRITICAL
**Owner**: Data Engineering

---

## Quick Links

- [Investigation Findings](../../../investigations/SPOT-CHECK-FINDINGS-2026-01-26.md)
- [Fix Summary](../../../investigations/SPOT-CHECK-FIX-SUMMARY-2026-01-26.md)
- [Spot Check System Docs](../../../06-testing/SPOT-CHECK-SYSTEM.md)

---

## Problem Statement

The spot check system (Session 113) identified a critical bug causing rolling averages to be calculated incorrectly in `player_daily_cache`. This affected 34% of sampled players with errors ranging from 2% to 37%.

**Impact**: ~53,100 cache records with incorrect rolling averages → cascading to ML features → potential prediction inaccuracy.

---

## Solution Overview

**Root Cause**: Date filter used `<=` instead of `<` in cache data extraction
**Fix**: Changed two date filters to correctly implement cache semantics
**Status**: ✅ Code fix complete, ⏳ Data regeneration pending

---

## Implementation Status

### ✅ Phase 0: Code Fix (COMPLETE)
- [x] Identify root cause
- [x] Fix `_extract_player_game_data()` date filter (line 425)
- [x] Fix `_extract_team_offense_data()` date filter (line 454)
- [x] Verify fix with test query
- [x] Document findings

### ⏳ Phase 1: Recent Data Regeneration (PENDING)
**Timeline**: 3-5 hours
**Command**:
```bash
python backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
  --start-date 2024-12-27 \
  --end-date 2025-01-26 \
  --backfill-mode
```

### ⏳ Phase 2: Validation (PENDING)
**Timeline**: 30 minutes
**Command**:
```bash
# Test known failures
python scripts/spot_check_data_accuracy.py --player-lookup mobamba --date 2025-01-20
python scripts/spot_check_data_accuracy.py --player-lookup joshgiddey --date 2025-01-20

# Broad validation
python scripts/spot_check_data_accuracy.py --samples 100 --start-date 2025-01-01 --end-date 2025-01-26
```

### ⏳ Phase 3: Full Season Regeneration (PENDING)
**Timeline**: 12-15 hours
**Command**:
```bash
python backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
  --start-date 2024-10-01 \
  --end-date 2025-01-26 \
  --backfill-mode
```

### ⏳ Phase 4: ML Feature Store Update (PENDING)
**Timeline**: 8-10 hours
**Command**:
```bash
python backfill_jobs/predictions/ml_feature_store_v2_backfill.py \
  --start-date 2024-10-01 \
  --end-date 2025-01-26 \
  --backfill-mode
```

---

## Key Metrics

### Before Fix
- **Spot check accuracy**: 30% (180/600 checks passed)
- **Sample pass rate**: 66% (66/100 players)
- **Failures**: 34 players with rolling average errors
- **Error range**: 2% to 37%

### After Fix (Expected)
- **Spot check accuracy**: >95%
- **Sample pass rate**: >95%
- **Rolling average errors**: <2% (within tolerance)

---

## Files Modified

```
data_processors/precompute/player_daily_cache/player_daily_cache_processor.py
  - Line 425: Fixed player game data extraction
  - Line 454: Fixed team offense data extraction
```

---

## Documentation Created

```
docs/investigations/SPOT-CHECK-FINDINGS-2026-01-26.md
docs/investigations/SPOT-CHECK-FIX-SUMMARY-2026-01-26.md
docs/08-projects/current/spot-check-data-quality-fix/README.md (this file)
```

---

## Next Steps

1. **Run Phase 1 regeneration** (last 30 days) - URGENT
2. **Validate Phase 1** with spot checks
3. **Run Phase 3 regeneration** (full season)
4. **Update ML feature store** (Phase 4)
5. **Final validation** with comprehensive spot check
6. **Investigate usage_rate precision** (lower priority)

---

## Timeline

| Phase | Task | Duration | Status |
|-------|------|----------|--------|
| 0 | Code fix | 1 hour | ✅ DONE |
| 1 | Recent data (30d) | 3-5 hours | ⏳ PENDING |
| 2 | Validate Phase 1 | 30 min | ⏳ PENDING |
| 3 | Full season (118d) | 12-15 hours | ⏳ PENDING |
| 4 | ML features | 8-10 hours | ⏳ PENDING |
| 5 | Final validation | 1 hour | ⏳ PENDING |

**Total**: ~24-32 hours (can run overnight)

---

## Contact

**Team**: Data Engineering
**Last Updated**: 2026-01-26 09:20 PST
