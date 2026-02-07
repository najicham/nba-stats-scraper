# Feature Store Performance Investigation - Project Overview

**Session:** 143
**Date:** February 6, 2026
**Status:** Complete
**Priority:** P1 - Backfill mode unusable (17+ minutes per game date)

---

## Table of Contents

1. [Problem](#problem)
2. [Root Causes Found](#root-causes-found)
3. [Diagnosis Approach](#diagnosis-approach)
4. [Instrumentation Added](#instrumentation-added)
5. [Results](#results)
6. [Key Lesson](#key-lesson)
7. [Files Changed](#files-changed)
8. [Related Documentation](#related-documentation)

---

## Problem

The ML Feature Store processor (`data_processors/precompute/ml_feature_store/`) took **17.7 minutes per game date** in backfill mode. Production (non-backfill) was fast at **2.0-3.4 seconds**. The bottleneck was in `batch_extract_all_data()`, which runs 11 BigQuery queries in parallel.

This made backfilling historical dates effectively unusable. A 30-day backfill that should take minutes would take over 8 hours.

---

## Root Causes Found

### 1. Unbounded CTE in `_batch_extract_last_10_games` (PRIMARY)

**File:** `data_processors/precompute/ml_feature_store/feature_extractor.py`

The `total_games_per_player` CTE counted ALL historical games with `WHERE game_date < '{game_date}'` and NO date lower bound. This caused a full table scan on `player_game_summary` (potentially millions of rows).

**Before:**
```sql
WITH total_games_per_player AS (
  SELECT player_id, COUNT(*) as total_games
  FROM player_game_summary
  WHERE game_date < '{game_date}'
  GROUP BY player_id
)
```

**After:**
```sql
WITH total_games_per_player AS (
  SELECT player_id, COUNT(*) as total_games
  FROM player_game_summary
  WHERE game_date < '{game_date}'
    AND game_date >= DATE_SUB('{game_date}', INTERVAL 365 DAY)
  GROUP BY player_id
)
```

Bootstrap detection only needs approximately 1 year of data to determine whether a player is new. Scanning the full history back to the earliest records was unnecessary.

This was the **primary bottleneck** causing the 17+ minute extraction time.

### 2. Excessive Lookback in `_batch_extract_opponent_history`

**File:** `data_processors/precompute/ml_feature_store/feature_extractor.py`

Used `INTERVAL 3 YEAR` lookback on `player_game_summary` for all players. NBA rosters change significantly year-over-year, making 3-year opponent history data less relevant for current predictions.

**Fix:** Reduced to `INTERVAL 1 YEAR`.

### 3. No Query Timeouts

**File:** `data_processors/precompute/ml_feature_store/feature_extractor.py`

`_safe_query()` had no timeout parameter. Queries could run indefinitely if they hit an unbounded scan or BigQuery slowdown, with no way to detect or recover.

**Fix:** Added `timeout=120` parameter to `job.result()` calls. Any individual query that exceeds 120 seconds will now raise a timeout exception rather than blocking the entire pipeline.

### 4. Connection Pool Starvation

**File:** `shared/clients/bigquery_pool.py`

The urllib3 default connection pool size is 10, but the feature extractor runs 11 parallel BigQuery queries via `ThreadPoolExecutor`. The 11th query would starve waiting for a connection from the pool, causing unpredictable delays and potential timeouts.

**Fix:** Increased pool size to 20 in `shared/clients/bigquery_pool.py`, providing comfortable headroom above the 11 concurrent queries.

---

## Diagnosis Approach

1. **Checked production logs first** -- confirmed production (non-backfill) was fast at 2-3 seconds. This narrowed the problem to backfill-specific code paths or data volume differences.

2. **Added per-query timing instrumentation** to identify which of the 11 parallel queries was slow. Without this, we only knew the total extraction time was 17+ minutes but not which query was responsible.

3. **Analyzed query patterns for unbounded scans** -- once the slow query was identified, examined the SQL for missing date bounds. The unbounded CTE in `_batch_extract_last_10_games` was immediately apparent as the root cause.

---

## Instrumentation Added

Three levels of query timing visibility were added to `feature_extractor.py`:

| Log Tag | Purpose | Detail |
|---------|---------|--------|
| `[QUERY_TIMING]` | Per-query completion time | Logs each individual query name and its execution time in seconds |
| `[QUERY_TIMING_BREAKDOWN]` | Aggregated summary | After all queries complete, logs all timings sorted slowest-first |
| `[SLOW_QUERY]` | Warning threshold | Emits a warning for any individual query exceeding 30 seconds |

Example log output:
```
[QUERY_TIMING] _batch_extract_last_10_games completed in 2.1s
[QUERY_TIMING] _batch_extract_opponent_history completed in 1.8s
[QUERY_TIMING_BREAKDOWN] All queries: last_10_games=2.1s, opponent_history=1.8s, ...
```

These log entries persist in production for ongoing monitoring. If backfill performance degrades in the future, the timing breakdown will immediately identify which query regressed.

---

## Results

| Metric | Before | After |
|--------|--------|-------|
| Backfill extraction (per date) | 1,061s (17.7 min) | ~3s |
| Production extraction (per date) | 2-3s | 2-3s (unchanged) |
| Query timeout protection | None | 120s per query |
| Connection pool size | 10 connections | 20 connections |
| Performance visibility | None | Per-query timing logs |

The backfill performance improvement is approximately **350x** (from 17.7 minutes to ~3 seconds). A 30-day backfill that previously took 8+ hours now completes in under 2 minutes.

Production performance was unchanged because the non-backfill path already benefits from smaller data volumes and partition pruning.

---

## Key Lesson

**Always add date lower bounds to CTEs that aggregate historical data.** Even when you "need all historical data" (like counting total games for bootstrap detection), there is usually a reasonable bound (1 year for NBA data) that prevents full table scans while still providing accurate results.

This is a specific instance of a broader principle in BigQuery: **unbounded date ranges on partitioned tables defeat partition pruning and cause full table scans.** The query planner cannot optimize a CTE that reads all partitions, even if the outer query only needs recent data.

Corollary: **Always add per-query timing instrumentation to parallel query patterns.** Without timing on each individual query, you can only observe the total time and are left guessing which query is the bottleneck. The `[QUERY_TIMING]` pattern added here should be replicated in any other service that runs multiple BigQuery queries in parallel.

---

## Files Changed

| File | Changes |
|------|---------|
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | Per-query timing instrumentation, date-bounded CTEs (1-year lookback), query timeouts (120s) |
| `shared/clients/bigquery_pool.py` | Connection pool size increased from 10 to 20 |

---

## Related Documentation

- **Session 142 handoff:** `docs/09-handoff/2026-02-06-SESSION-142-HANDOFF.md`
- **Feature quality visibility project:** `docs/08-projects/current/feature-quality-visibility/`
- **Feature completeness project:** `docs/08-projects/current/feature-completeness/`
- **ML Feature Store schema:** `schemas/bigquery/predictions/04_ml_feature_store_v2.sql`

---

**Document Version:** 1.0
**Last Updated:** February 6, 2026 (Session 143)
