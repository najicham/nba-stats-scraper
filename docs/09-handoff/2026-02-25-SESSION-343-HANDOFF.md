# Session 343 Handoff — Model Evaluation Plan, Q55 Discovery, Shadow Deploys

**Date:** 2026-02-25
**Focus:** Comprehensive model system evaluation, v9_low_vegas retrain experiments, v12_noveg Q55 discovery, shadow model registration.

---

## What Was Done

### 1. Comprehensive Model System Evaluation Plan

**Doc:** `docs/08-projects/current/model-system-evaluation-session-343/00-EVALUATION-PLAN.md`

Wrote a 7-part evaluation plan covering:
- Current state assessment (all models BLOCKED/DEGRADING)
- Root cause diagnosis (staleness + UNDER bias + Vegas anchoring)
- 8 structured investigations with SQL queries and methods
- Retrain strategy with Phase A/B/C priorities
- 4 architecture decisions (default architecture, quantile strategy, retrain cadence, best bets volume)
- 4-week execution timeline
- Success metrics

### 2. v9_low_vegas Retrain — 4 Variants Tested

Fixed the `vegas_line:0.25` → `--category-weight "vegas=0.25"` syntax issue. Ran 4 experiments:

| Variant | MAE | HR 3+ | N 3+ | OVER HR | UNDER HR | Gates Failed |
|---------|-----|-------|------|---------|----------|-------------|
| v2 (47d train) | 5.169 | **60.0%** | 45 | 63.6% | 58.8% | MAE (+0.03), N |
| v3 (87d train) | 5.107 | 55.9% | 34 | 54.5% | 56.5% | HR, N |
| v4 (47d + RSM 0.5) | 5.110 | 55.3% | 47 | 50.0% | 56.4% | HR, N, DIR |
| **v12_noveg Q55** | **5.024** | **60.0%** | 20 | **80.0%** | 53.3% | N only |

**Key findings:**
- v2 (47-day train, Dec 25 - Feb 9) is the best v9 variant
- v12_noveg Q55 is the standout model — best MAE, best OVER generation, best calibration
- All models fail sample size gate (N < 50) — structural limitation of 15-day eval window
- RSM 0.5 hurts v9_low_vegas, 87-day window dilutes signal — both added to dead ends

### 3. Shadow Model Registration

Both models uploaded to GCS and registered in `model_registry` with `enabled=true`, `status='shadow'`:

| Model ID | Family | GCS Path |
|----------|--------|----------|
| `catboost_v9_low_vegas_train1225_0209` | v9_low_vegas | `gs://nba-props-platform-models/catboost/v9/monthly/catboost_v9_33f_wt_train20251225-20260209_20260225_100515.cbm` |
| `catboost_v12_noveg_q55_train1225_0209` | v12_noveg_q55 | `gs://nba-props-platform-models/catboost/v12/monthly/catboost_v9_50f_noveg_train20251225-20260209_20260225_100720.cbm` |

Added `v12_noveg_q55` family to `cross_model_subsets.py` and `model_direction_affinity.py`.

### 4. Verified Session 342 Deploys

- All 4 Cloud Builds from commit `16e341c2`: SUCCESS
- Zero deployment drift
- prediction-worker deployed with zombie decommission
- phase6-export deployed with affinity blocking (`v343_affinity_blocking_active`)
- Today's predictions still show 22 system_ids (pre-deploy batch) — **tomorrow will show ~8**

### 5. Code & Doc Updates

- **CLAUDE.md:** Updated model section (crisis status, shadow models, dead ends, affinity blocking in negative filters)
- **cross_model_subsets.py:** Added `v12_noveg_q55` family
- **model_direction_affinity.py:** Added `v12_noveg_q55` to `v12_noveg` affinity group
- **tests:** 50/50 pass including 3 new Q55 tests
- **signal_best_bets_exporter.py:** Added `best-bets/latest.json` backward compat endpoint
- **post_grading_export/main.py:** Added `record.json` + `history.json` re-export post-grading

---

## What Was NOT Done (Action Items for Next Session)

### PRIORITY 1: Deep-Dive Model Feature Stores + Experiment with New Tuning

**User request:** Study all models and their feature stores — see what each model's strengths are, how feature importance profiles differ, and whether to experiment with new models/tuning.

**Plan:** Investigation 8 in the evaluation plan:
1. Extract `feature_importances_` from each enabled model's .cbm file
2. Compare top 10 features across families (v9_mae, v9_low_vegas, v12_noveg_q55, etc.)
3. Correlate feature importance with winning predictions per model
4. Experiment with Q57, different training windows, category weights, min-data-in-leaf

### PRIORITY 2: Grade Shadow Models (After 5+ Days)

The two shadow models need 5+ days of grading data before evaluation:
- `catboost_v12_noveg_q55_train1225_0209` — first-ever Q55, monitor OVER/UNDER split
- `catboost_v9_low_vegas_train1225_0209` — fresh v9_low_vegas, compare to stale version

