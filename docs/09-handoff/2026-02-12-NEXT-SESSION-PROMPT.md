# Session Start Prompt — 2026-02-13

Read the Session 217 handoff doc and pick up where we left off:

```
cat docs/09-handoff/2026-02-12-SESSION-217-HANDOFF.md
```

## Immediate tasks:

1. **Fix live-export Cloud Build trigger** — It fails on every push with "Function already exists in 1st gen, can't change the environment." The `deploy-live-export` trigger uses `cloudbuild-functions.yaml` which passes `--gen2`, but `live-export` is Gen1. Fix: either migrate to Gen2 or recreate trigger without `--gen2`.

2. **Verify bigquery-daily-backup ran** — We fixed gsutil→gcloud storage and deployed yesterday. Check if the 2 AM backup succeeded:
   ```bash
   gcloud scheduler jobs describe bigquery-daily-backup --location=us-west2 --project=nba-props-platform --format="yaml(status,lastAttemptTime)"
   ```

3. **Q43 shadow model check** — Champion is 33+ days stale, Q43 has 29/50 edge 3+ picks at 48.3% HR with 100% UNDER bias. Check if we've crossed 50 picks for promotion decision:
   ```bash
   PYTHONPATH=. python bin/compare-model-performance.py catboost_v9_q43_train1102_0131 --days 14
   ```

4. **Run daily validation** — `/validate-daily` — test the 3 new phases added in Session 217 (0.477 boxscore fallback, 0.478 Phase 3→4 format, 0.71 enrichment health).

5. **Monthly retrain consideration** — Champion trained Nov 2-Jan 8, now 35+ days stale. If Q43 isn't promoting, consider a fresh retrain with data through Feb.
