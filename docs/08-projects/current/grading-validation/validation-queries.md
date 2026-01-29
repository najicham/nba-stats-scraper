# Comprehensive Validation Queries

A collection of queries to validate data quality from different angles.

## 1. Prediction Coverage Analysis

### 1.1 Line Source Distribution
Shows how many predictions use real betting lines vs estimated lines.

```sql
SELECT
  game_date,
  line_source,
  COUNT(*) as predictions,
  COUNT(DISTINCT player_lookup) as unique_players
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() - 7
  AND is_active = TRUE
GROUP BY 1, 2
ORDER BY 1 DESC, predictions DESC
```

### 1.2 Business Key Duplicates (Line Sensitivity)
Check for multiple predictions per player/system/game with different lines.

```sql
SELECT
  game_date,
  COUNT(*) as total_predictions,
  COUNT(DISTINCT CONCAT(player_lookup, '|', system_id, '|', game_id)) as unique_keys,
  COUNT(*) - COUNT(DISTINCT CONCAT(player_lookup, '|', system_id, '|', game_id)) as duplicates,
  ROUND(100.0 * (COUNT(*) - COUNT(DISTINCT CONCAT(player_lookup, '|', system_id, '|', game_id))) / COUNT(*), 1) as dup_pct
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() - 7
  AND is_active = TRUE
  AND line_source = 'ACTUAL_PROP'
GROUP BY 1
ORDER BY 1 DESC
```

### 1.3 Predictions by System
See which prediction systems are generating predictions.

```sql
SELECT
  game_date,
  system_id,
  COUNT(*) as predictions,
  COUNTIF(line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')) as with_real_line,
  COUNTIF(line_source NOT IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')) as estimated_line
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() - 7
  AND is_active = TRUE
GROUP BY 1, 2
ORDER BY 1 DESC, predictions DESC
```

## 2. Grading Coverage Analysis

### 2.1 Grading Coverage by Date and Line Source
How many predictions were graded vs total.

```sql
WITH predictions AS (
  SELECT game_date, line_source, player_lookup, system_id
  FROM nba_predictions.player_prop_predictions
  WHERE game_date >= CURRENT_DATE() - 7
    AND is_active = TRUE
),
graded AS (
  SELECT DISTINCT game_date, player_lookup, system_id
  FROM nba_predictions.prediction_accuracy
  WHERE game_date >= CURRENT_DATE() - 7
)
SELECT
  p.game_date,
  p.line_source,
  COUNT(*) as total_predictions,
  COUNTIF(g.player_lookup IS NOT NULL) as graded,
  COUNTIF(g.player_lookup IS NULL) as not_graded,
  ROUND(100.0 * COUNTIF(g.player_lookup IS NOT NULL) / COUNT(*), 1) as graded_pct
FROM predictions p
LEFT JOIN graded g ON p.game_date = g.game_date
  AND p.player_lookup = g.player_lookup
  AND p.system_id = g.system_id
GROUP BY 1, 2
ORDER BY 1 DESC, total_predictions DESC
```

### 2.2 Grading Summary
Overall grading statistics.

```sql
SELECT
  game_date,
  COUNT(*) as graded_records,
  COUNT(DISTINCT player_lookup) as players,
  COUNTIF(is_voided = false OR is_voided IS NULL) as active,
  COUNTIF(is_voided = true) as voided,
  COUNTIF(prediction_correct = true) as correct,
  COUNTIF(prediction_correct = false) as incorrect,
  ROUND(100.0 * COUNTIF(prediction_correct = true) /
    NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as accuracy_pct
FROM nba_predictions.prediction_accuracy
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY 1
ORDER BY 1 DESC
```

## 3. Minutes Coverage Analysis

### 3.1 Minutes Coverage with DNP Detection
Validates that players who played have minutes recorded.

