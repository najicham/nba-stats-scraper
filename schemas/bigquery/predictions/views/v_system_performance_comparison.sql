-- Path: schemas/bigquery/predictions/views/v_system_performance_comparison.sql
-- ============================================================================
-- View: system_performance_comparison
-- Purpose: Comprehensive system performance comparison with recent trends
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_predictions.v_system_performance_comparison` AS
SELECT 
  s.system_id,
  s.system_name,
  s.system_category,
  s.active,
  s.is_champion,
  
  COUNT(*) as total_predictions,
  AVG(CAST(r.prediction_correct AS INT64)) as accuracy,
  AVG(r.prediction_error) as avg_error,
  STDDEV(r.prediction_error) as std_error,
  
  AVG(CASE WHEN r.confidence_score >= 85 THEN CAST(r.prediction_correct AS INT64) ELSE NULL END) as high_conf_accuracy,
  AVG(CASE WHEN r.confidence_score < 70 THEN CAST(r.prediction_correct AS INT64) ELSE NULL END) as low_conf_accuracy,
  
  s.expected_latency_ms as avg_latency_ms,
  s.last_prediction_at,
  s.last_7_days_accuracy,
  s.last_30_days_accuracy
  
FROM `nba-props-platform.nba_predictions.prediction_systems` s
LEFT JOIN `nba-props-platform.nba_predictions.player_prop_predictions` p 
  ON s.system_id = p.system_id
LEFT JOIN `nba-props-platform.nba_predictions.prediction_results` r
  ON p.prediction_id = r.prediction_id
WHERE r.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY s.system_id, s.system_name, s.system_category, s.active, s.is_champion,
         s.expected_latency_ms, s.last_prediction_at, s.last_7_days_accuracy, s.last_30_days_accuracy
ORDER BY accuracy DESC;
