# Session 169 Handoff — UNDER Bias Root Cause Found & Fixed, Stale Model Cleanup

**Date:** February 9, 2026
**Commit:** `0fb76d06` (pushed and deployed to Cloud Run)
**Status:** Critical fix — Vegas line disconnect found and fixed

## What Was Done

### P0: UNDER Bias Root Cause — FOUND AND FIXED

**Root cause:** The coordinator loads `actual_prop_line` from Phase 3's stale `upcoming_player_game_context.current_points_line` (which is often NULL for pre-game runs). Meanwhile, it separately queries fresh odds to build `line_values` (e.g., [31.5, 30.5, ...]). The worker's Vegas override depends on `actual_prop_line`, which is NULL, so the model predicts WITHOUT its most important feature (#25 vegas_points_line).

**Data flow (before fix):**
```
Coordinator:
  player_loader.py:356 → current_points_line from Phase 3 table = NULL (stale)
  player_loader.py:418 → actual_prop_line = player.get('current_points_line') = NULL
  Separately: odds query → line_values = [31.5, 30.5, 28.5, 27.5, 29.5] (fresh)

Worker:
  worker.py:1101 → actual_prop = None (from stale Phase 3)
  worker.py:1108 → feature_store vegas also null (Phase 4 hadn't updated yet)
  worker.py:1114 → vegas_points_line = None, has_vegas_line = 0.0
  → Model predicts WITHOUT Vegas anchor → UNDER bias
```

**Fix (worker.py:1101):** When `actual_prop_line` is None but `has_prop_line=True` and `line_values` exist, recover by using the median line value as the Vegas override. This ensures the model ALWAYS has its Vegas feature when the coordinator found real lines.

**Evidence that confirmed the root cause:**
1. All 42 FIRST predictions had `has_prop_line=True`, `line_source=ACTUAL_PROP` — coordinator FOUND lines
2. But features_snapshot showed `vegas_points_line: null`, `has_vegas_line: 0.0`
3. `current_points_line` in predictions was set from `line_values` (fresh odds), not from `actual_prop_line`
4. Feature store's Vegas data (29.5 for Embiid) was from a LATER Phase 4 re-run (after 16:45 UTC)

**Key investigation findings:**
1. "Weekly bias acceleration" (Jan 12: +1.29 → Feb 9: -3.84) was partly apples-to-oranges — Feb 5-7 were BACKFILL, Feb 9 was FIRST-run
2. FIRST-run predictions consistently show UNDER bias because model misses Vegas
3. BACKFILL predictions are near-neutral because Phase 4 has complete data by then
4. Bias is tier-correlated: Stars (-4.60), Starters (-4.11), Role Players (-2.88), Bench (-1.48) — higher lines = bigger miss when Vegas feature is null
5. RETRY predictions on Feb 9 had avg_pvl = +0.66 (coordinator passes actual_prop_line from fresh odds)

### P1: Stale Prediction Cleanup (DONE)

| Model | Rows Deactivated |
|-------|-----------------|
| v9_current_season | 412 |
| v9_36features_20260108_212239 | 17 |
| catboost_v9_2026_02 | 966 |
| **Total** | **1,395** |

Verification: all 3 categories show 0 active predictions.

### P2: Disabled Broken Monthly Model (DONE)

`predictions/worker/prediction_systems/catboost_monthly.py` line 55: `"enabled": True` → `"enabled": False` for `catboost_v9_2026_02`.

### P3: Feb 4 Backfill (DEFERRED)

Deferred until fix is deployed and verified. After deploy, backfill Feb 4 with:
```bash
POST /start {"game_date":"2026-02-04","prediction_run_mode":"BACKFILL"}
```

### Model Deployment & Naming Check (DONE)

| Model | Status | Naming Convention? |
|-------|--------|-------------------|
| `catboost_v9_33features_20260201_011018.cbm` | PRODUCTION | No — old format |
| `catboost_v9_33f_train20251102-20260108_*.cbm` | Shadow | Yes — Session 165 |
| `catboost_v9_33f_train20251102-20260131_*.cbm` | Shadow | Yes — Session 165 |
| `catboost_v9_feb_02_retrain.cbm` | Deprecated | No — ad-hoc |
| `catboost_v9_2026_02.cbm` | Untested | No — monthly shorthand |

BQ registry, GCS manifest, and Cloud Run env vars are all consistent.

### Features Snapshot Expansion (DONE)

**File:** `predictions/worker/worker.py`

1. **Expanded features_snapshot** from ~17 to ALL 33 model input features plus metadata
2. **Added `fs_vegas_points_line`** — saves the feature store's Vegas value BEFORE coordinator override
3. **Added `fs_has_vegas_line`** — saves the feature store's has_vegas flag BEFORE override
4. Enables post-hoc debugging: if `fs_vegas_points_line` differs from `vegas_points_line`, the override logic changed it

## Files Modified

| File | Change |
|------|--------|
| `predictions/worker/worker.py` | Vegas line recovery fix, expanded features_snapshot to 33 features, fs_original tracking |
| `predictions/worker/prediction_systems/catboost_monthly.py` | Disabled catboost_v9_2026_02 model |

## Root Cause Deep Dive

### The Two Line Sources Problem

The coordinator has two independent line sources that should agree but don't:

1. **Phase 3 table** (`upcoming_player_game_context.current_points_line`) — populated during Phase 3 at ~07:03 UTC, often NULL for early predictions
2. **Real-time odds queries** — coordinator queries raw odds tables to find fresh `line_values`

`actual_prop_line` was set from source #1 (stale), while `line_values` came from source #2 (fresh). The worker's Vegas override logic depended on `actual_prop_line`, which was NULL.

### Why BACKFILL Worked Fine

BACKFILL predictions run AFTER games complete. By then:
- Phase 4 has re-run with complete data → feature store has real Vegas values
- Coordinator's Phase 3 table has been updated → `current_points_line` is populated
- Either path provides the Vegas line to the model

### Feature Store Timing

The feature store for Feb 9 was written in two phases:
1. **~07:30 UTC** (after Phase 3→4 trigger): Feature store written, but raw odds data barely available (earliest: 07:00:34 UTC). Many players may have had NULL Vegas.
2. **~17:10 UTC** (after second Phase 2/3 cycle): Feature store re-written with complete odds data. Current BQ query shows this updated version.

## Verification After Deploy

```sql
-- Check that Vegas line recovery is working
-- Look for predictions where fs_vegas_points_line differs from vegas_points_line
SELECT player_lookup,
  JSON_VALUE(TO_JSON_STRING(features_snapshot), '$.vegas_points_line') as model_vegas,
  JSON_VALUE(TO_JSON_STRING(features_snapshot), '$.fs_vegas_points_line') as feature_store_vegas,
  JSON_VALUE(TO_JSON_STRING(features_snapshot), '$.has_vegas_line') as has_vegas,
  current_points_line, predicted_points,
  predicted_points - current_points_line as pvl
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-02-10'
  AND system_id = 'catboost_v9'
  AND model_version = 'v9_20260201_011018'
  AND prediction_run_mode = 'FIRST'
  AND is_active = TRUE
ORDER BY player_lookup
LIMIT 20
```

Expected: `model_vegas` should now be non-null for players with real lines.

## Next Session Priorities

### P1: Add avg_pvl Monitoring
Alert when a prediction batch's avg_pvl < -2.0 (would have caught this immediately).

### P2: Add model_version Filter to Subsets
Prevent future stale model leak: add `AND model_version = '{production_version}'` to subset queries in `subset_picks_notifier.py:152`.

### P3: Evaluate Shadow Models
Two shadow models exist but have NULL evaluation metrics:
- `catboost_v9_33f_train20251102-20260108_20260208_170526` (same dates, different seed)
- `catboost_v9_33f_train20251102-20260131_20260208_170613` (extended through Jan 31)

### P4: Fix Coordinator actual_prop_line
Long-term: fix the coordinator to set `actual_prop_line` from the fresh odds query, not the stale Phase 3 table. The worker fix is a defense-in-depth fallback.

### P5: Feb 4 Backfill
After verifying fix works on Feb 10 FIRST predictions.

## Key Metrics

| Metric | Value |
|--------|-------|
| FIRST-run avg_pvl (Feb 9) | -3.84 |
| RETRY avg_pvl (Feb 9) | +0.66 |
| BACKFILL avg_pvl (Feb 5-7) | -0.03 to -0.15 |
| Active predictions Feb 9 | 56 (42 FIRST + 14 RETRY) |
| Stale predictions cleaned | 1,395 |
| Feature store Vegas (Embiid) | 29.5 (from later Phase 4 re-run) |
| Snapshot Vegas (Embiid, FIRST) | null (root cause) |
| Raw odds earliest snapshot | 07:00:34 UTC |
| FIRST prediction time | 13:04 UTC |
