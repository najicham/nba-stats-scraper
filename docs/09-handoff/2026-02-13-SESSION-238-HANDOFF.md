# Session 238 Handoff - UPCG Fix, Column Migration, V12 Shadow Deploy

**Date:** 2026-02-13
**Session Type:** Infrastructure / Bug Fix / Model Deployment
**Status:** All 3 tasks complete, deployed to main

---

## What Was Done

### 1. P0: Fixed UPCG days_rest Processor

**Root Cause:** Commit 922b8c16 (Feb 11) changed the UPCG completeness check from log-only to BLOCKING. This caused `_process_single_player()` to return `(False, 'INCOMPLETE_DATA_SKIPPED')` for every player, so `_calculate_player_context()` was never called and days_rest was never computed. The revert (e846d26b) restored non-blocking behavior.

**Additional Fix (Session 238):**
- Changed dependency from `bdl_player_boxscores` (critical: True, stale since Feb 6) to `nbac_gamebook_player_stats` (critical: False, fresh through Feb 12)
- This prevents a **time bomb**: BDL data ages past 30 days ~Mar 8, which would trigger `raise ValueError("Missing critical dependencies")` in `analytics_base.py:659` and block ALL UPCG processing
- Updated `quality_flags.py` source from `bdl_player_boxscores` to `player_game_summary` (matches actual data source)
- Updated docstrings to reflect actual data flow: `player_game_summary` (PRIMARY) → `nbac_gamebook_player_stats` (fallback)

**Key Architecture Finding:** The UPCG processor has a data source mismatch:
- Dependency check validates Phase 2 raw tables
- Actual data extraction queries `nba_analytics.player_game_summary` (Phase 3)
- Comment at line 371 says dependency check is "for reference" but `analytics_base.py` DOES enforce critical dependencies with `raise ValueError`

**Commit:** `83a4f08c`

### 2. Phase 2: Migrated Feature Readers to Individual Columns

**Context:** Session 237 added 54 `feature_N_value` columns to `ml_feature_store_v2` with dual-write. NULL = default/missing, value = real data. Session 238 migrates the READERS.

**Changes:**

| File | Change |
|------|--------|
| `predictions/worker/data_loaders.py` | Reads 54 `feature_N_value` columns. Builds feature dict excluding NULL values so `.get()` defaults in prediction systems work. Falls back to array for rows without individual columns. |
| `shared/ml/training_data_loader.py` | Added 54 individual columns to training SQL query. |
| `ml/experiments/quick_retrain.py` | `prepare_features()` prefers individual columns. NULL → np.nan (CatBoost native). Falls back to array for backfill gaps (pre-source-tracking rows). Removes `fillna(median)` when using individual columns. |

**Inference behavior is UNCHANGED.** When a feature is NULL (excluded from dict), the prediction system's `.get('feature_name', default)` returns the same hardcoded default it always used.

**Training behavior improves.** NULL → np.nan → CatBoost handles natively (learns optimal splits for missing values, better than median imputation).

**Backfill gap handling:** For historical data where `feature_N_value` is NULL but array has a real value (pre-source-tracking rows), the training code falls back to the array value. Zero-tolerance ensures required features are real.

**Commit:** `25b80179`

### 3. Enabled V12 Model 1 Shadow Predictions

**One-line change:** Added `'catboost_v12'` to `active_systems` in `predictions/coordinator/coordinator.py:619`.

Everything else was already in place:
- Model artifact: `gs://nba-props-platform-models/catboost/v12/catboost_v12_50f_noveg_train20251102-20260131.cbm` (357KB)
- Env var: `CATBOOST_V12_MODEL_PATH` already set on prediction-worker
- Worker code: V12 loading + prediction dispatch already implemented
- System ID: `catboost_v12`

**V12 specs:** Vegas-free CatBoost, 50 features (excludes indices 25-28), 67% avg HR edge 3+ across 4 eval windows. First model to cross breakeven in problem period (Feb 2026).

**V12 will start producing shadow predictions on Feb 19** (next game day).

**Commit:** `8d1fd56a`

---

## What Was NOT Changed

- **No model retraining** — V12 artifact already existed, V9 champion unchanged
- **No quality gate changes** — `default_feature_count` / `is_quality_ready` still array-based (Phase 3/4 of migration)
- **Array still written** — dual-write preserves backward compat
- **No prediction system code changes** — `catboost_v8.py`, `catboost_v9.py`, `catboost_v12.py` unchanged

---

## Data Findings

### Feature 39 (days_rest) Source Tracking

