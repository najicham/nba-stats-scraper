# Scoring Tier Adjustments - Implementation & Lessons Learned

**Status:** Implemented and Validated
**Created:** 2025-12-11
**Last Updated:** 2025-12-11 (Session 124)

---

## Overview

The `scoring_tier_adjustments` system corrects systematic prediction biases based on player scoring tiers. Players who average different point totals have different prediction error patterns.

---

## Implementation Summary

### Components

| Component | File | Purpose |
|-----------|------|---------|
| Processor | `data_processors/ml_feedback/scoring_tier_processor.py` | Computes tier adjustments from historical errors |
| Adjuster | `data_processors/ml_feedback/scoring_tier_adjuster.py` | Applies adjustments to predictions |
| Table | `nba_predictions.scoring_tier_adjustments` | Stores computed adjustments |
| Backfill | `backfill_jobs/prediction/player_prop_predictions_backfill.py` | Applies adjustments during prediction generation |

### Tier Definitions

| Tier | Season Average PPG | Description |
|------|-------------------|-------------|
| STAR_30PLUS | >= 30 | Elite scorers |
| STARTER_20_29 | 20-29 | Starting caliber |
| ROTATION_10_19 | 10-19 | Rotation players |
| BENCH_0_9 | < 10 | Bench players |

---

## Critical Bug Found & Fixed (Session 124)

### The Problem

Tier adjustments were making predictions **WORSE** (+0.089 MAE) instead of better.

**Root Cause:** Mismatch between computation and application:
- **Computation** classified players by `actual_points` (what they scored in that game)
- **Application** classified players by `season_avg` (what they average)

These are different populations! A star player (30+ avg) having an off night (18 points) would be classified differently at computation vs application time.

### The Fix

Changed `_compute_tier_metrics()` to classify by `season_avg` (JOIN with `ml_feature_store_v2`):

```sql
-- BEFORE (wrong)
CASE WHEN actual_points >= 30 THEN 'STAR_30PLUS' ...

-- AFTER (correct)
WITH player_season_avg AS (
  SELECT player_lookup, game_date, features[OFFSET(2)] as season_avg
  FROM ml_feature_store_v2
)
SELECT
  CASE WHEN psa.season_avg >= 30 THEN 'STAR_30PLUS' ...
FROM prediction_accuracy pa
JOIN player_season_avg psa USING (player_lookup, game_date)
```

### Results

| Metric | Before Fix | After Fix |
|--------|------------|-----------|
| Overall MAE Change | +0.089 (worse) | **-0.055 (better)** |
| BENCH tier | +0.147 (worse) | -0.041 (better) |
| ROTATION tier | -0.060 (better) | -0.056 (better) |
| STARTER tier | +0.180 (worse) | -0.175 (better) |

### Adjustment Values Before vs After

| Tier | Old (Wrong) | New (Correct) |
|------|-------------|---------------|
| BENCH_0_9 | -1.5 (wrong direction!) | +0.9 to +1.6 |
| ROTATION_10_19 | +3.5 (overcorrecting) | +1.1 to +1.3 |
| STARTER_20_29 | +7.7 (massively overcorrecting) | +1.3 to +2.2 |

---

## Validation

### Built-in Validation Method

A safeguard was added to catch future issues:

```python
from data_processors.ml_feedback.scoring_tier_processor import ScoringTierProcessor

processor = ScoringTierProcessor()
result = processor.validate_adjustments_improve_mae('2021-12-05', '2022-01-07')

# Returns:
# {
#   'n': 5148,
#   'mae_raw': 4.7237,
#   'mae_adjusted': 4.669,
#   'mae_change': -0.0547,  # Negative = good!
#   'is_improving': True
# }

# Raises ValueError if mae_change > 0.1 (adjustments making things worse)
```

### Validation Query

```sql
-- Check that adjustments improve MAE
WITH preds AS (
  SELECT p.predicted_points, p.adjusted_points, pa.actual_points
  FROM `nba_predictions.player_prop_predictions` p
  JOIN `nba_predictions.prediction_accuracy` pa
    USING (player_lookup, game_date, system_id)
  WHERE p.system_id = 'ensemble_v1' AND p.scoring_tier IS NOT NULL
)
SELECT
  ROUND(AVG(ABS(predicted_points - actual_points)), 4) as mae_raw,
  ROUND(AVG(ABS(adjusted_points - actual_points)), 4) as mae_adjusted,
  ROUND(AVG(ABS(adjusted_points - actual_points)) -
        AVG(ABS(predicted_points - actual_points)), 4) as mae_change
FROM preds;

-- mae_change should be NEGATIVE (adjustments improve predictions)
```

---

## Key Lessons Learned

1. **Consistency is critical**: When computing adjustments for a classification system, use the SAME classification basis for both computation and application.

2. **Validate direction**: If adjustments make MAE worse, something is fundamentally wrong - don't just tune parameters.

3. **Test end-to-end**: Unit testing computation in isolation won't catch mismatches - need integration tests.

4. **Add safeguards**: The `validate_adjustments_improve_mae()` method will catch future regressions.

---

## How It Works (Technical Flow)

```
┌─────────────────────────────────────────────────────────────────┐
│                    ADJUSTMENT COMPUTATION                        │
│                                                                  │
│  1. Query prediction_accuracy + ml_feature_store_v2             │
│  2. Classify each prediction by season_avg tier                 │
│  3. Compute avg bias (signed_error) per tier                    │
│  4. Store recommended_adjustment = -bias in scoring_tier_adjustments │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ADJUSTMENT APPLICATION                        │
│                                                                  │
│  1. For each prediction, get player's season_avg from MLFS     │
│  2. Classify tier by season_avg                                 │
│  3. Look up adjustment for that tier                            │
│  4. adjusted_points = predicted_points + (adjustment * factor)  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Files Reference

| File | Purpose |
|------|---------|
| `data_processors/ml_feedback/scoring_tier_processor.py` | Core computation logic |
| `data_processors/ml_feedback/scoring_tier_adjuster.py` | Application logic |
| `schemas/bigquery/nba_predictions/scoring_tier_adjustments.sql` | Table schema |
| `docs/09-handoff/2025-12-11-SESSION124-TIER-ADJUSTMENT-FIX.md` | Detailed session handoff |

---

## Future Improvements

1. **Per-player adjustments**: Some players may have consistent biases beyond their tier
2. **Context-aware adjustments**: Home/away, back-to-back, opponent strength
3. **Dynamic adjustment factors**: Currently hardcoded (50-100%), could be learned
4. **Real-time monitoring**: Dashboard to track adjustment effectiveness over time

---

## Checklist for Future Changes

If you modify the tier adjustment system:

- [ ] Ensure computation and application use the SAME classification basis
- [ ] Run `validate_adjustments_improve_mae()` after changes
- [ ] Verify mae_change is negative (adjustments help, not hurt)
- [ ] Check adjustment values are reasonable (typically +/- 3 points max)
- [ ] Update this document with any new lessons learned
