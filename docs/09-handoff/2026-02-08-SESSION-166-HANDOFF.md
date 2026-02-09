# Session 166 Handoff: Model Eval Pipeline Fix + Retrain Experiments

**Date:** 2026-02-08
**Focus:** Fix model evaluation pipeline to match production, fix tier bias, run experiments, backfill Feb 2-7

## What Was Done

### 1. Fixed Model Evaluation Pipeline (`ml/experiments/quick_retrain.py`)

**Problem:** The experiment pipeline used DraftKings-only lines from `odds_api_player_points_props`, but production uses a multi-source cascade (DK -> FD -> BetMGM with OddsAPI -> BettingPros fallback). This caused experiment hit rates to be artificially lower than production.

**Fix:** Added `load_eval_data_from_production()` that queries `prediction_accuracy` for the EXACT lines production used at prediction time. This is now the default (`--use-production-lines`). The old DraftKings-only path remains as `--no-production-lines` fallback for eval periods without production predictions.

**Impact:** Jan 9-15 eval hit rate went from ~63% (old DK-only) to 83.16% (production lines) — matching what we actually see in production.

### 2. Fixed Tier Bias Hindsight Issue

**Problem:** `compute_tier_bias()` classified players into tiers (Stars 25+, Starters 15-24, etc.) using `actual_points` — which is hindsight bias. Session 124 proved it should use `points_avg_season` (what the model knows pre-game).

**Fix:** Added `season_avgs` parameter to `compute_tier_bias()`, extracted from feature index 2 (`points_avg_season`). Falls back to actuals for backward compatibility.

### 3. Model Experiments

| Experiment | Training | Eval | MAE | Edge 3+ HR | Vegas Bias | Gates |
|-----------|----------|------|-----|------------|------------|-------|
| V9_REPRODUCE_JAN8 | Nov 2 - Jan 8 | Jan 9-15 (prod lines) | 4.74 | 83.16% (n=95) | +1.42 | ALL PASS |
| V9_JAN31_EXTEND | Nov 2 - Jan 31 | Feb 1-7 (prod lines) | 5.23 | 63.64% (n=22) | -0.39 | 2 FAIL (MAE, sample) |
| V9_JAN8_EVAL_FEB | Nov 2 - Jan 8 | Feb 1-7 (prod lines) | 5.23 | 66.67% (n=33) | -0.63 | 2 FAIL (MAE, sample) |

**Key finding:** Feb 1-7 was a harder week for BOTH models (MAE 5.23 for both). The Jan 31 extended model didn't help or hurt — sample size too low to tell (n=22 vs n=33).

### 4. Models Uploaded to GCS (Shadow Mode)

Both uploaded with new naming convention and registered:

```
gs://nba-props-platform-models/catboost/v9/
├── catboost_v9_33f_train20251102-20260108_20260208_170526.cbm  # Shadow (SHA: 5a4470b9)
├── catboost_v9_33f_train20251102-20260131_20260208_170613.cbm  # Shadow (SHA: 7908ff07)
```

Registry synced via `./bin/model-registry.sh sync` — 5 models total in registry.

### 5. Critical Discovery: Feb 2-7 Used Wrong Model

**Production data analysis revealed:**

| Date | Model File | avg_pred_vs_line | Status |
|------|-----------|------------------|--------|
| Feb 1 | `catboost_v9_33features_20260201_011018.cbm` | -0.13 | Correct |
| Feb 2 | Same (correct) | -1.03 | Correct model, original run |
| Feb 3 | Mixed (correct + 36features) | -0.47 | Partially backfilled |
| Feb 4 | Mixed (correct + 36features) | -2.92 | Partially backfilled |
| **Feb 5** | **`catboost_v9_feb_02_retrain.cbm`** | **+0.04** | **WRONG MODEL** |
| **Feb 6** | **`catboost_v9_feb_02_retrain.cbm`** | **-5.91** | **WRONG MODEL** |
| **Feb 7** | **`catboost_v9_feb_02_retrain.cbm`** | **-3.75** | **WRONG MODEL** |

The Feb 2 retrain (deprecated for UNDER bias -2.26) was still generating active predictions for Feb 5-7.

### 6. Critical Bug: Cloud Build Downloads Wrong Model (`cloudbuild.yaml`)

