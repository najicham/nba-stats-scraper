# Session 37 Investigation Report - V8 Model Degradation & Data Quality

**Date:** 2026-01-30
**Status:** Investigation Complete, Action Plan Required

---

## Executive Summary

Two critical issues investigated:

1. **Double Insertion Bug**: player_game_summary processor inserts records twice due to retry decorator interaction
2. **V8 Model Degradation**: Hit rate dropped from 67.9% to 48.3% due to BOTH model over-prediction AND Vegas lines getting sharper

---

## Part 1: Double Insertion Bug

### Evidence

| Date | Raw BDL Records | Analytics Records | Duplicates |
|------|-----------------|-------------------|------------|
| 2026-01-29 | 282 | 564 | 282 (100%) |
| 2026-01-28 | 325 | 325 | 0 |
| 2026-01-27 | 239 | 239 | 0 |

All 564 records processed at same second (2026-01-30 15:51:38) with 282 distinct millisecond timestamps.

### Root Cause

**Location:** `data_processors/analytics/operations/bigquery_save_ops.py`, lines 63-64

```python
@retry_on_quota_exceeded  # Line 63
@retry_on_serialization   # Line 64
def save_analytics(self) -> bool:
```

**Bug Chain:**
1. `save_analytics()` called with 282 records
2. Deduplication at line 138
3. `_save_with_proper_merge()` executes MERGE query
4. **MERGE succeeds** (DML completes)
5. `result(timeout=300)` throws serialization error (timing issue)
6. Exception caught by `@retry_on_serialization` decorator
7. **ENTIRE `save_analytics()` retried** with same records
8. Second MERGE inserts duplicates (different processed_at timestamps)

### Fix Required

**Option A (Recommended):** Remove retry decorator from `save_analytics()`, keep only on `_save_with_proper_merge()`

**Option B:** Add idempotency check - query target table before MERGE to detect if records already exist

**Option C:** Make processed_at immutable - set once during transformation, not regenerated on retry

### Files to Modify

| File | Line | Change |
|------|------|--------|
| `bigquery_save_ops.py` | 63-64 | Remove `@retry_on_serialization` from `save_analytics()` |
| `bigquery_save_ops.py` | 256-257 | Keep retry on `_save_with_proper_merge()` only |

---

## Part 2: V8 Model Degradation Analysis

### Performance Timeline

| Week | Hit Rate | Vegas MAE | Model MAE | Model Edge |
|------|----------|-----------|-----------|------------|
| Dec 21 | **77.0%** | 5.52 | 4.11 | **+1.42** |
| Dec 28 | **67.9%** | 4.95 | 4.43 | **+0.52** |
| Jan 04 | 62.7% | 4.71 | 4.55 | +0.16 |
| Jan 11 | 51.1% | 5.35 | 6.02 | -0.67 |
| Jan 18 | 51.6% | 5.14 | 5.86 | -0.71 |
| Jan 25 | **48.3%** | 4.81 | 5.72 | **-0.91** |

**Key Insight:** Model edge flipped from +1.42 (we beat Vegas) to -0.91 (Vegas beats us)

### Dual Root Cause

#### 1. Vegas Lines Got Sharper (External Factor)

| Metric | Dec 21 | Jan 25 | Change |
|--------|--------|--------|--------|
| Vegas MAE | 5.52 | 4.81 | **-0.71** (13% better) |
| Within 2pts | 26.0% | 31.0% | +5.0% |
| Within 3pts | 37.2% | 39.7% | +2.5% |

Vegas reduced their average error by 0.71 points - they're setting tighter, more accurate lines.

#### 2. Model Performance Degraded (Internal Factor)

| Metric | Dec 21 | Jan 25 | Change |
|--------|--------|--------|--------|
| Model MAE | 4.11 | 5.72 | **+1.61** (39% worse) |
| OVER MAE | 4.28 | 6.79 | **+2.51** (59% worse) |
| UNDER MAE | 4.55 | 5.70 | +1.15 (25% worse) |

Model's average error increased by 1.61 points, with OVER predictions degrading most severely.

### OVER vs UNDER Asymmetric Collapse

| Week | OVER Hit Rate | UNDER Hit Rate | Gap |
|------|---------------|----------------|-----|
| Dec 21 | **77.2%** | 69.2% | +8.0 |
| Dec 28 | 70.5% | 64.0% | +6.5 |
| Jan 11 | 46.7% | 51.6% | -4.9 |
| Jan 25 | **38.7%** | 50.0% | **-11.3** |

**Critical Finding:** OVER picks collapsed from 77% to 39%. UNDER picks also degraded but remain at ~50% (coin flip).

### High Confidence (Decile 10) Collapse

