-- ============================================================================
-- NBA Prediction Grading Query
-- ============================================================================
-- Purpose: Grade NBA predictions against actual results
-- Schedule: Daily at 12:00 PM PT (after boxscores ingested)
-- Destination: nba_predictions.prediction_grades
-- ============================================================================

-- Parameters:
-- @game_date: The game date to grade (defaults to yesterday)
-- Example: DECLARE game_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);

INSERT INTO `nba-props-platform.nba_predictions.prediction_grades` (
  prediction_id,
  player_lookup,
  game_id,
  game_date,
  system_id,
  predicted_points,
  confidence_score,
  recommendation,
  points_line,
  actual_points,
  actual_vs_line,
  prediction_correct,
  margin_of_error,
  line_margin,
  graded_at,
  grading_version,
  data_quality_tier,
  has_issues,
  issues,
  minutes_played,
  player_dnp
)
SELECT
  p.prediction_id,
  p.player_lookup,
  p.game_id,
  p.game_date,
  p.system_id,

  -- Prediction details
  CAST(p.predicted_points AS NUMERIC) as predicted_points,
  CAST(p.confidence_score AS NUMERIC) as confidence_score,
  p.recommendation,
  CAST(p.current_points_line AS NUMERIC) as points_line,

  -- Actual results
  a.points as actual_points,
  CASE
    WHEN a.points > p.current_points_line THEN 'OVER'
    WHEN a.points < p.current_points_line THEN 'UNDER'
    WHEN a.points = p.current_points_line THEN 'PUSH'
    ELSE NULL
  END as actual_vs_line,

  -- Grading results
  CASE
    -- Don't grade PASS predictions
    WHEN p.recommendation = 'PASS' THEN NULL
    -- Don't grade NO_LINE predictions
    WHEN p.recommendation = 'NO_LINE' THEN NULL
    -- Don't grade if player didn't play (0 minutes)
    WHEN a.minutes_played = 0 THEN NULL
    -- PUSH = no win/loss
    WHEN a.points = p.current_points_line THEN NULL
    -- OVER predictions
    WHEN p.recommendation = 'OVER' AND a.points > p.current_points_line THEN TRUE
    WHEN p.recommendation = 'OVER' AND a.points < p.current_points_line THEN FALSE
    -- UNDER predictions
    WHEN p.recommendation = 'UNDER' AND a.points < p.current_points_line THEN TRUE
    WHEN p.recommendation = 'UNDER' AND a.points > p.current_points_line THEN FALSE
    ELSE NULL
  END as prediction_correct,

  CAST(ABS(p.predicted_points - a.points) AS NUMERIC) as margin_of_error,
  CAST(a.points - p.current_points_line AS NUMERIC) as line_margin,

  -- Metadata
  CURRENT_TIMESTAMP() as graded_at,
  'v1' as grading_version,
  a.data_quality_tier,

  -- Issues detection
  CASE
    WHEN a.points IS NULL THEN TRUE
    WHEN a.minutes_played = 0 THEN TRUE
    WHEN a.data_quality_tier != 'gold' THEN TRUE
    WHEN p.current_points_line IS NULL THEN TRUE
    ELSE FALSE
  END as has_issues,

  ARRAY(
    SELECT issue FROM UNNEST([
      IF(a.points IS NULL, 'missing_actual_points', NULL),
      IF(a.minutes_played = 0, 'player_dnp', NULL),
      IF(a.data_quality_tier != 'gold', CONCAT('quality_tier_', COALESCE(a.data_quality_tier, 'unknown')), NULL),
      IF(p.current_points_line IS NULL, 'missing_betting_line', NULL)
    ]) AS issue
    WHERE issue IS NOT NULL
  ) as issues,

  CAST(a.minutes_played AS INT64) as minutes_played,
  a.minutes_played = 0 as player_dnp

FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
INNER JOIN `nba-props-platform.nba_analytics.player_game_summary` a
  ON p.player_lookup = a.player_lookup
  AND p.game_date = a.game_date

WHERE
  -- Only grade games from the specified date (configurable)
  p.game_date = @game_date

  -- Only grade active predictions (latest version)
  AND p.is_active = TRUE

  -- Grade all systems (or specify system_id in WHERE clause if needed)
  -- AND p.system_id = 'catboost_v8'

  -- Don't re-grade already graded predictions (idempotency)
  AND p.prediction_id NOT IN (
    SELECT prediction_id
    FROM `nba-props-platform.nba_predictions.prediction_grades`
    WHERE game_date = @game_date
  );
