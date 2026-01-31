# Model Drift Status Update - 2026-01-30

**Status:** 🔴 P0 CRITICAL - Retraining Threshold Exceeded

---

## Current Weekly Hit Rates

| Week Start | Predictions | Hit Rate | Bias | Status |
|------------|-------------|----------|------|--------|
| 2026-01-25 | 334 | 50.6% | -0.23 | 🔴 CRITICAL |
| 2026-01-18 | 159 | 51.6% | +0.72 | 🔴 CRITICAL |
| 2026-01-11 | 618 | 51.1% | -0.53 | 🔴 CRITICAL |
| 2026-01-04 | 547 | 62.7% | -0.08 | ✅ OK |
| 2025-12-28 | 105 | 65.7% | -0.09 | ✅ OK |

---

## Trigger Analysis

Per the [Model Drift Monitoring Framework](../catboost-v8-performance-analysis/MODEL-DRIFT-MONITORING-FRAMEWORK.md):

### Retraining Criteria Met ✓

| Condition | Threshold | Actual | Met? |
|-----------|-----------|--------|------|
| Overall hit rate < 55% | 2+ weeks | **3 weeks** | ✅ YES |
| Star tier hit rate < 60% | 2+ weeks | ~53% (Jan) | ✅ YES |
| Edge vs Vegas | < -1.0 pts | Unknown | ❓ |

**Conclusion:** P0 retraining criteria exceeded. The model has been underperforming for 3 consecutive weeks.

---

## Root Cause (from Prior Analysis)

Per SESSION-28-DATA-CORRUPTION-INCIDENT.md:

1. **NBA dynamics shift** - 2025-26 season has different scoring patterns than training data (2021-2024)
2. **Star players under-predicted** by 8-14 points (taking more shots, playing more minutes)
3. **Bench players over-predicted** by 6-7 points (getting fewer opportunities)
4. **Training data is stale** - model doesn't capture current player trajectory

---

## Experiment Results (What's Been Tried)

### ❌ CatBoost V9 - Recency Weighting (FAILED)

Documented in: `../catboost-v9-experiments/`

**Result:** All recency weighting experiments performed WORSE than baseline.

| Experiment | MAE | vs Baseline |
|------------|-----|-------------|
| V8 Baseline | 4.0235 | - |
| Recency 90-day | 4.1816 | +3.9% worse |
| Recency 180-day | 4.1681 | +3.6% worse |
| Recency 365-day | 4.0760 | +1.3% worse |

**V9 code has been deleted.**

### ❌ CatBoost V11 - Seasonal Features (FAILED)

Documented in: `../catboost-v11-seasonal/`

**Result:** Seasonal features also HURT performance.

| Experiment | MAE | vs Baseline |
|------------|-----|-------------|
| V8 Baseline | 4.0235 | - |
| V11 Seasonal | 4.0581 | +0.86% worse |

Seasonal features tested: `week_of_season`, `pct_season_completed`, `days_to_all_star`, `is_post_all_star` - none appeared in top 10 feature importance.

### Key Finding

**V8 is well-optimized and hard to beat with simple time-based features.** Both recency and seasonality hypotheses were wrong - the model doesn't benefit from knowing "when" in the season, it already captures what matters via `points_avg_last_5/10`.

---

## What's Actually Happening

The model isn't broken - the NBA is playing differently:

1. **Stars are scoring MORE than predicted** (under-predicted by 8-14 points)
2. **Bench players are scoring LESS than predicted** (over-predicted by 6-7 points)
3. This is a **systematic shift** in how the league operates, not a model bug

The model trained on 2021-2024 data doesn't reflect January 2026 dynamics.

---

## Remaining Options

Since time-based features don't help, focus on:

### Option A: Better Context Features
- Player matchup data (defender assignment)
- Injury/lineup context (who's out affects usage)
- Home/away splits by player
- Game importance (playoff implications)

### Option B: Accept Lower Performance
- V8 may be as good as it gets with current features
- 50% hit rate is still slightly better than random
- Monitor and wait for patterns to stabilize

### Option C: Full Model Redesign
- Would require significant engineering effort
- Not recommended until simpler options exhausted

---

## Recommended Next Steps

1. **Immediate:** Continue monitoring, no emergency pause needed (50% is not 45%)
2. **This Week:**
   - Review walk-forward experiment results
   - Decide on retraining approach
   - Set up A/B testing infrastructure if not exists
3. **Next Week:**
   - Deploy retrained model to shadow/canary
   - Compare against production V8
   - Full rollout if improvement confirmed

---

## Queries for Investigation

### Get Tier Breakdown (Last 4 Weeks)

```sql
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  CASE
    WHEN actual_points >= 25 THEN '1_stars_25+'
    WHEN actual_points >= 15 THEN '2_starters_15-25'
    WHEN actual_points >= 5 THEN '3_rotation_5-15'
    ELSE '4_bench_<5'
  END as tier,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate,
  ROUND(AVG(predicted_points - actual_points), 2) as bias
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
  AND prediction_correct IS NOT NULL
GROUP BY 1, 2
ORDER BY 1 DESC, 2;
```

### Get Vegas Comparison

```sql
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  COUNT(*) as predictions,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as our_mae,
  ROUND(AVG(ABS(line_value - actual_points)), 2) as vegas_mae,
  ROUND(AVG(ABS(line_value - actual_points)) - AVG(ABS(predicted_points - actual_points)), 2) as our_edge
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
  AND line_value IS NOT NULL
  AND prediction_correct IS NOT NULL
GROUP BY 1
ORDER BY 1 DESC;
```

---

*Updated: 2026-01-30 Session 44*
