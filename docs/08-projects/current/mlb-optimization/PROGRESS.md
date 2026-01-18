# MLB Optimization Progress

**Last Updated**: 2026-01-17

## Completed Tasks

### ✅ Optimization #1: Shared Feature Loader (COMPLETE)

**Problem Solved**:
- Previously: Each prediction system would call `batch_predict()` separately
- Impact: 3x redundant BigQuery queries for the same features
- Cost: 15-20 seconds for 20 pitchers

**Implementation**:
1. Created `load_batch_features()` in `/predictions/mlb/pitcher_loader.py`
   - Single BigQuery query loads all features for all pitchers
   - Returns `Dict[pitcher_lookup, features]` mapping
   - Joins 3 tables: pitcher_game_summary, pitcher_rolling_statcast, bp_pitcher_props

2. Updated `run_multi_system_batch_predictions()` in `/predictions/mlb/worker.py`
   - Calls `load_batch_features()` ONCE
   - Loops through pitchers and systems
   - Passes preloaded features to each system's `predict()`
   - **Now generates predictions from ALL systems** (v1_baseline, v1_6_rolling, ensemble_v1)
   - Previous version only returned v1_baseline predictions

**Expected Results**:
- 66% reduction in BigQuery queries (from 3 to 1)
- 30-40% faster batch times (15-20s → 8-12s for 20 pitchers)
- All 3 systems now functional in batch mode

**Files Modified**:
- `/predictions/mlb/pitcher_loader.py` - Added `load_batch_features()` function
- `/predictions/mlb/worker.py` - Rewrote `run_multi_system_batch_predictions()`

---

### ✅ Optimization #2: Feature Coverage Tracking (IN PROGRESS)

**Problem Solved**:
- Previously: Missing features default to hardcoded values silently
- Impact: No visibility into data quality, false confidence in low-data scenarios
- Example: Prediction with 10/35 features missing shows 75% confidence (misleading)

**Implementation (Step 1/3 COMPLETE)**:
1. ✅ Added feature coverage methods to `/predictions/mlb/base_predictor.py`:
   - `_calculate_feature_coverage(features, required_features)` - Calculates % of non-null features
   - `_adjust_confidence_for_coverage(confidence, coverage_pct)` - Adjusts confidence based on coverage

   Coverage penalties:
   - >= 90%: No reduction
   - 80-89%: -5 confidence points
   - 70-79%: -10 confidence points
   - 60-69%: -15 confidence points
   - < 60%: -25 confidence points

**Remaining Steps**:
2. ⏳ Integrate into prediction systems' `predict()` methods
3. ⏳ Add `feature_coverage_pct` to prediction output
4. ⏳ Create BigQuery schema migration

---

## In Progress

### ⏳ Optimization #3: IL Cache Reliability
- Add retry logic with exponential backoff
- Reduce TTL from 6hrs to 3hrs
- Fail-safe: return empty set instead of stale cache

### ⏳ Optimization #4: Configurable Alert Thresholds
- Create AlertConfig class
- Make thresholds environment variable configurable
- Update deployment script

---

## Next Steps

1. Complete feature coverage integration (add to predict() methods)
2. Create BigQuery schema migration for `feature_coverage_pct` column
3. Implement IL cache retry logic
4. Configure alert thresholds
5. Create performance benchmarking script
6. Test all optimizations
7. Document and create completion handoff

---

## Performance Targets

| Metric | Current | Target | Status |
|--------|---------|--------|--------|
| BigQuery queries per batch | 3 | 1 | ✅ COMPLETE |
| Batch time (20 pitchers) | 15-20s | 8-12s | 🔄 Testing needed |
| Systems in batch mode | 1 (v1 only) | 3 (all) | ✅ COMPLETE |
| Feature coverage tracking | None | All predictions | 🔄 In progress |
| IL cache reliability | Stale fallback | Retry + fail-safe | ⏳ Not started |
| Alert threshold config | Hardcoded | Env vars | ⏳ Not started |
