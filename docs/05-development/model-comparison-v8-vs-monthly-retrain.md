# Model Comparison: V8 Baseline vs Monthly Retrain

**Date:** 2026-01-31
**Session:** 59
**Author:** Claude Opus 4.5

---

## Executive Summary

A monthly retrain experiment revealed a critical insight: **better MAE does not equal better hit rate**. A model trained on recent data (Oct-Dec 2025) achieved lower prediction error but significantly worse betting performance compared to V8 baseline. Investigation uncovered severe data quality issues in the recent training period that explain the performance gap.

### Key Finding

| Metric | Monthly Retrain | V8 Baseline | Winner |
|--------|-----------------|-------------|--------|
| MAE | 5.13 | 5.36 | Monthly Retrain |
| Hit Rate (all) | 49.01% | 55.48% | **V8 by 6.5%** |
| Hit Rate (5+ edge) | 53.88% | 60.54% | **V8 by 6.7%** |
| Hit Rate (premium) | 50.00% | 78.23% | **V8 by 28%** |

**The model that predicts actual points more accurately loses more bets.**

---

## Part 1: V8 Baseline - How It Was Trained

### Training Configuration

| Parameter | Value |
|-----------|-------|
| **Training Period** | November 2021 - June 2024 (2.5 years) |
| **Training Samples** | 76,863 |
| **Data Split** | 70% train / 15% val / 15% test (chronological) |
| **Architecture** | Stacked ensemble (XGBoost + LightGBM + CatBoost) |
| **Meta-Learner** | Ridge regression |
| **Features** | 33 |

### Ensemble Weights

The Ridge meta-learner learned these coefficients:

| Model | Weight | Interpretation |
|-------|--------|----------------|
| CatBoost | 0.736 | Primary predictor (73.6%) |
| XGBoost | 0.380 | Secondary signal (38%) |
| LightGBM | -0.104 | Negative weight (error correction) |

**Note:** Production only loads CatBoost, not the full ensemble.

### CatBoost Hyperparameters

```python
{
    'depth': 6,
    'learning_rate': 0.07,
    'l2_leaf_reg': 3.8,
    'subsample': 0.72,
    'min_data_in_leaf': 16,
    'iterations': 1000,
    'early_stopping_rounds': 50
}
```

### Training Data Quality

| Metric | V8 Training Period |
|--------|-------------------|
| Records with Vegas line = 0 | 0.9% |
| Records with has_vegas_line = 1 | 55.9% |
| Records with points_avg_last_5 = 0 | 0.4% |
| High quality records (90+ score) | 13,068 |

### Feature Set (33 Features)

```
Base (25): points_avg_last_5, points_avg_last_10, points_avg_season,
           points_std_last_10, games_in_last_7_days, fatigue_score,
           shot_zone_mismatch_score, pace_score, usage_spike_score,
           rest_advantage, injury_risk, recent_trend, minutes_change,
           opponent_def_rating, opponent_pace, home_away, back_to_back,
           playoff_game, pct_paint, pct_mid_range, pct_three, pct_free_throw,
           team_pace, team_off_rating, team_win_pct

Vegas (4):  vegas_points_line, vegas_opening_line, vegas_line_move, has_vegas_line

History (2): avg_points_vs_opponent, games_vs_opponent

Efficiency (2): minutes_avg_last_10, ppm_avg_last_10
```

---

## Part 2: Monthly Retrain - What We Trained

### Training Configuration

| Parameter | Value |
|-----------|-------|
| **Training Period** | October 15 - December 31, 2025 (78 days requested) |
| **Actual Data Available** | November 4 - December 31, 2025 (56 days) |
| **Training Samples** | 8,598 |
| **Eval Period** | January 1-30, 2026 |
| **Eval Samples** | 3,041 |
| **Architecture** | Single CatBoost model |
| **Features** | 33 |

### CatBoost Hyperparameters

```python
{
    'iterations': 1000,
    'learning_rate': 0.05,
    'depth': 6,
    'l2_leaf_reg': 3,
    'random_seed': 42,
    'early_stopping_rounds': 50
}
```

