# Data Discrepancy Investigation Report

**Date:** 2026-01-30
**Investigator:** Claude Code Session
**Scope:** Full pipeline data quality audit

---

## Executive Summary

A comprehensive investigation of data quality across all pipeline phases revealed several significant discrepancies:

| Issue | Severity | Impact | Status |
|-------|----------|--------|--------|
| Rolling average cache bug | HIGH | Historical analysis contaminated | Root cause identified |
| Model accuracy degradation | CRITICAL | catboost_v8 down 14% | Needs investigation |
| Player name normalization | MEDIUM | 15-20% cache gaps | Fix needed |
| Feature store NULL completeness | MEDIUM | 30% of Jan 2026 records | Needs cleanup |
| DNP voiding gaps | LOW | 532 predictions unvoided | Fix needed |

---

## 1. Rolling Average Cache Discrepancy

### Root Cause: IDENTIFIED

The cache backfill (run 2026-01-07) used **`game_date <= analysis_date`** instead of correct **`game_date < analysis_date`**.

This caused rolling averages to include the game ON the cache date, shifting L5/L10 windows by one game.

### Evidence

**File:** `data_processors/precompute/player_daily_cache/player_daily_cache_processor.py`
- Line 432: Fix comment confirms bug
- Commit `f5e249c8` (2026-01-25) contains the fix

### Match Rate by Period

| Period | Match Rate | Impact |
|--------|------------|--------|
| Nov 2024 | 97.6% | Minimal |
| Dec 2024 | 99.2% | Minimal |
| Jan 2025 | 99.1% | Minimal |
| Feb 2025 | ~22% | **Significant** |
| Mar 2025 | 20.4% | **Significant** |
| Apr 2025 | 42.8% | Moderate |
| May 2025 | 5.6% | **Severe** |

### Example Discrepancy

**Cade Cunningham on Mar 15, 2025:**
- Cache L5: 27.0 (includes Mar 15 game with 11 pts)
- Correct L5: 32.2 (excludes Mar 15 game)
- Error: 5.2 points

### Impact

| Area | Status |
|------|--------|
| Production predictions | NOT AFFECTED (uses fixed code) |
| Historical analysis (Feb-Jun 2025) | AFFECTED |
| ML training data | POTENTIALLY AFFECTED |

### Recommendation

1. For historical analysis: Recalculate L5/L10 from player_game_summary
2. Optional: Re-backfill cache for Feb-Jun 2025 with corrected code

---

## 2. Model Accuracy Degradation

### Finding: CRITICAL

The primary production model (catboost_v8) has experienced significant accuracy drop:

| Period | Accuracy |
|--------|----------|
| 2024-25 Season | 74.3% |
| 2025-26 Season | 60.5% |
| **Drop** | **-13.8%** |

### Weekly Trend (January 2026)

| Week | Accuracy | Avg Predicted | Avg Actual | Over-Prediction |
|------|----------|---------------|------------|-----------------|
| Dec 28 | 67.0% | 12.9 | 13.6 | -0.7 |
| Jan 4 | 61.8% | 13.7 | 13.2 | +0.5 |
| Jan 11 | 41.5% | 15.5 | 15.4 | +0.1 |
| Jan 18 | 54.4% | 17.2 | 14.7 | +2.5 |
| Jan 25 | **49.0%** | **19.2** | **12.5** | **+6.7** |

### Root Cause Hypothesis

The model is systematically over-predicting points, with bias increasing over time:
- Jan 25: Over-predicting by 6.7 points on average
- This could indicate:
  - Feature store data quality issues
  - Season pattern changes not captured
  - Training data staleness

### Problem Players

| Player | Total | Accuracy | Avg Error |
|--------|-------|----------|-----------|
| Danny Wolf | 47 | 31.9% | 5.3 |
| Dominick Barlow | 57 | 33.3% | 5.0 |
| Kenrich Williams | 153 | 35.9% | 5.6 |
| Jay Huff | 93 | 37.6% | 6.1 |
| Zion Williamson | 143 | 38.5% | 8.7 |

### Recommendation

1. Investigate model drift - consider retraining
2. Check feature store data quality for recent months
3. Review if training data needs refreshing

---

## 3. Feature Store Discrepancies

### NULL Historical Completeness

| Month | Total | NULL Completeness | Percentage |
|-------|-------|-------------------|------------|
| Pre-Dec 2025 | 25,888 | 0 | 0% |
| Dec 2025 | 6,866 | 1,347 | **19.6%** |
| Jan 2026 | 7,470 | 2,299 | **30.8%** |

Records with NULL `historical_completeness` have unreliable feature values.

### Season Average Fluctuations

**Example - LeBron James:**
| Date | points_avg_season | Day Change |
|------|-------------------|------------|
| 2025-12-20 | 18.6 | - |
| 2025-12-21 | 7.0 | **-11.6** |
| 2025-12-23 | 18.6 | **+11.6** |

Records on 2025-12-21 appear to have corrupted feature values.

### Sentinel Values (-1.0)

| Feature | Sentinel Count | Description |
|---------|----------------|-------------|
| recent_trend | 2,834 | Insufficient trend data |
| minutes_change | 1,763 | Missing minutes data |
| vegas_line_move | 148 | No vegas line |
| shot_zone_mismatch | 142 | Missing shot zone |

