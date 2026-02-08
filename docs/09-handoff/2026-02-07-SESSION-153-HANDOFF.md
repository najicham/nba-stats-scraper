# Session 153 Handoff — Materialize Subsets + Subset Grading

**Date:** 2026-02-07
**Commit:** NOT YET COMMITTED — all changes are local, uncommitted
**Status:** Code written, needs review before commit/deploy

## Problem Statement

Subsets were computed on-the-fly during GCS export (`AllSubsetsPicksExporter`). This meant:
1. **No queryable entity** — subsets didn't exist in BigQuery, only in exported JSON files
2. **No proper grading** — the `v_dynamic_subset_performance` view recomputes subset membership retroactively using *current* definitions, grading what the subset *would have been*, not what it *actually was*
3. **No history** — if picks changed throughout the day (early predictions → overnight → line checks), only the latest export mattered

## What Was Built

### 1. `current_subset_picks` Table — Materialized Subsets (NEW)

**File:** `schemas/bigquery/predictions/06_current_subset_picks.sql`

Append-only table. Every time predictions are generated and subsets are computed, a new set of rows is inserted with a unique `version_id`. No UPDATEs ever (avoids BigQuery 90-min DML partition locks).

**Design:** Predictions regenerate 4-6x/day (2:30 AM early, 7 AM overnight, 10 AM retry, hourly line checks, 4 PM last call). Each triggers materialization → new version. Old versions preserved for history.

**Consumers pick their own version:**
- **Exporter (latest):** `WHERE version_id = (SELECT MAX(version_id) ...)`
- **Grader (pre-tip):** `WHERE version_id = (SELECT MAX(version_id) ... AND computed_at < first_tip_time)`
- **History:** All versions queryable for time-series analysis

**Rich provenance per pick:**
- `feature_quality_score`, `default_feature_count`, `line_source`, `prediction_run_mode`, `prediction_made_before_game`, `quality_alert_level`

**Version-level context:**
- `daily_signal` (GREEN/YELLOW/RED), `pct_over`, `total_predictions_available`

### 2. `SubsetMaterializer` — Compute + Write Subsets (NEW)

**File:** `data_processors/publishing/subset_materializer.py`

Extracted filtering logic from `AllSubsetsPicksExporter`. Loads definitions, loads predictions with full provenance, applies subset filters, writes to BQ. Append-only — no deletes, no updates.

### 3. `AllSubsetsPicksExporter` — Now Reads from Materialized Table (MODIFIED)

**File:** `data_processors/publishing/all_subsets_picks_exporter.py`

- Reads from `current_subset_picks` (latest version) first
- Falls back to on-the-fly computation if no materialized data exists (old dates, table doesn't exist yet)
- Removed `_record_snapshot()` (superseded by materializer)
- Removed `json` and `uuid` imports (no longer needed)

### 4. Daily Export Wiring (MODIFIED)

**File:** `backfill_jobs/publishing/daily_export.py`

When `subset-picks` is in export types, calls `SubsetMaterializer.materialize()` first (non-fatal), then `AllSubsetsPicksExporter.export()`.

### 5. `subset_grading_results` Table (NEW)

**File:** `schemas/bigquery/predictions/07_subset_grading_results.sql`

Stores grading per subset per game_date: wins, losses, pushes, voided, hit_rate, ROI, MAE, over/under breakdown.

### 6. `SubsetGradingProcessor` — Grade Subsets (NEW)

**File:** `data_processors/grading/subset_grading/subset_grading_processor.py`

**Key design: pre-tip version selection.** Looks up first game tip time from `nba_reference.nba_schedule`, then picks `MAX(version_id) WHERE computed_at < first_tip_time`. Falls back to latest version if no schedule data. This ensures we grade the picks that were "locked in" before games started.

Uses same win/loss/push/DNP logic as `PredictionAccuracyProcessor`.

### 7. Grading Pipeline Wiring (MODIFIED)

**File:** `orchestration/cloud_functions/grading/main.py`

Added `run_subset_grading()` function and Step 2b after post-grading validation. Non-fatal — if subset grading fails, individual prediction grading still succeeds.

## Files Summary

### New (4)
| File | Lines |
|------|-------|
| `schemas/bigquery/predictions/06_current_subset_picks.sql` | 69 |
| `schemas/bigquery/predictions/07_subset_grading_results.sql` | 48 |
| `data_processors/publishing/subset_materializer.py` | 335 |
| `data_processors/grading/subset_grading/subset_grading_processor.py` | 464 |

### Modified (3)
| File | Change |
|------|--------|
| `data_processors/publishing/all_subsets_picks_exporter.py` | Read from materialized table with fallback; remove snapshot recording |
| `backfill_jobs/publishing/daily_export.py` | Call materializer before export |
| `orchestration/cloud_functions/grading/main.py` | Add subset grading step |

---

## Open Items for Next Session to Review

### 1. Add `game_id` and `rank_in_subset` (SHOULD DO)

**`game_id`** — Currently not stored. Useful for JOINing to schedule, analyzing per-game.

**`rank_in_subset`** — The pick's position (1st, 2nd, 3rd) within the subset. For "Top 5" subsets, knowing whether a pick was #1 or #5 matters for analysis. Currently lost after materialization. The rank is implicit in the filtering order (composite_score DESC) but not stored.

Both are easy to add — `game_id` comes from the predictions query (needs to be added to the SELECT), `rank_in_subset` is the enumeration index during `_filter_picks_for_subset`.

### 2. Filtering Logic Duplication (ACCEPTABLE FOR NOW)

The subset filtering logic (`_filter_picks_for_subset`) exists in both:
- `SubsetMaterializer._filter_picks_for_subset()`
- `AllSubsetsPicksExporter._filter_picks_for_subset()` (fallback path)

These must stay in sync. Could extract to a shared module, but the fallback is temporary — once all new dates have materialized data, the exporter's copy is only used for historical backfill of old dates. Not worth abstracting yet.

### 3. `subset_pick_snapshots` Table Cleanup (LOW)

Session 152's `subset_pick_snapshots` table is now superseded by `current_subset_picks`. The `_record_snapshot()` call was removed from the exporter. The BQ table still exists with historical data — leave it for now, clean up later.

### 4. Storage Growth Estimation (NO CONCERN)

Append-only means rows accumulate. Estimated volume:
- ~12 subsets × ~5 picks avg = ~60 rows per version
- ~5 versions per game day = ~300 rows/day
- ~180 game days/season = ~54,000 rows/season

This is negligible for BigQuery. No partition expiration needed.

### 5. `v_dynamic_subset_performance` View Coexistence

The existing view still works and is still used by the exporter's `_get_all_subset_performance()` for displaying 30-day stats in the export JSON. Once `subset_grading_results` has data, we could switch to reading from it instead. Both can coexist safely.

### 6. Grading Cloud Function Deployment

The grading Cloud Function (`orchestration/cloud_functions/grading/main.py`) imports the new `SubsetGradingProcessor`. This Cloud Function has its own deployment — it needs to be redeployed to pick up the new code. Check how it's deployed (it may not be in the auto-deploy triggers since it's a Cloud Function, not a Cloud Run service).

