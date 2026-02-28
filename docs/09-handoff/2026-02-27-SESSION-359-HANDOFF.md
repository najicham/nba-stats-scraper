# Session 359 Handoff — Vegas Feature Experiment Matrix

**Date:** 2026-02-27
**Previous:** Session 358 — LightGBM fix, V16/Q5/LightGBM awaiting first batch

## What Session 359 Did

### 1. Vegas Feature Experiment Matrix (12 experiments)

Systematically tested how different vegas feature strategies affect directional accuracy, especially UNDER performance. All experiments used the same windows: train Dec 1 - Feb 15, eval Feb 16-27.

### 2. Code Change: Added v16/noveg feature set choices to quick_retrain.py

Added `v16`, `v12_noveg`, `v16_noveg` as valid `--feature-set` choices. Auto-handles `_noveg` suffix (sets `no_vegas=True`) and auto-enables `--v16-features` when `v16` is selected.

**File:** `ml/experiments/quick_retrain.py` (lines 202-205, 2412-2425)

### 3. Shadow Deployed 2 Models

| Model ID | Config | Edge 3+ HR | OVER | UNDER |
|----------|--------|-----------|------|-------|
| `catboost_v12_train1201_0215` | V12 vegas=0.25 weight | 75.0% (n=16) | 100% | 60.0% |
| `catboost_v16_noveg_rec14_train1201_0215` | V16 noveg + 14-day recency | 69.0% (n=29) | 81.8% | 61.1% |

---

## Full Experiment Results

| Exp | Config | Edge 3+ HR | N | OVER HR (n) | UNDER HR (n) | Vegas Bias | MAE | Top Feature |
|-----|--------|-----------|---|------------|-------------|------------|-----|-------------|
| **A1** | V12 vegas=1.0 | 71.4% | 14 | 87.5% (8) | 50.0% (6) | +0.13 | 5.18 | vegas_points_line (22.8%) |
| **A2** | V12 vegas=0.5 | **75.0%** | 16 | **100%** (7) | 55.6% (9) | -0.01 | 5.17 | points_avg_season (22.3%) |
| **A3** | V12 vegas=0.25 | **75.0%** | 16 | **100%** (6) | **60.0%** (10) | -0.05 | 5.15 | points_avg_season (28.1%) |
| **A4** | V12 vegas=0.1 | 70.6% | 17 | 100% (6) | 54.5% (11) | -0.10 | 5.20 | points_avg_season (25.8%) |
| **A5** | V12 noveg | 73.7% | 19 | 100% (9) | 50.0% (10) | +0.01 | 5.17 | points_avg_season (19.1%) |
| **B1** | V16 noveg | 61.5% | 26 | 76.9% (13) | 46.2% (13) | -0.02 | 5.27 | points_avg_season (28.7%) |
| **B2** | V16 vegas=0.25 | 60.9% | 23 | 80.0% (10) | 46.2% (13) | -0.18 | 5.26 | points_avg_season (29.5%) |
| **B3** | V16 vegas=0.1 | 52.4% | 21 | 72.7% (11) | 30.0% (10) | -0.12 | 5.25 | points_avg_season (26.7%) |
| **C1** | V12 noveg anchor | 66.7% | 9 | 83.3% (6) | 33.3% (3) | -0.27 | 5.08 | (collapsed) |
| **C2** | V16 noveg anchor | 66.7% | 9 | 83.3% (6) | 33.3% (3) | -0.27 | 5.07 | margin_vs_line (18.4%) |
| **D1** | V16 noveg + rec14 | 69.0% | 29 | 81.8% (11) | **61.1%** (18) | -0.02 | 5.39 | points_avg_season (22.8%) |
| **D2** | V12 v025 + rec14 | 59.3% | 27 | 80.0% (10) | 47.1% (17) | -0.06 | 5.26 | points_avg_season (18.5%) |

---

## Key Findings

### 1. Vegas Weight Sweet Spot: 0.25x

The optimal vegas influence is much lower than the default 1.0x:
- At 1.0x: `vegas_points_line` is #1 feature (22.8%), model anchors to line, UNDER 50%
- At 0.25x: `vegas_points_line` drops to #8 (2.7%), `points_avg_season` dominates (28.1%), UNDER 60%
- At 0.0x (noveg): Model is too independent, UNDER drops back to 50%

**Interpretation:** A small amount of vegas signal (0.25x) helps the model understand the baseline expectation without anchoring to it. The model learns "where the line is" as soft context, not as a prediction target.

### 2. V16 Deviation Features Hurt Quality

Every B experiment underperformed its A counterpart:
- B1 (V16 noveg) 61.5% vs A5 (V12 noveg) 73.7%
- B2 (V16 vegas=0.25) 60.9% vs A3 (V12 vegas=0.25) 75.0%

V16 features generate more edge 3+ picks (21-26 vs 14-19) but at lower quality. The rolling features add noise on this eval window. **Exception:** Combined with recency weighting (D1), V16 recovered to 69% with the best UNDER HR (61.1%).

### 3. Anchor-Line Training is a Dead End

