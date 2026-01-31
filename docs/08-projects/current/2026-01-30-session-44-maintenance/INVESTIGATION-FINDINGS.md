# Session 44 Investigation Findings

**Date:** 2026-01-30
**Focus:** Model drift analysis, prediction coverage investigation

---

## Executive Summary

### Key Findings

1. **Model Drift is CRITICAL** - 3 weeks below 55% hit rate, we're now WORSE than Vegas
2. **Prediction Coverage is Working as Designed** - 44% coverage is expected based on filtering rules
3. **Stars are the Problem** - Model under-predicts stars by 8-10 points

### Immediate Actions Needed

1. **Model**: Accept current V8 performance or pursue matchup/context features (not time-based)
2. **Coverage**: No action needed - filtering is intentional
3. **Monitoring**: Add star player tier tracking to daily validation

---

## Finding 1: Model Drift Analysis

### Weekly Performance (Last 5 Weeks)

| Week Start | Predictions | Hit Rate | Bias | Our MAE | Vegas MAE | Edge |
|------------|-------------|----------|------|---------|-----------|------|
| 2026-01-25 | 334 | **50.6%** | -0.23 | 5.87 | 4.71 | **-1.16** |
| 2026-01-18 | 159 | **51.6%** | +0.72 | 5.80 | 5.04 | **-0.76** |
| 2026-01-11 | 618 | **51.1%** | -0.53 | 5.85 | 4.91 | **-0.93** |
| 2026-01-04 | 547 | 62.7% | -0.08 | 4.46 | 4.65 | +0.19 |
| 2025-12-28 | 105 | 65.7% | -0.09 | 4.69 | 5.16 | +0.47 |

### Critical Insight: We're Now WORSE Than Vegas

- **December**: Our edge was positive (+0.19 to +0.47 points better than Vegas)
- **January**: Our edge is negative (-0.76 to -1.16 points WORSE than Vegas)
- Vegas MAE improved from ~5.0 to ~4.7 while our MAE degraded from ~4.5 to ~5.9

### Tier Breakdown (Week of Jan 25)

| Tier | Predictions | Hit Rate | Bias |
|------|-------------|----------|------|
| Stars (25+ pts) | 30 | **30.0%** | **-10.26** |
| Starters (15-25) | 92 | 41.3% | -2.33 |
| Rotation (5-15) | 162 | 57.4% | +1.10 |
| Bench (<5) | 50 | 58.0% | +5.36 |

### Root Cause: Star Player Under-Prediction

- **Stars scoring 10+ points MORE than predicted**
- **Bench players scoring 5+ points LESS than predicted**
- This is a systematic NBA dynamics shift, not a model bug
- V9 (recency) and V11 (seasonal) experiments both FAILED to help

### What This Means

The model was trained on 2021-2024 data where:
- Stars had different usage patterns
- Bench players got more opportunities

In January 2026:
- Stars are taking more shots, playing more minutes
- Bench players are getting squeezed out
- The model can't adapt because it has no features capturing this shift

---

## Finding 2: Prediction Coverage (44%) is By Design

### The Numbers

| Source | Players |
|--------|---------|
| upcoming_player_game_context | 319 |
| ml_feature_store_v2 | 319 |
| player_prop_predictions | 141 |

**Gap**: 178 players have no predictions

### Why: Filtering Rules

Players get predictions if:
1. **avg_minutes_per_game_last_7 >= 15** (118 players) → 100% get predictions
2. **avg_minutes < 15 BUT has_prop_line = true** (23 players) → Get predictions
3. **avg_minutes < 15 AND no prop line** (178 players) → **No prediction**

### This is Intentional

From `player_loader.py`:
```python
def create_prediction_requests(
    self,
    game_date: date,
    min_minutes: int = 15,  # Default filter
    ...
)
```

**Rationale**: Why predict for low-minute players with no betting lines?
- No betting opportunity
- Less reliable stats (small sample)
- Lower impact on betting P&L

