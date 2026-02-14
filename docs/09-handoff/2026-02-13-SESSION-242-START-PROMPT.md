# Session 242 Start Prompt

Read the Session 241 handoff at `docs/09-handoff/2026-02-13-SESSION-241-HANDOFF.md` and the project doc at `docs/08-projects/current/model-improvement-analysis/24-ALL-PLAYER-TRAINING-PLAN.md`.

## Context

Session 241 implemented V9 all-player predictions:
- **Backfilled** 904 NO_PROP_LINE V9 predictions (Feb 1-12), graded 13,915
- **Deployed** V9 re-prediction on enrichment (`/line-update` endpoint) — when lines arrive at 18:40 UTC, V9 re-predicts with real vegas features
- **Confirmed** training already includes all players (36.2% without lines)
- **MAE results:** no-line 4.99, with-line 5.45, overall 5.30
- **Champion decay confirmed:** 48% HR all, 40.6% HR edge 3+ (below 52.4% breakeven). Fresh retrain: 56.7% / 69.2%.

All-Star break: Feb 13-18. Next games Feb 19.

## Priorities

1. **Verify `/line-update` on Feb 19** — first game day post break. After 18:40 UTC enrichment, check for `LINE_UPDATE` predictions:
   ```sql
   SELECT prediction_run_mode, COUNT(*) FROM nba_predictions.player_prop_predictions
   WHERE game_date = '2026-02-19' AND system_id = 'catboost_v9' GROUP BY 1
   ```

2. **Monthly V9 retrain is overdue** — champion is 35+ days stale. All-Star break is ideal window:
   ```bash
   PYTHONPATH=. python ml/experiments/quick_retrain.py \
       --name "V9_FEB_RETRAIN" --train-start 2025-11-02 --train-end 2026-02-12 --walkforward
   ```

3. **V12 deployment decision** — vegas-free model ready (67% HR edge 3+ avg across 4 eval windows). See `docs/08-projects/current/model-improvement-analysis/22-PHASE1B-RESULTS.md`.

## Quick Validation
```bash
/validate-daily
```
