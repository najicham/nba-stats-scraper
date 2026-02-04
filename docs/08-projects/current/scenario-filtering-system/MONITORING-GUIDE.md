# Scenario Filtering System - Monitoring Guide

**For Future Sessions**: Use this guide to monitor and maintain the scenario filtering system.

## Daily Monitoring (5 minutes)

### 1. Check Today's Optimal Picks

Run `/hit-rate-analysis --query 11` or:

```sql
SELECT player_lookup, recommendation, current_points_line as line,
  ROUND(ABS(predicted_points - current_points_line), 1) as edge,
  CASE
    WHEN recommendation = 'OVER' AND current_points_line < 12 AND ABS(predicted_points - current_points_line) >= 5 THEN '🟢 OPTIMAL_OVER'
    WHEN recommendation = 'UNDER' AND current_points_line >= 25 AND ABS(predicted_points - current_points_line) >= 3 THEN '🟢 OPTIMAL_UNDER'
    WHEN recommendation = 'OVER' AND ABS(predicted_points - current_points_line) >= 7 THEN '🟢 ULTRA_HIGH'
    ELSE '🟡 STANDARD'
  END as scenario
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9' AND is_active = TRUE
  AND recommendation IN ('OVER', 'UNDER')
  AND (
    (recommendation = 'OVER' AND current_points_line < 12 AND ABS(predicted_points - current_points_line) >= 5) OR
    (recommendation = 'UNDER' AND current_points_line >= 25 AND ABS(predicted_points - current_points_line) >= 3) OR
    (recommendation = 'OVER' AND ABS(predicted_points - current_points_line) >= 7)
  )
ORDER BY scenario, ABS(predicted_points - current_points_line) DESC;
```

**Expected**: 1-5 optimal picks per day.

### 2. Check for Blacklisted Players

If any UNDER pick hits a blacklisted player, flag it:

```sql
SELECT p.player_lookup, p.recommendation, p.current_points_line
FROM nba_predictions.player_prop_predictions p
JOIN nba_predictions.player_betting_risk b ON p.player_lookup = b.player_lookup
WHERE p.game_date = CURRENT_DATE() AND p.recommendation = 'UNDER'
  AND b.risk_type = 'under_blacklist' AND b.is_active = TRUE;
```

**Action**: Warn user if blacklisted players appear in UNDER recommendations.

## Weekly Monitoring (15 minutes)

### 1. Scenario Performance Check

Run `/hit-rate-analysis --query 8` and compare to expected:

| Scenario | Expected HR | Alert If |
|----------|-------------|----------|
| optimal_over | 87.3% | < 75% for 2 weeks |
| optimal_under | 70.7% | < 60% for 2 weeks |
| ultra_high_edge_over | 88.5% | < 75% for 2 weeks |
| anti_under_low_line | 53.8% | > 60% (might be working now) |

### 2. Player Blacklist Validation

Run `/hit-rate-analysis --query 9` to check if blacklisted players still underperform.

**Remove from blacklist if**: Player shows >55% UNDER hit rate for 3+ weeks with 10+ bets.

### 3. Opponent Risk Validation

Run `/hit-rate-analysis --query 10` to check opponent patterns.

**Remove from risk list if**: Team shows >50% UNDER hit rate for 3+ weeks.

## Monthly Revalidation (30 minutes)

### 1. Full Subset Performance Audit

```sql
SELECT
  d.subset_id,
  d.subset_name,
  d.expected_hit_rate,
  COUNT(*) as actual_bets,
  ROUND(100.0 * SUM(CASE WHEN pa.prediction_correct THEN 1 ELSE 0 END) / COUNT(*), 1) as actual_hr,
  ROUND(100.0 * SUM(CASE WHEN pa.prediction_correct THEN 1 ELSE 0 END) / COUNT(*), 1) - d.expected_hit_rate as drift
FROM nba_predictions.prediction_accuracy pa
CROSS JOIN nba_predictions.dynamic_subset_definitions d
WHERE d.scenario_category IS NOT NULL
  AND pa.system_id = 'catboost_v9'
  AND pa.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND pa.prediction_correct IS NOT NULL
  AND (d.recommendation_filter IS NULL OR pa.recommendation = d.recommendation_filter)
  AND (d.min_edge IS NULL OR ABS(pa.predicted_points - pa.line_value) >= d.min_edge)
  AND (d.line_min IS NULL OR pa.line_value >= d.line_min)
  AND (d.line_max IS NULL OR pa.line_value < d.line_max)
GROUP BY 1, 2, 3
ORDER BY drift DESC;
```

