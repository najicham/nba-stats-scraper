# Phase 5C Handoff for Continuation

**Date:** 2025-12-10
**Purpose:** Standalone handoff for Phase 5C ML Feedback implementation

---

## Current Status

| Component | Status | Details |
|-----------|--------|---------|
| scoring_tier_adjustments table | CREATED | 24 rows (4 tiers × 6 weeks) |
| Scoring Tier Processor | IMPLEMENTED | `data_processors/ml_feedback/scoring_tier_processor.py` |
| Backfill Script | IMPLEMENTED | `backfill_jobs/ml_feedback/scoring_tier_backfill.py` |
| Validation | COMPLETE | 50% adjustment = 47% MAE reduction for stars |
| **Integration** | **NOT DONE** | Apply adjustments in prediction pipeline |

---

## Key Finding: Tier-Specific Bias

| Tier | Bias | Recommended Adjustment Factor |
|------|------|------------------------------|
| STAR_30PLUS | -13.2 points | **100%** (full correction) |
| STARTER_20_29 | -7.8 points | 75% |
| ROTATION_10_19 | -3.6 points | 50% |
| BENCH_0_9 | +1.6 points | 50% |

Star players are systematically under-predicted by 13+ points.

---

## What Needs to Be Done

### Priority 1: Integrate into Prediction Pipeline

Modify `backfill_jobs/prediction/player_prop_predictions_backfill.py` to apply scoring tier adjustments:

```python
from data_processors.ml_feedback.scoring_tier_processor import ScoringTierProcessor

ADJUSTMENT_FACTORS = {
    'BENCH_0_9': 0.5,
    'ROTATION_10_19': 0.5,
    'STARTER_20_29': 0.75,
    'STAR_30PLUS': 1.0,  # Full adjustment
}

def apply_scoring_tier_adjustment(base_prediction: float, as_of_date: str) -> float:
    """Apply scoring tier adjustment to base prediction."""
    processor = ScoringTierProcessor()
    tier = processor.classify_tier(base_prediction)
    adjustment = processor.get_adjustment(tier, as_of_date)
    factor = ADJUSTMENT_FACTORS.get(tier, 0.5)
    return base_prediction + (adjustment * factor)
```

### Priority 2: player_prediction_bias Table

Per-player corrections for consistently biased predictions. Schema designed but not implemented:

```sql
CREATE TABLE player_prediction_bias (
  player_lookup STRING NOT NULL,
  system_id STRING NOT NULL,
  as_of_date DATE NOT NULL,

  sample_size INTEGER,
  avg_signed_error NUMERIC(5,2),
  avg_absolute_error NUMERIC(5,2),
  recent_bias_trend STRING,  -- 'IMPROVING', 'WORSENING', 'STABLE'

  recommended_adjustment NUMERIC(5,2),
  adjustment_confidence NUMERIC(4,3)
);
```

### Priority 3: Confidence Calibration

Calibrate confidence scores to actual win rates by decile.

---

## Existing Data

**Table:** `nba_predictions.scoring_tier_adjustments`

```sql
SELECT * FROM nba_predictions.scoring_tier_adjustments
WHERE as_of_date = '2022-01-07'
ORDER BY scoring_tier;
```

**Table:** `nba_predictions.prediction_accuracy` (47,355 rows)
- Used for calculating adjustments
- Partitioned by game_date, clustered by system_id

---

## Files

```
data_processors/ml_feedback/
├── __init__.py
├── scoring_tier_processor.py  ← DONE
└── (player_bias_processor.py) ← TO CREATE

backfill_jobs/ml_feedback/
├── __init__.py
├── scoring_tier_backfill.py   ← DONE
└── (player_bias_backfill.py)  ← TO CREATE

schemas/bigquery/nba_predictions/
└── scoring_tier_adjustments.sql  ← DONE
```

---

## Validation Query

After integrating adjustments, verify improvement:

```sql
WITH adjusted AS (
  SELECT
    p.*,
    CASE
      WHEN actual_points >= 30 THEN 'STAR_30PLUS'
      WHEN actual_points >= 20 THEN 'STARTER_20_29'
      WHEN actual_points >= 10 THEN 'ROTATION_10_19'
      ELSE 'BENCH_0_9'
    END as tier,
    a.recommended_adjustment
  FROM nba_predictions.prediction_accuracy p
  JOIN nba_predictions.scoring_tier_adjustments a
    ON p.game_date <= a.as_of_date
    AND a.as_of_date = '2022-01-07'
    AND CASE
      WHEN p.actual_points >= 30 THEN 'STAR_30PLUS'
      WHEN p.actual_points >= 20 THEN 'STARTER_20_29'
      WHEN p.actual_points >= 10 THEN 'ROTATION_10_19'
      ELSE 'BENCH_0_9'
    END = a.scoring_tier
  WHERE p.system_id = 'ensemble_v1'
)
SELECT
  tier,
  COUNT(*) as n,
  ROUND(AVG(absolute_error), 2) as original_mae,
  ROUND(AVG(ABS(actual_points - (predicted_points + recommended_adjustment))), 2) as adjusted_mae
FROM adjusted
GROUP BY 1
ORDER BY 1;
```

---

## Success Metrics

| Metric | Before | Target |
|--------|--------|--------|
| STAR bias | -13.2 | < -3.0 |
| Overall MAE | 4.5 | < 4.0 |

---

## Related Docs

- `docs/09-handoff/2025-12-10-SESSION116-PHASE5C-SCORING-TIER-ADJUSTMENTS.md`
- `docs/09-handoff/2025-12-10-SESSION117-PHASE5C-VALIDATION-COMPLETE.md`
- `docs/08-projects/current/phase-5c-ml-feedback/DESIGN.md`

---

**TL;DR:** scoring_tier_adjustments is built and validated. Next step is integrating it into the prediction pipeline, then building player_prediction_bias.
