# Session 358 Handoff — LightGBM Fix, V16/Q5/LightGBM Awaiting First Batch

**Date:** 2026-02-27
**Previous:** Session 357 — V16 model trained and enabled in shadow

## What Session 358 Did

### 1. Fixed LightGBM Model Loading Bug (Critical)

**Problem:** Both LightGBM models (`lgbm_v12_noveg_train1102_0209`, `lgbm_v12_noveg_train1201_0209`) were registered with `model_type='lightgbm'` in BQ but the worker was treating them as CatBoost models, causing "Incorrect model file descriptor" errors on every batch since their registration.

**Root cause:** The `model_type` field from BigQuery was not propagating correctly through `get_enabled_models_from_registry()`. Despite the code looking correct, the runtime was falling back to CatBoost for all models.

**Fix:** Added defensive multi-layer detection in `get_enabled_models_from_registry()`:
1. Primary: Registry `model_type` field (check for `'lightgbm'`)
2. Fallback: Model ID prefix (`lgbm`)
3. Fallback: GCS path extension (`.txt` = LightGBM, `.cbm` = CatBoost)
4. Added diagnostic logging showing `model_type` and `is_lightgbm` at load time

**File:** `predictions/worker/prediction_systems/catboost_monthly.py` (lines 301-330, 409-417)
**Commit:** `7ee998bd` — deployed via auto-deploy, build SUCCESS, revision `prediction-worker-00294-ds7`

### 2. Daily Steering Report

| Metric | Value | Status |
|--------|-------|--------|
| Best bets 7d | 8W-4L (66.7%) | PROFITABLE |
| Best bets 14d | 10W-6L (62.5%) | PROFITABLE |
| Best model edge 3+ 7d | v9_low_vegas 50.0% (N=54) | AT BREAKEVEN |
| Production v12 edge 3+ 7d | 44.7% (N=85) | BELOW BREAKEVEN |
| Market compression | 1.173 | GREEN (edges expanding) |
| Grading coverage | 100% (Feb 24-26) | HEALTHY |
| Deployment drift | Zero | HEALTHY |

### 3. Validated Pipeline Health

- **Grading:** 100% complete for all recent dates (Feb 24-26: 726-3129 predictions each)
- **Phase 3 analytics:** Feb 26 data present (369 records, 10 games). Earlier validation query had a false alarm from game_id format mismatch (schedule uses numeric `0022500849`, player_game_summary uses `20260226_NOP_UTA` — this is normal).
- **Feature store:** Operating normally
- **Deployment:** All 16 services up to date, zero drift

---

## V16 / Q5 / LightGBM — Awaiting Feb 28 Batch

All three model groups are registered, enabled, and have files in GCS — but **none have generated predictions yet**. The Feb 27 batch ran at 18:03 UTC, before all three were ready:

| Model | Registered | Issue | Fix Time |
|-------|-----------|-------|----------|
| `catboost_v16_noveg_train1201_0215` | 21:29 UTC Feb 27 | After batch | N/A (timing) |
| `catboost_v12_noveg_q5_train0115_0222` | 20:07 UTC Feb 27 | After batch | N/A (timing) |
| `lgbm_v12_noveg_train1102_0209` | Pre-existing | Worker treated as CatBoost | Fixed 22:09 UTC |
| `lgbm_v12_noveg_train1201_0209` | Pre-existing | Worker treated as CatBoost | Fixed 22:09 UTC |

**First predictions from all 4 models expected: Feb 28 morning batch (~6 AM ET / 11:00 UTC)**

### GCS Verification (all files confirmed present)

```
gs://nba-props-platform-models/catboost/v16/monthly/catboost_v16_52f_noveg_v16_train20251201-20260215_20260227_132512.cbm
gs://nba-props-platform-models/catboost/v12/monthly/lgbm_v12_50f_noveg_train20251201-20260209_20260226_231504.txt
gs://nba-props-platform-models/catboost/v12/monthly/lgbm_v12_50f_noveg_train20251102-20260209_20260226_221032.txt
```

---

## Full Registry: 13 Enabled Models

| Model ID | Type | Feature Set | Train Window | Status |
|----------|------|-------------|-------------|--------|
| `catboost_v9_33f_*` | catboost | v9 | Jan 6 - Feb 5 | **PRODUCTION** |
| `catboost_v16_noveg_train1201_0215` | catboost | v16_noveg | Dec 1 - Feb 15 | active (NEW) |
| `catboost_v12_noveg_q5_train0115_0222` | catboost | v12_noveg | Jan 15 - Feb 22 | active (NEW) |
| `catboost_v12_noveg_q55_train0115_0222` | catboost | v12_noveg | Jan 15 - Feb 22 | active |
| `catboost_v12_noveg_q55_tw_train0105_0215` | catboost | v12_noveg | Jan 5 - Feb 15 | shadow |
| `catboost_v12_noveg_q55_tw_train1225_0209` | catboost | v12_noveg | Dec 25 - Feb 9 | shadow |
| `catboost_v12_noveg_q57_train1225_0209` | catboost | v12_noveg | Dec 25 - Feb 9 | shadow |
| `catboost_v12_mae_train0104_0215` | catboost | v12 | Jan 4 - Feb 15 | active |
| `catboost_v12_noveg_mae_train0104_0215` | catboost | v12_noveg | Jan 4 - Feb 15 | active |
| `catboost_v9_low_vegas_train0106_0205` | catboost | v9 | Jan 6 - Feb 5 | active |
| `catboost_v9_low_vegas_train1225_0209` | catboost | v9 | Dec 25 - Feb 9 | shadow |
| `lgbm_v12_noveg_train1102_0209` | lightgbm | v12_noveg | Nov 2 - Feb 9 | active |
| `lgbm_v12_noveg_train1201_0209` | lightgbm | v12_noveg | Dec 1 - Feb 9 | active |

