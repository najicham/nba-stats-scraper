# Session 142 Handoff: Feature Completeness Tracking + Backfill Performance Issue

**Date:** 2026-02-06
**Focus:** Track which features are defaulted per prediction, diagnose pipeline gaps
**Status:** Code complete + deployed. Backfill 97.2% done. Performance investigation needed.

## What Was Done

### 1. Added `default_feature_indices` Column
- **Both tables**: `player_prop_predictions` and `ml_feature_store_v2`
- BigQuery DDL executed successfully
- Schema SQL files updated
- Empty array = all features real. Non-empty = those indices used defaults.

### 2. Quality Scorer Emits `default_feature_indices`
- `quality_scorer.py`: Extracts indices from existing `is_default` dict (no new computation)
- Verified: `[25, 26, 27]` for vegas-only defaults, `[]` for clean players

### 3. Prediction Worker Writes `default_feature_indices`
- `data_loaders.py`: Loads from feature store
- `worker.py`: Writes to prediction record

### 4. Feature Source Classification Constants
- `shared/ml/feature_contract.py`: `FEATURES_FROM_PHASE4`, `FEATURES_FROM_PHASE3`, `FEATURES_CALCULATED`, `FEATURES_VEGAS`, `FEATURES_SHOT_ZONE`, `FEATURE_SOURCE_MAP`

### 5. Pipeline Gap Diagnosis
Top defaulted features (last 7 days):
- **Vegas (25-27)**: 1,436 defaults, 464 players -- NORMAL (not all players have prop lines)
- **Shot zones (18-20)**: 512 defaults, 126 players -- low-minutes players
- **Minutes/PPM (31-32)**: 328 defaults, 90 players -- new/traded players
- **Composite factors (5-8)**: 103 defaults, 52 players -- processor coverage gap

### 6. SQL Backfill of `default_feature_indices`
- Populated **127,616 of 131,363 records** (97.2%) using SQL UPDATE in ~20 seconds
- Derived from existing `feature_N_source` columns (verified 0 mismatches against `default_feature_count`)
- **3,594 records** (2.8%) still missing -- these have NULL `feature_N_source` columns entirely

### 7. Deployments Complete
- `nba-phase4-precompute-processors` -- deployed, validated
- `prediction-worker` -- deployed, validated

### 8. Tests Pass
- All 60 quality gate and quality system tests pass

## CRITICAL: ML Feature Store Processor Performance Issue

### The Problem

The ML Feature Store backfill processor takes **17.7 minutes per game date**. This was discovered when trying to backfill 3,594 records across ~35 dates. A single date (2026-02-05) took 1,167 seconds total:

```
Extract Phase: 1067.6s (17.8 min) <-- THE BOTTLENECK
  - check_dependencies: 0.0s
  - get_players_with_games: 2.5s
  - batch_extract_all_data: 1061.6s  <-- 11 parallel BQ queries, still 17.7 min
Calculate Phase: 27.3s
  - player_processing: 21.1s (267 players at 13.4/sec)
Write Phase: 8.2s
  - MERGE: 2.7s, Load: 4.8s
```

### Why This Matters

This processor runs **daily in production orchestration** as part of Phase 4. If it takes 17+ minutes per date during daily runs, it's a significant pipeline bottleneck. Need to determine:
1. Is this only in backfill mode? (backfill queries ALL players who played, ~267/date)
2. Does production mode (upcoming players only, ~250/date) have similar performance?
3. Was it always this slow, or did the Session 134/137 quality visibility schema (120+ new fields) slow it down?

### Architecture: 11 Parallel BigQuery Queries

The extraction runs 11 queries via `ThreadPoolExecutor(max_workers=11)`:

| # | Query | File:Lines | What It Does | Estimated Cost |
|---|-------|-----------|-------------|----------------|
| 1 | `batch_extract_daily_cache` | feature_extractor.py:347-409 | Player daily cache, 14-day fallback | Low |
| 2 | `batch_extract_composite_factors` | feature_extractor.py:411-486 | Composite factors, 7-day fallback | Low |
| 3 | `batch_extract_shot_zone` | feature_extractor.py:488-530 | Shot zone analysis, 14-day fallback | Low |
| 4 | `batch_extract_team_defense` | feature_extractor.py:532-575 | Team defense, 7-day fallback | Low |
| 5 | `batch_extract_player_context` | feature_extractor.py:577-600 | Player game context | Low |
| 6 | `batch_extract_last_10_games` | feature_extractor.py:602-687 | **SUSPECT** - counts ALL historical games with no date limit | HIGH |
| 7 | `batch_extract_season_stats` | feature_extractor.py:689-726 | Season aggregates | Medium |
| 8 | `batch_extract_team_games` | feature_extractor.py:728-760 | Team games for season | Medium |
| 9 | `batch_extract_vegas_lines` | feature_extractor.py:766-889 | Vegas lines, 2-source UNION | Medium |
| 10 | `batch_extract_opponent_history` | feature_extractor.py:891-943 | **SUSPECT** - 3-year lookback | HIGH |
| 11 | `batch_extract_minutes_ppm` | feature_extractor.py:945-980 | Minutes/PPM, 30-day window | Low |

