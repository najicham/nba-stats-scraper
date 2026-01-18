-- ============================================================================
-- View: confidence_calibration
-- Purpose: Check if confidence scores are well-calibrated
-- Expected: 90% confidence → ~90% accuracy
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.confidence_calibration` AS
SELECT
  system_id,

  -- Bucket confidence scores (e.g., 0.65-0.69 → 65)
  FLOOR(confidence_score * 100 / 5) * 5 as confidence_bucket,

  COUNT(*) as total_predictions,
  COUNTIF(prediction_correct) as correct_predictions,

  -- Actual accuracy in this confidence bucket
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 2) as actual_accuracy_pct,

  -- Average confidence in this bucket
  ROUND(AVG(confidence_score) * 100, 2) as avg_confidence,

  -- Calibration error (how far off is confidence from actual accuracy?)
  ROUND(AVG(confidence_score) * 100 - 100.0 * COUNTIF(prediction_correct) / COUNT(*), 2) as calibration_error,

  -- Additional metrics
  ROUND(AVG(margin_of_error), 2) as avg_margin_of_error,
  MIN(game_date) as first_prediction_date,
  MAX(game_date) as last_prediction_date

FROM `nba-props-platform.nba_predictions.prediction_grades`
WHERE
  prediction_correct IS NOT NULL  -- Only gradeable predictions
  AND has_issues = FALSE           -- Only clean data
  AND confidence_score > 0         -- Valid confidence scores
GROUP BY system_id, confidence_bucket
HAVING COUNT(*) >= 10  -- Minimum sample size for statistical significance
ORDER BY system_id, confidence_bucket DESC;