Best MAE (5.07-5.08) but collapsed feature importance (all scoring features → 0%) and produced only 9 edge 3+ picks. The model learns a near-constant residual.

### 4. Recency is Situational

- Helped V16 (D1: 69% from B1's 62%) — V16's extra features benefit from recency context
- Hurt V12 vegas=0.25 (D2: 59% from A3's 75%) — A3 is already well-calibrated
- 14-day recency generates more picks but at lower per-pick quality when the base model is already good

### 5. Feature Importance Shift

| Vegas Weight | #1 Feature | % Importance | #2 Feature |
|-------------|-----------|-------------|-----------|
| 1.0 (A1) | vegas_points_line | 22.8% | points_avg_season (10.9%) |
| 0.5 (A2) | points_avg_season | 22.3% | points_avg_last_10 (11.0%) |
| 0.25 (A3) | points_avg_season | 28.1% | points_avg_last_10 (9.1%) |
| 0.0 (A5) | points_avg_season | 19.1% | points_avg_last_10 (16.8%) |

At 0.25x weight, the model concentrates on `points_avg_season` (28.1%) — more than at full vegas OR no vegas. This suggests the model is most confident in its player-scoring signal when vegas provides soft context but doesn't dominate.

---

## Shadow Fleet Status (as of Feb 27)

**15 enabled models now** (13 existing + 2 new from Session 359):

| Model ID | Type | Notes |
|----------|------|-------|
| `catboost_v12_train1201_0215` | NEW | V12 vegas=0.25, 75% HR edge 3+ |
| `catboost_v16_noveg_rec14_train1201_0215` | NEW | V16 noveg + 14d recency, 69% HR, best UNDER 61.1% |
| `catboost_v16_noveg_train1201_0215` | Session 357 | V16 noveg, 70.8% backtest |
| `lgbm_v12_noveg_train1102_0209` | Session 350 | LightGBM, awaiting first batch |
| `lgbm_v12_noveg_train1201_0209` | Session 350 | LightGBM, awaiting first batch |
| (10 more existing shadow models) | | |

**IMPORTANT:** The `catboost_v12_train1201_0215` model uses feature_set=v12 with ALL features (including vegas). The vegas=0.25 weight was applied during training only — at inference time, the worker feeds standard V12 features and the model internally uses what it learned. No special worker changes needed.

**CONCERN:** The D1 model (`catboost_v16_noveg_rec14_train1201_0215`) has a new model_family `v16_noveg_rec14_mae` — verify the worker discovers it correctly. Check Feb 28 batch predictions.

---

## What to Do Next

### 1. Verify Feb 28 Batch (after 6 AM ET)

```sql
-- Check both new Session 359 models appear
SELECT system_id, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-28'
  AND system_id IN ('catboost_v12_train1201_0215', 'catboost_v16_noveg_rec14_train1201_0215')
GROUP BY system_id;
```

### 2. Monitor Live Performance (after 2+ days)

```sql
SELECT system_id,
       COUNT(*) as picks,
       ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr,
       COUNTIF(ABS(predicted_points - line_value) >= 3) as edge3_n,
       ROUND(100.0 * COUNTIF(ABS(predicted_points - line_value) >= 3 AND prediction_correct)
         / NULLIF(COUNTIF(ABS(predicted_points - line_value) >= 3), 0), 1) as edge3_hr
FROM nba_predictions.prediction_accuracy
WHERE system_id IN ('catboost_v12_train1201_0215', 'catboost_v16_noveg_rec14_train1201_0215')
  AND game_date >= '2026-02-28'
GROUP BY system_id;
```

### 3. Consider Next Feature Experiments

The experiment matrix showed that **player performance features matter most**. `points_avg_season` at 28.1% importance in the best model suggests the model wants MORE player-specific signal. Brainstorm player-specific features that could improve directional accuracy, especially for UNDER predictions.

---

## Dead Ends (New from Session 359)

- **Anchor-line training** (predict actual - prop_line): Collapses feature importance, only 9 edge 3+ picks, UNDER 33.3%. Best MAE but useless for betting.
- **V16 deviation features alone**: Hurt quality vs V12 on Feb eval window (61.5% vs 73.7%). Only work when combined with recency weighting.
- **Recency on well-calibrated models**: Hurt V12 vegas=0.25 (75% → 59%). Don't add recency to models that are already performing well.
- **Vegas weight < 0.25**: Going below 0.25 (to 0.1) does not improve UNDER — it gets worse (54.5%). There IS signal in the vegas line; just need to dampen it heavily.

---

## Key Files Changed

| File | Changes |
|------|---------|
| `ml/experiments/quick_retrain.py` | Added v16, v12_noveg, v16_noveg to --feature-set choices; auto-handling of _noveg suffix |

## Schema Reference

- `prediction_accuracy` columns: `predicted_points`, `line_value`, `prediction_correct`
- `model_registry`: `model_id`, `enabled`, `model_family`, `feature_set`, `gcs_path`
- Category weight feature: `--category-weight "vegas=0.25"` reduces CatBoost feature weight for vegas features during training only