```sql
-- Check shadow model performance after grading
SELECT system_id,
       CASE WHEN predicted_points < line_value THEN 'UNDER' ELSE 'OVER' END as direction,
       COUNT(*) as picks,
       COUNTIF(prediction_correct) as wins,
       ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct), COUNTIF(prediction_correct IS NOT NULL)) * 100, 1) as hr
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= '2026-02-26'
  AND system_id IN ('catboost_v12_noveg_q55_train1225_0209', 'catboost_v9_low_vegas_train1225_0209')
  AND prediction_correct IS NOT NULL
GROUP BY 1, 2
```

### PRIORITY 3: Verify Tomorrow's Prediction Count

Zombie decommission should reduce system_ids from 22 to ~8 tomorrow:
```sql
SELECT DISTINCT system_id, COUNT(*) as picks
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = DATE_ADD(CURRENT_DATE(), INTERVAL 1 DAY)
GROUP BY 1 ORDER BY 1
```

### PRIORITY 4: Decommission v12_vegas_q43

20.0% HR at edge 5+ — catastrophic. Should be disabled in model_registry:
```sql
UPDATE `nba-props-platform.nba_predictions.model_registry`
SET enabled = false, status = 'disabled', notes = CONCAT(notes, ' | Session 344: decommissioned, 20% HR edge 5+')
WHERE model_id = 'catboost_v12_vegas_q43_train0104_0215'
```

### PRIORITY 5: Run Investigation 1 (Best Bets Source Attribution)

See evaluation plan for full query. Key question: which model families source winning best bets?

---

## Commits This Session

| Commit | Description |
|--------|-------------|
| `733005a6` | feat: register Q55 shadow model, add evaluation plan, update model docs |

**Pushed to main** — auto-deploying. Cloud Functions will pick up the new `v12_noveg_q55` family classification.

---

## Key Files Modified

| File | Change |
|------|--------|
| `CLAUDE.md` | Model crisis status, shadow models, dead ends, affinity blocking |
| `shared/config/cross_model_subsets.py` | Added `v12_noveg_q55` family |
| `ml/signals/model_direction_affinity.py` | Added Q55 to `v12_noveg` affinity group |
| `tests/unit/signals/test_model_direction_affinity.py` | 3 new Q55 tests (50/50 pass) |
| `data_processors/publishing/signal_best_bets_exporter.py` | best-bets/latest.json backward compat |
| `orchestration/cloud_functions/post_grading_export/main.py` | record.json + history.json re-export |
| `docs/08-projects/current/model-system-evaluation-session-343/00-EVALUATION-PLAN.md` | Full evaluation plan |

---

## Model Registry State (8 Enabled)

| Model ID | Family | Feature Set | Status | Training |
|----------|--------|-------------|--------|----------|
| catboost_v9_33f_train20260106-20260205 | v9_mae | v9 (33f) | **PRODUCTION** | Jan 6 - Feb 5 |
| catboost_v9_low_vegas_train0106_0205 | v9_low_vegas | v9 (33f) | active | Jan 6 - Feb 5 |
| catboost_v12_mae_train0104_0215 | v12_mae | v12 (54f) | active | Jan 4 - Feb 15 |
| catboost_v12_noveg_mae_train0104_0215 | v12_noveg_mae | v12_noveg (50f) | active | Jan 4 - Feb 15 |
| catboost_v12_noveg_q43_train0104_0215 | v12_noveg_q43 | v12_noveg (50f) | active | Jan 4 - Feb 15 |
| catboost_v12_vegas_q43_train0104_0215 | v12_vegas_q43 | v12 (54f) | active | Jan 4 - Feb 15 |
| **catboost_v9_low_vegas_train1225_0209** | v9_low_vegas | v9 (33f) | **shadow** | Dec 25 - Feb 9 |
| **catboost_v12_noveg_q55_train1225_0209** | v12_noveg_q55 | v12_noveg (50f) | **shadow** | Dec 25 - Feb 9 |

---

## Quick Start for Next Session

```bash
# 1. Verify deploys landed from push
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=8
./bin/check-deployment-drift.sh --verbose

# 2. Check if zombie cleanup worked (tomorrow's predictions)
bq query --use_legacy_sql=false --project_id=nba-props-platform \
  "SELECT DISTINCT system_id FROM \`nba-props-platform.nba_predictions.player_prop_predictions\` WHERE game_date = CURRENT_DATE()"

# 3. Check shadow model predictions exist
bq query --use_legacy_sql=false --project_id=nba-props-platform \
  "SELECT system_id, COUNT(*) FROM \`nba-props-platform.nba_predictions.player_prop_predictions\` WHERE game_date = CURRENT_DATE() AND system_id IN ('catboost_v12_noveg_q55_train1225_0209', 'catboost_v9_low_vegas_train1225_0209') GROUP BY 1"

# 4. START: Deep-dive model feature stores (Priority 1)
# Extract feature importances from each model .cbm file
# See evaluation plan Investigation 8

# 5. Decommission v12_vegas_q43 (Priority 4)
```
