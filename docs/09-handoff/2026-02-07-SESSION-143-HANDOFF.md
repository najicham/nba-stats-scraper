# Session 143 Handoff: Feature Store Performance Fix + Timing Visibility

**Date:** 2026-02-07
**Focus:** Fix ML feature store backfill performance, add cross-processor timing visibility
**Status:** Performance fix deployed. Backfill not yet run. Coverage gaps identified.

## What Was Done

### 1. ML Feature Store Backfill Performance: 17.7 min → ~3s

**Root cause:** Unbounded CTE in `_batch_extract_last_10_games` did a full table scan on `player_game_summary` with no date lower bound.

**Fixes applied:**
- Added 365-day lower bound to `total_games_per_player` CTE (PRIMARY fix)
- Reduced `_batch_extract_opponent_history` from 3-year to 1-year lookback
- Added `timeout=120` to `_safe_query()` (prevents indefinite query hangs)
- Increased BQ connection pool from 10 → 20 (we run 11 parallel queries)
- Added per-query `[QUERY_TIMING]` instrumentation to identify slow queries

**Production was already fast** (2-3s). This only affected backfill mode.

### 2. Timing Breakdown Persistence (All Phases)

Added `timing_breakdown JSON` column to `processor_run_history` table:
- Phase 2: `load_time`, `transform_time`, `save_time`
- Phase 3: `extract_time`, `transform_time`, `save_time`, `change_detection_time`
- Phase 4: `extract_time`, `calculate_time`, `save_time` + custom `detail` dict
- ML Feature Store: includes per-query timing in `detail` key

**Query example:**
```sql
SELECT processor_name, duration_seconds,
  JSON_VALUE(timing_breakdown, '$.extract_time') as extract_s,
  JSON_VALUE(timing_breakdown, '$.save_time') as save_s
FROM nba_reference.processor_run_history
WHERE data_date >= CURRENT_DATE() - 7
  AND status = 'success'
ORDER BY duration_seconds DESC;
```

### 3. Deployed Phase 4

`nba-phase4-precompute-processors` deployed with commit `b7a68c4d`. All 60 tests pass.

### 4. Documentation

Created `docs/08-projects/current/feature-store-performance/00-PROJECT-OVERVIEW.md`

## NOT Done - Tasks for Next Session

### Task 1: Run ML Feature Store Backfill (3,594 records)

Records with NULL `feature_N_source` columns need full processor rerun:

```bash
# 2025-26 season (363 records, ~33 dates) - ~2 min
PYTHONPATH=. python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2025-12-01 --end-date 2026-02-06 --skip-preflight

# 2021 season (3,231 records, ~56 dates) - ~3 min
PYTHONPATH=. python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2021-11-02 --end-date 2021-12-31 --skip-preflight
```

### Task 2: Backfill Feature Store Coverage Gaps

**Current coverage gaps identified:**

| Month | Game Summary Records | Feature Store Records | Missing | Coverage |
|-------|---------------------|-----------------------|---------|----------|
| 2025-10 | 1,566 | 0 | 1,566 | 0% |
| 2025-11 (first 3 days) | 843 | 0 | 843 | - |

**Missing dates:** 2025-10-22 through 2025-11-03 (season start, bootstrap period overlaps).

The ML feature store processor skips "bootstrap period" (first 14 days). Records from 2025-10-22 to 2025-11-03 were skipped. These players have limited history but should still get feature records for completeness.

**Action:** Either lower the bootstrap threshold or run a targeted backfill for Oct/Nov 2025 dates.

### Task 3: Log Missing Features for Automatic Backfill

The user wants the backfill process to **log whenever features are missing** so they can be backfilled later. Specifically:

- When the feature store processor skips a player (bootstrap, missing data, etc.), log the `(player_lookup, game_date, reason)` to a tracking table
- Create a `nba_predictions.feature_store_gaps` table (or similar) that tracks:
  - `player_lookup`, `game_date`, `reason` (bootstrap, missing_phase4, no_games, etc.)
  - `detected_at` timestamp
  - `resolved_at` (NULL until backfilled)
- A scheduled job or backfill script can query this table and fill gaps

### Task 4: Ensure Complete Player Coverage

**Current state:**
- `player_game_summary` has records for ALL players who appeared in a game (played + DNP)
- `ml_feature_store_v2` has records for both played and DNP players (good!)
- **Injured players on injury report but NOT in game_summary:** ~9,274 missing records (players listed as injured who didn't play and weren't on the roster sheet)

**Question to resolve:** Should we create feature store records for players who are on the injury report but never appeared in the game? Currently the feature store only covers players in `player_game_summary` (who actually dressed for the game, even if DNP).

### Task 5: Deploy Other Services with Timing Breakdown

The timing breakdown was added to Phase 2, 3, and 4 base classes. Only Phase 4 was deployed. The other services need deployment to start capturing timing data:

```bash
./bin/deploy-service.sh nba-phase2-processors
./bin/deploy-service.sh nba-phase3-analytics-processors
```

### Task 6 (Optional): Implement --parallel Flag

The `--parallel` flag on the ML feature store backfill script is declared but never implemented. The `player_composite_factors` backfill has a working parallel implementation that could be copied. With 89 dates and ~3s each, sequential is fine (~5 min), but parallel would help for larger backfills.

## Key Files

| File | What Changed |
|------|-------------|
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | Per-query timing, date-bounded CTEs, query timeouts |
| `shared/clients/bigquery_pool.py` | Connection pool 10→20 |
| `shared/processors/mixins/run_history_mixin.py` | `timing_breakdown` param in `record_run_complete()` |
| `data_processors/precompute/precompute_base.py` | Phase 4 timing breakdown persistence |
| `data_processors/analytics/analytics_base.py` | Phase 3 timing breakdown persistence |
| `data_processors/raw/processor_base.py` | Phase 2 timing breakdown persistence |
| `schemas/bigquery/nba_reference/processor_run_history.sql` | `timing_breakdown JSON` column |
| `docs/08-projects/current/feature-store-performance/00-PROJECT-OVERVIEW.md` | Investigation docs |

## Key Lesson

**Always add date lower bounds to CTEs on partitioned tables.** The `total_games_per_player` CTE had `WHERE game_date < X` with no lower bound, causing a full table scan. Adding `AND game_date >= DATE_SUB(X, INTERVAL 365 DAY)` reduced the query from 17+ minutes to 3 seconds.
