-- =============================================================================
-- Historical Analysis Queries
-- Used to discover and validate pre-game signals
-- =============================================================================

-- Query 1: Daily Performance with Signals
-- Core query that correlates pre-game signals with actual hit rates
WITH predictions AS (
  SELECT
    p.game_date,
    p.system_id,
    p.player_lookup,
    p.predicted_points,
    p.current_points_line,
    p.confidence_score,
    p.recommendation,
    ABS(p.predicted_points - p.current_points_line) as edge,
    pgs.points as actual_points
  FROM nba_predictions.player_prop_predictions p
  JOIN nba_analytics.player_game_summary pgs
    ON p.player_lookup = pgs.player_lookup AND p.game_date = pgs.game_date
  WHERE p.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
    AND p.system_id = 'catboost_v9'
    AND p.current_points_line IS NOT NULL
)
SELECT
  game_date,

  -- Pre-game signals (knowable before games)
  COUNT(*) as total_picks,
  SUM(CASE WHEN edge >= 5 THEN 1 ELSE 0 END) as high_edge_picks,
  ROUND(AVG(confidence_score), 2) as avg_confidence,
  ROUND(AVG(edge), 2) as avg_edge,
  ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) as pct_over,

  -- Outcomes (only knowable after games)
  ROUND(100.0 * COUNTIF(
    edge >= 5 AND
    ((actual_points > current_points_line AND recommendation = 'OVER') OR
     (actual_points < current_points_line AND recommendation = 'UNDER'))
  ) / NULLIF(COUNTIF(edge >= 5 AND actual_points != current_points_line), 0), 1) as high_edge_hit_rate,

  -- Classification
  CASE
    WHEN ROUND(100.0 * COUNTIF(
      edge >= 5 AND
      ((actual_points > current_points_line AND recommendation = 'OVER') OR
       (actual_points < current_points_line AND recommendation = 'UNDER'))
    ) / NULLIF(COUNTIF(edge >= 5 AND actual_points != current_points_line), 0), 1) >= 60 THEN 'GOOD'
    WHEN ROUND(100.0 * COUNTIF(
      edge >= 5 AND
      ((actual_points > current_points_line AND recommendation = 'OVER') OR
       (actual_points < current_points_line AND recommendation = 'UNDER'))
    ) / NULLIF(COUNTIF(edge >= 5 AND actual_points != current_points_line), 0), 1) >= 45 THEN 'OK'
    ELSE 'BAD'
  END as day_quality

FROM predictions
GROUP BY game_date
ORDER BY game_date DESC;


-- Query 2: Signal Correlation Analysis
-- Group days by pct_over ranges and see average hit rates
WITH daily_data AS (
  SELECT
    p.game_date,
    ROUND(100.0 * COUNTIF(p.recommendation = 'OVER') / COUNT(*), 1) as pct_over,
    ROUND(100.0 * COUNTIF(
      ABS(p.predicted_points - p.current_points_line) >= 5 AND
      ((pgs.points > p.current_points_line AND p.recommendation = 'OVER') OR
       (pgs.points < p.current_points_line AND p.recommendation = 'UNDER'))
    ) / NULLIF(COUNTIF(
      ABS(p.predicted_points - p.current_points_line) >= 5 AND
      pgs.points != p.current_points_line
    ), 0), 1) as high_edge_hit_rate
  FROM nba_predictions.player_prop_predictions p
  JOIN nba_analytics.player_game_summary pgs
    ON p.player_lookup = pgs.player_lookup AND p.game_date = pgs.game_date
  WHERE p.game_date >= DATE('2026-01-01')
    AND p.system_id = 'catboost_v9'
    AND p.current_points_line IS NOT NULL
  GROUP BY p.game_date
)
SELECT
  CASE
    WHEN pct_over < 20 THEN '1. <20% (Extreme Under)'
    WHEN pct_over < 25 THEN '2. 20-25% (Heavy Under)'
    WHEN pct_over < 30 THEN '3. 25-30% (Slight Under)'
    WHEN pct_over < 35 THEN '4. 30-35% (Balanced)'
    WHEN pct_over < 40 THEN '5. 35-40% (Slight Over)'
    ELSE '6. 40%+ (Heavy Over)'
  END as pct_over_bucket,
  COUNT(*) as days,
  ROUND(AVG(high_edge_hit_rate), 1) as avg_hit_rate,
  ROUND(MIN(high_edge_hit_rate), 1) as min_hit_rate,
  ROUND(MAX(high_edge_hit_rate), 1) as max_hit_rate
FROM daily_data
WHERE high_edge_hit_rate IS NOT NULL
GROUP BY 1
ORDER BY 1;


