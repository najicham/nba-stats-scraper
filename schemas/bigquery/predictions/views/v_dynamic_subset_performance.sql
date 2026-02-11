-- Dynamic Subset Performance Tracking View
-- Session 83 (2026-02-02)
-- Tracks performance of dynamic subsets with signal-based filtering

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.v_dynamic_subset_performance` AS

WITH subset_definitions AS (
  SELECT
    subset_id,
    system_id,
    use_ranking,
    top_n,
    signal_condition,
    min_edge,
    min_confidence
  FROM `nba-props-platform.nba_predictions.dynamic_subset_definitions`
  WHERE is_active = TRUE
),

base_predictions AS (
  SELECT
    p.game_date,
    p.system_id,
    p.player_lookup,
    p.predicted_points,
    p.current_points_line,
    p.recommendation,
    p.confidence_score,
    ABS(p.predicted_points - p.current_points_line) as edge,
    (ABS(p.predicted_points - p.current_points_line) * 10) + (p.confidence_score * 0.5) as composite_score,
    pgs.points as actual_points,
    s.daily_signal,
    s.pct_over
  FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
  LEFT JOIN `nba-props-platform.nba_analytics.player_game_summary` pgs
    ON p.player_lookup = pgs.player_lookup AND p.game_date = pgs.game_date
  LEFT JOIN `nba-props-platform.nba_predictions.daily_prediction_signals` s
    ON p.game_date = s.game_date AND p.system_id = s.system_id
  WHERE p.is_active = TRUE
    AND p.current_points_line IS NOT NULL
),

ranked_predictions AS (
  SELECT
    d.subset_id,
    d.use_ranking,
    d.top_n,
    d.signal_condition,
    p.*,
    ROW_NUMBER() OVER (
      PARTITION BY d.subset_id, p.game_date
      ORDER BY p.composite_score DESC
    ) as daily_rank
  FROM base_predictions p
  CROSS JOIN subset_definitions d
  WHERE p.system_id = d.system_id
    AND p.edge >= COALESCE(d.min_edge, 0)
    AND (d.min_confidence IS NULL OR p.confidence_score >= d.min_confidence)
),

filtered_predictions AS (
  SELECT
    subset_id,
    game_date,
    player_lookup,
    predicted_points,
    current_points_line,
    recommendation,
    confidence_score,
    edge,
    composite_score,
    actual_points,
    daily_signal,
    pct_over,
    daily_rank,
    -- Determine if pick should be included based on signal condition
    CASE
      WHEN signal_condition = 'ANY' THEN TRUE
      WHEN signal_condition = 'GREEN' AND daily_signal = 'GREEN' THEN TRUE
      WHEN signal_condition = 'GREEN_OR_YELLOW' AND daily_signal IN ('GREEN', 'YELLOW') THEN TRUE
      WHEN signal_condition = 'RED' AND daily_signal = 'RED' THEN TRUE
      ELSE FALSE
    END as signal_match,
    -- Determine if pick qualifies for ranking (before signal filter)
    CASE
      WHEN use_ranking = TRUE AND daily_rank <= top_n THEN TRUE
      WHEN use_ranking = FALSE THEN TRUE
      ELSE FALSE
    END as rank_qualifies
  FROM ranked_predictions
),

final_picks AS (
  SELECT *
  FROM filtered_predictions
  WHERE rank_qualifies = TRUE
    AND signal_match = TRUE
),

performance_by_subset AS (
  SELECT
    subset_id,
    game_date,
    daily_signal,
    pct_over,

    -- Volume metrics
    COUNT(*) as picks,
    COUNT(DISTINCT player_lookup) as unique_players,

    -- Performance metrics (only for completed games)
    COUNTIF(actual_points IS NOT NULL AND actual_points != current_points_line) as graded_picks,
    COUNTIF(
      actual_points IS NOT NULL
      AND actual_points != current_points_line
      AND (
        (actual_points > current_points_line AND recommendation = 'OVER') OR
        (actual_points < current_points_line AND recommendation = 'UNDER')
      )
    ) as wins,

    ROUND(100.0 * COUNTIF(
      actual_points IS NOT NULL
      AND actual_points != current_points_line
      AND (
        (actual_points > current_points_line AND recommendation = 'OVER') OR
        (actual_points < current_points_line AND recommendation = 'UNDER')
      )
    ) / NULLIF(COUNTIF(actual_points IS NOT NULL AND actual_points != current_points_line), 0), 1) as hit_rate,

    -- Quality metrics
    ROUND(AVG(edge), 2) as avg_edge,
    ROUND(AVG(confidence_score), 2) as avg_confidence,
    ROUND(AVG(composite_score), 1) as avg_composite_score,

    -- Error metrics (only for graded picks)
    ROUND(AVG(CASE WHEN actual_points IS NOT NULL THEN ABS(predicted_points - actual_points) END), 2) as mae,

    -- Directional breakdown
    COUNTIF(recommendation = 'OVER') as overs,
    COUNTIF(recommendation = 'UNDER') as unders,
    ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) as pct_overs

  FROM final_picks
  GROUP BY subset_id, game_date, daily_signal, pct_over
)

SELECT
  p.subset_id,
  d.subset_name,
  p.game_date,
  p.daily_signal,
  p.pct_over,
  d.signal_condition,
  d.use_ranking,
  d.top_n,
  d.min_edge,
  d.min_confidence,
  p.picks,
  p.unique_players,
  p.graded_picks,
  p.wins,
  p.hit_rate,
  p.avg_edge,
  p.avg_confidence,
  p.avg_composite_score,
  p.mae,
  p.overs,
  p.unders,
  p.pct_overs
FROM performance_by_subset p
JOIN `nba-props-platform.nba_predictions.dynamic_subset_definitions` d
  ON p.subset_id = d.subset_id
WHERE d.is_active = TRUE
ORDER BY p.game_date DESC, p.subset_id;
