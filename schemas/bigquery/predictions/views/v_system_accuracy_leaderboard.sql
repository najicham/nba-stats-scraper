-- Path: schemas/bigquery/predictions/views/v_system_accuracy_leaderboard.sql
-- ============================================================================
-- View: system_accuracy_leaderboard
-- Purpose: Rank systems by accuracy (last 30 days)
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.system_accuracy_leaderboard` AS
SELECT 
  s.system_name,
  s.system_type,
  s.is_champion,
  COUNT(*) as total_predictions,
  AVG(CASE WHEN r.prediction_correct THEN 1.0 ELSE 0.0 END) as accuracy,
  AVG(r.prediction_error) as avg_error,
  AVG(r.confidence_score) as avg_confidence,
  AVG(CASE WHEN r.within_3_points THEN 1.0 ELSE 0.0 END) as within_3_rate,
  AVG(CASE WHEN r.within_5_points THEN 1.0 ELSE 0.0 END) as within_5_rate,
  AVG(CASE 
    WHEN r.confidence_score >= 85 AND r.prediction_correct THEN 1.0 
    WHEN r.confidence_score >= 85 THEN 0.0 
    ELSE NULL 
  END) as high_conf_accuracy
FROM `nba-props-platform.nba_predictions.prediction_results` r
JOIN `nba-props-platform.nba_predictions.prediction_systems` s 
  ON r.system_id = s.system_id
WHERE r.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY s.system_name, s.system_type, s.is_champion
HAVING total_predictions >= 30
ORDER BY accuracy DESC;
