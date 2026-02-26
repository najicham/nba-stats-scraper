# Session 344b Handoff — Feature Analysis, Tuning Experiments, Model Registration

**Date:** 2026-02-25
**Focus:** Deep-dive model feature stores, run tuning experiments, decommission v12_vegas_q43, register promising shadow models.

---

## What Was Done

### 1. Verified Session 343 Deploys

- All 8 Cloud Builds: SUCCESS (deployed ~15:38 UTC)
- Zero deployment drift
- Zombie cleanup NOT YET visible (today's predictions ran before deploy) — expect ~9 system_ids tomorrow
- Shadow models (Q55, v9_low_vegas) not yet generating predictions — will start tomorrow

### 2. Feature Importance Analysis (Investigation 4+8)

**Extracted `feature_importances_` from all 8 enabled models.** Downloaded .cbm files from GCS, loaded with CatBoost.

**Core finding — Vegas features are the #1 differentiator:**

| Feature | Winners (Q55, v9_lv, nv_q43, nv_mae) | Losers (v9_mae, v12_mae, vq43) |
|---------|---------------------------------------|--------------------------------|
| `vegas_points_line` | 2.7% | **23.9%** |
| `points_avg_season` | **23.1%** | 8.7% |
| `vegas_opening_line` | 1.2% | **10.0%** |
| `points_avg_last_10` | **14.0%** | 6.4% |
| `line_vs_season_avg` | **8.0%** | 2.0% |

**Winners form independent opinions from player stats. Losers are cheap copies of Vegas.**

### 3. Feature-Value/Winning Correlation

Queried `prediction_accuracy` JOIN `ml_feature_store_v2` for 14 days at edge 3+.

**Strong signals differentiating winning from losing predictions:**
- **pts_std (variance):** UNDER winners have higher variance (6.5-7.4 vs 5.6-6.5). High-variance players more likely to go UNDER.
- **recent_trend (momentum):** UNDER winners have negative trend (-0.5 to -0.8 vs +0.4 for losers). Players trending UP + UNDER bet = BAD.
- **multi_book_line_std:** Asymmetric — UNDER wins with LOW disagreement, OVER wins with HIGH disagreement.

### 4. Tuning Experiments (7 models tested)

All v12_noveg architecture, trained Dec 25 - Feb 9:

| Model | MAE | HR 3+ (N) | HR 5+ (N) | OVER HR | UNDER HR | Notes |
|-------|-----|-----------|-----------|---------|----------|-------|
| **Q55+trend_wt** | 5.118 | **58.6% (29)** | 66.7% (3) | 50.0% | **60.9%** | **BEST OVERALL — registered** |
| **Q57** | 5.089 | 53.9% (26) | **80.0% (5)** | 40.0% | **62.5%** | **UNDER specialist — registered** |
| Q55 baseline | 5.069 | 47.6% (21) | 50.0% (2) | 44.4% | 50.0% | Weaker than 7d eval suggested |
| Q60 | 5.111 | 51.5% (33) | 80.0% (5) | 50.0% | 55.6% | OVER volume but unprofitable |
| Q55+minleaf25 | 5.000 | 50.0% (4) | N/A | N/A | 50.0% | Kills feature diversity |
| Q55+minleaf50 | 5.058 | 50.0% (6) | 0% (1) | N/A | 50.0% | Kills feature diversity |

**Q55+trend_wt config:** `--category-weight "recent_performance=2.0,derived=1.5,matchup=0.5"` — directly encodes feature analysis insight.

### 5. Decommissioned v12_vegas_q43

- Disabled in model_registry: `enabled=false, status='disabled'`
- 20% HR at edge 5+, confirmed by feature analysis: vegas_points_line at 22.8% importance anchors model to market

### 6. Registered 2 New Shadow Models

| Model ID | Family | GCS Path |
|----------|--------|----------|
| `catboost_v12_noveg_q55_tw_train1225_0209` | v12_noveg_q55_tw | `gs://nba-props-platform-models/catboost/v12/monthly/catboost_v12_50f_noveg_q55_trend_wt_train20251225-20260209_20260225_155457.cbm` |
| `catboost_v12_noveg_q57_train1225_0209` | v12_noveg_q57 | `gs://nba-props-platform-models/catboost/v12/monthly/catboost_v12_50f_noveg_q57_train20251225-20260209_20260225_161059.cbm` |

Updated `cross_model_subsets.py` and `model_direction_affinity.py` to classify both new families. 50/50 tests pass.

### 7. Code Changes

| File | Change |
|------|--------|
| `shared/config/cross_model_subsets.py` | Added `v12_noveg_q55_tw` and `v12_noveg_q57` families. Updated `build_noveg_mae_sql_filter` to exclude Q55/Q57/Q60 patterns. |
| `ml/signals/model_direction_affinity.py` | Added `v12_noveg_q55_tw` and `v12_noveg_q57` to `v12_noveg` affinity group |
| `CLAUDE.md` | Updated shadow models, dead ends (min-leaf, Q60), model count |
| `docs/08-projects/current/model-system-evaluation-session-343/00-EVALUATION-PLAN.md` | Added Session 344 findings section |

---

## Key Insights

### 1. The Winning Recipe
**No-vegas + Q55-Q57 quantile + trend category weights.** This combination:
- Removes Vegas anchoring (the #1 cause of model failure)
- Uses above-mean quantile to counteract structural UNDER bias
- Up-weights features that differentiate winners from losers

### 2. Q55 Baseline Weaker Than Reported
Session 343 reported 60% HR edge 3+ on a 7-day window. Extended to 15 days: only 47.6%. The initial assessment was optimistic due to small, favorable sample. **Always use 15+ day eval windows.**

### 3. Feature Diversity Is Essential
min-data-in-leaf regularization (25 or 50) concentrates importance on 2-3 features (64-68% in top 2) and destroys the secondary features that provide betting edge. The default CatBoost min-leaf is better.

### 4. Q60 Is the Quantile Ceiling
Q60 generates OVER volume (24 OVER picks at edge 3+ vs 9 for Q55) but at only 50% OVER HR — unprofitable. Diminishing returns beyond Q57.

---

## What Was NOT Done

### PRIORITY 1: Wait for Shadow Model Grading (5+ days)
All 4 shadow models need real grading data before evaluation:
```sql
SELECT system_id,
       CASE WHEN predicted_points < line_value THEN 'UNDER' ELSE 'OVER' END as direction,
       COUNT(*) as picks,
       COUNTIF(prediction_correct) as wins,
       ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct), COUNTIF(prediction_correct IS NOT NULL)) * 100, 1) as hr
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= '2026-02-26'
  AND system_id IN (
    'catboost_v12_noveg_q55_train1225_0209',
    'catboost_v9_low_vegas_train1225_0209',
    'catboost_v12_noveg_q55_tw_train1225_0209',
    'catboost_v12_noveg_q57_train1225_0209'
  )
  AND prediction_correct IS NOT NULL
GROUP BY 1, 2
```

### PRIORITY 2: Verify Tomorrow's Prediction Count
Zombie decommission + new shadows should produce ~9 system_ids.

### PRIORITY 3: Add Export Freshness Monitor to daily-health-check CF
`bin/monitoring/check_export_freshness.py` currently runs manually. Should be integrated into the `daily-health-check` Cloud Function so stale exports trigger Slack alerts automatically. The CF is at `orchestration/cloud_functions/daily_health_check/`. Add a freshness check step that calls the same logic, alerting to `#nba-alerts` on STALE/MISSING.

### PRIORITY 4: Investigation 1 — Best Bets Source Attribution
Still needed to determine which model families source winning best bets.

### PRIORITY 5: Investigations 2-3 — Decay Timeline + Direction Bias Deep Dive

### PRIORITY 6: Fresh Training Window Experiment
Test if the Q55+trend_wt recipe holds on a different training window (e.g., Jan 1 - Feb 19) to confirm it's not window-specific.

---

## Model Registry State (9 Enabled)

| Model ID | Family | Status | Training |
|----------|--------|--------|----------|
| catboost_v9_33f_train... | v9_mae | **PRODUCTION** | Jan 6 - Feb 5 |
| catboost_v9_low_vegas_train0106_0205 | v9_low_vegas | active | Jan 6 - Feb 5 |
| catboost_v12_mae_train0104_0215 | v12_mae | active | Jan 4 - Feb 15 |
| catboost_v12_noveg_mae_train0104_0215 | v12_noveg_mae | active | Jan 4 - Feb 15 |
| catboost_v12_noveg_q43_train0104_0215 | v12_noveg_q43 | active | Jan 4 - Feb 15 |
| catboost_v12_noveg_q55_train1225_0209 | v12_noveg_q55 | shadow | Dec 25 - Feb 9 |
| catboost_v9_low_vegas_train1225_0209 | v9_low_vegas | shadow | Dec 25 - Feb 9 |
| **catboost_v12_noveg_q55_tw_train1225_0209** | **v12_noveg_q55_tw** | **shadow** | Dec 25 - Feb 9 |
| **catboost_v12_noveg_q57_train1225_0209** | **v12_noveg_q57** | **shadow** | Dec 25 - Feb 9 |

**Disabled:** catboost_v12_vegas_q43_train0104_0215 (Session 344, 20% HR)

---

## Dead Ends Confirmed (Session 344)

| Approach | Why Dead |
|----------|----------|
| min-data-in-leaf 25/50 | Kills feature diversity (top 2 = 64-68% importance) |
| Q60 quantile | Generates OVER volume but not profitably (50% OVER HR) |
| Q43 + Vegas | 20% HR, feature analysis confirms Vegas anchoring at 22.8% |
| Full-Vegas MAE | Vegas features = 37% of importance, model becomes worse copy of market |

---

## Quick Start for Next Session

```bash
# 1. Check if zombie cleanup + new shadows are generating
bq query --use_legacy_sql=false --project_id=nba-props-platform \
  "SELECT DISTINCT system_id FROM \`nba-props-platform.nba_predictions.player_prop_predictions\` WHERE game_date = CURRENT_DATE()"

# 2. If 5+ days have passed, grade shadow models
bq query --use_legacy_sql=false --project_id=nba-props-platform \
  "SELECT system_id, COUNT(*) as n, COUNTIF(prediction_correct) as w FROM \`nba-props-platform.nba_predictions.prediction_accuracy\` WHERE game_date >= '2026-02-26' AND (system_id LIKE '%q55_tw%' OR system_id LIKE '%q57%') GROUP BY 1"

# 3. Run daily checks
/daily-steering
./bin/check-deployment-drift.sh --verbose
```
