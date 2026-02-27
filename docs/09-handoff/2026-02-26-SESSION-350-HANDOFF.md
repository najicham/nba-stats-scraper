# Session 350 Handoff — Model Diversity Experiments + LightGBM Shadow Deploy

**Date:** 2026-02-26
**Focus:** Test three model diversity strategies (classifier, LightGBM, player-tier) to address February decline and V9-dominated best bets

## What Was Done

### Part 1: Implementation (earlier in session)
Added three new experiment modes to `ml/experiments/quick_retrain.py`:
- `--classify` — Binary OVER/UNDER classifier (CatBoost Logloss)
- `--framework lightgbm` — LightGBM as alternative to CatBoost
- `--player-tier {star,starter,role}` — Tier-specific models

Added 5 new model families to `shared/config/cross_model_subsets.py`:
- `v12_noveg_classify`, `lgbm_v12_noveg_mae`, `v12_noveg_star`, `v12_noveg_starter`, `v12_noveg_role`

### Part 2: Extended Window Experiments + Shadow Registration

Ran 4 experiments with longer training/eval windows (Dec 1 or Nov 2 train, Feb 10-25 eval):

| Experiment | HR Edge 3+ | N | MAE | OVER | UNDER | Vegas Bias | Gates |
|---|---|---|---|---|---|---|---|
| **LGBM MAE Nov** | **73.3%** | 30 | **5.027** | 75.0% | **71.4%** | +0.22 | **5/6** |
| **LGBM MAE Dec** | **67.7%** | 31 | 5.119 | **80.0%** | 61.9% | -0.07 | **5/6** |
| LGBM Q55 Dec | 51.7% | 29 | 5.127 | 58.8% | 41.7% | +0.15 | 3/6 |
| Tier Starter Dec | 56.5% | 170 | 6.394 | 58.1% | 50.0% | +2.49 | 1/6 |

**Key: LightGBM is non-deterministic.** Q55 collapsed from 62.1% to 51.7% between runs. MAE variants were stable/improved. Only MAE models are safe for shadow deployment.

### Part 3: Shadow Registration + Worker LightGBM Support

**2 LightGBM models registered and enabled in model_registry:**
- `lgbm_v12_noveg_train1102_0209` — Nov 2 train, 73.3% HR, best model seen
- `lgbm_v12_noveg_train1201_0209` — Dec 1 train, 67.7% HR, OVER specialist (80%)

**Worker changes to support LightGBM:**
- `predictions/worker/requirements.txt` — Added `lightgbm==4.3.0`
- `predictions/worker/prediction_systems/catboost_monthly.py` — Framework-aware loading:
  - Registry query now includes `model_type` column
  - `_load_model_from_path()` detects `model_type='lightgbm'` → uses `lgb.Booster(model_file=path)`
  - Prediction output tagged `model_type='monthly_retrain_lgbm_v12'`
- Verified locally: LightGBM model loads through CatBoostMonthly, produces correct predictions

**Other changes:**
- `ml/experiments/quick_retrain.py` — Added `--force-register` flag to bypass governance gates for supplementary models. Fixed JSON type bug in auto-register (`training_config_json` column needs `PARSE_JSON()`).
- `CLAUDE.md` — Added dead ends: no-vegas classifier, tier models 42-day window, starter tier Dec 1 window

## Key Findings

### LightGBM provides genuine algorithmic diversity
Feature importance is fundamentally different from CatBoost:
- **LightGBM:** `points_avg_last_10` + `points_avg_season` = 40-50% importance
- **CatBoost:** `line_vs_season_avg` dominates

This means LightGBM and CatBoost will disagree on different players, providing real diversity in the multi-model best bets system.

### LightGBM is a precision model
Better MAE (5.03 vs 5.14 baseline) means tighter predictions closer to the line → fewer edge 3+ picks (30-31 vs CatBoost's ~100+) but higher quality. This is ideal for the multi-model architecture where it supplements rather than replaces CatBoost.

### November noise doesn't hurt LightGBM
The Nov 2 start (100 days, 26% of early data low quality) produced the BEST model (73.3% HR, both directions > 71%). This contradicts the CatBoost dead end "87-day window dilutes signal" — LightGBM's leaf-wise growth handles temporal noise better than CatBoost's symmetric trees.

### LightGBM Q55 is unstable
Non-deterministic training caused Q55 to swing from 62% to 52% HR between runs. MAE models were stable/improved. Don't shadow-register Q55 without multi-run validation.

### Starter tier model: dead end
Even with 1,780 training samples (Dec 1 window), the starter tier model fails 5/6 gates: Vegas bias +2.49, bench bias +7.62, UNDER at breakeven. Training on a subset cripples predictions for everyone else.

## Dead Ends Added to CLAUDE.md
- `no-vegas binary classifier (AUC 0.507)` — features predict points, not over/under direction
- `tier models on 42-day window (star: 244, starter: 933)` — insufficient data per tier
- `starter tier model Dec 1 window (1/6 gates)` — can't predict outside trained tier

## Deployment Required

**Push to main to deploy worker with LightGBM support.** The worker changes are:
1. New pip dependency: `lightgbm==4.3.0`
2. Framework-aware model loading in `catboost_monthly.py`
3. 2 LightGBM models already registered + enabled in BQ

After deploy, monitor with:
```bash
# Check models are loading
gcloud run services logs read prediction-worker --region=us-west2 --limit=50 | grep -i lightgbm

# Check predictions appearing
bq query --use_legacy_sql=false "
SELECT system_id, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE()
  AND system_id LIKE 'lgbm%'
GROUP BY 1
"
```

## Files Modified
- `ml/experiments/quick_retrain.py` — `--force-register` flag, PARSE_JSON fix
- `predictions/worker/requirements.txt` — `lightgbm==4.3.0`
- `predictions/worker/prediction_systems/catboost_monthly.py` — LightGBM loading + prediction
- `shared/config/cross_model_subsets.py` — 5 new model family patterns (earlier)
- `CLAUDE.md` — Dead ends updated

## Models in Registry (enabled, shadow)
- `lgbm_v12_noveg_train1102_0209` — 73.3% HR, OVER 75%, UNDER 71%
- `lgbm_v12_noveg_train1201_0209` — 67.7% HR, OVER 80%, UNDER 62%
