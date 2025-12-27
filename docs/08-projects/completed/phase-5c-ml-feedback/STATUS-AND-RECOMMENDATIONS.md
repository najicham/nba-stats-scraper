# Phase 5B/5C: Current Status and Recommendations

**Last Updated:** 2025-12-10
**Author:** Session 115/116 (Claude)

---

## Executive Summary

This document provides the current state of Phase 5B (Grading) and recommendations for Phase 5C (ML Feedback).

| Phase | Status |
|-------|--------|
| **Phase 5B** (Grading) | **COMPLETE** - 47,355 predictions graded |
| **Phase 5C** (ML Feedback) | **NOT IMPLEMENTED** - Design ready |
| **Phase 6.1** (Publishing) | **COMPLETE** - JSON exports to GCS |

**Phase 5C is now the priority** - Phase 6.1 is done, so focus on ML improvements.

---

## Phase 5B: Grading - COMPLETE

### What Exists

**Table:** `nba_predictions.prediction_accuracy`

**Schema (v3):**
```sql
-- Primary Keys
player_lookup STRING NOT NULL,
game_id STRING NOT NULL,
game_date DATE NOT NULL,       -- Partition key
system_id STRING NOT NULL,     -- Cluster key

-- Team Context (v3 addition)
team_abbr STRING,              -- Player's team (e.g., 'LAL')
opponent_team_abbr STRING,     -- Opponent team (e.g., 'BOS')

-- Prediction Snapshot
predicted_points NUMERIC(5, 1),
confidence_score NUMERIC(4, 3),
confidence_decile INT64,       -- 1-10 calibration bucket (v3 addition)
recommendation STRING,         -- OVER/UNDER/PASS
line_value NUMERIC(5, 1),

-- Feature Inputs
referee_adjustment NUMERIC(5, 1),
pace_adjustment NUMERIC(5, 1),
similarity_sample_size INTEGER,

-- Actual Result
actual_points INTEGER,
minutes_played NUMERIC(5, 1),  -- (v3 addition, NULL for early dates)

-- Core Accuracy Metrics
absolute_error NUMERIC(5, 1),
signed_error NUMERIC(5, 1),    -- Positive = over-predict, Negative = under-predict
prediction_correct BOOLEAN,

-- Margin Analysis
predicted_margin NUMERIC(5, 1),
actual_margin NUMERIC(5, 1),

-- Threshold Accuracy
within_3_points BOOLEAN,
within_5_points BOOLEAN,

-- Metadata
model_version STRING,
graded_at TIMESTAMP
```

### Current Data

| Metric | Value |
|--------|-------|
| Total Records | ~47,395 |
| Date Range | 2021-11-06 to 2025-11-30 |
| Unique Dates | 62 |
| Avg MAE | 4.5-5.2 points |
| Avg Bias | -0.8 to -1.5 (under-predicting) |

### Implementation Files

```
data_processors/grading/
├── __init__.py
├── prediction_accuracy/
│   ├── __init__.py
│   └── prediction_accuracy_processor.py

backfill_jobs/grading/
├── __init__.py
├── prediction_accuracy/
│   ├── __init__.py
│   └── prediction_accuracy_grading_backfill.py
```

### How to Run Grading

```bash
# Daily grading (single date)
PYTHONPATH=. .venv/bin/python -c "
from data_processors.grading.prediction_accuracy.prediction_accuracy_processor import PredictionAccuracyProcessor
processor = PredictionAccuracyProcessor()
result = processor.process('2025-12-09')
print(result)
"

# Backfill grading
PYTHONPATH=. .venv/bin/python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2021-11-01 --end-date 2025-11-30 --skip-preflight
```

---

## Phase 5C: ML Feedback - NOT IMPLEMENTED

### Problem Statement

Analysis of `prediction_accuracy` data revealed systematic bias:

| Scoring Tier | Avg Bias | Predicted | Actual | Problem |
|--------------|----------|-----------|--------|---------|
| 30+ (stars)  | **-12.6** | 21.2     | 33.8   | Severe under-prediction |
| 20-29        | -7.2     | 16.4      | 23.5   | Under-prediction |
| 10-19        | -3.1     | 10.8      | 13.9   | Slight under-prediction |
| 0-9 (bench)  | +1.6     | 5.7       | 4.1    | Over-prediction |

**Root Cause:** Excessive regression to mean in the prediction systems.

### Proposed Solution

Create feedback tables that adjust future predictions:

| Table | Purpose | Priority |
|-------|---------|----------|
| `scoring_tier_adjustments` | Fix -12.6 star bias | HIGH |
| `player_prediction_bias` | Per-player corrections | HIGH |
| `confidence_calibration` | Recalibrate confidence | MEDIUM |
| `system_agreement_patterns` | Agreement → confidence | MEDIUM |
| `context_error_correlations` | Back-to-back adjustments | LOW |

### Recommended First Step: scoring_tier_adjustments

This table would immediately address the -12.6 star bias:

```sql
CREATE TABLE scoring_tier_adjustments (
  system_id STRING NOT NULL,
  scoring_tier STRING NOT NULL,  -- 'STAR_30PLUS', 'STARTER_20_29', etc.
  as_of_date DATE NOT NULL,

  sample_size INTEGER,
  avg_signed_error NUMERIC(5,2),
  avg_absolute_error NUMERIC(5,2),

  recommended_adjustment NUMERIC(5,2),  -- Add this to prediction
  adjustment_confidence NUMERIC(4,3),

  tier_min_points NUMERIC(5,1),
  tier_max_points NUMERIC(5,1),

  computed_at TIMESTAMP
)
PARTITION BY as_of_date
CLUSTER BY system_id, scoring_tier;
```

