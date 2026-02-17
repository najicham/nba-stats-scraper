# Session 276: Model Retrain Sprint Results

**Date:** 2026-02-16
**Context:** All-Star break window. Both models BLOCKED (V9: 44.1% 7d HR, 39+ days stale; V12: 48.3%, 17 days stale). Games resume Feb 19.

## Summary

Retrained all model families + first-ever V12+Quantile experiments. 6 models total:
- 2 MAE models (V9 champion + V12 shadow)
- 4 quantile models (V9 Q43/Q45 + V12 Q43/Q45)

All 4 quantile models passed ALL governance gates. MAE models passed all gates except sample size (n<50 due to All-Star break eval window — acceptable).

## Results

### MAE Models (train through Feb 5, eval Feb 6-12)

| Model | MAE | HR All | HR 3+ | N 3+ | Vegas Bias | Status |
|-------|-----|--------|-------|------|------------|--------|
| V9 MAE | 4.766 | 56.07% | 76.19% | 21 | -0.07 | **PRODUCTION** |
| V12 No-Vegas MAE | 4.701 | 59.06% | 69.23% | 13 | -0.01 | Shadow (enabled) |

### Quantile Models (train through Jan 25, eval Jan 26-Feb 12)

| Model | MAE | HR All | HR 3+ | N 3+ | Vegas Bias | Gates |
|-------|-----|--------|-------|------|------------|-------|
| V9 Q43 | 4.954 | 52.13% | 62.61% | 115 | -1.38 | **ALL PASSED** |
| V9 Q45 | 4.942 | 50.74% | 62.89% | 97 | -1.25 | **ALL PASSED** |
| V12 Q43 | 4.930 | 53.51% | 61.60% | 125 | -1.44 | **ALL PASSED** |
| V12 Q45 | 4.934 | 54.21% | 61.22% | 98 | -1.06 | **ALL PASSED** |

### Walkforward Breakdown

**V9 MAE:**
| Week | N | MAE | HR All | HR 3+ | Bias |
|------|---|-----|--------|-------|------|
| Jan 26-Feb 1 | 470 | 4.65 | 56.8% | 81.2% | +0.04 |
| Feb 2-8 | 367 | 5.16 | 52.7% | 60.0% | -0.16 |

**V12 No-Vegas MAE:**
| Week | N | MAE | HR All | HR 3+ | Bias |
|------|---|-----|--------|-------|------|
| Jan 26-Feb 1 | 470 | 4.68 | 56.1% | 69.2% | +0.10 |
| Feb 2-8 | 367 | 5.07 | 57.3% | 54.5% | +0.12 |

## Key Findings

1. **V12+Quantile works.** First-ever experiment combining 50 features with quantile loss. Both Q43 and Q45 passed all governance gates with strong sample sizes (n=125 and n=98).

2. **V12 Q43 has highest N of any quantile model.** 125 edge 3+ predictions in eval — more than V9 Q43 (115). The richer feature set generates more confident (higher-edge) predictions.

3. **Quantile models show UNDER preference.** All 4 have negative Vegas bias (-1.06 to -1.44), confirming they predict lower than Vegas lines. This complements the UNDER signals in the signal system.

4. **MAE models have near-zero Vegas bias.** V9 at -0.07, V12 at -0.01. This means they track Vegas closely and generate fewer edge 3+ predictions — by design.

5. **All-Star break eval challenge.** With no games Feb 13-18, we used split eval windows. MAE models got limited N for edge 3+ (21 and 13). Walkforward results provide additional validation.

## Registry State

| model_id | family | enabled | status |
|----------|--------|---------|--------|
| catboost_v9_train1102_0205 | v9_mae | TRUE | production |
| catboost_v12_noveg_train1102_0205 | v12_noveg_mae | TRUE | active |
| catboost_v9_q43_train1102_0125 | v9_q43 | TRUE | active |
| catboost_v9_q45_train1102_0125 | v9_q45 | TRUE | active |
| catboost_v12_noveg_q43_train1102_0125 | v12_noveg_q43 | TRUE | active |
| catboost_v12_noveg_q45_train1102_0125 | v12_noveg_q45 | TRUE | active |

## Next Steps

1. **Feb 19:** Verify all 6 models generate predictions for resumed games
2. **Feb 19-25:** Monitor live HR for all models via `validate-daily`
3. **After 50+ graded edge 3+ picks:** Compare champion vs challengers for potential promotion
4. **Route UNDER signals to Q43/Q45** for model-aware scoring (Priority 5 from Session 275)
