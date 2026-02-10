Read docs/09-handoff/2026-02-10-SESSION-176-HANDOFF.md and work through the priority items:

- P0: Verify Feb 10 FIRST-run predictions. Check avg_pvl within +/-1.5, OVER% >25%, zero RECOMMENDATION_DIRECTION_MISMATCH in logs. Also check for new ODDS_API_COVERAGE and NO_LINE_DIAGNOSTIC messages in prediction-worker/coordinator Cloud Run logs — these are new Session 175 diagnostics appearing for the first time.
- P1: Check if Feb 9 games are Final (status=3) and grade them. 10 games were played on Feb 9. Trigger grading via `gcloud pubsub topics publish nba-grading-trigger --message='{"target_date":"2026-02-09","trigger_source":"manual"}' --project=nba-props-platform`.
- P2: Model retrain with extended data. Model decay confirmed: edge 3+ hit rate dropped from 71.2% (Jan 12 week) to 47.3% (Feb 2 week). Both OVER and UNDER directions are underperforming equally — this is core model decay, not directional bias. Use /model-experiment to retrain with `--train-start 2025-11-02 --train-end 2026-01-31 --walkforward`. Follow all governance gates. Do NOT deploy without explicit approval.
- P3: Verify `prediction_regeneration_audit` table has data after the next regeneration event. It was empty due to a JSON type mismatch bug fixed in Session 176.
- P4: Check OddsAPI diagnostic logs after Feb 10 run. Search Cloud Run logs for ODDS_API_COVERAGE and NO_LINE_DIAGNOSTIC to understand whether low line coverage is "no data scraped" vs "player name mismatch".

Use agents in parallel where possible. Commit and push when done — Cloud Build auto-deploys on push to main.
