# Player Investigation Template

**Purpose:** Deep-dive analysis of a single player to understand patterns and debug prediction failures.

**When to use:** After aggregate analysis reveals patterns, use this to understand WHY.

---

## Quick Start

Replace `{{PLAYER_LOOKUP}}` with the player's lookup key (e.g., `lebron-james`, `nikola-jokic`).

---

## 1. Player Overview

### Basic Stats

```sql
-- Player prediction summary
SELECT
  COUNT(*) as total_predictions,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(AVG(signed_error), 2) as bias,
  ROUND(STDDEV(absolute_error), 2) as error_volatility,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1 ELSE 0 END) * 100, 1) as win_rate_pct,
  ROUND(AVG(CASE WHEN absolute_error <= 3 THEN 1 ELSE 0 END) * 100, 1) as within_3_pct,
  ROUND(AVG(CASE WHEN absolute_error <= 5 THEN 1 ELSE 0 END) * 100, 1) as within_5_pct,
  MIN(game_date) as first_game,
  MAX(game_date) as last_game
FROM `nba_predictions.prediction_accuracy`
WHERE player_lookup = '{{PLAYER_LOOKUP}}'
  AND system_id = 'ensemble_v1';
```

### Compare to Population

```sql
-- How does this player compare to others in their tier?
WITH player_stats AS (
  SELECT
    player_lookup,
    AVG(absolute_error) as mae,
    COUNT(*) as games
  FROM `nba_predictions.prediction_accuracy`
  WHERE system_id = 'ensemble_v1'
  GROUP BY 1
  HAVING games >= 20
),
target_player AS (
  SELECT mae FROM player_stats WHERE player_lookup = '{{PLAYER_LOOKUP}}'
)
SELECT
  ROUND(t.mae, 3) as player_mae,
  ROUND(AVG(p.mae), 3) as population_avg_mae,
  ROUND(PERCENT_RANK() OVER (ORDER BY t.mae), 2) as percentile_rank,
  CASE
    WHEN t.mae < AVG(p.mae) - STDDEV(p.mae) THEN 'HIGHLY PREDICTABLE'
    WHEN t.mae < AVG(p.mae) THEN 'ABOVE AVERAGE'
    WHEN t.mae < AVG(p.mae) + STDDEV(p.mae) THEN 'BELOW AVERAGE'
    ELSE 'HARD TO PREDICT'
  END as predictability
FROM player_stats p
CROSS JOIN target_player t
GROUP BY t.mae;
```

---

## 2. System Comparison

### Which System Works Best for This Player?

```sql
SELECT
  system_id,
  COUNT(*) as predictions,
  ROUND(AVG(absolute_error), 3) as mae,
  ROUND(AVG(signed_error), 3) as bias,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1 ELSE 0 END) * 100, 1) as win_rate_pct
FROM `nba_predictions.prediction_accuracy`
WHERE player_lookup = '{{PLAYER_LOOKUP}}'
GROUP BY 1
ORDER BY mae;
```

### System Performance Gap

```sql
-- Is there a system that's dramatically better/worse?
WITH system_mae AS (
  SELECT
    system_id,
    AVG(absolute_error) as mae
  FROM `nba_predictions.prediction_accuracy`
  WHERE player_lookup = '{{PLAYER_LOOKUP}}'
  GROUP BY 1
)
SELECT
  MIN(mae) as best_mae,
  MAX(mae) as worst_mae,
  MAX(mae) - MIN(mae) as gap,
  ARRAY_AGG(STRUCT(system_id, mae) ORDER BY mae LIMIT 1)[OFFSET(0)].system_id as best_system,
  ARRAY_AGG(STRUCT(system_id, mae) ORDER BY mae DESC LIMIT 1)[OFFSET(0)].system_id as worst_system
FROM system_mae
WHERE system_id != 'ensemble_v1';
```

**Key Question:** If gap > 1.0, should we use a different system for this player?

---

## 3. Context Analysis

### Back-to-Back Performance

```sql
SELECT
  mlfs.is_back_to_back,
  COUNT(*) as games,
  ROUND(AVG(pa.predicted_points), 1) as avg_prediction,
  ROUND(AVG(pa.actual_points), 1) as avg_actual,
  ROUND(AVG(pa.absolute_error), 2) as mae,
  ROUND(AVG(pa.signed_error), 2) as bias
FROM `nba_predictions.prediction_accuracy` pa
JOIN `nba_predictions.ml_feature_store_v2` mlfs USING (player_lookup, game_date)
WHERE pa.player_lookup = '{{PLAYER_LOOKUP}}'
  AND pa.system_id = 'ensemble_v1'
GROUP BY 1
ORDER BY 1;
```

