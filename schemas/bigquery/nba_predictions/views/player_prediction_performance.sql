-- ============================================================================
-- View: player_prediction_performance
-- Purpose: Per-player accuracy across all systems
-- Updated: 2026-01-29 - Changed from prediction_grades to prediction_accuracy
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.player_prediction_performance` AS
SELECT
  player_lookup,
  system_id,

  -- Prediction volume
  COUNT(*) as total_predictions,
  COUNT(DISTINCT game_date) as games_predicted,

  -- Accuracy metrics
  COUNTIF(prediction_correct) as correct,
  COUNTIF(NOT prediction_correct) as incorrect,
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 2) as accuracy_pct,

  -- Performance metrics
  ROUND(AVG(CASE WHEN prediction_correct IS NOT NULL THEN absolute_error END), 2) as avg_absolute_error,
  ROUND(AVG(CASE WHEN prediction_correct THEN confidence_score ELSE NULL END) * 100, 2) as avg_confidence_when_correct,
  ROUND(AVG(CASE WHEN NOT prediction_correct THEN confidence_score ELSE NULL END) * 100, 2) as avg_confidence_when_wrong,

  -- Point prediction stats
  ROUND(AVG(predicted_points), 1) as avg_predicted_points,
  ROUND(AVG(actual_points), 1) as avg_actual_points,

  -- Line performance
  COUNTIF(recommendation = 'OVER') as over_count,
  COUNTIF(recommendation = 'UNDER') as under_count,
  COUNTIF(recommendation = 'PASS') as pass_count,

  -- Over/Under split accuracy
  ROUND(100.0 * COUNTIF(recommendation = 'OVER' AND prediction_correct) /
    NULLIF(COUNTIF(recommendation = 'OVER' AND prediction_correct IS NOT NULL), 0), 2) as over_accuracy_pct,
  ROUND(100.0 * COUNTIF(recommendation = 'UNDER' AND prediction_correct) /
    NULLIF(COUNTIF(recommendation = 'UNDER' AND prediction_correct IS NOT NULL), 0), 2) as under_accuracy_pct,

  -- Date range
  MIN(game_date) as first_prediction,
  MAX(game_date) as last_prediction

FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE (is_voided IS NULL OR is_voided = FALSE)  -- Only non-voided predictions
GROUP BY player_lookup, system_id
HAVING COUNT(*) >= 5  -- Minimum sample size
ORDER BY accuracy_pct DESC, total_predictions DESC;
