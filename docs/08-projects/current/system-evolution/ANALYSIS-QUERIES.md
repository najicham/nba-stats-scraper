# Analysis Queries: Discovering System Performance Patterns

**Last Updated:** 2025-12-11

Run these queries after backfill completes to discover which systems excel in which contexts.

---

## Prerequisites

These queries assume:
- `nba_predictions.prediction_accuracy` is populated (Phase 5B grading complete)
- `nba_predictions.player_prop_predictions` has predictions with context
- `nba_predictions.ml_feature_store_v2` has feature data

---

## 1. Baseline: Overall System Performance

**Start here.** Get the baseline to compare against.

```sql
-- Overall performance by system (all contexts)
SELECT
  system_id,
  COUNT(*) as predictions,
  ROUND(AVG(absolute_error), 3) as mae,
  ROUND(AVG(signed_error), 3) as bias,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1 ELSE 0 END) * 100, 1) as win_rate_pct,
  ROUND(AVG(CASE WHEN absolute_error <= 3 THEN 1 ELSE 0 END) * 100, 1) as within_3_pct,
  ROUND(AVG(CASE WHEN absolute_error <= 5 THEN 1 ELSE 0 END) * 100, 1) as within_5_pct
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
GROUP BY 1
ORDER BY mae;
```

---

## 2. Season Phase Analysis

**Key Question:** Does xgboost improve mid-season when it has more training data?

```sql
-- Performance by season phase
WITH game_counts AS (
  -- Count games per team per season to determine phase
  SELECT
    game_date,
    -- Approximate season phase based on month
    CASE
      WHEN EXTRACT(MONTH FROM game_date) IN (10, 11) THEN 'EARLY'
      WHEN EXTRACT(MONTH FROM game_date) = 12 THEN 'MID_EARLY'
      WHEN EXTRACT(MONTH FROM game_date) IN (1, 2) THEN 'MID_LATE'
      WHEN EXTRACT(MONTH FROM game_date) IN (3, 4) THEN 'LATE'
      ELSE 'PLAYOFFS'
    END as season_phase
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
)
SELECT
  g.season_phase,
  pa.system_id,
  COUNT(*) as n,
  ROUND(AVG(pa.absolute_error), 3) as mae,
  ROUND(AVG(pa.signed_error), 3) as bias,
  ROUND(AVG(CASE WHEN pa.prediction_correct THEN 1 ELSE 0 END) * 100, 1) as win_rate_pct
FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
JOIN game_counts g ON pa.game_date = g.game_date
GROUP BY 1, 2
HAVING n >= 100
ORDER BY g.season_phase, mae;
```

### Visual: Best System by Season Phase

```sql
-- Which system wins each phase?
WITH phase_performance AS (
  SELECT
    CASE
      WHEN EXTRACT(MONTH FROM game_date) IN (10, 11) THEN 'EARLY'
      WHEN EXTRACT(MONTH FROM game_date) = 12 THEN 'MID_EARLY'
      WHEN EXTRACT(MONTH FROM game_date) IN (1, 2) THEN 'MID_LATE'
      WHEN EXTRACT(MONTH FROM game_date) IN (3, 4) THEN 'LATE'
    END as season_phase,
    system_id,
    AVG(absolute_error) as mae
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE system_id != 'ensemble_v1'  -- Compare base systems
  GROUP BY 1, 2
),
ranked AS (
  SELECT
    season_phase,
    system_id,
    mae,
    RANK() OVER (PARTITION BY season_phase ORDER BY mae) as rank
  FROM phase_performance
  WHERE season_phase IS NOT NULL
)
SELECT * FROM ranked WHERE rank = 1
ORDER BY season_phase;
```

---

## 3. Scoring Tier Analysis

**Key Question:** Do different systems work better for stars vs role players?

