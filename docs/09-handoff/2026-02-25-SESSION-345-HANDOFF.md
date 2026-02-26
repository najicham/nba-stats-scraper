# Session 345 Handoff — Export Freshness Monitor, Best Bets Attribution, Fresh Window Experiment

**Date:** 2026-02-25
**Focus:** Verify zombie cleanup, integrate export freshness monitoring, run Investigation 1 (best bets source attribution), test Q55+trend_wt recipe on fresh training window.

---

## What Was Done

### 1. Verified Zombie Cleanup + Shadow Model Activation (Priority 1)

- **Model registry confirmed:** 9 enabled models (correct)
- **Today's predictions (Feb 25):** Still show 22 system_ids — expected since predictions ran before Session 344 deploy
- **Feb 26 predictions should show ~9 system_ids** with all 4 shadow models active
- **Deployment drift:** Zero — all services up to date at commit c3d2be9
- **Shadow models not yet generating:** None of the 4 shadows (Q55, Q55+trend_wt, Q57, v9_low_vegas_new) have prediction data yet. First predictions expected Feb 26.

### 2. Added Export Freshness Monitor to daily-health-check CF (Priority 2)

Integrated `bin/monitoring/check_export_freshness.py` logic into the daily-health-check Cloud Function as CHECK 8.

**What it monitors:**
- 10 GCS export files in `gs://nba-props-platform-api/`
- Configurable staleness thresholds: 12h (tonight all-players), 24h (status, signal-health, model-health, best-bets), 36h (record, history)
- Severity levels: `critical` (tonight/all-players, signal-best-bets/latest), `fail` (status, health, best-bets), `warn` (record, history)

**Alert routing:** Same as existing checks — critical → #app-error-alerts, warnings → #nba-alerts, summary → #daily-orchestration.

**File changed:** `orchestration/cloud_functions/daily_health_check/main.py` (+109 lines)

### 3. Investigation 1: Best Bets Source Attribution (Priority 3)

Joined `signal_best_bets_picks` with `prediction_accuracy` for comprehensive grading (Jan 1 - Feb 25).

**Overall: 68.9% HR on 106 graded picks**

| Family | Direction | Graded | Wins | HR | Avg Edge |
|--------|-----------|--------|------|----|----------|
| **v12_mae OVER** | OVER | **20** | **18** | **90.0%** | 8.0 |
| **v9_mae UNDER** | UNDER | 22 | 15 | **68.2%** | 5.9 |
| v9_mae OVER | OVER | 43 | 27 | 62.8% | 7.5 |
| v12_mae UNDER | UNDER | 15 | 8 | 53.3% | 4.5 |

**Counterfactual: Excluding v12_mae UNDER → 71.4% HR** (up from 68.9%).

**Key insight:** v12_mae OVER (90%) is the crown jewel. v12_mae UNDER (53.3%) is the only family+direction combo below breakeven. v9_low_vegas and noveg variants barely appear because they were recently activated.

**Note:** signal_best_bets_picks table has grading gaps (only Feb 22+ has inline grading populated). Join with prediction_accuracy is needed for full picture.

### 4. Shadow Model Live Performance (Priority 4)

No grading data available — all 4 shadows registered Feb 25, first predictions expected Feb 26. Check back in 3-5 days.

### 5. Fresh Training Window Experiment (Priority 5)

Trained Q55+trend_wt on Jan 5 - Feb 19 (46 days) with eval Feb 20-28.

| Metric | Original (Dec 25 - Feb 9) | Fresh (Jan 5 - Feb 19) |
|--------|---------------------------|------------------------|
| HR edge 3+ | **58.6%** (N=29) | 48.0% (N=25) |
| HR edge 5+ | 66.7% (N=3) | **66.7%** (N=9) |
| OVER HR | 50.0% (N=6) | **71.4%** (N=7) |
| UNDER HR | **60.9%** (N=23) | 38.9% (N=18) |
| Vegas bias | N/A | -0.42 |
| Stars HR | N/A | 0% (N=5) |

