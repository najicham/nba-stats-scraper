# Testing Ensemble Combinations Without Re-Backfilling

**Created:** 2025-12-11
**Key Insight:** Most experiments can run on existing data

---

## What Requires Backfill vs Not

| Experiment Type | Backfill Needed? | Why |
|-----------------|------------------|-----|
| Different ensemble weights | **NO** | Recompute from stored base predictions |
| Context-based adjustments | **NO** | Apply adjustment to stored predictions |
| Interaction adjustments (age + B2B) | **NO** | Query context, apply adjustment |
| New prediction system (LSTM) | **YES** | New model, new predictions |
| New feature IN a model (xgboost + rest) | **YES** | Model retrained, predictions change |
| Different tier boundaries | **NO** | Reclassify and recompute |

---

## The Magic: Retroactive Ensemble Computation

Since you stored all 4 base system predictions, you can compute ANY ensemble retroactively:

```sql
-- Compute a custom ensemble for ALL historical predictions
WITH base_predictions AS (
  SELECT
    player_lookup,
    game_date,
    MAX(CASE WHEN system_id = 'xgboost_v1' THEN predicted_points END) as xgb,
    MAX(CASE WHEN system_id = 'moving_average_baseline_v1' THEN predicted_points END) as ma,
    MAX(CASE WHEN system_id = 'similarity_balanced_v1' THEN predicted_points END) as sim,
    MAX(CASE WHEN system_id = 'zone_matchup_v1' THEN predicted_points END) as zone
  FROM `nba_predictions.player_prop_predictions`
  WHERE system_id IN ('xgboost_v1', 'moving_average_baseline_v1',
                      'similarity_balanced_v1', 'zone_matchup_v1')
  GROUP BY 1, 2
  HAVING xgb IS NOT NULL AND ma IS NOT NULL AND sim IS NOT NULL AND zone IS NOT NULL
),
actuals AS (
  SELECT player_lookup, game_date, actual_points
  FROM `nba_predictions.prediction_accuracy`
  WHERE system_id = 'ensemble_v1'  -- Any system, actuals are same
)
SELECT
  b.player_lookup,
  b.game_date,

  -- Original ensemble (25/25/25/25)
  (b.xgb * 0.25 + b.ma * 0.25 + b.sim * 0.25 + b.zone * 0.25) as ensemble_original,

  -- Test ensemble 1: Heavy XGBoost (40/20/20/20)
  (b.xgb * 0.40 + b.ma * 0.20 + b.sim * 0.20 + b.zone * 0.20) as ensemble_heavy_xgb,

  -- Test ensemble 2: Heavy Similarity (20/20/40/20)
  (b.xgb * 0.20 + b.ma * 0.20 + b.sim * 0.40 + b.zone * 0.20) as ensemble_heavy_sim,

  -- Test ensemble 3: No Moving Average (33/0/33/33)
  (b.xgb * 0.333 + b.ma * 0.0 + b.sim * 0.333 + b.zone * 0.333) as ensemble_no_ma,

  a.actual_points
FROM base_predictions b
JOIN actuals a USING (player_lookup, game_date);
```

### Compare MAE of Different Ensembles

```sql
WITH ensembles AS (
  -- (CTE from above)
)
SELECT
  'Original (25/25/25/25)' as ensemble,
  AVG(ABS(ensemble_original - actual_points)) as mae
FROM ensembles
UNION ALL
SELECT
  'Heavy XGB (40/20/20/20)' as ensemble,
  AVG(ABS(ensemble_heavy_xgb - actual_points)) as mae
FROM ensembles
UNION ALL
SELECT
  'Heavy Similarity (20/20/40/20)' as ensemble,
  AVG(ABS(ensemble_heavy_sim - actual_points)) as mae
FROM ensembles
UNION ALL
SELECT
  'No Moving Avg (33/0/33/33)' as ensemble,
  AVG(ABS(ensemble_no_ma - actual_points)) as mae
FROM ensembles
ORDER BY mae;
```

---

## Testing Context-Based Adjustments

### Example: Test "Veterans on B2B get -2 adjustment"

