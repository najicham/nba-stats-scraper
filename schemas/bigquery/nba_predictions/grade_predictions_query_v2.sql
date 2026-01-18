-- ============================================================================
-- NBA Prediction Grading Query V2 (IMPROVED DEDUPLICATION)
-- ============================================================================
-- Purpose: Grade NBA predictions against actual results with robust duplicate prevention
-- Schedule: Daily at 12:00 PM PT (after boxscores ingested)
-- Destination: nba_predictions.prediction_grades
--
-- Changes from V1:
-- - Improved deduplication logic using composite key instead of just prediction_id
-- - Added defensive MERGE statement option for safer upserts
-- - Better handling of NULL betting lines
-- ============================================================================

-- Parameters:
-- @game_date: The game date to grade (defaults to yesterday)
-- Example: DECLARE game_date DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);

-- Option A: INSERT with improved deduplication (recommended)
-- ============================================================================
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
    WHEN p.recommendation = 'PASS' THEN NULL
    WHEN p.recommendation = 'NO_LINE' THEN NULL
    WHEN a.minutes_played = 0 THEN NULL
    WHEN a.points = p.current_points_line THEN NULL
    WHEN p.recommendation = 'OVER' AND a.points > p.current_points_line THEN TRUE
    WHEN p.recommendation = 'OVER' AND a.points < p.current_points_line THEN FALSE
    WHEN p.recommendation = 'UNDER' AND a.points < p.current_points_line THEN TRUE
    WHEN p.recommendation = 'UNDER' AND a.points > p.current_points_line THEN FALSE
    ELSE NULL
  END as prediction_correct,

  CAST(ABS(p.predicted_points - a.points) AS NUMERIC) as margin_of_error,
  CAST(a.points - p.current_points_line AS NUMERIC) as line_margin,

  -- Metadata
  CURRENT_TIMESTAMP() as graded_at,
  'v2' as grading_version,
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
  p.game_date = @game_date
  AND p.is_active = TRUE

  -- IMPROVED: Use composite key for deduplication (not just prediction_id)
  -- This prevents duplicates even if prediction_id changes or query re-runs
  AND NOT EXISTS (
    SELECT 1
    FROM `nba-props-platform.nba_predictions.prediction_grades` g
    WHERE g.player_lookup = p.player_lookup
      AND g.game_date = p.game_date
      AND g.system_id = p.system_id
      -- Handle NULL betting lines explicitly
      AND (
        (g.points_line IS NULL AND p.current_points_line IS NULL) OR
        (g.points_line = p.current_points_line)
      )
  );


-- Option B: MERGE statement for safer upserts (alternative approach)
-- ============================================================================
-- Use this if you want to update existing grades instead of preventing duplicates
-- Commented out by default - use INSERT above for normal operations

/*
MERGE `nba-props-platform.nba_predictions.prediction_grades` T
USING (
  SELECT
    p.prediction_id,
    p.player_lookup,
    p.game_id,
    p.game_date,
    p.system_id,
    CAST(p.predicted_points AS NUMERIC) as predicted_points,
    CAST(p.confidence_score AS NUMERIC) as confidence_score,
    p.recommendation,
    CAST(p.current_points_line AS NUMERIC) as points_line,
    a.points as actual_points,
    CASE
      WHEN a.points > p.current_points_line THEN 'OVER'
      WHEN a.points < p.current_points_line THEN 'UNDER'
      WHEN a.points = p.current_points_line THEN 'PUSH'
      ELSE NULL
    END as actual_vs_line,
    CASE
      WHEN p.recommendation = 'PASS' THEN NULL
      WHEN p.recommendation = 'NO_LINE' THEN NULL
      WHEN a.minutes_played = 0 THEN NULL
      WHEN a.points = p.current_points_line THEN NULL
      WHEN p.recommendation = 'OVER' AND a.points > p.current_points_line THEN TRUE
      WHEN p.recommendation = 'OVER' AND a.points < p.current_points_line THEN FALSE
      WHEN p.recommendation = 'UNDER' AND a.points < p.current_points_line THEN TRUE
      WHEN p.recommendation = 'UNDER' AND a.points > p.current_points_line THEN FALSE
      ELSE NULL
    END as prediction_correct,
    CAST(ABS(p.predicted_points - a.points) AS NUMERIC) as margin_of_error,
    CAST(a.points - p.current_points_line AS NUMERIC) as line_margin,
    CURRENT_TIMESTAMP() as graded_at,
    'v2_merge' as grading_version,
    a.data_quality_tier,
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
  WHERE p.game_date = @game_date
    AND p.is_active = TRUE
) S
ON T.player_lookup = S.player_lookup
  AND T.game_date = S.game_date
  AND T.system_id = S.system_id
  AND (
    (T.points_line IS NULL AND S.points_line IS NULL) OR
    (T.points_line = S.points_line)
  )
WHEN MATCHED THEN
  UPDATE SET
    actual_points = S.actual_points,
    actual_vs_line = S.actual_vs_line,
    prediction_correct = S.prediction_correct,
    margin_of_error = S.margin_of_error,
    line_margin = S.line_margin,
    graded_at = S.graded_at,
    grading_version = S.grading_version,
    data_quality_tier = S.data_quality_tier,
    has_issues = S.has_issues,
    issues = S.issues,
    minutes_played = S.minutes_played,
    player_dnp = S.player_dnp
WHEN NOT MATCHED THEN
  INSERT (
    prediction_id, player_lookup, game_id, game_date, system_id,
    predicted_points, confidence_score, recommendation, points_line,
    actual_points, actual_vs_line, prediction_correct,
    margin_of_error, line_margin, graded_at, grading_version,
    data_quality_tier, has_issues, issues, minutes_played, player_dnp
  )
  VALUES (
    S.prediction_id, S.player_lookup, S.game_id, S.game_date, S.system_id,
    S.predicted_points, S.confidence_score, S.recommendation, S.points_line,
    S.actual_points, S.actual_vs_line, S.prediction_correct,
    S.margin_of_error, S.line_margin, S.graded_at, S.grading_version,
    S.data_quality_tier, S.has_issues, S.issues, S.minutes_played, S.player_dnp
  );
*/
