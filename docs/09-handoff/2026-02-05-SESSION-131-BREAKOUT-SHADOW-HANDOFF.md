# Session 131 Handoff - Breakout Classifier Shadow Mode Verification

**Date:** 2026-02-05
**Session:** 131
**Focus:** Fix breakout classifier model loading + proper naming convention

---

## Summary

Fixed breakout classifier shadow mode deployment. The model file was not being copied to the Docker image, causing the classifier to return LOW_RISK for all players. Implemented proper model naming convention with training dates.

---

## What Was Done

### 1. Fixed Model Not Loading (P0)

**Issue:** Breakout classifier logs showed:
```
No Breakout Classifier model files found in /app/models. Expected files matching: breakout_exp_EXP_COMBINED_BEST_*.cbm
```

**Root Cause:** Session 130B committed the classifier code but did NOT add the model file to the Dockerfile.

**Fix:**
- Upload models to GCS: `gs://nba-props-platform-models/breakout/v1/`
- Add `BREAKOUT_CLASSIFIER_MODEL_PATH` env var pointing to GCS model
- Update classifier to load from GCS instead of local file

### 2. Implemented Proper Model Naming

**New Convention:** `breakout_v1_{train_start}_{train_end}.cbm`

Example: `breakout_v1_20251102_20260115.cbm` (trained Nov 2 to Jan 15)

**Models Created:**
| Model | Training Window | AUC | Purpose |
|-------|----------------|-----|---------|
| `breakout_v1_20251102_20260115.cbm` | Nov 2 - Jan 15 | 0.6933 | Validation on recent weeks |
| `breakout_v1_20251102_20260205.cbm` | Nov 2 - Feb 5 | 0.7302 | Full training data |

### 3. Code Changes

**Files Modified:**
- `predictions/worker/prediction_systems/breakout_classifier_v1.py` - Updated model loading pattern
- `predictions/worker/Dockerfile` - Use GCS path instead of local file

**Commits:**
- `2f8cc6ff` - fix: Include breakout classifier model in worker Docker image
- `8886339c` - feat: Update breakout classifier naming and GCS model loading

---

## Deployment Status

**DEPLOYMENT IN PROGRESS**

```bash
# Check deployment status
tail -20 /tmp/claude-1000/-home-naji-code-nba-stats-scraper/tasks/bdddd9c.output

# Or run fresh deploy
./bin/deploy-service.sh prediction-worker
```

**Environment Variable Set:**
```
BREAKOUT_CLASSIFIER_MODEL_PATH=gs://nba-props-platform-models/breakout/v1/breakout_v1_20251102_20260115.cbm
```

---

## P0: Complete Deployment & Verify

After deployment completes:

1. **Check logs for successful model load:**
```bash
gcloud run services logs read prediction-worker --region=us-west2 --limit=50 | grep -i "breakout"
```

Should see:
```
Loading Breakout Classifier from env var: gs://nba-props-platform-models/breakout/v1/breakout_v1_20251102_20260115.cbm
Breakout Classifier V1 model loaded successfully
```

2. **Verify shadow data after next prediction run (~2:30 AM ET):**
```sql
SELECT
  game_date,
  COUNT(*) as total,
  COUNTIF(JSON_VALUE(features_snapshot, '$.breakout_shadow.risk_score') IS NOT NULL) as with_shadow
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-02-05'
GROUP BY game_date;
```

---

## P1: Backfill Validation

Use the mid-January model to backfill and validate on Jan 16 - Feb 5 games:

```bash
# Use model-experiment skill to analyze performance
/model-experiment
```

The mid-Jan model (AUC 0.6933) can be used to see how breakout filtering would have performed on the past 3 weeks.

---

## Key Files

- Classifier code: `predictions/worker/prediction_systems/breakout_classifier_v1.py`
- Models in GCS: `gs://nba-props-platform-models/breakout/v1/`
- Experiment runner: `ml/experiments/breakout_experiment_runner.py`

---

## Model Naming Convention

Per `docs/08-projects/current/ml-challenger-training-strategy/MODEL-NAMING-CONVENTIONS.md`:

| Type | Pattern | Example |
|------|---------|---------|
| Production | `breakout_v1_{train_start}_{train_end}.cbm` | `breakout_v1_20251102_20260115.cbm` |
| Experiments | `exp_YYYYMMDD_hypothesis.cbm` | `exp_20260205_breakout_deep.cbm` |

---

## Quick Commands

```bash
# Check deployment status
./bin/whats-deployed.sh

# Verify env var
gcloud run services describe prediction-worker --region=us-west2 \
  --format="value(spec.template.spec.containers[0].env)" | tr ';' '\n' | grep BREAKOUT

# List GCS models
gsutil ls gs://nba-props-platform-models/breakout/v1/

# Train new model with different dates
PYTHONPATH=. python ml/experiments/breakout_experiment_runner.py \
  --name "BREAKOUT_V1_NEW" \
  --train-start 2025-11-02 \
  --train-end 2026-01-31 \
  --eval-start 2026-02-01 \
  --eval-end 2026-02-04

# Switch to different model
gcloud run services update prediction-worker \
  --region=us-west2 \
  --update-env-vars="BREAKOUT_CLASSIFIER_MODEL_PATH=gs://nba-props-platform-models/breakout/v1/breakout_v1_20251102_20260205.cbm"
```

---

## Session Learnings

### Docker Image Model Pattern
- For models that change frequently, use GCS + env var (not baked into Docker)
- Allows model swaps without redeployment
- Pattern: `BREAKOUT_CLASSIFIER_MODEL_PATH=gs://bucket/path/model.cbm`

### Model Naming with Training Dates
- Include training start and end dates in model name
- Format: `{model_type}_v{version}_{start}_{end}.cbm`
- Makes it easy to identify what data the model was trained on

---

## Related Sessions

- **Session 128:** Developed breakout classifier (AUC 0.7302)
- **Session 130B:** Deployed classifier code (but forgot model file!)
- **Session 131:** Fixed model loading, added proper naming

---

*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
