Read docs/09-handoff/2026-02-10-SESSION-178-HANDOFF.md and work through priorities:

- P0: **Push and deploy.** Session 178 committed but did NOT push. Run `git push origin main` to trigger auto-deploy of prediction-worker with the new Jan 31 challenger models. Verify Cloud Build triggers fired: `gcloud builds list --region=us-west2 --project=nba-props-platform --limit=5`

- P1: **Grade Feb 9 games** if completed (check `game_status=3`). Then backfill all 3 challengers for Feb 9:
  ```
  PYTHONPATH=. python bin/backfill-challenger-predictions.py --model catboost_v9_train1102_0108 --start 2026-02-09 --end 2026-02-09
  PYTHONPATH=. python bin/backfill-challenger-predictions.py --model catboost_v9_train1102_0131 --start 2026-02-09 --end 2026-02-09
  PYTHONPATH=. python bin/backfill-challenger-predictions.py --model catboost_v9_train1102_0131_tuned --start 2026-02-09 --end 2026-02-09
  ```
  Then trigger grading for Feb 9 and re-run the 4-way comparison with the extra day of data.

- P2: **Verify Feb 10 live predictions** — first overnight run with Jan 31 challengers deployed. Check all 4 models have predictions: `SELECT system_id, COUNT(*) FROM nba_predictions.player_prop_predictions WHERE game_date='2026-02-10' AND system_id LIKE 'catboost_v9%' GROUP BY 1`. Verify champion looks normal (avg_pvl within +/-1.5, OVER% >25%).

- P3: **Run subset analysis** on backfilled predictions — compare all models across dynamic subsets. This was not done in Session 178.

- P4: **Monitor model decay vs challengers.** Champion hit rate dropped from 71.2% → 47.3% over 4 weeks. The Jan 31 models showed 56-57% HR on Feb 4-8 matched pairs. If they sustain this in live predictions, champion promotion should be considered urgently.

Session 178 context:
- Retired 2 contaminated _0208 models (trained Nov 2 - Feb 8, backtest had 31-day train/eval overlap)
- Trained 2 new Jan 31 models: _0131 (defaults, depth=6/l2=3/lr=0.05) and _0131_tuned (depth=5/l2=5/lr=0.03 + recency 30d)
- Both uploaded to GCS, added to MONTHLY_MODELS config, backfilled 466 predictions each for Feb 4-8, graded (449 each)
- 4-way head-to-head (Feb 4-8, n=269 matched): Champion 49.8%, Jan 8 50.9%, Jan 31 defaults 56.1%, Jan 31 tuned 56.9%
- Jan 8 challenger (_0108) head-to-head (Jan 9-Feb 8, n=1457 matched): +1.7pp HR, -0.32 MAE, wins 54% of disagreements
- compare-model-performance.py bug fixed (edge → predicted_margin)
- Jan 12 anomaly resolved (legitimate OVER day, not data issue)
- CLAUDE.md and project docs updated with all results

Use agents in parallel where possible.
