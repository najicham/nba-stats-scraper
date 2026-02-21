# Session 312B Handoff — Frontend Pipeline Issues

**Date:** 2026-02-20
**Status:** Investigation needed
**Priority:** High — frontend showing stale/missing data to users

## Context

Session 312 implemented best bets frontend communication improvements (filter_summary, edge_distribution, status.json best_bets service). During validation, the frontend team reported three issues with the GCS-exported JSON files that power the website.

**Key distinction:** BigQuery has correct data. The issue is that the GCS JSON exports (which the frontend reads) are stale or incomplete.

## Issue 1: Live Grading Export Not Populating Actuals

**Symptom:** `v1/live-grading/2026-02-19.json` has `generated_at: null`, all 81 predictions show `game_status: "scheduled"`, 0 actuals populated. The frontend sees yesterday's games as ungraded.

**Reality in BigQuery:** `prediction_accuracy` has 1,011 graded records for Feb 19 at 100% coverage. The data is fully graded in BQ — the export just didn't pick it up.

**Investigation so far:**
- Post-game marker exists: `v1/live/post-game-2026-02-19.done` (created 05:00 UTC Feb 20)
- The `2026-02-19.json` file was written at 06:57 UTC Feb 20 but still has no actuals
- Live grading exporter uses `_fetch_bigquery_scores()` which queries `nba_analytics.player_game_summary` with `game_status = 3`
- BDL API is disabled, so only BQ scores path is active

**Key files:**
- `data_processors/publishing/live_grading_exporter.py` — main exporter
  - `_fetch_bigquery_scores()` (lines ~454-550) — gets actual scores from player_game_summary
  - `_grade_predictions()` (lines ~590-709) — compares predicted vs actual
  - `generate_json()` (lines ~96-156) — orchestrates the export
- `orchestration/cloud_functions/live_export/main.py` — trigger logic, post-game re-export

**What to check:**
1. Does `player_game_summary` for Feb 19 have `game_status = 3` for all games? Maybe the game_status wasn't updated when the export ran.
2. Is there a join key mismatch between what the exporter queries and what's in `player_game_summary`?
3. Look at Cloud Function logs: `gcloud functions logs read live-export --region=us-west2 --limit=50 --start-time=2026-02-20T04:00:00Z`
4. The `generated_at: null` is suspicious — suggests the export ran but the score-fetching code path was skipped entirely.

**Quick fix to try:** Manually trigger the live-grading export for Feb 19:
```bash
# Check if there's a backfill script
python backfill_jobs/publishing/daily_export.py --date 2026-02-19 --types live-grading
```

## Issue 2: `systems/subsets.json` Stale Since Feb 13

**Symptom:** `v1/systems/subsets.json` was last updated Feb 13 (`generated_at: 2026-02-13T10:00:20`). Only shows 3 model groups: phoenix, aurora, summit. New models (catboost_v9_q43, catboost_v9_q45) are missing.

**Note:** `systems/performance.json` IS being updated (latest: Feb 20 at 10:00 UTC). So the `phase6-daily-results` scheduler is working, but the subset definitions export specifically stopped.

**Investigation so far:**
- `phase6-daily-results` scheduler job is ENABLED, runs at `0 5 * * *` (5 AM ET)
- Feb 13 was during the All-Star break. The exporter may have an early return for "no predictions" that prevents regenerating the file.
- The `SubsetDefinitionsExporter` reads from `dynamic_subset_definitions` table where `is_active = TRUE`

**Key files:**
- `data_processors/publishing/subset_definitions_exporter.py` — the exporter
  - `generate_json()` (lines ~51-97) — queries active subsets and groups by model
  - Uses `shared.config.model_codenames` for display names
  - Uses `shared.config.subset_public_names` for public subset names
- `shared/config/cross_model_subsets.py` — dynamic model discovery
  - `MODEL_FAMILIES` dict (lines ~28-74) — pattern-based classification
  - `classify_system_id()` (lines ~77-97) — maps system_id to family
- The daily export orchestrator that calls this exporter (check `backfill_jobs/publishing/daily_export.py`)

**What to check:**
1. Read `subset_definitions_exporter.py` for any early return that skips writing during breaks
2. Check Cloud Function logs for the phase6-export function around 5 AM ET
3. Manually run the export to see if it works: check if there's a CLI or backfill entry point
4. Verify `dynamic_subset_definitions` has entries for the q43/q45 models

**Quick fix:** Manually trigger the subset definitions export. If it works, the issue is just the break-period skip logic.

## Issue 3: New Model Groups Not in `subsets.json`

**Symptom:** Frontend sees predictions from `catboost_v9_q43_train1102_0125` and `catboost_v9_q45_train1102_0125` but these don't have display names in `systems/subsets.json`.

**Root cause:** This is a downstream effect of Issue 2. Once `subsets.json` regenerates, the `SubsetDefinitionsExporter` should auto-discover these models via:
1. `dynamic_subset_definitions` table (if entries exist)
2. `cross_model_subsets.py` model family classification

**What to verify:**
```sql
-- Check if q43/q45 have subset definitions
SELECT subset_id, system_id, is_active, subset_name
FROM nba_predictions.dynamic_subset_definitions
WHERE system_id LIKE '%q43%' OR system_id LIKE '%q45%'
ORDER BY system_id, subset_id
```

If no rows exist, the subset materializer needs to create definitions for these models.

## Pipeline Architecture Reference

```
BigQuery (source of truth)
  → Phase 6 Exporters (Python)
    → GCS JSON files (v1/*)
      → Frontend reads these
```

**Scheduler:** `phase6-daily-results` at 5 AM ET triggers Pub/Sub → `phase6-export` Cloud Function
**Live:** `live-export-evening` every 3 min 4-11 PM ET triggers HTTP → `live-export` Cloud Function

## Session 312 Changes (already committed, not yet deployed)

The following changes from Session 312 are on `main` but not yet pushed/deployed:
- `ml/signals/aggregator.py` — returns `(picks, filter_summary)` tuple now
- `data_processors/publishing/signal_best_bets_exporter.py` — metadata on 0-pick days, filter_summary, edge_distribution
- `data_processors/publishing/status_exporter.py` — best_bets service in status.json
- Updated callers: `steering_replay.py`, `signal_annotator.py`, `signal_backtest.py`, `signal_backfill.py`
- Updated tests: `test_player_blacklist.py`, new `test_aggregator.py`, new `test_signal_best_bets_exporter.py`

These changes need to be committed and pushed to trigger auto-deploy. They are safe — 56 tests passing (1 pre-existing failure: stale `ALGORITHM_VERSION` assertion in `test_player_blacklist.py`).

## Recommended Approach

1. **Push Session 312 changes first** (commit + push to main → auto-deploy)
2. **Fix Issue 2** (subsets.json) — likely quickest, probably just needs a manual re-export or fix to break-period skip logic
3. **Fix Issue 1** (live grading) — investigate why actuals aren't populating, check CF logs
4. **Issue 3 resolves itself** once Issue 2 is fixed
