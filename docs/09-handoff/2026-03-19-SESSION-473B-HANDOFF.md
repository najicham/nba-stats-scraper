# Session 473B Handoff — MLB Retrain Complete, NBA Fleet Restored

**Date:** 2026-03-19
**Previous:** Session 473A (NBA fleet restored, edge collapse root cause)

## TL;DR

Two major systems brought to ready state: (1) NBA pick drought resolved by re-enabling 4 Feb-trained models + fixing `retrain.sh` framework bug. (2) MLB 2026 season retrain complete — CatBoost V2 regressor deployed with 70% OVER HR, opening day March 27.

---

## What Was Done This Session

### NBA: Fleet Restored (Session 473A)

See `2026-03-19-SESSION-473-HANDOFF.md` for full details.

**Summary:**
- Root cause of 8-day pick drought: models trained through March TIGHT market (Vegas MAE 4.1-4.9) have edge collapse (avg_abs_diff ~1.1).
- Re-enabled 4 Feb-trained models (73%, 71%, 71%, 68% gov HR). Fleet now 6 models.
- Fixed `retrain.sh` to pass `--framework lightgbm/xgboost` from model_type field.
- March 19 is the first test — check if picks flow at 6 AM ET.

### MLB: 2026 Season Retrain + Deploy

**Training:**
```
Script:  scripts/mlb/training/train_regressor_v2.py
Model:   CatBoost V2 Regressor, 36 features
Window:  120 days (2025-05-31 to 2025-09-28)
Samples: 3,855 train / 559 validation
```

**Results (all gates passed):**
| Gate | Result | Threshold |
|------|--------|-----------|
| MAE | **1.76 K** | < 2.0 |
| OVER HR at edge ≥ 0.75 | **70.0%** (N=180) | ≥ 55% |
| N | 559 | ≥ 30 |
| OVER rate | 90.7% | 30-95% |

**Deployed:**
- GCS: `gs://nba-props-platform-ml-models/mlb/catboost_mlb_v2_regressor_40f_20250928.cbm`
- Env vars updated: `MLB_ACTIVE_SYSTEMS=catboost_v2_regressor`, `MLB_CATBOOST_V2_MODEL_PATH=...`
- BQ registry: `catboost_mlb_v2_regressor_36f_20250928` (enabled=TRUE, is_production=TRUE)
- Health check: PASSED

**Note on filename:** Model saved as `catboost_mlb_v2_regressor_40f_20250928.cbm` (legacy `40f` label hardcoded at line 542 of `train_regressor_v2.py`), but the model actually has 36 features. Not a functional issue — predictor reads feature count from metadata.

**Runbook fixed:** `07-LAUNCH-RUNBOOK.md` Step 1.1 updated — `--training-end 2026-03-20` was wrong (no 2026 data exists). Correct: `--training-end 2025-09-28 --window 120`.

---

## Current State

### MLB Worker
- **Active system:** `catboost_v2_regressor` (36 features)
- **Model:** `catboost_mlb_v2_regressor_40f_20250928.cbm` (trained May 31 - Sept 28 2025)
- **Status:** Deployed, health check passing
- **Edge floors:** 0.75K home, 1.25K away (defaults in code, no env override needed)
- **UNDER:** Disabled (MLB_UNDER_ENABLED=false by default)
- **Max picks/day:** 5

### NBA Fleet (6 models enabled)
| Model | Gov HR | Trained through |
|-------|--------|-----------------|
| `lgbm_v12_noveg_train0103_0227` | 73.1% | Feb 27 |
| `catboost_v12_noveg_train0108_0215` | 71.1% | Feb 15 |
| `catboost_v16_noveg_train1201_0215` | 70.8% | Feb 15 |
| `catboost_v12_noveg_train0104_0215` | 67.6% | Feb 15 |
| `catboost_v12_noveg_train0113_0310` | 66.7% | Mar 10 (edge collapse) |
| `lgbm_v12_noveg_vw015_train1215_0208` | 66.7% | Feb 8 (bridge) |

---

## Immediate Next Steps (Next Session)