**Root Cause Found:** The worker's `_load_model_from_default_location()` loads local model files BEFORE checking the `CATBOOST_V9_MODEL_PATH` env var. Cloud Build Step 0 was downloading `monthly/*.cbm` (untested `catboost_v9_2026_02.cbm` with 36 features) and baking it into the Docker image. The env var was silently ignored.

**Fix:** Changed `cloudbuild.yaml` to download the specific production model (`catboost_v9_33features_20260201_011018.cbm`) instead of `monthly/*.cbm`.

**Pushed to main** — auto-deploy will rebuild the worker with the correct model.

### 7. Backfill Status (In Progress)

- **Feb 2-3:** Backfill completed via coordinator HTTP API (correct model: `33features`)
- **Feb 5-7:** Backfill triggered via Pub/Sub (`nba-prediction-trigger`) but used wrong baked-in model (`36features`)
- **Feb 2-7:** Grading triggered via Pub/Sub (`nba-grading-trigger`)

**IMPORTANT:** Feb 5-7 backfills need to be RE-RUN after the Cloud Build deploys the fixed worker image. The current backfill used the wrong Docker-baked model.

## Subset Analysis

**Key findings from deep dive:**
- Subsets are **hardcoded** to `system_id = 'catboost_v9'` in `subset_materializer.py` and `all_subsets_picks_exporter.py`
- Subsets don't auto-regenerate after prediction backfill — need explicit `daily_export.py --only subset-picks`
- Overall subset performance (Jan 9+): Top 3 at 88.5%, High Edge OVER at 82.8%
- Feb 2-7 subset performance was degraded by wrong model predictions

**After backfill completes, run:**
```bash
python backfill_jobs/publishing/daily_export.py \
  --start-date 2026-02-02 --end-date 2026-02-07 \
  --only subset-picks
```

## What Needs To Be Done (Next Session)

### Step 1: Verify New Worker is Deployed with Correct Model
```bash
# Check the deployed commit matches our fix
gcloud run services describe prediction-worker --region=us-west2 \
  --format="value(metadata.labels.commit-sha)"
# Should match: 87f0750d or later (the cloudbuild.yaml fix commit)
```

### Step 2: Re-trigger Backfill for Feb 3-7
Previous backfills used old worker with wrong Docker-baked model. Now that the worker has the correct model:
```bash
# Use coordinator /start endpoint (more reliable than Pub/Sub for backfill)
TOKEN=$(gcloud auth print-identity-token)
for DATE in 2026-02-03 2026-02-04 2026-02-05 2026-02-06 2026-02-07; do
  curl -X POST "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"game_date\": \"$DATE\", \"prediction_run_mode\": \"BACKFILL\"}"
  sleep 120  # Wait 2 min between batches
done
```

### Step 3: Verify Correct Model Used
```sql
-- ALL dates should show ONLY catboost_v9_33features_20260201_011018.cbm
SELECT game_date,
  ARRAY_AGG(DISTINCT model_file_name IGNORE NULLS) as models,
  ROUND(AVG(predicted_points - current_points_line), 2) as avg_pvl
FROM nba_predictions.player_prop_predictions
WHERE game_date BETWEEN '2026-02-02' AND '2026-02-07'
  AND system_id = 'catboost_v9' AND is_active = TRUE
  AND current_points_line IS NOT NULL
GROUP BY 1 ORDER BY 1;
```

### Step 4: Trigger Re-grading
```bash
for DATE in 2026-02-02 2026-02-03 2026-02-04 2026-02-05 2026-02-06 2026-02-07; do
  gcloud pubsub topics publish nba-grading-trigger \
    --project=nba-props-platform \
    --message="{\"target_date\":\"$DATE\",\"trigger_source\":\"backfill\"}"
  sleep 2
done
```

### Step 5: Re-materialize Subsets
After predictions and grading are confirmed:
```bash
python backfill_jobs/publishing/daily_export.py \
  --start-date 2026-02-02 --end-date 2026-02-07 \
  --only subset-picks
```

