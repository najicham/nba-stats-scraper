# Session Handoff: Grading Backfill & Fair Comparison

**Date:** 2026-01-10
**Status:** COMPLETE

---

## Executive Summary

This session identified and fixed a critical gap in the model comparison process:
- CatBoost v8 predictions were backfilled (121K) but never graded
- This caused misleading comparisons (1,500 vs 50,000 picks)
- Phase 5B grading backfill completed - **485K predictions graded**

### Final Fair Comparison Results

| System | Picks | Win Rate | MAE |
|--------|-------|----------|-----|
| **catboost_v8** | 47,995 | **74.4%** | **4.00** |
| moving_average_baseline | 45,132 | 59.7% | 5.00 |
| ensemble_v1 | 39,617 | 58.6% | 5.03 |
| zone_matchup_v1 | 48,838 | 51.3% | 6.64 |

**CatBoost v8 outperforms by 14.7 percentage points** with comparable pick counts.

---

## Problem Identified

### Initial Comparison (Misleading)

| System | Picks | Win Rate |
|--------|-------|----------|
| catboost_v8 | 1,583 | 71.8% |
| moving_average_baseline | 45,989 | 28.7% |
| xgboost_v1 | 63,945 | 28.2% |

**Problem:** This wasn't apples-to-apples because:
1. catboost_v8 only had 15 days graded (Dec 20, 2025 - Jan 7, 2026)
2. Old systems had 6 months graded (Nov 2024 - Jan 2026)

### Root Cause

The `ml/backfill_v8_predictions.py` script only ran **Phase 5A** (writing predictions). It never ran:
- **Phase 5B**: Grading predictions against actual results
- **Phase 5C**: Regenerating daily performance aggregates

---

## What Was Done

### 1. Documentation Updates (Committed)

Updated `CHAMPION-CHALLENGER-FRAMEWORK.md` to include:
- Section 2.4: Run Grading Backfill (Phase 5B) - CRITICAL
- Section 2.5: Regenerate Daily Performance (Phase 5C)
- Section 2.6: Verify Grading Complete
- Common Pitfall warning about forgetting grading

Commit: `980c2c5`

### 2. Fair Comparison Analysis (Committed)

Created `FAIR-COMPARISON-ANALYSIS.md` documenting:
- Why pick counts were different
- Fair comparison methodology
- SQL queries for apples-to-apples comparison

### 3. Phase 5B Grading Backfill (RUNNING)

Started at: 2026-01-10 ~11:00 PM
Command:
```bash
PYTHONPATH=. .venv/bin/python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2021-11-02 --end-date 2026-01-08
```

Progress tracking:
```bash
tail -f grading_backfill_v8.log
```

Estimated completion: ~2-3 hours (851 dates × ~12 sec/date)

---

## Completed Actions

### Phase 5B Grading (DONE)

- Started: 2026-01-10 ~11:00 PM
- Completed: 2026-01-10 ~2:06 AM
- Results: 851 dates, 485,191 predictions graded, 0 failures

### Phase 5C Daily Performance (DONE)

1. **Run Phase 5C** to regenerate daily performance:
```bash
PYTHONPATH=. .venv/bin/python data_processors/grading/system_daily_performance/system_daily_performance_processor.py \
  --start-date 2021-11-02 --end-date 2026-01-08
```

2. **Verify grading coverage**:
```sql
SELECT
    system_id,
    COUNT(*) as graded_predictions,
    MIN(game_date) as first_graded,
    MAX(game_date) as last_graded,
    COUNTIF(recommendation IN ('OVER', 'UNDER')) as picks,
    ROUND(COUNTIF(prediction_correct) / COUNTIF(recommendation IN ('OVER', 'UNDER')) * 100, 1) as win_rate
FROM nba_predictions.prediction_accuracy
GROUP BY system_id
ORDER BY system_id;
```