```sql
SELECT
  game_date,
  COUNT(*) as total_players,
  COUNTIF(is_dnp = TRUE) as flagged_dnp,
  COUNTIF(minutes_played IS NULL OR minutes_played = 0) as no_minutes,
  COUNTIF(minutes_played > 0) as has_minutes,
  ROUND(100.0 * COUNTIF(minutes_played > 0) / COUNT(*), 1) as minutes_pct,
  -- Effective DNP rate (using 0 minutes as indicator)
  ROUND(100.0 * COUNTIF(minutes_played IS NULL OR minutes_played = 0) / COUNT(*), 1) as effective_dnp_pct
FROM nba_analytics.player_game_summary
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY 1
ORDER BY 1 DESC
```

### 3.2 Players Without Minutes (Investigation)
Find specific players missing minutes data.

```sql
SELECT
  player_lookup,
  team_abbr,
  game_id,
  points,
  minutes_played,
  is_dnp,
  dnp_reason
FROM nba_analytics.player_game_summary
WHERE game_date = CURRENT_DATE() - 1
  AND (minutes_played IS NULL OR minutes_played = 0)
  AND (is_dnp IS NULL OR is_dnp = FALSE)
ORDER BY team_abbr
LIMIT 20
```

## 4. Data Source Reconciliation

### 4.1 BDL vs NBAC Player Counts
Compare player counts between data sources.

```sql
WITH bdl_counts AS (
  SELECT game_date, COUNT(DISTINCT player_lookup) as bdl_players
  FROM nba_raw.bdl_player_boxscores
  WHERE game_date >= CURRENT_DATE() - 7
  GROUP BY 1
),
nbac_counts AS (
  SELECT game_date, COUNT(DISTINCT player_lookup) as nbac_players
  FROM nba_raw.nbac_gamebook_player_boxscores
  WHERE game_date >= CURRENT_DATE() - 7
  GROUP BY 1
),
analytics_counts AS (
  SELECT game_date, COUNT(DISTINCT player_lookup) as analytics_players
  FROM nba_analytics.player_game_summary
  WHERE game_date >= CURRENT_DATE() - 7
  GROUP BY 1
)
SELECT
  COALESCE(b.game_date, n.game_date, a.game_date) as game_date,
  b.bdl_players,
  n.nbac_players,
  a.analytics_players
FROM bdl_counts b
FULL OUTER JOIN nbac_counts n ON b.game_date = n.game_date
FULL OUTER JOIN analytics_counts a ON b.game_date = a.game_date
ORDER BY 1 DESC
```

## 5. Prediction vs Actual Matching

### 5.1 Player Match Rate
Check how many predicted players have matching actuals.

```sql
WITH pred_players AS (
  SELECT DISTINCT game_date, player_lookup
  FROM nba_predictions.player_prop_predictions
  WHERE game_date >= CURRENT_DATE() - 7
    AND is_active = TRUE
    AND line_source = 'ACTUAL_PROP'
),
actual_players AS (
  SELECT DISTINCT game_date, player_lookup, points
  FROM nba_analytics.player_game_summary
  WHERE game_date >= CURRENT_DATE() - 7
)
SELECT
  p.game_date,
  COUNT(*) as predicted_players,
  COUNTIF(a.player_lookup IS NOT NULL) as have_actuals,
  COUNTIF(a.player_lookup IS NOT NULL AND a.points IS NOT NULL) as have_points,
  COUNTIF(a.player_lookup IS NULL) as missing_actuals,
  ROUND(100.0 * COUNTIF(a.player_lookup IS NOT NULL) / COUNT(*), 1) as match_pct
FROM pred_players p
LEFT JOIN actual_players a ON p.game_date = a.game_date AND p.player_lookup = a.player_lookup
GROUP BY 1
ORDER BY 1 DESC
```

---

## Usage Notes

1. **Replace `CURRENT_DATE()` with specific dates** for historical analysis
2. **Adjust the date range** (default is 7 days) based on your needs
3. **Run these queries in BigQuery Console** or via `bq query --use_legacy_sql=false`

## Thresholds

| Metric | Good | Warning | Critical |
|--------|------|---------|----------|
| Grading Coverage (ACTUAL_PROP) | ≥95% | 80-94% | <80% |
| Minutes Coverage (active players) | ≥95% | 85-94% | <85% |
| Prediction Match Rate | 100% | 95-99% | <95% |
| Accuracy (non-voided) | ≥52% | 48-51% | <48% |

---

*Created: 2026-01-29*
