# ML Model v8 Deployment Project

**Status**: Ready for Production
**Created**: January 8-9, 2026
**Best Model**: v8 Stacked Ensemble (3.40 MAE)

---

## Executive Summary

After extensive experimentation, we achieved a **29% improvement over the mock baseline** and **25% better than Vegas** on out-of-sample 2024-25 season data.

| Metric | Value |
|--------|-------|
| Test MAE | 3.40 points |
| vs Mock (4.80) | -29.1% |
| vs Vegas (4.98) | -31.8% |
| Betting Accuracy | 71.6% |
| High-Confidence (>5pt edge) | 91.5% |

---

## Project Documents

| Document | Description |
|----------|-------------|
| [MODEL-SUMMARY.md](./MODEL-SUMMARY.md) | Technical details of v8 model architecture |
| [IMPROVEMENT-JOURNEY.md](./IMPROVEMENT-JOURNEY.md) | Full timeline of ML experiments |
| [NEXT-STEPS.md](./NEXT-STEPS.md) | Recommendations for deployment and further work |
| [SHADOW-MODE-GUIDE.md](./SHADOW-MODE-GUIDE.md) | Shadow mode implementation and usage |
| [ML-EXPERIMENT-ARCHITECTURE.md](./ML-EXPERIMENT-ARCHITECTURE.md) | **NEW**: Multi-model experimentation pipeline |

---

## Quick Reference

### Model Files
```
models/xgboost_v8_33features_*.json      # XGBoost component (3.45 MAE)
models/lightgbm_v8_33features_*.txt      # LightGBM component (3.47 MAE)
models/catboost_v8_33features_*.cbm      # CatBoost component (3.43 MAE)
models/ensemble_v8_*_metadata.json       # Ensemble metadata (3.40 MAE)
```

### Training Script
```
ml/train_final_ensemble_v8.py
```

### Key Features (Top 5)
1. `points_avg_last_5` (31.8%)
2. `points_avg_last_10` (18.6%)
3. `ppm_avg_last_10` (14.6%) - **BREAKTHROUGH FEATURE**
4. `minutes_avg_last_10` (10.9%) - **BREAKTHROUGH FEATURE**
5. `points_std_last_10` (6.3%)

---

## Immediate Opportunity: Injury Filter

**NEW FINDING**: We can prevent 28.6% of DNP errors with a simple inference-time filter.

| DNP Category | Catchable | Action |
|--------------|-----------|--------|
| Listed "OUT" | 1,833 (28.6%) | Skip prediction |
| Listed "QUESTIONABLE" | 567 (8.8%) | Flag uncertainty |
| No report | 3,760 (58.6%) | Can't catch |

This is NOT a model change - just check injury report before generating predictions.

See [NEXT-STEPS.md](./NEXT-STEPS.md) for implementation details.

---

## Deployment Recommendation

**Deploy immediately in shadow mode**, then gradual rollout:

1. Week 1-2: Shadow mode (log v8 predictions alongside mock)
2. Week 3: 25% traffic to v8
3. Week 4+: Full rollout if metrics hold

See [NEXT-STEPS.md](./NEXT-STEPS.md) for detailed deployment plan.
