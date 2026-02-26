# Session 349 Prompt

Start with the Session 348 handoff at `docs/09-handoff/2026-02-26-SESSION-348-HANDOFF.md`.

Session 348 accomplished: full February decline diagnosis (OVER collapsed 80%→58%, Starters OVER 90%→33%, full-vegas failing), signal-density filter deployed (76.2% backtest HR, +8pp improvement), fresh v12_noveg_q55_tw model retrained (68% HR, +0.11 bias) and registered as shadow, pubsub_v1 import error fixed.

Work through these priorities:

1. **Grade Feb 26 best bets.** 5 picks were exported (last batch before signal-density filter). All were base-only Stars/Starters UNDER — exactly the profile the new filter blocks. Check if the filter was correct to block this type:
   ```sql
   SELECT player_name, recommendation, edge, line_value, prediction_correct, actual_points
   FROM `nba-props-platform.nba_predictions.signal_best_bets_picks`
   WHERE game_date = '2026-02-26'
   ```

2. **Verify shadow model coverage.** Feb 27 should show ~117 predictions per shadow, including the new `train0105_0215`:
   ```sql
   SELECT system_id, COUNT(*) as predictions
   FROM `nba-props-platform.nba_predictions.player_prop_predictions`
   WHERE game_date = '2026-02-27'
   GROUP BY 1 ORDER BY 2 DESC
   ```

3. **Check signal-density filter impact.** Feb 27 is the first day with the filter active. How many picks survive?
   ```sql
   SELECT game_date, COUNT(*) as picks,
          ARRAY_TO_STRING(ARRAY_AGG(player_name ORDER BY ABS(edge) DESC), ', ') as players
   FROM `nba-props-platform.nba_predictions.signal_best_bets_picks`
   WHERE game_date = '2026-02-27'
   GROUP BY 1
   ```
   If zero picks, consider lowering edge floor to 4.5 for signal-rich picks (4+ signals).

4. **Grade shadow models if 3+ days available** (expected Mar 1-3):
   ```sql
   SELECT system_id,
          CASE WHEN predicted_points < line_value THEN 'UNDER' ELSE 'OVER' END as direction,
          COUNT(*) as picks, COUNTIF(prediction_correct) as wins,
          COUNTIF(prediction_correct IS NOT NULL) as graded,
          ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct), COUNTIF(prediction_correct IS NOT NULL)) * 100, 1) as hr
   FROM `nba-props-platform.nba_predictions.prediction_accuracy`
   WHERE game_date >= '2026-02-27'
     AND system_id LIKE '%train%'
     AND prediction_correct IS NOT NULL
   GROUP BY 1, 2
   ORDER BY 1, 2
   ```

5. **Evaluate blowout_recovery signal for demotion.** 57.1% HR (14 picks) — the worst performing signal. Consider moving to DISABLED.

6. **Consider disabling older q55_tw shadow** (`train1225_0209`) once newer (`train0105_0215`) has 2-3 days of data.

Key context:
- Signal-density filter blocks picks with ONLY base signals (model_health + high_edge + edge_spread_optimal). Backtest: 57.1% HR blocked vs 76.2% kept.
- Tonight's 5 picks were exported BEFORE filter deployed — natural experiment.
- 11 enabled models (2 production + 4 active + 5 shadow).
- All production models 21-26 days stale. Fresh q55_tw shadow is the path to recovery.
- Best bets algorithm version: `v348_signal_density_filter`.