**Finding: Recipe is partially window-sensitive.**
- Edge 5+ is stable at 66.7% across both windows — genuine signal exists
- OVER improved (71.4%), UNDER collapsed (38.9%) — Stars UNDER = 0% is the culprit
- Role players remain strong (66.7%) — "role player edge" pattern confirmed
- **The recipe needs a Stars UNDER filter** to be robust across windows

**Gates: FAILED** (MAE, HR 3+, directional balance). Model saved locally but NOT uploaded/registered.

---

## Key Insights

### 1. Best Bets Attribution Confirms Model-Direction Value
- v12_mae OVER (90% HR) should be protected/prioritized
- v12_mae UNDER (53.3%) should get model-direction affinity blocking
- v9_mae provides volume at 62-68% — still valuable
- The new noveg shadow models haven't had time to contribute yet

### 2. Q55+trend_wt Recipe Has Real Signal but Needs Guardrails
- Edge 5+ = 66.7% across both windows — the high-edge signal is genuine
- OVER predictions are strong (71.4%) in the fresh window
- Stars UNDER is a consistent vulnerability (0% on fresh window)
- **Recommendation:** Add "Stars UNDER at edge < 5" negative filter

### 3. Export Freshness Monitoring Now Automated
- Daily health check at 8 AM ET now checks all 10 export files
- Will catch stale exports like the Session 343 incident (best-bets/latest.json stale 4 days)

---

## What Was NOT Done

### PRIORITY 1: Verify Feb 26 Predictions (~9 system_ids)
```sql
SELECT DISTINCT system_id
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = '2026-02-26'
```

### PRIORITY 2: Grade Shadow Models (need 3-5 days from Feb 26)
```sql
SELECT system_id,
       CASE WHEN predicted_points < line_value THEN 'UNDER' ELSE 'OVER' END as direction,
       COUNT(*) as picks, COUNTIF(prediction_correct) as wins,
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

### PRIORITY 3: Consider v12_mae UNDER Blocking
Based on Investigation 1, v12_mae UNDER at 53.3% HR may warrant model-direction affinity blocking. Wait for shadow models to provide alternative UNDER picks first.

### PRIORITY 4: Investigations 2-3 (Decay Timeline, Direction Bias Deep Dive)
From evaluation plan — not yet started.

### PRIORITY 5: Consider Stars UNDER Filter
Fresh window experiment shows Stars (25+) UNDER at 0% HR (N=5). May need a negative filter: `Stars UNDER + edge < 5 → block`.

---

## Code Changes

| File | Change |
|------|--------|
| `orchestration/cloud_functions/daily_health_check/main.py` | Added GCS export freshness monitoring (CHECK 8), v1.4 |

## Model Artifacts

| File | Notes |
|------|-------|
| `models/catboost_v9_50f_noveg_wt_train20260105-20260219_20260225_163751.cbm` | Fresh window experiment, GATES FAILED, local only |

---

## Quick Start for Next Session

```bash
# 1. Check if zombie cleanup worked (should see ~9 system_ids)
bq query --use_legacy_sql=false --project_id=nba-props-platform \
  "SELECT DISTINCT system_id FROM \`nba-props-platform.nba_predictions.player_prop_predictions\` WHERE game_date = '2026-02-26'"

# 2. If 3+ days past Feb 26, grade shadow models
bq query --use_legacy_sql=false --project_id=nba-props-platform \
  "SELECT system_id, COUNT(*) as n, COUNTIF(prediction_correct) as w FROM \`nba-props-platform.nba_predictions.prediction_accuracy\` WHERE game_date >= '2026-02-26' AND (system_id LIKE '%q55%' OR system_id LIKE '%q57%' OR system_id LIKE '%low_vegas_train1225%') AND prediction_correct IS NOT NULL GROUP BY 1"

# 3. Check export freshness monitoring working
gcloud functions logs read daily-health-check --project=nba-props-platform --limit=20 --region=us-west2

# 4. Run daily checks
/daily-steering
./bin/check-deployment-drift.sh --verbose
```
