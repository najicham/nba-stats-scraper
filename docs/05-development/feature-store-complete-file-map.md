# Feature Store: Complete File Map & Adding Features Guide

**Last Updated:** February 5, 2026 (Session 134)
**Companion to:** `ML-FEATURE-VERSION-UPGRADE-GUIDE.md` (challenger model pattern)

---

## Purpose

This document provides:
1. A complete map of every file that touches `ml_feature_store_v2`
2. The exact checklist for adding a new feature (every file to update)
3. Category definitions for the quality visibility system

For the challenger model pattern (shadow mode, A/B testing, promotion), see `ML-FEATURE-VERSION-UPGRADE-GUIDE.md`.

---

## Current Feature Set (37 features, v2_37features)

**Source of truth:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` lines 95-139

```
Index  Name                        Category         Source
-----  --------------------------  ---------------  -----------
 0     points_avg_last_5           player_history   phase4/phase3
 1     points_avg_last_10          player_history   phase4/phase3
 2     points_avg_season           player_history   phase4/phase3
 3     points_std_last_10          player_history   phase4/phase3
 4     games_in_last_7_days        player_history   phase4/phase3
 5     fatigue_score               matchup          phase4 (CRITICAL)
 6     shot_zone_mismatch_score    matchup          phase4 (CRITICAL)
 7     pace_score                  matchup          phase4 (CRITICAL)
 8     usage_spike_score           matchup          phase4 (CRITICAL)
 9     rest_advantage              game_context     calculated
