# Session 122 Handoff - Tier Classification Boundary Fix Complete

**Date:** 2025-12-10
**Focus:** Completed tier boundary fix and analyzed results

---

## Executive Summary

Sessions 120-121 identified and fixed two related bugs in scoring tier adjustments:

1. **Session 120 Bug**: Tiers classified by predicted_points instead of season_avg
2. **Session 121 Bug**: Tier boundaries didn't match tier names

Both fixes are now in place. The backfill is running but hitting BigQuery streaming buffer errors on recent dates.

---

## Bug History

### Session 120: Wrong Classification Basis
- **Problem**: Tiers were classified using `predicted_points` instead of `season_avg`
- **Impact**: A star player predicted to score 5 points (injury/rest) got BENCH tier adjustments
- **Fix**: Added `classify_tier_by_season_avg()` method using season average from ML features

### Session 121: Wrong Tier Boundaries
- **Problem**: Even with season_avg, boundaries didn't match tier names:
  | Tier Name | Old Boundary | Correct Boundary |
  |-----------|--------------|------------------|
  | STAR_30PLUS | >= 25 | >= 30 |
  | STARTER_20_29 | >= 18 | >= 20 |
  | ROTATION_10_19 | >= 10 | >= 10 |
  | BENCH_0_9 | < 10 | < 10 |

- **Impact**: Players with 25-29 ppg got massive +12 pt adjustments meant for 30+ scorers
- **Evidence**: STAR_30PLUS tier showed avg_season_ppg = 26.7, max = 29.9 (NO actual 30+ scorers!)

---

## Fixes Applied

### File: `data_processors/ml_feedback/scoring_tier_processor.py`

```python
# Lines 326-336 - classify_tier_by_season_avg()
# BEFORE (WRONG)
if season_avg >= 25:
    return 'STAR_30PLUS'
elif season_avg >= 18:
    return 'STARTER_20_29'

# AFTER (CORRECT)
if season_avg >= 30:
    return 'STAR_30PLUS'
elif season_avg >= 20:
    return 'STARTER_20_29'
elif season_avg >= 10:
    return 'ROTATION_10_19'
else:
    return 'BENCH_0_9'
```

### File: `backfill_jobs/prediction/player_prop_predictions_backfill.py`

- Lines 626-634: Extract season_avg from features and pass through predictions dict
- Lines 490-494: Use `classify_tier_by_season_avg(tier_basis)` with season_avg

---

## Current State

### Backfill Progress
- **Shell ID**: `1e2085`
- **Status**: Running at 11/33 dates (Dec 15)
- **Issue**: Streaming buffer errors on Dec 5-14 (can't update recent data)

### Data Verification (Before Fix Applied)

Tier distribution showing misclassification:
```
| scoring_tier   | count | avg_season_ppg | min | max  | avg_predicted |
|----------------|-------|----------------|-----|------|---------------|
| BENCH_0_9      |  2743 |            5.3 | 0.0 | 13.5 |           4.3 |
| ROTATION_10_19 |  1957 |           12.8 | 5.5 | 22.5 |          12.1 |
| STARTER_20_29  |   336 |           21.4 |14.7 | 27.6 |          21.0 |
| STAR_30PLUS    |   106 |           26.6 |23.5 | 29.9 |          27.1 |
```

**Note**: This data is from BEFORE the fix - the fix is being applied now.

### Feature Distribution (Reality Check)
```
| season_ppg_bucket | count |
|-------------------|-------|
|              30.0 |     9 |  <- Very few 30+ scorers!
|              29.0 |     6 |
|              28.0 |    18 |
|              27.0 |    41 |
|              26.0 |    56 |
|              25.0 |    32 |
```

**Key Insight**: In early 2021-22 season, only 9 player-game records had season_avg >= 30 ppg. This is expected - very few players average 30+ for a full season.

---

## Next Steps

### Immediate (When Backfill Completes)
1. Wait for backfill to complete (~5-10 min remaining)
2. Streaming buffer will prevent Dec 5-14 updates

### After Streaming Buffer Clears (~90 min)
1. Re-run backfill for Dec 5-14 to apply corrected tier logic
2. Run grading backfill to update prediction_accuracy table
3. Analyze MAE by tier to verify improvement

### Validation Query
```sql
-- Verify tier classification after fix
WITH mlfs AS (
  SELECT player_lookup, game_date, features[OFFSET(2)] as season_avg
  FROM nba_predictions.ml_feature_store_v2
  WHERE game_date >= '2021-12-05'
)
SELECT
  p.scoring_tier,
  COUNT(*) as count,
  ROUND(AVG(m.season_avg), 1) as avg_season_ppg,
  ROUND(MIN(m.season_avg), 1) as min_season_ppg,
  ROUND(MAX(m.season_avg), 1) as max_season_ppg
FROM nba_predictions.player_prop_predictions p
JOIN mlfs m ON p.player_lookup = m.player_lookup AND p.game_date = m.game_date
WHERE p.system_id = 'ensemble_v1' AND p.scoring_tier IS NOT NULL
GROUP BY 1 ORDER BY 1;
```

**Expected Result After Fix**:
- STAR_30PLUS: min_season_ppg >= 30.0
- STARTER_20_29: season_ppg 20.0 - 29.9
- ROTATION_10_19: season_ppg 10.0 - 19.9
- BENCH_0_9: season_ppg < 10.0

---

## Background Processes

| Shell ID | Command | Status |
|----------|---------|--------|
| 1e2085 | Predictions backfill with corrected tier boundaries | Running (11/33) |

---

## Files Modified

1. `data_processors/ml_feedback/scoring_tier_processor.py`
   - Fixed `classify_tier_by_season_avg()` boundaries (lines 326-336)

2. `backfill_jobs/prediction/player_prop_predictions_backfill.py`
   - Extract and pass season_avg (lines 626-634)
   - Use season_avg for tier classification (lines 490-494)

---

## Related Sessions

- Session 120: Identified tier adjustment bug (adjustments making MAE worse)
- Session 121: Fixed classification basis + tier boundaries

---

**End of Handoff**
