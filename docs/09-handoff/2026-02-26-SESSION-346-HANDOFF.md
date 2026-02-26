# Session 346 Handoff — Shadow Model Bug Fix, Decay Timeline, Daily Steering

**Date:** 2026-02-26
**Focus:** Fix shadow models not generating predictions, complete Investigation 2 (decay timeline), daily steering report.

---

## What Was Done

### 1. Fixed Shadow Models Not Loading (CRITICAL BUG)

**Root cause:** `get_enabled_models_from_registry()` in `catboost_monthly.py` line 293 filtered `WHERE status = 'active'`, but the 4 shadow models were registered with `status = 'shadow'`.

**Fix:** Changed filter to `status IN ('active', 'shadow')` — one line change.

**Also fixed:** Added `COPY ml/ ./ml/` to prediction worker Dockerfile — pre-existing missing dependency for breakout classifier's `from ml.features.breakout_features import ...`.

**Deployed:** prediction-worker deployed successfully. Shadow models will lazy-load on first prediction request (Feb 27 morning).

**Impact:** Shadow models lost 1 day of predictions (Feb 26). First shadow predictions: Feb 27. Shadow grading data expected: Mar 2-4.

### 2. Investigation 2: Model Decay Timeline (COMPLETED)

**Confirmed ~14-21 day shelf life hypothesis.** Full results in evaluation plan.

**Key findings:**

| Architecture | Profitable Window | Collapse Point | Edge 5+ Cliff |
|-------------|-------------------|----------------|---------------|
| Full-Vegas (V9, V12) | Days 0-14 | Day 15 | 74% → 32% |
| Low/No-Vegas | Days 0-21 | Day 22+ | More gradual |

- **V12 Champion (trained Jan 31):** 60% HR through day 14, collapses to 47.2% at day 22-28. Edge 5+ crashes from 66.7% to 30.8%.
- **Historical V9:** 60-62% HR days 0-14, cliff to 40.9% at day 15. Edge 5+ drops from 74% to 32%.
- **V9 Low Vegas:** More decay-resistant — 52.2% at days 15-21 vs 35-41% for full-Vegas models.

**Recommendations:**
1. **14-day retrain cadence** (7-day buffer before the day-21 cliff)
2. **Low-Vegas/No-Vegas architecture is more decay-resistant** — supports architecture shift
3. **Edge 5+ decays faster than edge 3+** — high-confidence picks are more staleness-sensitive

### 3. Daily Steering Report

**Model health:** ALL BLOCKED or DEGRADING. Best: v9_low_vegas at 53.7% HR 7d.

**Edge 5+ health:** v9_low_vegas PROFITABLE at 64.7% edge 5+ 14d (N=17). Production champions (v9, v12) are LOSING at edge 5+.

**Best bets:** 75.0% HR last 7d (6-2), 63.6% HR last 30d (28-16). Filter chain is working.

**Market regime:** GREEN compression (1.133), YELLOW edge supply (2.4 picks/day improving). Direction balance healthy: OVER 60% / UNDER 71.4%.

### 4. Best Bets Attribution (Updated)

Same as Session 345 — 106 graded picks. Shadow models haven't contributed yet since they weren't generating predictions. v12_mae OVER still crown jewel at 90.0% (20 picks).

---

## Key Insights

### 1. Shadow Model Bug Was Silent
The models were enabled in the registry (`enabled=TRUE`) but the code only loaded `status='active'`. No errors were logged — the registry query simply returned fewer models. Lesson: add logging for expected vs actual model count.

### 2. Decay Timeline Supports Architecture Shift
Low/no-Vegas models decay more gracefully (52% at day 15-21 vs 35% for full-Vegas). This, combined with Session 344's feature analysis (winners use player stats, losers anchor to Vegas), makes a strong case for transitioning to no-Vegas as the default architecture.

### 3. Best Bets System Resilient Despite Model Crisis
Despite ALL models being BLOCKED, best bets maintains 63.6% HR over 30 days. The edge 5+ filter + negative filter chain is extracting profitable signal from degraded models. The system works — it just needs better-performing models to increase volume.

---

## What Was NOT Done

### PRIORITY 1: Verify Shadow Models Loading (Feb 27 morning)
```sql
-- Should show ~9-10 system_ids
SELECT DISTINCT system_id
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = '2026-02-27'
```

### PRIORITY 2: Grade Shadow Models (Mar 2-4, 3-5 days from Feb 27)
```sql
SELECT system_id,
       CASE WHEN predicted_points < line_value THEN 'UNDER' ELSE 'OVER' END as direction,
       COUNT(*) as picks, COUNTIF(prediction_correct) as wins,
       ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct), COUNTIF(prediction_correct IS NOT NULL)) * 100, 1) as hr
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= '2026-02-27'
  AND system_id IN (
    'catboost_v12_noveg_q55_train1225_0209',
    'catboost_v9_low_vegas_train1225_0209',
    'catboost_v12_noveg_q55_tw_train1225_0209',
    'catboost_v12_noveg_q57_train1225_0209'
  )
  AND prediction_correct IS NOT NULL
GROUP BY 1, 2
```

### PRIORITY 3: Investigation 3 — Direction Bias Deep Dive
Track weekly `avg(predicted - line_value)` per family. Segment by home/away, b2b, player tier. Identify if UNDER bias worsens with staleness.

### PRIORITY 4: Evaluate v12_mae UNDER Blocking
53.3% HR drags best bets from 71.4% → 68.9%. Wait for shadow models to provide alternative UNDER picks first.

### PRIORITY 5: Stars UNDER Negative Filter
0% HR in fresh window experiment (N=5). Need N >= 15 from live data before implementing.

---

## Code Changes

| File | Change |
|------|--------|
| `predictions/worker/prediction_systems/catboost_monthly.py` | Changed registry query from `status='active'` to `status IN ('active', 'shadow')` |
| `predictions/worker/Dockerfile` | Added `COPY ml/ ./ml/` for breakout classifier imports |
| `docs/08-projects/current/model-system-evaluation-session-343/00-EVALUATION-PLAN.md` | Added Investigation 2 findings, updated checklist |

---

## Quick Start for Next Session

```bash
# 1. Verify shadow models are generating predictions (should see ~9-10 system_ids)
bq query --use_legacy_sql=false --project_id=nba-props-platform \
  "SELECT DISTINCT system_id FROM \`nba-props-platform.nba_predictions.player_prop_predictions\` WHERE game_date = '2026-02-27'"

# 2. If 3+ days past Feb 27, grade shadow models
bq query --use_legacy_sql=false --project_id=nba-props-platform \
  "SELECT system_id, COUNT(*) as n, COUNTIF(prediction_correct) as w, ROUND(100*SAFE_DIVIDE(COUNTIF(prediction_correct), COUNTIF(prediction_correct IS NOT NULL)),1) as hr FROM \`nba-props-platform.nba_predictions.prediction_accuracy\` WHERE game_date >= '2026-02-27' AND (system_id LIKE '%q55%' OR system_id LIKE '%q57%' OR system_id LIKE '%low_vegas_train1225%') AND prediction_correct IS NOT NULL GROUP BY 1"

# 3. Run daily checks
/daily-steering
./bin/check-deployment-drift.sh --verbose
```