### Step 6: Verify Corrected Performance
```sql
-- Edge 3+ hit rate should improve significantly for Feb 2-7
SELECT game_date,
  ROUND(AVG(predicted_margin), 2) as avg_margin,
  COUNTIF(ABS(predicted_margin) >= 3 AND prediction_correct IS NOT NULL) as edge3_n,
  ROUND(100.0 * COUNTIF(ABS(predicted_margin) >= 3 AND prediction_correct = TRUE) /
    NULLIF(COUNTIF(ABS(predicted_margin) >= 3 AND prediction_correct IS NOT NULL), 0), 1) as edge3_hr
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date BETWEEN '2026-02-02' AND '2026-02-07'
  AND prediction_correct IS NOT NULL
GROUP BY 1 ORDER BY 1;
```

### Step 7: Monitor Shadow Models
Both shadow models are registered and uploaded. Monitor them against production for 1-2 weeks before making promotion decisions.

## Files Modified

| File | Change |
|------|--------|
| `ml/experiments/quick_retrain.py` | Production-line eval, tier bias fix, CLI flags |
| `cloudbuild.yaml` | Download production model instead of monthly/*.cbm |

## Commits

```
a6796867 fix: Align model eval with production lines and fix tier bias hindsight
b437d6b2 docs: Session 166 handoff — eval pipeline fix, experiments, Feb 2-7 backfill
87f0750d fix: Cloud Build downloads production model instead of untested monthly
```

## Architectural Lessons

1. **Local-first model loading is dangerous** — The worker's `_load_model_from_default_location()` checks local files before the GCS env var. Any model baked into the Docker image overrides the env var, making `CATBOOST_V9_MODEL_PATH` a no-op. This is the root cause of the Feb 5-7 wrong-model issue.

2. **Model naming matters for sorting** — `sorted(model_files)[-1]` picks alphabetically last. `36features` > `33features`, so the wrong model was selected even when both existed locally.

3. **Eval pipeline must match production** — DraftKings-only eval lines gave ~63% hit rates while production showed ~71%+. The multi-source line cascade produces different (often better) lines.

4. **Tier bias using actuals is hindsight** — Classifying players by what they scored (actuals) rather than what they're expected to score (season avg) distorts tier analysis.

## Recommendations

### Immediate Priority: Complete Feb 2-7 Backfill (Steps 1-6 above)
The corrected worker (commit `87f0750d`) has been deployed via Cloud Build. Follow Steps 1-6 sequentially — verify deployment, re-trigger backfill, re-grade, re-materialize subsets, verify performance. Feb 2 is already correct; Feb 3-7 need re-running.

### Model Decisions
- **Keep current production model** (`catboost_v9_33features_20260201_011018.cbm`, trained Nov 2 - Jan 8). It remains the best validated model.
- **Both shadow models are registered in GCS and BQ** — monitor them over the next 1-2 weeks. The Jan 31 extended model needs more eval data (only n=22 at edge 3+) before any promotion decision.
- **Don't promote either shadow model yet** — neither passed governance gates on Feb 1-7 eval, though this was partly a tough week and partly low sample size.

### Prevent Model Loading Bug Recurrence
The root cause (`_load_model_from_default_location()` prioritizing local files over GCS env var) should be addressed more durably. Two options:
1. **Quick fix (done):** Cloud Build only downloads the production model — but this is fragile since the model filename is hardcoded in `cloudbuild.yaml` and must be updated on every model promotion.
2. **Better fix (recommended for next session):** Change `catboost_v9.py` to check `CATBOOST_V9_MODEL_PATH` env var FIRST, only falling back to local files if env var is unset. This makes the env var authoritative and eliminates the Docker-baked model override problem.

### Subset Backfill After Predictions
Subsets are hardcoded to `system_id = 'catboost_v9'` and do NOT auto-regenerate after prediction backfill. After Step 3 confirms correct models, you MUST run Step 5 (`daily_export.py --only subset-picks`) or the subset picks will still reflect the old bad predictions.

### Re-run Experiments After Backfill
Once Feb 2-7 predictions are corrected and re-graded, re-run the Jan 31 extended model experiment to get accurate hit rates:
```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_JAN31_REEVAL" \
    --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-07 --force
```
With corrected production lines in `prediction_accuracy`, the n at edge 3+ should increase and give more reliable hit rate comparisons.

### Cloud Build Hardcoded Model Path
`cloudbuild.yaml` now has the production model filename hardcoded. When the production model is eventually promoted/changed, remember to update this line:
```yaml
gsutil cp "gs://nba-props-platform-models/catboost/v9/catboost_v9_33features_20260201_011018.cbm" models/
```
Consider reading the production model path from `manifest.json` dynamically in a future session.
