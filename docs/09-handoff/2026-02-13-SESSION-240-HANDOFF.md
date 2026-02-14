# Session 240 Handoff — V12 NaN Defaults, All-Player Predictions, Pipeline Rethink

## What Was Done

### 1. V12 Feature Defaults Replaced with NaN
**Commits:** `28a1881b`, `3af668c2`, `384a9fb8`

V12 features 39-53 in the feature store processor now use `float('nan')` instead of hardcoded defaults (1.0, 80.0, 5.0, 112.0, etc.). CatBoost handles NaN natively via tree splits — it can now distinguish "real value of 1.0" from "missing data."

Changes:
- **ml_feature_store_processor.py**: All 15 V12 features use `float('nan')` + source `'missing'` instead of defaults
- **quality_scorer.py**: All V12 features (39-53) added to OPTIONAL_FEATURES; quality score excludes optional missing features from average
- **Individual columns**: Updated write rule to `source in ('default', 'missing', 'fallback')` → NULL
- **backfill-v12-predictions.py**: Reads individual columns (NULL-aware) instead of features array

### 2. V12 Predictions for ALL Players (Not Just Those with Lines)
The backfill script was updated to LEFT JOIN V9 lines instead of INNER JOIN. Players without prop lines get `recommendation='NO_LINE'` but still have `predicted_points` for MAE evaluation.

**Backfill run:** 1,013 NO_LINE predictions written for Feb 1-12 (all quality-ready players who previously had no V12 prediction because they lacked lines).

### 3. Full-Population MAE in Model Experiment Skill
`quick_retrain.py` now reports two MAE metrics:
- **MAE (w/lines)**: existing, only players with prop lines (~40-50% of players)
- **MAE (all players)**: NEW, all quality-ready players regardless of lines

Hit rate metrics remain line-only (need a line to bet on). Full-pop MAE stored in `ml_experiments.results_json` as `mae_all_players`.

### 4. Feature Store Backfill NOT Needed
Analysis showed zero players would be newly unblocked by making V12 features optional — every V12-blocked player also has V9 required defaults. The NaN change helps future data quality and model accuracy, not immediate coverage.

---

## Key Discovery: Prediction Pipeline Needs Rethinking

### Current State (Broken)

The prediction pipeline has evolved into a fragmented mess of run modes:

| Mode | When | What It Does | NO_PROP_LINE? |
|------|------|-------------|---------------|
| OVERNIGHT | Old pattern (pre-Feb 8) | Predicts ALL players | Yes (12-23 per day) |
| FIRST | ~morning | Early predictions, lines only | No |
| LAST_CALL | ~afternoon | Later run | No (despite name) |
| RETRY | Various | Retries failed | Sometimes |
| BACKFILL | Manual | Fill gaps | Sometimes |

**Problem:** Since ~Feb 8, the system switched from OVERNIGHT (includes all players) to FIRST+LAST_CALL+RETRY (lines only). NO_PROP_LINE predictions dropped to zero. Feb 12 didn't even get a LAST_CALL run.

### Desired State (Proposed)

The model predicts POINTS — it doesn't need a prop line to make a prediction. The prop line is only needed for the over/under recommendation and edge calculation. The system should:

1. **Predict ALL players early** — generate `predicted_points` for every quality-ready player regardless of prop line availability. Set `recommendation='NO_LINE'` and `has_prop_line=False`.

2. **Enrich with lines when they arrive** — the enrichment trigger (18:40 UTC) already does this. When a line appears, update `current_points_line`, recalculate `recommendation` (OVER/UNDER), and set `has_prop_line=True`.

3. **Re-predict when lines arrive** (optional but ideal) — once we have the line, we could re-run the prediction with the line as a feature (for V9 which uses vegas features). V12 doesn't need this since it's vegas-free. For V9, the line improves prediction quality.

4. **Measure MAE on ALL players** — not just those with lines. This gives us the full picture of model accuracy.

### Why This Matters

