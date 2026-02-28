# Session 361 Handoff — Shadow Fleet Review + Model Loading Diagnosis

**Date:** 2026-02-27
**Previous:** Session 360 — V17 experiment results (dead end)

## What Session 361 Did

### 1. Daily Steering Report

Ran full daily steering. Key findings:

- **ALL models BLOCKED** — every model in the fleet is below breakeven (52.4%)
- Best performing: `v9_low_vegas_train0106_0205` at 50-51.9% HR 7d
- **Best bets still profitable**: 70% last 7d, 62.5% last 14d, 61.7% last 30d — multi-model filtering is saving the system
- Market regime GREEN — edges are wide (compression 1.236), problem is model quality not market
- Signal health: model-dependent signals (`high_edge`, `edge_spread_optimal`) degraded; behavioral signals (`book_disagreement` 60-62%) holding up

### 2. Pipeline Validation

Ran validate-daily checks. All critical checks passed except:

- **Cross-model parity FAIL**: 7 newly registered models not generating predictions (see below)
- **Deployment drift WARN**: 8 services stale from V17 commit `a559702f` (non-breaking, additive code)

### 3. Diagnosed Why New Models Aren't Predicting

**Root cause: Two issues found.**

#### Issue A: LightGBM Loading Bug (Fixed, Untested)

LightGBM models were downloaded from GCS but loaded with CatBoost's native loader instead of LightGBM's booster. Error: `Incorrect model file descriptor`.

The fix (commit `7ee998bd`, "defensive LightGBM detection in worker model loader") was deployed at 22:02 UTC on Feb 27 via Cloud Build. It adds fallback detection from `model_id` prefix (`lgbm*`) and GCS path extension (`.txt`). The failing logs were from 18:03 UTC (before deployment).

**This fix has NOT been tested in production yet** — no worker runs since deployment (no games Feb 27).

#### Issue B: CatBoost Models — Timing Gap (Not a Bug)

Five new CatBoost models (V16, V12 vegas=0.25, q55, q5) were registered AFTER the last worker run (18:03 UTC). They'll be picked up automatically on the next run.

| Model | Registered | Purpose |
|-------|-----------|---------|
| `catboost_v12_train1201_0215` | Feb 28 00:20 UTC | V12 vegas=0.25 weight — **75% backtest HR** |
| `catboost_v16_noveg_rec14_train1201_0215` | Feb 28 00:21 UTC | V16 noveg + 14-day recency — **69% backtest, best UNDER** |
| `catboost_v16_noveg_train1201_0215` | Feb 27 21:29 UTC | V16 noveg baseline |
| `catboost_v12_noveg_q55_train0115_0222` | Feb 27 19:33 UTC | Q55 fresh training window |
| `catboost_v12_noveg_q5_train0115_0222` | Feb 27 20:07 UTC | Q5 experiment |

---

## What Changed

No code changes this session. Diagnosis only.

---

## Action Items for Next Session

### 1. CRITICAL: Verify Feb 28 Model Loading (Do This First)

After Feb 28 predictions run, check worker logs:

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="prediction-worker" AND textPayload=~"Loaded.*monthly model"' \
  --project=nba-props-platform --limit=5 --freshness=12h \
  --format=json | python3 -c "import sys,json; [print(e.get('textPayload','')) for e in json.load(sys.stdin)]"
```

**Expected:** "Loaded 15 monthly model(s) (15 from registry, 0 from dict)" with all models listed.

**Check LightGBM specifically:**

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="prediction-worker" AND textPayload=~"lgbm|lightgbm|LightGBM"' \
  --project=nba-props-platform --limit=10 --freshness=12h \
  --format="table(timestamp,textPayload)"
```

**Expected:** "Loading LightGBM monthly model from: gs://..." (NOT "Loading CatBoost").

**If LightGBM still fails:** The diagnostic logging (`model_type=..., is_lightgbm=...`) in the new code will show why. Check if `model_type` is NULL or unexpected value.

### 2. Shadow Fleet Live Data Check

After 3-5 days of Feb 28+ data, evaluate the Session 359 models:

