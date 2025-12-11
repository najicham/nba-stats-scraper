# Session 121 Handoff - Tier Classification Boundary Fix

**Date:** 2025-12-10
**Focus:** Fixed critical tier boundary mismatch in scoring tier adjustments

---

## Executive Summary

Session 120 identified that tier adjustments were making predictions **worse** (adjusted MAE 4.92 vs raw MAE 4.74). This session diagnosed and fixed the root cause: tier classification boundaries didn't match tier names.

**Key Fix:** Changed tier boundaries to exactly match tier names.

---

## Bug Identified

### The Problem

In `classify_tier_by_season_avg()`, boundaries were misaligned:

| Tier Name | Old Boundary | Correct Boundary | Impact |
|-----------|--------------|------------------|--------|
| STAR_30PLUS | >= 25 | >= 30 | 25-29 ppg players got +12 pt adjustments meant for 30+ scorers |
| STARTER_20_29 | >= 18 | >= 20 | 18-19 ppg players got starter adjustments |
| ROTATION_10_19 | >= 10 | >= 10 | Correct |
| BENCH_0_9 | < 10 | < 10 | Correct |

### Evidence from Data

Before the fix, STAR_30PLUS tier showed:
- avg_season_ppg = 26.7 (max = 29.9 - NO actual 30+ scorers!)
- These 25-29 ppg players received +12.43 pt adjustments
- This caused MAE to increase by +5.77 points for this tier alone

---

## Fix Applied

**File:** `data_processors/ml_feedback/scoring_tier_processor.py`

```python
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
```

### Verification

```python
# Test output after fix:
5.0 ppg -> BENCH_0_9
9.9 ppg -> BENCH_0_9
10.0 ppg -> ROTATION_10_19
19.9 ppg -> ROTATION_10_19
20.0 ppg -> STARTER_20_29
29.9 ppg -> STARTER_20_29
30.0 ppg -> STAR_30PLUS
35.0 ppg -> STAR_30PLUS
```

---

## Background Processes

Prediction backfill with corrected tier boundaries:
- **Shell ID:** `1e2085`
- **Command:** `backfill_jobs/prediction/player_prop_predictions_backfill.py --start-date 2021-12-05 --end-date 2022-01-07`
- **Status:** Running (33 dates, ~10-15 min total)

---

## Next Steps

1. **Wait for backfill to complete** (~5-10 min remaining)
2. **Verify MAE improvement** - expect STAR_30PLUS MAE to improve significantly
3. **Run grading backfill** to update prediction_accuracy table
4. **Compare raw vs adjusted MAE** by tier with corrected classifications

### Validation Query (after backfill completes)

```sql
-- Verify corrected tier classification
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

**Expected Result:**
- STAR_30PLUS should only contain players with season_avg >= 30
- STARTER_20_29 should contain players with season_avg 20-29.9
- Each tier's season_avg range should match its name

---

## Files Modified

1. `data_processors/ml_feedback/scoring_tier_processor.py` (lines 326-336)
   - Fixed tier boundaries in `classify_tier_by_season_avg()`

---

## Related Sessions

- Session 120: Identified tier adjustment bug (adjustments making predictions worse)
- Session 119: Initial Phase 5C scoring tier implementation

---

**End of Handoff**