---

## What to Do Next (Priority Order)

### 1. CRITICAL: Verify Feb 28 Batch Produces All Models

Run this after 6 AM ET on Feb 28:

```sql
-- Should show 15 system_ids (13 shadow + 1 production + extras)
SELECT system_id, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-28'
GROUP BY system_id ORDER BY system_id;
```

**Must verify these 4 NEW models appear:**
```sql
SELECT system_id, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-28'
  AND system_id IN (
    'catboost_v16_noveg_train1201_0215',
    'catboost_v12_noveg_q5_train0115_0222',
    'lgbm_v12_noveg_train1102_0209',
    'lgbm_v12_noveg_train1201_0209'
  )
GROUP BY system_id;
```

**If LightGBM models still missing**, check worker logs for the fix:
```bash
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=prediction-worker AND (textPayload:lgbm OR textPayload:LightGBM OR textPayload:lightgbm)" --limit=30 --format="table(timestamp, textPayload)" --project=nba-props-platform
```

Look for: `Loading LightGBM monthly model from: ... (model_type='lightgbm', is_lightgbm=True)` — this confirms the fix is working.

### 2. Monitor V16 First Live Performance (After Feb 28 Grading)

```sql
SELECT system_id, game_date,
       COUNT(*) as picks,
       COUNTIF(prediction_correct) as wins,
       ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr,
       COUNTIF(ABS(predicted_points - line_value) >= 3) as edge3_n,
       COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct) as edge3_w,
       ROUND(100.0 * COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct)
         / NULLIF(COUNTIF(ABS(predicted_points - line_value) >= 3), 0), 1) as edge3_hr
FROM nba_predictions.prediction_accuracy
WHERE system_id IN ('catboost_v16_noveg_train1201_0215', 'catboost_v12_noveg_q5_train0115_0222',
                    'lgbm_v12_noveg_train1102_0209', 'lgbm_v12_noveg_train1201_0209')
  AND game_date >= '2026-02-28'
GROUP BY system_id, game_date ORDER BY system_id, game_date;
```

**V16 backtest reference:** 70.83% HR edge 3+ (OVER 88.9%, UNDER 60.0%)
**LightGBM backtest reference:** 67-73% HR edge 3+ (precision models, fewer picks)

### 3. Fleet-Wide Shadow Comparison (After 2+ Days of Data)

```sql
SELECT system_id,
       COUNT(*) as picks,
       COUNTIF(prediction_correct) as wins,
       ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr,
       COUNTIF(ABS(predicted_points - line_value) >= 3) as edge3_n,
       COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct) as edge3_w,
       ROUND(100.0 * COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct)
         / NULLIF(COUNTIF(ABS(predicted_points - line_value) >= 3), 0), 1) as edge3_hr
FROM nba_predictions.prediction_accuracy
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY system_id ORDER BY edge3_hr DESC;
```

### 4. Daily Operations

Run `/daily-steering` and `/validate-daily`.

---

## Fleet Health Context (as of Feb 27)

**Best bets are profitable** (62.5-66.7% HR) despite all models being BLOCKED at raw level. The multi-model edge selection + negative filters are working as intended.

**Edge 3+ leaders (7d):**
| Model | HR | N |
|-------|-----|---|
| v9_low_vegas_train0106_0205 | 50.0% | 54 |
| v9_q45_train1102_0125 | 50.0% | 30 |
| v12_q43_train1225_0205_feb22 | 50.0% | 20 |
| catboost_v12 (production) | 44.7% | 85 |

**Session 343-344 models** (q55, q57, q55_tw, v9_lv retrained): Still accumulating data — only 6 graded picks each, too early to evaluate.

**Upcoming schedule:** 5 games Feb 28, 11 games Mar 1 (large slate = more prediction volume).

---

## Key Files Changed

| File | Changes |
|------|---------|
| `predictions/worker/prediction_systems/catboost_monthly.py` | Defensive LightGBM detection + diagnostic logging |

## Schema Reference

- `prediction_accuracy` columns: `predicted_points`, `line_value`, `prediction_correct`, `graded_at` (NOT `predicted_value`, NOT `is_best_bet`)
- `signal_best_bets_picks`: Self-contained table with `prediction_correct` and `actual_points`
- `nba_reference.nba_schedule` game_ids are numeric (`0022500849`), `player_game_summary` uses date format (`20260226_NOP_UTA`)

## Dead Ends (Don't Revisit)

Same as Session 357, no new dead ends this session.
