# Morning Investigation Feb 3 - Feature Store Quality Issue

**Date:** 2026-02-03
**Issue:** ML Feature Store producing 65% quality features instead of 85%+

## Root Cause Analysis

### Problem
Phase 4 processors (player_daily_cache, player_composite_factors, etc.) process **completed games** and store data with `game_date = yesterday`. When ML Feature Store runs for **today's upcoming games**, it queries with `WHERE game_date = TODAY` and finds **zero rows**.

### Why This Happened
1. **Architectural Assumption Violation**: The MLFeatureStoreProcessor was designed assuming Phase 4 data would be available for the exact `game_date`. This works for backfill but fails for upcoming games.

2. **Dependency Check Failure**: The processor has strict dependency checks that fail when Phase 4 tables have 0 rows for today:
   - PlayerDailyCacheProcessor: 0% coverage (needs 70%)
   - PlayerCompositeFactorsProcessor: 0% coverage (needs 70%)
   - PlayerShotZoneAnalysisProcessor: 0% coverage (needs 70%)
   - TeamDefenseZoneAnalysisProcessor: 0% coverage (needs 80%)

3. **Workaround Required**: Must pass `strict_mode: false` AND `skip_dependency_check: true` to bypass checks.

### What Was Fixed
Session 95 added fallback queries to all Phase 4 extractors:
- `_batch_extract_daily_cache()` - Uses most recent cache_date per player (14-day lookback)
- `_batch_extract_composite_factors()` - Uses most recent game_date per player (7-day lookback)
- `_batch_extract_shot_zone()` - Uses most recent analysis_date per player (14-day lookback)
- `_batch_extract_team_defense()` - Uses most recent analysis_date per team (7-day lookback)

### Remaining Issue
Debug logs show:
- Fallback queries return 521 composite factors
- Batch cache is being used (`use_batch=True`)
- Players are found in lookup (`found=True`)
- BUT: Feature calculation still reports 0/339 from Phase 4

Further investigation needed to trace why lookup data isn't being used during feature calculation.

## Impact on Daily Orchestration

### Current State
- Today's predictions were made with **65% feature quality** (should be 85%+)
- Quality gate system deployed but not yet effective
- Predictions may have underprediction bias (false high-edge UNDER picks)

### Risk Assessment
| Scenario | Hit Rate |
|----------|----------|
| GREEN signal + High Quality | 66.9% |
| RED signal + High Quality | 54.8% |
| RED signal + Low Quality | **45.5%** |

## Recommended Fixes

### Immediate: Update Scheduler Jobs
The `ml-feature-store-7am-et` and `ml-feature-store-1pm-et` jobs need to pass bypass flags:

```bash
# Update ml-feature-store-7am-et
gcloud scheduler jobs update http ml-feature-store-7am-et \
  --location=us-west2 \
  --message-body='{"processors": ["MLFeatureStoreProcessor"], "analysis_date": "TODAY", "strict_mode": false, "skip_dependency_check": true}'

# Update ml-feature-store-1pm-et
gcloud scheduler jobs update http ml-feature-store-1pm-et \
  --location=us-west2 \
  --message-body='{"processors": ["MLFeatureStoreProcessor"], "analysis_date": "TODAY", "strict_mode": false, "skip_dependency_check": true}'
```

### Medium-term: Fix Feature Calculation Bug
1. Add more debug logging to trace why composite_factors lookup data isn't being used
2. Check for type mismatches or field name mismatches between extraction and calculation
3. Verify BigQuery returns proper Python types (not NaN/None issues)

### Long-term: Architectural Improvements
1. **Upcoming Game Mode**: Add explicit mode for ML Feature Store that:
   - Skips date-specific dependency checks
   - Uses fallback queries by default
   - Logs quality degradation appropriately

2. **Monitoring**: Add alerts for:
   - Feature quality dropping below 80%
   - Composite factors usage at 0%
   - Phase 4 data availability for upcoming games

3. **Documentation**: Update Phase 4 docs to clarify:
   - Tables contain data for completed games only
   - Upcoming game predictions need fallback logic

## Commits Made
```
df8448bc fix: Add fallback to recent data for all Phase 4 extractors (Session 95)
281e30f8 chore: Add WARNING-level logs to debug fallback extraction (Session 95)
16cdd540 chore: Add DEBUG_COMPOSITE logging
```

## Verification Queries

### Check Feature Quality
```sql
SELECT
  ROUND(AVG(feature_quality_score), 1) as avg_quality,
  COUNTIF(feature_quality_score >= 85) as high_quality,
  COUNTIF(feature_quality_score < 80) as low_quality,
  COUNT(*) as total
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE()
```

### Check Phase 4 Data Availability
```sql
SELECT 'composite_factors' as table_name, MAX(game_date) as latest_date
FROM nba_precompute.player_composite_factors
UNION ALL
SELECT 'daily_cache', MAX(cache_date)
FROM nba_precompute.player_daily_cache
```

### Check Prediction Quality Impact
```sql
SELECT
  prediction_attempt,
  ROUND(AVG(feature_quality_score), 1) as avg_quality,
  COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND is_active = TRUE
GROUP BY prediction_attempt
```
