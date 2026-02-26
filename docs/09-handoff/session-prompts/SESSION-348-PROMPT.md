# Session 348 Prompt

Copy/paste this to start the next session:

---

Start with the Session 347 handoff at docs/09-handoff/2026-02-26-SESSION-347-HANDOFF.md and the evaluation plan at docs/08-projects/current/model-system-evaluation-session-343/00-EVALUATION-PLAN.md.

Session 347 accomplished: health gate removal, AWAY noveg negative filter, best bets grading backfill (68.6% HR on 105 graded picks), shadow model coverage diagnosis (deploy timing — self-resolving).

Work through these priorities:

1. **Grade Feb 26 best bets.** 5 picks were exported (first since health gate removal). Check results:
   ```sql
   SELECT sbp.player_name, sbp.recommendation, sbp.edge, sbp.line_value,
          pa.prediction_correct, pa.actual_points
   FROM `nba-props-platform.nba_predictions.signal_best_bets_picks` sbp
   LEFT JOIN `nba-props-platform.nba_predictions.prediction_accuracy` pa
     ON sbp.game_id = pa.game_id AND sbp.player_lookup = pa.player_lookup
     AND sbp.system_id = pa.system_id
   WHERE sbp.game_date = '2026-02-26'
   ```

2. **Verify shadow models at full coverage.** Feb 27 should show ~117 predictions per shadow model (was 6 on Feb 26 due to deploy timing). Check:
   ```sql
   SELECT system_id, COUNT(*) as predictions
   FROM `nba-props-platform.nba_predictions.player_prop_predictions`
   WHERE game_date = '2026-02-27'
   GROUP BY 1 ORDER BY 2 DESC
   ```
   If still low, investigate `_prepare_v12_feature_vector()` failures in worker logs.

3. **Grade shadow models if 3+ days available** (expected Mar 1-3):
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

4. **Fix pubsub_v1 import error.** `post-grading-export` CF steps 6-8 crash with `cannot import name 'pubsub_v1' from 'google.cloud'`. Check if `google-cloud-pubsub` is in the CF's requirements.txt. This breaks re-export of tonight/all-players.json, best-bets/all.json, and record.json after grading.

5. **Run /daily-steering** and check deployment drift.

Key context from Session 347:
- Health gate removed — best bets flow even when model HR < breakeven. Filter pipeline is the real quality control.
- AWAY noveg filter deployed — blocks v12_noveg AWAY predictions (43-44% HR vs 57-59% HOME).
- Best bets grading fixed via one-time BQ backfill. 105/117 picks graded at 68.6% HR (72-33).
- Shadow model 6/117 coverage was deploy timing — should self-resolve Feb 27.
- Investigation 3 completed: bias is structural (don't fix it), HOME/AWAY is +15pp for noveg, Stars UNDER broken, B2B hurts V12 only.
- All models BLOCKED/DEGRADING but edge 5+ filter chain keeps best bets profitable.
