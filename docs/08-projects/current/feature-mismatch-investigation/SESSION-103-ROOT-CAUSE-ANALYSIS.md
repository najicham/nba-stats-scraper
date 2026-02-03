# Session 103: Root Cause Analysis of Model Bias

**Date:** 2026-02-03
**Status:** Investigation Complete

## Executive Summary

The CatBoost V9 model has regression-to-mean bias that causes:
- Stars under-predicted by ~9 pts
- Bench players over-predicted by ~5.5 pts

**Root cause is NOT missing features.** The bias exists even when all features (including Vegas lines) are present. The fundamental issue is that **Vegas lines themselves are biased**, and our model follows Vegas too closely.

## Key Findings

### 1. Sportsbook Props Are Not Available for All Players

Only 16% of bench players and 46.7% of role players have DraftKings props. This is expected - there's no betting market for 3-point scorers.

| Tier | % with DK Props |
|------|-----------------|
| Star | 77.5% |
| Starter | 67.9% |
| Role | 46.7% |
| Bench | **16.0%** |

### 2. Feature Store Design is Correct

The feature store intentionally stores NULL when no prop exists. The `has_vegas_line` flag (feature index 28) indicates whether data is real. This is correct behavior.

### 3. Vegas Lines Are ALSO Biased

**Critical finding:** Vegas lines themselves under-predict stars by ~8 points:

| Tier | Vegas Line | Actual | Vegas Bias |
|------|------------|--------|------------|
| Star | 22.2 | 30.4 | **-8.2** |
| Starter | 16.3 | 18.7 | -2.4 |
| Role | 10.8 | 9.5 | +1.3 |
| Bench | 7.3 | 2.2 | **+5.1** |

This is intentional by sportsbooks - they set conservative lines to balance betting action.

### 4. Model Follows Vegas Too Closely

| Tier | Vegas Line | Model Pred | Difference |
|------|------------|------------|------------|
| Star | 22.2 | 21.1 | -1.1 |
| Starter | 16.3 | 15.9 | -0.4 |
| Role | 10.8 | 11.0 | +0.2 |
| Bench | 7.3 | 7.8 | +0.5 |

The model stays within 1-2 points of Vegas lines instead of learning to diverge when appropriate.

## Is scoring_tier a Band-Aid or Real Signal?

**It's a REAL signal, not a band-aid.**

The bias exists even when:
1. Vegas lines ARE present
2. All 33+ features are populated
3. Feature quality score is high

This proves the model needs explicit tier information to understand:
- Stars should be expected to exceed their Vegas lines
- Bench players should be expected to fall short of their lines
- The relationship between features and actual scoring varies by tier

## Recommended Solutions

### Short-term: Tier Calibration Metadata (Implemented)
- Store `scoring_tier` and `tier_adjustment` in predictions
- Apply calibration at query time: `predicted_points + tier_adjustment`
- Preserves raw predictions for analysis

### Medium-term: Add scoring_tier as Training Feature
- Add categorical feature to CatBoost training
- Helps model learn tier-specific patterns
- Reduces reliance on Vegas line following

### Long-term: Investigate Vegas Line Divergence
- When should model diverge from Vegas?
- Train on "prediction vs actual" instead of just "actual"
- Consider quantile regression to reduce mean-seeking behavior

## Data Quality Check (Training Data)

Training data distribution (Nov 2025 - Jan 2026):

| Line Status | Tier | Count | Avg Actual |
|-------------|------|-------|------------|
| HAS_LINE | Bench | 145 | 2.4 |
| HAS_LINE | Role | 441 | 9.8 |
| HAS_LINE | Star | 144 | 31.2 |
| HAS_LINE | Starter | 310 | 18.8 |
| NO_LINE | Bench | 12,605 | 1.5 |
| NO_LINE | Role | 5,339 | 9.1 |
| NO_LINE | Star | 969 | 30.3 |
| NO_LINE | Starter | 2,482 | 18.7 |

95% of training data has NO vegas line. The model is learning primarily from players without props.

## Small Data Bug Found

180 records (out of ~8000) have Vegas values but `has_vegas_line=0`. This is minor but should be fixed.

## Files Changed This Session

| File | Change |
|------|--------|
| `predictions/worker/worker.py` | Added `scoring_tier` and `tier_adjustment` metadata fields |
| `predictions/worker/worker.py` | Added `_compute_scoring_tier()` and `_compute_tier_adjustment()` functions |

## Next Steps

1. Create `/spot-check-features` skill to validate training data quality
2. Consider adding `scoring_tier` as categorical feature in training
3. Investigate why model follows Vegas so closely
4. Consider training on residuals (prediction - vegas) to learn divergence patterns
