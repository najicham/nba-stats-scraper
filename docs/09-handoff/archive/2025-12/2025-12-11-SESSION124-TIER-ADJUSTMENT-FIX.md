# Session 124 Handoff - Tier Adjustment Computation Fix

**Date:** 2025-12-11
**Focus:** Fixed tier adjustment computation to use season_avg instead of actual_points

---

## Executive Summary

Fixed a critical bug where tier adjustments were making predictions **worse** (+0.089 MAE) instead of better. The root cause was a mismatch between how adjustments were computed (by actual game points) vs how they were applied (by season average).

### Key Results
| Metric | Before Fix | After Fix |
|--------|------------|-----------|
| Overall MAE Change | +0.089 (worse) | **-0.055 (better)** |
| BENCH tier | +0.147 (worse) | -0.041 (better) |
| STARTER tier | +0.180 (worse) | -0.175 (better) |

---

## The Bug

### What Was Wrong

The `scoring_tier_processor.py` computed adjustments by classifying players based on **actual_points** (what they scored in that game):

```sql
-- OLD (WRONG)
CASE
  WHEN actual_points >= 30 THEN 'STAR_30PLUS'
  WHEN actual_points >= 20 THEN 'STARTER_20_29'
  ...
END as scoring_tier
```

But `scoring_tier_adjuster.py` applied adjustments based on **season_avg** (what players average):

```python
# Application uses season_avg
tier = adjuster.classify_tier_by_season_avg(season_avg)
adjustment = adjuster.get_adjustment_for_tier(tier)
```

### Why This Caused Problems

- Adjustments computed for "players who scored 30+ in a game" were applied to "players who average 30+ PPG"
- These are different populations with different error patterns
- A star player (30+ avg) having an off night (scoring 18) would get the wrong adjustment

### The Fix

Changed `_compute_tier_metrics()` in `scoring_tier_processor.py` to JOIN with `ml_feature_store_v2` and classify by `season_avg`:

```sql
-- NEW (CORRECT)
WITH player_season_avg AS (
  SELECT player_lookup, game_date, features[OFFSET(2)] as season_avg
  FROM `nba_predictions.ml_feature_store_v2`
)
SELECT
  CASE
    WHEN psa.season_avg >= 30 THEN 'STAR_30PLUS'
    WHEN psa.season_avg >= 20 THEN 'STARTER_20_29'
    ...
  END as scoring_tier,
  AVG(pa.signed_error) as avg_signed_error
FROM prediction_accuracy pa
JOIN player_season_avg psa ON pa.player_lookup = psa.player_lookup AND pa.game_date = psa.game_date
```

---

## Adjustment Values Before vs After

| Tier | Old Adjustment | New Adjustment | Issue |
|------|---------------|----------------|-------|
| BENCH_0_9 | -1.5 to -1.6 | +0.9 to +1.6 | Was wrong direction! |
| ROTATION_10_19 | +2.7 to +3.5 | +1.1 to +1.3 | Was overcorrecting |
| STARTER_20_29 | +6.6 to +7.7 | +1.3 to +2.2 | Was massively overcorrecting |
| STAR_30PLUS | +11.6 to +13.0 | N/A (no data) | Was based on wrong population |

---

## Files Modified

1. **`data_processors/ml_feedback/scoring_tier_processor.py`**
   - `_compute_tier_metrics()`: Changed to JOIN with ml_feature_store_v2 and classify by season_avg
   - Updated module docstring to document the fix

---

## Streaming Buffer Fixes (Also This Session)

Fixed `insert_rows_json` → `load_table_from_json` in 20+ files to eliminate 90-minute streaming buffer issues. See separate documentation in `docs/05-development/guides/bigquery-best-practices.md`.

---

## Validation Queries

### Check Tier Adjustments Are Sensible
```sql
SELECT as_of_date, scoring_tier,
       ROUND(avg_signed_error, 2) as bias,
       ROUND(recommended_adjustment, 2) as adjustment
FROM `nba_predictions.scoring_tier_adjustments`
ORDER BY as_of_date DESC, scoring_tier
LIMIT 20;
```

### Check MAE Impact
```sql
WITH preds AS (
  SELECT p.predicted_points, p.adjusted_points, pa.actual_points
  FROM `nba_predictions.player_prop_predictions` p
  JOIN `nba_predictions.prediction_accuracy` pa USING (player_lookup, game_date, system_id)
  WHERE p.system_id = 'ensemble_v1' AND p.scoring_tier IS NOT NULL
)
SELECT
  ROUND(AVG(ABS(predicted_points - actual_points)), 4) as mae_raw,
  ROUND(AVG(ABS(adjusted_points - actual_points)), 4) as mae_adjusted,
  ROUND(AVG(ABS(adjusted_points - actual_points)) - AVG(ABS(predicted_points - actual_points)), 4) as mae_change
FROM preds;
-- mae_change should be NEGATIVE (adjustments improve predictions)
```

---

## Lessons Learned

1. **Consistency is critical**: When computing adjustments for a classification system, use the SAME classification basis for both computation and application

2. **Validate direction**: If adjustments are making MAE worse, something is fundamentally wrong - don't just tune parameters

3. **Test end-to-end**: Unit testing the adjustment computation in isolation wouldn't catch this - need integration tests that verify the full pipeline

---

## Recommendations

1. **Add validation**: Add a check that verifies adjustments improve MAE before deploying new adjustment values

2. **Monitor in production**: Track MAE with and without adjustments to catch regressions

3. **Document assumptions**: The tier system assumes season_avg is the classification basis - this should be explicitly documented

---

**End of Handoff**
