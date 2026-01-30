# Session 24 Investigation Findings - CatBoost V8 Performance Analysis

**Date:** 2026-01-29
**Author:** Claude Opus 4.5
**Status:** ROOT CAUSES IDENTIFIED

---

## Executive Summary

The investigation into CatBoost V8's performance drop from 74% (2024-25 season) to 52% (Jan 2026) identified **three root causes**:

| Root Cause | Impact | Status |
|------------|--------|--------|
| **Feature Passing Bug** | Predictions inflated by +29 points | Documented in Session 20, needs fix |
| **Confidence Scale Change** | 50% of 2025-26 predictions are coin flips | Bug introduced Dec 10, 2025 |
| **BettingPros Data Gap** | Lower quality ODDS_API lines used | Oct-Nov 2025 missing |

**Key Finding:** The model itself is NOT broken. Percent-scale predictions still achieve 66-75% hit rate. The decimal-scale forward-looking predictions are broken due to the feature passing bug.

---

## The Model Works: Evidence from 2024-25 Season

### Experiment D1 Results

| Metric | Value |
|--------|-------|
| **Predictions** | 13,315 |
| **Hit Rate** | **74.25%** |
| **ROI** | **+41.75%** |

### Monthly Performance (No Decay)

| Month | Hit Rate | Months Since Training |
|-------|----------|----------------------|
| Nov 2024 | 77.44% | 6 |
| Dec 2024 | 74.95% | 7 |
| Jan 2025 | 72.82% | 8 |
| Feb 2025 | 71.99% | 9 |
| Mar 2025 | 73.32% | 10 |
| Apr 2025 | 74.49% | 11 |
| May 2025 | 79.44% | 12 |
| Jun 2025 | 79.12% | 13 |

**The model maintained 72-79% hit rate for 13 months after training ended.**

### By Confidence Tier

| Tier | Predictions | Hit Rate | ROI |
|------|-------------|----------|-----|
| 95%+ | 1,562 | **79.64%** | +52.04% |
| 90-95% | 8,317 | 75.42% | +43.98% |
| 85-90% | 3,345 | 68.79% | +31.32% |

### By Direction

| Direction | Hit Rate | ROI |
|-----------|----------|-----|
| UNDER | **76.54%** | +46.11% |
| OVER | 72.21% | +37.85% |

**Best segment: High-confidence (90%+) UNDER = 78.09% hit rate**

---

## Root Cause #1: Feature Passing Bug (CRITICAL)

### The Bug

**Location:** `predictions/worker/prediction_systems/catboost_v8.py:_prepare_feature_vector()`

The `predict()` method expects Vegas/opponent/PPM features as **function parameters**, but the worker only passes the features dict. This causes features 25-32 to use **wrong fallback values**.

### Worker Calls

```python
# What the worker passes:
catboost.predict(
    player_lookup=player_lookup,
    features=features,
    betting_line=line_value
    # Missing: vegas_line, opponent_avg, ppm_avg_last_10, etc.!
)
```

### Feature Impact

| Feature | Index | Production Uses | Should Be | Error |
|---------|-------|-----------------|-----------|-------|
| vegas_line | 25 | season_avg (30.1) | 29.68 | -0.4 |
| vegas_opening | 26 | season_avg (30.1) | 31.50 | -1.4 |
| vegas_line_move | 27 | 0.0 | -1.82 | +1.8 |
| **has_vegas_line** | 28 | **0.0** | **1.0** | **-1.0** |
| opponent_avg | 29 | season_avg (30.1) | 25.0 | +5.1 |
| games_vs_opponent | 30 | 0.0 | 14.0 | -14.0 |
| minutes_avg | 31 | 35.0 | 35.0 | OK |
| **ppm_avg** | 32 | **0.4** | **0.868** | **-0.47** |

### Result

For Anthony Edwards on Jan 28:
- **Production prediction:** 64.48 points → clamped to 60
- **Correct prediction:** 34.96 points
- **Error:** +29.52 points!

### Evidence in Data

| Metric | 2024-25 | 2025-26 | Change |
|--------|---------|---------|--------|
| Avg Edge (predicted - line) | 0.50 pts | 3.76 pts | **+652%** |
| OVER edge | +4.13 | +8.99 | **+118%** |
| Predictions >50 pts | 0 | 128 | New bug |
| P95 predicted | 28.1 | 42.1 | +50% |

### Fix Applied (Session 24)

**File:** `predictions/worker/worker.py` (lines 815-870)

The fix adds a v3.7 feature enrichment block that populates the CatBoost V8 required features:

```python
# v3.7 (Session 24 FIX): Add CatBoost V8 required features
actual_prop = line_source_info.get('actual_prop_line')
if actual_prop is not None:
    features['vegas_points_line'] = actual_prop
    features['vegas_opening_line'] = actual_prop
    features['vegas_line_move'] = 0.0
    features['has_vegas_line'] = 1.0  # CRITICAL!
else:
    features['has_vegas_line'] = 0.0

# PPM calculated from available data
features['ppm_avg_last_10'] = pts_avg / mins_avg
```

**What changed:**
1. `vegas_points_line` now populated from `actual_prop_line`
2. `has_vegas_line` = 1.0 when we have a line (was 0.0 before!)
3. `ppm_avg_last_10` calculated from points/minutes (was defaulting to 0.4)

---

## Root Cause #2: Confidence Scale Change

### Timeline

