# Session 116 Handoff - Phase 5C.1 Scoring Tier Adjustments

**Date:** 2025-12-10
**Focus:** Implement scoring tier adjustments to fix -12.6 star bias

---

## Executive Summary

This session implemented Phase 5C.1 - the `scoring_tier_adjustments` table and processor. This is the highest-impact ML feedback mechanism, designed to correct the severe under-prediction of star players.

**Key Achievement:** Stars who are under-predicted by -13.2 points now have a computed adjustment of +13.2 points.

---

## What Was Done

### 1. Created BigQuery Table

**Table:** `nba_predictions.scoring_tier_adjustments`

| Column | Type | Purpose |
|--------|------|---------|
| system_id | STRING | Prediction system (e.g., ensemble_v1) |
| scoring_tier | STRING | STAR_30PLUS, STARTER_20_29, ROTATION_10_19, BENCH_0_9 |
| as_of_date | DATE | Date this adjustment was computed for |
| sample_size | INTEGER | Number of predictions analyzed |
| avg_signed_error | NUMERIC | Bias (negative = under-predict) |
| avg_absolute_error | NUMERIC | MAE for this tier |
| recommended_adjustment | NUMERIC | Points to ADD to predictions |
| adjustment_confidence | NUMERIC | 0.0-1.0 confidence in adjustment |

### 2. Created Processor

**File:** `data_processors/ml_feedback/scoring_tier_processor.py`

Key methods:
- `process(as_of_date)` - Compute adjustments from prediction_accuracy
- `get_adjustment(tier)` - Get adjustment for a tier
- `classify_tier(predicted_points)` - Classify prediction into tier

### 3. Created Backfill Job

**File:** `backfill_jobs/ml_feedback/scoring_tier_backfill.py`

Usage:
```bash
# Compute single date
PYTHONPATH=. .venv/bin/python backfill_jobs/ml_feedback/scoring_tier_backfill.py --as-of-date 2022-01-07

# Weekly snapshots
PYTHONPATH=. .venv/bin/python backfill_jobs/ml_feedback/scoring_tier_backfill.py --start-date 2021-12-05 --end-date 2022-01-07 --weekly
```

---

## Current Adjustments (as of 2022-01-07)

| Tier | Bias | Adjustment | Sample | Win Rate |
|------|------|------------|--------|----------|
| BENCH_0_9 | +1.64 | -1.64 | 2,449 | 93.4% |
| ROTATION_10_19 | -3.61 | +3.61 | 1,378 | 86.4% |
| STARTER_20_29 | -7.82 | +7.82 | 534 | 12.5% |
| **STAR_30PLUS** | **-13.15** | **+13.15** | 149 | 41.6% |

The adjustments negate the bias:
- If a player is under-predicted by -13.15, add +13.15 to correct

---

## Files Created

```
schemas/bigquery/nba_predictions/
└── scoring_tier_adjustments.sql       # Schema definition

data_processors/ml_feedback/
├── __init__.py
└── scoring_tier_processor.py          # Main processor

backfill_jobs/ml_feedback/
├── __init__.py
└── scoring_tier_backfill.py           # Backfill job
```

---

## How to Use in Phase 5A

```python
from data_processors.ml_feedback.scoring_tier_processor import ScoringTierProcessor

processor = ScoringTierProcessor()

# In prediction pipeline:
def predict_with_adjustment(player_lookup, base_prediction):
    # Classify tier (using predicted points, not actual)
    tier = processor.classify_tier(base_prediction)

    # Get adjustment
    adjustment = processor.get_adjustment(tier)

    # Apply partial adjustment (0.5 factor for caution)
    adjusted = base_prediction + (adjustment * 0.5)

    return adjusted

# Example:
# base_prediction = 23.5 (classified as STARTER_20_29)
# adjustment = +7.82
# adjusted = 23.5 + (7.82 * 0.5) = 27.41
```

---

## Next Steps

### Immediate (Phase 5C.1 Complete)
1. ✅ Table created and populated
2. ✅ Processor working
3. ✅ Single date backfill verified

### To Do (Phase 5C Integration)
1. **Backfill weekly snapshots** - Generate historical adjustments
2. **Integrate with Phase 5A** - Modify prediction pipeline to apply adjustments
3. **Validate improvement** - Re-run predictions with adjustments, measure bias reduction

### Backfill Command
```bash
# Generate weekly snapshots from Dec 2021 to Jan 2022
PYTHONPATH=. .venv/bin/python backfill_jobs/ml_feedback/scoring_tier_backfill.py \
  --start-date 2021-12-05 --end-date 2022-01-07 --weekly
```

### Integration Points

The adjustments should be applied in:
- `data_processors/prediction/player_prop_predictions_processor.py` - Main prediction generation

---

## Verification Queries

```sql
-- Check current adjustments
SELECT * FROM nba_predictions.scoring_tier_adjustments
WHERE as_of_date = '2022-01-07'
ORDER BY scoring_tier;

-- Check adjustment confidence
SELECT
  scoring_tier,
  sample_size,
  recommended_adjustment,
  adjustment_confidence
FROM nba_predictions.scoring_tier_adjustments
WHERE as_of_date = '2022-01-07'
ORDER BY ABS(recommended_adjustment) DESC;
```

---

## Related Documents

- `docs/08-projects/current/phase-5c-ml-feedback/DESIGN.md` - Full design
- `docs/08-projects/current/phase-5c-ml-feedback/STATUS-AND-RECOMMENDATIONS.md` - Updated status
- `docs/09-handoff/2025-12-10-SESSION114-PHASE5B-V3-ENHANCEMENTS.md` - Phase 5B v3 changes

---

**End of Handoff**
