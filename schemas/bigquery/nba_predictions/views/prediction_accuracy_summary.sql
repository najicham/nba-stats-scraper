-- ============================================================================
-- View: prediction_accuracy_summary
-- Purpose: Daily accuracy summary for all systems
-- Updated: 2026-01-29 - Changed from prediction_grades to prediction_accuracy
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.prediction_accuracy_summary` AS
SELECT
  game_date,
  system_id,
  COUNT(*) as total_predictions,
  COUNTIF(prediction_correct) as correct_predictions,
  COUNTIF(NOT prediction_correct) as incorrect_predictions,
  COUNTIF(prediction_correct IS NULL) as ungradeable,
  COUNTIF(is_voided = TRUE) as voided_predictions,

  -- Accuracy metrics
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNTIF(prediction_correct IS NOT NULL), 2) as accuracy_pct,
  ROUND(AVG(CASE WHEN prediction_correct IS NOT NULL THEN absolute_error END), 2) as avg_absolute_error,
  ROUND(AVG(CASE WHEN prediction_correct IS NOT NULL THEN confidence_score END) * 100, 2) as avg_confidence,

  -- Line performance
  ROUND(AVG(CASE WHEN prediction_correct IS NOT NULL THEN ABS(actual_margin) END), 2) as avg_line_margin,

  -- DNP/Voided breakdown
  COUNTIF(is_voided = TRUE) as dnp_count,
  COUNTIF(actual_points IS NULL) as missing_actuals_count

FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE (is_voided IS NULL OR is_voided = FALSE)  -- Only include non-voided in accuracy calc
GROUP BY game_date, system_id
ORDER BY game_date DESC, accuracy_pct DESC;
