# Session 241 Handoff — V9 All-Player Predictions

**Date:** 2026-02-13
**Session Type:** Feature Implementation + Data Analysis
**Status:** Complete — code deployed, backfill done, experiment run
**Games Status:** All-Star Break (Feb 13-18) — Next games Feb 19

---

## What Was Done

### 1. V9 NO_PROP_LINE Backfill (`bin/backfill-v9-no-line-predictions.py`)
- Created reusable backfill script for V9 predictions on players without prop lines
- **Ran backfill:** 904 predictions across Feb 1-12 (12 game dates)
- All written as `line_source='NO_PROP_LINE'`, `prediction_run_mode='BACKFILL'`
- Predictions per day roughly doubled (e.g., Feb 3: 146 → 343)
- Safety: hard-coded training end dates per model prevent data leakage

### 2. V9 Re-prediction on Enrichment (Deployed)
- **New endpoint:** `/line-update` on prediction-coordinator
- **New quality gate mode:** `LINE_UPDATE` — bypasses "Predict Once, Never Replace" so V9 can re-predict when vegas features arrive
- **Enrichment trigger updated:** After enriching lines at 18:40 UTC, identifies V9 players that got lines and calls `/line-update` to supersede old predictions and generate new ones
- **Enrichment processor:** Added `get_v9_players_needing_reprediction()` and `enriched_players` list in result
- **Why:** V9 uses `vegas_points_line` (feature #25, 29% importance). NaN → real value = materially different prediction.

### 3. Training Diagnostics (`--include-no-line` flag)
- Added to `quick_retrain.py` and documented in SKILL.md
- Reveals that **36.2% of training data is players without prop lines** — model already trains on all players
- The flag is diagnostic only, does not change training behavior

### 4. Grading + MAE Analysis
- Grading backfill ran for Feb 1-12 (15,370 total predictions graded)
- **No-line MAE: 4.99** vs with-line MAE: 5.45 (bench/role players are more predictable)
- **No-line role players (5-14 pts): 3.08 MAE** — best of any segment
- **No-line stars: 18.5 MAE** — without vegas as anchor, model underpredicts stars severely (only 12 cases)
- **Champion V9 decay confirmed:** 48% HR all, 40.6% HR edge 3+ (well below 52.4% breakeven)

---

## Key Numbers

| Metric | Value |
|--------|-------|
| V9 backfill predictions | 904 (Feb 1-12) |
| Total graded (all V9, Feb 1-12) | 2,288 |
| No-line MAE | 4.99 |
| With-line MAE | 5.45 |
| Overall MAE | 5.30 |
| Training: % without lines | 36.2% (3,483 / 9,629) |
| Fresh retrain HR all | 56.7% |
| Fresh retrain HR edge 3+ | 69.2% (n=13, low sample) |
| Champion HR all (stale) | 48.0% |
| Champion HR edge 3+ (stale) | 40.6% |

---

## Commits

| SHA | Description |
|-----|-------------|
| `b9b54644` | feat: V9 all-player predictions — backfill, re-prediction on enrichment, training diagnostics |
| `7ee2063f` | docs: All-player training analysis — line coverage and MAE results |
| `d9676cae` | docs: Session 241 results — V9 backfill, training experiment, MAE analysis |

---

## Deployments

All auto-deployed via Cloud Build (all SUCCESS):
- `prediction-coordinator` — `/line-update` endpoint + `_generate_predictions_for_players` accepts configurable `prediction_run_mode`
- `enrichment-trigger` Cloud Function — V9 re-prediction after enrichment
- `prediction_line_enrichment_processor` — `enriched_players` in result + `get_v9_players_needing_reprediction()`

---

## Files Changed/Created

| File | Action |
|------|--------|
| `bin/backfill-v9-no-line-predictions.py` | **NEW** — V9 NO_PROP_LINE backfill script |
| `predictions/coordinator/coordinator.py` | EDIT — `/line-update` endpoint, configurable run mode |
| `predictions/coordinator/quality_gate.py` | EDIT — `LINE_UPDATE` mode in enum, thresholds, parser |
| `orchestration/cloud_functions/enrichment_trigger/main.py` | EDIT — V9 re-prediction trigger after enrichment |
| `data_processors/enrichment/.../prediction_line_enrichment_processor.py` | EDIT — enriched players list, V9 reprediction query |
| `ml/experiments/quick_retrain.py` | EDIT — `--include-no-line` flag, `analyze_training_line_coverage()` |
| `.claude/skills/model-experiment/SKILL.md` | EDIT — document `--include-no-line` |
| `docs/08-projects/current/model-improvement-analysis/24-ALL-PLAYER-TRAINING-PLAN.md` | **NEW** — full project doc with results |
| `docs/08-projects/current/model-improvement-analysis/25-ALL-PLAYER-TRAINING-ANALYSIS.md` | **NEW** — training analysis doc |

---

## What Needs Verification

### 1. Enrichment Re-prediction (Next Game Day — Feb 19)
The `/line-update` flow hasn't been tested in production yet. On Feb 19 (first game after All-Star break), verify:
```sql
-- Should see LINE_UPDATE predictions after 18:40 UTC
SELECT prediction_run_mode, COUNT(*) as n
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-19'
  AND system_id = 'catboost_v9'
GROUP BY 1
```
Check enrichment trigger logs:
```bash
gcloud functions logs read enrichment-trigger --region=us-west2 --limit=50
```
Check coordinator logs for `/line-update`:
```bash
gcloud run services logs read prediction-coordinator --region=us-west2 --limit=50 | grep line-update
```

### 2. Grading Backfill
First attempt failed (Firestore lock timeout — transient). Retry succeeded for most dates but should be verified:
```sql
SELECT game_date, COUNT(*) as graded
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date BETWEEN '2026-02-01' AND '2026-02-12'
GROUP BY 1 ORDER BY 1
```

---

## Pending / Next Steps

1. **Monthly V9 retrain is overdue** — champion at 48% HR all, 40.6% HR edge 3+ (35+ days stale). Fresh retrain shows 56.7% / 69.2%. Run:
   ```bash
   PYTHONPATH=. python ml/experiments/quick_retrain.py \
       --name "V9_FEB_RETRAIN" \
       --train-start 2025-11-02 --train-end 2026-02-12 \
       --walkforward
   ```
   Wait for gates to pass, then follow shadow → promote process.

2. **V12 deployment** — V12 (vegas-free, 50 features) showed 67% HR edge 3+ avg across 4 eval windows (Session 228-230). Ready for production but requires separate deployment decision.

3. **All-Star break** — No games Feb 13-18. Pipeline will be idle. Good window for retrain + shadow testing.

4. **Verify no-line stars** — 12 cases of stars without lines had 18.5 MAE. After `/line-update` is active, these should get re-predicted with real vegas features, dramatically improving accuracy.

---

## Known Issues

- **Grading backfill Firestore lock timeout** — transient, resolved on retry. If it happens again, just retry.
- **No-line bench bias** — model overpredicts bench players scoring near 0 (bias +4.7). Expected behavior — CatBoost can't predict below 0.
- **Edge 3+ sample size** — only 13 graded in the 12-day eval window. Need 50+ for governance gates. Longer eval window or more game days needed.
