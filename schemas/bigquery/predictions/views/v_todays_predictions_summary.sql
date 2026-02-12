-- @quality-filter: exempt
-- Reason: Daily summary view, shows all predictions for pipeline health monitoring

-- Path: schemas/bigquery/predictions/views/v_todays_predictions_summary.sql
-- ============================================================================
-- View: todays_predictions_summary
-- Purpose: Today's predictions with champion system highlighted
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.todays_predictions_summary` AS
SELECT 
  p.player_lookup,
  p.game_id,
  s.system_name,
  s.is_champion,
  p.predicted_points,
  p.confidence_score,
  p.recommendation,
  p.current_points_line,
  p.line_margin,
  p.similar_games_count,
  p.key_factors
FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
JOIN `nba-props-platform.nba_predictions.prediction_systems` s 
  ON p.system_id = s.system_id
WHERE p.game_date = CURRENT_DATE()
  AND p.is_active = TRUE
  AND s.active = TRUE
ORDER BY s.is_champion DESC, p.confidence_score DESC;