**Key Question:** Does this player show B2B fatigue? Is bias negative on B2B?

### Rest Days Analysis

```sql
SELECT
  CASE
    WHEN mlfs.days_rest = 0 THEN '0 (B2B)'
    WHEN mlfs.days_rest = 1 THEN '1 day'
    WHEN mlfs.days_rest = 2 THEN '2 days'
    ELSE '3+ days'
  END as rest_bucket,
  COUNT(*) as games,
  ROUND(AVG(pa.actual_points), 1) as avg_actual,
  ROUND(AVG(pa.signed_error), 2) as bias,
  ROUND(AVG(pa.absolute_error), 2) as mae
FROM `nba_predictions.prediction_accuracy` pa
JOIN `nba_predictions.ml_feature_store_v2` mlfs USING (player_lookup, game_date)
WHERE pa.player_lookup = '{{PLAYER_LOOKUP}}'
  AND pa.system_id = 'ensemble_v1'
GROUP BY 1
ORDER BY 1;
```

### Season Phase Performance

```sql
SELECT
  CASE
    WHEN EXTRACT(MONTH FROM pa.game_date) IN (10, 11) THEN '1_EARLY'
    WHEN EXTRACT(MONTH FROM pa.game_date) = 12 THEN '2_DEC'
    WHEN EXTRACT(MONTH FROM pa.game_date) IN (1, 2) THEN '3_MID'
    WHEN EXTRACT(MONTH FROM pa.game_date) IN (3, 4) THEN '4_LATE'
    ELSE '5_PLAYOFFS'
  END as season_phase,
  COUNT(*) as games,
  ROUND(AVG(pa.actual_points), 1) as avg_actual,
  ROUND(AVG(pa.absolute_error), 2) as mae,
  ROUND(AVG(pa.signed_error), 2) as bias
FROM `nba_predictions.prediction_accuracy` pa
WHERE pa.player_lookup = '{{PLAYER_LOOKUP}}'
  AND pa.system_id = 'ensemble_v1'
GROUP BY 1
ORDER BY 1;
```

**Key Question:** Does this player ramp up/down through the season?

### Home vs Away

```sql
SELECT
  CASE WHEN pa.team_id = g.home_team_id THEN 'HOME' ELSE 'AWAY' END as location,
  COUNT(*) as games,
  ROUND(AVG(pa.actual_points), 1) as avg_actual,
  ROUND(AVG(pa.signed_error), 2) as bias,
  ROUND(AVG(pa.absolute_error), 2) as mae
FROM `nba_predictions.prediction_accuracy` pa
JOIN `nba_raw.games` g ON pa.game_date = g.game_date  -- Adjust join as needed
WHERE pa.player_lookup = '{{PLAYER_LOOKUP}}'
  AND pa.system_id = 'ensemble_v1'
GROUP BY 1;
```

---

## 4. Minutes Analysis

### Minutes Consistency

```sql
SELECT
  ROUND(AVG(mlfs.minutes_recent_avg), 1) as expected_minutes,
  ROUND(AVG(pa.minutes_played), 1) as actual_avg_minutes,
  ROUND(STDDEV(pa.minutes_played), 1) as minutes_std,
  ROUND(CORR(pa.minutes_played, pa.actual_points), 3) as minutes_points_correlation
FROM `nba_predictions.prediction_accuracy` pa
JOIN `nba_predictions.ml_feature_store_v2` mlfs USING (player_lookup, game_date)
WHERE pa.player_lookup = '{{PLAYER_LOOKUP}}'
  AND pa.system_id = 'ensemble_v1';
```

### Minutes Miss → Points Miss

```sql
-- How much do minutes misses drive our errors?
SELECT
  CASE
    WHEN pa.minutes_played < mlfs.minutes_recent_avg - 8 THEN 'WAY_UNDER (-8+)'
    WHEN pa.minutes_played < mlfs.minutes_recent_avg - 4 THEN 'UNDER (-4 to -8)'
    WHEN pa.minutes_played > mlfs.minutes_recent_avg + 8 THEN 'WAY_OVER (+8+)'
    WHEN pa.minutes_played > mlfs.minutes_recent_avg + 4 THEN 'OVER (+4 to +8)'
    ELSE 'NORMAL'
  END as minutes_deviation,
  COUNT(*) as games,
  ROUND(AVG(pa.absolute_error), 2) as mae,
  ROUND(AVG(pa.signed_error), 2) as bias
FROM `nba_predictions.prediction_accuracy` pa
JOIN `nba_predictions.ml_feature_store_v2` mlfs USING (player_lookup, game_date)
WHERE pa.player_lookup = '{{PLAYER_LOOKUP}}'
  AND pa.system_id = 'ensemble_v1'
  AND pa.minutes_played IS NOT NULL
  AND mlfs.minutes_recent_avg IS NOT NULL
GROUP BY 1
ORDER BY 1;
```

