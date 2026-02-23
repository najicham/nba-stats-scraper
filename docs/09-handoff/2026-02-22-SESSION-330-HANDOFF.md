# Session 330 Handoff — Coordinator Bug Fixes + Batch Line Optimization

**Date:** 2026-02-22
**Previous Session:** 329 — V12+Vegas Fix Verified, Coordinator Timeout Fixed

## What Was Done

### 1. Fixed `name 'bigquery' is not defined` in coordinator (P1)

**Root cause:** Two post-consolidation quality check blocks in `coordinator.py` (lines ~3702 and ~4004) used `bigquery.QueryJobConfig()` and `bigquery.Client()` but the only `bigquery` import was inside a `TYPE_CHECKING` block (not available at runtime).

**Fix:** Added `from google.cloud import bigquery` local import to both try blocks, matching the pattern used by other methods in the same file.

### 2. Fixed Decimal JSON serialization in best bets export (P1)

**Root cause:** `json.dumps()` calls in `signal_best_bets_exporter.py` (lines 576, 588, 591) and `signal_annotator.py` (line 351) serialized BQ result rows containing `Decimal` values without a custom handler. The `_json_serializer` in `base_exporter.py` was only used for GCS uploads, not for BQ string fields.

**Fix:** Added `default=str` to all 4 bare `json.dumps()` calls.

### 3. Resolved unrecognized 50f_noveg model (P2)

`catboost_v9_50f_noveg_train20251225-20260205_20260221_211702` is a **legitimate** v12-family shadow model:
- Model family: `v12_noveg_q43`, 50 features
- Registered in `model_registry` at 05:24 UTC Feb 22
- Status: active, enabled, is_production=false
- Made 78 predictions for Feb 22 (not 42 as initially reported)
- Dynamic model discovery (`discover_models()`) correctly picks it up

**No action needed.**

### 4. Batch line lookup optimization in player_loader (P3)

**The problem:** N+1 query pattern — each of 365 players triggered up to 10 sequential BQ queries (5 sportsbooks x 2 data sources), totaling 3,650+ queries taking ~13 minutes.

**The fix:** Added `_batch_fetch_all_betting_lines()` that does **3 total queries**:
1. Single OddsAPI query for all players using `IN UNNEST(@player_lookups)` with sportsbook ranking via `ROW_NUMBER()`
2. Single BettingPros query for remaining players not found in OddsAPI
3. Single batch diagnostic query for players with no lines

Also added `_batch_track_no_line_reasons()` to replace per-player diagnostic queries.

**Expected improvement:** ~13 min → ~1-2 min (99.5% fewer queries). Original per-player fallback preserved for non-batch codepaths.

**Chain:** `create_prediction_requests()` → `_create_request_for_player()` → `_get_betting_lines()` → `_query_actual_betting_line()` all now accept `_prefetched_lines` optional parameter.

### 5. Monitored model health (P4/P5)

| Model | HR (edge 3+) | N | State |
|-------|-------------|---|-------|
| catboost_v9 (champion) | 80.0% | 5 | HEALTHY |
| catboost_v12 (vegas) | 56.0% | 25 | WATCH |
| catboost_v9_low_vegas | 60.0% | 15 | HEALTHY |
| catboost_v12_noveg_q43 | 60.0% | 20 | BLOCKED |

V9 champion looks great at 80% but N=5 is too small. V12+vegas at 56% is above breakeven but below historical 62.7%. Feb 20 was a universally bad day that pushed 6/10 models to BLOCKED state. Short-term variance, not structural.

## Follow-Up (Next Session)

### P1: Verify batch line optimization in production

The batch optimization deployed as revision `prediction-coordinator-00274` (commit 07b2090). Monitor Feb 23 prediction run (~6 AM ET, 3 games):
- Check coordinator logs for `BATCH_LINES:` messages showing timing
- Verify line coverage matches pre-optimization levels
- Expected: player_loader phase should drop from ~13 min to ~1-2 min

### P2: Validate coordinator timeout headroom

With batch optimization, the 900s timeout should have ample headroom even on 15-game days. After verifying Feb 23 runs, consider whether timeout can be reduced back to 540s.

### P3: Pre-existing deployment drift

`validation-runner` has drift (commit 81a149b1 deployed vs e24a5637 current). Caused by `shared/` changes in prior sessions, not urgent. Deploy when convenient:
```bash
# From repo root
./bin/deploy-service.sh validation-runner
```

### P4: Model health monitoring

Continue tracking V12+vegas vs V9 performance daily. If V12+vegas sustains 55%+ HR over next 5+ days with meaningful N, consider promotion discussion.

### P5: Pre-existing test failures

12 of 26 player_loader tests fail (pre-existing, not caused by Session 330 changes):
- Most failures due to `validate_game_date()` rejecting test date `2025-11-08` as >90 days old
- Test mocking issues with BQ client iterators
- Not blocking production but should be cleaned up

### Optional

- Ultra OVER gate progress: 17-2 (89.5%, N=19). Need 50 for public exposure.
- `model_performance_daily` has duplicate rows for Feb 21 — post-grading export may have double-written

## Key Files Changed

| File | Change |
|------|--------|
| `predictions/coordinator/coordinator.py` | Added `from google.cloud import bigquery` to 2 post-consolidation try blocks |
| `predictions/coordinator/player_loader.py` | Added `_batch_fetch_all_betting_lines()`, `_batch_track_no_line_reasons()`, threaded `_prefetched_lines` through call chain |
| `data_processors/publishing/signal_best_bets_exporter.py` | Added `default=str` to 3 `json.dumps()` calls |
| `data_processors/publishing/signal_annotator.py` | Added `default=str` to 1 `json.dumps()` call |

## Deployment Status

All builds SUCCESS for commit `07b2090`:
- `prediction-coordinator` — deployed 16:54 UTC (revision 00274)
- `post-grading-export` — deployed
- `live-export` — deployed
- `phase6-export` — deployed
