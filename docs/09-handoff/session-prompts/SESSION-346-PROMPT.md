# Session 346 Prompt

Copy/paste this to start the next session:

---

Start with the Session 345 handoff at docs/09-handoff/2026-02-25-SESSION-345-HANDOFF.md and the evaluation plan at docs/08-projects/current/model-system-evaluation-session-343/00-EVALUATION-PLAN.md (scroll to "What's Next" checklist at the bottom).

Work through these priorities:

1. **Verify zombie cleanup worked.** Check today's predictions — should see ~9 system_ids (down from 22). Confirm all 4 shadow models are generating predictions:
   - catboost_v12_noveg_q55_train1225_0209
   - catboost_v12_noveg_q55_tw_train1225_0209
   - catboost_v12_noveg_q57_train1225_0209
   - catboost_v9_low_vegas_train1225_0209
   If any shadow model is missing from predictions, investigate the prediction worker logs.

2. **Run /daily-steering** and check deployment drift. The export freshness monitor was deployed to daily-health-check CF last session — check if it ran correctly at 8 AM ET by reviewing the Cloud Function logs.

3. **If shadow models have 2+ days of grading data**, check their live performance:
   ```sql
   SELECT system_id,
          CASE WHEN predicted_points < line_value THEN 'UNDER' ELSE 'OVER' END as direction,
          COUNT(*) as picks, COUNTIF(prediction_correct) as wins,
          ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct), COUNTIF(prediction_correct IS NOT NULL)) * 100, 1) as hr
   FROM `nba-props-platform.nba_predictions.prediction_accuracy`
   WHERE game_date >= '2026-02-26'
     AND system_id IN ('catboost_v12_noveg_q55_train1225_0209', 'catboost_v9_low_vegas_train1225_0209',
                        'catboost_v12_noveg_q55_tw_train1225_0209', 'catboost_v12_noveg_q57_train1225_0209')
     AND prediction_correct IS NOT NULL
   GROUP BY 1, 2
   ```
   Compare against offline eval expectations: Q55+trend_wt should be best overall (58.6% edge 3+ offline), Q57 should be UNDER specialist (62.5% UNDER offline).

4. **If grading data is insufficient** (< 2 days), skip to Investigation 2: Model Decay Timeline. Query 7-day rolling HR by model family, starting from each model's training end date, to confirm the ~21-day shelf life hypothesis and set retrain cadence.

5. **Update best bets attribution** with fresh data — re-run the Investigation 1 query from Session 345 to see if new families are sourcing picks now that shadows are active:
   ```sql
   SELECT source_model_family, recommendation as direction,
          COUNT(*) as picks, COUNTIF(pa.prediction_correct) as wins,
          COUNTIF(pa.prediction_correct IS NOT NULL) as graded,
          ROUND(SAFE_DIVIDE(COUNTIF(pa.prediction_correct), COUNTIF(pa.prediction_correct IS NOT NULL)) * 100, 1) as hr
   FROM `nba-props-platform.nba_predictions.signal_best_bets_picks` sbp
   JOIN `nba-props-platform.nba_predictions.prediction_accuracy` pa
     ON sbp.game_date = pa.game_date AND sbp.game_id = pa.game_id
     AND sbp.system_id = pa.system_id AND sbp.player_lookup = pa.player_lookup
   WHERE sbp.game_date >= '2026-01-01'
   GROUP BY 1, 2 ORDER BY graded DESC
   ```

Key context from Session 345:
- Best bets overall: 68.9% HR (106 graded). v12_mae OVER = 90% (crown jewel). v12_mae UNDER = 53.3% (weakest).
- Fresh window experiment: Q55+trend_wt edge 5+ = 66.7% (stable across windows). Stars UNDER = 0% (vulnerability).
- Model-direction affinity is dynamic (queries BQ at runtime, blocks < 45% HR) — no manual intervention needed for v12_mae UNDER.
- Export freshness monitor now live in daily-health-check CF.