3. **Run fair comparison** (same dates, same threshold):
```sql
WITH fair_comparison AS (
  SELECT
    system_id,
    predicted_points,
    actual_points,
    line_value,
    CASE
      WHEN predicted_points - line_value >= 1.0 THEN 'OVER'
      WHEN predicted_points - line_value <= -1.0 THEN 'UNDER'
      ELSE 'PASS'
    END as uniform_recommendation,
    CASE
      WHEN predicted_points - line_value >= 1.0 AND actual_points > line_value THEN TRUE
      WHEN predicted_points - line_value <= -1.0 AND actual_points < line_value THEN TRUE
      WHEN ABS(predicted_points - line_value) < 1.0 THEN NULL
      ELSE FALSE
    END as uniform_correct,
    ABS(predicted_points - actual_points) as absolute_error
  FROM nba_predictions.prediction_accuracy
  WHERE has_prop_line = TRUE
    AND line_value IS NOT NULL
    AND actual_points IS NOT NULL
    -- Use same date range for all systems
    AND game_date >= '2024-10-01'
)

SELECT
  system_id,
  COUNT(*) as total_predictions,
  COUNTIF(uniform_recommendation IN ('OVER', 'UNDER')) as picks,
  COUNTIF(uniform_correct = TRUE) as wins,
  ROUND(SAFE_DIVIDE(
    COUNTIF(uniform_correct = TRUE),
    COUNTIF(uniform_recommendation IN ('OVER', 'UNDER'))
  ) * 100, 1) as win_rate_pct,
  ROUND(AVG(absolute_error), 2) as mae
FROM fair_comparison
GROUP BY system_id
ORDER BY win_rate_pct DESC;
```

4. **Update FAIR-COMPARISON-ANALYSIS.md** with final results

---

## Key Decisions Made

### On xgboost_v1

**Decision:** Wait for catboost_v9 as challenger, don't resurrect xgboost_v1.

Reasons:
- xgboost_v1 showed 20-30% win rate (worse than coin flip)
- Wasn't designed for real Vegas lines
- Effort better spent on catboost_v9

### On Old Systems

**Decision:** Keep in database for audit, filter from reports.

The old systems (ensemble_v1, moving_average_baseline, etc.) remain for:
- Historical audit trail
- Understanding how much catboost_v8 improved things

---

## Files Changed

| File | Status |
|------|--------|
| `docs/08-projects/current/ml-model-v8-deployment/CHAMPION-CHALLENGER-FRAMEWORK.md` | Updated with grading steps |
| `docs/08-projects/current/ml-model-v8-deployment/FAIR-COMPARISON-ANALYSIS.md` | Created (moved from handoff) |
| `docs/09-handoff/2026-01-10-GRADING-BACKFILL-SESSION.md` | This file |

---

## Monitoring the Backfill

```bash
# Check progress
tail -20 grading_backfill_v8.log

# Check if still running
ps aux | grep prediction_accuracy_grading

# If it stopped, resume from checkpoint
PYTHONPATH=. .venv/bin/python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
  --start-date 2021-11-02 --end-date 2026-01-08
# (checkpoint will auto-resume)
```

---

## Actual Final Results

After grading completed, the fair comparison shows:

| System | Picks | Win Rate | MAE |
|--------|-------|----------|-----|
| **catboost_v8** | 47,995 | **74.4%** | **4.00** |
| moving_average_baseline | 45,132 | 59.7% | 5.00 |
| ensemble_v1 | 39,617 | 58.6% | 5.03 |
| zone_matchup_v1 | 48,838 | 51.3% | 6.64 |
| similarity_balanced_v1 | 26,165 | 50.8% | 5.41 |

**Pick counts are now comparable** (26K-49K each), and **catboost_v8 outperforms by 14.7 percentage points**.

---

## Commits This Session

```
234a92f docs(analysis): Update with final fair comparison results
980c2c5 docs(ml-v8): Add grading backfill steps to champion-challenger framework
d697548 docs(analysis): Add fair system comparison analysis
b49b6b3 docs(handoff): Add grading backfill session handoff
```
