-- ============================================================================
-- Pick Subset Performance View
-- ============================================================================
-- Purpose: Calculate performance metrics for each defined subset
--
-- Note: This uses a CASE-based approach rather than dynamic SQL since
-- BigQuery views don't support dynamic filter application.
--
-- Each subset is calculated inline based on its filter criteria.
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.v_subset_performance` AS

WITH base_accuracy AS (
  SELECT *
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE system_id = 'catboost_v8'
    AND prediction_correct IS NOT NULL
),

subset_metrics AS (
  -- Actionable Filtered (Primary - what we recommend)
  SELECT
    'actionable_filtered' as subset_id,
    'Actionable Picks (Filtered)' as subset_name,
    'OVER/UNDER with real lines, excluding 88-90% problem tier' as subset_description,
    1 as display_order,
    TRUE as is_primary,
    game_date,
    COUNT(*) as picks,
    COUNTIF(prediction_correct = TRUE) as wins,
    COUNTIF(prediction_correct = FALSE) as losses,
    ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100, 1) as win_rate,
    ROUND(AVG(absolute_error), 2) as mae,
    ROUND(AVG(confidence_score) * 100, 1) as avg_confidence
  FROM base_accuracy
  WHERE recommendation IN ('OVER', 'UNDER')
    AND has_prop_line = TRUE
    AND NOT (confidence_score >= 0.88 AND confidence_score < 0.90)
  GROUP BY game_date

  UNION ALL

  -- All Actionable (Unfiltered baseline)
  SELECT
    'actionable_all' as subset_id,
    'All Actionable Picks (Unfiltered)' as subset_name,
    'All OVER/UNDER picks with real lines (no filtering)' as subset_description,
    2 as display_order,
    FALSE as is_primary,
    game_date,
    COUNT(*) as picks,
    COUNTIF(prediction_correct = TRUE) as wins,
    COUNTIF(prediction_correct = FALSE) as losses,
    ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100, 1) as win_rate,
    ROUND(AVG(absolute_error), 2) as mae,
    ROUND(AVG(confidence_score) * 100, 1) as avg_confidence
  FROM base_accuracy
  WHERE recommendation IN ('OVER', 'UNDER')
    AND has_prop_line = TRUE
  GROUP BY game_date

  UNION ALL

  -- Very High Confidence (90%+)
  SELECT
    'very_high_confidence' as subset_id,
    'Very High Confidence (90%+)' as subset_name,
    '90%+ confidence picks only' as subset_description,
    3 as display_order,
    FALSE as is_primary,
    game_date,
    COUNT(*) as picks,
    COUNTIF(prediction_correct = TRUE) as wins,
    COUNTIF(prediction_correct = FALSE) as losses,
    ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100, 1) as win_rate,
    ROUND(AVG(absolute_error), 2) as mae,
    ROUND(AVG(confidence_score) * 100, 1) as avg_confidence
  FROM base_accuracy
  WHERE recommendation IN ('OVER', 'UNDER')
    AND has_prop_line = TRUE
    AND confidence_score >= 0.90
  GROUP BY game_date

  UNION ALL

  -- Problem Tier (88-90%) - Shadow tracking
  SELECT
    'problem_tier_88_90' as subset_id,
    'Problem Tier (88-90%) - Shadow' as subset_name,
    '88-90% confidence picks (known to underperform)' as subset_description,
    10 as display_order,
    FALSE as is_primary,
    game_date,
    COUNT(*) as picks,
    COUNTIF(prediction_correct = TRUE) as wins,
    COUNTIF(prediction_correct = FALSE) as losses,
    ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100, 1) as win_rate,
    ROUND(AVG(absolute_error), 2) as mae,
    ROUND(AVG(confidence_score) * 100, 1) as avg_confidence
  FROM base_accuracy
  WHERE recommendation IN ('OVER', 'UNDER')
    AND has_prop_line = TRUE
    AND confidence_score >= 0.88 AND confidence_score < 0.90
  GROUP BY game_date

  UNION ALL

  -- OVER picks only
  SELECT
    'over_picks_only' as subset_id,
    'OVER Picks Only' as subset_name,
    'OVER picks only (filtered)' as subset_description,
    20 as display_order,
    FALSE as is_primary,
    game_date,
    COUNT(*) as picks,
    COUNTIF(prediction_correct = TRUE) as wins,
    COUNTIF(prediction_correct = FALSE) as losses,
    ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100, 1) as win_rate,
    ROUND(AVG(absolute_error), 2) as mae,
    ROUND(AVG(confidence_score) * 100, 1) as avg_confidence
  FROM base_accuracy
  WHERE recommendation = 'OVER'
    AND has_prop_line = TRUE
    AND NOT (confidence_score >= 0.88 AND confidence_score < 0.90)
  GROUP BY game_date

  UNION ALL

  -- UNDER picks only
  SELECT
    'under_picks_only' as subset_id,
    'UNDER Picks Only' as subset_name,
    'UNDER picks only (filtered)' as subset_description,
    21 as display_order,
    FALSE as is_primary,
    game_date,
    COUNT(*) as picks,
    COUNTIF(prediction_correct = TRUE) as wins,
    COUNTIF(prediction_correct = FALSE) as losses,
    ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100, 1) as win_rate,
    ROUND(AVG(absolute_error), 2) as mae,
    ROUND(AVG(confidence_score) * 100, 1) as avg_confidence
  FROM base_accuracy
  WHERE recommendation = 'UNDER'
    AND has_prop_line = TRUE
    AND NOT (confidence_score >= 0.88 AND confidence_score < 0.90)
  GROUP BY game_date
)

SELECT * FROM subset_metrics;

-- ============================================================================
-- Summary View: Aggregated subset performance (all time)
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.v_subset_performance_summary` AS
SELECT
  subset_id,
  subset_name,
  subset_description,
  display_order,
  is_primary,
  MIN(game_date) as first_date,
  MAX(game_date) as last_date,
  COUNT(DISTINCT game_date) as days,
  SUM(picks) as total_picks,
  SUM(wins) as total_wins,
  SUM(losses) as total_losses,
  ROUND(SAFE_DIVIDE(SUM(wins), SUM(picks)) * 100, 1) as overall_win_rate,
  ROUND(AVG(mae), 2) as avg_mae,
  ROUND(AVG(avg_confidence), 1) as avg_confidence
FROM `nba-props-platform.nba_predictions.v_subset_performance`
GROUP BY subset_id, subset_name, subset_description, display_order, is_primary
ORDER BY display_order;