```sql
-- Performance by scoring tier
WITH predictions_with_tier AS (
  SELECT
    p.scoring_tier,
    pa.system_id,
    pa.absolute_error,
    pa.signed_error,
    pa.prediction_correct
  FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
  JOIN `nba-props-platform.nba_predictions.prediction_accuracy` pa
    ON p.player_lookup = pa.player_lookup
    AND p.game_date = pa.game_date
    AND p.system_id = pa.system_id
  WHERE p.scoring_tier IS NOT NULL
)
SELECT
  scoring_tier,
  system_id,
  COUNT(*) as n,
  ROUND(AVG(absolute_error), 3) as mae,
  ROUND(AVG(signed_error), 3) as bias,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1 ELSE 0 END) * 100, 1) as win_rate_pct
FROM predictions_with_tier
GROUP BY 1, 2
HAVING n >= 50
ORDER BY scoring_tier, mae;
```

---

## 4. Home/Away Analysis

**Key Question:** Do we have a home/away bias issue?

```sql
-- Performance by location (if captured)
SELECT
  CASE WHEN pa.team_id = pa.home_team_id THEN 'HOME' ELSE 'AWAY' END as location,
  pa.system_id,
  COUNT(*) as n,
  ROUND(AVG(pa.absolute_error), 3) as mae,
  ROUND(AVG(pa.signed_error), 3) as bias
FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
GROUP BY 1, 2
HAVING n >= 100
ORDER BY location, mae;
```

---

## 5. Two-Dimensional Analysis: Season Phase + Tier

**Key Question:** Do stars and role players have different seasonal patterns?

```sql
-- Cross-tabulation: Season Phase x Scoring Tier
WITH enriched AS (
  SELECT
    CASE
      WHEN EXTRACT(MONTH FROM pa.game_date) IN (10, 11) THEN 'EARLY'
      WHEN EXTRACT(MONTH FROM pa.game_date) = 12 THEN 'MID_EARLY'
      WHEN EXTRACT(MONTH FROM pa.game_date) IN (1, 2) THEN 'MID_LATE'
      WHEN EXTRACT(MONTH FROM pa.game_date) IN (3, 4) THEN 'LATE'
    END as season_phase,
    p.scoring_tier,
    pa.system_id,
    pa.absolute_error
  FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
  JOIN `nba-props-platform.nba_predictions.player_prop_predictions` p
    ON pa.player_lookup = p.player_lookup
    AND pa.game_date = p.game_date
    AND pa.system_id = p.system_id
  WHERE p.scoring_tier IS NOT NULL
)
SELECT
  season_phase,
  scoring_tier,
  system_id,
  COUNT(*) as n,
  ROUND(AVG(absolute_error), 3) as mae
FROM enriched
WHERE season_phase IS NOT NULL
GROUP BY 1, 2, 3
HAVING n >= 30
ORDER BY season_phase, scoring_tier, mae;
```

---

## 6. Cross-Season Consistency

**Key Question:** Are patterns consistent across seasons, or just noise?

```sql
-- Check if the same system wins in multiple seasons
WITH season_system_performance AS (
  SELECT
    CASE
      WHEN game_date BETWEEN '2021-10-01' AND '2022-06-30' THEN '2021-22'
      WHEN game_date BETWEEN '2022-10-01' AND '2023-06-30' THEN '2022-23'
      WHEN game_date BETWEEN '2023-10-01' AND '2024-06-30' THEN '2023-24'
      WHEN game_date BETWEEN '2024-10-01' AND '2025-06-30' THEN '2024-25'
    END as season,
    system_id,
    AVG(absolute_error) as mae,
    COUNT(*) as n
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE system_id != 'ensemble_v1'
  GROUP BY 1, 2
),
ranked AS (
  SELECT
    season,
    system_id,
    mae,
    n,
    RANK() OVER (PARTITION BY season ORDER BY mae) as rank
  FROM season_system_performance
  WHERE season IS NOT NULL AND n >= 100
)
SELECT * FROM ranked
ORDER BY season, rank;
```

