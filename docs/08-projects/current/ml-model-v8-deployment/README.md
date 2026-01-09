# ML Model v8 Deployment Project

**Status**: DEPLOYED & BACKFILLED
**Created**: January 8-9, 2026
**Best Model**: v8 Stacked Ensemble (3.40 MAE training, 4.11 MAE backfill)

---

## Executive Summary

CatBoost V8 is now **live in production** and backfilled across 121,524 historical predictions.

### Training Metrics (Test Set)

| Metric | Value |
|--------|-------|
| Test MAE | 3.40 points |
| vs Mock (4.80) | -29.1% |
| Betting Accuracy | 71.6% |
| High-Confidence (≥10pt edge) | 91.5% |

### Backfill Results (All Historical Data)

| Metric | Value |
|--------|-------|
| Backfill MAE | 4.11 points |
| vs Vegas (4.93) | **-0.82 (model wins)** |
| Betting Accuracy | **74.6%** |
| High-Confidence (≥10pt edge) | **91.6%** |

### 2025-26 Season (Current)

| Metric | Value |
|--------|-------|
| Predictions | 1,626 |
| Win Rate | 71.8% |
| High-Confidence (≥10pt edge) | **94.0% (116 picks)** |

---

## Project Documents

| Document | Description |
|----------|-------------|
| [BACKFILL-RESULTS.md](./BACKFILL-RESULTS.md) | **NEW**: Backfill performance and 2025-26 season results |
| [PRODUCTION-DEPLOYMENT.md](./PRODUCTION-DEPLOYMENT.md) | Deployment guide and configuration |
| [MODEL-SUMMARY.md](./MODEL-SUMMARY.md) | Technical details of v8 model architecture |
| [IMPROVEMENT-JOURNEY.md](./IMPROVEMENT-JOURNEY.md) | Full timeline of ML experiments |
| [NEXT-STEPS.md](./NEXT-STEPS.md) | Recommendations for further work |
| [SHADOW-MODE-GUIDE.md](./SHADOW-MODE-GUIDE.md) | Shadow mode implementation and usage |
| [ML-EXPERIMENT-ARCHITECTURE.md](./ML-EXPERIMENT-ARCHITECTURE.md) | Multi-model experimentation pipeline |

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

## Deployment Status

**V8 is now LIVE in production** (replaced mock XGBoostV1 on January 9, 2026).

### What's Deployed
- Production worker uses CatBoostV8 (33 features)
- Model uploaded to GCS: `gs://nba-props-platform-ml-models/catboost_v8_33features_20260108_211817.cbm`
- Feature store upgraded to 33 features
- 121,524 historical predictions backfilled
- Phase 6 export complete

See [PRODUCTION-DEPLOYMENT.md](./PRODUCTION-DEPLOYMENT.md) for configuration details.