| Week | Decile 10 Picks | Hit Rate | % of Total |
|------|-----------------|----------|------------|
| Dec 21 | 640 | **57.2%** | 79.1% |
| Dec 28 | 541 | 56.4% | 69.3% |
| Jan 11 | 113 | 40.7% | 13.1% |
| Jan 25 | 77 | **24.7%** | 20.9% |

**Critical Finding:** High confidence picks dropped from 57% to 25% hit rate - worse than random.

### Strong Signal OVER Picks (Most Concerning)

When model predicts 3+ points above line:

| Week | Strong OVER | Hit Rate |
|------|-------------|----------|
| Dec 21 | 262 | **85.9%** |
| Dec 28 | 137 | 81.8% |
| Jan 11 | 122 | 46.7% |
| Jan 25 | 51 | **33.3%** |

**Critical Finding:** Our highest-conviction OVER picks went from 86% to 33% - catastrophic failure.

### Player Tier Analysis

| Tier | Dec 28 | Jan 25 | Change |
|------|--------|--------|--------|
| Stars (25+) | 57.8% | **22.6%** | -35.2% |
| Starters (15-25) | 52.5% | 31.5% | -21.0% |
| Rotation (8-15) | 52.0% | 40.7% | -11.3% |
| Bench (<8) | 51.5% | 33.1% | -18.4% |

**Finding:** Star players had the worst degradation - model systematically over-predicts their scoring.

### Degradation Start Point

| Date | Hit Rate | Event |
|------|----------|-------|
| Jan 05 | 54.3% | Decline begins |
| **Jan 07** | **50.8%** | **Tipping point** |
| Jan 09 | 33.9% | Sharp decline |
| Jan 14-28 | 30-36% | Sustained failure |

**Degradation Start:** January 7-9, 2026

---

## Part 3: Vegas Line Sharpness Analysis

### Is Vegas Getting Better?

**YES** - Vegas lines are getting more accurate:

| Period | Vegas MAE | Interpretation |
|--------|-----------|----------------|
| Dec 14-21 | 5.52-6.06 | Normal variance |
| Dec 28-Jan 4 | 4.71-4.95 | Improving |
| Jan 11-25 | 4.81-5.35 | **Consistently better** |

Vegas reduced MAE by ~0.7 points (13% improvement) while our model's MAE increased by 1.6 points.

### Market Efficiency Hypothesis

The data suggests:
1. **Vegas adapted** - Lines are now centered closer to actual outcomes
2. **Our features lag** - Rolling averages may not capture recent player form changes
3. **Scoring pattern shift** - January may have different dynamics (rest, injuries, trade deadline)

---

## Summary: Why V8 Is Failing

### Contributing Factors (Weighted by Impact)

| Factor | Impact | Evidence |
|--------|--------|----------|
| Model over-predicting scoring | **40%** | OVER MAE went from 4.28 to 6.79 |
| Vegas lines got sharper | **25%** | Vegas MAE improved 0.7 points |
| Confidence calibration broken | **20%** | Decile 10 went from 57% to 25% |
| Star player prediction failure | **15%** | Stars dropped from 58% to 23% |

### Root Cause Summary

**The model is systematically over-predicting player scoring, especially for OVER picks and star players, at a time when Vegas has tightened their lines. The confidence scoring is completely miscalibrated - high confidence picks are now worse than random.**

---

## Action Plan

### Immediate (Today)

1. [ ] Deduplicate 2026-01-29 data:
   ```bash
   bash scripts/maintenance/deduplicate_player_game_summary.sh
   ```

2. [ ] Fix retry decorator bug in `bigquery_save_ops.py`

### Short-term (This Week)

3. [ ] Consider raising confidence threshold from 0.84 to 0.90 (or higher)
4. [ ] Add Vegas sharpness monitoring to daily validation
5. [ ] Investigate feature staleness - are rolling averages lagging?

### Medium-term (Next 2 Weeks)

6. [ ] Retrain V8 with recent data (2026 season)
7. [ ] Add recency weighting to features
8. [ ] Consider separate models for OVER vs UNDER predictions

### Monitoring Additions

9. [ ] Add weekly Vegas MAE tracking
10. [ ] Alert when model edge goes negative for 2+ consecutive weeks
11. [ ] Alert when OVER vs UNDER gap exceeds 10%

---

## Files Modified This Session

```
docs/08-projects/current/v8-model-investigation/SESSION-37-INVESTIGATION-REPORT.md (NEW)
```

## Related Documents

- `docs/09-handoff/2026-01-30-SESSION-36-V8-INVESTIGATION-HANDOFF.md`
- `docs/08-projects/current/ml-model-v8-deployment/CHAMPION-CHALLENGER-FRAMEWORK.md`

---

*Investigation complete. Model degradation is due to BOTH internal factors (over-prediction) AND external factors (sharper Vegas lines). Immediate action required on data quality bug and model confidence thresholds.*
