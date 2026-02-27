# Session 351 Handoff — LightGBM Validation + Fleet Triage

**Date:** 2026-02-27
**Previous:** Session 350 — Model diversity experiments, LightGBM deploy, fleet audit
**Full Session 350 details:** `docs/09-handoff/2026-02-26-SESSION-350-HANDOFF.md`

## Current Situation

The production models are below breakeven. A fleet of 11 shadow models is rebuilding, but most are too new to evaluate. LightGBM (first alternative framework) was deployed and should produce its first predictions on Feb 28.

### Production (both below breakeven)
| Model | Feb HR (edge 3+) | N | Staleness |
|---|---|---|---|
| `catboost_v12` | **48.7%** | 152 | 27 days |
| `catboost_v9` | **37.4%** | 230 | Affinity-blocked from best bets |

### Shadow Fleet (11 enabled models)
| Model | Backtest HR | Live HR | Live N | Started | Notes |
|---|---|---|---|---|---|
| `v9_low_vegas_train0106_0205` | 56.3% | **52.5%** | 61 | Feb 19 | Only model above breakeven |
| `v12_noveg_mae_train0104_0215` | 61.5% | 35.3% | 17 | Feb 24 | Trending bad, 3 days |
| `v12_mae_train0104_0215` | 55.6% | 25.0% | 8 | Feb 24 | Trending bad, 3 days |
| `v12_noveg_q55_tw_train0105_0215` | **68.0%** | — | 0 | Feb 27 | Session 348 best retrain |
| `v12_noveg_q55_tw_train1225_0209` | 58.6% | — | 0 | Feb 26 | Session 343 best overall |
| `v12_noveg_q55_train1225_0209` | 60.0% | — | 0 | Feb 26 | Q55 baseline |
| `v12_noveg_q57_train1225_0209` | 53.8% | — | 1 | Feb 26 | UNDER specialist |
| `v9_low_vegas_train1225_0209` | 60.0% | — | 0 | Feb 26 | Fresh v9 low-vegas |
| **`lgbm_v12_noveg_train1102_0209`** | **73.3%** | — | 0 | **Feb 28** | LightGBM Nov, best backtest HR |
| **`lgbm_v12_noveg_train1201_0209`** | **67.7%** | — | 0 | **Feb 28** | LightGBM Dec, OVER 80% |
| ~~`v12_noveg_q43_train0104_0215`~~ | — | 14.8% | 54 | Feb 24 | **DISABLED** Session 350 |

## Priority 1: Verify LightGBM Producing Predictions

LightGBM support was deployed Feb 27 (worker revision 00284). Old instances failed with `Incorrect model file descriptor`. New code loads lazily — first predictions should appear on the Feb 28 morning prediction cycle.

```bash
# Check predictions appeared
bq query --use_legacy_sql=false "
SELECT system_id, game_date, COUNT(*) as predictions
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE system_id LIKE 'lgbm%'
GROUP BY 1, 2
ORDER BY 2 DESC
"

# Check worker logs for successful loading
gcloud run services logs read prediction-worker --region=us-west2 --limit=100 | grep -i "lightgbm\|lgbm"

# If NOT producing, check for errors
gcloud run services logs read prediction-worker --region=us-west2 --limit=200 | grep -i "error.*lgbm\|fail.*lgbm\|lgbm.*error"
```

**If LightGBM models aren't loading:** The issue is likely the model loading path. Check that `config['model_type']` is `'lightgbm'` — the registry query in `catboost_monthly.py:get_enabled_models_from_registry()` must include `model_type` in the SELECT. Code is at `predictions/worker/prediction_systems/catboost_monthly.py:374-431`.

## Priority 2: Evaluate Shadow Models (when N >= 20)

Most shadow models only have 0-3 days of data. Evaluation becomes meaningful at ~20 edge 3+ bets (typically 5-7 days).