-- Query 3: V8 vs V9 Comparison
-- Compare performance between models
WITH predictions AS (
  SELECT
    p.game_date,
    p.system_id,
    ABS(p.predicted_points - p.current_points_line) as edge,
    p.recommendation,
    p.current_points_line,
    pgs.points as actual_points
  FROM nba_predictions.player_prop_predictions p
  JOIN nba_analytics.player_game_summary pgs
    ON p.player_lookup = pgs.player_lookup AND p.game_date = pgs.game_date
  WHERE p.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND p.system_id IN ('catboost_v9', 'catboost_v8')
    AND p.current_points_line IS NOT NULL
)
SELECT
  system_id,
  COUNT(*) as total_picks,
  SUM(CASE WHEN edge >= 5 THEN 1 ELSE 0 END) as high_edge_picks,

  -- Overall hit rate
  ROUND(100.0 * COUNTIF(
    (actual_points > current_points_line AND recommendation = 'OVER') OR
    (actual_points < current_points_line AND recommendation = 'UNDER')
  ) / NULLIF(COUNTIF(actual_points != current_points_line), 0), 1) as overall_hit_rate,

  -- High edge hit rate
  ROUND(100.0 * COUNTIF(
    edge >= 5 AND
    ((actual_points > current_points_line AND recommendation = 'OVER') OR
     (actual_points < current_points_line AND recommendation = 'UNDER'))
  ) / NULLIF(COUNTIF(edge >= 5 AND actual_points != current_points_line), 0), 1) as high_edge_hit_rate

FROM predictions
GROUP BY system_id;


-- Query 4: Pick Volume vs Performance
-- See if number of high-edge picks correlates with hit rate
WITH daily_data AS (
  SELECT
    p.game_date,
    SUM(CASE WHEN ABS(p.predicted_points - p.current_points_line) >= 5 THEN 1 ELSE 0 END) as high_edge_picks,
    ROUND(100.0 * COUNTIF(
      ABS(p.predicted_points - p.current_points_line) >= 5 AND
      ((pgs.points > p.current_points_line AND p.recommendation = 'OVER') OR
       (pgs.points < p.current_points_line AND p.recommendation = 'UNDER'))
    ) / NULLIF(COUNTIF(
      ABS(p.predicted_points - p.current_points_line) >= 5 AND
      pgs.points != p.current_points_line
    ), 0), 1) as high_edge_hit_rate
  FROM nba_predictions.player_prop_predictions p
  JOIN nba_analytics.player_game_summary pgs
    ON p.player_lookup = pgs.player_lookup AND p.game_date = pgs.game_date
  WHERE p.game_date >= DATE('2026-01-01')
    AND p.system_id = 'catboost_v9'
    AND p.current_points_line IS NOT NULL
  GROUP BY p.game_date
)
SELECT
  CASE
    WHEN high_edge_picks <= 2 THEN '1. 1-2 picks'
    WHEN high_edge_picks <= 4 THEN '2. 3-4 picks'
    WHEN high_edge_picks <= 6 THEN '3. 5-6 picks'
    WHEN high_edge_picks <= 8 THEN '4. 7-8 picks'
    ELSE '5. 9+ picks'
  END as pick_volume_bucket,
  COUNT(*) as days,
  ROUND(AVG(high_edge_hit_rate), 1) as avg_hit_rate,
  ROUND(STDDEV(high_edge_hit_rate), 1) as stddev_hit_rate
FROM daily_data
WHERE high_edge_hit_rate IS NOT NULL
GROUP BY 1
ORDER BY 1;


-- Query 5: Confidence Score Analysis
-- Does average confidence predict performance?
WITH daily_data AS (
  SELECT
    p.game_date,
    ROUND(AVG(p.confidence_score), 1) as avg_confidence,
    ROUND(100.0 * COUNTIF(
      ABS(p.predicted_points - p.current_points_line) >= 5 AND
      ((pgs.points > p.current_points_line AND p.recommendation = 'OVER') OR
       (pgs.points < p.current_points_line AND p.recommendation = 'UNDER'))
    ) / NULLIF(COUNTIF(
      ABS(p.predicted_points - p.current_points_line) >= 5 AND
      pgs.points != p.current_points_line
    ), 0), 1) as high_edge_hit_rate
  FROM nba_predictions.player_prop_predictions p
  JOIN nba_analytics.player_game_summary pgs
    ON p.player_lookup = pgs.player_lookup AND p.game_date = pgs.game_date
  WHERE p.game_date >= DATE('2026-01-01')
    AND p.system_id = 'catboost_v9'
    AND p.current_points_line IS NOT NULL
  GROUP BY p.game_date
)
SELECT
  CASE
    WHEN avg_confidence < 86 THEN '1. <86'
    WHEN avg_confidence < 87 THEN '2. 86-87'
    WHEN avg_confidence < 88 THEN '3. 87-88'
    WHEN avg_confidence < 89 THEN '4. 88-89'
    ELSE '5. 89+'
  END as confidence_bucket,
  COUNT(*) as days,
  ROUND(AVG(high_edge_hit_rate), 1) as avg_hit_rate
FROM daily_data
WHERE high_edge_hit_rate IS NOT NULL
GROUP BY 1
ORDER BY 1;
