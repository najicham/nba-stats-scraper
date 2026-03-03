# Session 383 Prompt

Session 382C just completed. Here's what happened and what to do next.

## What Was Done (Session 382C)

1. **2 spread-fix models deployed** — First models trained with corrected Feature 41 (spread_magnitude) and Feature 42 (implied_team_total), which were ALL ZEROS the entire season until Session 375 backfill.
   - `lgbm_v12_noveg_train0103_0227` — **73.08% HR edge 3+ (N=26), ALL GATES PASSED**. OVER 60%, UNDER 90.9%.
   - `catboost_v12_noveg_train0103_0227` — 64.71% HR (N=17), force-registered (sample size gate failed due to 2-day eval window only). VW015.
   - Both enabled in model_registry, will generate predictions on next pipeline run.

2. **`sharp_line_drop_under` signal deployed** — UNDER mirror of `sharp_line_move_over`. DK line dropped 2+ pts intra-day + UNDER = 72.4% HR (N=293), Feb 58.3%. 22 signals total. Coordinator manually redeployed (rev `prediction-coordinator-00325-7sv`).

3. **Fleet triage: 12,977 zombie predictions deactivated** — BLOCKED/legacy models had active predictions competing in best bets per-player selection. Worst: 15.9% HR model with 408 active preds, ensemble_v1 with avg edge 6.3. All 23 BLOCKED + 7 legacy models cleaned.

4. **Filter audit clean** — No drift or review alerts on any of the 5 directly-evaluated filters.

## Immediate Priorities

1. **Monitor new models** — Check if both spread-fix models generated predictions. Run:
   ```sql
   SELECT system_id, COUNT(*), AVG(ABS(predicted_points - current_points_line)) as avg_edge
   FROM nba_predictions.player_prop_predictions
   WHERE game_date = CURRENT_DATE() AND system_id IN ('lgbm_v12_noveg_train0103_0227', 'catboost_v12_noveg_train0103_0227')
   GROUP BY 1
   ```

2. **Monitor `sharp_line_drop_under` firing rate** — Check if signal is firing on UNDER picks and boosting signal count:
   ```sql
   SELECT signal_tag, COUNT(*) FROM nba_predictions.pick_signal_tags
   WHERE game_date = CURRENT_DATE() AND signal_tag = 'sharp_line_drop_under'
   GROUP BY 1
   ```

3. **Best bets quality check** — After 2-3 days, compare best bets performance before/after fleet triage. The 12,977 zombie prediction cleanup should improve selection quality.

4. **Run daily validation** — `/validate-daily` to confirm pipeline health after all changes.

## Fleet State

- **10 enabled models** in registry (2 new spread-fix + 8 existing)
- Only 2 confirmed HEALTHY: both LightGBM (71.4%, 19 days stale)
- New models have no live data yet — accumulating starting next pipeline run
- All BLOCKED/legacy model predictions deactivated

## Key Files Changed
- `ml/signals/sharp_line_drop_under.py` (new)
- `ml/signals/registry.py`, `signal_health.py`, `pick_angle_builder.py`, `combo_registry.py`
- Handoff: `docs/09-handoff/2026-03-02-SESSION-382C-HANDOFF.md`