```sql
WITH predictions_with_context AS (
  SELECT
    pa.player_lookup,
    pa.game_date,
    pa.predicted_points,
    pa.actual_points,
    pa.absolute_error as original_error,
    mlfs.is_back_to_back,
    mlfs.player_age,  -- Or compute from birthdate
    CASE WHEN mlfs.player_age >= 32 AND mlfs.is_back_to_back THEN TRUE ELSE FALSE END as is_veteran_b2b
  FROM `nba_predictions.prediction_accuracy` pa
  JOIN `nba_predictions.ml_feature_store_v2` mlfs USING (player_lookup, game_date)
  WHERE pa.system_id = 'ensemble_v1'
),
with_adjustment AS (
  SELECT
    *,
    -- Apply hypothetical adjustment
    CASE WHEN is_veteran_b2b THEN predicted_points - 2.0 ELSE predicted_points END as adjusted_prediction,
    CASE WHEN is_veteran_b2b THEN ABS(predicted_points - 2.0 - actual_points) ELSE original_error END as adjusted_error
  FROM predictions_with_context
)
SELECT
  'Original' as version,
  COUNT(*) as n,
  ROUND(AVG(original_error), 4) as mae
FROM with_adjustment

UNION ALL

SELECT
  'With Veteran B2B -2 adj' as version,
  COUNT(*) as n,
  ROUND(AVG(adjusted_error), 4) as mae
FROM with_adjustment

UNION ALL

-- Breakdown by segment
SELECT
  'Veteran B2B only' as version,
  COUNT(*) as n,
  ROUND(AVG(adjusted_error), 4) as mae
FROM with_adjustment
WHERE is_veteran_b2b;
```

---

## Testing Interaction Effects

### Example: Different Weights by Context

Test: "Use heavy XGBoost mid-season, heavy Similarity early season"

```sql
WITH base_predictions AS (
  SELECT
    player_lookup,
    game_date,
    MAX(CASE WHEN system_id = 'xgboost_v1' THEN predicted_points END) as xgb,
    MAX(CASE WHEN system_id = 'moving_average_baseline_v1' THEN predicted_points END) as ma,
    MAX(CASE WHEN system_id = 'similarity_balanced_v1' THEN predicted_points END) as sim,
    MAX(CASE WHEN system_id = 'zone_matchup_v1' THEN predicted_points END) as zone
  FROM `nba_predictions.player_prop_predictions`
  WHERE system_id != 'ensemble_v1'
  GROUP BY 1, 2
),
with_context AS (
  SELECT
    b.*,
    a.actual_points,
    CASE
      WHEN EXTRACT(MONTH FROM b.game_date) IN (10, 11) THEN 'EARLY'
      WHEN EXTRACT(MONTH FROM b.game_date) IN (12, 1, 2) THEN 'MID'
      ELSE 'LATE'
    END as season_phase
  FROM base_predictions b
  JOIN (SELECT DISTINCT player_lookup, game_date, actual_points
        FROM `nba_predictions.prediction_accuracy`) a
    USING (player_lookup, game_date)
),
with_adaptive_ensemble AS (
  SELECT
    *,
    -- Static ensemble
    (xgb * 0.25 + ma * 0.25 + sim * 0.25 + zone * 0.25) as static_ensemble,

    -- Adaptive ensemble based on season phase
    CASE season_phase
      WHEN 'EARLY' THEN (xgb * 0.15 + ma * 0.25 + sim * 0.40 + zone * 0.20)  -- Heavy similarity
      WHEN 'MID'   THEN (xgb * 0.40 + ma * 0.20 + sim * 0.20 + zone * 0.20)  -- Heavy xgboost
      WHEN 'LATE'  THEN (xgb * 0.30 + ma * 0.20 + sim * 0.20 + zone * 0.30)  -- Heavy zone
    END as adaptive_ensemble
  FROM with_context
)
SELECT
  season_phase,
  COUNT(*) as n,
  ROUND(AVG(ABS(static_ensemble - actual_points)), 3) as static_mae,
  ROUND(AVG(ABS(adaptive_ensemble - actual_points)), 3) as adaptive_mae,
  ROUND(AVG(ABS(static_ensemble - actual_points)) - AVG(ABS(adaptive_ensemble - actual_points)), 3) as improvement
FROM with_adaptive_ensemble
GROUP BY 1
ORDER BY 1;
```

---

## Testing Complex Interactions

### Example: Age + Rest + Tier Combinations