10     injury_risk                 game_context     calculated
11     recent_trend                game_context     calculated
12     minutes_change              game_context     calculated
13     opponent_def_rating         matchup          phase3 (CRITICAL)
14     opponent_pace               matchup          phase3 (CRITICAL)
15     home_away                   game_context     calculated
16     back_to_back                game_context     calculated
17     playoff_game                game_context     calculated
18     pct_paint                   game_context     phase4
19     pct_mid_range               game_context     phase4
20     pct_three                   game_context     phase4
21     pct_free_throw              game_context     phase4
22     team_pace                   team_context     phase3
23     team_off_rating             team_context     phase3
24     team_win_pct                team_context     phase3
25     vegas_points_line           vegas            phase4
26     vegas_opening_line          vegas            phase4
27     vegas_line_move             vegas            calculated
28     has_vegas_line              vegas            calculated
29     avg_points_vs_opponent      player_history   phase4/phase3
30     games_vs_opponent           player_history   phase4/phase3
31     minutes_avg_last_10         player_history   phase4/phase3
32     ppm_avg_last_10             player_history   phase4/phase3
33     dnp_rate                    player_history   phase4
34     pts_slope_10g               player_history   calculated
35     pts_vs_season_zscore        player_history   calculated
36     breakout_flag               player_history   calculated
```

### Quality Category Mapping

| Category | Indices | Count | Notes |
|----------|---------|-------|-------|
| **matchup** | 5-8, 13-14 | 6 | CRITICAL - Session 132 issue area |
| **player_history** | 0-4, 29-36 | 13 | Largest category; 33-36 are trajectory/DNP features |
| **team_context** | 22-24 | 3 | Usually reliable |
| **vegas** | 25-28 | 4 | Low coverage is normal |
| **game_context** | 9-12, 15-21 | 11 | Mostly calculated features |
| **Total** | | **37** | |

---

## Complete File Map

### WRITE SIDE (Phase 4 processors — generate features)

| File | Role | What to Update |
|------|------|----------------|
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | **Main processor.** Defines `FEATURE_NAMES`, `FEATURE_COUNT`, `FEATURE_VERSION`, `ML_FEATURE_RANGES`. Orchestrates feature generation and writes records. | Add feature name to `FEATURE_NAMES` array, bump `FEATURE_COUNT` and `FEATURE_VERSION`, add validation range to `ML_FEATURE_RANGES` |
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | Queries Phase 3/4 upstream tables to extract raw data. Tracks provenance and fallback reasons. | Add extraction query for new feature's upstream data source |
| `data_processors/precompute/ml_feature_store/feature_calculator.py` | Calculates derived features (indices 9-12, 15-17, 27-28, 34-36). | Add calculation logic if the new feature is derived/calculated |
| `data_processors/precompute/ml_feature_store/quality_scorer.py` | Scores each feature's quality 0-100 based on source. | Add quality scoring rules for new feature, update category mapping |
| `data_processors/precompute/ml_feature_store/batch_writer.py` | Batches and writes to BigQuery via MERGE (upsert). | Usually no changes needed unless write pattern changes |
| `data_processors/precompute/ml_feature_store/breakout_risk_calculator.py` | Calculates breakout-specific scores. | Only if adding a breakout-related feature |

### READ SIDE (Phase 5 predictions — consume features)

| File | Role | What to Update |
|------|------|----------------|
| `predictions/worker/data_loaders.py` | Loads features from BigQuery. Auto-detects `feature_version`. | Update `_detect_feature_version()` to handle new version string |
| `predictions/worker/worker.py` | Orchestrates prediction systems. | Usually no changes unless adding a new prediction system |
| `predictions/worker/prediction_systems/catboost_v8.py` | CatBoost V8 model (accepts v2_33/37features, uses first 33). | No change if new feature is appended (V8 ignores extra features) |
| `predictions/worker/prediction_systems/catboost_v9.py` | CatBoost V9 model. | Same as V8 unless new model is trained on the new feature |
| `predictions/worker/prediction_systems/breakout_classifier_v1.py` | Breakout classifier. | Only if adding a breakout-specific feature |
| `predictions/worker/quality_tracker.py` | Monitors feature quality metrics. | Update if adding new quality thresholds |

### ML TRAINING (train models on features)

| File | Role | What to Update |
|------|------|----------------|
| `ml/features/breakout_features.py` | Shared breakout feature module. Defines V1/V2/V3 feature lists. | Only if adding a breakout feature |
| `ml/experiments/breakout_experiment_runner.py` | Trains breakout classifier. | Only if adding a breakout feature |
| `ml/experiments/train_walkforward.py` | Walk-forward model training. | Update feature count filter in training query |
| `ml/backfill_v8_predictions.py` | Backfills predictions. Filters by `feature_count IN (33, 37)`. | Add new feature_count to the IN clause |

### SCHEMA & VALIDATION

| File | Role | What to Update |
|------|------|----------------|
| `schemas/bigquery/predictions/04_ml_feature_store_v2.sql` | Master BigQuery schema definition. | Add `feature_N_quality` and `feature_N_source` columns for new index, update field summary, update ALTER TABLE, update unpivot view |
| `shared/validation/feature_store_validator.py` | Validates feature data. `EXPECTED_FEATURE_COUNT = 37`. | Bump `EXPECTED_FEATURE_COUNT`, add validation bounds for new feature |
| `bin/audit_feature_store.py` | Audit script. `FEATURE_SPECS` defines 37 features with validation rules. | Add new feature to `FEATURE_SPECS` with min/max/allow_null/check_constant |

### ORCHESTRATION & MONITORING

| File | Role | What to Update |
|------|------|----------------|
| `orchestration/cloud_functions/phase4_to_phase5/main.py` | Phase 4→5 trigger. Detects ml_feature_store completion. | No changes needed |
| `bin/monitoring/feature_store_health_check.py` | Health check monitoring. | No changes needed (reads dynamically) |
| `bin/monitoring/pipeline_canary_queries.py` | Pipeline canary checks. | No changes needed |

### TESTS

| File | Role | What to Update |
|------|------|----------------|
| `tests/unit/data_processors/test_ml_feature_store.py` | Unit tests for quality_scorer, feature_calculator, validation. | Add test cases for new feature's quality scoring and calculation |

---

## Step-by-Step: Adding a New Feature

### Phase 1: Implement (files to change)

**Step 1: Feature definition** — `ml_feature_store_processor.py`
```python
# 1a. Add to FEATURE_NAMES (ALWAYS at the END)
FEATURE_NAMES = [
    # ... existing 37 features ...
    'my_new_feature',  # NEW: Feature 37
]

