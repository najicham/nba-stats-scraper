Read docs/09-handoff/2026-02-10-SESSION-180-HANDOFF.md and work through priorities:

- P0: **Re-trigger Feb 10 predictions.** Session 180 attempted but 0 prop lines were available (1:30 AM ET). Check if lines exist now: `bq query --use_legacy_sql=false "SELECT COUNT(*) FROM nba_raw.odds_api_player_points_props WHERE game_date='2026-02-10'"`. If >0, trigger predictions and backfill all 3 challengers. Feature store already has 79 records ready.

- P1: **Grade Feb 10 once games complete.** Backfill challengers:
  ```
  PYTHONPATH=. python bin/backfill-challenger-predictions.py --model catboost_v9_train1102_0108 --start 2026-02-10 --end 2026-02-10
  PYTHONPATH=. python bin/backfill-challenger-predictions.py --model catboost_v9_train1102_0131 --start 2026-02-10 --end 2026-02-10
  PYTHONPATH=. python bin/backfill-challenger-predictions.py --model catboost_v9_train1102_0131_tuned --start 2026-02-10 --end 2026-02-10
  ```
  Trigger grading, re-run comparison.

- P2: **Run experiment sweep from Session 179B.** The A1 Vegas Weight Sweep (6 experiments) is ready to go — commands in `docs/09-handoff/2026-02-09-SESSION-179B-HANDOFF.md` P0 section. Use `--train-start 2025-11-02 --train-end 2026-01-31 --eval-start 2026-02-01 --eval-end 2026-02-08 --walkforward --force`.

- P3: **Monitor promotion readiness.** Jan 31 tuned now leads at 55.1% HR (n=301, 6 days), strongest disagreement signal (+24pp vs champion). Champion at 49.5% and decaying. Need ~2 more weeks. Key question: does tuned sustain its lead over defaults?

Session 180 context:
- Graded Feb 9 using nbac_player_boxscores fallback (gamebook scraper hadn't fired yet at session time)
- Manually triggered Phase 3 for Feb 9 (209 records), then grading — all 4 models graded
- 4-way matched comparison (Feb 4-9, n=301 actionable): Champion 49.5%, Jan 8 50.5%, Jan 31 defaults 54.2%, **Jan 31 tuned 55.1%**
- Tuned's disagreement signal: 62% vs champion's 38% when they disagree (n=71, +24pp gap)
- Defaults' disagreement signal: 58.3% vs champion's 41.7% (n=84, +16.6pp gap)
- Feb 9 was a bad day for defaults (42.3%) but tuned held up (48.1%)
- Champion producing fewer actionable picks (33-63/day vs challengers 52-131)
- No gamebook scraper gap — it runs at 4 AM ET, session was 1:30 AM ET

Use agents in parallel where possible.
