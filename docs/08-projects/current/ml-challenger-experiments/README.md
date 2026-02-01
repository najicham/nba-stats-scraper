# ML Challenger Experiments - CatBoost V9

**Status:** ✅ V9 MODEL IMPLEMENTED - READY FOR DEPLOYMENT
**Created:** Session 61 (2026-02-01)
**Completed:** Session 67 (2026-02-01)

---

## Project Summary

This project discovered that the V8 model's 84% hit rate was fake due to data leakage, trained challenger models to find a working configuration, and successfully created CatBoost V9 which achieves **56.5% premium hit rate** on clean, non-leaked data.

### Key Outcome

| Model | Training | Premium HR | High-Edge HR | MAE |
|-------|----------|------------|--------------|-----|
| V8 (old) | 2021-2024 historical | 52.5% | 56.9% | 5.36 |
| **V9 (new)** | Current season only | **56.5%** | **72.2%** | **4.82** |

V9 beats V8 on all metrics.

---

## Documents

| Document | Purpose |
|----------|---------|
| [EXPERIMENT-PLAN.md](./EXPERIMENT-PLAN.md) | Experiment definitions, results, root cause analysis |
| [V9-PROMOTION-PLAN.md](./V9-PROMOTION-PLAN.md) | Deployment checklist, retraining strategy |
| [HISTORICAL-FEATURE-CLEANUP-PLAN.md](./HISTORICAL-FEATURE-CLEANUP-PLAN.md) | Future: cleaning historical data for cross-season training |

---

## V9 Model Specification

### Training Configuration

| Property | Value |
|----------|-------|
| Training Period | Nov 2, 2025 → Jan 8, 2026 |
| Training Samples | 9,993 |
| Features | 33 (same as V8) |
| Model File | `catboost_v9_33features_20260201_011018.cbm` |
| System ID | `catboost_v9` |

### Why Current Season Training?

1. **Avoids historical data quality issues**
   - `team_win_pct` was broken (always 0.5) before Nov 2025
   - Vegas imputation mismatch between training and inference

2. **Captures current patterns**
   - Player roles change season-to-season
   - Team dynamics, trades, injuries
   - League trends (pace, three-point rates)

3. **Designed for monthly retraining**
   - Training window expands as season progresses
   - Always trained on most recent data

---

## Implementation Status

### Completed ✅

- [x] Discovered data leakage bug (Session 66)
- [x] Ran 4 challenger experiments (Session 67)
- [x] Verified evaluation data is clean (no leakage)
- [x] Created `catboost_v9.py` prediction system
- [x] Updated worker to support V9 via `CATBOOST_VERSION` env var
- [x] Created feature audit script (`bin/audit_feature_store.py`)

### Pending (Deployment)

- [ ] Upload model to GCS: `gs://nba-props-platform-models/catboost/v9/`
- [ ] Deploy prediction-worker with `CATBOOST_VERSION=v9`
- [ ] Monitor for 48-72 hours
- [ ] Register model in `ml_model_registry` table

---

## Usage

### Switch to V9 (Default)

```bash
# V9 is now the default
CATBOOST_VERSION=v9 ./bin/deploy-service.sh prediction-worker
```

### Rollback to V8

```bash
CATBOOST_VERSION=v8 ./bin/deploy-service.sh prediction-worker
```

### Verify Model Version

```bash
# Check which model is running
curl https://prediction-worker-xxx.run.app/ | jq '.systems'
```

---

## Monthly Retraining

V9 is designed for monthly retraining:

```bash
# Retrain with expanded window
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_$(date +%b)_RETRAIN" \
    --train-start 2025-11-02 \
    --train-end $(date -d "yesterday" +%Y-%m-%d) \
    --eval-start $(date -d "7 days ago" +%Y-%m-%d) \
    --eval-end $(date -d "yesterday" +%Y-%m-%d)
```

---

## Related Sessions

- **Session 66**: Discovered data leakage bug
- **Session 67**: Ran experiments, implemented V9

---

*Last Updated: Session 67, 2026-02-01*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