# 1b. Bump count and version
FEATURE_COUNT = 38  # Was 37
FEATURE_VERSION = 'v2_38features'  # Was v2_37features

# 1c. Add validation range
ML_FEATURE_RANGES = {
    # ... existing ranges ...
    37: (0.0, 100.0, False),  # (min, max, is_critical)
}
```

**Step 2: Data extraction** — `feature_extractor.py`
- If the feature comes from an upstream table: add query to fetch the data
- If calculated on-the-fly: skip this step

**Step 3: Feature calculation** — `feature_calculator.py` or `ml_feature_store_processor.py`
```python
# In _extract_all_features() or equivalent:
new_value = calculate_my_new_feature(player_data)
features.append(new_value)
feature_sources[37] = 'calculated'  # or 'phase4', 'phase3'
```

**Step 4: Quality scoring** — `quality_scorer.py`
- Add the new feature index to the appropriate category in `FEATURE_CATEGORIES`
- Define quality scoring rules (what constitutes good vs bad data)

**Step 5: Schema** — `04_ml_feature_store_v2.sql`
```sql
-- Add to CREATE TABLE:
feature_37_quality FLOAT64 OPTIONS(description='Quality 0-100 for feature 37 (my_new_feature)'),
feature_37_source STRING OPTIONS(description='Source for feature 37 (my_new_feature): phase4, phase3, calculated, default'),

-- Add to ALTER TABLE:
ADD COLUMN IF NOT EXISTS feature_37_quality FLOAT64 OPTIONS (description='...'),
ADD COLUMN IF NOT EXISTS feature_37_source STRING OPTIONS (description='...'),

-- Add to unpivot view:
UNION ALL SELECT player_lookup, game_date, 37, 'my_new_feature', feature_37_quality, feature_37_source FROM ...
```

**Step 6: Validation** — `feature_store_validator.py` and `audit_feature_store.py`
- Bump `EXPECTED_FEATURE_COUNT` to 38
- Add feature bounds to `FEATURE_SPECS`

**Step 7: Tests** — `test_ml_feature_store.py`
- Add test for the new feature's calculation
- Add test for quality scoring

### Phase 2: Consumer updates

**Step 8: Data loader** — `data_loaders.py`
- Update `_detect_feature_version()` to handle `v2_38features`

**Step 9: Backfill** — Generate historical data
```bash
PYTHONPATH=. python bin/backfill_ml_feature_store.py \
    --start-date 2025-11-01 \
    --end-date 2026-02-05 \
    --feature-version v2_38features
