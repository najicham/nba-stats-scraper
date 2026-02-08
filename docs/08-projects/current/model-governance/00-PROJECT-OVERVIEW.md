# Model Governance Project

**Session:** 163 (2026-02-08)
**Status:** Implemented
**Priority:** Critical (responding to model performance crash)

## Problem Statement

On Feb 2, a retrained CatBoost V9 model was deployed to production without proper validation. The retrained model had:
- **51.2% high-edge hit rate** (down from 71.2% with the original)
- **-2.26 avg pred_vs_vegas bias** (systematic UNDER-prediction)
- **87% UNDER recommendation skew** (vs ~50% balanced)

The root causes:
1. No Vegas bias check before deployment — MAE looked better (4.12 vs 4.82) but predictions were miscalibrated vs market
2. No immutable model versioning — `MODEL_VERSION` was hardcoded to `"v9_current_season"` for all retrains
3. No model integrity verification — no SHA256 hashing
4. Dockerfile glob pattern mismatch — monthly model sat in Docker image unused
5. No shadow testing process — retrains went straight to production

## Investigation Findings

### Timeline
| Date | Event | Impact |
|------|-------|--------|
| Feb 1 | Original V9 created (Session 67) | 71.2% high-edge hit rate |
| Feb 1 10:10 AM | Jan 10-29 backfilled with original V9 | Great performance |
| Feb 2 | Retrained model deployed (Session 82) | Hit rate crashed |
| Feb 2-7 | Bad model in production | 53.4% hit rate, -5.3 pred_vs_vegas |
| Feb 8 (Session 163) | Rolled back to original V9 | Performance restored |

### Model Comparison
| Metric | Original V9 | Feb 2 Retrain | Feb 7 Monthly |
|--------|------------|---------------|---------------|
| **File** | catboost_v9_33features_20260201_011018.cbm | catboost_v9_feb_02_retrain.cbm | catboost_v9_2026_02.cbm |
| **Size** | 700KB | 800KB | 979KB |
| **SHA256** | 5b3a187b... | 5ecf7ba3... | 9f7cea27... |
| **Training** | Nov 2 - Jan 8 | Nov 2 - Jan 31 | Nov 2 - Jan 31 |
| **High-edge HR** | 71.2% | 51.2% | 53.7% |
| **pred_vs_vegas** | -0.13 (neutral) | -2.26 (UNDER bias) | -4.83 (worse) |
| **Status** | PRODUCTION | Deprecated | Untested |

### Why the Retrain Was Worse
The Feb 2 retrain had lower MAE (4.12 vs 4.82) which LOOKED better. But MAE measures absolute error, not directional accuracy. The retrained model was systematically predicting lower than Vegas lines, creating massive UNDER recommendation skew. Vegas lines are set by professional oddsmakers with market efficiency — a model that systematically disagrees with Vegas by -2.26 points is usually wrong.

## Solution Implemented

### 1. Immediate Rollback
- Changed `CATBOOST_V9_MODEL_PATH` env var to original model
- Regenerated Feb 8 predictions (67 expected)
- Backfilling Feb 1-7 with original model

### 2. Dynamic Model Versioning (`catboost_v9.py`)
- `MODEL_VERSION` derived from loaded filename (e.g., `v9_20260201_011018`)
- SHA256 computed at load time
- Local glob matches any `catboost_v9*.cbm` (was `catboost_v9_33features_*`)
- Model file name and SHA256 written to every prediction metadata

### 3. Model Registry
- **BigQuery table:** `nba_predictions.model_registry` with SHA256 column
- **GCS manifest:** `gs://nba-props-platform-models/catboost/v9/manifest.json`
- **CLI tool:** `./bin/model-registry.sh list|production|validate|manifest`
- All 3 V9 models registered with SHA256 hashes and status

### 4. Governance Gates in `quick_retrain.py`
New gates that MUST pass before a model can be deployed:

| Gate | Threshold | Why |
|------|-----------|-----|
| **Vegas bias** | pred_vs_vegas within +/- 1.5 | Feb 2 retrain was -2.26 |
| **High-edge hit rate** | >= 60% on edge 3+ | Feb 2 retrain was 51.2% |
| **Sample size** | >= 50 graded edge 3+ bets | Statistical reliability |
| **Tier bias** | No tier > +/- 5 points | Regression-to-mean detection |
| **MAE improvement** | Lower than baseline | Basic accuracy check |

### 5. Standard Naming Convention
Models: `catboost_v9_{train_end_YYYYMMDD}_{timestamp_HHMMSS}.cbm`
Example: `catboost_v9_20260131_143022.cbm`

## Promotion Process

```
1. Train: PYTHONPATH=. python ml/experiments/quick_retrain.py --name "MAR_MONTHLY"
2. Verify: ALL gates must pass (script outputs gate summary)
3. Upload: gsutil cp models/catboost_v9_*.cbm gs://nba-props-platform-models/catboost/v9/
4. Register: Add to model_registry table + update manifest.json
5. Shadow: Run for 2+ days alongside production (different system_id)
6. Compare: Check pred_vs_vegas, hit rate, and direction balance
7. Promote: Update CATBOOST_V9_MODEL_PATH env var
8. Monitor: Watch hit rate for 48 hours after switch
```

## Rollback Procedure

```bash
# 1. Find the production model
./bin/model-registry.sh production

# 2. Switch env var to previous model
gcloud run services update prediction-worker \
  --region=us-west2 --project=nba-props-platform \
  --update-env-vars="CATBOOST_V9_MODEL_PATH=gs://nba-props-platform-models/catboost/v9/PREVIOUS_MODEL.cbm"

# 3. Regenerate today's predictions
curl -X POST "https://prediction-coordinator-756957797294.us-west2.run.app/start" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"game_date":"YYYY-MM-DD","prediction_run_mode":"BACKFILL"}'

# 4. Update registry
./bin/model-registry.sh  # Update statuses in BQ
```

## Files Modified
- `predictions/worker/prediction_systems/catboost_v9.py` — Dynamic versioning, SHA256
- `predictions/worker/Dockerfile` — Fixed glob mismatch
- `ml/experiments/quick_retrain.py` — Governance gates
- `bin/model-registry.sh` — SHA256 validation, manifest command
- `nba_predictions.model_registry` — Added SHA256 column, fixed statuses
- `gs://nba-props-platform-models/catboost/v9/manifest.json` — Created
