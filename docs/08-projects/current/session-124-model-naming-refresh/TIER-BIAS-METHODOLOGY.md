# Tier Bias Measurement Methodology

**Session 124 Finding: Two methods give vastly different results**

---

## The Two Methods

### Method 1: Tier by Actual Points (WRONG)

```sql
-- DON'T USE THIS
CASE
  WHEN actual_points >= 25 THEN 'Star'
  ...
```

**Results (30-day):**
- Stars: -8.7 bias
- Bench: +6.3 bias

**Why it's wrong:** Uses hindsight. A 20 PPG starter who scores 30 gets classified as "star" that day. The model correctly predicted ~21, but this looks like -9 bias.

### Method 2: Tier by Season Average (CORRECT)

```sql
-- USE THIS
CASE
  WHEN points_avg_season >= 25 THEN 'Star'
  ...
```

**Results (30-day):**
- Stars: +0.1 bias
- Bench: +0.6 bias

**Why it's correct:** Uses pre-game player identity - what the model actually sees when making predictions.

---

## Standard Query for Tier Bias

```sql
-- CORRECT tier bias measurement
SELECT
  CASE
    WHEN season.points_avg_season >= 25 THEN '1_Stars (25+)'
    WHEN season.points_avg_season >= 15 THEN '2_Starters (15-24)'
    WHEN season.points_avg_season >= 8 THEN '3_Role (8-14)'
    ELSE '4_Bench (<8)'
  END as tier,
  COUNT(*) as predictions,
  ROUND(AVG(pa.predicted_points), 1) as avg_predicted,
  ROUND(AVG(pa.actual_points), 1) as avg_actual,
  ROUND(AVG(pa.predicted_points - pa.actual_points), 1) as bias,
  ROUND(100.0 * COUNTIF(pa.prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy pa
JOIN (
  SELECT player_lookup, AVG(points) as points_avg_season
  FROM nba_analytics.player_game_summary
  WHERE game_date >= '2025-11-01'
    AND points IS NOT NULL
    AND minutes_played > 10
  GROUP BY player_lookup
) season ON pa.player_lookup = season.player_lookup
WHERE pa.system_id = 'catboost_v9'
  AND pa.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND pa.game_date < CURRENT_DATE()
  AND pa.actual_points IS NOT NULL
  AND pa.recommendation IN ('OVER', 'UNDER')
GROUP BY 1
ORDER BY 1
```

---

## Interpretation Guide

| Tier | Acceptable Bias | Warning | Critical |
|------|-----------------|---------|----------|
| Stars (25+) | ±2 pts | ±3-4 pts | >±5 pts |
| Starters (15-24) | ±1.5 pts | ±2-3 pts | >±4 pts |
| Role (8-14) | ±1 pts | ±2 pts | >±3 pts |
| Bench (<8) | ±1.5 pts | ±2-3 pts | >±4 pts |

---

## Current Status (2026-02-04)

| Tier | Bias | Status |
|------|------|--------|
| Stars | +0.1 | ✅ Excellent |
| Starters | -0.9 | ✅ Good |
| Role | -0.1 | ✅ Excellent |
| Bench | +0.6 | ✅ Good |

**Conclusion:** CatBoost V9 is well-calibrated. No model fixes needed for tier bias.

---

*Session 124 - Tier Bias Methodology*