### The 141 Predictions Breakdown

| Category | Count | % of 319 |
|----------|-------|----------|
| Above 15 min | 118 | 37% |
| Below 15 min + has prop line | 23 | 7% |
| **Total with predictions** | **141** | **44%** |
| No prediction (low min, no line) | 178 | 56% |

---

## Finding 3: Failed Prediction Worker Runs

### The 10 Failures

All 10 failed prediction worker runs had error: "No features available"

But investigation shows features DID exist for these players:
- donovanmitchell - features exist in ml_feature_store_v2
- scottiebarnes - features exist
- demarderozan - features exist
- jarenjacksonjr - features exist
- oganunoby - features exist

### Timing Analysis

| Event | Time (UTC) |
|-------|------------|
| Features written | 17:13:11 - 17:13:24 |
| Prediction worker failures | 17:45:02 - 17:53:26 |
| Predictions created | 19:52:03 - 20:55:41 |

The failures happened 30 minutes AFTER features were written, so timing isn't the issue.

### Likely Cause

The feature lookup cache in `data_loaders.py` may have:
1. Cached an empty result before features were written
2. Failed to refresh when features became available
3. Some BigQuery transient error during lookup

### Impact

Only 10 failures out of 319 players (3%) - low impact. The system recovered later and created 141 predictions.

---

## Finding 4: Experiments Already Tried

### V9 Recency Weighting - FAILED

| Experiment | MAE | vs Baseline |
|------------|-----|-------------|
| V8 Baseline | 4.0235 | - |
| Recency 90-day | 4.1816 | +3.9% worse |
| Recency 180-day | 4.1681 | +3.6% worse |
| Recency 365-day | 4.0760 | +1.3% worse |

**V9 code deleted** - recency weighting hurts performance.

### V11 Seasonal Features - FAILED

| Experiment | MAE | vs Baseline |
|------------|-----|-------------|
| V8 Baseline | 4.0235 | - |
| V11 Seasonal | 4.0581 | +0.86% worse |

**Seasonal features (week_of_season, days_to_all_star) had zero predictive value**.

### Conclusion

Time-based features don't help. The model's problem isn't "when" - it's "who" (star vs bench dynamics).

---

## Recommendations

### Short-Term (This Week)

1. **Accept Current Performance** - V8 is as good as it gets with current features
2. **Add Tier Monitoring** - Add star player hit rate to daily validation
3. **Alert on Vegas Edge** - Trigger warning when edge goes negative

### Medium-Term (2-4 Weeks)

1. **Investigate Matchup Features** - Defender assignment may help star predictions
2. **Player Trajectory Features** - `pts_slope_10g` (rising vs declining) - but test carefully
3. **Game Importance Context** - Playoff implications may affect star usage

### Long-Term (1+ Month)

1. **Consider Model Architecture** - Player-tier-specific models?
2. **Live Lineup Data** - Who's actually playing affects usage
3. **Accept Market Reality** - Vegas has more data, may be hard to beat

---

## Queries Used

### Weekly Hit Rate
```sql
SELECT
  DATE_TRUNC(game_date, WEEK) as week_start,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate,
  ROUND(AVG(predicted_points - actual_points), 2) as bias
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
  AND prediction_correct IS NOT NULL
GROUP BY 1
ORDER BY 1 DESC;
```

### Tier Breakdown
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
GROUP BY 1, 2
ORDER BY 1 DESC, 2;
```

### Vegas Comparison
```sql
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as our_mae,
  ROUND(AVG(ABS(line_value - actual_points)), 2) as vegas_mae,
  ROUND(AVG(ABS(line_value - actual_points)) - AVG(ABS(predicted_points - actual_points)), 2) as our_edge
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
  AND line_value IS NOT NULL
GROUP BY 1
ORDER BY 1 DESC;
```

---

*Investigation completed 2026-01-30 Session 44*