### Suspected Bottlenecks

1. **`batch_extract_last_10_games` (lines 602-687)**
   - Has a CTE `total_games_per_player` that counts ALL historical games with `WHERE game_date < '{game_date}'` and NO lower bound
   - Full table scan on player_game_summary for every player
   - **Fix:** Add `AND game_date >= DATE_SUB('{game_date}', INTERVAL 365 DAY)` -- 10 games never needs more than 1 year

2. **`batch_extract_opponent_history` (lines 891-943)**
   - Uses `INTERVAL 3 YEAR` lookback on `player_game_summary`
   - For 500+ players with multiple opponents each
   - **Fix:** Reduce to 1 year for backfill, keep 3 years for production if needed

3. **No query-level timeouts**
   - BigQuery queries can run indefinitely
   - No timeout set anywhere in the feature extractor
   - **Fix:** Add `job_config.timeout` or `query_job.result(timeout=120)` per query

4. **Sequential fallback queries**
   - When exact date data is missing, each extractor runs a SECOND fallback query
   - 11 queries can become 15-22 queries when fallbacks activate
   - **Fix:** Combine primary + fallback into single queries using COALESCE or UNION ALL

### What We Don't Know Yet

- **Is production equally slow?** The 17.7 min measurement was backfill mode. Production mode might differ:
  - Backfill queries `player_game_summary` for played roster (historical)
  - Production queries `upcoming_player_game_context` for expected roster (forward-looking)
  - Both paths converge at `batch_extract_all_data` which is the bottleneck

- **Was it always this slow?** The Session 134/137 quality visibility added 120+ new fields to the MERGE. The MERGE itself only takes 2.7s, but the schema fetch + temp table creation adds overhead. The extraction queries haven't changed recently though.

- **Which of the 11 queries is actually slow?** The timing breakdown only shows `batch_extract_all_data` as a single number. Need per-query timing.

### Investigation Steps for Next Session

```bash
# 1. Add per-query timing to feature_extractor.py
# In batch_extract_all_data(), each of the 11 ThreadPoolExecutor tasks
# should log their individual duration. Look at lines ~211-327.

# 2. Check production timing
# Look at recent Cloud Run logs for the ML Feature Store processor:
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-phase4-precompute-processors" AND textPayload:"PERFORMANCE TIMING"' --project=nba-props-platform --limit=10 --format=json

# 3. Compare backfill vs production performance
# Check if the PERFORMANCE TIMING BREAKDOWN appears in production logs
# and compare batch_extract_all_data times

# 4. Profile the expensive queries
# Run each query individually with EXPLAIN and check bytes scanned:
# - batch_extract_last_10_games query (lines 631-687)
# - batch_extract_opponent_history query (lines 931-943)
```

### Key Files to Investigate

| File | What to Look At |
|------|----------------|
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | All 11 batch_extract_* methods, ThreadPoolExecutor at ~line 211 |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | `process_game_date()` flow, timing breakdown at end |
| `data_processors/precompute/ml_feature_store/batch_writer.py` | MERGE performance (currently fine at 2.7s) |
| `backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py` | Backfill orchestration, per-date loop |

## Remaining Work

### 3,594 Records Without Source Columns

These records have feature data but no `feature_N_source` columns (written before quality scoring deployment). They need a full processor rerun. Affected dates:

- **2021**: 3,231 records across ~60 dates (early season, 25.7% of 2021 data)
- **2025**: 21 records across ~12 dates
- **2026**: 342 records across ~32 dates

At current speed (17.7 min/date), this is ~11 hours for ~35 unique dates (2025-26 only). The 2021 dates would add ~18 more hours.

```bash
# Run backfill for 2025-26 affected dates only (after fixing performance)
PYTHONPATH=. python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2025-12-01 --end-date 2026-02-06

# Run backfill for 2021 affected dates
PYTHONPATH=. python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2021-11-02 --end-date 2021-12-31
```

### Future Coverage Improvements

To increase prediction coverage from ~75 to ~180/day, fix in priority order:
1. **Composite factors (5-8)**: Fix processor for 52 additional players
2. **Shot zones (18-20)**: Handle sparse data for 126 players
3. **Player history (0-4)**: Bootstrap new players from limited data
4. **Vegas (25-27)**: Structural -- only players with prop lines get vegas data

## What's NOT Changed

- **Model**: V9 stays as-is (33 features, all-floats)
- **Zero tolerance**: Still blocks predictions when `default_feature_count > 0`
- **Coverage**: Still ~75 predictions/day

## Key Files

- `docs/08-projects/current/feature-completeness/00-PROJECT-OVERVIEW.md` -- full gap analysis
- `shared/ml/feature_contract.py` -- feature source classification constants
- `data_processors/precompute/ml_feature_store/quality_scorer.py` -- quality scoring + default_feature_indices
- `data_processors/precompute/ml_feature_store/feature_extractor.py` -- THE FILE TO INVESTIGATE for performance
