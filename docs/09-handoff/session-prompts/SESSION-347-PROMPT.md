# Session 347 Prompt

Copy/paste this to start the next session:

---

Start with the Session 346 handoff at docs/09-handoff/2026-02-26-SESSION-346-HANDOFF.md and the evaluation plan at docs/08-projects/current/model-system-evaluation-session-343/00-EVALUATION-PLAN.md.

Work through these priorities:

1. **Verify shadow models are generating predictions.** Session 346 fixed a bug where shadow models with `status='shadow'` weren't loaded by the prediction worker. The fix was deployed Feb 26. Check Feb 27+ predictions:
   ```sql
   SELECT DISTINCT system_id
   FROM `nba-props-platform.nba_predictions.player_prop_predictions`
   WHERE game_date >= '2026-02-27'
   ORDER BY system_id
   ```
   Should see ~9-10 system_ids including: `catboost_v12_noveg_q55_train1225_0209`, `catboost_v12_noveg_q55_tw_train1225_0209`, `catboost_v12_noveg_q57_train1225_0209`, `catboost_v9_low_vegas_train1225_0209`.

2. **Run /daily-steering** and check deployment drift.

3. **If shadow models have 3+ days of grading data** (expected Mar 2-4), grade them:
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
   Compare: Q55+trend_wt should be best overall (58.6% edge 3+ offline), Q57 should be UNDER specialist (62.5% UNDER offline).

4. **If grading data is sufficient**, evaluate promotion path for the best shadow model. If not, continue to Investigation 3 (direction bias deep dive).

5. **Investigation 3: Direction Bias Deep Dive** — track weekly `avg(predicted - line_value)` per family, segment by player tier (stars/starters/role players), home/away, b2b. Identify which game contexts worsen UNDER bias.

Key context from Session 346:
- Shadow model bug fixed: `status IN ('active', 'shadow')` instead of `status = 'active'`.
- Investigation 2 confirmed: ~14-day shelf life for full-Vegas models, ~21 days for low/no-Vegas. Retrain cadence should be 14 days.
- Best bets overall: 63.6% HR 30d (28-16). v12_mae OVER 90% is crown jewel. v12_mae UNDER 53.3% is weak link.
- All models BLOCKED/DEGRADING but edge 5+ filter chain keeps best bets profitable.