| Date | Event | Scale |
|------|-------|-------|
| Before Dec 10, 2025 | Predictions stored | 0-100 (percent) |
| Dec 10, 2025 | Commit `6bccfdd1` deployed | Changed to 0-1 |
| Jan 9, 2026 | Backfill run | Used 0-100 (old code?) |
| Jan 11, 2026+ | Forward-looking | Uses 0-1 (decimal) |

### Performance by Scale

| Period | Scale | Predictions | Hit Rate |
|--------|-------|-------------|----------|
| 2024-25 | Percent (0-100) | 13,315 | **74.25%** |
| 2025 Q4 | Percent (0-100) | 1,133 | **74.67%** |
| 2025 Q4 | Decimal (0-1) | 2,952 | **55.49%** |
| 2026 | Percent (0-100) | 730 | **66.30%** |
| 2026 | Decimal (0-1) | 1,607 | **49.97%** |

### Key Insight

**Percent-scale predictions still work (66-75% hit rate). Decimal-scale predictions are coin flips (50%).**

This is because the decimal-scale predictions are the **forward-looking** predictions that use the broken feature passing code. The percent-scale predictions are from the **Jan 9 backfill** which somehow used correct features (or had data leakage).

### Current State

The `normalize_confidence()` function now correctly converts:
```python
def normalize_confidence(confidence: float, system_id: str) -> float:
    if system_id in ['catboost_v8', 'xgboost_v1', 'similarity_balanced_v1']:
        return confidence / 100.0  # Convert 0-100 to 0-1
    return confidence
```

**The scale itself is fixed.** The issue is that decimal-scale predictions correlate with the broken feature passing bug.

---

## Root Cause #3: BettingPros Data Gap

### Missing Data

| Month | BettingPros | Odds API |
|-------|-------------|----------|
| Oct 2025 | **MISSING** | 5,064 lines |
| Nov 2025 | **MISSING** | 16,236 lines |
| Dec 2025 | 11,921 | 16,985 |
| Jan 2026 | 135,942* | 39,384 |

*Jan 2026 BettingPros volume is 10x normal - likely duplicates.

### Impact on Performance

| Line Source | 2025-26 Hit Rate |
|-------------|------------------|
| ODDS_API | **55.49%** |
| BETTINGPROS | **65.77%** |

The 10 percentage point difference means that when BettingPros lines are unavailable, predictions must use lower-quality ODDS_API lines.

---

## Why Backfill Shows 74% But Forward-Looking Shows 52%

### The Mystery

| Prediction Type | Hit Rate |
|-----------------|----------|
| Jan 9 Backfill (percent scale) | 74.74% |
| Forward-looking (decimal scale) | 52.03% |

### Explanation

1. **Backfill predictions** were created on Jan 9, 2026 using historical feature store data
2. **Forward-looking predictions** are created in production using the broken feature passing code
3. The backfill code path may have correctly read features from the feature store
4. The production worker code path doesn't pass features correctly to the model

**OR** there's data leakage in the backfill (unlikely since decimal backfill also shows 53.87%).

### Most Likely Explanation

The backfill script reads features differently than the production worker:
- Backfill: Reads from `ml_feature_store_v2` table with all features pre-computed
- Production: Computes features on-the-fly and passes to model incorrectly

---

## Forward-Looking Reality

| Type | Predictions | Hit Rate |
|------|-------------|----------|
| All forward-looking (Jan 2026) | 813 | **52.03%** |
| Retroactive (Dec 2025) | 2,716 | 64.03% |
| Retroactive (Nov 2025) | 1,369 | 54.42% |

Only **11% of 2025-26 predictions** (1,737 of 15,526) were truly forward-looking.

---

## Action Items

### Immediate (P0)

1. **Fix feature passing bug** - Update `catboost_v8.py` to read features from dict
2. **Deploy and verify** - Confirm predictions are reasonable (not 60+ points)
3. **Add extreme prediction warnings** - Log when prediction > 55 or < 5

### Short-term (P1)

4. **Investigate BettingPros scraper** - Restore Oct-Nov 2025 data collection
5. **Add feature validation** - Warn when key features use defaults
6. **Standardize confidence scale** - Ensure all systems output 0-100

### Medium-term (P2)

7. **Continue walk-forward experiments** - Understand optimal training window
8. **Set up model monitoring** - Alert on performance degradation
9. **Create champion-challenger framework** - Test new models safely

---

## Experiment Results Summary

### D1: Existing V8 on 2024-25 Season

| Metric | Value |
|--------|-------|
| Hit Rate | 74.25% |
| ROI | +41.75% |
| Best Segment | High-conf UNDER (78.09%) |
| Decay | None (maintained 72-79% for 13 months) |

**Conclusion:** Model works well when features are passed correctly.

---

## Key Learnings

1. **The model isn't broken** - It achieved 74% on 2024-25 out-of-sample data
2. **Feature passing is critical** - Wrong defaults cause +29 point errors
3. **Backfill vs production code paths differ** - Need to ensure consistency
4. **Line source matters** - BETTINGPROS outperforms ODDS_API by 10pp
5. **Confidence scale was red herring** - Real issue is feature passing

---

## Files Referenced

| File | Purpose |
|------|---------|
| `predictions/worker/prediction_systems/catboost_v8.py` | Feature passing bug location |
| `predictions/worker/data_loaders.py` | Confidence normalization |
| `ml/train_final_ensemble_v8.py` | Training script |
| `docs/09-handoff/2026-01-29-SESSION-20-CATBOOST-V8-FIX-AND-SAFEGUARDS.md` | Full fix documentation |

---

*Document created: 2026-01-29 Session 24*
*Author: Claude Opus 4.5*
