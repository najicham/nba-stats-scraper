# CatBoost V8 Walk-Forward Experiment Results

**Date:** 2026-01-29
**Session:** 27
**Status:** Complete - All experiments validated on clean data

---

## Executive Summary

We conducted walk-forward validation experiments to validate CatBoost V8 performance across multiple seasons. After fixing the feature store bug (L5/L10 one-game shift), the results show:

- **Consistent 70-74% hit rate** across all seasons
- **Production model (70.7%)** matches experimental results
- **Bug inflated prior results by 3-4%** (buggy data showed 74%, clean data shows 70%)

---

## Production Model Comparison

| Metric | Production V8 | Experiments (Clean) |
|--------|---------------|---------------------|
| **Hit Rate** | 70.7% | 69.5-72.1% |
| **Sample Size** | 17,561 bets | 7,795-10,667 per exp |
| **Date Range** | Nov 2024 - Jan 2026 | Various seasons |
| **Training Data** | Nov 2021 - Jun 2024 | Various |

**Conclusion:** Production performance aligns with experimental validation.

---

## Experiment Results

### Clean Baseline Experiments (2022-2024 Evaluation)

These experiments used data that was never affected by the feature store bug.

| Exp | Training Period | Eval Period | Samples | MAE | Hit Rate | ROI |
|-----|-----------------|-------------|---------|-----|----------|-----|
| **A1** | 2021-11 to 2022-06 | 2022-10 to 2023-06 | 25,574 | 3.89 | **72.1%** | +37.5% |
| **A2** | 2021-11 to 2023-06 | 2023-10 to 2024-06 | 25,948 | 3.66 | **73.9%** | +41.1% |

### Fixed 2024-25 Experiments (Post-Bug Fix)

These experiments were re-run after patching the feature store L5/L10 values.

| Exp | Training Period | Eval Period | Samples | MAE | Hit Rate | ROI |
|-----|-----------------|-------------|---------|-----|----------|-----|
| **A3_fixed** | 2021-11 to 2024-06 | 2024-10 to 2025-06 | 16,303 | 3.91 | **70.8%** | +35.0% |
| **B1_fixed** | 2021-11 to 2023-06 | 2024-10 to 2025-06 | 16,303 | 3.93 | **70.6%** | +34.7% |
| **B2_fixed** | 2023-10 to 2024-06 | 2024-10 to 2025-06 | 16,303 | 3.99 | **69.5%** | +32.7% |
| **B3_fixed** | 2022-10 to 2024-06 | 2024-10 to 2025-06 | 16,303 | 3.92 | **70.7%** | +34.9% |

### Before vs After Bug Fix

| Experiment | Buggy Hit Rate | Fixed Hit Rate | Difference |
|------------|----------------|----------------|------------|
| A3 | 74.3% | 70.8% | **-3.5%** |
| B1 | 73.4% | 70.6% | **-2.8%** |
| B2 | 74.1% | 69.5% | **-4.6%** |
| B3 | 74.0% | 70.7% | **-3.3%** |

**Note:** The buggy data included the current game's score in L5/L10 calculations (future information leak), artificially inflating accuracy.

---

## Performance by Confidence Level

From experiment A3_fixed (representative):

| Confidence | Edge | Hit Rate | Sample Size |
|------------|------|----------|-------------|
| **High** | 5+ pts | 82.8% | 1,240 |
| **Medium** | 3-5 pts | 75.9% | 2,078 |
| **Low** | 1-3 pts | 65.3% | 4,710 |
| **Pass** | <1 pt | 54.9% | 3,321 |

**Key insight:** Higher edge predictions have significantly higher accuracy, validating the confidence scoring system.

---

## Performance by Direction

From experiment A3_fixed:

| Direction | Hit Rate | Sample Size |
|-----------|----------|-------------|
| OVER | 69.5% | 4,228 |
| UNDER | 72.2% | 3,800 |

**Note:** UNDER predictions slightly more accurate.

---

## Season-over-Season Trend

| Eval Season | Best Hit Rate | Trend |
|-------------|---------------|-------|
| 2022-23 | 72.1% (A1) | Baseline |
| 2023-24 | 73.9% (A2) | +1.8% |
| 2024-25 | 70.8% (A3) | -3.1% |

**Observation:** Slight performance decline in 2024-25 may indicate:
- Market efficiency improving
- Player behavior changes
- Need for model retraining with recent data