**Application in Phase 5A:**
```python
def predict_with_tier_adjustment(player_lookup, base_prediction):
    # Classify tier based on base prediction
    if base_prediction >= 25:
        tier = 'STAR_30PLUS'
    elif base_prediction >= 18:
        tier = 'STARTER_20_29'
    # ... etc

    adjustment = get_tier_adjustment(tier)
    return base_prediction + (adjustment.recommended_adjustment * 0.5)  # Partial application
```

### Current Status (Updated)

**Phase 6.1 is COMPLETE.** Phase 5C is now the priority.

**What Phase 6.1 delivered:**
- GCS bucket: `gs://nba-props-platform-api` (public, CDN-ready)
- 61 daily results JSON files exported
- System performance JSON with rolling windows
- Aggregation table: `nba_predictions.system_daily_performance`

**Next priorities:**
1. **Phase 5C.1**: `scoring_tier_adjustments` (fix -12.6 star bias) ← **START HERE**
2. **Phase 5C.2**: `player_prediction_bias` (per-player corrections)
3. **Phase 6.2**: Best bets exporter, player profiles
4. **Phase 5C.3**: Confidence calibration, context correlations

---

## Queries for Analysis

### Check Current Bias by Scoring Tier

```sql
SELECT
  CASE
    WHEN actual_points >= 30 THEN 'STAR_30PLUS'
    WHEN actual_points >= 20 THEN 'STARTER_20_29'
    WHEN actual_points >= 10 THEN 'ROTATION_10_19'
    ELSE 'BENCH_0_9'
  END as scoring_tier,
  COUNT(*) as predictions,
  ROUND(AVG(signed_error), 2) as avg_bias,
  ROUND(AVG(absolute_error), 2) as avg_mae,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1 ELSE 0 END) * 100, 1) as win_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'ensemble_v1'
GROUP BY 1
ORDER BY 1;
```

### Check Confidence Calibration

```sql
SELECT
  confidence_decile,
  COUNT(*) as predictions,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1 ELSE 0 END) * 100, 1) as actual_win_pct,
  ROUND((confidence_decile - 0.5) * 10, 0) as expected_win_pct,
  ROUND(AVG(absolute_error), 2) as avg_mae
FROM nba_predictions.prediction_accuracy
WHERE confidence_decile IS NOT NULL
GROUP BY 1
ORDER BY 1;
```

### Check Performance by Opponent

```sql
SELECT
  opponent_team_abbr,
  COUNT(*) as predictions,
  ROUND(AVG(absolute_error), 2) as avg_mae,
  ROUND(AVG(signed_error), 2) as avg_bias,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1 ELSE 0 END) * 100, 1) as win_rate
FROM nba_predictions.prediction_accuracy
WHERE opponent_team_abbr IS NOT NULL
GROUP BY 1
ORDER BY avg_mae
LIMIT 10;
```

---

## Files to Create for Phase 5C

When ready to implement:

```
data_processors/ml_feedback/
├── __init__.py
├── scoring_tier_processor.py         # Priority 1
├── player_bias_processor.py          # Priority 2
├── confidence_calibration_processor.py
├── system_agreement_processor.py
└── context_correlation_processor.py

backfill_jobs/ml_feedback/
├── __init__.py
└── ml_feedback_backfill.py

schemas/bigquery/nba_predictions/
├── scoring_tier_adjustments.sql
├── player_prediction_bias.sql
├── confidence_calibration.sql
├── system_agreement_patterns.sql
└── context_error_correlations.sql
```

---

## Handoff for Phase 5C Implementation

### Your Mission

Implement Phase 5C ML Feedback tables to improve prediction accuracy. The biggest win is fixing the **-12.6 point bias for 30+ scorers**.

### Start Here

1. **Read the full design**: `docs/08-projects/current/phase-5c-ml-feedback/DESIGN.md`
2. **Verify the bias still exists**:
   ```bash
   bq query --use_legacy_sql=false "
   SELECT
     CASE
       WHEN actual_points >= 30 THEN 'STAR_30PLUS'
       WHEN actual_points >= 20 THEN 'STARTER_20_29'
       WHEN actual_points >= 10 THEN 'ROTATION_10_19'
       ELSE 'BENCH_0_9'
     END as scoring_tier,
     COUNT(*) as n,
     ROUND(AVG(signed_error), 2) as avg_bias
   FROM nba_predictions.prediction_accuracy
   WHERE system_id = 'ensemble_v1'
   GROUP BY 1 ORDER BY 1"
   ```

3. **Implement `scoring_tier_adjustments`** (Priority 1):
   - Create schema in `schemas/bigquery/nba_predictions/`
   - Create processor in `data_processors/ml_feedback/`
   - Backfill historical data
   - Integrate with Phase 5A prediction pipeline

### Key Files to Reference

| File | Purpose |
|------|---------|
| `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py` | Pattern for processors |
| `data_processors/publishing/base_exporter.py` | Pattern for BigQuery queries |
| `backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py` | Pattern for backfills |

### Success Metrics

After implementing Phase 5C.1, re-run bias analysis. Target:
- 30+ scorer bias: **-12.6 → < -3.0**
- Overall MAE: **4.5 → < 4.0**

---

## Related Documents

- `docs/08-projects/current/phase-5c-ml-feedback/DESIGN.md` - Full design spec
- `docs/08-projects/current/phase-6-publishing/DESIGN.md` - Phase 6 design (for reference)
- `docs/08-projects/current/phase-6-publishing/IMPLEMENTATION-GUIDE.md` - Phase 6 implementation (for patterns)

---

**End of Document**
