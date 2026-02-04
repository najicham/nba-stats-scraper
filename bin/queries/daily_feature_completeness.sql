-- Daily Feature Store Completeness Check
-- Run after ml_feature_store processor completes
-- Purpose: Monitor schema consistency and data quality trends

SELECT
  game_date,
  COUNT(*) as total_records,
  ROUND(100.0 * COUNTIF(feature_count = 37) / COUNT(*), 1) as pct_37_features,
  ROUND(100.0 * COUNTIF(feature_quality_score >= 70) / COUNT(*), 1) as pct_quality_ok,
  ROUND(100.0 * COUNTIF(features[OFFSET(33)] IS NOT NULL) / COUNT(*), 1) as pct_has_trajectory,

  -- Alert flags
  CASE
    WHEN COUNTIF(feature_count = 37) < COUNT(*) * 0.95 THEN 'SCHEMA_INCOMPLETE'
    WHEN COUNTIF(feature_quality_score >= 70) < COUNT(*) * 0.70 THEN 'LOW_QUALITY'
    ELSE 'OK'
  END as alert_status

FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC
