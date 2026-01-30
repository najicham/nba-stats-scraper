# CatBoost V11 - Seasonal Features

**Status**: EXPERIMENTS COMPLETE - Seasonal features don't help
**Started**: 2026-01-30
**Completed**: 2026-01-30
**Result**: V8 remains the champion

---

## Summary

Tested the hypothesis that seasonal patterns (All-Star effects, time-of-season) improve predictions by adding 4 seasonal features to V8's 33-feature baseline.

**Result: Seasonal features HURT performance** - same pattern as V9 recency weighting.

---

## Experiment Results

| Experiment | MAE | Features | vs Baseline |
|------------|-----|----------|-------------|
| **V11 Baseline** | **4.0235** | 33 | - |
| V11 Seasonal | 4.0581 | 37 | +0.86% worse |

### Key Findings

1. **Seasonal features not useful**: None of the 4 seasonal features appeared in top 10 importance
2. **Model ignores time-of-season**: CatBoost found no predictive value in:
   - `week_of_season`
   - `pct_season_completed`
   - `days_to_all_star`
   - `is_post_all_star`
3. **V8 remains champion**: Both recency (V9) and seasonal (V11) hypotheses failed

---

## Background

Session 34 tested recency weighting (V9) and found it **hurts** performance. The original observation was:

> "Stars get more minutes near All-Star break, bench rotations tighten"

We hypothesized this was a **seasonal effect** rather than uniform recency. V11 tested this by adding explicit time-of-season features.

**Result:** The seasonal hypothesis was also wrong. The model doesn't benefit from knowing what week of the season it is.

---

## Seasonal Features Tested

```python
V11_SEASONAL_FEATURES = [
    'week_of_season',         # 0-42 (weeks since season start)
    'pct_season_completed',   # 0.0-1.0
    'days_to_all_star',       # Days until All-Star break (negative after)
    'is_post_all_star',       # 0/1 boolean
]
```

Feature statistics (full dataset):
- `week_of_season`: min=2, max=34, mean=13
- `pct_season_completed`: min=0.06, max=0.97, mean=0.38
- `days_to_all_star`: min=-126, max=110, mean=25
- `is_post_all_star`: min=0, max=1, mean=0.34 (34% post-ASB)

---

## Why Seasonal Features Failed

Possible explanations:

1. **The original observation was wrong**: Stars don't actually play more near All-Star - or it doesn't affect points
2. **Effect already captured**: The model may already capture this via `points_avg_last_5/10` and `minutes_avg_last_10`
3. **Effect is player-specific**: A global seasonal feature doesn't capture player-tier differences
4. **Effect is too weak**: Even if real, it's not strong enough to be predictive

---

## Feature Importance (V11 Seasonal)

Top 10 features (seasonal features not present):
1. `points_avg_last_5`: 45.45%
2. `points_avg_last_10`: 13.77%
3. `ppm_avg_last_10`: 10.54%
4. `minutes_avg_last_10`: 7.51%
5. `points_std_last_10`: 5.45%
6. `points_avg_season`: 3.80%
7. `vegas_points_line`: 2.95%
8. `vegas_opening_line`: 2.74%
9. `vegas_line_move`: 1.24%
10. `recent_trend`: 1.19%

The model strongly favors recent performance averages over time-of-season context.

---

## Files Created

### Models
```
ml/experiments/results/catboost_v11_exp_V11_SEASONAL_A1_20260130_095000.cbm
ml/experiments/results/catboost_v11_exp_V11_BASELINE_A1_20260130_095025.cbm
```

### Training Script
```
ml/experiments/train_v11_seasonal.py
```

---

## Learnings

1. **Both time-based hypotheses failed**: Recency (V9) and seasonality (V11) don't help
2. **V8 is well-optimized**: Simple 33-feature model is hard to beat
3. **Recent performance dominates**: `points_avg_last_5` alone is 45% of importance
4. **Don't over-engineer**: The best model is often the simplest one that works

---

## Recommendation

**Do not pursue further time-based features.** Both recency weighting and seasonal features hurt performance.

Future improvements should focus on:
- Better player matchup features
- Injury/lineup context
- Home/away splits by player
- Game importance (playoff implications)

---

## Version Comparison

| Version | Features | Approach | Status |
|---------|----------|----------|--------|
| V8 | 33 | Standard | **PRODUCTION** (MAE 4.02) |
| V9 | 36 + recency | Uniform recency weighting | DELETED (hurt) |
| V10 | 33 | Model file only | No system |
| V11 | 37 | Seasonal features | FAILED (hurt) |

---

*V11 experiments complete. Seasonal features don't help. V8 remains the champion.*
