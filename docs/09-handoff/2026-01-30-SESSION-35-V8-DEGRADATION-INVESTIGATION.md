# Session 35 Handoff - V8 Performance Degradation Investigation

**Date:** 2026-01-30
**Priority:** HIGH
**Status:** Investigation needed

---

## Executive Summary

V8 CatBoost model is performing significantly worse this season (2025-26) compared to last season (2024-25). However, **the highest confidence predictions are still performing well** - the degradation is coming from mid-tier confidence predictions.

---

## Performance Data

### Season Comparison

| Season | Predictions | MAE | Hit Rate |
|--------|-------------|-----|----------|
| 2024-25 | 17,498 | **4.04** | **56.5%** |
| 2025-26 | 4,921 | **5.62** | **48.8%** |

**Degradation: +39% MAE, -7.7% hit rate**

### Monthly Breakdown

| Month | Predictions | MAE | Hit Rate |
|-------|-------------|-----|----------|
| Nov 2024 | 2,431 | 3.92 | 58.9% |
| Dec 2024 | 2,694 | 4.09 | 57.0% |
| Jan 2025 | 3,282 | 4.00 | 55.5% |
| Feb 2025 | 2,642 | 4.19 | 53.8% |
| Mar 2025 | 3,484 | 4.12 | 56.5% |
| Apr 2025 | 2,215 | 4.03 | 57.5% |
| May 2025 | 618 | 3.60 | 59.5% |
| Jun 2025 | 132 | 3.21 | 54.5% |
| **Nov 2025** | 391 | **7.80** | **39.9%** |
| Dec 2025 | 2,022 | 5.51 | 57.5% |
| **Jan 2026** | 2,508 | **5.37** | **43.1%** |

### Confidence Decile Analysis (Key Finding)

| Month | Decile 10 (Top) | Decile 9 | Decile 10 Count | Decile 9 Count |
|-------|-----------------|----------|-----------------|----------------|
| Nov 2025 | 7.53 MAE | 10.81 MAE | 228 | 90 |
| Dec 2025 | 4.64 MAE | 8.40 MAE | 1,552 | 470 |
| **Jan 2026** | **3.61 MAE** | **6.19 MAE** | 793 | 1,715 |

**Critical Insight**: In January 2026:
- Top confidence (decile 10): MAE 3.61 (GOOD - matches last season)
- Next tier (decile 9): MAE 6.19 (BAD - dragging down average)
- Decile 9 has 2x more predictions than decile 10

---

## Data Quality Issues

### Missing Dates in January 2026

Games existed but no graded V8 predictions:
- Jan 8 (3 games)
- Jan 19 (9 games)
- Jan 21-25 (6-8 games each day)
- Jan 29 (8 games) - may just not be graded yet

**Feature store has data for these dates** - issue is in prediction generation pipeline.

### Prediction Generation Check

```sql
-- Predictions exist for some missing dates but low counts
SELECT game_date, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v8'
  AND game_date IN ('2026-01-21', '2026-01-22', '2026-01-23', '2026-01-24', '2026-01-25')
GROUP BY 1
ORDER BY 1;

-- Results:
-- 2026-01-22: 2 predictions (should be ~100+)
-- 2026-01-24: 44 predictions
-- 2026-01-25: 564 predictions
```

---

## Investigation Questions

### 1. Why is decile 9 performing so poorly?
- What distinguishes decile 9 from decile 10 predictions?
- Are there specific player types, matchups, or game contexts?
- Is the confidence calibration broken?

### 2. What happened in November 2025?
- MAE spiked from ~4.0 to 7.8
- Only 391 predictions (low volume)
- Was this a pipeline issue or model issue?

### 3. Why are predictions missing for Jan 21-25?
- Feature store has data
- Prediction coordinator/worker may have failed
- Check Cloud Run logs for those dates

### 4. Is the model drift or data drift?
- V8 model hasn't changed
- Are features calculating differently?
- Are player behaviors different this season?

---

## Suggested Investigation Steps

### Step 1: Analyze Decile 9 vs Decile 10

```sql
-- Compare characteristics of decile 9 vs 10 predictions
SELECT
  confidence_decile,
  AVG(line_value) as avg_line,
  AVG(predicted_points) as avg_predicted,
  AVG(actual_points) as avg_actual,
  AVG(ABS(predicted_points - line_value)) as avg_edge,
  COUNT(DISTINCT player_lookup) as unique_players
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= '2026-01-01'
  AND confidence_decile IN (9, 10)
GROUP BY 1;
```

### Step 2: Check Feature Quality This Season

```sql
-- Compare feature distributions this season vs last
SELECT
  CASE WHEN game_date < '2025-07-01' THEN '2024-25' ELSE '2025-26' END as season,
  AVG(features[OFFSET(0)]) as points_avg_last_5,
  AVG(features[OFFSET(5)]) as fatigue_score,
  AVG(features[OFFSET(25)]) as vegas_points_line
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2024-11-01'
GROUP BY 1;
```

### Step 3: Check Prediction Worker Logs

```bash
# Check logs for Jan 21-25
gcloud logging read 'resource.type="cloud_run_revision"
  AND resource.labels.service_name="prediction-worker"
  AND timestamp >= "2026-01-21T00:00:00Z"
  AND timestamp <= "2026-01-26T00:00:00Z"
  AND severity >= WARNING' --limit=100
```

### Step 4: Check Specific Bad Predictions

```sql
-- Find worst predictions in decile 9
SELECT
  game_date,
  player_lookup,
  predicted_points,
  actual_points,
  absolute_error,
  line_value,
  confidence_score
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= '2026-01-01'
  AND confidence_decile = 9
ORDER BY absolute_error DESC
LIMIT 20;
```

---

## Session 35 Accomplishments (Context)

Before this investigation started, Session 35:
1. Removed V9 code (recency weighting failed)
2. Tested V11 seasonal features (also failed)
3. Confirmed V8 remains the best model architecture

The performance degradation is NOT about the model design - it's about data/pipeline issues.

---

## Files to Reference

- Grading queries: `docs/02-operations/runbooks/`
- Prediction worker: `predictions/worker/worker.py`
- V8 prediction system: `predictions/worker/prediction_systems/catboost_v8.py`
- Feature store processor: `data_processors/precompute/ml_feature_store/`

---

## Quick Commands

```bash
# Check recent V8 predictions
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as predictions
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8' AND game_date >= '2026-01-01'
GROUP BY 1 ORDER BY 1"

# Check prediction worker logs
gcloud logging read 'resource.labels.service_name="prediction-worker"' --limit=50

# Run daily validation
/validate-daily
```

---

*Investigation needed to understand V8 degradation. Key insight: top confidence predictions are fine, problem is mid-tier confidence.*
