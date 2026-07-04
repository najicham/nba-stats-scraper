# nba-monitoring-alerts

Cloud Function (gen2, HTTP) that runs a set of sanity checks on the NBA prediction
system every 4 hours (Cloud Scheduler job `nba-monitoring-alerts`, `0 */4 * * *`).
Built to prevent recurrence of the CatBoost V8 Jan 2026 incident.

## Checks (`run_all_checks`)
- `player_daily_cache_freshness` — cache updated within 24h + ≥50 players.
- `feature_quality` — `ml_feature_store_v2` avg/min quality + phase4_partial share.
- `confidence_distribution` — confidence clustering / low variety. **STALE** (see below).
- `prediction_accuracy` — avg error + win rate. **STALE** (see below).
- `model_loading` — prediction-worker log scan for model-load failures.

## History
- **2026-07-04 — source exhumed + versioned.** The deployed code previously existed
  ONLY inside an incident-doc markdown heredoc (never in the repo), so it was invisible
  to the syntax/schema pre-commit hooks and could break silently. Pulled from the
  deployed `function-source.zip` (generation `1768621716807390`) and committed here.
- **2026-07-04 — fixed two BigQuery errors that were logging every 4h, 24/7:**
  1. `feature_quality`: `ml_nba.ml_feature_store_v2` → `nba_predictions.ml_feature_store_v2`
     (the `ml_nba` dataset does not exist).
  2. `prediction_accuracy`: `is_correct` → `prediction_correct` (correct graded column).
  Both corrected queries were dry-run-validated against the live schema.
- **2026-07-04 — two further errors found while verifying a clean run** (the review's log
  sample had only caught the two above):
  3. `feature_quality`: `COUNTIF(...) / COUNT(*)` was `0/0` (division-by-zero) with no rows
     today, and the NULL aggregate row would fire a false "quality degraded" alert →
     `SAFE_DIVIDE` + a `total_rows == 0 → NO_DATA` guard.
  4. `model_loading`: the Cloud Logging `timestamp>"..."` filter used a naive isoformat
     with no timezone (rejected as "incorrect type") → append `Z` (UTC).
  Verified end-to-end: all 5 checks now run with zero errors (revision 00006).

## Known staleness (season-open follow-up)
`confidence_distribution` and `prediction_accuracy` target `TARGET_SYSTEM_ID`, which defaults
to the retired `catboost_v8` (override with env `MONITOR_SYSTEM_ID`). The fleet is now 10+
shadow models with no single champion, so with the default these two checks return `NO_DATA`
and monitor nothing. They no longer ERROR (that was the bleeding fixed above). At season open,
set `MONITOR_SYSTEM_ID` to an active model or make the checks fleet-wide. (Parameterized rather
than hardcoded so the `validate-model-references` pre-commit hook passes.)

## Deploy
```bash
./deploy.sh   # gen2, python311, entry run_all_checks, preserves existing env vars
```
The scheduler already exists and is not modified by the deploy.