**Key Question:** Are our biggest errors driven by minutes variance?

---

## 5. Error Analysis

### Worst Predictions

```sql
-- Find the 10 worst predictions to investigate
SELECT
  pa.game_date,
  pa.predicted_points,
  pa.actual_points,
  pa.absolute_error,
  pa.minutes_played,
  mlfs.minutes_recent_avg,
  mlfs.is_back_to_back,
  mlfs.days_rest,
  -- What might explain it?
  CASE
    WHEN pa.minutes_played < mlfs.minutes_recent_avg - 10 THEN 'EARLY_EXIT'
    WHEN pa.actual_points > pa.predicted_points + 10 THEN 'EXPLOSION'
    WHEN pa.actual_points < pa.predicted_points - 10 THEN 'DUD_GAME'
    ELSE 'UNCLEAR'
  END as likely_cause
FROM `nba_predictions.prediction_accuracy` pa
JOIN `nba_predictions.ml_feature_store_v2` mlfs USING (player_lookup, game_date)
WHERE pa.player_lookup = '{{PLAYER_LOOKUP}}'
  AND pa.system_id = 'ensemble_v1'
ORDER BY pa.absolute_error DESC
LIMIT 10;
```

**Manual Investigation:** For each bad prediction, ask:
- Did they leave early (injury, foul trouble, blowout)?
- Was this a career game / terrible game?
- Was there news we didn't capture (load management, illness)?

### Error Distribution

```sql
SELECT
  CASE
    WHEN absolute_error <= 2 THEN '0-2 (excellent)'
    WHEN absolute_error <= 4 THEN '2-4 (good)'
    WHEN absolute_error <= 6 THEN '4-6 (ok)'
    WHEN absolute_error <= 10 THEN '6-10 (poor)'
    ELSE '10+ (catastrophic)'
  END as error_bucket,
  COUNT(*) as n,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) as pct
FROM `nba_predictions.prediction_accuracy`
WHERE player_lookup = '{{PLAYER_LOOKUP}}'
  AND system_id = 'ensemble_v1'
GROUP BY 1
ORDER BY 1;
```

### Streakiness Check

```sql
-- Are errors correlated game-to-game? (Streaky player)
WITH errors AS (
  SELECT
    game_date,
    signed_error,
    LAG(signed_error) OVER (ORDER BY game_date) as prev_error
  FROM `nba_predictions.prediction_accuracy`
  WHERE player_lookup = '{{PLAYER_LOOKUP}}'
    AND system_id = 'ensemble_v1'
)
SELECT
  ROUND(CORR(signed_error, prev_error), 3) as error_autocorrelation,
  CASE
    WHEN CORR(signed_error, prev_error) > 0.3 THEN 'STREAKY - weight recent form more'
    WHEN CORR(signed_error, prev_error) < -0.2 THEN 'MEAN-REVERTING - regression expected'
    ELSE 'RANDOM - no pattern'
  END as interpretation
FROM errors
WHERE prev_error IS NOT NULL;
```

---

## 6. Season-by-Season Comparison

```sql
SELECT
  CASE
    WHEN game_date BETWEEN '2021-10-01' AND '2022-06-30' THEN '2021-22'
    WHEN game_date BETWEEN '2022-10-01' AND '2023-06-30' THEN '2022-23'
    WHEN game_date BETWEEN '2023-10-01' AND '2024-06-30' THEN '2023-24'
    ELSE '2024-25'
  END as season,
  COUNT(*) as games,
  ROUND(AVG(actual_points), 1) as avg_actual,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(AVG(signed_error), 2) as bias
FROM `nba_predictions.prediction_accuracy`
WHERE player_lookup = '{{PLAYER_LOOKUP}}'
  AND system_id = 'ensemble_v1'
GROUP BY 1
ORDER BY 1;
```

**Key Question:** Is our model getting better or worse for this player over time?

---

## 7. Full Timeline Export

Export for manual review in spreadsheet:

