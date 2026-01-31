# Session 55 Findings - Stacked Ensemble Experiments

**Date:** 2026-01-31
**Focus:** Testing recency weighting on full stacked ensemble
**Status:** Complete - Key hypothesis disproven

---

## Executive Summary

**The core question:** Does 60-day recency weighting help the stacked ensemble (XGBoost + LightGBM + CatBoost + Ridge)?

**The answer:** No. Recency weighting on historical data (2021-2024) provides no meaningful benefit for January 2026 predictions. The key is training on **recent data only**, not weighting old data.

---

## Experiment Results

### January 2026 Performance (3+ Edge)

| Model | Training Data | Recency | Hit Rate | MAE | Bets |
|-------|--------------|---------|----------|-----|------|
| V8 Production | 2021-2024 | None | 49.4% | 4.89 | ~1070 |
| ENS_BASELINE (stacked) | 2021-2024 | None | 50.0% | 6.47 | 888 |
| ENS_REC60 (stacked) | 2021-2024 | 60d half-life | 50.1% | 6.71 | 963 |
| **JAN_DEC_ONLY** | Dec 2025 only | Implicit | **54.7%** | **4.53** | 609 |

### Key Observations

1. **Stacked ensemble ≈ Single CatBoost** - No meaningful difference (50.0% vs 49.4%)
2. **Recency weighting doesn't help** - ENS_REC60 (50.1%) ≈ ENS_BASELINE (50.0%)
3. **JAN_DEC dominates** - +5% hit rate over all old-data models

---

## Why Session 52's 65% Result Didn't Replicate

Session 52 found: "60-day recency weighting achieves 65% hit rate on high-confidence picks"

**Key differences:**

| Factor | Session 52 | Session 55 |
|--------|-----------|-----------|
| Model | Single CatBoost | Stacked Ensemble |
| Evaluation | 5+ point edge | 3+ point edge |
| Bet volume | 40 bets | 888-963 bets |
| Statistical significance | Low (40 bets) | Higher (900+ bets) |

The 65% result was likely noise from a small sample (40 bets). With 900+ bets, the true performance is ~50%.

---

## Architecture Analysis Confirmed

### Production V8 Uses Single CatBoost

```python
# catboost_v8.py line 480
model_files = list(models_dir.glob("catboost_v8_33features_*.cbm"))
self.model = cb.CatBoostRegressor()
self.model.load_model(str(model_path))
# XGBoost and LightGBM are NOT loaded in production
```

### Stacked Ensemble Coefficients

| Experiment | XGBoost | LightGBM | CatBoost |
|------------|---------|----------|----------|
| V8 Training | 0.38 | -0.10 | 0.74 |
| ENS_BASELINE | 0.29 | 0.11 | 0.59 |
| ENS_REC60 | 0.46 | 0.21 | 0.31 |

Observations:
- V8 training had negative LightGBM weight (penalized)
- Recency weighting changed the coefficient balance significantly
- CatBoost dominates in all cases

---

## Why Training on Recent Data Wins

The fundamental insight: **Player behavior has drifted from 2021-2024 to January 2026.**

### What Changed

| Factor | 2021-2024 | January 2026 |
|--------|----------|--------------|
| Player roles | Different | New stars emerged, veterans declined |
| Team compositions | Different | Major trades (Luka to LAL, etc.) |
| Pace of play | Slower | Faster (league trend) |
| Three-point rate | Lower | Higher |
| Load management | Less common | More common |

### Why Recency Weighting Doesn't Fix This

Recency weighting (60-day half-life) still includes data from 2021-2024:
- 365 days old: weight = 0.3% of max
- But that's still 0.3% × 70,000 samples = ~200 effective samples of old data

Training on December 2025 only:
- 4,400 samples of purely current behavior
- No pollution from old patterns

---

## Recommendations

### 1. Deploy JAN_DEC_ONLY Model (Priority: Immediate)

The JAN_DEC model outperforms V8 by 5% hit rate. This is production-ready:

```bash
# Copy to GCS
gsutil cp ml/experiments/results/catboost_v9_exp_JAN_DEC_ONLY_20260131_085101.cbm \
    gs://nba-props-models/catboost_jan_dec_v1.cbm
```

### 2. Abandon Stacked Ensemble (Priority: Now)

The stacked ensemble provides no benefit:
- Same hit rate as single model
- 3x complexity (model loading, inference)
- Not worth the overhead

### 3. Set Up Monthly Retraining (Priority: High)

Train on last 60 days at the start of each month:

```bash
# February model
PYTHONPATH=. python ml/experiments/train_walkforward.py \
    --train-start 2025-12-01 \
    --train-end 2026-01-31 \
    --experiment-id FEB_2026
```

### 4. Increase Edge Threshold (Priority: Immediate)

V8 at 3+ edge: 49.4% (losing money)
V8 at 5+ edge: ~54% (profitable)

Until JAN_DEC is deployed:
```python
MIN_EDGE_THRESHOLD = 5.0  # Up from 3.0
```

---

## Files Created

| File | Purpose |
|------|---------|
| `ml/experiments/train_stacked_ensemble_recency.py` | Training script for stacked ensemble with recency |
| `ml/experiments/evaluate_stacked_ensemble.py` | Evaluation script for stacked ensemble |
| `ml/experiments/results/ensemble_exp_ENS_REC60_*` | Recency-weighted ensemble models |
| `ml/experiments/results/ensemble_exp_ENS_BASELINE_*` | Baseline ensemble models |
| `docs/.../V8-ARCHITECTURE-ANALYSIS.md` | V8 architecture documentation |

---

## Key Learnings

1. **Training data recency > Recency weights** - Use recent data only, not weighted old data
2. **Ensemble complexity isn't worth it** - Single CatBoost performs the same
3. **Small sample results are unreliable** - 40 bets at 65% doesn't replicate at scale
4. **Player behavior drifts** - Models need regular retraining

---

## Next Steps

1. ✅ Stacked ensemble experiments - Complete (no benefit)
2. ⏳ Deploy JAN_DEC model - Ready for implementation
3. ⏳ Monthly retraining pipeline - Design in progress
4. ⏳ Drift detection - Next task

---

*Session 55 - Stacked Ensemble Experiments Complete*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
