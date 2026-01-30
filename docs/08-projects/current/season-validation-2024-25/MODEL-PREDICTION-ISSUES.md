# Model & Prediction Issues - Investigation Brief

**Date:** 2026-01-30
**Purpose:** Document model drift and prediction-related issues for planning session
**Priority:** P1 CRITICAL

---

## Executive Summary

The `catboost_v8` model has experienced significant accuracy degradation since early January 2026. Accuracy dropped from ~58% to 45% with a systematic over-prediction bias of +6.25 points. Additionally, DNP (Did Not Play) predictions are not being voided properly, causing 121 predictions to be incorrectly counted as losses.

---

## Issue 1: Model Drift - catboost_v8 Over-Predicting

### Symptoms

- Model accuracy dropped from 57.8% (Dec 21) to **45.4%** (Jan 25)
- Systematic over-prediction: averaging **+6.25 points** above actual
- Standard deviation increased from 5.4 to 11.2 (predictions becoming less consistent)

### Weekly Accuracy Trend

| Week | Predictions | Accuracy | Avg Error | Std Error |
|------|-------------|----------|-----------|-----------|
| Nov 30 | 216 | 61.6% | +5.65 | 10.95 |
| Dec 7 | 123 | 52.8% | +6.17 | 9.98 |
| Dec 14 | 451 | 59.6% | +3.09 | 9.26 |
| Dec 21 | 809 | 57.8% | -0.50 | 5.43 |
| Dec 28 | 757 | 54.3% | -0.64 | 5.45 |
| **Jan 4** | 694 | 50.3% | +0.42 | 6.51 |
| Jan 11 | 116 | 37.9% | +0.29 | 8.35 |
| **Jan 18** | 520 | 49.8% | +2.33 | 9.21 |
| **Jan 25** | 801 | **45.4%** | **+6.25** | 11.16 |

### Key Observations

1. **Dec 21-28 was the sweet spot** - Model had slight under-prediction (-0.5 to -0.6), low variance, ~55-58% accuracy
2. **Jan 4 inflection point** - Error flipped from negative to positive
3. **Jan 18-25 rapid degradation** - Over-prediction accelerated from +2.3 to +6.25 points
4. **Variance doubled** - Std error went from 5.4 (Dec) to 11.2 (Jan 25)

### Potential Root Causes to Investigate

1. **Feature Store Data Quality**
   - Rolling average cache bug was identified (fixed but may have affected training data)
   - 30% NULL historical_completeness in Jan 2026 feature store
   - 187 duplicate records found on 2026-01-09

2. **Player Name Normalization Issues**
   - 15-20% gap between analytics and cache due to lookup inconsistencies
   - Examples: `boneshyland` vs `nahshonhyland`
   - Could cause feature mismatches

3. **Seasonal Factors**
   - Mid-season player workload changes
   - Trade deadline approaching (Feb 6)
   - All-Star break effects

4. **Data Pipeline Issues**
   - Scraper wrong-code deployment (Jan 25-28) may have affected data quality
   - Phase 3 processors intermittently failing

### Diagnostic Queries

```sql
-- Check feature store quality by week
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  COUNT(*) as records,
  COUNT(DISTINCT player_lookup) as players,
  AVG(ARRAY_LENGTH(features)) as avg_feature_count,
  COUNTIF(features IS NULL) as null_features
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2025-12-01'
GROUP BY 1 ORDER BY 1;

-- Check prediction distribution shift
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  AVG(predicted_points) as avg_predicted,
  AVG(actual_points) as avg_actual,
  STDDEV(predicted_points) as std_predicted,
  STDDEV(actual_points) as std_actual
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8' AND game_date >= '2025-12-01'
GROUP BY 1 ORDER BY 1;

-- Check for feature drift
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  AVG(features[OFFSET(0)]) as feature_0_avg,
  AVG(features[OFFSET(1)]) as feature_1_avg,
  AVG(features[OFFSET(2)]) as feature_2_avg
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2025-12-01'
GROUP BY 1 ORDER BY 1;
```

### Impact Assessment

- **Accuracy**: 45% is barely above random (50% for over/under)
- **User Trust**: Predictions are not actionable at this accuracy level
- **Data Integrity**: Over-prediction suggests systematic bias in input features

---

## Issue 2: DNP Voiding Not Working

### Symptoms

- **691 predictions** have `actual_points = 0` in January 2026
- **121 of these** are counted as losses (prediction_correct = FALSE)
- These are OVER predictions where player didn't play

### Data Analysis

| Date | Zero Actual | Counted Wrong | OVER w/0 | UNDER w/0 |
|------|-------------|---------------|----------|-----------|
| Jan 28 | 247 | 38 | 38 | 71 |
| Jan 27 | 63 | 9 | 9 | 30 |
| Jan 26 | 94 | 9 | 9 | 17 |
| Jan 25 | 32 | 4 | 4 | 17 |
| Jan 23 | 47 | 37 | 37 | 6 |

### Expected Behavior

When a player doesn't play (DNP), predictions should be:
1. Marked as voided/inactive
2. NOT counted in accuracy calculations
3. Excluded from win/loss records

### Current Behavior