```bash
# Run this daily to check accumulation
bq query --use_legacy_sql=false "
SELECT system_id,
  COUNTIF(ABS(predicted_margin) >= 3) as edge3,
  ROUND(SAFE_DIVIDE(COUNTIF(ABS(predicted_margin) >= 3 AND prediction_correct),
    COUNTIF(ABS(predicted_margin) >= 3)) * 100, 1) as hr_edge3,
  MIN(game_date) as first, MAX(game_date) as last
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
WHERE system_id IN (
  'catboost_v12_noveg_q55_tw_train0105_0215',
  'catboost_v12_noveg_q55_tw_train1225_0209',
  'catboost_v12_noveg_q55_train1225_0209',
  'catboost_v12_noveg_q57_train1225_0209',
  'catboost_v9_low_vegas_train1225_0209',
  'lgbm_v12_noveg_train1102_0209',
  'lgbm_v12_noveg_train1201_0209'
)
AND game_date >= '2026-02-26'
GROUP BY 1
ORDER BY hr_edge3 DESC
"
```

**Decision criteria:**
- HR >= 55% at N >= 20 → keep shadowing
- HR >= 60% at N >= 30 → candidate for promotion
- HR < 45% at N >= 20 → disable (like q43 was)

## Priority 3: Triage Underperforming Models

Two Session 348 retrains are trending badly:

| Model | Live HR | N | Action |
|---|---|---|---|
| `v12_noveg_mae_train0104_0215` | 35.3% | 17 | Disable if <40% at N>=30 |
| `v12_mae_train0104_0215` | 25.0% | 8 | Disable if <40% at N>=20 |

```bash
# Check if they've improved
bq query --use_legacy_sql=false "
SELECT system_id,
  COUNTIF(ABS(predicted_margin) >= 3) as edge3,
  ROUND(SAFE_DIVIDE(COUNTIF(ABS(predicted_margin) >= 3 AND prediction_correct),
    COUNTIF(ABS(predicted_margin) >= 3)) * 100, 1) as hr
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
WHERE system_id IN ('catboost_v12_noveg_mae_train0104_0215', 'catboost_v12_mae_train0104_0215')
  AND game_date >= '2026-02-24'
GROUP BY 1
"

# To disable:
# bq query --use_legacy_sql=false "UPDATE nba_predictions.model_registry SET enabled=FALSE, notes=CONCAT(notes, ' | DISABLED: X% HR live') WHERE model_id='MODEL_ID'"
```

## Priority 4: Fresh LightGBM Retrain (if live results validate)

If LightGBM shows >= 55% HR live after 3-5 days, retrain with fresher data:

```bash
# Retrain with data through Feb 20 (latest safe window)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "LGBM_V12_NOVEG_FRESH" --feature-set v12 --no-vegas --framework lightgbm \
    --train-start 2025-12-01 --train-end 2026-02-20 \
    --eval-start 2026-02-21 --eval-end 2026-02-27 \
    --force --force-register --enable
```

This would give a model only 7 days stale instead of 18.

## Key Architecture Notes

### LightGBM in the Worker
- `catboost_monthly.py` handles both frameworks via `config['model_type']`
- LightGBM loads with `lgb.Booster(model_file=path)`, predicts with `.predict(vector)[0]`
- Prediction output tagged `model_type='monthly_retrain_lgbm_v12'`
- Feature vector identical to CatBoost v12_noveg (50 features, name-based extraction)

### `--force-register` Flag
Added to `quick_retrain.py` to bypass governance gates when registering supplementary models (like LightGBM with N<50 sample size). Use only with explicit approval.

### LightGBM Non-Determinism
LightGBM MAE is stable across runs. LightGBM Q55 is NOT — swung 62%→52% between identical runs. Only register MAE variants without multi-run validation.

## Dead Ends Confirmed This Session
- No-vegas binary classifier (AUC 0.507 = random)
- Tier models on 42-day window (insufficient per-tier samples)
- Starter tier model on Dec 1 window (1/6 gates, can't predict outside tier)
- Noveg Q43 on fresh data (14.8% HR live, catastrophic UNDER compounding)
- LightGBM Q55 (non-deterministic, unreliable)

## Files Changed This Session
- `ml/experiments/quick_retrain.py` — `--force-register`, `--framework lightgbm`, `--player-tier`, `--classify`, PARSE_JSON fix
- `predictions/worker/requirements.txt` + `requirements-lock.txt` — `lightgbm==4.6.0`
- `predictions/worker/prediction_systems/catboost_monthly.py` — LightGBM framework support
- `shared/config/cross_model_subsets.py` — 5 new model families
- `CLAUDE.md` — Model section rewritten, dead ends updated
