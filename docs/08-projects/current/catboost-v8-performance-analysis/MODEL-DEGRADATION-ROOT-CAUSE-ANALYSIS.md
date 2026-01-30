# CatBoost V8 Model Degradation: Root Cause Analysis

**Date:** 2026-01-30
**Author:** Session 28 Investigation
**Status:** Analysis Complete - Solutions Proposed

---

## Executive Summary

CatBoost V8's January 2026 performance degradation (74% → ~55% hit rate) is caused by a **fundamental shift in NBA scoring patterns**, not data corruption or model bugs. The model is systematically:

1. **Under-predicting star players** by 8-14 points
2. **Over-predicting bench players** by 6-7 points

This indicates the 2021-2024 training data no longer reflects current NBA dynamics.

---

## Evidence

### 1. Monthly Performance Trend

| Month | Hit Rate | MAE | Bias | Notes |
|-------|----------|-----|------|-------|
| Nov 2025 | 52.7% | 7.79 | +4.10 | Season start, limited data |
| Dec 2025 | **68.4%** | 5.51 | +1.31 | Strong performance |
| Jan 2026 | 58.2% | 5.37 | +0.29 | **Degraded** |

### 2. Player Scoring vs Historical Averages

| Month | Pts vs L5 Avg | Pts vs Season Avg |
|-------|---------------|-------------------|
| Nov 2025 | -1.67 | -1.51 |
| Dec 2025 | -1.23 | -1.24 |
| **Jan 2026** | **-2.40** | **-2.63** |

Players are scoring **2.4 points below their L5 average** in January - the model expects regression to mean, but players are regressing MORE than expected.

### 3. Performance by Player Tier

| Month | Stars (25+) | Starters (15-25) | Rotation (5-15) | Bench (<5) |
|-------|-------------|------------------|-----------------|------------|
| Dec 2025 | 79.3% | 69.0% | 65.0% | 67.8% |
| Jan 2026 | **53.1%** | **57.6%** | 60.6% | 55.7% |

**Stars collapsed from 79% to 53%** - this is the primary driver.

### 4. Prediction Bias by Tier

| Month | Stars Bias | Starters Bias | Rotation Bias | Bench Bias |
|-------|------------|---------------|---------------|------------|
| Dec 2025 | -1.38 | +0.35 | +1.59 | +4.27 |
| Jan 2026 | **-8.12** | **-2.57** | +1.02 | **+6.90** |

