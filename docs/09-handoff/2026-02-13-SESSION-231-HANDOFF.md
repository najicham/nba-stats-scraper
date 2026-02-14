# Session 231 Handoff — V12 Feature Store Extension (39 → 54 Features)

## What Was Done

Extended ml_feature_store_v2 from 39 → 54 features so V12's 15 new features (indices 39-53) are computed during Phase 4 instead of at prediction time. This gives V12 features quality visibility, zero-tolerance gating, and feature-level debugging — same as all other features.

### Files Modified (8 files)

| File | Change |
|------|--------|
| `schemas/bigquery/predictions/04_ml_feature_store_v2.sql` | Added `feature_37_quality` through `feature_53_quality` (FLOAT64) and `feature_37_source` through `feature_53_source` (STRING) — 34 new columns in DDL + ALTER TABLE |
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | Expanded UPCG query (+4 fields: `minutes_in_last_7_days`, `game_spread`, `prop_over_streak`, `prop_under_streak`). Added `_batch_extract_player_rolling_stats()` query + 5 accessor methods. New query runs in parallel with existing 11. |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | `FEATURE_VERSION='v2_54features'`, `FEATURE_COUNT=54`, +15 FEATURE_NAMES, +15 ML_FEATURE_RANGES. Added V12 extraction block in `_extract_all_features()` for features 39-53. |
| `data_processors/precompute/ml_feature_store/quality_scorer.py` | `FEATURE_COUNT=54`. Updated `FEATURE_CATEGORIES` (player_history +6, game_context +9), `FEATURE_UPSTREAM_TABLES`, `DEFAULT_FALLBACK_REASONS`, `OPTIONAL_FEATURES` (+7: {41,42,47,50,51,52,53}). |
| `shared/ml/feature_contract.py` | `FEATURE_STORE_FEATURE_COUNT=54`, `CURRENT_FEATURE_STORE_VERSION='v2_54features'`, +15 FEATURE_STORE_NAMES. Updated `validate_all_contracts()`. |
| `predictions/worker/prediction_systems/catboost_v12.py` | **Removed `V12FeatureAugmenter` class entirely** (~290 lines of BigQuery batch queries). V12 now reads all 50 features by name from the feature store dict via `features.get(name)`. Removed `game_date` parameter (captured harmlessly via `**kwargs`). |
| `predictions/worker/prediction_systems/catboost_v8.py` | Added `'v2_54features'` to accepted `feature_version` allowlist (line 577). Without this, V8/V9 predictions would reject the new version string. |
| `shared/config/model_codenames.py` | Added codename `nova` for `catboost_v12`. |

### How Feature Retrieval Works (no changes needed)

The prediction worker data loader (`predictions/worker/data_loaders.py:980`) does:
```python
features = dict(zip(feature_names, feature_array))
```
Since we append 15 new names+values to both arrays, V12's `features.get('days_rest')` etc. automatically finds them. The data loader is version-agnostic.

### V12 Features 39-53 Mapping

| Idx | Name | Source | Notes |
|-----|------|--------|-------|
| 39 | `days_rest` | UPCG | phase3 |
| 40 | `minutes_load_last_7d` | UPCG | phase3 |
| 41 | `spread_magnitude` | abs(UPCG.game_spread) | **dead feature** — optional, default 5.0 |
| 42 | `implied_team_total` | (game_total ± spread)/2 | **dead feature** — optional, default 112.0 |
| 43 | `points_avg_last_3` | rolling stats query | calculated |
| 44 | `scoring_trend_slope` | OLS slope last 7 | calculated |
| 45 | `deviation_from_avg_last3` | z-score | calculated |
| 46 | `consecutive_games_below_avg` | cold streak | calculated |
| 47 | `teammate_usage_available` | always 0.0 | **dead feature** — optional |
| 48 | `usage_rate_last_5` | rolling stats query | calculated |
| 49 | `games_since_structural_change` | team/gap detection | calculated |
| 50 | `multi_book_line_std` | always 0.5 | **dead feature** — optional |
| 51 | `prop_over_streak` | UPCG | optional |
| 52 | `prop_under_streak` | UPCG | optional |
| 53 | `line_vs_season_avg` | vegas_line - season_avg | optional (0.0 if no vegas) |

Dead features (41, 42, 47, 50) produce constant values — they exist because V12 was trained with them. They're marked as `OPTIONAL_FEATURES` so they don't trigger zero-tolerance blocking.

### Validation Status

- `PYTHONPATH=. python -m shared.ml.feature_contract --validate` — ALL PASSED
- All 8 Python files compile cleanly (`py_compile`)
- Worker data loader verified — `dict(zip(feature_names, feature_array))` picks up new features automatically

## What's NOT Done — Deploy Checklist

### Step 1: Run ALTER TABLE on BigQuery

Run the ALTER TABLE statements from the DDL file to add 34 new columns to the live table. Extract the relevant statements:

