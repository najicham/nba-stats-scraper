# Session 348 Prompt

Copy/paste this to start the next session:

---

Start with the Session 347 handoff at docs/09-handoff/2026-02-26-SESSION-347-HANDOFF.md and the evaluation plan at docs/08-projects/current/model-system-evaluation-session-343/00-EVALUATION-PLAN.md.

Work through these priorities:

1. **Fix best bets grading.** `signal_best_bets_picks.prediction_correct` is NULL for most rows (only 7 of 49 since Jan 28). The grading service writes to `prediction_accuracy` but doesn't backfill to `signal_best_bets_picks`. Consider adding a post-grading job that joins actuals. This is critical for programmatic performance monitoring.

2. **Monitor Feb 26 best bets results.** 5 picks were exported (first since health gate removal). Check results:
   ```sql
   SELECT sbp.player_name, sbp.recommendation, sbp.edge, pa.prediction_correct
   FROM `nba-props-platform.nba_predictions.signal_best_bets_picks` sbp
   LEFT JOIN `nba-props-platform.nba_predictions.prediction_accuracy` pa
     ON sbp.game_id = pa.game_id AND sbp.player_lookup = pa.player_lookup
     AND sbp.system_id = pa.system_id
   WHERE sbp.game_date = '2026-02-26'
   ```

3. **Monitor AWAY noveg filter impact.** Session 347 added a negative filter blocking v12_noveg AWAY predictions (43-44% HR vs 57-59% HOME). Check filter summary in next day's export logs to see how many picks it blocks.

4. **Grade shadow models if 3+ days available** (expected Mar 1-3):
   ```sql
   SELECT system_id,
          CASE WHEN predicted_points < line_value THEN 'UNDER' ELSE 'OVER' END as direction,
          COUNT(*) as picks, COUNTIF(prediction_correct) as wins,
          COUNTIF(prediction_correct IS NOT NULL) as graded,
          ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct), COUNTIF(prediction_correct IS NOT NULL)) * 100, 1) as hr
   FROM `nba-props-platform.nba_predictions.prediction_accuracy`
   WHERE game_date >= '2026-02-27'
     AND system_id IN ('catboost_v12_noveg_q55_train1225_0209', 'catboost_v9_low_vegas_train1225_0209',
                        'catboost_v12_noveg_q55_tw_train1225_0209', 'catboost_v12_noveg_q57_train1225_0209')
     AND prediction_correct IS NOT NULL
   GROUP BY 1, 2
   ```

5. **Investigate shadow model low coverage.** `*_train1225_0209` models only produced 6 predictions vs 117 for main models on Feb 26. These are the best-performing shadow models — investigate why coverage is so low.

6. **Run /daily-steering** and check deployment drift.

Key context from Session 347:
- Health gate removed from signal best bets exporter (was blocking all profitable picks).
- AWAY noveg negative filter added to aggregator (blocks v12_noveg AWAY predictions).
- Investigation 3 completed: UNDER bias is structural/stable, HOME/AWAY gap is +15pp for noveg, Stars UNDER is broken across all models, B2B hurts v12 UNDER.
- Investigation 2 confirmed: ~14-day shelf life for full-Vegas, ~21 days for low/no-Vegas.
- Shadow models first predictions expected Feb 27 (bug fix deployed Feb 26).
- All models still BLOCKED/DEGRADING but edge 5+ filter chain keeps best bets profitable at 63%+ HR.