```sql
WITH enriched AS (
  SELECT
    pa.player_lookup,
    pa.game_date,
    pa.predicted_points,
    pa.actual_points,
    p.scoring_tier,
    mlfs.is_back_to_back,
    -- Age group (would need player age data)
    CASE
      WHEN mlfs.player_age < 25 THEN 'YOUNG'
      WHEN mlfs.player_age < 32 THEN 'PRIME'
      ELSE 'VETERAN'
    END as age_group,
    -- Rest status
    CASE
      WHEN mlfs.days_rest >= 2 THEN 'RESTED'
      WHEN mlfs.is_back_to_back THEN 'B2B'
      ELSE 'NORMAL'
    END as rest_status
  FROM `nba_predictions.prediction_accuracy` pa
  JOIN `nba_predictions.player_prop_predictions` p USING (player_lookup, game_date, system_id)
  JOIN `nba_predictions.ml_feature_store_v2` mlfs USING (player_lookup, game_date)
  WHERE pa.system_id = 'ensemble_v1'
),
adjustment_grid AS (
  -- Define adjustments for each combination
  SELECT 'YOUNG' as age_group, 'B2B' as rest_status, -0.5 as adjustment UNION ALL
  SELECT 'YOUNG', 'NORMAL', 0.0 UNION ALL
  SELECT 'YOUNG', 'RESTED', 0.3 UNION ALL
  SELECT 'PRIME', 'B2B', -1.0 UNION ALL
  SELECT 'PRIME', 'NORMAL', 0.0 UNION ALL
  SELECT 'PRIME', 'RESTED', 0.2 UNION ALL
  SELECT 'VETERAN', 'B2B', -2.5 UNION ALL  -- Big adjustment for old + tired
  SELECT 'VETERAN', 'NORMAL', 0.0 UNION ALL
  SELECT 'VETERAN', 'RESTED', 0.5
),
with_adjustments AS (
  SELECT
    e.*,
    COALESCE(g.adjustment, 0) as context_adjustment,
    e.predicted_points + COALESCE(g.adjustment, 0) as adjusted_prediction
  FROM enriched e
  LEFT JOIN adjustment_grid g
    ON e.age_group = g.age_group AND e.rest_status = g.rest_status
)
SELECT
  'Original' as version,
  ROUND(AVG(ABS(predicted_points - actual_points)), 4) as mae
FROM with_adjustments
UNION ALL
SELECT
  'With Age+Rest Adjustments' as version,
  ROUND(AVG(ABS(adjusted_prediction - actual_points)), 4) as mae
FROM with_adjustments;
```

---

## Grid Search for Optimal Adjustments

Find the best adjustment values automatically:

```sql
-- Test multiple adjustment values for Veteran + B2B
WITH test_values AS (
  SELECT value FROM UNNEST([-4.0, -3.5, -3.0, -2.5, -2.0, -1.5, -1.0, -0.5, 0.0]) as value
),
predictions AS (
  SELECT
    pa.predicted_points,
    pa.actual_points,
    CASE WHEN mlfs.player_age >= 32 AND mlfs.is_back_to_back THEN TRUE ELSE FALSE END as is_veteran_b2b
  FROM `nba_predictions.prediction_accuracy` pa
  JOIN `nba_predictions.ml_feature_store_v2` mlfs USING (player_lookup, game_date)
  WHERE pa.system_id = 'ensemble_v1'
)
SELECT
  t.value as adjustment,
  ROUND(AVG(
    CASE
      WHEN p.is_veteran_b2b THEN ABS(p.predicted_points + t.value - p.actual_points)
      ELSE ABS(p.predicted_points - p.actual_points)
    END
  ), 4) as mae
FROM predictions p
CROSS JOIN test_values t
GROUP BY 1
ORDER BY mae;
```

---

## Framework: Experiment Runner

### Python Script for Testing Combinations

