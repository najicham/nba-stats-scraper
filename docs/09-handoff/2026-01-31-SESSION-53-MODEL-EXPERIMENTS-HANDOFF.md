# Session 53 Handoff - Model Retraining Experiments

**Date:** 2026-01-31
**Focus:** CatBoost model retraining experiments and performance analysis
**Status:** Research complete, implementation plan ready

---

## Executive Summary

We investigated the model drift issue (50.6% hit rate in January vs 62.7% in early January) by training 6 new CatBoost models with different data configurations. Key finding: **Production V8 significantly outperforms all retrained models because it's a stacked ensemble (XGBoost + LightGBM + CatBoost with Ridge meta-learner), not a single CatBoost model.**

### Critical Insights

1. **Star player predictions are the root cause of drift** - Our models get 29-39% on stars vs V8's 55.8%
2. **Rotation/bench players perform well** - Our models match or beat V8 (63% vs 59%)
3. **High confidence + high edge is key** - V8 at 90% conf + 3+ edge = 78.6% hit rate
4. **Training data period matters less than architecture** - Same-period training still underperforms V8 ensemble

---

## Experiments Conducted

### Models Trained

| Experiment ID | Training Period | Features | Samples | Val MAE |
|---------------|-----------------|----------|---------|---------|
| JAN_DEC_ONLY | Dec 2025 | 37 | 4,415 | 4.74 |
| JAN_NOV_DEC | Nov-Dec 2025 | 33 | 8,949 | 4.33 |
| JAN_NOV_DEC_RECENCY | Nov-Dec 2025 (60d half-life) | 33 | 8,949 | 4.33 |
| JAN_LAST_SEASON | Nov 2024 - Apr 2025 | 34 | 24,845 | 4.27 |
| JAN_COMBINED | Nov 2024 - Dec 2025 | 34 | 34,795 | 4.05 |
| JAN_FULL_HISTORY | Nov 2021 - Jun 2024 | 33 | 77,780 | 3.64 |

### Evaluation Results (January 2026)

| Model | Hit Rate (1+ edge) | Hit Rate (3+ edge) | MAE | vs Breakeven |
|-------|-------------------|-------------------|-----|--------------|
| **V8 Production** | **57.3%** | **58.8%** | 5.19 | **+4.9%** |
| JAN_LAST_SEASON | 53.4% | 57.4% | 5.07 | +1.0% |
| JAN_NOV_DEC | 53.0% | 59.4% | 5.06 | +0.6% |
| JAN_DEC_ONLY | 55.1% | 61.6% | 4.90 | +2.7% |
| JAN_FULL_HISTORY | 51.0% | 52.2% | 5.48 | -1.4% |
| JAN_COMBINED | 49.0% | 53.8% | 5.12 | -3.4% |

---

## Performance by Confidence Level

### V8 Production (90%+ confidence)

| Edge | Hit Rate | Bets |
|------|----------|------|
| 1+ | 66.4% | 426 |
| 2+ | 68.6% | 271 |
| 3+ | **78.6%** | 140 |
| 5+ | **81.8%** | 44 |

### Our Best Models (90%+ confidence)

| Edge | JAN_LAST_SEASON | JAN_DEC_ONLY | JAN_NOV_DEC |
|------|-----------------|--------------|-------------|
| 1+ | 55.2% (212) | 55.1% (294) | 56.4% (275) |
| 2+ | 56.2% (89) | 59.1% (154) | 55.9% (143) |
| 3+ | 60.0% (45) | 61.6% (73) | 59.4% (69) |
| 5+ | 47.6% (21) | 58.3% (12) | 66.7% (9) |

---

## Performance by Player Tier (Edge >= 2)

| Tier | V8 Prod | JAN_DEC_ONLY | JAN_NOV_DEC | JAN_LAST_SEASON |
|------|---------|--------------|-------------|-----------------|
| **Star (25+)** | **55.8%** | 29.6% | 30.9% | 38.8% |
| Starter (15-25) | 56.3% | **59.9%** | **59.4%** | 56.2% |
| Rotation (5-15) | 59.1% | **63.0%** | 60.5% | 58.9% |
| Bench (<5) | **57.5%** | 40.4% | 38.3% | 52.1% |

**Key Finding:** Our models excel at rotation players (63% vs 59%) but fail at stars (30% vs 56%).

---

## Ensemble Experiments

