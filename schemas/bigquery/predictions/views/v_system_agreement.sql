-- Path: schemas/bigquery/predictions/views/v_system_agreement.sql
-- ============================================================================
-- View: system_agreement
-- Purpose: Analyze agreement/disagreement across all systems
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.v_system_agreement` AS
WITH system_predictions AS (
  SELECT 
    player_lookup,
    game_date,
    game_id,
    COUNT(DISTINCT system_id) as system_count,
    AVG(predicted_points) as avg_prediction,
    STDDEV(predicted_points) as prediction_std,
    MIN(predicted_points) as min_prediction,
    MAX(predicted_points) as max_prediction,
    MAX(predicted_points) - MIN(predicted_points) as prediction_range
  FROM `nba-props-platform.nba_predictions.player_prop_predictions`
  WHERE is_active = TRUE
  GROUP BY player_lookup, game_date, game_id
)
SELECT 
  *,
  CASE 
    WHEN prediction_range <= 2 THEN 'HIGH_AGREEMENT'
    WHEN prediction_range <= 4 THEN 'MODERATE_AGREEMENT'
    WHEN prediction_range <= 6 THEN 'LOW_AGREEMENT'
    ELSE 'VERY_LOW_AGREEMENT'
  END as agreement_category,
  100 * (1 - LEAST(1.0, prediction_std / NULLIF(avg_prediction, 0))) as agreement_score
FROM system_predictions;
