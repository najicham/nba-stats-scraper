# Production vs Backtest Gap Analysis

**Date:** 2026-01-31
**Finding:** Production V8 hits 57%, backtest shows 49% - an 8% gap

---

## The Discrepancy

| Source | Hit Rate | Sample Size |
|--------|----------|-------------|
| Production V8 (prediction_accuracy) | 56.97-59% | 1,931 |
| Backtest V8 (ml_feature_store_v2) | 49.44% | 3,039 |
| Backtest JAN_DEC | 54.68% | 609 |

This matters because Session 55 concluded JAN_DEC (54.7%) beats V8 (49.4%). But if production V8 is actually at 57%, that conclusion is wrong.

---

## Root Causes Identified

### 1. Sample Population Difference (PRIMARY)

Backtest includes ~60% more player-games than production:

```
Production: 1,931 samples, 333 unique players
Backtest: 3,039 samples, 338 unique players
```

The extra 1,108 samples are players/games where production **didn't generate predictions** for various reasons (no prop line, player filtered out, etc.).

### 2. Missing Dates in Production

Production grading is missing 8 dates that are in the feature store:

| Date | Feature Store Entries | In Production? |
|------|----------------------|----------------|
| 2026-01-19 | 148 | NO |
| 2026-01-21 | 112 | NO |
| 2026-01-22 | 124 | NO |
| 2026-01-23 | 119 | NO |
| 2026-01-24 | 45 | NO |
| 2026-01-29 | 117 | NO |
| 2026-01-30 | 128 | NO |

This is ~793 predictions not graded in production.

### 3. Line Type Mixing

The `has_vegas_line=1.0` flag in feature store is set for BOTH:
- **Actual prop lines** (round half-point numbers like 22.5)
- **Estimated averages** (many decimals like 26.514705882352942)

Distribution:
```
72% - MANY_DECIMALS (estimated)
27% - ROUND_HALF (actual Vegas)
1% - OTHER
```

---

## Why Vegas Line Timing is NOT the Issue

We verified that feature store lines match production lines:

```sql
-- Average difference: 0.02 points (essentially identical)
game_date       avg_feature_line  avg_prod_line  avg_line_diff
2026-01-15      13.02             13.03          0.019
2026-01-17      13.51             13.51          0.023
```

---

## Model's Edge Source

Production V8 achieves 56.6% hit rate while simple over rate is only 47%.

The model adds ~10% edge by choosing the CORRECT bet direction:
- OVER bets: 53.63% hit rate
- UNDER bets: 59.24% hit rate

The model correctly identifies that lines are slightly high (over rate 47%) and selects more UNDER bets.

---

## Selection Bias Evidence

Players in production vs. not in production:

| In Production | Count | Avg Line | Over Rate |
|--------------|-------|----------|-----------|
| TRUE | 1,669 | 13.49 | 47.39% |
| FALSE | 1,370 | 12.47 | 46.79% |

Production subset has slightly higher-scoring players.

---

## Implications

### For Experiment Evaluation

1. **Cannot compare backtest hit rate to production hit rate directly**
2. **Can still compare Model A vs Model B on same backtest** (fair comparison)
3. **JAN_DEC deployment NOT recommended** - would likely underperform production V8

### For Future Experiments

When evaluating new models:

```python
# WRONG: Compare backtest to production
if backtest_hit_rate > production_hit_rate:  # Invalid comparison
    deploy()

# RIGHT: Compare models on same backtest
if new_model_backtest > baseline_backtest:  # Valid comparison
    consider_deployment()
```

---

## Recommended Fixes

### Option 1: Production-Filtered Backtest

Only evaluate on samples that exist in production:

```sql
SELECT * FROM ml_feature_store_v2 f
WHERE EXISTS (
  SELECT 1 FROM prediction_accuracy pa
  WHERE pa.player_lookup = f.player_lookup
    AND pa.game_date = f.game_date
    AND pa.system_id = 'catboost_v8'
)
```

### Option 2: "Production-Equivalent" Filter

Match production's selection criteria:
1. Only actual prop lines (line ends in .5)
2. Only dates where production ran
3. Only players with sufficient history

### Option 3: Accept Different Absolute Numbers

Use backtest for **relative** model comparisons, not absolute hit rate predictions.

Document that:
- Backtest ~49% corresponds to production ~57%
- 5% backtest improvement → ~5% production improvement

---

## Summary

| Question | Answer |
|----------|--------|
| Why the 8% gap? | Sample population + missing dates + line mixing |
| Is backtest wrong? | No, it's measuring a different population |
| Should we deploy JAN_DEC? | NO - production V8 is already at 57% |
| Are experiments useless? | NO - relative comparisons still valid |
| How to fix? | Filter to production samples or accept different baselines |