### Duplicate Records

**187 exact duplicate records** found in January 2026 (all on 2026-01-09).

### Recommendation

1. Fix NULL historical_completeness records
2. Remove 187 duplicate records
3. Investigate 2025-12-21 data anomaly
4. Monitor day-over-day feature fluctuations

---

## 4. Cross-Phase Data Consistency

### Raw → Analytics

| Period | Gap | Root Cause |
|--------|-----|------------|
| Recent (Jan 2026) | 0% | Perfect alignment |
| Historical (Nov 2024) | 39% | DNP players excluded (expected) |

**Note:** Analytics correctly filters to players who actually played.

### Analytics → Cache

| Period | Gap | Root Cause |
|--------|-----|------------|
| Recent | 15-20% | Player name normalization |
| Historical | 16-20% | Same issue |

### Player Name Normalization Issues

| Variant 1 | Variant 2 | Player |
|-----------|-----------|--------|
| `boneshyland` | `nahshonhyland` | Bones Hyland |
| `craigporter` | `craigporterjr` | Craig Porter Jr. |
| `treyjemison` | `treyjemisoniii` | Trey Jemison III |
| `hugogonzalez` | `hugogonzlez` | Hugo Gonzalez |

### Cache → Feature Store

| Period | Gap | Notes |
|--------|-----|-------|
| Nov 2024 | 22% | Early season issues |
| Dec 2024 | 7% | Improving |
| Jan 2026 | 0% | Fixed |

**Good news:** This gap has been fixed over time.

### Feature Store → Predictions

| Period | Gap | Root Cause |
|--------|-----|------------|
| Recent | 50-60% | Expected - no betting lines |
| Historical | 0% | Already graded |

**Note:** This is expected behavior - predictions only generated when betting lines available.

---

## 5. Prediction Grading

### Grading Status

| Status | Count | Notes |
|--------|-------|-------|
| GRADED | 52,378 | Successfully graded |
| PASS | 45,901 | Correctly not graded |
| NO_LINE | 25,423 | Correctly not graded |
| PUSH | 133 | Correctly not graded |

**Finding:** Grading logic is working correctly.

### DNP Voiding Issue

- 532 DNP predictions marked `is_voided=false` with `actual_points=0`
- These are graded as losses, unfairly impacting accuracy

### Recommendation

Update voiding logic to catch DNP predictions.

---

## 6. Priority Action Items

### P1 - Critical (This Week)

1. **Investigate model drift** - catboost_v8 accuracy dropped 14%
2. **Fix DNP voiding** - 532 predictions incorrectly not voided

### P2 - High (This Sprint)

3. **Fix player name normalization** - Create canonical lookup table
4. **Clean feature store** - Remove duplicates, fix NULL completeness

### P3 - Medium (Next Sprint)

5. **Re-backfill cache** - Feb-Jun 2025 with corrected code (optional)
6. **Add data quality monitoring** - Daily reconciliation alerts

### P4 - Low (Backlog)

7. **Investigate 2025-12-21 anomaly** - Feature values corrupted on this date
8. **Document Cache→Feature improvement** - What fixed the 22%→0% gap

---

## Appendix: Queries Used

### Rolling Average Validation
```sql
SELECT
  c.player_lookup,
  c.cache_date,
  c.points_avg_last_5 as cache_l5,
  (SELECT ROUND(AVG(points), 1)
   FROM (SELECT points FROM nba_analytics.player_game_summary
         WHERE player_lookup = c.player_lookup
         AND game_date < c.cache_date
         ORDER BY game_date DESC LIMIT 5)) as calc_l5,
  ABS(c.points_avg_last_5 - calc_l5) as diff
FROM nba_precompute.player_daily_cache c
WHERE c.cache_date BETWEEN '2025-03-01' AND '2025-03-31'
  AND ABS(c.points_avg_last_5 - calc_l5) > 1.0
ORDER BY diff DESC
LIMIT 20
```

### Model Accuracy by Week
```sql
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1 ELSE 0 END) * 100, 1) as accuracy,
  ROUND(AVG(predicted_value), 1) as avg_predicted,
  ROUND(AVG(actual_value), 1) as avg_actual
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= '2025-12-01'
GROUP BY 1
ORDER BY 1
```

### Cross-Phase Consistency
```sql
SELECT
  r.game_date,
  COUNT(DISTINCT r.player_lookup) as raw,
  COUNT(DISTINCT a.player_lookup) as analytics,
  COUNT(DISTINCT c.player_lookup) as cache,
  COUNT(DISTINCT f.player_lookup) as features
FROM nba_raw.bdl_player_boxscores r
LEFT JOIN nba_analytics.player_game_summary a USING (player_lookup, game_date)
LEFT JOIN nba_precompute.player_daily_cache c ON r.player_lookup = c.player_lookup
LEFT JOIN nba_predictions.ml_feature_store_v2 f USING (player_lookup, game_date)
WHERE r.game_date >= CURRENT_DATE() - 7
GROUP BY 1
ORDER BY 1 DESC
```

---

*Report generated by Claude Code automated investigation*