```python
# experiments/ensemble_tester.py

from google.cloud import bigquery
import itertools

client = bigquery.Client()

def test_ensemble_weights(weights: dict) -> float:
    """
    Test a specific weight combination on historical data.
    Returns MAE.
    """
    query = f"""
    WITH base AS (
      SELECT
        player_lookup, game_date,
        MAX(CASE WHEN system_id = 'xgboost_v1' THEN predicted_points END) as xgb,
        MAX(CASE WHEN system_id = 'moving_average_baseline_v1' THEN predicted_points END) as ma,
        MAX(CASE WHEN system_id = 'similarity_balanced_v1' THEN predicted_points END) as sim,
        MAX(CASE WHEN system_id = 'zone_matchup_v1' THEN predicted_points END) as zone
      FROM `nba_predictions.player_prop_predictions`
      WHERE system_id != 'ensemble_v1'
      GROUP BY 1, 2
    ),
    with_actual AS (
      SELECT b.*, a.actual_points
      FROM base b
      JOIN (SELECT DISTINCT player_lookup, game_date, actual_points
            FROM `nba_predictions.prediction_accuracy`) a USING (player_lookup, game_date)
    )
    SELECT AVG(ABS(
      xgb * {weights['xgb']} +
      ma * {weights['ma']} +
      sim * {weights['sim']} +
      zone * {weights['zone']}
      - actual_points
    )) as mae
    FROM with_actual
    """
    result = client.query(query).result()
    return list(result)[0].mae


def grid_search_weights(step: float = 0.05):
    """
    Grid search over weight combinations (must sum to 1.0).
    """
    results = []

    # Generate all combinations that sum to 1.0
    for xgb in [i * step for i in range(int(1/step) + 1)]:
        for ma in [i * step for i in range(int((1-xgb)/step) + 1)]:
            for sim in [i * step for i in range(int((1-xgb-ma)/step) + 1)]:
                zone = 1.0 - xgb - ma - sim
                if zone >= 0:
                    weights = {'xgb': xgb, 'ma': ma, 'sim': sim, 'zone': round(zone, 2)}
                    mae = test_ensemble_weights(weights)
                    results.append({**weights, 'mae': mae})

    # Sort by MAE
    results.sort(key=lambda x: x['mae'])
    return results


def test_context_adjustment(context_filter: str, adjustment: float) -> dict:
    """
    Test applying an adjustment to a specific context.
    Returns MAE with and without adjustment.
    """
    query = f"""
    WITH predictions AS (
      SELECT
        pa.predicted_points,
        pa.actual_points,
        ({context_filter}) as matches_context
      FROM `nba_predictions.prediction_accuracy` pa
      JOIN `nba_predictions.ml_feature_store_v2` mlfs USING (player_lookup, game_date)
      WHERE pa.system_id = 'ensemble_v1'
    )
    SELECT
      AVG(ABS(predicted_points - actual_points)) as mae_original,
      AVG(ABS(
        CASE WHEN matches_context THEN predicted_points + {adjustment} ELSE predicted_points END
        - actual_points
      )) as mae_adjusted,
      COUNTIF(matches_context) as context_count
    FROM predictions
    """
    result = list(client.query(query).result())[0]
    return {
        'original_mae': result.mae_original,
        'adjusted_mae': result.mae_adjusted,
        'improvement': result.mae_original - result.mae_adjusted,
        'context_count': result.context_count
    }


# Example usage
if __name__ == '__main__':
    # Test veteran B2B adjustment
    result = test_context_adjustment(
        context_filter="mlfs.player_age >= 32 AND mlfs.is_back_to_back",
        adjustment=-2.0
    )
    print(f"Veteran B2B adjustment of -2.0:")
    print(f"  Original MAE: {result['original_mae']:.4f}")
    print(f"  Adjusted MAE: {result['adjusted_mae']:.4f}")
    print(f"  Improvement: {result['improvement']:.4f}")
    print(f"  Affected predictions: {result['context_count']}")
```

---

## What DOES Require Backfill

### 1. New Prediction System
If you want to add an LSTM model, you need to:
- Train the model
- Generate predictions for all historical dates
- Store in prediction tables
- Grade against actuals

### 2. New Features IN Existing Models
If you want xgboost to USE days_rest as an input feature:
- Retrain the model with new features
- Regenerate all predictions
- This IS a backfill

### 3. Changes to ML Feature Store
If you want to add a new feature to MLFS:
- Backfill MLFS with new feature
- If models use it, retrain and backfill predictions

---

## Recommended Experiment Workflow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     EXPERIMENT WORKFLOW                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  1. HYPOTHESIS                                                              │
│     "Veterans on B2B need -2 adjustment"                                    │
│     "XGBoost should have 40% weight mid-season"                            │
│                                                                              │
│  2. RETROACTIVE TEST (No backfill)                                          │
│     Run SQL query on existing predictions                                   │
│     Compare MAE with vs without change                                      │
│                                                                              │
│  3. VALIDATE ACROSS SEASONS                                                 │
│     Check improvement in 2021-22, 2022-23, 2023-24                         │
│     Must improve in 2+ seasons to be real                                   │
│                                                                              │
│  4. IF VALIDATED → Implement in code                                        │
│     Add to ensemble logic or adjustment pipeline                            │
│     No backfill needed - just update going forward                          │
│                                                                              │
│  5. IF NOT VALIDATED → Document and move on                                 │
│     "Tested veteran B2B -2 adj, improved 0.02 MAE, not significant"        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Summary: What You Can Test Without Backfill

| Test | Method | Backfill? |
|------|--------|-----------|
| Different ensemble weights (40/20/20/20) | Recompute from base predictions | NO |
| Context-based adjustment (veteran B2B -2) | Apply to stored predictions | NO |
| Interaction adjustments (age + rest + tier) | Join context, apply grid | NO |
| Context-aware weights (different weights by season phase) | Conditional recompute | NO |
| Optimal adjustment values (grid search) | Test multiple values | NO |
| New prediction system (LSTM) | Generate new predictions | YES |
| New features in xgboost model | Retrain model | YES |
| Player embeddings/clustering | New approach | YES |

**Bottom line:** You have a LOT of experimentation you can do purely in SQL on existing data.
