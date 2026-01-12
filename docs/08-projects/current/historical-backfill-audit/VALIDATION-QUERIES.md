# Validation Queries

**Purpose:** SQL queries for validating backfill completeness and data quality.

---

## Quick Health Check Queries

### 1. Overall Coverage by Season

```sql
-- Player Game Summary (Phase 3)
SELECT
  season_year,
  MIN(game_date) as first_game,
  MAX(game_date) as last_game,
  COUNT(DISTINCT game_date) as game_days,
  COUNT(DISTINCT game_id) as total_games,
  COUNT(DISTINCT player_lookup) as unique_players
FROM `nba-props-platform.nba_analytics.player_game_summary`
GROUP BY season_year
ORDER BY season_year;
```

### 2. Odds API Props Coverage

```sql
-- Check prop line coverage by month
SELECT
  EXTRACT(YEAR FROM game_date) as year,
  EXTRACT(MONTH FROM game_date) as month,
  COUNT(DISTINCT game_date) as days_with_props,
  COUNT(DISTINCT player_lookup) as unique_players
FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
WHERE game_date >= '2021-10-01'
GROUP BY 1, 2
ORDER BY 1, 2;
```

### 3. Phase 4 Precompute Coverage

```sql
-- Player Daily Cache
SELECT
  EXTRACT(YEAR FROM cache_date) as year,
  EXTRACT(MONTH FROM cache_date) as month,
  COUNT(DISTINCT cache_date) as days,
  COUNT(DISTINCT player_lookup) as players
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date >= '2021-10-01'
GROUP BY 1, 2
ORDER BY 1, 2;

-- Player Composite Factors
SELECT
  EXTRACT(YEAR FROM game_date) as year,
  EXTRACT(MONTH FROM game_date) as month,
  COUNT(DISTINCT game_date) as days,
  COUNT(DISTINCT player_lookup) as players
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= '2021-10-01'
GROUP BY 1, 2
ORDER BY 1, 2;

-- ML Feature Store V2
SELECT
  EXTRACT(YEAR FROM game_date) as year,
  COUNT(DISTINCT game_date) as days,
  COUNT(DISTINCT player_lookup) as players,
  COUNT(*) as total_rows
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date >= '2021-10-01'
GROUP BY 1
ORDER BY 1;
```

### 4. Predictions Coverage

```sql
SELECT
  EXTRACT(YEAR FROM game_date) as year,
  COUNT(DISTINCT game_date) as days,
  COUNT(DISTINCT player_lookup) as players,
  COUNT(*) as total_rows
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date >= '2021-10-01'
GROUP BY 1
ORDER BY 1;
```

---

## Data Quality Queries

### 5. Check for Duplicates

```sql
-- Phase 4: Composite Factors
SELECT game_date, player_lookup, COUNT(*) as dup_count
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= '2024-10-22'
GROUP BY game_date, player_lookup
HAVING COUNT(*) > 1
ORDER BY dup_count DESC
LIMIT 100;

-- Phase 5: Predictions
SELECT game_date, player_lookup, system_id, COUNT(*) as dup_count
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date >= '2024-10-22'
GROUP BY game_date, player_lookup, system_id
HAVING COUNT(*) > 1
ORDER BY dup_count DESC
LIMIT 100;
```

### 6. Check for NULL Critical Fields

```sql
-- Phase 5: Predictions
SELECT
  COUNTIF(game_id IS NULL) as null_game_id,
  COUNTIF(player_lookup IS NULL OR player_lookup = '') as null_player,
  COUNTIF(system_id IS NULL OR system_id = '') as null_system,
  COUNTIF(predicted_points IS NULL) as null_predicted,
  COUNT(*) as total_rows
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date >= '2024-10-22';

-- Phase 4: Composite Factors
SELECT
  COUNTIF(player_lookup IS NULL) as null_player,
  COUNTIF(game_id IS NULL) as null_game_id,
  COUNTIF(fatigue_score IS NULL) as null_fatigue,
  COUNTIF(opponent_strength_score IS NULL) as null_opponent,
  COUNT(*) as total_rows
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= '2024-10-22';
```

### 7. Value Range Validation

```sql
-- Prediction value ranges
SELECT
  COUNT(*) as total,
  COUNTIF(predicted_points < 0) as negative_points,
  COUNTIF(predicted_points > 60) as over_60_points,
  COUNTIF(confidence_score < 0 OR confidence_score > 1) as bad_confidence,
  MIN(predicted_points) as min_predicted,
  MAX(predicted_points) as max_predicted,
  ROUND(AVG(predicted_points), 2) as avg_predicted
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date >= '2024-10-22';
```

### 8. Cascade Contamination Check

```sql
-- Check Phase 3 paint data (source of contamination)
SELECT
  game_date,
  COUNT(*) as total,
  COUNTIF(opp_paint_attempts > 0) as valid,
  ROUND(100.0 * COUNTIF(opp_paint_attempts > 0) / COUNT(*), 2) as pct_valid
FROM `nba-props-platform.nba_analytics.team_defense_game_summary`
WHERE game_date >= '2024-10-22'
GROUP BY 1
HAVING COUNTIF(opp_paint_attempts > 0) / COUNT(*) < 0.95
ORDER BY 1;

-- Check Phase 4 opponent strength (indicator of Phase 3 issues)
SELECT
  game_date,
  COUNT(*) as total,
  COUNTIF(opponent_strength_score > 0) as valid,
  ROUND(100.0 * COUNTIF(opponent_strength_score > 0) / COUNT(*), 2) as pct_valid
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= '2024-10-22'
GROUP BY 1
HAVING COUNTIF(opponent_strength_score > 0) / COUNT(*) < 0.95
ORDER BY 1;
```