```sql
-- Features 37-53 quality columns
ALTER TABLE `nba-props-platform.nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS feature_37_quality FLOAT64,
ADD COLUMN IF NOT EXISTS feature_38_quality FLOAT64,
ADD COLUMN IF NOT EXISTS feature_39_quality FLOAT64,
ADD COLUMN IF NOT EXISTS feature_40_quality FLOAT64,
ADD COLUMN IF NOT EXISTS feature_41_quality FLOAT64,
ADD COLUMN IF NOT EXISTS feature_42_quality FLOAT64,
ADD COLUMN IF NOT EXISTS feature_43_quality FLOAT64,
ADD COLUMN IF NOT EXISTS feature_44_quality FLOAT64,
ADD COLUMN IF NOT EXISTS feature_45_quality FLOAT64,
ADD COLUMN IF NOT EXISTS feature_46_quality FLOAT64,
ADD COLUMN IF NOT EXISTS feature_47_quality FLOAT64,
ADD COLUMN IF NOT EXISTS feature_48_quality FLOAT64,
ADD COLUMN IF NOT EXISTS feature_49_quality FLOAT64,
ADD COLUMN IF NOT EXISTS feature_50_quality FLOAT64,
ADD COLUMN IF NOT EXISTS feature_51_quality FLOAT64,
ADD COLUMN IF NOT EXISTS feature_52_quality FLOAT64,
ADD COLUMN IF NOT EXISTS feature_53_quality FLOAT64;

-- Features 37-53 source columns
ALTER TABLE `nba-props-platform.nba_predictions.ml_feature_store_v2`
ADD COLUMN IF NOT EXISTS feature_37_source STRING,
ADD COLUMN IF NOT EXISTS feature_38_source STRING,
ADD COLUMN IF NOT EXISTS feature_39_source STRING,
ADD COLUMN IF NOT EXISTS feature_40_source STRING,
ADD COLUMN IF NOT EXISTS feature_41_source STRING,
ADD COLUMN IF NOT EXISTS feature_42_source STRING,
ADD COLUMN IF NOT EXISTS feature_43_source STRING,
ADD COLUMN IF NOT EXISTS feature_44_source STRING,
ADD COLUMN IF NOT EXISTS feature_45_source STRING,
ADD COLUMN IF NOT EXISTS feature_46_source STRING,
ADD COLUMN IF NOT EXISTS feature_47_source STRING,
ADD COLUMN IF NOT EXISTS feature_48_source STRING,
ADD COLUMN IF NOT EXISTS feature_49_source STRING,
ADD COLUMN IF NOT EXISTS feature_50_source STRING,
ADD COLUMN IF NOT EXISTS feature_51_source STRING,
ADD COLUMN IF NOT EXISTS feature_52_source STRING,
ADD COLUMN IF NOT EXISTS feature_53_source STRING;
```

### Step 2: Commit & Push

```bash
git add schemas/bigquery/predictions/04_ml_feature_store_v2.sql \
  data_processors/precompute/ml_feature_store/feature_extractor.py \
  data_processors/precompute/ml_feature_store/ml_feature_store_processor.py \
  data_processors/precompute/ml_feature_store/quality_scorer.py \
  shared/ml/feature_contract.py \
  predictions/worker/prediction_systems/catboost_v12.py \
  predictions/worker/prediction_systems/catboost_v8.py \
  shared/config/model_codenames.py
git commit -m "feat: extend feature store to 54 features for V12"
git push origin main
```

Auto-deploys: `nba-phase4-precompute-processors` + `prediction-worker`.

### Step 3: Verify builds

```bash
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=5
```

### Step 4: Trigger Phase 4 reprocessing for today

Trigger via Pub/Sub or HTTP to reprocess today's features with the new 54-feature version.

### Step 5: Verify

```sql
-- Check feature count and version
SELECT feature_count, feature_version, ARRAY_LENGTH(features), ARRAY_LENGTH(feature_names)
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE()
LIMIT 5;
-- Expect: 54, 'v2_54features', 54, 54

-- Check V12 feature quality columns populated
SELECT feature_39_quality, feature_43_source, feature_48_source
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE()
LIMIT 5;
-- Expect: non-null values

-- Check V12 predictions still flowing
SELECT COUNT(*) FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v12' AND game_date = CURRENT_DATE();
```

## Future: Export Visibility for V12

After V12 predictions are validated with the new feature store:

1. **Add subset definitions** to BQ `dynamic_subset_definitions` table for `catboost_v12`
2. **Add public subset names** to `shared/config/subset_public_names.py`
3. **Add display info** to `MODEL_DISPLAY_INFO` in `shared/config/model_codenames.py`
4. Codename `nova` already registered.

## Risk Assessment

- **V8/V9 predictions**: Safe. They extract 33 features by name, ignore extras. Version allowlist updated.
- **V12 predictions**: Will work identically. Same features, just sourced from store instead of BigQuery queries. Actually **more reliable** because features get quality-gated.
- **Backward compatibility**: Old records (v2_39features) still readable. New records are v2_54features.
- **Rollback**: If issues, revert the commit. Old v2_39features code still works. ALTER TABLE columns are additive (IF NOT EXISTS).

## Key Design Decisions

1. **Dead features (41, 42, 47, 50)** output constant values — kept because V12 was trained with them. Marked OPTIONAL so they don't block zero-tolerance.
2. **Rolling stats query** runs in parallel with existing 11 queries (ThreadPoolExecutor 12 workers). Queries player_game_summary for last 60 days.
3. **`line_vs_season_avg` (feature 53)** computed from features[25] (vegas_points_line) minus features[2] (points_avg_season), defaulting to 0.0 if no vegas line.
4. **V12FeatureAugmenter removed** — was ~290 lines of BigQuery batch queries running at prediction time. Now Phase 4 handles it with quality visibility.
