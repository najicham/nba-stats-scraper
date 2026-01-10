# Analysis: Fair System Comparison

**Date:** 2026-01-10
**Status:** COMPLETE

---

## Problem Statement

Initial system performance comparison showed misleading pick counts:
- catboost_v8: ~1,500 picks
- Old systems: 45,000-65,000 picks

This made comparisons appear invalid. Investigation was needed to understand why and produce a fair comparison.

---

## Root Causes Identified

### 1. Different Time Periods

| System | First Graded | Last Graded | Days |
|--------|--------------|-------------|------|
| catboost_v8 | 2025-12-20 | 2026-01-07 | 15 |
| ensemble_v1 | 2024-11-19 | 2026-01-04 | 171 |
| xgboost_v1 | 2024-11-19 | 2025-06-19 | 158 |
| Other systems | 2024-11-19 | 2026-01-04 | ~170 |

**Issue:** CatBoost v8 backfill (Jan 8-9, 2026) wrote to `player_prop_predictions` but only 15 days have been graded in `prediction_accuracy`. Old systems have 6 months of graded data.

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

## Results: Fair Comparison (Dec 20 - Jan 7, 2026)

| System | Predictions | Picks | Wins | Win Rate | MAE |
|--------|-------------|-------|------|----------|-----|
| **catboost_v8** | 1,998 | 1,602 | 1,150 | **71.8%** | **4.15** |
| moving_average_baseline_v1 | 1,616 | 1,282 | 763 | 59.5% | 5.02 |
| ensemble_v1 | 1,686 | 1,285 | 743 | 57.8% | 5.08 |
| zone_matchup_v1 | 1,686 | 1,490 | 793 | 53.2% | 6.49 |
| similarity_balanced_v1 | 1,210 | 886 | 447 | 50.5% | 5.69 |
| moving_average | 70 | 56 | 27 | 48.2% | 5.01 |

**Note:** xgboost_v1 not included - stopped generating predictions in June 2025.

---

## Key Insights

### 1. Pick Counts Are Now Comparable
With same date range, picks are 1,282-1,602 (not 1,500 vs 50,000).

### 2. CatBoost V8 Decisively Outperforms
- **Win rate:** 71.8% vs 59.5% (12.3 percentage points better than second place)
- **MAE:** 4.15 vs 5.02 (17% lower error than second place)

### 3. All Old Systems Beat 50% (Barely)
With uniform threshold, old systems range from 48.2% to 59.5% - better than random but not profitable after vig.

### 4. CatBoost V8 Is Profitable
At 71.8% win rate, catboost_v8 is profitable even with standard -110 juice (break-even ~52.4%).

---

## Recommendations

### Immediate Actions

1. **Keep catboost_v8 as production system** - Clearly the best performer
2. **Grade backfilled predictions** - Run grading job on historical catboost_v8 predictions to get more comparison data
3. **Filter old systems from reports** - They add noise without value

### Future Comparisons

When comparing systems, always:
1. Use the same date range for all systems
2. Apply uniform edge thresholds
3. Filter to real Vegas lines only (`has_prop_line = TRUE`)
4. Note the sample size (15 days is limited)

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
