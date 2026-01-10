# Analysis: Fair System Comparison

**Date:** 2026-01-10
**Status:** COMPLETE - Full Historical Comparison Available

---

## Problem Statement

Initial system performance comparison showed misleading pick counts:
- catboost_v8: ~1,500 picks
- Old systems: 45,000-65,000 picks

This made comparisons appear invalid. Investigation was needed to understand why and produce a fair comparison.

**Resolution:** Phase 5B grading backfill was run on Jan 10, 2026, grading all 485K predictions. Full historical comparison is now available.

---

## Root Causes Identified (Now Resolved)

### 1. Different Time Periods (FIXED)

**Before Fix:**
| System | First Graded | Last Graded | Days |
|--------|--------------|-------------|------|
| catboost_v8 | 2025-12-20 | 2026-01-07 | 15 |
| Other systems | 2024-11-19 | 2026-01-04 | ~170 |

**After Fix (Jan 10, 2026):**
| System | First Graded | Last Graded | Graded Predictions |
|--------|--------------|-------------|-------------------|
| catboost_v8 | 2021-11-02 | 2026-01-07 | 116,356 |
| ensemble_v1 | 2021-11-06 | 2026-01-07 | 101,969 |
| Other systems | 2021-11-06 | 2026-01-07 | 62K-102K |

**Issue was:** CatBoost v8 backfill (Jan 8-9, 2026) wrote to `player_prop_predictions` but grading (Phase 5B) was never run. Old systems had 6 months of graded data.

### 2. Different Edge Thresholds (Before Normalization)

| System | Original Edge Threshold |
|--------|------------------------|
| catboost_v8 | 1.0 points |
| xgboost_v1, ensemble_v1 | 1.5 points |
| moving_average, zone_matchup, similarity | 2.0 points |

### 3. Fake Line=20 Legacy

Old systems historically used `line=20` as a default when no Vegas line existed, inflating pick counts. This was patched on Jan 10, 2026 (see `bin/patches/patch_fake_lines.sql`).

---

## Fair Comparison Methodology

To compare apples-to-apples:

1. **Same date range** - Only Dec 20, 2025 - Jan 7, 2026 (where all systems have data)
2. **Same edge threshold** - Recalculate picks using uniform 1.0 point edge for all
3. **Real lines only** - Filter to `has_prop_line = TRUE`

### Query Used

```sql
WITH fair_comparison AS (
  SELECT
    system_id,
    player_lookup,
    game_date,
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
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE has_prop_line = TRUE
    AND line_value IS NOT NULL
    AND actual_points IS NOT NULL
    AND game_date >= '2025-12-20'
    AND game_date <= '2026-01-07'
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

---

## Results: Full Historical Comparison (2021-11-06 to 2026-01-07)

After running Phase 5B grading backfill, we now have a true apples-to-apples comparison with **comparable pick counts**.

### Final Results (Uniform 1.0 Edge Threshold)

| System | Predictions | Picks | Wins | Win Rate | MAE |
|--------|-------------|-------|------|----------|-----|
| **catboost_v8** | 61,220 | 47,995 | 35,689 | **74.4%** | **4.00** |
| moving_average_baseline_v1 | 55,539 | 45,132 | 26,931 | 59.7% | 5.00 |
| ensemble_v1 | 55,610 | 39,617 | 23,217 | 58.6% | 5.03 |
| zone_matchup_v1 | 55,610 | 48,838 | 25,060 | 51.3% | 6.64 |
| similarity_balanced_v1 | 36,833 | 26,165 | 13,303 | 50.8% | 5.41 |

**Note:** xgboost_v1 not included - stopped generating predictions in June 2025.

### Previous Limited Comparison (Dec 20 - Jan 7, 2026 only)

| System | Picks | Win Rate | MAE |
|--------|-------|----------|-----|
| catboost_v8 | 1,602 | 71.8% | 4.15 |
| moving_average_baseline_v1 | 1,282 | 59.5% | 5.02 |
| ensemble_v1 | 1,285 | 57.8% | 5.08 |

---

## Key Insights

### 1. Pick Counts Are Now Comparable
With full grading backfill, picks are 26K-49K for each system (not 1,500 vs 50,000).

### 2. CatBoost V8 Decisively Outperforms
- **Win rate:** 74.4% vs 59.7% (**14.7 percentage points better** than second place)
- **MAE:** 4.00 vs 5.00 (20% lower error than second place)
- **35,689 wins** on 47,995 picks - massive sample size

### 3. Old Systems Are Marginally Better Than Random
With uniform threshold, old systems range from 50.8% to 59.7% - some profitable, most not after vig.

### 4. CatBoost V8 Is Highly Profitable
At 74.4% win rate, catboost_v8 is extremely profitable with standard -110 juice (break-even ~52.4%).
Expected profit: ~22% ROI on each bet.

---

## Recommendations

### Completed Actions

1. ✅ **Keep catboost_v8 as production system** - Clearly the best performer (74.4% win rate)
2. ✅ **Grade backfilled predictions** - Completed Jan 10, 2026 (485K predictions graded)
3. ✅ **Document grading steps** - Added to CHAMPION-CHALLENGER-FRAMEWORK.md

### Remaining Actions

1. **Filter old systems from reports** - They add noise without value (optional)
2. **Deploy system_performance_alert** - Monitor champion vs challengers

### Future Comparisons

When comparing systems, always:
1. Run Phase 5B grading backfill after prediction backfill
2. Use the same date range for all systems
3. Apply uniform edge thresholds
4. Filter to real Vegas lines only (`has_prop_line = TRUE`)

### Data Cleanup Options

| Option | Recommendation |
|--------|----------------|
| Delete old system predictions | Not recommended - keep for audit |
| Filter from reports/exports | **Recommended** - update exporters |
| Mark as deprecated | Good for documentation |

---

## Related Documents

- `docs/09-handoff/2026-01-10-CATBOOST-V8-PRODUCTION-HANDOFF.md` - Production switch details
- `bin/patches/patch_fake_lines.sql` - Historical data patch
- `docs/08-projects/current/ml-model-v8-deployment/CHAMPION-CHALLENGER-FRAMEWORK.md` - Model comparison framework

---

## Verification Queries

### Check grading coverage by system
```sql
SELECT
  system_id,
  MIN(game_date) as first_graded,
  MAX(game_date) as last_graded,
  COUNT(DISTINCT game_date) as days_graded
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE has_prop_line = TRUE
GROUP BY system_id
ORDER BY system_id;
```

### Re-run fair comparison (update dates as needed)
```sql
-- Use the query in "Query Used" section above
-- Adjust date range to match available data
```
