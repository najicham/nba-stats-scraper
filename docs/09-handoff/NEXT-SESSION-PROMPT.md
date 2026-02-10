Read docs/09-handoff/2026-02-10-SESSION-179-HANDOFF.md and work through priorities:

- P0: **Grade Feb 9.** Session 179 backfilled all 3 challengers (59 each) but grading was blocked — raw data hadn't been scraped yet. Verify raw data exists now: `bq query --use_legacy_sql=false "SELECT COUNT(*) FROM nba_raw.nbac_gamebook_player_stats WHERE game_date='2026-02-09'"`. If >0, trigger grading: `gcloud pubsub topics publish nba-grading-trigger --message='{"target_date":"2026-02-09","trigger_source":"manual"}' --project=nba-props-platform`. Then run 4-way comparison with the extra day.

- P1: **Verify Feb 10 live predictions** — first overnight run with Jan 31 challengers deployed. Check all 4 models have predictions: `SELECT system_id, COUNT(*) FROM nba_predictions.player_prop_predictions WHERE game_date='2026-02-10' AND system_id LIKE 'catboost_v9%' GROUP BY 1`. If only champion appears, check prediction-worker logs for challenger errors.

- P2: **Grade Feb 10** once games complete. Backfill all 3 challengers for Feb 10:
  ```
  PYTHONPATH=. python bin/backfill-challenger-predictions.py --model catboost_v9_train1102_0108 --start 2026-02-10 --end 2026-02-10
  PYTHONPATH=. python bin/backfill-challenger-predictions.py --model catboost_v9_train1102_0131 --start 2026-02-10 --end 2026-02-10
  PYTHONPATH=. python bin/backfill-challenger-predictions.py --model catboost_v9_train1102_0131_tuned --start 2026-02-10 --end 2026-02-10
  ```
  Trigger grading and re-run comparison.

- P3: **Monitor promotion readiness.** Champion is below breakeven (49.1% overall, 47.9% edge 3+). Jan 31 defaults leads at 54.8% HR with nearly perfect Vegas bias (+0.01). When they disagree (n=257), Jan 31 wins 55.3% vs champion's 39.0%. BUT Jan 31 only has 5 days of data — need ~2 more weeks. Key metric to track: Jan 31 defaults sustained HR above 53%.

Session 179 context:
- Pushed Session 178 commits, deployed prediction-worker with Jan 31 challengers (verified commit c76ecb7)
- Backfilled 59 predictions each for all 3 challengers for Feb 9 (grading blocked, awaiting pipeline)
- 4-way matched comparison (Feb 4-8, n=449): Champion 49.8%, Jan 8 52.1%, Jan 31 defaults **54.8%**, Jan 31 tuned 53.9%
- Disagreement analysis: when models disagree (n=257), Jan 31 defaults wins by +16.3pp
- Champion weekly decay: 71.2% -> 67.0% -> 56.0% -> 47.9% edge 3+ HR over 4 weeks
- Jan 31 models have tight predictions (stddev ~1.0 vs champion 2.23) — few edge 3+ picks. If promoted, subset thresholds and signal system need recalibration.
- Subset analysis: only "Green Light" had enough picks (58.4% HR, n=197). Signal effectiveness degrading.

Use agents in parallel where possible.