```sql
SELECT system_id,
       COUNT(*) as total_picks,
       COUNTIF(ABS(predicted_points - line_value) >= 3) as edge3_n,
       COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct) as edge3_w,
       ROUND(100.0 * COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct)
         / NULLIF(COUNTIF(ABS(predicted_points - line_value) >= 3), 0), 1) as edge3_hr
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= '2026-02-28'
  AND system_id IN ('catboost_v12_train1201_0215', 'catboost_v16_noveg_rec14_train1201_0215',
                    'catboost_v16_noveg_train1201_0215', 'lgbm_v12_noveg_train1102_0209',
                    'lgbm_v12_noveg_train1201_0209')
GROUP BY system_id ORDER BY edge3_hr DESC;
```

**Key model:** `catboost_v12_train1201_0215` (V12 vegas=0.25) had **75% backtest HR edge 3+**. If it sustains 60%+ live, it's the promotion candidate.

### 3. Deployment Drift Cleanup

8 services stale from V17 commit. Push to main to auto-deploy, or manually deploy critical services:

```bash
# These are from the V17 feature infrastructure code (additive, non-breaking)
# but should be resolved to keep deployment clean
git push origin main  # Auto-deploys changed services
```

### 4. Next Experiment (After Fleet Data)

Wait for 3-5 days of shadow fleet data before choosing:

- **If `v12_vegas=0.25` sustains 60%+ live HR**: Promote to production
- **If all new models fail live**: Try Option B from Session 360 — per-direction OVER/UNDER models (UNDER has been the persistent weakness)
- **If LightGBM loading is fixed and shows good HR**: Consider it for multi-model selection

### 5. Front-Load Detection Finding

`catboost_v12_train1225_0205` showed clear front-loading pattern:
- 7d HR consistently 6-8pp below 14d HR
- Declined from 50% → 32% over one week

Session 360 suggested adding automated front-load detection to `decay-detection` CF: flag if `rolling_hr_7d < rolling_hr_14d - 5%` for 3+ consecutive days. This is still un-built.

---

## Current Fleet Status (as of Feb 27)

### Production
- `catboost_v12` (v12_50f_huber): BLOCKED, 44.7% HR 7d

### Shadow — Accumulating Data
- `v9_low_vegas_train0106_0205`: BLOCKED 50-51.9% (best current model)
- `v12_train1102_1225`: BLOCKED 46.2%
- `v12_noveg_train1102_0205`: BLOCKED 44.7%
- Session 343-344 models: BLOCKED 38-50%
- Session 348 `q55_tw_train0105_0215`: In fleet

### Shadow — Newly Registered (No Live Data Yet)
- `catboost_v12_train1201_0215`: V12 vegas=0.25 — **75% backtest**
- `catboost_v16_noveg_rec14_train1201_0215`: V16 noveg + recency — **69% backtest**
- `catboost_v16_noveg_train1201_0215`: V16 noveg — 70.8% backtest
- `lgbm_v12_noveg_train1102_0209`: LightGBM — 73.3% backtest (loading fix untested)
- `lgbm_v12_noveg_train1201_0209`: LightGBM — 67.7% backtest (loading fix untested)
- `catboost_v12_noveg_q55_train0115_0222`: Q55 fresh window
- `catboost_v12_noveg_q5_train0115_0222`: Q5 experiment

### Best Bets Performance
- 7d: 7-3 (70.0%)
- 14d: 10-6 (62.5%)
- 30d: 29-18 (61.7%)
- System is still profitable despite all individual models being BLOCKED

---

## Key File References

- Worker model loading: `predictions/worker/prediction_systems/catboost_monthly.py:271-340` (registry query), `:405-463` (model loading), `:740-791` (load all models)
- LightGBM fix: commit `7ee998bd` (deployed Feb 27 22:02 UTC)
- Model registry: `nba_predictions.model_registry` (BigQuery)
- Quick retrain registration: `ml/experiments/quick_retrain.py:2321-2406`

## What NOT to Do

- **Don't experiment yet** — wait for shadow fleet data (3-5 days)
- **Don't promote any model** — none have sufficient live data
- **Don't revert the LightGBM fix** — it hasn't been tested yet, wait for Feb 28 run
- **Don't manually trigger predictions** — let the pipeline run naturally for Feb 28 games to test the full flow