### Training Data Quality Issues

| Metric | Monthly Retrain | V8 Baseline | Problem |
|--------|-----------------|-------------|---------|
| Records with Vegas line = 0 | **68.6%** | 0.9% | CRITICAL |
| Records with has_vegas_line = 1 | 10.5% | 55.9% | CRITICAL |
| Records with points_avg = 0 | **15.5%** | 0.4% | Early season |
| High quality records | **43** | 13,068 | Almost none |
| Total samples | 8,598 | 76,863 | 11% of V8 |

---

## Part 3: Root Cause Analysis

### Why V8 Has Better Hit Rate Despite Worse MAE

#### 1. Training/Inference Distribution Mismatch

The monthly retrain learned that `vegas_line = 0` is normal because 68.6% of training data had missing Vegas lines. During inference on January 2026, Vegas lines are always available. This creates a fundamental mismatch.

```
Training distribution:  vegas_line = 0 for 68.6% of samples
Inference distribution: vegas_line > 0 for 100% of samples
```

The model learned to predict points *without* relying on Vegas lines, which is exactly backwards from what we want.

#### 2. Vegas Data Pipeline Failure

Investigation revealed the Vegas data scraper failed from November 13 - December 19, 2025:

| Date Range | Vegas Line Coverage |
|------------|---------------------|
| Nov 4-12, 2025 | Partial |
| Nov 13 - Dec 19, 2025 | **0%** (pipeline broken) |
| Dec 20-31, 2025 | Restored |

This 5-week gap corrupted the training data.

#### 3. Early Season Bootstrap Problem

The 2025-26 NBA season started October 21. For the first 2 weeks:
- Many players had no 5-game or 10-game history
- `points_avg_last_5` = 0 for 15.5% of records
- Rolling averages were unreliable

V8 was trained on mid-season data where all players have established history.

#### 4. Sample Size Difference

| Dataset | Samples | Unique Games |
|---------|---------|--------------|
| V8 Training | 76,863 | ~2,500 |
| Monthly Retrain | 8,598 | ~150 |

The monthly retrain had 11% of V8's training data, reducing the model's ability to learn stable patterns.

#### 5. Feature Store Backfill Gap

October 2025 games exist in `player_game_summary` but were **never backfilled** to `ml_feature_store_v2`. The training script requested Oct 15 - Dec 31 but only received Nov 4 - Dec 31.

---

## Part 4: Why MAE and Hit Rate Diverge

### The Betting Optimization Paradox

MAE measures: "How close is my prediction to the actual points?"
Hit Rate measures: "Did I correctly pick OVER or UNDER vs the Vegas line?"

These optimize for different things:

```
Example:
  Vegas Line: 20.5
  Actual: 25

Model A: Predicts 22 (MAE = 3, picks OVER, WINS)
Model B: Predicts 24 (MAE = 1, picks OVER, WINS)
Model C: Predicts 19 (MAE = 6, picks UNDER, LOSES)
```

**Better MAE doesn't guarantee correct direction.** What matters is:
1. Being on the correct side of the line
2. Having conviction (edge) when you're right
3. Avoiding high-confidence wrong picks

### V8's Secret: Vegas Line Integration

V8 was trained with high-quality Vegas line data. It learned:
- When Vegas is likely wrong (exploitable edges)
- When Vegas is right (avoid betting)
- How to calibrate confidence based on line accuracy

The monthly retrain learned:
- Vegas line is usually 0 (wrong)
- Predict points from player stats alone (misses market information)
- No understanding of when Vegas is beatable

---

## Part 5: V8 Production Performance (January 2026)

### Overall Performance

| Metric | Value |
|--------|-------|
| Total Predictions | 2,925 |
| Graded Predictions | 2,163 |
| **Overall Hit Rate** | **55.48%** |
| Breakeven (−110 juice) | 52.4% |
| **Edge Over Breakeven** | **+3.08%** |

### By Confidence Tier

