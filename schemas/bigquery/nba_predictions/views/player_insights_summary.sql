-- ============================================================================
-- View: player_insights_summary
-- Purpose: Aggregated player performance across all systems for dashboard
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.player_insights_summary` AS
WITH player_stats AS (
  SELECT
    player_lookup,
    COUNT(DISTINCT system_id) as systems_tracking,
    COUNT(*) as total_predictions,
    COUNTIF(prediction_correct) as total_correct,
    COUNTIF(NOT prediction_correct) as total_incorrect,
    COUNTIF(prediction_correct IS NULL) as ungradeable,

    -- Accuracy
    ROUND(100.0 * COUNTIF(prediction_correct) / COUNTIF(prediction_correct IS NOT NULL), 2) as avg_accuracy_pct,

    -- Margin of error
    ROUND(AVG(CASE WHEN prediction_correct IS NOT NULL THEN margin_of_error END), 2) as avg_margin_of_error,

    -- Over/Under counts
    COUNTIF(recommendation = 'OVER' AND prediction_correct IS NOT NULL) as over_predictions,
    COUNTIF(recommendation = 'UNDER' AND prediction_correct IS NOT NULL) as under_predictions,

    -- Date range
    MIN(game_date) as first_prediction_date,
    MAX(game_date) as last_prediction_date

  FROM `nba-props-platform.nba_predictions.prediction_grades`
  WHERE has_issues = FALSE
  GROUP BY player_lookup
  HAVING COUNT(*) >= 15  -- Minimum sample size
),
best_system_per_player AS (
  SELECT
    player_lookup,
    system_id as best_system,
    accuracy_pct as best_system_accuracy,
    ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY accuracy_pct DESC, total_predictions DESC) as rn
  FROM `nba-props-platform.nba_predictions.player_prediction_performance`
)
SELECT
  ps.*,
  bs.best_system,
  ROUND(bs.best_system_accuracy, 2) as best_system_accuracy
FROM player_stats ps
LEFT JOIN best_system_per_player bs
  ON ps.player_lookup = bs.player_lookup
  AND bs.rn = 1
ORDER BY ps.avg_accuracy_pct DESC;
