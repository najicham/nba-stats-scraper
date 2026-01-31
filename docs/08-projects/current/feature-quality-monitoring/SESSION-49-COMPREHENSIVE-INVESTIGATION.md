# Session 49: Comprehensive ML Feature Store Investigation

**Date:** 2026-01-31
**Status:** Investigation complete, fixes committed, backfill pending

---

## Executive Summary

Session 49 conducted a comprehensive investigation of all 37 ML features in the feature store. We discovered **6 critical/high-severity bugs** affecting the majority of historical data.

### Bugs Found and Fixed

| Bug | Feature | Severity | Records Affected | Status |
|-----|---------|----------|------------------|--------|
| Wrong comparison | `back_to_back` (16) | CRITICAL | 128,141 (100%) | ✅ Fixed |
| Missing field passthrough | `team_win_pct` (24) | CRITICAL | 127,869 (99.8%) | ✅ Fixed |
| Upstream NULL | `usage_spike_score` (8) | HIGH | 126,613 (98.8%) | ❌ Upstream issue |
| Upstream NULL | `pace_score` (7) | HIGH | 120,314 (93.9%) | ❌ Upstream issue |
| Data sourcing | `injury_risk` (10) | LOW | 127,238 (99.3%) | ✅ Working as designed |
| Impossible values | `games_in_last_7_days` (4) | HIGH | 546 (since Dec 2025) | ⚠️ Needs investigation |

---

## Detailed Findings

### 1. back_to_back Bug (CRITICAL) ✅ FIXED

**File:** `data_processors/analytics/upcoming_player_game_context/player_stats.py:61`

**Bug:**
```python
# WRONG: days_rest == 0 means same-day (impossible)
back_to_back = (days_rest == 0)

# CORRECT: consecutive days are 1 day apart
back_to_back = (days_rest == 1)
```

**Impact:** 100% of records have `back_to_back = 0`. Should be ~15-20% true.

**Fix Commit:** `a7381972`

**Irony:** Same file correctly uses `== 1` at line 82 for `back_to_backs_last_14_days`.

---

### 2. team_win_pct Bug (CRITICAL) ✅ FIXED

**File:** `data_processors/precompute/ml_feature_store/feature_extractor.py:154,179`

**Bug:** `team_abbr` not included in `get_players_with_games()` queries.

**Impact:** 99.8% of records have `team_win_pct = 0.5` (default).

**Fix Commit:** `1c8d84d3`

---

### 3. usage_spike_score (HIGH) ❌ UPSTREAM ISSUE

**Root Cause:** `projected_usage_rate` is 100% NULL in `upcoming_player_game_context`

**Evidence:**
```sql
SELECT COUNT(*), COUNTIF(projected_usage_rate IS NULL)
FROM nba_analytics.upcoming_player_game_context
-- Result: 191,151 total, 191,151 NULL (100%)
```

**Status:** Requires implementation of usage rate calculation in Phase 3

---

### 4. pace_score (HIGH) ❌ UPSTREAM ISSUE

**Root Cause:** `opponent_pace_last_10` is 65-100% NULL historically

**Status:** Upstream calculation may be broken or incomplete

---

### 5. injury_risk (LOW) ✅ WORKING AS DESIGNED

**Explanation:** 99.3% zeros is CORRECT because:
- `player_status` is only populated when player appears on injury report
- No injury report = NULL = healthy = 0.0 injury_risk
- This is correct behavior, not a bug

---

### 6. games_in_last_7_days (HIGH) ⚠️ NEEDS INVESTIGATION

**Issue:** Values up to 24 found (impossible, max should be ~5)

**When:** Started December 2025 (546 affected records)

**Status:** Needs separate investigation

---

## CatBoost V8 Model Features

**Actual feature count:** 34 features (not 33 or 37)

The model file is named `catboost_v8_33features_*.cbm` but uses 34 features:
- 25 base features
- 4 Vegas features
- 2 opponent history features
- 2 minutes/PPM features
- 1 shot zone availability flag (added 2026-01-25)

The 37-feature version in ML feature store includes additional experimental features (33-36: dnp_rate, pts_slope, zscore, breakout_flag).

---

## Prevention Mechanisms Added

### 1. Batch Variance Validation (Commit 72d1ba8d)

```python
FEATURE_VARIANCE_THRESHOLDS = {
    24: (0.05, 5, 'team_win_pct'),    # Catches constant 0.5
    5: (5.0, 10, 'fatigue_score'),    # Catches constant 50.0
    7: (0.5, 5, 'pace_score'),        # Catches constant 0.0
    # ... 10 features monitored
}
```

### 2. Pre-write Range Validation (Commit 0ea398bd)

37 features validated against expected ranges before writing to BigQuery.

### 3. Feature Health Monitoring Table

`nba_monitoring_west2.feature_health_daily` tracks daily statistics per feature.

---

## Backfill Requirements

### Priority 1: Code Fixes Already Deployed

| Feature | Fix | Backfill Scope |
|---------|-----|----------------|
| `team_win_pct` | ✅ Deployed | 127,869 records |
| `back_to_back` | ✅ Needs deploy | 128,141 records |

### Priority 2: Upstream Fixes Needed First

| Feature | Upstream Fix Needed | Backfill Scope |
|---------|---------------------|----------------|
| `usage_spike_score` | Implement usage rate calc | 126,613 records |
| `pace_score` | Fix opponent_pace_last_10 | 120,314 records |

### Backfill Order

1. Deploy Phase 3 (back_to_back fix)
2. Backfill `upcoming_player_game_context` (Phase 3)
3. Backfill `player_composite_factors` (Phase 4)
4. Backfill `ml_feature_store_v2` (Phase 4)

---

## Admin Dashboard Enhancements Proposed

Add "ML Feature Health" tab with:

1. **Feature Distribution Cards** - Per-feature mean, stddev, zero%, null%
2. **Health Status Grid** - Green/yellow/red for each feature
3. **Historical Comparison** - Current vs 30-day baseline
4. **Variance Alerts** - Features with suspiciously low variance
5. **Data Source Coverage** - Phase 4 vs Phase 3 fallback rates

Query source: `nba_monitoring_west2.feature_health_daily`

---

## Files Changed in Session 49

| File | Change | Commit |
|------|--------|--------|
| `feature_extractor.py` | Add team_abbr to queries | `1c8d84d3` |
| `ml_feature_store_processor.py` | Add variance validation | `72d1ba8d` |
| `player_stats.py` | Fix back_to_back calculation | `a7381972` |

---

## Next Steps

1. **Deploy Phase 3** with back_to_back fix
2. **Investigate** games_in_last_7_days bug (Dec 2025+)
3. **Implement** usage rate calculation for usage_spike_score
4. **Fix** opponent_pace_last_10 calculation
5. **Add** ML Feature Health tab to admin dashboard
6. **Backfill** all affected data after fixes deployed

---

## Key Learnings

1. **Comparison operators matter**: `== 0` vs `== 1` for consecutive days
2. **Field passthrough is fragile**: Easy to forget fields in query chains
3. **Hardcoded defaults mask bugs**: Constants like 0.5 look plausible
4. **Upstream NULLs cascade**: 100% NULL upstream → broken downstream
5. **Variance validation catches bugs**: Zero variance = something wrong
6. **Same-file inconsistency**: back_to_back bug existed while correct logic was 20 lines away

---

*Session 49 - Comprehensive ML Feature Store Investigation*
*Co-Authored-By: Claude Opus 4.5*
