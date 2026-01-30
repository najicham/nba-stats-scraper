-- ============================================================================
-- View: player_insights_summary
-- Purpose: Aggregated player performance across all systems for dashboard
-- Updated: 2026-01-29 - Changed from prediction_grades to prediction_accuracy
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
    ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 2) as avg_accuracy_pct,

    -- Absolute error
    ROUND(AVG(CASE WHEN prediction_correct IS NOT NULL THEN absolute_error END), 2) as avg_absolute_error,

    -- Over/Under counts
    COUNTIF(recommendation = 'OVER' AND prediction_correct IS NOT NULL) as over_predictions,
    COUNTIF(recommendation = 'UNDER' AND prediction_correct IS NOT NULL) as under_predictions,

    -- Date range
    MIN(game_date) as first_prediction_date,
    MAX(game_date) as last_prediction_date

  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE (is_voided IS NULL OR is_voided = FALSE)  -- Only non-voided predictions
  GROUP BY player_lookup
  HAVING COUNT(*) >= 15  -- Minimum sample size
),
best_system_per_player AS (
  SELECT
    player_lookup,
    system_id as best_system,
    accuracy_pct as best_system_accuracy,
    ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY accuracy_pct DESC NULLS LAST, total_predictions DESC) as rn
  FROM `nba-props-platform.nba_predictions.player_prediction_performance`
  WHERE accuracy_pct IS NOT NULL
)
SELECT
  ps.*,
  bs.best_system,
  ROUND(bs.best_system_accuracy, 2) as best_system_accuracy
FROM player_stats ps
LEFT JOIN best_system_per_player bs
  ON ps.player_lookup = bs.player_lookup
  AND bs.rn = 1
ORDER BY ps.avg_accuracy_pct DESC NULLS LAST;
