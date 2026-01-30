# Session 26 Handoff - Walk-Forward Experiments

**Date:** 2026-01-29
**Author:** Claude Opus 4.5
**Status:** COMPLETE
**Commit:** d4bc7061

---

## Executive Summary

Built ML experiment infrastructure and ran 6 walk-forward experiments to understand optimal training strategy. **All experiments achieved 72-74% hit rate** - the model is robust across different training configurations.

| Series | Question | Best Result |
|--------|----------|-------------|
| A (window size) | How much training data? | A2: 73.9% (2 seasons) |
| B (recency) | Recent vs older data? | B3: 73.8% (recent 2 seasons) |

---

## What Was Built

### Experiment Infrastructure (`ml/experiments/`)

```
ml/experiments/
├── __init__.py              # Module description
├── train_walkforward.py     # Train on any date range
├── evaluate_model.py        # Evaluate with hit rate/ROI/MAE
├── run_experiment.py        # Combined train + eval
├── compare_results.py       # Compare all experiments
└── results/                 # Models + JSON results
```

### Quick Commands

```bash
# Run a new experiment
PYTHONPATH=. python ml/experiments/run_experiment.py \
    --experiment-id NEW_EXP \
    --train-start 2021-11-01 --train-end 2024-06-01 \
    --eval-start 2024-10-01 --eval-end 2025-01-29

# Compare all results
PYTHONPATH=. python ml/experiments/compare_results.py
```

---

## Experiment Results

### Full Comparison Table

| Exp | Training Data | Eval Period | Samples | Hit Rate | ROI | MAE |
|-----|--------------|-------------|---------|----------|-----|-----|
| A1 | 2021-22 (26K) | 2022-23 | 25,574 | 72.3% | +37.8% | 3.893 |
| A2 | 2021-23 (52K) | 2023-24 | 25,948 | **73.9%** | +40.8% | 3.661 |
| A3 | 2021-24 (78K) | 2024-25 | 3,120 | 73.6% | +40.3% | 3.577 |
| B1 | 2021-23 (52K) | 2024-25 | 3,120 | 73.0% | +39.1% | 3.603 |
| B2 | 2023-24 (26K) | 2024-25 | 3,120 | 73.5% | +40.0% | 3.658 |
| B3 | 2022-24 (51K) | 2024-25 | 3,120 | 73.8% | +40.6% | 3.617 |

### Key Findings

1. **All configurations work well**: 72-74% hit rate regardless of training window
2. **More data → lower MAE**: Point prediction accuracy improves with more training data
3. **Recency matters slightly**: Recent 2 seasons (B3) marginally better than older 2 seasons (B1)
4. **No decay observed**: Models trained years ago still perform on recent data
5. **UNDER bets stronger**: Consistently 76-78% vs 69-71% for OVER

### Recommendations

| Decision | Recommendation |
|----------|---------------|
| Training window | **2-3 seasons** (balance of recency and volume) |
| Retraining frequency | **Quarterly** (model doesn't decay quickly) |
| Expected performance | **73% hit rate, 40% ROI** |

---

## Files Changed

| File | Change |
|------|--------|
| `ml/experiments/__init__.py` | NEW: Module init |
| `ml/experiments/train_walkforward.py` | NEW: Training script |
| `ml/experiments/evaluate_model.py` | NEW: Evaluation script |
| `ml/experiments/run_experiment.py` | NEW: Combined runner |
| `ml/experiments/compare_results.py` | NEW: Comparison tool |
| `ml/experiments/results/*.cbm` | NEW: 6 trained models |
| `ml/experiments/results/*.json` | NEW: 12 result files |
| `docs/.../EXPERIMENT-INFRASTRUCTURE.md` | NEW: How-to guide |
| `docs/.../WALK-FORWARD-EXPERIMENT-PLAN.md` | Updated with results |
| `docs/.../README.md` | Updated with experiment status |

---

## Documentation Created

| Document | Location |
|----------|----------|
| Experiment Infrastructure Guide | `docs/08-projects/current/catboost-v8-performance-analysis/EXPERIMENT-INFRASTRUCTURE.md` |
| Updated Experiment Plan | `docs/08-projects/current/catboost-v8-performance-analysis/WALK-FORWARD-EXPERIMENT-PLAN.md` |

---

## What's Not Deployed

The experiment infrastructure is **local only** - these scripts run on your machine to train and evaluate models. No production deployment needed.

The production prediction worker is unchanged and still uses the existing CatBoost V8 model (which was fixed in Session 25).

---

## Next Session Checklist

### If continuing experiments:
```bash
# Run decay analysis (Series C)
# This shows month-by-month performance to understand how quickly models age
PYTHONPATH=. python ml/experiments/run_experiment.py \
    --experiment-id C1 \
    --train-start 2021-11-01 --train-end 2023-06-30 \
    --eval-start 2023-10-01 --eval-end 2024-06-30 \
    --monthly-breakdown
```

### If retraining production model:
```bash
# Train new model with all available data
PYTHONPATH=. python ml/experiments/run_experiment.py \
    --experiment-id prod_v9 \
    --train-start 2021-11-01 --train-end 2025-01-29 \
    --eval-start 2025-01-01 --eval-end 2025-01-29
```

### Quick health check:
```bash
bq query --use_legacy_sql=false \
  "SELECT game_date, AVG(predicted_points - current_points_line) as avg_edge
   FROM nba_predictions.player_prop_predictions
   WHERE system_id='catboost_v8' AND game_date >= CURRENT_DATE() - 3
   GROUP BY 1"
```

---

## Summary Statistics

| Metric | Value |
|--------|-------|
| Experiments run | 6 |
| Models trained | 6 |
| Total training time | ~10 minutes |
| Scripts created | 4 |
| Docs created/updated | 3 |
| Commits | 1 |

---

*Session 26 complete: 2026-01-29*