---

## Key Findings

### 1. Model Validation Successful
The CatBoost V8 model achieves **consistent 70%+ hit rates** across 3+ seasons of out-of-sample evaluation, well above the 52.4% breakeven threshold.

### 2. Feature Store Bug Impact
The L5/L10 bug artificially inflated 2024-25 results by 3-4%. Clean data shows true performance of ~70% (matching production).

### 3. Training Data Quantity
| Training Samples | Best Hit Rate |
|------------------|---------------|
| ~26K (1 season) | 72.1% |
| ~52K (2 seasons) | 73.9% |
| ~78K (3 seasons) | 70.8% |

More training data doesn't guarantee better results - recency may matter more.

### 4. ROI Consistency
All experiments show **32-41% ROI**, validating the betting edge is real and substantial.

---

## Methodology

### Walk-Forward Validation
Each experiment follows strict temporal separation:
1. Train on historical data only
2. Evaluate on future (unseen) data
3. No data leakage between train/eval periods

### Evaluation Criteria
- **Minimum edge:** 1.0 points (only count predictions with edge >= 1)
- **Vegas lines:** Only real Vegas lines used (has_vegas_line = 1.0)
- **Hit rate:** Percentage of predictions where actual result matched prediction direction

### Feature Store Fix
Applied 2026-01-29 to correct L5/L10 values:
- **8,456 records patched** from player_daily_cache
- **Verification:** 100% match rate after fix
- **Audit trail:** `feature_store_patch_audit` table

---

## Files & Artifacts

### Experiment Results
```
ml/experiments/results/
├── A1_results.json
├── A2_results.json
├── A3_fixed_results.json
├── B1_fixed_results.json
├── B2_fixed_results.json
├── B3_fixed_results.json
├── catboost_v9_exp_A3_fixed_*.cbm
├── catboost_v9_exp_B1_fixed_*.cbm
├── catboost_v9_exp_B2_fixed_*.cbm
└── catboost_v9_exp_B3_fixed_*.cbm
```

### Documentation
```
docs/08-projects/current/
├── catboost-v8-performance-analysis/
│   ├── EXPERIMENT-INFRASTRUCTURE.md
│   ├── EXPERIMENT-RESULTS-2026-01-29.md (this file)
│   └── WALK-FORWARD-EXPERIMENT-PLAN.md
└── season-validation-2024-25/
    ├── FEATURE-STORE-BUG-ROOT-CAUSE.md
    └── FEATURE-STORE-BUG-IMPACT-ANALYSIS.md
```

---

## Running Experiments

### Train and Evaluate
```bash
PYTHONPATH=. python ml/experiments/run_experiment.py \
    --experiment-id MY_EXP \
    --train-start 2021-11-01 --train-end 2024-06-30 \
    --eval-start 2024-10-01 --eval-end 2025-06-30
```

### Compare All Results
```bash
PYTHONPATH=. python ml/experiments/compare_results.py
```

### Verify Feature Store
```sql
SELECT
  FORMAT_DATE('%Y-%m', fs.game_date) as month,
  ROUND(100.0 * COUNTIF(ABS(fs.features[OFFSET(0)] - c.points_avg_last_5) < 0.1) / COUNT(*), 1) as l5_match_pct
FROM nba_predictions.ml_feature_store_v2 fs
JOIN nba_precompute.player_daily_cache c
  ON fs.player_lookup = c.player_lookup AND fs.game_date = c.cache_date
WHERE fs.game_date >= '2024-10-01' AND fs.feature_count = 33
GROUP BY 1 ORDER BY 1
```

---

## Recommendations

### Short-term
1. **Continue using CatBoost V8** - validated performance matches production
2. **Monitor 2024-25 performance** - slight decline warrants attention
3. **Fix feature store code** - prevent future `<=` vs `<` bugs

### Medium-term
1. **Retrain with 2024-25 data** - model may benefit from recent patterns
2. **Investigate UNDER outperformance** - possible signal for strategy adjustment
3. **A/B test confidence thresholds** - optimize bet selection

### Long-term
1. **Automate walk-forward validation** - run monthly to track drift
2. **Add feature importance tracking** - detect which features degrade
3. **Build model versioning system** - formal A/B testing infrastructure

---

*Experiments conducted by Session 27 - 2026-01-29*
*Production comparison data: 17,561 predictions, 70.7% hit rate*