### Consistency Score

```sql
-- How often does each system rank in top 2?
WITH rankings AS (
  -- (same CTE as above)
  SELECT
    system_id,
    COUNTIF(rank <= 2) as top_2_finishes,
    COUNT(*) as seasons_measured
  FROM ranked
  GROUP BY 1
)
SELECT
  system_id,
  top_2_finishes,
  seasons_measured,
  ROUND(100.0 * top_2_finishes / seasons_measured, 1) as consistency_pct
FROM rankings
ORDER BY consistency_pct DESC;
```

---

## 7. Find Actionable Gaps

**Key Question:** Where is the MAE difference between systems large enough to matter?

```sql
-- Find contexts where best vs worst system differs by >0.5 MAE
WITH context_performance AS (
  SELECT
    CASE
      WHEN EXTRACT(MONTH FROM game_date) IN (10, 11) THEN 'EARLY'
      WHEN EXTRACT(MONTH FROM game_date) = 12 THEN 'MID_EARLY'
      WHEN EXTRACT(MONTH FROM game_date) IN (1, 2) THEN 'MID_LATE'
      ELSE 'LATE'
    END as season_phase,
    system_id,
    AVG(absolute_error) as mae,
    COUNT(*) as n
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE system_id != 'ensemble_v1'
  GROUP BY 1, 2
  HAVING n >= 100
)
SELECT
  season_phase,
  MIN(mae) as best_mae,
  MAX(mae) as worst_mae,
  MAX(mae) - MIN(mae) as gap,
  ARRAY_AGG(STRUCT(system_id, mae) ORDER BY mae LIMIT 1)[OFFSET(0)].system_id as best_system
FROM context_performance
GROUP BY 1
HAVING gap > 0.3
ORDER BY gap DESC;
```

---

## 8. Compute Optimal Weights Per Context

**Output for production use.**

```sql
-- Generate weight recommendations based on inverse MAE
WITH context_mae AS (
  SELECT
    CASE
      WHEN EXTRACT(MONTH FROM game_date) IN (10, 11) THEN 'EARLY'
      WHEN EXTRACT(MONTH FROM game_date) = 12 THEN 'MID_EARLY'
      WHEN EXTRACT(MONTH FROM game_date) IN (1, 2) THEN 'MID_LATE'
      ELSE 'LATE'
    END as season_phase,
    system_id,
    AVG(absolute_error) as mae
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE system_id IN ('xgboost_v1', 'moving_average_baseline_v1', 'similarity_balanced_v1', 'zone_matchup_v1')
  GROUP BY 1, 2
),
inverse_mae AS (
  SELECT
    season_phase,
    system_id,
    mae,
    1.0 / mae as inv_mae
  FROM context_mae
  WHERE season_phase IS NOT NULL
),
totals AS (
  SELECT
    season_phase,
    SUM(inv_mae) as total_inv_mae
  FROM inverse_mae
  GROUP BY 1
)
SELECT
  i.season_phase,
  i.system_id,
  ROUND(i.mae, 3) as mae,
  ROUND(i.inv_mae / t.total_inv_mae, 3) as recommended_weight
FROM inverse_mae i
JOIN totals t ON i.season_phase = t.season_phase
ORDER BY i.season_phase, recommended_weight DESC;
```

---

## 9. Validate: Would Context-Aware Weights Help?

**The key question: Is this worth doing?**