```

**Step 10: Train new model** — See `ML-FEATURE-VERSION-UPGRADE-GUIDE.md` for challenger pattern

### Phase 3: Deploy

**Step 11: Deploy Phase 4 processors**
```bash
./bin/deploy-service.sh nba-phase4-precompute-processors
```

**Step 12: Deploy prediction worker** (after model is trained)
```bash
./bin/deploy-service.sh prediction-worker
```

---

## Quick Checklist

Copy this when adding a feature:

```
- [ ] ml_feature_store_processor.py: FEATURE_NAMES, FEATURE_COUNT, FEATURE_VERSION, ML_FEATURE_RANGES
- [ ] feature_extractor.py: Add extraction query (if upstream data)
- [ ] feature_calculator.py: Add calculation logic (if derived)
- [ ] quality_scorer.py: Add to FEATURE_CATEGORIES, define quality rules
- [ ] 04_ml_feature_store_v2.sql: CREATE TABLE + ALTER TABLE + unpivot view
- [ ] feature_store_validator.py: Bump EXPECTED_FEATURE_COUNT, add bounds
- [ ] audit_feature_store.py: Add to FEATURE_SPECS
- [ ] test_ml_feature_store.py: Add tests
- [ ] data_loaders.py: Update _detect_feature_version()
- [ ] backfill_v8_predictions.py: Add new count to IN clause
- [ ] Backfill historical data
- [ ] Train challenger model (see ML-FEATURE-VERSION-UPGRADE-GUIDE.md)
- [ ] Deploy nba-phase4-precompute-processors
- [ ] Deploy prediction-worker (after model trained)
```

---

## Common Pitfalls

### 1. Feature index mismatch
New features MUST go at the END of `FEATURE_NAMES`. Never insert in the middle — models learn by position, not by name.

### 2. Forgetting the schema quality columns
If you add feature 37, you need `feature_37_quality` and `feature_37_source` columns in the SQL schema, the ALTER TABLE, AND the unpivot view. Three places.

### 3. Category mapping gap
Every feature must belong to exactly one quality category. If you add a feature and don't add it to `FEATURE_CATEGORIES` in `quality_scorer.py`, it becomes a monitoring blind spot.

### 4. Validator count mismatch
`feature_store_validator.py` has `EXPECTED_FEATURE_COUNT = 37`. If you bump the processor to 38 features but forget to update the validator, all records will fail validation.

### 5. Data loader version detection
`data_loaders.py` auto-detects feature versions. If it doesn't know about `v2_38features`, it will fall back to an older version and your new feature won't be loaded.

### 6. Backfill before training
You must backfill historical feature store data with the new feature BEFORE training a model. The model needs training data that includes the new feature.

---

## Upstream Dependencies

The feature store reads from these Phase 3/4 tables:

| Upstream Table | Features Fed | Phase |
|----------------|-------------|-------|
| `player_daily_cache` | 0-4, 31-32 (performance stats) | Phase 4 |
| `player_composite_factors` | 5-8 (composite factors) | Phase 4 |
| `player_shot_zone_analysis` | 18-21 (shot zones) | Phase 4 |
| `team_defense_zone_analysis` | 13-14 (opponent defense) | Phase 3 |
| `player_game_summary` | Historical stats for calculations | Phase 3 |
| `upcoming_player_game_context` | Schedule, rest, opponent info | Phase 3 |
| `team_offense_game_summary` | 22-24 (team context) | Phase 3 |
| `odds_api_*` tables | 25-28 (vegas lines) | Phase 2 |

When adding a feature from a NEW upstream source, you also need to:
1. Add source tracking fields (`source_*_last_updated`, etc.) to the schema
2. Update `feature_extractor.py` to query the new source
3. Ensure the new source runs BEFORE the feature store processor in Phase 4 orchestration

---

## Downstream Consumers

These systems read from the feature store:

| Consumer | What it reads | Impact of feature change |
|----------|--------------|-------------------------|
| `prediction-worker` | Feature arrays for predictions | Must handle new version |
| CatBoost V8/V9 models | First 33 features by position | Appended features are ignored |
| Breakout classifier | Subset of features by name | Only affected if breakout feature added |
| Training scripts | Historical features for model training | Need backfill with new feature |
| `/validate-daily` skill | Quality metrics | Auto-adapts if quality columns exist |
| `v_feature_quality_unpivot` view | Quality columns | Must add new feature row |

---

## References

- **Challenger model pattern:** `docs/05-development/ML-FEATURE-VERSION-UPGRADE-GUIDE.md`
- **Quality visibility design:** `docs/08-projects/current/feature-quality-visibility/07-FINAL-HYBRID-SCHEMA.md`
- **Schema definition:** `schemas/bigquery/predictions/04_ml_feature_store_v2.sql`
- **Feature processor:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
