# Session 169 Prompt

Copy everything below this line into a new chat:

---

Session 169 — Model UNDER Bias Crisis + Stale Model Cleanup

Read the handoff: `docs/09-handoff/2026-02-09-SESSION-168-HANDOFF.md`

Context: Session 168 completed Feb 5-7 backfill, deployed three bug fixes (supersede, vegas null-out, PRE_GAME mode mapping — commit `ea75d1c7`), and conducted a deep performance investigation. We found:

1. **URGENT: Model UNDER bias is accelerating.** Today (Feb 9) the production model's avg_pvl = -3.84 (predicts 4-10 pts below Vegas for star players). This is NOT a bug — the fixes are deployed and predictions have real Vegas lines. The bias worsened weekly: +1.29 → -0.07 → -0.26 → -0.94 → -3.84 from Jan 12 to Feb 9. The model is not usable for new picks.

2. **Stale model predictions polluting the database.** Under `system_id = 'catboost_v9'`, there are 269 active predictions from `v9_current_season` (wrong model era) and 17 from `v9_36features_20260108_212239` (wrong model file). These LEAK INTO SUBSETS because subsets filter by system_id but not model_version. Additionally, 823 active `catboost_v9_2026_02` predictions (the broken Session 163 retrain) need deactivation. SQL cleanup queries are in the handoff.

3. **Broken monthly model still config-enabled.** `predictions/worker/prediction_systems/catboost_monthly.py` line 55 has `catboost_v9_2026_02` with `"enabled": True`. The local model file was deleted in Session 167 but the config wasn't updated.

What needs to be done (in order):

1. **P0: Investigate UNDER bias root cause** — Compare feature distributions for today vs Jan 12 (peak performance). Check if Phase 4 precompute or feature store values have shifted. Determine if this is feature drift, data pipeline changes, or model decay 32 days past training end (Nov 2 - Jan 8). Check if last season's V8 had this issue at the same point.

2. **P1: Clean up stale predictions** — Run the BQ UPDATE queries from the handoff to deactivate v9_current_season (269), v9_36features (17), and catboost_v9_2026_02 (823).

3. **P2: Disable broken monthly model** — Set `"enabled": False` in catboost_monthly.py line 55. Commit and push.

4. **P3: Re-backfill Feb 4** — After stale cleanup, Feb 4 has 0 active catboost_v9 predictions. Trigger BACKFILL, re-grade, re-materialize subsets.

5. **P4: Decide on model action** — Options: (a) pause predictions until bias is fixed, (b) apply temporary bias correction offset, (c) retrain with extended data through Jan 31, (d) investigate if the pre-ASB scoring bump (confirmed +0.33-0.55 PPG across 4 seasons) is the primary driver.

Questions to answer:
- Why does the UNDER bias accelerate? Is it feature drift or model decay?
- Should we pause today's predictions given -3.84 avg_pvl?
- Are the non-catboost models (ensemble, moving_average, zone_matchup, similarity) useful or should they be disabled?
- Should subsets add a model_version filter to prevent future leaks?