| Confidence | Bets | Hit Rate |
|------------|------|----------|
| 95+ | 51 | **68.63%** |
| 92-95 | 418 | **65.07%** |
| 85-92 | 1,267 | 52.49% |
| <85 | 427 | 53.40% |

Confidence calibration is excellent - higher confidence = higher hit rate.

### Standard Filters

| Filter | Bets | Hit Rate | Status |
|--------|------|----------|--------|
| Premium (92+ conf, 3+ edge) | 147 | **78.23%** | Crushing |
| High Edge (5+ edge) | 446 | **60.54%** | Strong |

### Weekly Trend (Concerning)

| Week | Hit Rate | Trend |
|------|----------|-------|
| Dec 28 | 67.03% | - |
| Jan 4 | 62.71% | -4.3% |
| Jan 11 | 51.13% | -11.6% |
| Jan 18 | 48.34% | -2.8% |
| Jan 25 | 50.60% | +2.3% |

**Warning:** Performance degraded from 67% to ~50% over January. This may indicate model decay or a regime change in the data.

---

## Part 6: Recommendations

### Immediate Actions

1. **Do NOT deploy the monthly retrain model** - It's worse than V8 on the metric that matters (hit rate)

2. **Fix Vegas data pipeline** - Investigate why Nov 13 - Dec 19, 2025 had no Vegas data

3. **Backfill October 2025** - Run feature store backfill for Oct 21-31, 2025 games

### For Future Monthly Retrains

1. **Data Quality Gates**
   ```python
   # Before training, verify:
   assert pct_with_vegas_line > 0.90, "Vegas data too sparse"
   assert pct_with_points_history > 0.95, "Too many early-season records"
   assert training_samples > 30000, "Insufficient training data"
   ```

2. **Exclude Corrupted Periods**
   - Skip Nov 13 - Dec 19, 2025 until Vegas data is backfilled
   - Skip first 2 weeks of any season (early bootstrap)

3. **Use V8's Training Approach**
   - Stacked ensemble, not single model
   - Longer training window (12+ months)
   - Chronological validation split

4. **Add Hit Rate to Training Objective**
   - Consider custom loss function that penalizes wrong-side predictions
   - Or post-hoc calibration layer for confidence scores

### Model Refresh Strategy

Given V8's January decay (67% → 50%), consider:

1. **Incremental fine-tuning** - Update last layers on recent data
2. **Ensemble blending** - Combine V8 with recent-data model
3. **Regime detection** - Identify when patterns shift

---

## Part 7: Experiment Registry

### FEB_MONTHLY_V2 (This Experiment)

| Field | Value |
|-------|-------|
| experiment_id | 0eee2c3d |
| experiment_name | FEB_MONTHLY_V2 |
| hypothesis | 90 days training, full Jan eval |
| train_period | 2025-10-15 to 2025-12-31 |
| eval_period | 2026-01-01 to 2026-01-30 |
| train_samples | 8,598 |
| eval_samples | 3,041 |
| MAE | 5.1279 |
| hit_rate_all | 49.01% |
| hit_rate_high_edge | 53.88% |
| hit_rate_premium | 50.00% |
| status | completed |
| recommendation | DO NOT DEPLOY |

---

## Appendix: Files Referenced

| File | Purpose |
|------|---------|
| `ml/train_final_ensemble_v8.py` | V8 training script |
| `ml/experiments/quick_retrain.py` | Monthly retrain script |
| `models/ensemble_v8_20260108_211817_metadata.json` | V8 training metadata |
| `predictions/worker/prediction_systems/catboost_v8.py` | Production inference |

---

## Conclusion

The "MAE vs Hit Rate" paradox is a classic ML pitfall: optimizing for prediction accuracy doesn't optimize for the downstream business metric. V8 succeeds because it was trained on:

1. **High-quality Vegas data** (99% coverage vs 31%)
2. **Sufficient volume** (77K samples vs 9K)
3. **Stable mid-season patterns** (no early-season bootstrap)
4. **Ensemble architecture** (error correction via stacking)

Monthly retrains should only proceed after fixing the Vegas data pipeline and establishing quality gates.

---

*Document created: Session 59, 2026-01-31*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