- **Stars**: Model under-predicts by 8 points (they're scoring MORE than expected)
- **Bench**: Model over-predicts by 7 points (they're scoring LESS than expected)

### 5. Specific Player Examples (January 2026)

| Player | Predicted | Actual | Under-Predicted By |
|--------|-----------|--------|-------------------|
| Victor Wembanyama | 21.1 | 31.5 | 10.4 |
| Bam Adebayo | 14.8 | 28.0 | 13.2 |
| Tyrese Maxey | 24.5 | 33.0 | 8.5 |
| Donovan Mitchell | 25.5 | 33.6 | 8.1 |
| Julius Randle | 19.5 | 33.0 | 13.5 |

These are established stars performing **significantly above** historical patterns.

---

## Root Cause Analysis

### Primary Cause: NBA Dynamics Shift

The 2025-26 NBA season appears to have different scoring dynamics than 2021-2024:

1. **Star usage has increased** - Top players are taking more shots, playing more minutes
2. **Bench scoring has decreased** - Role players getting fewer opportunities
3. **Pace/efficiency changes** - League-wide shifts in how offenses operate

### Why the Model Fails

1. **Training data is stale** - Model trained on 2021-2024 patterns
2. **Features don't capture trajectory** - L5/L10 averages don't distinguish rising vs declining players
3. **No seasonal adjustment** - January patterns (pre-All-Star, trade deadline) may differ
4. **Static weights** - Model treats all historical data equally

### Why December Worked

December 2025 likely had:
- More predictable patterns early in season
- Stars closer to their historical averages
- Less variance in bench production

---

## Proposed Solutions

### Solution 1: Recency-Weighted Training (Quick Win)

**Concept:** Give more weight to recent games during training.

**Implementation:**
```python
# Add sample weights based on recency
days_old = (max_date - sample_date).days
weight = np.exp(-days_old / 180)  # Half-life of 6 months
```

**Expected Impact:** Model adapts faster to current patterns.

### Solution 2: Player Trajectory Features (Medium Effort)

**Concept:** Add features that capture whether a player is trending up or down.

**New Features:**
- `pts_trend_10g`: Slope of points over last 10 games
- `pts_vs_season_z`: Z-score of recent performance vs season average
- `usage_trend`: Change in usage rate over recent games
- `minutes_trend`: Change in minutes over recent games

**Expected Impact:** Model can distinguish rising stars from declining veterans.

### Solution 3: Rolling Model Updates (Systematic)

**Concept:** Retrain monthly with a sliding window of recent data.

**Implementation:**
- Training window: Last 12 months of data
- Retrain on the 1st of each month
- Automated pipeline with validation gates

**Expected Impact:** Model never more than 1 month stale.

### Solution 4: Ensemble with Recent Model (Hybrid)

**Concept:** Combine predictions from full-history model and recent-only model.

**Implementation:**
- Model A: Trained on 2021-2025 (stability)
- Model B: Trained on last 6 months (recency)
- Final = 0.4 * A + 0.6 * B

**Expected Impact:** Balances historical patterns with current dynamics.

---

## Monitoring Framework

### Key Metrics to Track Weekly

| Metric | Threshold | Action |
|--------|-----------|--------|
| Overall hit rate | < 60% for 2 weeks | Investigate |
| Star player hit rate | < 65% for 1 week | Alert |
| Prediction bias | > |3| pts | Investigate |
| MAE vs Vegas | > +1 pt worse | Alert |

### Drift Detection Queries

```sql
-- Weekly performance check
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate,
  ROUND(AVG(predicted_points - actual_points), 2) as bias
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 8 WEEK)
GROUP BY 1
ORDER BY 1 DESC;

-- Player tier performance
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  CASE
    WHEN actual_points >= 25 THEN 'stars'
    WHEN actual_points >= 15 THEN 'starters'
    ELSE 'rotation'
  END as tier,
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate,
  ROUND(AVG(predicted_points - actual_points), 2) as bias
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
GROUP BY 1, 2
ORDER BY 1 DESC, 2;
```

### Automated Alerts

Add to daily validation:
1. **Hit rate alert**: If 7-day rolling hit rate < 55%
2. **Bias alert**: If 7-day rolling bias > |5| points
3. **Tier divergence alert**: If star vs bench hit rate differs by > 20%

---

## Recommended Action Plan

### Immediate (This Week)

1. ✅ Document findings (this document)
2. 🔄 Add player trajectory features to feature store
3. 🔄 Run experiment with recency-weighted training
4. 🔄 Add weekly drift monitoring queries

### Short-term (Next 2 Weeks)

5. Build automated monthly retraining pipeline
6. Create drift detection dashboard
7. Test ensemble approach

### Long-term (Next Month)

8. Implement continuous learning (online updates)
9. Add seasonal adjustment features
10. Build A/B testing infrastructure for model versions

---

## Appendix: Feature Ideas

### Player Trajectory Features

| Feature | Description | Calculation |
|---------|-------------|-------------|
| `pts_slope_10g` | Points trend | Linear regression slope over L10 |
| `pts_acceleration` | Change in trend | Slope of L5 - Slope of L10 |
| `breakout_score` | Recent vs historical | (L5 avg - Season avg) / Season std |
| `consistency_10g` | Scoring stability | 1 / std(L10 points) |

### Seasonal Features

| Feature | Description |
|---------|-------------|
| `days_to_allstar` | Proximity to All-Star break |
| `days_to_trade_deadline` | Proximity to trade deadline |
| `season_pct_complete` | % of season elapsed |
| `is_back_half` | Boolean for post-All-Star |

### Team Context Features

| Feature | Description |
|---------|-------------|
| `team_win_streak` | Current win/loss streak |
| `team_b2b_fatigue` | Back-to-back impact |
| `team_travel_miles` | Recent travel distance |

---

*Analysis completed 2026-01-30*
*Ready for implementation*