### 1. Check NBA March 19 Picks (6 AM ET)
```sql
SELECT game_date, COUNT(*) as picks, system_id
FROM nba_predictions.signal_best_bets_picks
WHERE game_date = '2026-03-19'
GROUP BY 1, 2
```
Expected: 2-5 picks. If 0, check filter audit for candidate counts.

### 2. Resume MLB Schedulers (March 24)
```bash
./bin/mlb-season-resume.sh --dry-run   # Verify first
./bin/mlb-season-resume.sh             # Then execute
```
24 Cloud Scheduler jobs currently PAUSED. Must resume before Opening Day (March 27).

### 3. Verify MLB Opening Day (March 27)
```sql
SELECT game_date, COUNT(*) as n_predictions,
  AVG(edge) as avg_edge
FROM mlb_predictions.pitcher_strikeouts
WHERE game_date = '2026-03-27' AND system_id = 'catboost_v2_regressor'
GROUP BY 1
```
Expected: ~15-20 predictions, avg edge 0.5-1.0 K.

### 4. NBA Weekly Retrain (Monday March 23)
First run with fixed CF eval window. **CRITICAL:** New models trained with train_end=March 22 will likely have edge collapse (still in TIGHT market). Watch Slack `#deployment-alerts`. If new models show avg_abs_diff < 2.0, disable them immediately and keep the Feb-trained fleet.

Quick check after CF runs:
```sql
SELECT system_id, ROUND(AVG(ABS(predicted_points - current_points_line)),2) as avg_abs_diff,
  COUNT(*) as n
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND is_active = TRUE AND current_points_line IS NOT NULL
GROUP BY 1 ORDER BY 2 DESC
```

---

## P1 Items (Lower Priority)

### NBA: OVER Signal Deadlock (Ongoing)
Even with 6 models, OVER picks at edge_5+ still need real_sc ≥ 1 from non-shadow signals (`line_rising_over`, `book_disagreement`, `q4_scorer_over`, etc.). The HOT OVER signals (`projection_consensus_over` 80%, `usage_surge_over` 83%) are in SHADOW_SIGNALS.

Watch `usage_surge_over` for graduation (N=6 → needs N=30 at BB level with HR ≥ 60%).

### MLB: Register V3 (40f) as Shadow
The old production model (`catboost_mlb_v1_40f_train20250517_20250914`) is still enabled in the registry. Should be disabled since V2 is now production:
```sql
UPDATE mlb_predictions.model_registry
SET enabled = FALSE, is_production = FALSE
WHERE model_id = 'catboost_mlb_v1_40f_train20250517_20250914'
```

### NBA: Season-End Tanking Filter
Season ends ~April 13. Consider `tanking_risk` filter by April 1 for teams tanking (stars get big minutes in comfortable wins → UNDER picks on opponents' stars fail).

---

## Key Files Changed

| File | Change |
|------|--------|
| `bin/retrain.sh` | Added `--framework` flag from model_type in registry |
| `docs/08-projects/current/mlb-2026-season-strategy/07-LAUNCH-RUNBOOK.md` | Fixed Step 1.1 training-end date |
| BQ `nba_predictions.model_registry` | Re-enabled 4 Feb-trained models |
| BQ `mlb_predictions.model_registry` | Added `catboost_mlb_v2_regressor_36f_20250928` |
| GCS | Uploaded `catboost_mlb_v2_regressor_40f_20250928.cbm` |
| Cloud Run `mlb-prediction-worker` | Updated env vars to activate v2 regressor |

---

## Quick Start for Next Session

```bash
# 1. Check NBA March 19 picks
/todays-predictions

# 2. Check MLB worker health
curl -s https://mlb-prediction-worker-756957797294.us-west2.run.app/health

# 3. Check NBA filter audit
bq query --use_legacy_sql=false --project_id=nba-props-platform "
SELECT game_date, total_candidates, passed_filters
FROM nba_predictions.best_bets_filter_audit
WHERE game_date >= '2026-03-19'
ORDER BY 1 DESC"

# 4. If March 23 CF retrain fires, immediately check edge distribution of new models
# If avg_abs_diff < 2.0 → disable new models, keep Feb fleet
```