| Strategy | MAE | 2+ Edge | 3+ Edge |
|----------|-----|---------|---------|
| Production V8 | 5.19 | 57.6% | 58.8% |
| Simple Average (4 models) | 5.06 | 51.7% | 53.9% |
| Weighted Average | 5.12 | 51.8% | 53.8% |
| Consensus (3+/4 agree) | 5.05 | 51.6% | 53.7% |
| **Vegas Blend (80/20)** | **4.94** | 52.0% | **59.9%** |

**Vegas Blend at 3+ edge approaches V8 performance (59.9% vs 58.8%).**

---

## Data Quality Status

| Period | Feature Count | Corruption Rate | Notes |
|--------|---------------|-----------------|-------|
| 2021-2024 | 33 | <1% | Clean historical data |
| Nov 2025 | 33-37 | 8.6% | pts_avg_season errors |
| Dec 2025 | 33-37 | 1.2% | Acceptable |
| Jan 2026 | 33-37 | 1.5% | Acceptable |

---

## Root Cause Analysis

### Why V8 Outperforms Retrained Models

1. **Stacked Ensemble Architecture**
   - V8 uses XGBoost + LightGBM + CatBoost with Ridge meta-learner
   - Our experiments only used single CatBoost models
   - Ensemble diversity captures different patterns

2. **Star Player Handling**
   - V8: 55.8% hit rate on stars
   - Our models: 30-39% on stars
   - Stars have higher variance, ensemble smooths this

3. **Confidence Calibration**
   - V8 at 90% confidence = actual 68-82% accuracy
   - Our models at 90% confidence = actual 55-60% accuracy

### Why Star Predictions Fail

1. **Increased variance in January** - Stars scoring 9+ points above their averages (vs 7 in December)
2. **Breakout games unpredictable** - Role players having career nights (Jaylon Tyson: 39 pts on 13.4 avg)
3. **Trade impacts** - Luka to LAL, Ingram to TOR, Bane to ORL changed team contexts

---

## Files Created

### Models
```
ml/experiments/results/
├── catboost_v9_exp_JAN_DEC_ONLY_20260131_085101.cbm
├── catboost_v9_exp_JAN_NOV_DEC_20260131_085112.cbm
├── catboost_v9_exp_JAN_NOV_DEC_RECENCY_20260131_085120.cbm
├── catboost_v9_exp_JAN_LAST_SEASON_20260131_085238.cbm
├── catboost_v9_exp_JAN_COMBINED_20260131_085311.cbm
├── catboost_v9_exp_JAN_COMBINED_RECENCY_20260131_085332.cbm
├── catboost_v9_exp_JAN_FULL_HISTORY_20260131_085719.cbm
└── *_metadata.json (for each model)
```

### Code Changes
- `ml/experiments/evaluate_model.py` - Updated to handle 33/34/37 features dynamically

---

## Next Session Research Plan

See: `docs/08-projects/current/model-ensemble-research/RESEARCH-PLAN.md`

---

## Immediate Recommendations

### 1. Quick Win: Stricter Filtering
Only bet when:
- Confidence >= 90%
- Edge >= 3 points
- This gives V8 78.6% hit rate vs current 57%

### 2. Tier-Based Model Selection
- **Stars (25+)**: Use V8 production or Vegas blend
- **Rotation (5-15)**: Use JAN_DEC_ONLY (63% vs V8's 59%)
- **Bench (<5)**: Use V8 production

### 3. Vegas Blend for High Edge
At 3+ edge, Vegas Blend (80% model, 20% Vegas) achieves 59.9% = near V8 performance

---

## Key Learnings

1. **Model architecture > training data** - Same data, different architecture = different results
2. **Ensemble is essential** - Single models can't match ensemble diversity
3. **Player tier matters** - Different tiers need different strategies
4. **Confidence calibration is critical** - V8's confidence actually means something
5. **Recency weighting didn't help** - More data > recent data for CatBoost

---

## Commands Reference

```bash
# Train a new model
source .venv/bin/activate && PYTHONPATH=. python ml/experiments/train_walkforward.py \
    --train-start 2021-11-01 \
    --train-end 2024-06-30 \
    --experiment-id EXP_NAME

# Evaluate a model
source .venv/bin/activate && PYTHONPATH=. python ml/experiments/evaluate_model.py \
    --model-path "ml/experiments/results/catboost_v9_exp_*.cbm" \
    --eval-start 2026-01-01 \
    --eval-end 2026-01-30 \
    --experiment-id EXP_NAME \
    --monthly-breakdown

# Compare all results
source .venv/bin/activate && PYTHONPATH=. python ml/experiments/compare_results.py
```

---

*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