---

## Gap Detection Queries

### 9. Find Missing Dates

```sql
-- Generate expected dates and find gaps
WITH expected AS (
  SELECT date
  FROM UNNEST(GENERATE_DATE_ARRAY('2024-10-22', CURRENT_DATE())) AS date
  WHERE EXTRACT(MONTH FROM date) NOT IN (7, 8, 9)  -- Exclude offseason
),
actual AS (
  SELECT DISTINCT game_date
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE game_date >= '2024-10-22'
)
SELECT e.date as missing_date
FROM expected e
LEFT JOIN actual a ON e.date = a.game_date
WHERE a.game_date IS NULL
ORDER BY e.date;
```

### 10. Compare Expected vs Actual Games

```sql
-- Compare schedule to actual games processed
WITH schedule AS (
  SELECT
    game_date,
    COUNT(DISTINCT game_id) as scheduled_games
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date >= '2024-10-22'
  GROUP BY game_date
),
processed AS (
  SELECT
    game_date,
    COUNT(DISTINCT game_id) as processed_games
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= '2024-10-22'
  GROUP BY game_date
)
SELECT
  s.game_date,
  s.scheduled_games,
  COALESCE(p.processed_games, 0) as processed_games,
  s.scheduled_games - COALESCE(p.processed_games, 0) as missing
FROM schedule s
LEFT JOIN processed p ON s.game_date = p.game_date
WHERE s.scheduled_games - COALESCE(p.processed_games, 0) > 0
ORDER BY s.game_date;
```

---

## Prediction Accuracy Queries

### 11. Mean Absolute Error by System

```sql
SELECT
  p.system_id,
  EXTRACT(YEAR FROM p.game_date) as year,
  COUNT(*) as predictions,
  ROUND(AVG(ABS(p.predicted_points - pgs.points)), 2) as mae,
  ROUND(STDDEV(p.predicted_points - pgs.points), 2) as std_error
FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
JOIN `nba-props-platform.nba_analytics.player_game_summary` pgs
  ON p.game_date = pgs.game_date AND p.player_lookup = pgs.player_lookup
WHERE p.game_date >= '2024-10-22'
GROUP BY 1, 2
ORDER BY 2, 1;
```

### 12. Win Rate by System

```sql
SELECT
  system_id,
  COUNT(*) as total_predictions,
  COUNTIF(prediction_correct = TRUE) as correct,
  COUNTIF(prediction_correct = FALSE) as incorrect,
  COUNTIF(prediction_correct IS NULL) as no_line,
  ROUND(100.0 * COUNTIF(prediction_correct = TRUE) /
    NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 2) as win_rate_pct
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date >= '2024-10-22'
  AND recommendation IN ('OVER', 'UNDER')
GROUP BY system_id
ORDER BY win_rate_pct DESC;
```

---

## Registry & Player Lookup Queries

### 13. Unresolved Names Backlog

```sql
SELECT
  status,
  COUNT(*) as cnt,
  MIN(created_at) as oldest,
  MAX(created_at) as newest
FROM `nba-props-platform.nba_reference.unresolved_player_names`
GROUP BY status
ORDER BY cnt DESC;
```

### 14. Player Lookup Normalization Issues

```sql
-- Find potential suffix mismatches
SELECT
  player_lookup,
  COUNT(DISTINCT game_date) as games,
  MIN(game_date) as first_game,
  MAX(game_date) as last_game
FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
WHERE player_lookup LIKE '%jr%'
   OR player_lookup LIKE '%sr%'
   OR player_lookup LIKE '%ii%'
   OR player_lookup LIKE '%iii%'
GROUP BY player_lookup
ORDER BY games DESC
LIMIT 50;
```

---

## Circuit Breaker Queries

### 15. Active Circuit Breakers

```sql
SELECT
  processor_name,
  entity_id,
  entity_type,
  failure_count,
  last_failure_at,
  circuit_breaker_until,
  TIMESTAMP_DIFF(circuit_breaker_until, CURRENT_TIMESTAMP(), DAY) as days_remaining
FROM `nba-props-platform.nba_orchestration.reprocess_attempts`
WHERE circuit_breaker_active = TRUE
  AND circuit_breaker_until > CURRENT_TIMESTAMP()
ORDER BY last_failure_at DESC
LIMIT 100;
```

---

## Processor Run History

### 16. Recent Processor Failures

```sql
SELECT
  processor_name,
  run_date,
  status,
  error_message,
  run_duration_seconds
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE status = 'failed'
  AND run_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY run_date DESC, processor_name
LIMIT 50;
```

### 17. Processor Success Rate

```sql
SELECT
  processor_name,
  COUNT(*) as total_runs,
  COUNTIF(status = 'success') as successes,
  COUNTIF(status = 'failed') as failures,
  ROUND(100.0 * COUNTIF(status = 'success') / COUNT(*), 2) as success_rate
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE run_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY processor_name
ORDER BY success_rate ASC
LIMIT 20;
```

---

## Usage Notes

1. Replace `2024-10-22` with your target start date
2. For historical seasons, use appropriate date ranges:
   - 2021-22: `2021-10-19` to `2022-06-16`
   - 2022-23: `2022-10-18` to `2023-06-12`
   - 2023-24: `2023-10-24` to `2024-06-17`
   - 2024-25: `2024-10-22` to `2025-06-15`
3. Run queries via `bq query --use_legacy_sql=false`

---

*Created: January 12, 2026*