```sql
-- Compare static ensemble vs theoretical context-aware ensemble
WITH predictions_with_context AS (
  SELECT
    pa.game_date,
    pa.player_lookup,
    CASE
      WHEN EXTRACT(MONTH FROM pa.game_date) IN (10, 11) THEN 'EARLY'
      WHEN EXTRACT(MONTH FROM pa.game_date) = 12 THEN 'MID_EARLY'
      WHEN EXTRACT(MONTH FROM pa.game_date) IN (1, 2) THEN 'MID_LATE'
      ELSE 'LATE'
    END as season_phase,
    pa.system_id,
    pa.absolute_error
  FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
),
ensemble_static AS (
  SELECT game_date, player_lookup, absolute_error
  FROM predictions_with_context
  WHERE system_id = 'ensemble_v1'
),
-- Simulate: use best system per context
best_system_per_context AS (
  SELECT season_phase, system_id, AVG(absolute_error) as mae
  FROM predictions_with_context
  WHERE system_id != 'ensemble_v1'
  GROUP BY 1, 2
  QUALIFY RANK() OVER (PARTITION BY season_phase ORDER BY mae) = 1
),
simulated_adaptive AS (
  SELECT
    p.game_date,
    p.player_lookup,
    p.absolute_error
  FROM predictions_with_context p
  JOIN best_system_per_context b
    ON p.season_phase = b.season_phase
    AND p.system_id = b.system_id
)
SELECT
  'Static Ensemble' as approach,
  COUNT(*) as n,
  ROUND(AVG(absolute_error), 3) as mae
FROM ensemble_static

UNION ALL

SELECT
  'Oracle Best System' as approach,
  COUNT(*) as n,
  ROUND(AVG(absolute_error), 3) as mae
FROM simulated_adaptive;
```

**Interpretation:**
- If "Oracle Best System" MAE is much lower than static ensemble, there's signal to capture
- Gap of >0.1 MAE = definitely worth pursuing
- Gap of 0.05-0.1 MAE = probably worth it
- Gap of <0.05 MAE = marginal, may not be worth complexity

---

## 10. Export: Create Analysis Dashboard Data

```sql
-- Create summary table for dashboarding
CREATE OR REPLACE TABLE `nba-props-platform.nba_predictions.system_context_analysis` AS

WITH base AS (
  SELECT
    pa.game_date,
    pa.system_id,
    pa.absolute_error,
    pa.signed_error,
    pa.prediction_correct,
    CASE
      WHEN EXTRACT(MONTH FROM pa.game_date) IN (10, 11) THEN 'EARLY'
      WHEN EXTRACT(MONTH FROM pa.game_date) = 12 THEN 'MID_EARLY'
      WHEN EXTRACT(MONTH FROM pa.game_date) IN (1, 2) THEN 'MID_LATE'
      ELSE 'LATE'
    END as season_phase,
    CASE
      WHEN pa.game_date BETWEEN '2021-10-01' AND '2022-06-30' THEN '2021-22'
      WHEN pa.game_date BETWEEN '2022-10-01' AND '2023-06-30' THEN '2022-23'
      WHEN pa.game_date BETWEEN '2023-10-01' AND '2024-06-30' THEN '2023-24'
      ELSE '2024-25'
    END as season,
    p.scoring_tier
  FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
  LEFT JOIN `nba-props-platform.nba_predictions.player_prop_predictions` p
    ON pa.player_lookup = p.player_lookup
    AND pa.game_date = p.game_date
    AND pa.system_id = p.system_id
)
SELECT
  season,
  season_phase,
  scoring_tier,
  system_id,
  COUNT(*) as sample_size,
  ROUND(AVG(absolute_error), 4) as mae,
  ROUND(AVG(signed_error), 4) as bias,
  ROUND(AVG(CASE WHEN prediction_correct THEN 1 ELSE 0 END), 4) as win_rate,
  CURRENT_TIMESTAMP() as computed_at
FROM base
GROUP BY 1, 2, 3, 4
HAVING sample_size >= 20;
```

---

## Quick Reference: Run Order

1. **Query 1** - Get baseline
2. **Query 2** - Season phase patterns
3. **Query 3** - Tier patterns
4. **Query 6** - Cross-season consistency (is it real?)
5. **Query 9** - Validate: would this help?
6. If yes: **Query 8** - Compute recommended weights
