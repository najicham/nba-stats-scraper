-- @quality-filter: exempt
-- Reason: Model comparison view for today, shows all predictions for analysis

-- Path: schemas/bigquery/predictions/views/v_system_comparison_today.sql
-- ============================================================================
-- View: system_comparison_today
-- Purpose: Compare all systems for today's predictions
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.system_comparison_today` AS
SELECT 
  s.system_name,
  s.system_type,
  s.is_champion,
  COUNT(*) as predictions_made,
  AVG(p.confidence_score) as avg_confidence,
  AVG(p.predicted_points) as avg_predicted_points,
  SUM(CASE WHEN p.recommendation = 'OVER' THEN 1 ELSE 0 END) as over_count,
  SUM(CASE WHEN p.recommendation = 'UNDER' THEN 1 ELSE 0 END) as under_count,
  SUM(CASE WHEN p.recommendation = 'PASS' THEN 1 ELSE 0 END) as pass_count
FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
JOIN `nba-props-platform.nba_predictions.prediction_systems` s 
  ON p.system_id = s.system_id
WHERE p.game_date = CURRENT_DATE()
  AND p.is_active = TRUE
  AND s.active = TRUE
GROUP BY s.system_name, s.system_type, s.is_champion
ORDER BY s.is_champion DESC, predictions_made DESC;