### 7. Should the Phase 5→6 Orchestrator Call Materializer Directly?

Currently materialization is wired into `daily_export.py`. But the Phase 5→6 orchestrator (`orchestration/cloud_functions/phase5_to_phase6/main.py`) is what triggers exports after predictions complete. An alternative would be to call materialization directly from the orchestrator before triggering the Phase 6 export. This would make the materialization an explicit pipeline step rather than being embedded in the export job. Worth considering but not blocking.

---

## Deployment Steps (When Ready)

```bash
# 1. Create BigQuery tables
bq query --use_legacy_sql=false < schemas/bigquery/predictions/06_current_subset_picks.sql
bq query --use_legacy_sql=false < schemas/bigquery/predictions/07_subset_grading_results.sql

# 2. Commit and push (auto-deploy triggers for Cloud Run services)
git add schemas/bigquery/predictions/06_current_subset_picks.sql \
        schemas/bigquery/predictions/07_subset_grading_results.sql \
        data_processors/publishing/subset_materializer.py \
        data_processors/grading/subset_grading/__init__.py \
        data_processors/grading/subset_grading/subset_grading_processor.py \
        data_processors/publishing/all_subsets_picks_exporter.py \
        backfill_jobs/publishing/daily_export.py \
        orchestration/cloud_functions/grading/main.py
git commit -m "feat: Materialize subsets + subset grading (Session 153)"
git push origin main

# 3. Verify Cloud Build triggers fired
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=5

# 4. Redeploy grading Cloud Function (if not auto-deployed)
# [Check how grading CF is deployed — may need manual deploy]

# 5. Test materialization manually
# python -c "
# from data_processors.publishing.subset_materializer import SubsetMaterializer
# m = SubsetMaterializer()
# result = m.materialize('2026-02-07', 'manual')
# print(result)
# "
```

## Verification Queries

```sql
-- Check materialized data exists
SELECT version_id, computed_at, trigger_source, COUNT(*) as picks,
       COUNT(DISTINCT subset_id) as subsets
FROM nba_predictions.current_subset_picks
WHERE game_date = CURRENT_DATE()
GROUP BY 1, 2, 3
ORDER BY 2 DESC;

-- Check version history for a date (should see multiple versions throughout day)
SELECT version_id, computed_at, trigger_source, daily_signal,
       total_predictions_available, COUNT(*) as total_rows
FROM nba_predictions.current_subset_picks
WHERE game_date = '2026-02-07'
GROUP BY 1, 2, 3, 4, 5
ORDER BY 2;

-- Check subset grading results
SELECT subset_id, subset_name, total_picks, graded_picks, wins, hit_rate, roi
FROM nba_predictions.subset_grading_results
WHERE game_date >= CURRENT_DATE() - 3
ORDER BY game_date DESC, subset_id;

-- Compare materialized grading vs retroactive view
-- (may differ because view recomputes membership, grading uses actual membership)
SELECT g.subset_id, g.hit_rate as graded_hit_rate,
       ROUND(100.0 * v.wins / NULLIF(v.graded_picks, 0), 1) as view_hit_rate
FROM nba_predictions.subset_grading_results g
LEFT JOIN (
  SELECT subset_id, SUM(wins) as wins, SUM(graded_picks) as graded_picks
  FROM nba_predictions.v_dynamic_subset_performance
  WHERE game_date = g.game_date
  GROUP BY 1
) v ON g.subset_id = v.subset_id
WHERE g.game_date = '2026-02-07';
```