- OVER predictions with actual=0 are counted as LOSSES
- UNDER predictions with actual=0 are counted as WINS (correct but unfair)
- This artificially skews accuracy metrics

### Root Cause Location

The grading logic is in:
- `predictions/` directory (exact file TBD)
- Likely in the prediction grading/settlement code

### Fix Requirements

1. When `actual_points = 0`, mark prediction as voided
2. Set `is_active = FALSE` or equivalent
3. Exclude from `prediction_correct` calculation
4. Backfill: Update 691 existing records

### Diagnostic Queries

```sql
-- Find all DNP predictions
SELECT
  player_lookup,
  game_date,
  predicted_points,
  line_value,
  recommendation,
  prediction_correct
FROM nba_predictions.prediction_accuracy
WHERE actual_points = 0 AND game_date >= '2026-01-01'
ORDER BY game_date DESC;

-- Impact on accuracy if DNPs excluded
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  COUNT(*) as total,
  COUNTIF(actual_points > 0) as non_dnp,
  ROUND(100.0 * COUNTIF(prediction_correct AND actual_points > 0) /
        NULLIF(COUNTIF(actual_points > 0), 0), 1) as accuracy_excl_dnp
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8' AND game_date >= '2026-01-01'
GROUP BY 1 ORDER BY 1;
```

---

## Issue 3: Prediction Coverage Gaps

### Symptoms

Prediction coverage has been inconsistent:

| Date | Predicted | Expected | Coverage |
|------|-----------|----------|----------|
| Jan 29 | 113 | 274 | 41.2% |
| Jan 28 | 144 | 305 | 47.2% |
| Jan 27 | 122 | 236 | 51.7% |
| Jan 26 | 118 | 239 | 49.4% |
| Jan 25 | 149 | 204 | 73.0% |

### Potential Causes

1. **Prop line availability** - Not all players have betting lines
2. **Confidence filtering** - Low-confidence predictions filtered out
3. **Data quality gates** - Players with incomplete data excluded
4. **Feature store gaps** - Missing ML features for some players

### Impact

- Lower coverage = fewer actionable predictions
- May be missing valuable edge cases
- Could indicate upstream data issues

---

## Issue 4: Phase 3 Processor Failures

### Current Status (2026-01-30)

Only 2/5 Phase 3 processors completed today:
- ✅ `upcoming_player_game_context`
- ✅ `team_offense_game_summary`
- ❌ `player_game_summary`
- ❌ `team_defense_game_summary`
- ❌ `upcoming_team_game_context`

### Error Details

```
File "/app/data_processors/analytics/team_defense_game_summary/team_defense_game_summary_processor.py", line 1214
  if self.raw_data is None or self.raw_data.empty:
AttributeError: 'list' object has no attribute 'empty'
```

### Impact on Predictions

- Stale defensive matchup data
- Missing team context features
- Could affect prediction quality for today's games

---

## Recommended Investigation Plan

### Phase 1: Diagnose Model Drift (Priority 1)

1. **Feature Store Audit**
   - Check feature distributions by week
   - Identify any sudden shifts in input values
   - Verify feature completeness

2. **Prediction vs Actual Analysis**
   - Plot predicted vs actual by player tier
   - Check if drift affects all players or specific segments
   - Analyze by team, position, usage tier

3. **Training Data Review**
   - When was model last trained?
   - What date range was used?
   - Did training include corrupted cache data?

### Phase 2: Fix DNP Voiding (Priority 1)

1. **Locate grading code**
   - Find where `prediction_correct` is calculated
   - Identify where `actual_points` is populated

2. **Implement voiding logic**
   - Add check for `actual_points = 0`
   - Set appropriate void flag
   - Exclude from accuracy calculation

3. **Backfill historical data**
   - Update 691 records in Jan 2026
   - Recalculate accuracy metrics

### Phase 3: Fix Phase 3 Processors (Priority 2)

1. **Fix the AttributeError**
   - Line 1214 expects DataFrame, getting list
   - Add type checking or fix upstream data format

2. **Add resilience**
   - Handle edge cases gracefully
   - Add better error logging

---

## Key Files and Locations

| Component | Location |
|-----------|----------|
| CatBoost Model | `ml/models/catboost_v8/` |
| Feature Store | `nba_predictions.ml_feature_store_v2` |
| Prediction Accuracy | `nba_predictions.prediction_accuracy` |
| Grading Logic | `predictions/` (TBD exact file) |
| Phase 3 Processors | `data_processors/analytics/` |
| Player Daily Cache | `nba_precompute.player_daily_cache` |

## Related Documentation

- [Data Discrepancy Investigation](./DATA-DISCREPANCY-INVESTIGATION.md)
- [Session 27 Handoff](../../09-handoff/2026-01-30-SESSION-27-COMPREHENSIVE-FIXES.md)
- [Validation Framework](./VALIDATION-FRAMEWORK.md)

---

## Questions for Planning Session

1. Should we retrain the model with clean data, or try to fix input features first?
2. What's the acceptable accuracy threshold before model is considered broken?
3. Should DNP voiding be retroactive (fix historical data) or only going forward?
4. Is 45% accuracy still providing value, or should predictions be paused?
5. What monitoring should be added to catch drift earlier?

---

*Document created: 2026-01-30*
*For review by planning session*
