# Session 234 Start Prompt

Read the handoff doc at `docs/09-handoff/2026-02-13-SESSION-233-HANDOFF.md`.

Session 233 fixed a live-export timeout bug and backfilled grading for Feb 7-12. All committed and deployed. It's All-Star break (no games today).

Pick up with these priorities:

1. **Deploy `phase5b-grading`** — it's stale, missing commit `8454ccb4` (remove minimum prediction threshold from grading). Must be deployed before games resume. Also deploy `nba-grading-service` (4 commits behind).

2. **Champion model retrain** — the champion has decayed to 40-47% edge 3+ HR (well below 52.4% breakeven, 36 days stale). The All-Star break is a natural window for retraining. Run: `PYTHONPATH=. python ml/experiments/quick_retrain.py --name "V9_FEB_RETRAIN" --train-start 2025-11-02 --train-end 2026-02-12`. If gates pass, register in shadow mode and monitor when games resume.

3. **Check when games resume** and verify pipeline is ready: `bq query --use_legacy_sql=false "SELECT game_date, COUNT(*) as games FROM nba_reference.nba_schedule WHERE game_date > CURRENT_DATE() AND game_date <= CURRENT_DATE() + 7 GROUP BY 1 ORDER BY 1"`