| Date Range | feature_39_source | Reason |
|------------|-------------------|--------|
| Nov 2024 - Dec 2025 | `phase3` (33,931 rows) | Historical backfill with 54-feature code |
| Jan 2026 - Feb 12 | NULL | 54-feature code not deployed until Feb 13 |
| Feb 12 only | `default` (103 rows) | UPCG days_rest was broken (blocking completeness) |
| Feb 19+ (expected) | `phase3` | 54-feature code now deployed, UPCG fixed |

### feature_N_value Column Status

- Features 0-36 with source tracking: individual columns correctly populated
- Features 37-53: individual columns mostly NULL for Jan-Feb (source tracking was NULL, backfill set to NULL)
- Going forward (Feb 19+): all 54 columns will be correctly populated

---

## Deployment Status

All 3 commits pushed to main. Cloud Builds triggered:

| Service | Trigger | Status |
|---------|---------|--------|
| prediction-coordinator | Push to main | Building (V12 activation) |
| prediction-worker | Push to main | Building (column migration) |
| nba-phase4-precompute-processors | Push to main | Building (UPCG fix + dual-write) |
| nba-phase3-analytics-processors | Push to main | Building (UPCG dependency fix) |

---

## Feb 19 Readiness Checklist

- [x] UPCG days_rest: Fixed (non-blocking completeness, correct dependency)
- [x] Feature store: 54-feature code deployed, will write feature_39_source correctly
- [x] Feature readers: Migrated to individual columns
- [x] V12 shadow: Enabled in coordinator
- [ ] **Verify Feb 19 morning:** Run `/validate-daily` + `./bin/monitoring/validate_phase4_quality_feb19.sh`
- [ ] **Verify V12 predictions:** `SELECT system_id, COUNT(*) FROM nba_predictions.player_prop_predictions WHERE game_date = '2026-02-19' GROUP BY system_id`

---

## Remaining Work (Future Sessions)

### Phase 3-5 of Column Migration (MEDIUM priority)
1. **Per-model quality gating** — V9 gates on features 0-36, V12 gates on features 0-53 minus dead (47, 50) and optional vegas (25-27). Add `v9_quality_ready` / `v12_quality_ready` logic.
2. **Update validation SQL** — Replace `features[OFFSET(N)]` with `feature_N_value` in monitoring queries.
3. **Stop writing arrays** — Remove `features` and `feature_names` from processor record (final cleanup).

### V12 Monitoring (HIGH priority after Feb 19)
1. Monitor V12 shadow predictions for 7 days (Feb 19-25)
2. Target: 60%+ HR edge 3+ in production
3. If validates: promote V12 to champion, retire decaying V9
4. Decision tree in Session 236 handoff

### Q43 Progression
- At 39/50 edge 3+ picks (78% toward promotion threshold)
- Feb 19 (10 games) could add 12-15 picks
- If Q43 reaches 50+ with 55%+ HR by Feb 22: promote Q43
- If not: V12 is the better option

### Model Registry
- Register V12 in model registry after shadow validation
- `./bin/model-registry.sh sync` after any manifest.json updates

---

## Files Modified

1. `data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py` — BDL → nbac_gamebook dependency, docstring updates
2. `data_processors/analytics/upcoming_player_game_context/calculators/quality_flags.py` — Source reference update
3. `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` — Session 237 dual-write (committed this session)
4. `schemas/bigquery/predictions/04_ml_feature_store_v2.sql` — Session 237 schema (committed this session)
5. `predictions/worker/data_loaders.py` — Individual column reading
6. `shared/ml/training_data_loader.py` — Individual columns in training SQL
7. `ml/experiments/quick_retrain.py` — NULL-aware prepare_features()
8. `predictions/coordinator/coordinator.py` — V12 shadow activation

---

## Start Prompt for Next Session

```
Read the latest handoff: docs/09-handoff/2026-02-13-SESSION-238-HANDOFF.md

Session 238 completed:
1. Fixed UPCG days_rest (BDL dependency time bomb, non-blocking completeness)
2. Migrated feature readers to individual columns (data_loaders.py, training_data_loader.py, quick_retrain.py)
3. Enabled V12 Model 1 shadow predictions (one-line coordinator change)

Priority tasks:
1. Feb 19 validation: Run /validate-daily and check V12 shadow predictions appear
2. Monitor V12 HR edge 3+ for promotion decision (target: 60%+)
3. Per-model quality gating (V9 vs V12 gate on different feature subsets)
```

---

**Handoff Complete. Next session: Feb 19 validation + V12 monitoring.**
