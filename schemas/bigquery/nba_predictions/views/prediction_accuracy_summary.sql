-- ============================================================================
-- View: prediction_accuracy_summary
-- Purpose: Daily accuracy summary for all systems
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.prediction_accuracy_summary` AS
SELECT
  game_date,
  system_id,
  COUNT(*) as total_predictions,
  COUNTIF(prediction_correct) as correct_predictions,
  COUNTIF(NOT prediction_correct) as incorrect_predictions,
  COUNTIF(prediction_correct IS NULL) as ungradeable,
  COUNTIF(has_issues) as predictions_with_issues,

  -- Accuracy metrics
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNTIF(prediction_correct IS NOT NULL), 2) as accuracy_pct,
  ROUND(AVG(CASE WHEN prediction_correct IS NOT NULL THEN margin_of_error END), 2) as avg_margin_of_error,
  ROUND(AVG(CASE WHEN prediction_correct IS NOT NULL THEN confidence_score END) * 100, 2) as avg_confidence,

  -- Line performance
  ROUND(AVG(CASE WHEN prediction_correct IS NOT NULL THEN ABS(line_margin) END), 2) as avg_line_margin,

  -- Data quality
  COUNTIF(data_quality_tier = 'gold') as gold_tier_count,
  COUNTIF(data_quality_tier != 'gold') as non_gold_tier_count,

  -- Issue breakdown
  COUNTIF(player_dnp) as dnp_count,
  COUNTIF(actual_points IS NULL) as missing_actuals_count

FROM `nba-props-platform.nba_predictions.prediction_grades`
WHERE has_issues = FALSE  -- Only include clean predictions in accuracy calc
GROUP BY game_date, system_id
ORDER BY game_date DESC, accuracy_pct DESC;
