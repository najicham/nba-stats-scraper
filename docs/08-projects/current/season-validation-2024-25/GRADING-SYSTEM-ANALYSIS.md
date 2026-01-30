# Grading System Analysis - 2024-25 Season

**Analysis Date:** 2026-01-29
**Status:** ✅ System Working Correctly

---

## Lesson Learned: Use the Right Table!

**CRITICAL:** There are TWO grading tables. Use the correct one:

| Table | Use For | Date Range |
|-------|---------|------------|
| `prediction_accuracy` | **All validation** | Nov 2021 - Present (419K+ records) |
| `prediction_grades` | Do NOT use for historical | Jan 2026 only (9K records) |

Initial validation incorrectly checked `prediction_grades` and concluded grading was missing. Always use `prediction_accuracy` for grading validation.

---

## Executive Summary

The grading system is functioning as designed. All "ungraded" predictions have valid reasons for not being graded.

---

## Grading Breakdown (2024-25 Season)

| Category | Count | Percentage | Status |
|----------|-------|------------|--------|
| **Graded TRUE** | 22,707 | 22.7% | ✅ Correct predictions |
| **Graded FALSE** | 13,280 | 13.3% | ✅ Incorrect predictions |
| **Ungraded (no line)** | 25,423 | 25.4% | ✅ Expected - no betting line |
| **Ungraded (PASS reco)** | 38,407 | 38.5% | ✅ Expected - "don't bet" |
| **Ungraded (pushes)** | 115 | 0.1% | ✅ Expected - actual == line |
| **Total** | 99,932 | 100% | |

---

## Expected Grading Behavior (Reference)

### Graded (`prediction_correct` = TRUE or FALSE)

A prediction is graded when ALL of these conditions are met:
1. Recommendation is `OVER` or `UNDER` (actionable)
2. `line_value` is present and valid (not 20.0 placeholder)
3. `actual_points` is available (game completed)
4. `actual_points != line_value` (not a push)
5. Prediction is active (`is_active = TRUE`)
6. Not invalidated (no `invalidation_reason`)

**Grading Logic:**
```python
if recommendation == 'OVER':
    prediction_correct = (actual_points > line_value)
elif recommendation == 'UNDER':
    prediction_correct = (actual_points < line_value)
```

### Ungraded (`prediction_correct` = NULL)

| Reason | Description | Expected? |
|--------|-------------|-----------|
| **PASS recommendation** | Model says "don't bet" | ✅ Yes |
| **HOLD recommendation** | Wait-and-see position | ✅ Yes |
| **NO_LINE recommendation** | No betting line existed | ✅ Yes |
| **Missing line_value** | Prop not available | ✅ Yes |
| **Placeholder line (20.0)** | Invalid line data | ✅ Yes |
| **Push (actual == line)** | Neither win nor loss | ✅ Yes |
| **DNP (voided)** | Player didn't play | ✅ Yes |
| **Game cancelled/postponed** | Invalidated prediction | ✅ Yes |

---

## Analysis: Why Predictions Are Ungraded

### 1. No Line Available (25,423 predictions)

These predictions were made without a betting line to compare against. Could be:
- Props not offered by sportsbooks
- Player not popular enough for props
- Line data ingestion gap

**Validation expectation:** These should NOT be graded.

### 2. PASS Recommendations (38,407 predictions)

The model recommended NOT betting. There's no win/loss to evaluate because no bet was suggested.

**Validation expectation:** These should NOT be graded.

### 3. Pushes (115 predictions)

Actual points exactly matched the betting line. Like sportsbooks, pushes are neither wins nor losses.

**Validation expectation:** These should NOT be graded.

---

## Accuracy Metrics (Graded Predictions Only)

### By System

| System | Graded | Correct | Accuracy |
|--------|--------|---------|----------|
| **catboost_v8** | 13,322 | 9,894 | **74.3%** |
| moving_average_baseline_v1 | 5,283 | 3,280 | 62.1% |
| ensemble_v1 | 6,443 | 3,873 | 60.1% |
| zone_matchup_v1 | 6,662 | 3,487 | 52.3% |
| similarity_balanced_v1 | 4,277 | 2,173 | 50.8% |

### Calculation Note

Accuracy = `correct / (correct + incorrect)` excluding:
- NULL predictions (PASS, no line, pushes)
- Voided predictions (DNP)

---

## Grading System Implementation

**Main Processor:** `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`

**Key Method:**
```python
def compute_prediction_correct(recommendation, line_value, actual_points):
    if recommendation in ('PASS', 'HOLD', 'NO_LINE', None):
        return None
    if line_value is None:
        return None
    if actual_points == line_value:  # Push
        return None

    went_over = actual_points > line_value
    recommended_over = recommendation == 'OVER'
    return went_over == recommended_over
```

**Schedule:** Daily at 12:00 PM PT

**Output Table:** `nba_predictions.prediction_accuracy`

---

## Validation Guidelines

### When Validating Historical Data

✅ **Expected ungraded:**
- PASS/HOLD/NO_LINE recommendations
- Missing line values
- Pushes (actual == line)
- DNP players

❌ **Unexpected ungraded (investigate if found):**
- OVER/UNDER with line + actual + not push
- Should have `prediction_correct` = TRUE or FALSE

### Query to Find Unexpected Ungraded

```sql
SELECT *
FROM `nba_predictions.prediction_accuracy`
WHERE prediction_correct IS NULL
  AND recommendation IN ('OVER', 'UNDER')
  AND line_value IS NOT NULL
  AND actual_points IS NOT NULL
  AND actual_points != CAST(line_value AS INT64)
  AND is_voided IS NOT TRUE
```

**Expected result:** 0 rows (none found in 2024-25 season)

---

## Recommendations

### Documentation
- [x] Document expected grading behavior (this file)
- [ ] Add to runbook/troubleshooting guide

### Validation Integration
- [ ] Add "expected ungraded" checks to `/validate-historical`
- [ ] Flag unexpected ungraded as P2 issue

### Potential Improvements
1. **Increase graded percentage** by improving line coverage
2. **Reduce PASS recommendations** if model is too conservative
3. **Track push rate** to see if lines are well-calibrated

---

## Related Files

- Processor: `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`
- Schema: `schemas/bigquery/nba_predictions/prediction_accuracy.sql`
- Backfill: `backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py`