```sql
-- Export full prediction history
SELECT
  pa.game_date,
  pa.predicted_points,
  pa.actual_points,
  pa.absolute_error,
  pa.signed_error,
  pa.prediction_correct,
  pa.minutes_played,
  mlfs.minutes_recent_avg,
  mlfs.is_back_to_back,
  mlfs.days_rest,
  mlfs.season_avg,
  -- Individual system predictions
  xgb.predicted_points as xgb_pred,
  ma.predicted_points as ma_pred,
  sim.predicted_points as sim_pred,
  zone.predicted_points as zone_pred
FROM `nba_predictions.prediction_accuracy` pa
JOIN `nba_predictions.ml_feature_store_v2` mlfs USING (player_lookup, game_date)
LEFT JOIN `nba_predictions.player_prop_predictions` xgb
  ON pa.player_lookup = xgb.player_lookup AND pa.game_date = xgb.game_date AND xgb.system_id = 'xgboost_v1'
LEFT JOIN `nba_predictions.player_prop_predictions` ma
  ON pa.player_lookup = ma.player_lookup AND pa.game_date = ma.game_date AND ma.system_id = 'moving_average_baseline_v1'
LEFT JOIN `nba_predictions.player_prop_predictions` sim
  ON pa.player_lookup = sim.player_lookup AND pa.game_date = sim.game_date AND sim.system_id = 'similarity_balanced_v1'
LEFT JOIN `nba_predictions.player_prop_predictions` zone
  ON pa.player_lookup = zone.player_lookup AND pa.game_date = zone.game_date AND zone.system_id = 'zone_matchup_v1'
WHERE pa.player_lookup = '{{PLAYER_LOOKUP}}'
  AND pa.system_id = 'ensemble_v1'
ORDER BY pa.game_date;
```

---

## 8. Investigation Summary Template

After running queries, fill out this summary:

```markdown
## Player Investigation: {{PLAYER_NAME}}

**Date:** YYYY-MM-DD
**Total Predictions:** XXX
**Overall MAE:** X.XX
**Predictability:** [Highly Predictable / Average / Hard to Predict]

### Key Findings

1. **Best System:** [system_id] with MAE of X.XX
   - Gap vs ensemble: X.XX points

2. **Context Effects:**
   - B2B bias: X.XX (negative = we over-predict on B2B)
   - Home/Away difference: X.XX
   - Season phase pattern: [describe]

3. **Minutes Impact:**
   - Minutes correlation with errors: X.XX
   - % of big errors (10+) explained by minutes: XX%

4. **Worst Predictions:**
   - [Date]: Predicted XX, Actual XX - Cause: [early exit / explosion / unclear]
   - [Date]: Predicted XX, Actual XX - Cause: [...]

5. **Streakiness:** [Streaky / Mean-reverting / Random]

### Recommendations

- [ ] Use [system] instead of ensemble for this player
- [ ] Apply B2B adjustment of X.X
- [ ] Flag as unpredictable (lower confidence)
- [ ] No special handling needed
```

---

## 9. Players to Investigate

After aggregate analysis, investigate these player types:

| Category | Find Query | Why Investigate |
|----------|-----------|-----------------|
| Best predicted | `ORDER BY mae LIMIT 5` | What makes them easy? |
| Worst predicted | `ORDER BY mae DESC LIMIT 5` | Why do we fail? |
| Highest bias | `ORDER BY ABS(bias) DESC LIMIT 5` | Systematic errors |
| Most improved over time | Compare season MAE | Model learning? |
| High-volume star | Manual pick (LeBron, Jokic) | Important to get right |
| Volatile young player | High error stddev | Understand variance |
| Load-managed veteran | Kawhi, CP3 | Rest patterns |

### Find Worst Predicted Players

```sql
SELECT
  player_lookup,
  COUNT(*) as games,
  ROUND(AVG(absolute_error), 3) as mae,
  ROUND(STDDEV(absolute_error), 3) as error_std,
  ROUND(AVG(signed_error), 3) as bias
FROM `nba_predictions.prediction_accuracy`
WHERE system_id = 'ensemble_v1'
GROUP BY 1
HAVING games >= 30
ORDER BY mae DESC
LIMIT 20;
```

### Find Most Biased Players

```sql
SELECT
  player_lookup,
  COUNT(*) as games,
  ROUND(AVG(signed_error), 3) as bias,
  CASE WHEN AVG(signed_error) > 0 THEN 'OVER_PREDICT' ELSE 'UNDER_PREDICT' END as direction,
  ROUND(AVG(absolute_error), 3) as mae
FROM `nba_predictions.prediction_accuracy`
WHERE system_id = 'ensemble_v1'
GROUP BY 1
HAVING games >= 30
ORDER BY ABS(AVG(signed_error)) DESC
LIMIT 20;
```

---

## 10. Quick Investigation Checklist

- [ ] Run overview query - get baseline MAE, bias, predictability
- [ ] Compare systems - is ensemble actually best?
- [ ] Check B2B effect - is there fatigue bias?
- [ ] Check season phase - any pattern?
- [ ] Look at worst 10 predictions - what happened?
- [ ] Check minutes correlation - is that the driver?
- [ ] Check streakiness - weight recent form differently?
- [ ] Compare seasons - getting better or worse?
- [ ] Fill out summary template
- [ ] Decide: special handling needed?
