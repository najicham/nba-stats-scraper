# Session 54 Research Findings - Model Ensemble Analysis

**Date:** 2026-01-31
**Session:** 54
**Status:** Complete

---

## Executive Summary

**The Session 53 tier-based hypothesis was incorrect.** Rigorous backtesting shows:

1. **JAN_DEC_only (recent training data) outperforms V8 for ALL player tiers**
2. **The tier-based routing approach HURTS performance** when using V8 for stars/bench
3. **The simplest strategy wins**: Just use JAN_DEC_only for everything

### Key Results (Edge >= 3.0)

| Strategy | Hit Rate | ROI | Notes |
|----------|----------|-----|-------|
| **JAN_DEC_only** | **54.7%** | **+4.4%** | **BEST - Use this** |
| Tier-based | 54.1% | +3.3% | Worse than JAN_DEC only |
| V8-only | 49.4% | -5.6% | Below breakeven |

---

## Backtest Methodology

### Models Tested

1. **V8 Production** (CatBoost only, 33 features)
   - Trained on: 2021-2024 historical data
   - File: `models/catboost_v8_33features_20260108_211817.cbm`

2. **JAN_DEC_ONLY** (CatBoost, 37 features)
   - Trained on: December 2025 only
   - File: `ml/experiments/results/catboost_v9_exp_JAN_DEC_ONLY_20260131_085101.cbm`

3. **Tier-based** (routing between V8 and JAN_DEC)
   - Stars (22+ ppg): V8
   - Starters (14-22 ppg): JAN_DEC
   - Rotation (6-14 ppg): JAN_DEC
   - Bench (<6 ppg): V8

### Evaluation Data

- Period: January 1-30, 2026
- Samples: 4,792 player-games
- Vegas line coverage: 63.4%

### Tier Distribution

| Tier | Count | % | Model (Tier-based) |
|------|-------|---|-------------------|
| Star | 347 | 7.2% | V8 |
| Starter | 941 | 19.6% | JAN_DEC |
| Rotation | 1,923 | 40.1% | JAN_DEC |
| Bench | 1,581 | 33.0% | V8 |

---

## Results by Tier (Edge >= 3.0)

### Star Players (22+ ppg average)

| Model | Hit Rate | Bets |
|-------|----------|------|
| V8 | 50.0% | 170 |
| **JAN_DEC** | **53.5%** | 116 |

**JAN_DEC is better for stars by 3.5%**

### Starter Players (14-22 ppg)

| Model | Hit Rate | Bets |
|-------|----------|------|
| V8 | 46.4% | 364 |
| **JAN_DEC** | **55.8%** | 224 |

**JAN_DEC is better for starters by 9.4%**

### Rotation Players (6-14 ppg)

| Model | Hit Rate | Bets |
|-------|----------|------|
| V8 | 49.1% | 450 |
| **JAN_DEC** | **52.1%** | 217 |

**JAN_DEC is better for rotation by 3.0%**

### Bench Players (<6 ppg)

| Model | Hit Rate | Bets |
|-------|----------|------|
| V8 | 62.8% | 86 |
| **JAN_DEC** | **63.5%** | 52 |

**JAN_DEC is slightly better for bench by 0.7%**

---

## Why Session 53 Hypothesis Was Wrong

Session 53 suggested V8 outperforms for stars (55.8%) and bench (57.5%).
My backtest shows the opposite. Possible reasons:

1. **Different evaluation periods** - Session 53 may have used different dates
2. **Different edge thresholds** - Session 53 may have used edge >= 2.0
3. **Production V8 vs CatBoost-only** - Session 53's "V8" might have included full stacked ensemble
4. **Imputed Vegas lines** - Session 53 may not have filtered out imputed lines

### Critical Insight

The "V8 Production" in `catboost_v8.py` **only uses CatBoost**, not the full stacked ensemble:

```python
# catboost_v8.py line 480
model_files = list(models_dir.glob("catboost_v8_33features_*.cbm"))
self.model = cb.CatBoostRegressor()
self.model.load_model(str(model_path))
# XGBoost and LightGBM models exist but are NOT loaded!
```

The training script creates a stacked ensemble with:
- XGBoost (MAE 3.45)
- LightGBM (MAE 3.47)
- CatBoost (MAE 3.43)
- Ridge meta-learner (combined MAE 3.40)

But production only uses CatBoost (MAE 3.43), leaving 0.8% improvement on the table.

---

## MAE Comparison

| Model | MAE | vs V8 |
|-------|-----|-------|
| V8-only | 4.89 | baseline |
| Tier-based | 4.61 | -5.7% better |
| **JAN_DEC-only** | **4.53** | **-7.4% better** |

---

## Recommendation: Deploy JAN_DEC_ONLY

### Why JAN_DEC Wins

1. **Recency** - Trained on December 2025, captures current player roles
2. **37 features** - Includes DNP rate, trajectory features not in V8
3. **Simplicity** - No routing logic, single model

### Implementation Plan

**Phase 1: Shadow Mode (1 week)**

```python
# In prediction_worker.py
def predict_with_shadow(features):
    v8_pred = v8_model.predict(features[:33])
    jan_dec_pred = jan_dec_model.predict(features[:37])

    # Log both for comparison
    log_prediction(v8_pred, "v8", features)
    log_prediction(jan_dec_pred, "jan_dec", features)

    # Use V8 for now
    return v8_pred
```

**Phase 2: Gradual Rollout**

1. Deploy JAN_DEC model to GCS
2. Add environment variable for model selection
3. Roll out to 10% of predictions
4. Monitor hit rates for 1 week
5. If positive, increase to 50%, then 100%

**Phase 3: Monthly Retraining**

Since JAN_DEC's advantage comes from recency:
1. Train new model on last 60 days monthly
2. Validate against holdout
3. Deploy if MAE improves

---

## Files Created

| File | Purpose |
|------|---------|
| `ml/experiments/tier_based_backtest.py` | Backtest script |
| `ml/experiments/results/tier_based_backtest_*.json` | Backtest results |
| `docs/08-projects/current/model-ensemble-research/SESSION-54-FINDINGS.md` | This document |

---

## Next Steps

1. **Immediate**: Consider deploying JAN_DEC_only in shadow mode
2. **Short-term**: Set up monthly retraining pipeline
3. **Long-term**: Implement true stacked ensemble in production (XGB + LGB + CB + Ridge)

---

## Appendix: Full Backtest Output

```
================================================================================
 BETTING METRICS COMPARISON (Edge >= 3.0)
================================================================================

V8_only:
  Overall: 49.4% (529/1070)
  ROI: -5.6%, Profit: $-60.09
  By tier:
    star      :  50.0% (85/170)
    starter   :  46.4% (169/364)
    rotation  :  49.1% (221/450)
    bench     :  62.8% (54/86)

JAN_DEC_only:
  Overall: 54.7% (333/609)
  ROI: 4.4%, Profit: $26.73
  By tier:
    star      :  53.5% (62/116)
    starter   :  55.8% (125/224)
    rotation  :  52.1% (113/217)
    bench     :  63.5% (33/52)

tier_based:
  Overall: 54.1% (377/697)
  ROI: 3.3%, Profit: $22.73
  By tier:
    star      :  50.0% (85/170)
    starter   :  55.8% (125/224)
    rotation  :  52.1% (113/217)
    bench     :  62.8% (54/86)
```

---

*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