- **Coverage**: Currently ~30-40% of quality-ready players get predictions. Should be 100%.
- **MAE accuracy**: We're measuring MAE on a biased sample (players with lines tend to be starters/stars with more predictable stats).
- **Model development**: Training on all players but evaluating only on those with lines means we can't see how the model performs on bench players.
- **Grading**: NO_PROP_LINE predictions are excluded from grading — but they should still be graded for MAE (actual points vs predicted points). Hit rate grading still requires a line.

### Implementation Ideas for Next Session

1. **Quick fix**: Make the coordinator's FIRST/LAST_CALL runs include all players by default (set `require_real_lines=False`). The OVERNIGHT mode already did this.

2. **Better fix**: Separate the prediction pipeline into two phases:
   - **Phase A (early)**: Predict points for ALL players. No line required. Store as `prediction_run_mode='POINTS_ONLY'`.
   - **Phase B (enrichment)**: When lines arrive, update predictions with line, recommendation, edge. Mark as `prediction_run_mode='ENRICHED'`.
   - **Phase C (re-predict, optional)**: For V9, re-run with vegas features when line arrives. For V12, skip (vegas-free).

3. **Grading update**: Add MAE grading for all predictions (even NO_PROP_LINE). Keep hit-rate grading for line-only predictions.

### What to Investigate

- **Why did the mode change from OVERNIGHT to FIRST+LAST_CALL?** Check Cloud Scheduler job history and coordinator deploy history around Feb 7-8.
- **Does LAST_CALL use `require_real_lines=True`?** Check the scheduler payload sent to the coordinator.
- **Why did LAST_CALL not run on Feb 12?** Check scheduler logs.
- **Enrichment coverage**: How many NO_PROP_LINE predictions eventually get lines via enrichment? Is it 80%? 50%? This determines if the "predict early, enrich later" approach is viable.

---

## Files Changed

| File | Change |
|------|--------|
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | V12 features use NaN + 'missing' source; individual columns handle 'missing' |
| `data_processors/precompute/ml_feature_store/quality_scorer.py` | All V12 features optional; quality score skips optional missing |
| `bin/backfill-v12-predictions.py` | LEFT JOIN for all players; individual columns; NO_LINE handling |
| `ml/experiments/quick_retrain.py` | `load_eval_data_all_players()` + full-pop MAE in eval output |
| `.claude/skills/model-experiment/SKILL.md` | Updated output format showing both MAE metrics |

## Commits

```
384a9fb8 feat: Add full-population MAE to model experiment evaluation
3af668c2 feat: Backfill V12 predictions for ALL players, not just those with lines
28a1881b feat: Replace V12 feature defaults with NaN for proper CatBoost missing handling
```

## Quick Start for Next Session

```bash
# 1. Check deployment
./bin/check-deployment-drift.sh --verbose

# 2. Investigate scheduler configuration
gcloud scheduler jobs list --location=us-west2 --project=nba-props-platform | grep -i predict

# 3. Check enrichment coverage (how many NO_LINE get lines later?)
bq query --use_legacy_sql=false "
SELECT game_date,
  COUNTIF(line_source = 'NO_PROP_LINE') as still_no_line,
  COUNTIF(line_source != 'NO_PROP_LINE' AND prediction_run_mode = 'BACKFILL') as enriched
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v12' AND game_date >= '2026-02-01'
GROUP BY 1 ORDER BY 1"

# 4. Look at coordinator scheduler payloads
gcloud scheduler jobs describe <job-name> --location=us-west2 --project=nba-props-platform

# 5. Fix: make all prediction runs include all players
# In coordinator.py, change default require_real_lines or update scheduler payload
```

## Features Array Column (Future Work)

The `features` REPEATED FLOAT64 array in `ml_feature_store_v2` is legacy — individual columns (`feature_N_value`) are now the primary read path. The array can't store NULL/NaN (converts to 0.0). 65+ files still read from it. Removing it is a separate migration project. See Session 240 conversation for the full audit.
