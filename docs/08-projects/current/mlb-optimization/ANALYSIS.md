# MLB Batch Prediction Analysis

**Date**: 2026-01-17
**Analyzed by**: Claude Code

## Current System Architecture

### Prediction Systems (3 systems running concurrently)
1. `v1_baseline` - Original baseline model (25 features)
2. `v1_6_rolling` - Enhanced model (35 features, rolling Statcast metrics)
3. `ensemble_v1` - Weighted ensemble (30% V1 + 50% V1.6)

### Batch Prediction Flow (Current)

**File**: `/predictions/mlb/worker.py:308-374` (`run_multi_system_batch_predictions`)

```
1. Create temp PitcherStrikeoutsPredictor
2. Call temp_predictor.batch_predict(game_date, pitcher_lookups)
   - This executes a BigQuery query loading features for all pitchers
3. Loop through predictions
4. Only v1_baseline predictions are returned
5. Other systems (v1_6_rolling, ensemble_v1) are SKIPPED with TODO comment
```

**Key Code (worker.py:326-367)**:
```python
# Line 326-327: Comment says this avoids redundant queries, but NOT IMPLEMENTED
# Use first system to load features (all systems use same feature source)
# This avoids redundant BigQuery queries

# Line 336: Loads features via BigQuery
predictions_v1 = temp_predictor.batch_predict(game_date, pitcher_lookups)

# Line 352-368: Only v1_baseline used, others skipped
for system_id, predictor in systems.items():
    if system_id == 'v1_baseline':
        prediction = v1_pred.copy()
        prediction['system_id'] = system_id
        all_predictions.append(prediction)
    else:
        # For other systems, we need to call their predict() method
        # For Phase 2, we'll skip other systems in batch mode
        logger.debug(f"Skipping {system_id} in batch mode for Phase 2")
```

## Problem Identified

### Issue #1: Incomplete Multi-System Implementation
- **Impact**: Only v1_baseline predictions are generated in batch mode
- **Expected**: All 3 systems should generate predictions
- **Current**: v1_6_rolling and ensemble_v1 are skipped

### Issue #2: Inefficient Feature Loading (If Implemented Fully)
- **Current potential flow** (if systems were fully integrated):
  - v1_baseline calls batch_predict() → BigQuery query
  - v1_6_rolling calls batch_predict() → Same BigQuery query again
  - ensemble_v1 calls batch_predict() → Same BigQuery query again
- **Impact**: 3x redundant BigQuery queries (66% waste)
- **Cost**: ~15-20 seconds for 20 pitchers → could be 8-12 seconds with optimization

### Issue #3: No Feature Coverage Tracking
- **Current**: Missing features default to hardcoded values silently
- **Impact**: No visibility into data quality issues
- **Example**: Prediction with 10/35 features missing shows 75% confidence

## BigQuery Feature Query

**Current query** (in `pitcher_strikeouts_predictor.py:984-1066`):

Joins three tables:
1. `mlb_analytics.pitcher_game_summary` - Core features (rolling stats, season stats, workload)
2. `mlb_analytics.pitcher_rolling_statcast` - Statcast features (SwStr%, velocity)
3. `mlb_raw.bp_pitcher_props` - BettingPros projections

**Features loaded** (35 total for V1.6):
- Rolling stats: k_avg_last_3/5/10, k_std_last_10, ip_avg_last_5
- Season stats: k_per_9, ERA, WHIP, games, K total
- Context: is_home, opponent_k_rate, ballpark_factor
- Workload: days_rest, games_last_30_days, pitch_count
- Statcast (V1.6): swstr_pct_last_3, fb_velocity_last_3, swstr_trend
- BettingPros (V1.6): projection, performance %s

## Solution Design

### Optimization #1: Shared Feature Loader

Create `load_batch_features()` function that:
1. Executes BigQuery query ONCE for all pitchers
2. Returns `Dict[pitcher_lookup, features]` mapping
3. Worker calls this once, then passes preloaded features to each system's `predict()`

**Expected improvement**:
- Reduce from 3 queries to 1 query (66% reduction)
- Batch time: 15-20s → 8-12s (30-40% faster)

### Implementation Plan

1. **Create shared loader** in `/predictions/mlb/pitcher_loader.py`:
   - Function: `load_batch_features(game_date, pitcher_lookups, project_id)`
   - Returns: `Dict[str, Dict]` - pitcher_lookup → features dict
   - Uses existing query from pitcher_strikeouts_predictor.py

2. **Update worker.py**:
   - Replace `temp_predictor.batch_predict()` with `load_batch_features()`
   - Loop through pitchers and features
   - For each pitcher, call each system's `predict(features=preloaded_features)`
   - Collect predictions from all systems (not just v1_baseline)

3. **Modify base predictor** (if needed):
   - Ensure `predict()` accepts preloaded features
   - Skip feature loading if features are provided

## Performance Targets

| Metric | Current | Target | Improvement |
|--------|---------|--------|-------------|
| BigQuery queries per batch | 3 (if all systems active) | 1 | -66% |
| Batch time (20 pitchers) | 15-20s | 8-12s | 30-40% |
| Systems in batch mode | 1 (v1_baseline only) | 3 (all active) | +200% |

## Risk Assessment

**Risk Level**: LOW
- Changes are performance-focused, not algorithmic
- No changes to prediction logic
- Easy to test and rollback
- Backward compatible (single predictions unchanged)

## Next Steps

1. ✅ Analysis complete
2. ⏳ Implement `load_batch_features()` in pitcher_loader.py
3. ⏳ Update `run_multi_system_batch_predictions()` in worker.py
4. ⏳ Test with sample date
5. ⏳ Benchmark performance improvement
