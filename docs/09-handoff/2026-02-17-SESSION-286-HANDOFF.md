# Session 286 Handoff — Features Array Migration (Phases 1-4)

**Date:** 2026-02-17
**Focus:** Migrate all production, validation, and monitoring code off `features` ARRAY column to individual `feature_N_value` columns
**Status:** Phases 1-4 DONE (21 files, 843 insertions). Phases 5-8 remain for next session.

---

## What Was Done

### Phase 1: Column-Array Consistency Validation

Added new validation to catch future regressions during the migration:

| File | Change |
|------|--------|
| `shared/ml/feature_contract.py` | Added `build_feature_array_from_columns(row, num_features=54)` — reconstructs feature list from individual columns for training/augmentation code |
| `shared/validation/feature_store_validator.py` | Added `check_column_array_consistency()` function + `ColumnArrayConsistencyResult` dataclass. Checks core features (0-36) are >50% populated per date. FAIL if any drop to 0%. Wired into `validate_feature_store()` |
| `validation/validators/precompute/ml_feature_store_validator.py` | Added Check 14 (`_validate_column_population`). Also migrated Checks 5, 12, 13 off array |

### Phase 2: P0 Critical Production Files (3 files)

| File | Change |
|------|--------|
| `data_processors/publishing/results_exporter.py` | `features[OFFSET(2)]` → `feature_2_value`, `features[OFFSET(16)]` → `feature_16_value` |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | 2 injury PPG lookup queries: `features[OFFSET(2)]` → `feature_2_value` |
| `ml/experiments/quick_retrain.py` | WHERE clauses migrated, augmentation functions use `build_feature_array_from_columns()`, full-pop MAE section migrated. SQL SELECTs changed to `SELECT mf.*` with post-query reconstruction |

### Phase 3: Partially-Migrated Files (3 files)

| File | Change |
|------|--------|
| `predictions/worker/data_loaders.py` | Removed `features`/`feature_names` from SQL SELECT, removed array fallback branch, removed `features_array` backward-compat |
| `shared/ml/training_data_loader.py` | Removed `mf.features`/`mf.feature_names` from SQL SELECT |
| `ml/experiments/season_replay_full.py` | Removed `mf.features`/`mf.feature_names` from both train and eval queries |

### Phase 4: Validation & Monitoring Files (12 files)

| File | Pattern Replaced |
|------|-----------------|
| `shared/validation/feature_drift_detector.py` | 7 dynamic `features[OFFSET({idx})]` → `feature_{idx}_value` |
| `shared/validation/continuous_validator.py` | `features[OFFSET(25)]` → `feature_25_value` |
| `predictions/worker/quality_tracker.py` | `features[SAFE_OFFSET(18)]` → `feature_18_value` |
| `bin/audit_feature_store.py` | 8 dynamic array accesses → individual columns |
| `bin/monitoring/model_drift_detection.py` | `mf.features[0/1]` → `mf.feature_0_value`/`feature_1_value` |
| `ml/experiments/evaluate_model.py` | `features[OFFSET(25/28)]` → `feature_25_value`/`feature_28_value` |
| `data_processors/ml_feedback/scoring_tier_processor.py` | `features[OFFSET(2)]` → `feature_2_value` |
| `bin/validation/validate_feature_store_v33.py` | 3 `features[OFFSET(N)]` → `feature_N_value` |
| `validation/queries/monitoring/breakout_filter_monitoring.sql` | ~10 replacements across 6 queries |
| `validation/queries/monitoring/feature_quality_check.sql` | Rewrote using UNPIVOT pattern (CROSS JOIN UNNEST of individual columns) |
| `schemas/bigquery/predictions/views/v_daily_validation_summary.sql` | `fs.features[OFFSET(0)]` → `fs.feature_0_value` |

---

## What Remains (Phases 5-8)

### Phase 5: Migrate Backfill & Tool Scripts (4 files)

| File | Change Needed |
|------|---------------|
| `bin/spot_check_features.py` | Replace `features, feature_names` read → read `feature_N_value` columns directly |
| `bin/backfill-challenger-predictions.py` | Replace `row['features']` → `build_feature_array_from_columns()` |
| `bin/backfill-v12-predictions.py` | Remove array fallback, use columns only |
| `bin/backfill-v9-no-line-predictions.py` | Remove array fallback, use columns only |