**Alert if**: Any optimal subset drifts >10% below expected for 30 days.

### 2. Update Expected Hit Rates

If consistent drift detected, update the subset definition:

```sql
UPDATE nba_predictions.dynamic_subset_definitions
SET expected_hit_rate = [NEW_VALUE],
    last_validated_at = CURRENT_TIMESTAMP(),
    notes = CONCAT(notes, ' | Monthly update [DATE]: adjusted from X to Y')
WHERE subset_id = '[SUBSET_ID]';
```

### 3. Check New Anti-Patterns

Look for patterns that should be avoided:

```sql
-- Find consistently losing patterns
SELECT
  recommendation,
  CASE
    WHEN line_value < 10 THEN '<10'
    WHEN line_value < 15 THEN '10-15'
    WHEN line_value < 20 THEN '15-20'
    WHEN line_value < 25 THEN '20-25'
    ELSE '25+'
  END as line_range,
  CASE
    WHEN ABS(predicted_points - line_value) < 3 THEN '<3'
    WHEN ABS(predicted_points - line_value) < 5 THEN '3-5'
    ELSE '5+'
  END as edge_range,
  COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND prediction_correct IS NOT NULL
GROUP BY 1, 2, 3
HAVING COUNT(*) >= 20
ORDER BY hit_rate ASC
LIMIT 10;
```

## Red Flags - Immediate Action

| Signal | Meaning | Action |
|--------|---------|--------|
| optimal_over < 70% for 7 days | Scenario may be broken | Check line distribution, model drift |
| 3+ optimal picks all lose | Bad day or pattern shift | Review the specific games |
| Blacklisted player hits OVER 60% | Remove from blacklist | Update player_betting_risk |
| New player consistently <40% UNDER | Add to blacklist | Insert into player_betting_risk |

## Updating the System

### Add New Optimal Subset

```sql
INSERT INTO nba_predictions.dynamic_subset_definitions
(subset_id, subset_name, system_id, min_edge, recommendation_filter, line_min, line_max,
 scenario_category, expected_hit_rate, expected_roi, sample_size_source,
 validation_period, last_validated_at, is_active, notes)
VALUES
('[new_id]', '[Name]', 'catboost_v9', [edge], '[OVER/UNDER]', [min], [max],
 'optimal', [hr], [roi], [sample],
 '[date range]', CURRENT_TIMESTAMP(), TRUE,
 '[Session X verified. Description.]');
```

### Add Player to Blacklist

```sql
INSERT INTO nba_predictions.player_betting_risk
(player_lookup, player_name, risk_type, risk_reason, under_hit_rate, sample_size,
 validation_period, is_active, notes)
VALUES
('[lookup]', '[Name]', 'under_blacklist', '[reason]', [hr], [n],
 '[dates]', TRUE, 'Session X added');
```

### Deactivate Subset/Player

```sql
-- Don't delete, just deactivate
UPDATE nba_predictions.dynamic_subset_definitions
SET is_active = FALSE, notes = CONCAT(notes, ' | Deactivated [DATE]: [REASON]')
WHERE subset_id = '[ID]';
```

## Confidence Intervals Reference

For statistical significance:

| Sample Size | 95% CI Width |
|-------------|--------------|
| 30 bets | ±18% |
| 50 bets | ±14% |
| 100 bets | ±10% |
| 200 bets | ±7% |

**Minimum for action**: 50 bets (2-3 weeks of optimal picks)

## Related Skills

- `/hit-rate-analysis` - Queries 8-11 for scenario analysis
- `/subset-picks [subset_id]` - Get today's picks from a subset
- `/subset-performance` - Compare all subsets
- `/validate-daily` - Overall pipeline health

---

**Last Updated**: Session 112 (2026-02-03)