### Phase 6: Implement Dead Features (f47, f50)

**Feature 47: `teammate_usage_available`**
- SUM of usage_rate for OUT/DOUBTFUL teammates
- Cross-reference `nbac_injury_report` with `player_daily_cache` (their usage rates)
- Implement in `ml_feature_store_processor.py` near `_calculate_team_key_injury_impact()`
- Default when no injuries: 0.0
- Update `feature_contract.py` source classification

**Feature 50: `multi_book_line_std`**
- Standard deviation of player points prop lines across sportsbooks
- Query `odds_api_player_points` for all sportsbook lines, compute STDDEV
- Implement in `ml_feature_store_processor.py` in Vegas line extraction section
- Default when only 1 book: NULL
- Update `feature_contract.py` source classification

### Phase 7: Comprehensive Validation Run

```bash
# Full validation including new column consistency check
PYTHONPATH=. python -m shared.validation.feature_store_validator --days 90

# Spot check individual player features
python bin/spot_check_features.py

# Audit all features within bounds using columns
python bin/audit_feature_store.py --start-date 2025-11-04 --end-date 2026-02-17

# Verify f47/f50 are populated for recent dates
bq query "SELECT game_date, COUNTIF(feature_47_value IS NOT NULL) as f47_pop, COUNTIF(feature_50_value IS NOT NULL) as f50_pop FROM nba_predictions.ml_feature_store_v2 WHERE game_date >= '2026-02-17' GROUP BY 1"
```

### Phase 8: Remove Array Column (FUTURE — after 2+ weeks stable)

1. Stop dual-writing: remove `features` array from processor output
2. Drop `features` and `feature_names` columns from BigQuery schema
3. Remove `EXPECTED_FEATURE_COUNT` and array-related constants
4. Update CLAUDE.md to reflect new architecture

---

## Remaining Array References (not in scope for migration)

These files still use `features[OFFSET]` but are NOT production code:

| File | Reason to Skip |
|------|----------------|
| `backfill_jobs/feature_store/fix_team_win_pct.py` | One-off historical backfill |
| `scripts/backfill_feature_store_vegas.py` | One-off backfill script |
| `ml/archive/` (3 files) | Archived experiments |
| `tests/integration/monitoring/test_vegas_line_coverage.py` | Integration test (update when convenient) |
| `schemas/bigquery/patches/*.sql` | Historical one-off patches |
| `bin/queries/daily_feature_completeness.sql` | Query tool (Phase 5) |

---

## Key Design Decisions

1. **`build_feature_array_from_columns()` helper** — Bridges the gap for code that needs an ordered list (training augmentation, prepare_features). Lives in `shared/ml/feature_contract.py`. Handles NULL→NaN conversion for CatBoost compatibility.

2. **`SELECT mf.*` pattern in quick_retrain.py** — The three eval-data SQL functions use `SELECT mf.*` to pull all `feature_N_value` columns, then reconstruct a `features` list column via `build_feature_array_from_columns`. This keeps the augmentation write-back pattern working.

3. **UNPIVOT pattern in feature_quality_check.sql** — The dynamic `CROSS JOIN feature_definitions` with `features[SAFE_OFFSET(fd.idx)]` couldn't use `feature_{fd.idx}_value` dynamically. Replaced with `CROSS JOIN UNNEST([STRUCT(0 AS idx, feature_0_value AS val), ...])` pattern.

4. **Array column kept for now** — The `features` array is still written (dual-write) and still in the schema. Phase 8 removes it after stability is confirmed.

---

## Verification Done

- All 13 modified Python files pass `py_compile` syntax checks
- `quick_retrain.py`, `data_loaders.py`, `training_data_loader.py`, `season_replay_full.py` all pass syntax checks (confirmed by agents)
- No `features[OFFSET` or `features[SAFE_OFFSET` patterns remain in production/monitoring code
- Remaining hits are all in archive, one-off patches, or Phase 5 scope
